"""A thin wrapper around the Anthropic Messages API that records tokens and cost per call.

Anything with a compatible `create(**kwargs)` method can stand in for Claude, which is how the
tests run the whole graph without an API key.
"""
from __future__ import annotations

import json
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
        self._no_forced_tools: set[str] = set()  # models that reject tool_choice "tool"/"any"

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
            if tool_choice.get("type") in ("tool", "any") and model in self._no_forced_tools:
                tool_choice = {"type": "auto"}
            kwargs["tool_choice"] = tool_choice
        start = time.perf_counter()
        try:
            response = self.client.create(**kwargs)
        except Exception as e:
            # Some models (e.g. Claude Sonnet 5.5) do not allow forcing a specific tool. Fall back to
            # letting the model choose; `structured` tells it which tool to call and checks the result.
            message = str(e)
            if "tool_choice" in message and "not supported" in message and \
                    kwargs.get("tool_choice", {}).get("type") in ("tool", "any"):
                self._no_forced_tools.add(model)
                kwargs["tool_choice"] = {"type": "auto"}
                response = self.client.create(**kwargs)
            else:
                raise
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


class StructuredOutputError(RuntimeError):
    pass


def assistant_blocks(response: Any) -> list[dict]:
    """Assistant content as plain dicts, safe to send back to the API. Thinking blocks are kept,
    because models that think must see their own thinking again when a tool result comes back."""
    out = []
    for b in response.content:
        if b.type == "thinking":
            out.append({"type": "thinking", "thinking": b.thinking, "signature": b.signature})
        elif b.type == "redacted_thinking":
            out.append({"type": "redacted_thinking", "data": b.data})
        elif b.type == "text":
            out.append({"type": "text", "text": b.text})
        elif b.type == "tool_use":
            out.append({"type": "tool_use", "id": b.id, "name": b.name, "input": dict(b.input)})
    return out


def _coerce(data: dict, schema: dict) -> dict:
    """Repair the two shapes models most often get wrong: fields nested one level too deep,
    and arrays sent as JSON strings."""
    required = schema.get("required", [])
    if required and not any(k in data for k in required) and len(data) == 1:
        inner = next(iter(data.values()))
        if isinstance(inner, dict):
            data = inner
    for key, spec in schema.get("properties", {}).items():
        value = data.get(key)
        if spec.get("type") == "array" and isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    data[key] = parsed
            except json.JSONDecodeError:
                pass
    return data


def structured(llm: "LLM", step: str, model: str, system: str, messages: list[dict], tool: dict,
               max_tokens: int) -> dict:
    """Force Claude to call `tool` and return its validated input. On a malformed answer, show the model
    what was wrong and retry once with more room; then fail with a clear explanation."""
    messages = list(messages)
    schema = tool["input_schema"]
    system = f"{system}\n\nRespond only by calling the {tool['name']} tool."
    for attempt in range(2):
        resp = llm.call(step, model, system, messages, max_tokens=max_tokens, tools=[tool],
                        tool_choice={"type": "tool", "name": tool["name"]})
        block = next((b for b in resp.content if b.type == "tool_use" and b.name == tool["name"]), None)
        data = _coerce(dict(block.input), schema) if block else {}
        missing = [k for k in schema.get("required", []) if k not in data]
        stop = getattr(resp, "stop_reason", None)
        if block and not missing and stop != "max_tokens":
            return data
        problem = ("ran out of output tokens before finishing" if stop == "max_tokens"
                   else f"did not call {tool['name']}" if not block
                   else f"left out required fields: {', '.join(missing)}")
        if attempt == 0:
            if not block:
                messages += [{"role": "assistant", "content": assistant_blocks(resp) or
                              [{"type": "text", "text": "(no answer)"}]},
                             {"role": "user", "content": f"Call the {tool['name']} tool now with every required "
                                                         f"field: {', '.join(schema.get('required', []))}."}]
            else:
                messages += [{"role": "assistant", "content": assistant_blocks(resp)},
                             {"role": "user", "content": [{
                                 "type": "tool_result", "tool_use_id": block.id, "is_error": True,
                                 "content": f"That call {problem}. Call {tool['name']} again with every "
                                            f"required field: {', '.join(schema.get('required', []))}."}]}]
            max_tokens *= 2
            continue
        raise StructuredOutputError(
            f"{step}: the model {problem} (stop_reason={stop}). It returned: {json.dumps(data)[:500]}")
    raise AssertionError("unreachable")


def text_of(response: Any) -> str:
    return "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", None) == "text")
