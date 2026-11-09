"""Engine clients behind one interface.

Every engine in the study is reached through `Engine.chat`. Local models run on Ollama; hosted
models (OpenAI-compatible endpoints, and Claude through the Anthropic SDK) plug in behind the same
interface when keys are available.
"""

from __future__ import annotations

import os
import time
from functools import cache
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

import anthropic
import httpx

# Conservative chars-per-token (mistral tokenizes ~10% denser than llama); guards against silent truncation.
CHARS_PER_TOKEN = 3.2


class ContextOverflow(RuntimeError):
    """Raised when a prompt would not fit the engine's context window."""


@dataclass
class ChatResult:
    text: str
    tool_calls: list[dict[str, Any]]
    prompt_tokens: int
    completion_tokens: int
    seconds: float
    raw: dict[str, Any] = field(repr=False)
    # Extra keys for the assistant message that replays this reply in a tool loop (Claude needs
    # its own content blocks back, thinking included).
    replay: dict[str, Any] = field(default_factory=dict, repr=False)


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    return int(sum(len(str(m.get("content", ""))) for m in messages) / CHARS_PER_TOKEN)


def api_key(var: str) -> str:
    """The key from the environment, else from the repo's git-ignored .env file."""
    if var not in os.environ:
        env = Path(__file__).resolve().parents[2] / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                k, _, v = line.partition("=")
                if k.strip() == var:
                    os.environ[var] = v.strip().strip('"')
    return os.environ[var]


# USD per million tokens: input, output, cache write (5-minute TTL), cache read.
CLAUDE_PRICES = {
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.20),
    "claude-opus-5-5": (4.00, 20.00, 5.00, 0.20),
}


def _closed(schema: Any) -> Any:
    """A copy of a JSON Schema with every object closed (additionalProperties: false), which
    Anthropic structured outputs require. Objects already declare every key the pipeline reads."""
    if isinstance(schema, dict):
        out = {k: _closed(v) for k, v in schema.items()}
        if out.get("type") == "object":
            out.setdefault("additionalProperties", False)
        return out
    if isinstance(schema, list):
        return [_closed(v) for v in schema]
    return schema


@cache
def _anthropic_client(var: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key(var), max_retries=8)


def _claude_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """OpenAI/Ollama-style messages as an Anthropic system prompt and message list. Tool results
    carry no call id in the pipeline, so they are matched to the preceding calls in order."""
    system, out, pending = [], [], []
    for m in messages:
        role = m["role"]
        if role == "system":
            system.append(m["content"])
        elif role == "user":
            out.append({"role": "user", "content": m["content"]})
        elif role == "assistant":
            calls = m.get("tool_calls") or []
            blocks = m.get("blocks")
            if blocks is None:
                blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
                blocks += [{"type": "tool_use", "id": tc["id"], "name": tc["function"]["name"],
                            "input": tc["function"]["arguments"]} for tc in calls]
            out.append({"role": "assistant", "content": blocks})
            pending = [tc["id"] for tc in calls]
        elif role == "tool":
            result = {"type": "tool_result", "tool_use_id": pending.pop(0),
                      "content": m["content"]}
            if out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(result)
            else:
                out.append({"role": "user", "content": [result]})
        else:
            raise ValueError(f"unknown role {role}")
    return "\n\n".join(system), out


@dataclass
class Engine:
    """A chat model at a pinned version. `family` is used to keep the judge out of engine families."""

    name: str
    model: str
    family: str
    num_ctx: int = 32768
    provider: str = "ollama"
    base_url: str = "http://localhost:11434"
    temperature: float = 0.0
    seed: int = 7
    timeout: float = 1200.0
    api_key_env: str = "OPENAI_API_KEY"
    # Hosted APIs differ in what they accept: current Claude and GPT models on OpenRouter reject
    # temperature and seed (routing then finds no endpoint), and Gemini rejects seed. Those
    # engines run without them; their outputs are cached and released instead.
    send_temperature: bool = True
    send_seed: bool = True
    # Claude only. Local engines answer without reasoning, so thinking is off where the model
    # allows it. Where it can't be (Opus 5.5), or still runs between tool calls (Sonnet 5.5),
    # effort is low and `thinking_tokens` is added to every reply cap, so the pipeline's caps
    # bound the answer rather than the thinking.
    thinking: dict[str, Any] | None = None
    effort: str = "low"
    thinking_tokens: int = 0

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        use_tools: bool = True,
    ) -> ChatResult:
        """`use_tools=False` asks for an answer without further tool calls. Claude needs the
        tool definitions while its history holds tool calls, so it gets them with tool use off;
        other providers just get no tools."""
        # Ollama truncates over-long prompts without an error, which would quietly handicap the
        # raw-transcript baseline. Refuse anything that might not fit, with headroom for the reply.
        if estimate_tokens(messages) > 0.85 * self.num_ctx:
            raise ContextOverflow(
                f"{self.name}: ~{estimate_tokens(messages)} tokens exceeds 85% of {self.num_ctx}"
            )
        if self.provider == "anthropic":
            return self._anthropic(messages, tools, schema, max_tokens, use_tools)
        if not use_tools:
            tools = None
        if self.provider == "ollama":
            return self._ollama(messages, tools, schema, max_tokens)
        if self.provider == "openai":
            return self._openai(messages, tools, schema, max_tokens)
        raise ValueError(f"unknown provider {self.provider}")

    def _ollama(self, messages, tools, schema, max_tokens) -> ChatResult:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"num_ctx": self.num_ctx, "temperature": self.temperature, "seed": self.seed},
        }
        if tools:
            body["tools"] = tools
        if schema:
            body["format"] = schema
        if max_tokens:
            body["options"]["num_predict"] = max_tokens
        t0 = time.monotonic()
        r = httpx.post(f"{self.base_url}/api/chat", json=body, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        msg = data.get("message", {})
        return ChatResult(
            text=msg.get("content", ""),
            tool_calls=msg.get("tool_calls") or [],
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
            seconds=time.monotonic() - t0,
            raw=data,
        )

    def _openai(self, messages, tools, schema, max_tokens) -> ChatResult:
        body: dict[str, Any] = {"model": self.model, "messages": messages}
        if self.send_temperature:
            body["temperature"] = self.temperature
        if self.send_seed:
            body["seed"] = self.seed
        if max_tokens:
            body["max_tokens"] = max_tokens
        if tools:
            body["tools"] = tools
        if schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "out", "schema": schema},
            }
        if "openrouter.ai" in self.base_url:
            # Route only to providers that honour every parameter (above all response_format).
            body["provider"] = {"require_parameters": True}
        t0 = time.monotonic()
        for attempt in range(10):
            # Free tiers rate-limit (429), shed load (503) and stall; wait and retry the request.
            r = None
            try:
                r = httpx.post(
                    f"{self.base_url}/chat/completions",
                    json=body,
                    headers={"Authorization": f"Bearer {api_key(self.api_key_env)}"},
                    timeout=self.timeout,
                )
            except httpx.TimeoutException:
                if attempt == 9:
                    raise
            else:
                if r.status_code not in (429, 500, 503) or attempt == 9:
                    break
            wait = r.headers.get("retry-after") if r is not None else None
            time.sleep(min(300.0, float(wait or 10 * 2 ** attempt)))
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"{self.name}: {data['error']}")
        msg = data["choices"][0]["message"]
        usage = data.get("usage", {})
        return ChatResult(
            text=msg.get("content") or "",
            tool_calls=msg.get("tool_calls") or [],
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            seconds=time.monotonic() - t0,
            raw=data,
        )

    def _anthropic(self, messages, tools, schema, max_tokens, use_tools=True) -> ChatResult:
        system, msgs = _claude_messages(messages)
        kw: dict[str, Any] = {
            "model": self.model,
            "max_tokens": (max_tokens or 16000) + self.thinking_tokens,
            "messages": msgs,
            "output_config": {"effort": self.effort},
        }
        if schema:
            # Same role as Ollama's `format`: the registry schema constrains the decoder.
            kw["output_config"]["format"] = {"type": "json_schema", "schema": _closed(schema)}
        if system:
            # The context is the stable prefix of every probe in a condition: cache it.
            kw["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        if self.thinking:
            kw["thinking"] = self.thinking
        if tools:
            kw["tools"] = [{"name": t["function"]["name"],
                            "description": t["function"]["description"],
                            "input_schema": t["function"]["parameters"]} for t in tools]
            if not use_tools:
                kw["tool_choice"] = {"type": "none"}
        t0 = time.monotonic()
        r = _anthropic_client(self.api_key_env).messages.create(**kw)
        data = r.to_dict()
        u = r.usage
        p_in, p_out, p_write, p_read = CLAUDE_PRICES[self.model]
        cache_write = u.cache_creation_input_tokens or 0
        cache_read = u.cache_read_input_tokens or 0
        data["usage"]["cost"] = (u.input_tokens * p_in + u.output_tokens * p_out
                                 + cache_write * p_write + cache_read * p_read) / 1e6
        blocks = [b.to_dict() for b in r.content]
        calls = [{"id": b.id, "function": {"name": b.name, "arguments": b.input}}
                 for b in r.content if b.type == "tool_use"]
        return ChatResult(
            text="".join(b.text for b in r.content if b.type == "text"),
            tool_calls=calls,
            prompt_tokens=u.input_tokens + cache_write + cache_read,
            completion_tokens=u.output_tokens,
            seconds=time.monotonic() - t0,
            raw=data,
            replay={"blocks": blocks} if calls else {},
        )


# Three model families as engines; the judge comes from a fourth family.
ENGINES = {
    "llama": Engine("llama", "llama3.1:8b", family="meta"),
    "mistral": Engine("mistral", "mistral:7b", family="mistral"),
    "qwen": Engine("qwen", "qwen2.5:14b-instruct", family="qwen"),
}
JUDGE = Engine("judge", "phi4:latest", family="microsoft", num_ctx=16384)

# Gemini API free tier (key GEMINI_API_KEY in .env), OpenAI-compatible endpoint. Strong extractor
# and hosted judge at no cost; Google is a family outside the three local engines. Free Gemini
# models allow only 20 requests a day, so `gemma` (open weights, higher free limit) does the work.
GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai"
FREE = {
    "gemini": Engine("gemini", "gemini-3.5-flash", family="google", provider="openai",
                     base_url=GEMINI, num_ctx=200000, api_key_env="GEMINI_API_KEY",
                     timeout=300.0, send_seed=False),
    "gemma": Engine("gemma", "gemma-4-31b-it", family="google", provider="openai",
                    base_url=GEMINI, num_ctx=128000, api_key_env="GEMINI_API_KEY",
                    timeout=300.0, send_seed=False),
}

# Hosted engines through OpenRouter (key OPEN_ROUTER_API_KEY in .env). Not part of the local
# matrix: `sonnet` is the strong extractor (write-in from the local engines' cached dialogues),
# `gpt` the hosted judge, a family distinct from both the extractor and the local engines.
OPENROUTER = "https://openrouter.ai/api/v1"
HOSTED = {
    "sonnet": Engine("sonnet", "anthropic/claude-sonnet-5.5", family="anthropic",
                     provider="openai", base_url=OPENROUTER, num_ctx=200000,
                     api_key_env="OPEN_ROUTER_API_KEY", timeout=300.0,
                     send_temperature=False, send_seed=False),
    "gpt": Engine("gpt", "openai/gpt-6.1-sol", family="openai", provider="openai",
                  base_url=OPENROUTER, num_ctx=200000, api_key_env="OPEN_ROUTER_API_KEY",
                  timeout=300.0, send_temperature=False, send_seed=False),
}

# Claude through the Anthropic API (key CLAUDE_API_KEY in .env), as reader B and, later, strong
# extractor. Outside the local matrix; the judge stays outside the Anthropic family.
CLAUDE = {
    "haiku": Engine("haiku", "claude-haiku-5-5", family="anthropic", provider="anthropic",
                    num_ctx=1000000, api_key_env="CLAUDE_API_KEY", timeout=600.0,
                    thinking={"type": "disabled"}),
    "sonnet": Engine("sonnet", "claude-sonnet-5-5", family="anthropic", provider="anthropic",
                     num_ctx=1000000, api_key_env="CLAUDE_API_KEY", timeout=600.0,
                     thinking={"type": "between_tools"}, thinking_tokens=2048),
    "opus": Engine("opus", "claude-opus-5-5", family="anthropic", provider="anthropic",
                   num_ctx=1000000, api_key_env="CLAUDE_API_KEY", timeout=600.0,
                   thinking_tokens=2048),
}
