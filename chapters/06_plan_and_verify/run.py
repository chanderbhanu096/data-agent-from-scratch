"""Chapter 06 — Plan, verify, repair.

    python chapters/06_plan_and_verify/run.py

Chapter 05's agent is fluent and unreliable: 35% correct on the golden set. It
drops constraints, then claims it applied them. Telling it not to doesn't work —
chapter 05's prompt already said "every number must come from a tool result",
and it invented numbers anyway.

So this chapter stops asking and starts checking. Three changes:

    1. PLAN     Turn the question into a typed Requirements object before any
                SQL exists. A dropped constraint is now a missing field, not a
                subtlety buried in prose.

    2. VERIFY   The run_sql tool refuses SQL that doesn't implement the plan.
                Asked for "at least 500 trips" and the SQL has no HAVING COUNT?
                Rejected before it reaches the database, with a specific reason.

    3. REPAIR   Rejections and empty results come back as instructions, not
                dead ends. The loop already knew how to recover; now it is told
                exactly what to fix.

The pattern worth taking away: a rule you can check in code is a rule. A rule in
the system prompt is a request.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pydantic import BaseModel, Field, ValidationError
from rich.console import Console

from dataagent.cli import run_chapter
from dataagent.config import load_settings
from dataagent.llm import LLM, Tool, ToolCall, Usage, missing_credentials
from dataagent.tools import tool_sample_column
from dataagent.warehouse import UnsafeSQL, run_sql, schema_text

console = Console()

FAILURE_PREFIXES = ("SQL ERROR", "ERROR", "REJECTED", "CHECK FAILED", "EMPTY RESULT")
_SQL_IN_PROSE = re.compile(r"```sql|SELECT\s+.+\s+FROM\s+", re.IGNORECASE | re.DOTALL)


# ── 1. PLAN ───────────────────────────────────────────────────────────────────


class Requirements(BaseModel):
    """The question, restated as things a query must do.

    Every field here exists because a model dropped it in a real run.
    `min_count` in particular is the single highest-value field in this repo:
    it is the constraint that gets silently ignored, producing an average over
    one row presented as a finding.
    """

    metric: str = Field(description="What is being measured, e.g. 'average tip amount'")
    grouping: str | None = Field(
        default=None, description="Column to group by, e.g. 'borough'. Null if none."
    )
    filters: list[str] = Field(
        default_factory=list, description="Filters in plain English, e.g. 'payment is credit card'"
    )
    min_count: int | None = Field(
        default=None,
        description="Minimum rows per group, if the question says 'at least N' or 'ignore under N'",
    )
    sort: str | None = Field(default=None, description="'highest', 'lowest', or null")
    limit: int | None = Field(default=None, description="How many rows the answer needs")
    answerable: bool = Field(description="False if this warehouse cannot answer the question")
    reason: str = Field(description="One sentence: what the query must do, or why it can't")


PLAN_SYSTEM = """You turn a question about a NYC taxi warehouse into structured requirements.

The warehouse has exactly three tables:
  trips(pickup_at, dropoff_at, trip_distance_miles, pickup_zone_id, dropoff_zone_id,
        payment_type_id, fare_amount, tip_amount, tolls_amount, total_amount)
  zones(zone_id, borough, zone_name, service_zone)
  payment_types(payment_type_id, payment_type)

DEFAULT TO answerable=true. Anything about trips, fares, tips, distances, counts,
payments, zones, boroughs, or specific named places (JFK Airport, LaGuardia, Manhattan,
a named zone) IS answerable — those are all columns above. A specific place name is data
in the `zones` table, not a reason to refuse.

Set answerable=false ONLY when the question needs something genuinely absent: driver
names or earnings, weather, customer or passenger identity, or a date outside January 2024.
When unsure, set answerable=true and let the query decide.

Read the question carefully for minimum-count phrasing — "at least 500 trips",
"ignore boroughs under 1000", "with more than 200" — and put the number in min_count.
Missing it is the most common and most damaging mistake.

Reply with a single JSON object matching the schema. No prose, no code fences."""


def extract_json(text: str) -> dict:
    text = text.strip()
    if fence := re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL):
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in: {text[:150]!r}")
    return json.loads(text[start : end + 1])


def plan(llm: LLM, question: str, attempts: int = 3) -> Requirements:
    schema = json.dumps(Requirements.model_json_schema(), indent=2)
    messages = [{"role": "user", "content": question}]
    system = f"{PLAN_SYSTEM}\n\n{schema}"

    for attempt in range(1, attempts + 1):
        reply = llm.chat(messages, system=system, max_tokens=700)
        try:
            return Requirements.model_validate(extract_json(reply.text))
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            if attempt == attempts:
                # A failed plan is not fatal: fall back to an empty plan and let
                # the agent work unverified rather than refusing to try.
                return Requirements(
                    metric="unknown", answerable=True, reason="planning failed; unverified"
                )
            messages += [
                {"role": "assistant", "content": reply.text},
                {"role": "user", "content": f"That did not validate.\nError: {exc}\nJSON only."},
            ]
    raise AssertionError("unreachable")


# ── 2. VERIFY — the checks that make the plan binding ─────────────────────────

_HAS_HAVING_COUNT = re.compile(r"HAVING\s+.*COUNT\s*\(", re.IGNORECASE | re.DOTALL)
_HAS_GROUP_BY = re.compile(r"\bGROUP\s+BY\b", re.IGNORECASE)
_SELECTS_COUNT = re.compile(r"SELECT\b.*?\bCOUNT\s*\(", re.IGNORECASE | re.DOTALL)
_HAS_LIMIT = re.compile(r"\bLIMIT\b", re.IGNORECASE)

# A *_zone_id or payment_type_id in the SELECT list (before FROM), not inside a
# COUNT/join condition. Catches "SELECT pickup_zone_id, ..." → a numeric answer.
_SELECTS_BARE_ID = re.compile(
    r"SELECT\s+(?:(?!\bFROM\b).)*?\b\w*(?:zone_id|payment_type_id)\b"
    r"(?:(?!\bFROM\b).)*?\bFROM\b",
    re.IGNORECASE | re.DOTALL,
)


def check_sql(sql: str, req: Requirements) -> str | None:
    """Return a repair instruction if the SQL doesn't implement the plan.

    Deliberately shallow. These are not a SQL semantics checker — they are four
    cheap syntactic facts that caught the majority of real failures. Chapter 19
    measures what they miss.
    """
    if req.min_count and not _HAS_HAVING_COUNT.search(sql):
        return (
            f"The question requires at least {req.min_count} rows per group, but your SQL "
            f"has no HAVING clause counting rows. Add: HAVING COUNT(*) >= {req.min_count}"
        )

    if _HAS_GROUP_BY.search(sql) and not _SELECTS_COUNT.search(sql):
        return (
            "Your SQL groups rows but does not select COUNT(*). Add COUNT(*) to the SELECT "
            "list so the number of rows behind each average is visible. An average over "
            "3 rows is not a finding."
        )

    if req.limit and not _HAS_LIMIT.search(sql):
        return f"The question asks for {req.limit} row(s). Add LIMIT {req.limit}."

    # Selecting a bare *_zone_id or payment_type_id means the answer will name a
    # number ("zone 132") instead of a place ("JFK Airport"). Make it join.
    if _SELECTS_BARE_ID.search(sql):
        return (
            "Your SELECT returns a numeric id (a zone_id or payment_type_id). The answer "
            "must name the thing, not its id. Join to zones for zone_name/borough, or to "
            "payment_types for payment_type, and select the name column instead."
        )

    return None


def make_run_sql_tool(req: Requirements, budget: list[int]) -> Tool:
    """A run_sql that enforces the plan before touching the database.

    `budget` is a one-element list used as a mutable counter: after a few
    rejections we let the query through rather than looping forever. A verifier
    that can deadlock the agent is worse than one that gives up.
    """

    def handler(sql: str) -> str:
        if budget[0] > 0 and (problem := check_sql(sql, req)):
            budget[0] -= 1
            return f"CHECK FAILED: {problem}\nRewrite the query and call run_sql again."

        try:
            result = run_sql(sql, row_limit=1000)
        except UnsafeSQL as exc:
            return f"REJECTED: {exc}"
        except Exception as exc:  # noqa: BLE001
            return f"SQL ERROR: {str(exc).splitlines()[0]}"

        if not result.rows:
            # The failure the baseline kept making: 0 rows, and it concluded the
            # data didn't exist rather than that its filter was wrong.
            return (
                "EMPTY RESULT: the query ran but matched no rows. This usually means a "
                "filter value is wrong, not that the data is missing. Use sample_column "
                "to see the real values in the column you filtered on, then try again."
            )
        if len(result.rows) == 1 and all(v is None for v in result.rows[0]):
            # An aggregate over zero matching rows returns one row of NULLs, not
            # zero rows — so the guard above misses it, and the model reads NULL as
            # "no data exists." The cause is the same: a filter that matched nothing
            # (e.g. WHERE zone_name = 'JFK' when it is 'JFK Airport').
            return (
                "EMPTY RESULT: the aggregate came back all NULL, which means it ran over "
                "zero matching rows — your filter matched nothing, the data is not missing. "
                "Use sample_column to see the real values in the column you filtered on, "
                "then try again."
            )
        return result.to_markdown()

    return Tool(
        name="run_sql",
        description=(
            "Run a read-only SELECT against the taxi warehouse. The query is checked "
            "against the agreed requirements before it runs; if it fails a check you get "
            "an explanation and must fix the SQL. Only SELECT and WITH are permitted."
        ),
        parameters={
            "type": "object",
            "properties": {"sql": {"type": "string", "description": "One DuckDB SELECT"}},
            "required": ["sql"],
        },
        handler=handler,
    )


SAMPLE_TOOL = Tool(
    name="sample_column",
    description=(
        "List up to 15 real values from one column. Call this whenever a filter returns "
        "no rows, or before filtering on any text column, so you match values that exist."
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
)


def build_system(req: Requirements) -> str:
    """The plan travels with the prompt, so the model can't forget its own plan."""
    lines = [f"- metric: {req.metric}"]
    if req.grouping:
        lines.append(f"- group by: {req.grouping}")
    for f in req.filters:
        lines.append(f"- filter: {f}")
    if req.min_count:
        lines.append(
            f"- MINIMUM {req.min_count} ROWS PER GROUP — use HAVING COUNT(*) >= {req.min_count}"
        )
    if req.sort:
        lines.append(f"- sort: {req.sort}")
    if req.limit:
        lines.append(f"- limit: {req.limit}")

    return (
        "You are a data analyst for a NYC taxi warehouse. Use the tools to answer.\n\n"
        f"{schema_text()}\n\n"
        "Facts the schema cannot tell you:\n"
        "- trips.pickup_zone_id and trips.dropoff_zone_id join to zones.zone_id.\n"
        "- payment_type_id is meaningless alone; join payment_types for the name.\n"
        "- zone_name holds values like 'JFK Airport'; borough holds 'Manhattan', 'Queens'.\n"
        "- The data covers January 2024 only.\n\n"
        "REQUIREMENTS AGREED FOR THIS QUESTION:\n" + "\n".join(lines) + "\n\n"
        "Rules:\n"
        "- Never write SQL or JSON in your reply. SQL goes in the run_sql tool call.\n"
        "- Never invent numbers or tables of results. Only the tool can compute.\n"
        "- If a query returns no rows, your filter is probably wrong — use sample_column.\n"
        "- If a check fails, fix the SQL and call run_sql again. Do not explain instead.\n"
        "- When a group is backed by few rows, say so.\n"
        "- Final reply: one or two plain sentences with the numbers. No SQL."
    )


# ── The loop ──────────────────────────────────────────────────────────────────


class StopReason(str, Enum):
    ANSWERED = "answered"
    MAX_STEPS = "hit the step limit"
    UNANSWERABLE = "declined — warehouse cannot answer"


@dataclass
class Step:
    n: int
    thinking: str
    calls: list[ToolCall] = field(default_factory=list)
    results: list[str] = field(default_factory=list)


@dataclass
class AgentResult:
    answer: str
    steps: list[Step]
    usage: Usage
    stop_reason: StopReason
    requirements: Requirements | None = None
    checks_failed: int = 0

    @property
    def tool_calls_made(self) -> int:
        return sum(len(s.calls) for s in self.steps)

    @property
    def grounded(self) -> bool:
        if self.stop_reason is StopReason.UNANSWERABLE:
            return True  # declining without querying is the correct behaviour
        return any(not r.startswith(FAILURE_PREFIXES) for s in self.steps for r in s.results)

    @property
    def wrote_sql_as_prose(self) -> bool:
        return bool(_SQL_IN_PROSE.search(self.answer))


def run_agent(
    llm: LLM,
    question: str,
    *,
    max_steps: int = 12,
    max_check_failures: int = 3,
    on_step: Any = None,
) -> AgentResult:
    # ── 1. PLAN ───────────────────────────────────────────────────────────────
    req = plan(llm, question)

    if not req.answerable:
        return AgentResult(
            f"That can't be answered from this warehouse. {req.reason}",
            [],
            llm.total,
            StopReason.UNANSWERABLE,
            req,
        )

    budget = [max_check_failures]
    tools = [make_run_sql_tool(req, budget), SAMPLE_TOOL]
    system = build_system(req)

    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    steps: list[Step] = []

    for n in range(1, max_steps + 1):
        reply = llm.chat(messages, system=system, tools=tools, max_tokens=1200)
        step = Step(n=n, thinking=reply.text.strip())

        if not reply.wants_tools:
            steps.append(step)
            if on_step:
                on_step(step)
            return AgentResult(
                reply.text.strip(),
                steps,
                llm.total,
                StopReason.ANSWERED,
                req,
                max_check_failures - budget[0],
            )

        messages.append(
            {"role": "assistant", "content": reply.text, "tool_calls": reply.tool_calls}
        )

        for call in reply.tool_calls:
            handler = next((t.handler for t in tools if t.name == call.name), None)
            if handler is None:
                result = f"ERROR: no tool named {call.name!r}"
            else:
                try:
                    result = handler(**call.arguments)
                except TypeError as exc:
                    result = f"ERROR: bad arguments for {call.name}: {exc}"

            step.calls.append(call)
            step.results.append(result)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

        steps.append(step)
        if on_step:
            on_step(step)

    return AgentResult(
        f"Stopped after {max_steps} steps without an answer.",
        steps,
        llm.total,
        StopReason.MAX_STEPS,
        req,
        max_check_failures - budget[0],
    )


# ── Watching it work ──────────────────────────────────────────────────────────


def print_step(step: Step) -> None:
    for call, result in zip(step.calls, step.results, strict=True):
        console.print(f"  [magenta]{step.n}. → {call.name}[/magenta]({str(call.arguments)[:120]})")
        first = result.splitlines()[0] if result else "(empty)"
        colour = "[red]" if result.startswith(FAILURE_PREFIXES) else "[dim]"
        console.print(f"     {colour}{first[:130]}[/]")


QUESTIONS = [
    "Which pickup zone has the highest average total fare, among zones with at least 500 trips?",
    "What is the average total amount for trips picked up at JFK Airport?",
    "Which driver earned the most in tips?",
]


def main() -> None:
    settings = load_settings()
    if problem := missing_credentials(settings):
        console.print(f"[red]{problem}[/red]")
        raise SystemExit(1)

    console.rule("[bold]Chapter 06 — plan, verify, repair")
    console.print(f"[dim]{settings.provider}/{settings.model}[/dim]")

    for question in QUESTIONS:
        console.print(f"\n[bold cyan]Q[/bold cyan]  {question}")
        llm = LLM(settings)
        result = run_agent(llm, question, max_steps=settings.max_steps, on_step=print_step)

        req = result.requirements
        if req:
            plan_bits = [f"metric={req.metric}"]
            if req.grouping:
                plan_bits.append(f"group={req.grouping}")
            if req.min_count:
                plan_bits.append(f"[bold]min_count={req.min_count}[/bold]")
            console.print(f"  [blue]plan:[/blue] [dim]{' · '.join(plan_bits)}[/dim]")

        ok = result.stop_reason is not StopReason.MAX_STEPS and result.grounded
        console.print(f"  [bold {'green' if ok else 'yellow'}]{result.answer[:400]}[/]")
        console.print(
            f"  [dim]{len(result.steps)} steps · {result.checks_failed} checks caught · "
            f"stopped: {result.stop_reason.value}[/dim]"
        )
        if result.stop_reason is StopReason.ANSWERED and not result.grounded:
            console.print("  [red]⚠ UNGROUNDED[/red]")

    console.print(
        "\n[yellow]The checks are the point.[/yellow] Chapter 05 asked the model to "
        "apply constraints. This one refuses the query until it does.\n"
        "Measure it: [bold]python scripts/run_evals.py --agent=05 --agent=06[/bold]"
    )


if __name__ == "__main__":
    run_chapter(main)
