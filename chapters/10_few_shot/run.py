"""Chapter 10 — Few-shot examples: teach the model with worked answers.

    python chapters/10_few_shot/run.py

    # benchmark it — the point is the CHEAP tier, so measure it there and on Azure:
    python scripts/run_evals.py --agent=05 --agent=10 --runs=3

Chapter 06 showed that telling a weak model the rules doesn't work. This chapter
shows what does: not rules, but *examples*. Before the model writes SQL, we retrieve
a few solved questions shaped like this one and put them in the prompt — the way you
teach a person a query language, by showing them queries.

The retriever is Chapter 08's BM25, pointed at a library of solved question→SQL pairs
(`evals/examples.yaml`) instead of tables. The examples are deliberately not the eval
questions: they teach the join, the HAVING threshold, the `'Cash'` casing — patterns
that transfer — without ever being the answer. A gain on the held-out set is
generalisation, not memorisation.

This is the lever that makes the *cheap* tier from Chapter 09 worth routing more to:
a 3B model that has seen three worked joins writes the fourth one correctly.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rich.console import Console

from dataagent.cli import run_chapter
from dataagent.fewshot import render_examples, retrieve_examples
from dataagent.tools import TOOLS, build_system_prompt

console = Console()

EXAMPLES_K = 3


def _load_chapter_05():
    path = Path(__file__).resolve().parents[1] / "05_agent_loop" / "run.py"
    spec = importlib.util.spec_from_file_location("agent_05_for_10", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_ch05 = _load_chapter_05()


def build_few_shot_system(question: str, k: int = EXAMPLES_K) -> str:
    """The plain prompt, plus the k most similar solved examples."""
    examples = retrieve_examples(question, k)
    block = render_examples(examples)
    base = build_system_prompt()
    return f"{base}\n\n{block}" if block else base


def run_agent(
    llm,
    question: str,
    *,
    max_steps: int = 12,
    max_usd: float = 0.50,
    k: int = EXAMPLES_K,
    on_step: Any = None,
):
    """Chapter 05's loop, with worked examples retrieved into the system prompt."""
    return _ch05.run_agent(
        llm,
        question,
        tools=TOOLS,
        system=build_few_shot_system(question, k),
        max_steps=max_steps,
        max_usd=max_usd,
        on_step=on_step,
    )


# ── The demo: what gets retrieved for a hard question ─────────────────────────

DEMO_QUESTION = "Which borough has the highest average tip? Ignore boroughs with fewer than 1000 trips."


def main() -> None:
    console.print("[bold cyan]Few-shot — retrieve worked examples, then answer[/bold cyan]\n")
    console.print(f"  [cyan]Q[/cyan] {DEMO_QUESTION}\n")
    examples = retrieve_examples(DEMO_QUESTION, EXAMPLES_K)
    console.rule("[bold]Retrieved examples (patterns, not answers)")
    for ex in examples:
        console.print(f"  [green]~[/green] {ex.question}")
        console.print(f"    [dim]{' '.join(ex.sql.split())[:100]}[/dim]")
    console.print(
        "\n  None of these is the question asked — but between them they show the borough "
        "join, the [bold]HAVING count threshold[/bold], and the ranked average it needs. That "
        "is what goes into the prompt.\n"
        "[yellow]Measure it where it matters — the cheap tier:[/yellow]\n"
        "  [bold]DATAAGENT_PROVIDER=ollama python scripts/run_evals.py --agent=05 --agent=10[/bold]"
    )


if __name__ == "__main__":
    run_chapter(main)
