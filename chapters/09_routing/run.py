"""Chapter 09 — Routing: pay for the frontier model only when you need it.

    python chapters/09_routing/run.py

    # benchmark it (strong tier = your Azure reference; cheap tier = a free local model):
    python scripts/run_evals.py --agent=05 --agent=09 --runs=3

Chapter 08 made a real warehouse affordable in *tokens*. This one makes it
affordable in *dollars*. Most questions are easy — a count, a single filter — and a
free local model answers them correctly. A few are hard — a ranked aggregate with a
threshold — and only the frontier model gets them right. Sending every question to
the expensive model is paying frontier prices for `SELECT count(*)`.

So we route. `dataagent/routing.py` reads the *shape* of the question (never the
data) and picks a tier. The agent is Chapter 05's loop again — the only new thing is
*which model* runs it. The two tiers are yours to choose; the default is the pairing
most people already have: a free local model, and a paid API model for the hard ones.

The cost lever is honest and price-independent: the fraction of questions that ever
reach the paid tier. The accuracy question — does the cheap tier get its share right?
— is the thing you must measure, not assume.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rich.console import Console

from dataagent.cli import run_chapter
from dataagent.config import Settings, load_settings
from dataagent.llm import LLM
from dataagent.routing import route
from dataagent.tools import TOOLS, build_system_prompt

console = Console()


def _load_chapter_05():
    path = Path(__file__).resolve().parents[1] / "05_agent_loop" / "run.py"
    spec = importlib.util.spec_from_file_location("agent_05_for_09", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_ch05 = _load_chapter_05()
_CHEAP_LLM: LLM | None = None


def cheap_settings() -> Settings:
    """The cheap tier — a free local model by default, overridable in .env."""
    base = load_settings()
    provider = os.getenv("ROUTER_CHEAP_PROVIDER", "ollama")
    model = os.getenv("ROUTER_CHEAP_MODEL", "qwen2.5:3b")
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434") if provider == "ollama" else None
    return Settings(
        provider=provider,
        model=model,
        base_url=base_url,
        max_steps=base.max_steps,
        max_usd=base.max_usd,
        sql_row_limit=base.sql_row_limit,
        timeout_s=base.timeout_s,
    )


def _cheap_llm() -> LLM:
    global _CHEAP_LLM
    if _CHEAP_LLM is None:
        _CHEAP_LLM = LLM(cheap_settings())
    return _CHEAP_LLM


def run_agent(
    llm: LLM,
    question: str,
    *,
    max_steps: int = 12,
    max_usd: float = 0.50,
    on_step: Any = None,
):
    """`llm` is the strong tier (the eval's configured model). Cheap tier is built
    here, so routing is invisible to the harness — it just sees an agent."""
    decision = route(question)
    chosen = llm if decision.tier == "strong" else _cheap_llm()
    return _ch05.run_agent(
        chosen,
        question,
        tools=TOOLS,
        system=build_system_prompt(),
        max_steps=max_steps,
        max_usd=max_usd,
        on_step=on_step,
    )


# ── The demo: where every question goes, and why ──────────────────────────────

QUESTIONS = [
    "How many taxi trips are in the warehouse?",
    "What is the average trip distance in miles?",
    "Which pickup zone has the most trips?",
    "Which borough has the highest average tip? Ignore boroughs with fewer than 1000 trips.",
    "How many trips started in Queens?",
    "Which pickup zone has the highest average total fare, among zones with at least 500 trips?",
]


def main() -> None:
    console.print("[bold cyan]Routing — send the easy questions to the cheap model[/bold cyan]\n")
    strong = load_settings()
    cheap = cheap_settings()
    console.print(
        f"  strong tier: [magenta]{strong.provider}/{strong.model}[/magenta]   "
        f"cheap tier: [green]{cheap.provider}/{cheap.model}[/green]\n"
    )

    to_paid = 0
    for q in QUESTIONS:
        d = route(q)
        if d.tier == "strong":
            to_paid += 1
            console.print(f"  [magenta]→ STRONG[/magenta]  {q}")
            console.print(f"           [dim]{'; '.join(d.reasons)}[/dim]")
        else:
            console.print(f"  [green]→ cheap [/green]  {q}")

    console.print(
        f"\n  [bold]{to_paid}/{len(QUESTIONS)}[/bold] reached the paid tier. "
        "The rest were answered for free.\n"
        "[yellow]The cost is that fraction; the risk is a hard question that looks easy.[/yellow] "
        "Measure the trade:\n"
        "  [bold]python scripts/run_evals.py --agent=05 --agent=09 --runs=3[/bold]"
    )


if __name__ == "__main__":
    run_chapter(main)
