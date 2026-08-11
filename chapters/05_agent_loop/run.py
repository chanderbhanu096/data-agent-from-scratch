"""Chapter 05 — The agent loop, from scratch.

    python chapters/05_agent_loop/run.py

Chapter 04 did one round: ask, execute, answer. This is that, wrapped in a
`while`. That single change is what turns a function call into an agent — it can
now take as many steps as the problem needs, look at what came back, and decide
what to do next.

The loop itself is `run_agent()`, and it is about forty lines. Everything else in
this file is bookkeeping so you can watch it work. No framework is involved and
none is needed; read it top to bottom and you will know what LangGraph is doing
under its abstractions.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rich.console import Console

from dataagent.cli import run_chapter
from dataagent.config import load_settings
from dataagent.llm import LLM, Tool, ToolCall, Usage, missing_credentials
from dataagent.tools import TOOLS, build_system_prompt, execute

console = Console()


class StopReason(str, Enum):
    """Why the loop ended. An agent that can't say why it stopped is a black box."""

    ANSWERED = "answered"
    MAX_STEPS = "hit the step limit"
    MAX_BUDGET = "hit the cost limit"


@dataclass
class Step:
    """One iteration, kept for the trace."""

    n: int
    thinking: str
    calls: list[ToolCall] = field(default_factory=list)
    results: list[str] = field(default_factory=list)


FAILURE_PREFIXES = ("SQL ERROR", "ERROR", "REJECTED")

# A model that meant to call a tool but emitted the call as prose instead. Small
# models do this constantly, and it is invisible unless you look for it.
_SQL_IN_PROSE = re.compile(r"```sql|SELECT\s+.+\s+FROM\s+", re.IGNORECASE | re.DOTALL)


@dataclass
class AgentResult:
    answer: str
    steps: list[Step]
    usage: Usage
    stop_reason: StopReason

    @property
    def tool_calls_made(self) -> int:
        return sum(len(s.calls) for s in self.steps)

    @property
    def grounded(self) -> bool:
        """Did *any* tool call actually succeed before it answered?

        The loop stops when the model emits no tool calls. That is not the same
        as the model being finished — it also happens when it gives up and
        writes prose. An ungrounded answer is one where no tool ever returned
        usable data, so every number in it was invented.

        This does not prevent fabrication; nothing here can. It makes it
        *visible*, which is the difference between a wrong answer and a wrong
        answer you know about.
        """
        return any(
            not result.startswith(FAILURE_PREFIXES)
            for step in self.steps
            for result in step.results
        )

    @property
    def wrote_sql_as_prose(self) -> bool:
        """The classic small-model failure: the answer *is* the tool call."""
        return bool(_SQL_IN_PROSE.search(self.answer))


# ── The loop ──────────────────────────────────────────────────────────────────


def run_agent(
    llm: LLM,
    question: str,
    *,
    tools: list[Tool],
    system: str,
    max_steps: int = 12,
    max_usd: float = 0.50,
    on_step: Any = None,
) -> AgentResult:
    """Think → act → observe, until it answers or hits a limit.

    Read the four marked blocks and you have the whole idea. Everything after
    this chapter is a refinement of one of them.
    """
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    steps: list[Step] = []

    for n in range(1, max_steps + 1):
        # ── LIMIT: money. Checked before spending, not after. ─────────────────
        if llm.total.cost_usd > max_usd:
            return AgentResult(
                f"Stopped after ${llm.total.cost_usd:.4f}, over the ${max_usd:.2f} budget.",
                steps,
                llm.total,
                StopReason.MAX_BUDGET,
            )

        # ── 1. THINK ──────────────────────────────────────────────────────────
        reply = llm.chat(messages, system=system, tools=tools, max_tokens=1500)
        step = Step(n=n, thinking=reply.text.strip())

        # ── 2. DONE? No tool calls means it's finished talking. ───────────────
        if not reply.wants_tools:
            steps.append(step)
            if on_step:
                on_step(step)
            return AgentResult(reply.text.strip(), steps, llm.total, StopReason.ANSWERED)

        # The assistant's turn goes back verbatim, tool calls included. Drop it
        # and the model loses track of what it just asked for.
        messages.append(
            {"role": "assistant", "content": reply.text, "tool_calls": reply.tool_calls}
        )

        # ── 3. ACT — our code runs it, never the model. ───────────────────────
        for call in reply.tool_calls:
            result = execute(call.name, call.arguments)
            step.calls.append(call)
            step.results.append(result)

            # ── 4. OBSERVE — the result rejoins the conversation. ─────────────
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

        steps.append(step)
        if on_step:
            on_step(step)

    # ── LIMIT: steps. Without this, a confused agent loops forever. ───────────
    return AgentResult(
        f"Stopped after {max_steps} steps without reaching an answer.",
        steps,
        llm.total,
        StopReason.MAX_STEPS,
    )


# ── Watching it work ──────────────────────────────────────────────────────────


def print_step(step: Step) -> None:
    if step.thinking:
        console.print(f"  [dim]{step.thinking[:200]}[/dim]")
    for call, result in zip(step.calls, step.results, strict=True):
        arg_preview = str(call.arguments)[:150]
        console.print(f"  [magenta]{step.n}. → {call.name}[/magenta]({arg_preview})")
        first_line = result.splitlines()[0] if result else "(empty)"
        marker = "[red]" if result.startswith(("SQL ERROR", "ERROR", "REJECTED")) else "[dim]"
        console.print(f"     {marker}{first_line[:150]}[/]")


QUESTIONS = [
    # Needs two steps: look at the real borough values, then aggregate.
    "Which borough has the highest average tip? Ignore boroughs with under 1000 trips.",
    # The query that died in chapter 03. The loop gets to see the error and retry.
    "Which 5 pickup zones had the highest average fare, with at least 500 trips?",
]


def main() -> None:
    settings = load_settings()
    if problem := missing_credentials(settings):
        console.print(f"[red]{problem}[/red]")
        raise SystemExit(1)

    console.rule("[bold]Chapter 05 — the agent loop")
    console.print(
        f"[dim]{settings.provider}/{settings.model} · "
        f"max {settings.max_steps} steps · budget ${settings.max_usd:.2f}[/dim]"
    )

    system = build_system_prompt()

    for question in QUESTIONS:
        console.print(f"\n[bold cyan]Q[/bold cyan]  {question}")
        llm = LLM(settings)  # fresh cost counter per question

        result = run_agent(
            llm,
            question,
            tools=TOOLS,
            system=system,
            max_steps=settings.max_steps,
            max_usd=settings.max_usd,
            on_step=print_step,
        )

        answered = result.stop_reason is StopReason.ANSWERED
        colour = "green" if answered and result.grounded else "yellow"
        console.print(f"  [bold {colour}]{result.answer[:600]}[/bold {colour}]")
        console.print(
            f"  [dim]{len(result.steps)} steps · {result.tool_calls_made} tool calls · "
            f"{result.usage.input_tokens} in + {result.usage.output_tokens} out · "
            f"stopped: {result.stop_reason.value}[/dim]"
        )

        # The loop said "answered". These say whether to believe it.
        if answered and not result.grounded:
            console.print(
                "  [red]⚠ UNGROUNDED — no tool call ever succeeded, so every number "
                "above was invented.[/red]"
            )
        if result.wrote_sql_as_prose:
            console.print(
                "  [red]⚠ The answer contains SQL. The model meant to call the tool "
                "and typed it out instead.[/red]"
            )

    console.print(
        "\n[yellow]That is an agent.[/yellow] The only structural change from chapter 04 "
        "was `while`.\n"
        "Notice it now recovers from its own SQL errors — by accident, because an error "
        "is just another observation. Chapter 06 makes that deliberate and bounded."
    )


if __name__ == "__main__":
    run_chapter(main)
