"""Chapter 03 — Schema as context: the moment it writes real SQL.

    python chapters/03_schema_context/run.py

Same model, same gateway. The only thing that changed is what we put in front of
it. That is the whole lesson: capability you thought was missing was context you
hadn't supplied.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rich.console import Console
from rich.syntax import Syntax

from dataagent.cli import run_chapter
from dataagent.config import load_settings
from dataagent.llm import LLM, missing_credentials
from dataagent.warehouse import UnsafeSQL, run_sql, schema_text

console = Console()

QUESTIONS = [
    "How many trips started in Manhattan?",
    "What is the average tip amount by payment type? Show the payment type name.",
    "Which 5 pickup zones had the highest average fare, with at least 500 trips?",
]

# Notes the schema alone cannot tell it. Every one of these came from a real
# wrong answer — this block IS the accumulated debugging, and writing yours down
# is most of the work of shipping a text-to-SQL system.
DOMAIN_NOTES = """\
Facts about this warehouse:
- trips.pickup_zone_id and trips.dropoff_zone_id join to zones.zone_id.
- payment_type_id is meaningless on its own; join payment_types for the name.
- borough 'N/A' and 'Unknown' are real values in zones — not nulls.
- The data covers January 2024 only.
- Money columns are USD. total_amount already includes tip and tolls.
"""


def build_system_prompt() -> str:
    return (
        "You write DuckDB SQL for a NYC taxi warehouse.\n\n"
        f"{schema_text()}\n\n"
        f"{DOMAIN_NOTES}\n"
        "Rules:\n"
        "- Reply with ONE SELECT query and nothing else. No prose, no explanation.\n"
        "- Never write INSERT, UPDATE, DELETE, DROP or any statement that modifies data.\n"
        "- Always LIMIT results to 100 rows or fewer.\n"
    )


def extract_sql(text: str) -> str:
    """Strip fences and prose down to the query itself."""
    text = text.strip()
    if fence := re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE):
        text = fence.group(1)
    return text.strip().rstrip(";").strip()


def main() -> None:
    settings = load_settings()
    if problem := missing_credentials(settings):
        console.print(f"[red]{problem}[/red]")
        raise SystemExit(1)

    console.rule("[bold]Chapter 03 — schema as context")

    system = build_system_prompt()
    console.print(f"[dim]system prompt: {len(system):,} chars — the schema is most of it[/dim]")

    llm = LLM(settings)

    for question in QUESTIONS:
        console.print(f"\n[bold cyan]Q[/bold cyan]  {question}")

        reply = llm.chat([{"role": "user", "content": question}], system=system, max_tokens=600)
        sql = extract_sql(reply.text)
        console.print(Syntax(sql, "sql", theme="ansi_dark", word_wrap=True))

        try:
            result = run_sql(sql, row_limit=settings.sql_row_limit)
        except UnsafeSQL as exc:
            # Blocked before touching the database. Chapter 07 goes deep on this.
            console.print(f"  [red]blocked by guardrail:[/red] {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - a real, common failure mode
            # The model wrote invalid SQL. Right now that's the end of the road.
            # Chapter 06 hands this error back and lets it repair itself.
            console.print(f"  [red]SQL error:[/red] {str(exc).splitlines()[0]}")
            continue

        console.print(f"[green]{result.to_markdown(8)}[/green]")

    console.print(
        f"\n[dim]total: {llm.total.input_tokens} in + {llm.total.output_tokens} out · "
        f"${llm.total.cost_usd:.6f}[/dim]"
    )
    console.print(
        "\n[yellow]This is not an agent yet.[/yellow] We ask once, we run once. If the SQL "
        "is wrong, nothing recovers — you saw that if any query errored above.\n"
        "Chapter 04 hands the model the database. Chapter 05 lets it try again."
    )


if __name__ == "__main__":
    run_chapter(main)
