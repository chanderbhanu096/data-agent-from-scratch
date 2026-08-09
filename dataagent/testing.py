"""A scripted stand-in for a real model, for tests only.

Read this before you use it, because there's a line here worth being careful
about.

This is a **test double**: it returns replies you wrote, in order, and records
exactly what it was asked. It exists so the agent's plumbing — the retry loop,
tool dispatch, message threading — can be tested deterministically and in CI,
without an API key and without paying for tokens.

It is NOT a demo mode. No chapter imports it, no `run.py` can reach it, and
nothing it produces is ever shown to a user as a real answer. If you ever find
yourself wiring a canned response into a code path a user can see, you have
built a fake product, not a tested one.

Testing the *logic* with a double and testing the *model* with a real call are
two different jobs. This does the first. Only a real provider does the second.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dataagent.llm import Reply, Tool, Usage


@dataclass
class Call:
    """One recorded invocation, so tests can assert on what was actually sent."""

    messages: list[dict]
    system: str | None
    tools: list[Tool] | None


@dataclass
class ScriptedLLM:
    """Returns `replies` in order. Raises if the code asks for more than exist."""

    replies: list[Reply]
    calls: list[Call] = field(default_factory=list)
    total: Usage = field(default_factory=Usage)
    model: str = "scripted"

    def chat(
        self,
        messages: list[dict],
        *,
        system: str | None = None,
        tools: list[Tool] | None = None,
        max_tokens: int = 4096,
    ) -> Reply:
        # Copy the messages: the caller mutates its own list afterwards, and a
        # test asserting on turn N must see turn N as it was actually sent.
        self.calls.append(Call([dict(m) for m in messages], system, tools))

        if len(self.calls) > len(self.replies):
            raise AssertionError(
                f"Code asked for reply #{len(self.calls)} but only "
                f"{len(self.replies)} were scripted — the loop ran longer than expected."
            )

        reply = self.replies[len(self.calls) - 1]
        self.total = self.total + reply.usage
        return reply

    @property
    def call_count(self) -> int:
        return len(self.calls)
