"""Chapter 12 — Tracing: stop trusting the agent, start reading the receipt.

    python chapters/12_tracing/run.py

Up to now "it worked" has meant: the answer looked right. That is hope, not
evidence. A trace replaces it with a record — every step, every tool call, the
tokens and dollars each one cost, how long it took, and whether a single tool
call ever actually returned data (grounded) or the model just talked.

The loop already produces all of this; chapter 05's Step and Usage were built
for exactly this moment. What was missing was somewhere to *put* it. So this
chapter adds no loop machinery — it hangs a Tracer on the on_step callback the
loop already fires, and writes one JSON line per run you can grep and diff.

ponytail: no new counters in the loop. Per-step cost is a delta of the total
that's already tracked; the whole chapter is a callback plus a file append.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rich.console import Console
from rich.table import Table

from dataagent.cli import run_chapter
from dataagent.config import load_settings
from dataagent.llm import LLM, missing_credentials
from dataagent.tools import TOOLS, build_system_prompt
from dataagent.trace import Tracer, load_jsonl, save_jsonl, trace_record

console = Console()
_TRACE_PATH = Path(__file__).resolve().parent / "traces.jsonl"


def _load_chapter_05():
    path = Path(__file__).resolve().parents[1] / "05_agent_loop" / "run.py"
    spec = importlib.util.spec_from_file_location("agent_05_for_12", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_ch05 = _load_chapter_05()


def traced_run(settings, question: str):
    """Run one question and return (result, tracer) — the answer and its receipt."""
    llm = LLM(settings)
    tracer = Tracer(llm)
    result = _ch05.run_agent(
        llm, question, tools=TOOLS, system=build_system_prompt(), on_step=tracer
    )
    return result, tracer


def _timeline(tracer: Tracer) -> Table:
    t = Table(title="Timeline — one row per loop step", title_style="bold")
    for col in ("step", "tools", "ms", "in", "out", "$"):
        t.add_column(col, justify="right" if col != "tools" else "left")
    for s in tracer.steps:
        t.add_row(
            str(s.n),
            ", ".join(s.tools) or "[dim]—[/dim]",
            f"{s.ms:.0f}",
            str(s.input_tokens),
            str(s.output_tokens),
            f"{s.cost_usd:.5f}",
        )
    return t


def main() -> None:
    settings = load_settings()
    console.print("[bold cyan]Tracing — the run, on the record[/bold cyan]")
    console.print(f"[dim]{settings.provider}/{settings.model}[/dim]\n")

    if missing_credentials(settings):
        console.print("[yellow]Set a provider in .env to record a real trace.[/yellow]")
        return

    question = "What is the average tip amount by payment type? Show the payment type name."
    console.print(f"[cyan]Q[/cyan] {question}\n")

    result, tracer = traced_run(settings, question)

    console.print(_timeline(tracer))
    total = result.usage
    grounded = "[green]yes[/green]" if result.grounded else "[red]no[/red]"
    console.print(
        f"\n  answer: [green]{' '.join(result.answer.split())[:80]}[/green]"
        f"\n  grounded: {grounded}"
        f"  ·  stop: {result.stop_reason.value}"
        f"  ·  {total.input_tokens} in + {total.output_tokens} out"
        f"  ·  ${total.cost_usd:.5f}"
    )

    record = trace_record(
        question, result, tracer, provider=settings.provider, model=settings.model
    )
    save_jsonl(record, _TRACE_PATH)
    console.print(f"\n  [dim]appended to {_TRACE_PATH.name} — {len(load_jsonl(_TRACE_PATH))} run(s) on file[/dim]")
    console.print(
        "  [dim]that file is the point: an answer you can reopen, grep, and diff — "
        "not one you have to trust.[/dim]"
    )


if __name__ == "__main__":
    run_chapter(main)
