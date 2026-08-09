"""The model gateway — the only file in this repo that knows a provider exists.

Everything above this layer speaks one vocabulary: you send `Message`s and
`Tool`s, you get a `Reply` back. Swap Ollama for Claude and nothing else in the
codebase changes. That property is the whole point of a gateway, and it is why
this is the first thing we build.

Three providers are supported:

    ollama     — free, local, no API key. The default so the repo runs for
                 everyone.
    anthropic  — Claude.
    openai     — GPT.

The canonical message shape is OpenAI-flavoured because it is the one most
readers have seen:

    {"role": "user",      "content": "how many trips?"}
    {"role": "assistant", "content": "",  "tool_calls": [ToolCall(...)]}
    {"role": "tool",      "tool_call_id": "abc", "content": "12345"}

`_to_anthropic()` translates it into Anthropic's content-block format. Reading
that function is the fastest way to understand what a "message" really is.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from dataagent.config import Settings

Message = dict[str, Any]


# ── Wire types ────────────────────────────────────────────────────────────────


@dataclass
class ToolCall:
    """The model asking your code to run something. It cannot run it itself."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cost_usd + other.cost_usd,
        )


@dataclass
class Reply:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    stop_reason: str = ""

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


@dataclass
class Tool:
    """A function the model may ask for by name.

    `description` is not documentation — it is the prompt that decides whether
    the model reaches for this tool at all. Chapter 04 measures that directly.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Any = None


# ── Pricing, USD per million tokens ───────────────────────────────────────────
# Local models are free, so the table only covers hosted ones. Update here and
# cost accounting stays correct everywhere.

PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}


def price(model: str, usage_in: int, usage_out: int) -> float:
    rate_in, rate_out = PRICING.get(model, (0.0, 0.0))
    return (usage_in / 1_000_000) * rate_in + (usage_out / 1_000_000) * rate_out


# ── Gateway ───────────────────────────────────────────────────────────────────


class LLM:
    """One `chat()` method. Every chapter in this repo calls it."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.model
        self.total = Usage()

    def chat(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        tools: list[Tool] | None = None,
        max_tokens: int = 4096,
    ) -> Reply:
        provider = self.settings.provider
        if provider == "anthropic":
            reply = self._anthropic(messages, system, tools, max_tokens)
        elif provider == "openai":
            reply = self._openai(messages, system, tools, max_tokens)
        elif provider == "ollama":
            reply = self._ollama(messages, system, tools, max_tokens)
        else:  # pragma: no cover - config.py rejects this first
            raise ValueError(f"unknown provider {provider!r}")
        self.total = self.total + reply.usage
        return reply

    # ── Anthropic ─────────────────────────────────────────────────────────────

    def _anthropic(
        self,
        messages: list[Message],
        system: str | None,
        tools: list[Tool] | None,
        max_tokens: int,
    ) -> Reply:
        from anthropic import Anthropic

        client = Anthropic()
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": _to_anthropic(messages),
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ]

        # Note what is NOT here: temperature, top_p, top_k. Current Claude models
        # reject them outright. Steer with the prompt instead — chapter 03.
        resp = client.messages.create(**kwargs)

        text_parts, calls = [], []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input)))

        usage = Usage(
            resp.usage.input_tokens,
            resp.usage.output_tokens,
            price(self.model, resp.usage.input_tokens, resp.usage.output_tokens),
        )
        return Reply("".join(text_parts), calls, usage, resp.stop_reason or "")

    # ── OpenAI ────────────────────────────────────────────────────────────────

    def _openai(
        self,
        messages: list[Message],
        system: str | None,
        tools: list[Tool] | None,
        max_tokens: int,
    ) -> Reply:
        from openai import OpenAI

        client = OpenAI()
        msgs = list(messages)
        if system:
            msgs = [{"role": "system", "content": system}, *msgs]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": _to_openai(msgs),
        }
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]

        resp = client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        calls = [
            ToolCall(c.id, c.function.name, json.loads(c.function.arguments or "{}"))
            for c in (choice.message.tool_calls or [])
        ]
        usage = Usage(
            resp.usage.prompt_tokens,
            resp.usage.completion_tokens,
            price(self.model, resp.usage.prompt_tokens, resp.usage.completion_tokens),
        )
        return Reply(choice.message.content or "", calls, usage, choice.finish_reason or "")

    # ── Ollama ────────────────────────────────────────────────────────────────

    def _ollama(
        self,
        messages: list[Message],
        system: str | None,
        tools: list[Tool] | None,
        max_tokens: int,
    ) -> Reply:
        msgs = list(messages)
        if system:
            msgs = [{"role": "system", "content": system}, *msgs]

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": _to_openai(msgs),
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]

        base = self.settings.base_url or "http://localhost:11434"
        try:
            r = httpx.post(f"{base}/api/chat", json=payload, timeout=300.0)
            r.raise_for_status()
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Cannot reach Ollama at {base}.\n"
                "  1. Install it:  https://ollama.com\n"
                f"  2. Pull a model:  ollama pull {self.model}\n"
                "  3. Or switch provider in .env (DATAAGENT_PROVIDER=anthropic)"
            ) from exc

        data = r.json()
        msg = data.get("message", {})
        calls = []
        for i, c in enumerate(msg.get("tool_calls") or []):
            fn = c.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                args = json.loads(args or "{}")
            calls.append(ToolCall(f"call_{i}", fn.get("name", ""), args))

        # Local models are free, so cost stays 0.0 — but tokens are still counted
        # because context length is a real constraint even when the money isn't.
        usage = Usage(data.get("prompt_eval_count", 0), data.get("eval_count", 0), 0.0)
        return Reply(msg.get("content", ""), calls, usage, data.get("done_reason", ""))


# ── Format translation ────────────────────────────────────────────────────────


def _to_openai(messages: list[Message]) -> list[dict[str, Any]]:
    """Canonical -> OpenAI. Nearly the identity function; only tool calls differ."""
    out: list[dict[str, Any]] = []
    for m in messages:
        if m["role"] == "assistant" and m.get("tool_calls"):
            out.append(
                {
                    "role": "assistant",
                    "content": m.get("content") or "",
                    "tool_calls": [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                        }
                        for c in m["tool_calls"]
                    ],
                }
            )
        elif m["role"] == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": m["tool_call_id"],
                    "content": str(m["content"]),
                }
            )
        else:
            out.append({"role": m["role"], "content": m.get("content") or ""})
    return out


def _to_anthropic(messages: list[Message]) -> list[dict[str, Any]]:
    """Canonical -> Anthropic content blocks.

    Two differences worth internalising:
      * A tool call is a `tool_use` block inside the assistant's own message,
        not a sibling field beside the text.
      * A tool *result* is a `user` message. The model's turn ended when it
        asked; handing back the answer starts a new user turn.
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m["role"]

        if role == "assistant" and m.get("tool_calls"):
            blocks: list[dict[str, Any]] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for c in m["tool_calls"]:
                blocks.append(
                    {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                )
            out.append({"role": "assistant", "content": blocks})

        elif role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": m["tool_call_id"],
                "content": str(m["content"]),
            }
            if m.get("is_error"):
                block["is_error"] = True
            # Consecutive tool results merge into one user turn — the API wants
            # every result for a turn delivered together.
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})

        else:
            out.append({"role": role, "content": m.get("content") or ""})
    return out


def missing_credentials(settings: Settings) -> str | None:
    """Return a human-readable problem, or None if we're good to go."""
    if settings.provider == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
        return "ANTHROPIC_API_KEY is not set. Add it to .env, or set DATAAGENT_PROVIDER=ollama."
    if settings.provider == "openai" and not os.getenv("OPENAI_API_KEY"):
        return "OPENAI_API_KEY is not set. Add it to .env, or set DATAAGENT_PROVIDER=ollama."
    return None
