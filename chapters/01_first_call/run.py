"""Chapter 01 — Your first LLM call.

    python chapters/01_first_call/run.py

We ask the model a question about our warehouse. It cannot answer, and watching
it fail *correctly* is the point: a language model is a text-in / text-out
function with no access to your data. Everything in this repo is engineering to
close that gap.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rich.console import Console

from dataagent.cli import run_chapter
from dataagent.config import load_settings
from dataagent.llm import LLM, missing_credentials

console = Console()

QUESTION = "How many taxi trips started in Manhattan in January 2024?"


def main() -> None:
    settings = load_settings()
    if problem := missing_credentials(settings):
        console.print(f"[red]{problem}[/red]")
        raise SystemExit(1)

    console.rule("[bold]Chapter 01 — your first LLM call")
    console.print(f"[dim]provider[/dim] {settings.provider}   [dim]model[/dim] {settings.model}\n")

    llm = LLM(settings)

    # A "conversation" is just a list. There is no session on the server — you
    # resend the whole history every single time. That one fact explains most of
    # what agent frameworks spend their code on.
    messages = [{"role": "user", "content": QUESTION}]

    console.print(f"[bold cyan]You[/bold cyan]  {QUESTION}")
    reply = llm.chat(
        messages,
        system="You are a data analyst. Answer in two sentences or fewer.",
    )

    console.print(f"\n[bold green]Model[/bold green]  {reply.text.strip()}\n")

    u = reply.usage
    cost = f"${u.cost_usd:.6f}" if u.cost_usd else "$0 (local model)"
    console.print(
        f"[dim]{u.input_tokens} in + {u.output_tokens} out tokens · {cost} · "
        f"stop_reason={reply.stop_reason}[/dim]"
    )

    console.print(
        "\n[yellow]Notice what just happened.[/yellow] The model either refused, or it "
        "invented a number. It has never seen your warehouse — it cannot count rows in a "
        "database it has no connection to.\n\n"
        "Three things fix this, and they are the next three chapters:\n"
        "  02 — make the output a shape your code can act on\n"
        "  03 — put the schema in front of it, so it can write SQL\n"
        "  04 — give it a tool, so it can run that SQL itself"
    )


if __name__ == "__main__":
    run_chapter(main)
