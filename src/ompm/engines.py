"""Engine clients behind one interface.

Every engine in the study is reached through `Engine.chat`. Local models run on Ollama; hosted
models (OpenAI-compatible endpoints) plug in behind the same interface when keys are available.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

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

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> ChatResult:
        # Ollama truncates over-long prompts without an error, which would quietly handicap the
        # raw-transcript baseline. Refuse anything that might not fit, with headroom for the reply.
        if estimate_tokens(messages) > 0.85 * self.num_ctx:
            raise ContextOverflow(
                f"{self.name}: ~{estimate_tokens(messages)} tokens exceeds 85% of {self.num_ctx}"
            )
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


# Three model families as engines; the judge comes from a fourth family.
ENGINES = {
    "llama": Engine("llama", "llama3.1:8b", family="meta"),
    "mistral": Engine("mistral", "mistral:7b", family="mistral"),
    "qwen": Engine("qwen", "qwen2.5:14b-instruct", family="qwen"),
}
JUDGE = Engine("judge", "phi4:latest", family="microsoft", num_ctx=16384)

# Gemini API free tier (key GEMINI_API_KEY in .env), OpenAI-compatible endpoint. Strong extractor
# and hosted judge at no cost; Google is a family outside the three local engines.
GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai"
FREE = {
    "gemini": Engine("gemini", "gemini-3.5-flash", family="google", provider="openai",
                     base_url=GEMINI, num_ctx=200000, api_key_env="GEMINI_API_KEY",
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
