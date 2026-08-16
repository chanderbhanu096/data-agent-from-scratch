"""Chapter 11 — Conversation: the question stops being self-contained.

    python chapters/11_conversation/run.py

Every question so far arrived whole. Real users don't talk that way. They ask
"how many trips started in Manhattan?", see the answer, and say "and Queens?".
That second turn is not a question a text-to-SQL model can answer — on its own it
means nothing. The agent has to carry the first turn's intent forward.

The move is small and the discipline is large: keep the dialogue, and hand the
model the conversation so far so it can *rewrite* the follow-up into a complete
question before it writes SQL. The loop is still Chapter 05's. What's new is memory
— and the judgement about what's worth remembering (the questions and answers, not
every intermediate tool call, which would bury the thread in its own transcript).
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rich.console import Console

from dataagent.cli import run_chapter
from dataagent.config import load_settings
from dataagent.evals import truth_of, value_in_answer
from dataagent.llm import LLM, missing_credentials
from dataagent.tools import TOOLS, build_system_prompt

console = Console()
_CONV_PATH = Path(__file__).resolve().parents[2] / "evals" / "conversations.yaml"


def _load_chapter_05():
    path = Path(__file__).resolve().parents[1] / "05_agent_loop" / "run.py"
    spec = importlib.util.spec_from_file_location("agent_05_for_11", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_ch05 = _load_chapter_05()


def render_history(turns: list[tuple[str, str]]) -> str:
    """The dialogue so far, framed as context the follow-up resolves against."""
    if not turns:
        return ""
    lines = ["\n\nConversation so far — the next question may refer back to it:"]
    for question, answer in turns:
        lines.append(f'  User asked: "{question}"')
        lines.append(f"  You answered: {answer}")
    lines.append(
        '\nIf the new question is a follow-up ("and for Queens?", "what about those?", '
        '"only the long ones"), first rewrite it into a complete, standalone question using '
        "the conversation above, then answer that."
    )
    return "\n".join(lines)


@dataclass
class Conversation:
    """A running dialogue. Each turn sees the ones before it."""

    llm: LLM
    turns: list[tuple[str, str]] = field(default_factory=list)

    def ask(self, question: str, *, max_steps: int = 12, on_step: Any = None):
        system = build_system_prompt() + render_history(self.turns)
        result = _ch05.run_agent(
            self.llm,
            question,
            tools=TOOLS,
            system=system,
            max_steps=max_steps,
            on_step=on_step,
        )
        self.turns.append((question, result.answer))
        return result


def load_conversations(path: Path | None = None) -> list[dict]:
    return yaml.safe_load((path or _CONV_PATH).read_text())


def bench(settings) -> tuple[int, int]:
    """Score the follow-up turn of each sequence — the one that needs memory."""
    convos = load_conversations()
    correct = 0
    for c in convos:
        conv = Conversation(LLM(settings))
        conv.ask(c["setup"])  # sets context; result ignored
        result = conv.ask(c["followup"])
        truth = truth_of(c["reference_sql"])
        ok = bool(truth) and value_in_answer(result.answer, truth)
        correct += ok
        mark = "[green]✓[/green]" if ok else "[red]✗[/red]"
        console.print(
            f"  {mark} [dim]{c['id']:<18}[/dim] "
            f'"{c["followup"]}" [dim]→ {" ".join(result.answer.split())[:60]}[/dim]'
        )
    return correct, len(convos)


def main() -> None:
    settings = load_settings()
    console.print("[bold cyan]Conversation — carry the thread across turns[/bold cyan]")
    console.print(f"[dim]{settings.provider}/{settings.model}[/dim]\n")

    if missing_credentials(settings):
        console.print("[yellow]Set a provider in .env to run the dialogue.[/yellow]")
        console.print(
            "This chapter needs a model — the follow-ups are resolved by it, not by rules."
        )
        return

    # A live two-turn dialogue, so you can watch the follow-up resolve.
    conv = Conversation(LLM(settings))
    for q in ("How many trips started in Manhattan?", "And how many in Queens?"):
        console.print(f"[cyan]User[/cyan] {q}")
        r = conv.ask(q)
        console.print(f"[green]Agent[/green] {r.answer}\n")

    console.rule("[bold]Follow-up resolution — scored on the turn that needs memory")
    correct, total = bench(settings)
    console.print(f"\n  [bold]{correct}/{total}[/bold] follow-ups resolved correctly.")


if __name__ == "__main__":
    run_chapter(main)
