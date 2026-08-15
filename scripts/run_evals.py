"""Score an agent against the golden question set.

    python scripts/run_evals.py --agent=05
    python scripts/run_evals.py --agent=06 --runs=2
    python scripts/run_evals.py --agent=05 --agent=06        # head to head

This is the number that decides whether a change to the agent was an
improvement or just a different set of mistakes. Everything else in this repo
is an opinion; this is evidence.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from rich.console import Console

from dataagent.config import load_settings
from dataagent.evals import Report, load_cases, score_answer
from dataagent.llm import LLM
from dataagent.tools import TOOLS, build_system_prompt

console = Console()

AGENTS = {
    "05": ("chapters/05_agent_loop/run.py", "the plain loop"),
    "06": ("chapters/06_plan_and_verify/run.py", "plan, verify, repair"),
}


def load_agent(key: str):
    rel, _ = AGENTS[key]
    path = REPO_ROOT / rel
    if not path.exists():
        console.print(f"[red]No agent at {rel}[/red]")
        raise SystemExit(1)
    spec = importlib.util.spec_from_file_location(f"agent_{key}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_one(module, key: str, question: str, settings) -> tuple[str, bool, float]:
    """Returns (answer, grounded, seconds). Both agents expose run_agent()."""
    llm = LLM(settings)
    started = time.monotonic()
    try:
        if key == "06":
            result = module.run_agent(llm, question, max_steps=settings.max_steps)
        else:
            result = module.run_agent(
                llm,
                question,
                tools=TOOLS,
                system=build_system_prompt(),
                max_steps=settings.max_steps,
                max_usd=settings.max_usd,
            )
        return result.answer, result.grounded, time.monotonic() - started
    except Exception as exc:  # noqa: BLE001 - a crash scores as a failure
        return f"CRASHED: {str(exc).splitlines()[0][:100]}", False, time.monotonic() - started


def evaluate(key: str, runs: int, settings) -> Report:
    module = load_agent(key)
    cases = load_cases()
    scores = []

    for case in cases:
        for _ in range(runs):
            answer, grounded, secs = run_one(module, key, case.question, settings)
            score = score_answer(case, answer, grounded, secs)
            scores.append(score)

            mark = "[green]✓[/green]" if score.correct else "[red]✗[/red]"
            trap = " [yellow]TRAP[/yellow]" if score.hit_trap else ""
            console.print(
                f"  {mark}{trap} [dim]{case.id:<36} {secs:>4.0f}s  "
                f"{' '.join(score.answer.split())[:66]}[/dim]"
            )
    return Report(scores, label=key)


def main() -> None:
    keys = [a.split("=")[1] for a in sys.argv[1:] if a.startswith("--agent=")] or ["05"]
    runs = next((int(a.split("=")[1]) for a in sys.argv[1:] if a.startswith("--runs=")), 1)
    model = next((a.split("=")[1] for a in sys.argv[1:] if a.startswith("--model=")), None)

    settings = load_settings()
    if model:
        settings = type(settings)(**{**settings.__dict__, "model": model})

    console.print(
        f"[bold]{len(load_cases())} cases · {runs} run(s) · "
        f"{settings.provider}/{settings.model}[/bold]\n"
    )

    reports = []
    for key in keys:
        console.print(f"[bold cyan]agent {key} — {AGENTS[key][1]}[/bold cyan]")
        reports.append(evaluate(key, runs, settings))
        console.print()

    console.print("[bold]Results[/bold]")
    for r in reports:
        console.print(
            f"  agent {r.label}:  "
            f"[bold]{r.accuracy:.0%}[/bold] correct ({r.correct}/{r.total}) · "
            f"grounded {r.grounded}/{r.total} · traps hit {r.traps_hit}"
        )

    if len(reports) == 2:
        delta = reports[1].accuracy - reports[0].accuracy
        arrow = "improvement" if delta > 0 else ("regression" if delta < 0 else "no change")
        console.print(f"\n  [bold]{delta:+.0%}[/bold] — {arrow}")


if __name__ == "__main__":
    main()
