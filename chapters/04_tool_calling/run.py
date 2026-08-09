"""Chapter 04 — Tool calling: hand it the database.

    python chapters/04_tool_calling/run.py

Until now we ran the SQL. Here the model decides *which* tool to call and with
what arguments — and we execute it. One round only: ask, execute, answer.

Turning that single round into a loop is Chapter 05, and it's about ten lines.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rich.console import Console

from dataagent.cli import run_chapter
from dataagent.config import load_settings
from dataagent.llm import LLM, Tool, missing_credentials
from dataagent.warehouse import UnsafeSQL, connect, run_sql, schema_text

console = Console()


# ── The tools ─────────────────────────────────────────────────────────────────
#
# A tool is three things: a name, a description, and a JSON Schema. The
# description is not documentation — it is the prompt that decides whether the
# model reaches for this tool at all. Treat it as prompt engineering, because
# it is.


def tool_run_sql(sql: str) -> str:
    try:
        return run_sql(sql, row_limit=1000).to_markdown()
    except UnsafeSQL as exc:
        return f"REJECTED: {exc}"
    except Exception as exc:  # noqa: BLE001
        # Errors go back to the model as text, not as a raised exception. That
        # is what makes self-correction possible in chapter 06.
        return f"SQL ERROR: {str(exc).splitlines()[0]}"


def tool_sample_column(table: str, column: str) -> str:
    """Show the model what actually lives in a column before it filters on it."""
    con = connect(read_only=True)
    try:
        rows = con.execute(
            f'SELECT DISTINCT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL LIMIT 15'
        ).fetchall()
        return ", ".join(repr(r[0]) for r in rows) or "(no non-null values)"
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: {str(exc).splitlines()[0]}"
    finally:
        con.close()


TOOLS = [
    Tool(
        name="run_sql",
        description=(
            "Run a read-only SELECT query against the taxi warehouse and return the rows. "
            "Use this to answer any question about the data. Only SELECT and WITH are "
            "permitted; anything that writes will be rejected."
        ),
        parameters={
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "A single DuckDB SELECT statement"}
            },
            "required": ["sql"],
        },
        handler=tool_run_sql,
    ),
    Tool(
        name="sample_column",
        description=(
            "List up to 15 distinct values from one column. Call this BEFORE filtering on "
            "a text column, so you filter on values that actually exist rather than "
            "guessing at their spelling or capitalisation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Table name"},
                "column": {"type": "string", "description": "Column name"},
            },
            "required": ["table", "column"],
        },
        handler=tool_sample_column,
    ),
]

BY_NAME = {t.name: t for t in TOOLS}


def execute(name: str, arguments: dict[str, Any]) -> str:
    """The model asked. Your code decides whether to comply.

    This function is the security boundary of the entire system. Every guardrail
    in chapter 07 lives on this side of it.
    """
    tool = BY_NAME.get(name)
    if tool is None:
        return f"ERROR: no tool named {name!r}. Available: {', '.join(BY_NAME)}"
    try:
        return tool.handler(**arguments)
    except TypeError as exc:
        return f"ERROR: bad arguments for {name}: {exc}"


SYSTEM = (
    "You are a data analyst for a NYC taxi warehouse. Use the tools to answer questions "
    "with real numbers from the database. Never state a figure you did not read from a "
    "tool result.\n\n"
    f"{schema_text()}\n\n"
    "payment_type_id is meaningless alone — join payment_types for the name.\n"
    "The data covers January 2024 only."
)

QUESTION = "Which borough has the highest average tip, and what is it?"


def main() -> None:
    settings = load_settings()
    if problem := missing_credentials(settings):
        console.print(f"[red]{problem}[/red]")
        raise SystemExit(1)

    console.rule("[bold]Chapter 04 — tool calling")
    llm = LLM(settings)
    messages: list[dict[str, Any]] = [{"role": "user", "content": QUESTION}]
    console.print(f"[bold cyan]Q[/bold cyan]  {QUESTION}\n")

    # ── Round 1: the model decides ────────────────────────────────────────────
    reply = llm.chat(messages, system=SYSTEM, tools=TOOLS, max_tokens=1500)

    if not reply.wants_tools:
        console.print(f"[yellow]It answered without a tool:[/yellow] {reply.text}")
        console.print(
            "\n[dim]That's a failure mode worth seeing. Small models often ignore tools "
            "and answer from imagination. Sharpen the tool descriptions, or use a bigger "
            "model.[/dim]"
        )
        return

    messages.append({"role": "assistant", "content": reply.text, "tool_calls": reply.tool_calls})

    # ── We execute. The model never touches the database. ────────────────────
    for call in reply.tool_calls:
        console.print(f"[magenta]→ {call.name}[/magenta]({call.arguments})")
        result = execute(call.name, call.arguments)
        console.print(f"[dim]{result[:400]}[/dim]\n")
        messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

    # ── Round 2: the model reads the results and answers ─────────────────────
    final = llm.chat(messages, system=SYSTEM, tools=TOOLS, max_tokens=1000)

    if final.wants_tools:
        console.print(
            "[yellow]It wants to call another tool.[/yellow] We stop here — this chapter "
            "only does one round.\n"
            "[dim]That unmet request is exactly why Chapter 05 wraps this in a loop.[/dim]"
        )
        for call in final.tool_calls:
            console.print(f"  [dim]would call {call.name}({call.arguments})[/dim]")
    else:
        console.print(f"[bold green]Answer[/bold green]  {final.text.strip()}")

    console.print(
        f"\n[dim]total: {llm.total.input_tokens} in + {llm.total.output_tokens} out · "
        f"${llm.total.cost_usd:.6f}[/dim]"
    )


if __name__ == "__main__":
    run_chapter(main)
