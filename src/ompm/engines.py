"""Engine clients behind one interface.

Every engine in the study is reached through `Engine.chat`. Local models run on Ollama; hosted
models (OpenAI-compatible endpoints) plug in behind the same interface when keys are available.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

# Rough chars-per-token for English dialogue; used only to guard against silent truncation.
CHARS_PER_TOKEN = 3.5


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
    timeout: float = 600.0

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
    ) -> ChatResult:
        # Ollama truncates over-long prompts without an error, which would quietly handicap the
        # raw-transcript baseline. Refuse anything that might not fit, with headroom for the reply.
        if estimate_tokens(messages) > 0.85 * self.num_ctx:
            raise ContextOverflow(
                f"{self.name}: ~{estimate_tokens(messages)} tokens exceeds 85% of {self.num_ctx}"
            )
        if self.provider == "ollama":
            return self._ollama(messages, tools, schema)
        if self.provider == "openai":
            return self._openai(messages, tools, schema)
        raise ValueError(f"unknown provider {self.provider}")

    def _ollama(self, messages, tools, schema) -> ChatResult:
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

    def _openai(self, messages, tools, schema) -> ChatResult:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "seed": self.seed,
        }
        if tools:
            body["tools"] = tools
        if schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "out", "schema": schema},
            }
        t0 = time.monotonic()
        r = httpx.post(
            f"{self.base_url}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
            timeout=self.timeout,
        )
        r.raise_for_status()
        data = r.json()
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

# Hosted engines, enabled when keys and budget exist.
HOSTED = {
    "gpt": Engine(
        "gpt", "gpt-4o-mini", family="openai", provider="openai",
        base_url="https://api.openai.com/v1", num_ctx=128000,
    ),
}
