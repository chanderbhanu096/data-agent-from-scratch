"""Chapter 02 — Structured output you can actually trust.

    python chapters/02_structured_output/run.py

Chapter 01 gave us prose. Prose is useless to a program. Here we get back a typed
object — and, more importantly, we handle the case where the model gets the shape
wrong, because it will.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pydantic import BaseModel, Field, ValidationError
from rich.console import Console

from dataagent.cli import run_chapter
from dataagent.config import load_settings
from dataagent.llm import LLM, missing_credentials

console = Console()


class QuestionPlan(BaseModel):
    """What we want back. The docstrings become the model's instructions."""

    intent: Literal["aggregate", "filter", "rank", "trend", "unanswerable"] = Field(
        description="The kind of query this question needs"
    )
    tables_needed: list[str] = Field(description="Warehouse tables required to answer it")
    time_filtered: bool = Field(description="True if the question restricts a date range")
    reasoning: str = Field(description="One sentence explaining the classification")


QUESTIONS = [
    "What was the average tip by borough in January?",
    "Which pickup zone had the most trips?",
    "What's the weather like in Berlin?",
]


def extract_json(text: str) -> dict:
    """Pull the JSON object out of a model response.

    Models wrap JSON in prose and ```json fences no matter how firmly you ask
    them not to. Parsing defensively is cheaper than prompting harder.
    """
    text = text.strip()
    if fence := re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL):
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in response: {text[:200]!r}")
    return json.loads(text[start : end + 1])


def plan_question(llm: LLM, question: str, max_attempts: int = 3) -> QuestionPlan:
    """Ask for a plan, validate it, and feed failures back as a repair prompt.

    This retry loop is the actual pattern. Everything a "structured output"
    library does for you is a variation on it, and knowing that means you can
    debug it when it misbehaves.
    """
    schema = json.dumps(QuestionPlan.model_json_schema(), indent=2)
    system = (
        "You classify questions about a NYC taxi warehouse.\n"
        "The warehouse has exactly three tables: trips, zones, payment_types.\n"
        "Reply with a single JSON object matching this schema. No prose, no code fences.\n\n"
        f"{schema}"
    )
    messages = [{"role": "user", "content": question}]

    for attempt in range(1, max_attempts + 1):
        reply = llm.chat(messages, system=system, max_tokens=800)
        try:
            return QuestionPlan.model_validate(extract_json(reply.text))
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            console.print(f"  [yellow]attempt {attempt} invalid:[/yellow] {str(exc)[:110]}")
            if attempt == max_attempts:
                raise
            # Show the model its own broken output and the specific error. A bare
            # "try again" is much less effective than naming what was wrong.
            messages += [
                {"role": "assistant", "content": reply.text},
                {
                    "role": "user",
                    "content": (
                        f"That did not validate against the schema.\n"
                        f"Error: {exc}\n"
                        f"Return only the corrected JSON object."
                    ),
                },
            ]
    raise AssertionError("unreachable")


def main() -> None:
    settings = load_settings()
    if problem := missing_credentials(settings):
        console.print(f"[red]{problem}[/red]")
        raise SystemExit(1)

    console.rule("[bold]Chapter 02 — structured output")
    llm = LLM(settings)

    for question in QUESTIONS:
        console.print(f"\n[bold cyan]Q[/bold cyan]  {question}")
        try:
            plan = plan_question(llm, question)
        except Exception as exc:  # noqa: BLE001 - surfacing the failure is the lesson
            console.print(f"  [red]gave up after retries:[/red] {exc}")
            continue

        console.print(f"  [green]intent[/green]        {plan.intent}")
        console.print(f"  [green]tables[/green]        {plan.tables_needed or '—'}")
        console.print(f"  [green]time filter[/green]   {plan.time_filtered}")
        console.print(f"  [dim]{plan.reasoning}[/dim]")

    console.print(
        f"\n[dim]total: {llm.total.input_tokens} in + {llm.total.output_tokens} out · "
        f"${llm.total.cost_usd:.6f}[/dim]"
    )
    console.print(
        "\n[yellow]The third question is the interesting one.[/yellow] A useful classifier "
        "has to be able to say 'I can't answer this' — an agent that always finds an answer "
        "is an agent that fabricates one."
    )


if __name__ == "__main__":
    run_chapter(main)
