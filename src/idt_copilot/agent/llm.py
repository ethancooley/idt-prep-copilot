"""A thin wrapper around the Anthropic Messages API that records tokens and cost per call.

Anything with a compatible `create(**kwargs)` method can stand in for Claude, which is how the
tests run the whole graph without an API key.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

# USD per million tokens (input, output). Check https://platform.claude.com/docs/en/about-claude/pricing
PRICING = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}


class MessagesClient(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    seconds: float = 0.0
    by_step: dict[str, dict[str, float]] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"llm_calls": self.calls, "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "cost_usd": round(self.cost_usd, 4), "llm_seconds": round(self.seconds, 2), "by_step": self.by_step}


class LLM:
    def __init__(self, client: MessagesClient | None = None):
        if client is None:
            import anthropic
            client = anthropic.Anthropic().messages
        self.client = client
        self.usage = Usage()

    def call(self, step: str, model: str, system: str, messages: list[dict], max_tokens: int = 2000,
             tools: list[dict] | None = None, tool_choice: dict | None = None) -> Any:
        kwargs: dict[str, Any] = {
            "model": model, "max_tokens": max_tokens, "messages": messages,
            # Cache the system prompt: it is identical across participants and calls.
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        }
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
        start = time.perf_counter()
        response = self.client.create(**kwargs)
        elapsed = time.perf_counter() - start
        self._record(step, model, response, elapsed)
        return response

    def _record(self, step: str, model: str, response: Any, elapsed: float) -> None:
        usage = getattr(response, "usage", None)
        tin = getattr(usage, "input_tokens", 0) or 0
        tin += (getattr(usage, "cache_read_input_tokens", 0) or 0) + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        tout = getattr(usage, "output_tokens", 0) or 0
        price_in, price_out = PRICING.get(model, (0.0, 0.0))
        cost = (tin * price_in + tout * price_out) / 1_000_000
        u = self.usage
        u.calls += 1
        u.input_tokens += tin
        u.output_tokens += tout
        u.cost_usd += cost
        u.seconds += elapsed
        s = u.by_step.setdefault(step, {"calls": 0, "cost_usd": 0.0})
        s["calls"] += 1
        s["cost_usd"] = round(s["cost_usd"] + cost, 4)


def tool_input(response: Any, name: str) -> dict:
    """The input of the first tool_use block with this name (used for forced structured output)."""
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == name:
            return dict(block.input)
    raise ValueError(f"Model did not call {name}")


def text_of(response: Any) -> str:
    return "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", None) == "text")
