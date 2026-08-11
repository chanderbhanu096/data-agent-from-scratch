"""The agent's tools, promoted to library code.

Chapter 04 built these by hand so you'd know exactly what a tool is: a name, a
description, a JSON Schema, and a Python function. That lesson is done. From
chapter 05 on, tools are a solved problem and the chapters are about what you
wrap around them — so they live here instead of being retyped every time.

`execute()` is the security boundary of the whole system. The model asks; this
function decides whether to comply. Chapter 07 adds teeth to it.
"""

from __future__ import annotations

from typing import Any

from dataagent.llm import Tool
from dataagent.warehouse import UnsafeSQL, connect, run_sql, schema_text


def tool_run_sql(sql: str) -> str:
    try:
        return run_sql(sql, row_limit=1000).to_markdown()
    except UnsafeSQL as exc:
        return f"REJECTED: {exc}"
    except Exception as exc:  # noqa: BLE001
        # Returned, not raised. An agent can read this and try again; it cannot
        # read a traceback. This one line is what makes chapter 06 possible.
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


TOOLS: list[Tool] = [
    Tool(
        name="run_sql",
        description=(
            "Run a read-only SELECT query against the taxi warehouse and return the rows. "
            "Use this to answer any question about the data. Only SELECT and WITH are "
            "permitted; anything that writes will be rejected. If the query fails, read "
            "the error, fix the SQL, and call this again."
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
    """Run one tool call. Every failure returns text the model can act on."""
    tool = BY_NAME.get(name)
    if tool is None:
        return f"ERROR: no tool named {name!r}. Available: {', '.join(BY_NAME)}"
    try:
        return tool.handler(**arguments)
    except TypeError as exc:
        return f"ERROR: bad arguments for {name}: {exc}"


def build_system_prompt() -> str:
    """Standing instructions plus the schema and the notes it can't infer."""
    return (
        "You are a data analyst for a NYC taxi warehouse. Answer questions using the "
        "tools. Work in steps: inspect what you need, run SQL, then answer.\n\n"
        f"{schema_text()}\n\n"
        "Facts you cannot get from the schema:\n"
        "- trips.pickup_zone_id and trips.dropoff_zone_id join to zones.zone_id.\n"
        "- payment_type_id is meaningless alone; join payment_types for the name.\n"
        "- borough 'N/A' and 'Unknown' are real values in zones, not nulls.\n"
        "- The data covers January 2024 only.\n"
        "- total_amount already includes tip and tolls.\n\n"
        "Rules:\n"
        "- NEVER write SQL in your reply. SQL goes in the run_sql tool call, nothing\n"
        "  else. If you are about to type ```sql, call the tool instead.\n"
        "- If a query errors, do not explain the fix — call run_sql again with the\n"
        "  corrected query. Explaining is not fixing.\n"
        "- NEVER write a table of results. You cannot compute; only the tool can.\n"
        "  Every number you state must appear in a tool result you actually received.\n"
        "- When a group has very few rows, say so — a mean over 7 trips is not a finding.\n"
        "- Only once a tool has returned the data, reply in one or two sentences of\n"
        "  plain English with the numbers. That reply must contain no SQL."
    )
