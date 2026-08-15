"""Chapter 08 — Schema retrieval: find the tables before you write the SQL.

    python chapters/08_schema_retrieval/run.py

    # benchmark it (measured on the Azure reference model):
    python scripts/run_evals.py --agent=05 --agent=08 --runs=3

Every chapter so far dumped the *whole* schema into the prompt. That works for a
three-table warehouse and breaks for a real one. Two things go wrong at once when
the catalog is 300 tables:

    1. It doesn't fit. The schema alone can blow the context window before the
       question is even asked.
    2. Even when it fits, it hurts. Burying the two relevant tables among 298
       irrelevant ones makes the model pick the wrong ones — a needle in a haystack
       you built yourself.

So we retrieve. Before writing any SQL, score every table against the question and
keep the few that matter. This chapter's agent is Chapter 05's exact loop — the only
change is the schema it's handed: the *retrieved* subset instead of everything.

The retriever (`dataagent/retrieval.py`) is BM25, from scratch — no embeddings, no
vector store, no network. It is the honest baseline, and the README is explicit about
where lexical matching runs out (it matches schema *words*, not data *values* — ask
about "Manhattan" and it can't know that's a borough). The seam is the point:
retrieve, then prompt. Swap in embeddings and nothing else changes.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rich.console import Console

from dataagent.cli import run_chapter
from dataagent.config import load_settings
from dataagent.llm import LLM, missing_credentials
from dataagent.retrieval import (
    full_catalog,
    render_for_prompt,
    render_schema,
    retrieve,
    warehouse_cards,
)
from dataagent.tools import TOOLS, build_system_prompt

console = Console()

RETRIEVED_K = 6


def _load_chapter_05():
    """The loop lives in Chapter 05; this chapter changes only what feeds it."""
    path = Path(__file__).resolve().parents[1] / "05_agent_loop" / "run.py"
    spec = importlib.util.spec_from_file_location("agent_05_for_08", path)
    module = importlib.util.module_from_spec(spec)
    # Register before exec: dataclasses resolve their module via sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_ch05 = _load_chapter_05()


def run_agent(
    llm: LLM,
    question: str,
    *,
    max_steps: int = 12,
    max_usd: float = 0.50,
    k: int = RETRIEVED_K,
    on_step: Any = None,
):
    """Retrieve the relevant tables, then run Chapter 05's loop over just those."""
    retrieved = retrieve(question, full_catalog(), k)
    system = build_system_prompt(schema=render_for_prompt(retrieved))
    return _ch05.run_agent(
        llm,
        question,
        tools=TOOLS,
        system=system,
        max_steps=max_steps,
        max_usd=max_usd,
        on_step=on_step,
    )


# ── The demo (no model needed — retrieval is the point) ───────────────────────

DEMO_QUESTIONS = [
    "What is the average tip by payment type?",
    "Which pickup zone has the most trips?",
    "How many trips had a total amount over 100 dollars?",
    "How many trips started in Manhattan?",  # the honest miss — see below
]


def show_haystack() -> None:
    catalog = full_catalog()
    real = len(warehouse_cards())
    dumped = render_schema(catalog)
    console.rule("[bold]1. The whole catalog no longer fits")
    console.print(
        f"  {len(catalog)} tables ({real} real, {len(catalog) - real} decoys). "
        f"Dumping all of them is ~[bold]{len(dumped) // 4:,} tokens[/bold] of schema — "
        "before the question."
    )


def show_retrieval() -> None:
    catalog = full_catalog()
    real = {c.name for c in warehouse_cards()}
    console.rule("[bold]2. Retrieve the few that matter")
    for q in DEMO_QUESTIONS:
        picked = retrieve(q, catalog, k=RETRIEVED_K)
        names = [
            f"[green]{c.name}[/green]" if c.name in real else f"[dim]{c.name}[/dim]"
            for c in picked
        ]
        console.print(f"  [cyan]Q[/cyan] {q}")
        console.print(f"     → {', '.join(names) or '[red](nothing scored)[/red]'}")


def show_the_seam() -> None:
    console.rule("[bold]3. The retrieved schema is what the agent sees")
    picked = retrieve(DEMO_QUESTIONS[0], full_catalog(), k=RETRIEVED_K)
    console.print(f"  [dim]{render_for_prompt(picked)[:600]}[/dim]")


def main() -> None:
    console.print("[bold cyan]Schema retrieval — the schema is too big, so fetch the relevant slice[/bold cyan]\n")
    show_haystack()
    show_retrieval()
    show_the_seam()
    console.print(
        "\n[yellow]Notice the last question.[/yellow] 'Manhattan' is a value in a row, not a "
        "word in the schema, so lexical retrieval can miss `zones`. That gap is exactly where "
        "embeddings earn their keep — the seam stays the same. Benchmark it on your model:\n"
        "  [bold]python scripts/run_evals.py --agent=05 --agent=08 --runs=3[/bold]"
    )
    settings = load_settings()
    if missing_credentials(settings):
        console.print("\n[dim](Set a provider in .env to run the agent end to end.)[/dim]")


if __name__ == "__main__":
    run_chapter(main)
