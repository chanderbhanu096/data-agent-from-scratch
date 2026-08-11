"""Run the same questions through several models and score the results.

    python scripts/compare_models.py                      # all installed models
    python scripts/compare_models.py qwen2.5:3b llama3.2:3b

Picking a local model by reputation is guessing. This measures the two things
that actually matter for an agent:

    grounded  — did a tool call succeed, or did it make the answer up?
    correct   — is the expected value present in the answer?

It is a crude ancestor of the eval harness in chapter 19, and it exists because
"which small model can actually call a tool" turned out to be an empirical
question, not a documented one.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import httpx
from rich.console import Console

from dataagent.config import load_settings
from dataagent.llm import LLM
from dataagent.tools import TOOLS, build_system_prompt

console = Console()


def _load_agent():
    path = REPO_ROOT / "chapters" / "05_agent_loop" / "run.py"
    spec = importlib.util.spec_from_file_location("ch05_agent", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ch05 = _load_agent()


@dataclass
class Case:
    question: str
    # Substrings that must appear in the answer. Ground truth computed directly
    # from the warehouse — see the comment on each.
    expect: tuple[str, ...]


CASES = [
    # SELECT count(*) FROM trips t JOIN zones z ON t.pickup_zone_id = z.zone_id
    # WHERE z.borough = 'Manhattan'  ->  257614
    Case("How many trips started in Manhattan?", ("257,614", "257614")),
    # Boroughs with >= 1000 trips, by avg tip: Queens 8.13 wins
    # (Manhattan 2.81, Brooklyn 1.98, Unknown 3.62).
    Case(
        "Which borough has the highest average tip? Ignore boroughs with under 1000 trips.",
        ("Queens",),
    ),
]


def installed_models() -> list[str]:
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=10)
        return sorted(m["name"] for m in r.json().get("models", []))
    except httpx.HTTPError:
        console.print("[red]Ollama is not reachable. Start it with: ollama serve[/red]")
        raise SystemExit(1) from None


def score(model: str, case: Case, system: str) -> dict:
    settings = load_settings()
    settings = type(settings)(**{**settings.__dict__, "provider": "ollama", "model": model})
    llm = LLM(settings)

    started = time.monotonic()
    try:
        result = ch05.run_agent(
            llm, case.question, tools=TOOLS, system=system, max_steps=8, max_usd=1.0
        )
    except Exception as exc:  # noqa: BLE001 - a crash is a result too
        return {
            "ok": False,
            "grounded": False,
            "correct": False,
            "sql_prose": False,
            "steps": 0,
            "secs": time.monotonic() - started,
            "answer": f"CRASHED: {str(exc).splitlines()[0][:80]}",
        }

    answer = result.answer
    return {
        "ok": True,
        "grounded": result.grounded,
        "correct": any(e.lower() in answer.lower() for e in case.expect),
        "sql_prose": result.wrote_sql_as_prose,
        "steps": len(result.steps),
        "secs": time.monotonic() - started,
        "answer": " ".join(answer.split())[:110],
    }


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    runs = next(
        (int(a.split("=")[1]) for a in sys.argv[1:] if a.startswith("--runs=")),
        3,
    )
    models = args or installed_models()
    if not models:
        console.print("[red]No models installed. Try: ollama pull qwen2.5:3b[/red]")
        raise SystemExit(1)

    system = build_system_prompt()
    console.print(f"[bold]{len(models)} models · {len(CASES)} questions · {runs} runs each[/bold]")
    console.print(
        "[dim]Runs are repeated because one run tells you almost nothing — the same "
        "model, question and prompt can pass and fail on consecutive attempts.[/dim]\n"
    )

    # model -> [grounded_count, correct_count, attempts]
    tally: dict[str, list[int]] = {m: [0, 0, 0] for m in models}

    for case in CASES:
        console.print(f"[cyan]Q  {case.question}[/cyan]")
        for model in models:
            outcomes, answers, secs = [], [], []
            for _ in range(runs):
                r = score(model, case, system)
                tally[model][0] += int(r["grounded"])
                tally[model][1] += int(r["correct"])
                tally[model][2] += 1
                outcomes.append(
                    "[green]✓[/green]"
                    if r["correct"]
                    else ("[yellow]~[/yellow]" if r["grounded"] else "[red]✗[/red]")
                )
                answers.append(r["answer"])
                secs.append(r["secs"])

            hits = sum(1 for o in outcomes if "green" in o)
            console.print(
                f"  [bold]{model:<14}[/bold] {''.join(outcomes)}  "
                f"[dim]{hits}/{runs} correct · {sum(secs) / len(secs):.0f}s avg[/dim]"
            )
            for a in dict.fromkeys(answers):  # unique, order preserved
                console.print(f"     [dim]{a}[/dim]")
        console.print()

    console.print("[bold]Totals[/bold]  [dim]✓ correct · ~ grounded but wrong · ✗ ungrounded[/dim]")
    for model, (g, c, n) in sorted(tally.items(), key=lambda kv: (-kv[1][1], -kv[1][0])):
        console.print(
            f"  {model:<24} correct {c}/{n} ({c / n:.0%})   grounded {g}/{n} ({g / n:.0%})"
        )


if __name__ == "__main__":
    main()
