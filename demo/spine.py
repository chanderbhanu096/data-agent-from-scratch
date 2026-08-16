"""The demo's read-only orchestrator.

One question, run through the real chapter agents in sequence, so the UI can show
what each capability adds side by side. Every column is a genuine run of the same
loop the chapters ship — this file *imports* them, exactly like chapters 11 and 13
already import chapter 05. It does not touch `dataagent/` or any chapter: no edits,
no monkey-patching, no shortcuts. If a column needs data the library doesn't
expose, it's derived here from the public `AgentResult`, not bolted onto the loop.

Three run modes share this spine:
  cloud   a hosted frontier model (Azure) — the live experience
  local   a free model on your machine (Ollama) — live, offline, no key
  replay  captured real runs from demo/data/runs.json — no model at all

ponytail: no new agent machinery. The columns are the chapters you already built;
the tracer is chapter 12's; the only new code is the glue that lines them up.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataagent.config import Settings, _model_for, load_settings
from dataagent.llm import LLM, missing_credentials
from dataagent.tools import TOOLS, build_system_prompt
from dataagent.trace import Tracer

DATA_PATH = Path(__file__).resolve().parent / "data" / "runs.json"


def _load_chapter(folder: str, modname: str):
    path = ROOT / "chapters" / folder / "run.py"
    spec = importlib.util.spec_from_file_location(modname, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[modname] = module
    spec.loader.exec_module(module)
    return module


_ch05 = _load_chapter("05_agent_loop", "demo_ch05")
_ch06 = _load_chapter("06_plan_and_verify", "demo_ch06")
_ch08 = _load_chapter("08_schema_retrieval", "demo_ch08")
_ch10 = _load_chapter("10_few_shot", "demo_ch10")


def _run_05(llm: LLM, q: str, tr: Tracer):
    return _ch05.run_agent(llm, q, tools=TOOLS, system=build_system_prompt(), on_step=tr)


def _run_06(llm: LLM, q: str, tr: Tracer):
    return _ch06.run_agent(llm, q, on_step=tr)


def _run_08(llm: LLM, q: str, tr: Tracer):
    return _ch08.run_agent(llm, q, on_step=tr)


def _run_10(llm: LLM, q: str, tr: Tracer):
    return _ch10.run_agent(llm, q, on_step=tr)


# ponytail: chapter 09 (routing) is deliberately not a column — its cheap tier is a
# local Ollama, which the hosted demo has no access to, so it would fall back every
# time instead of showing anything. It stays a link like the other build-up chapters.


_REPO_ROOT = "https://github.com/chanderbhanu096/data-agent-from-scratch"
_REPO = f"{_REPO_ROOT}/tree/main/chapters"

# The whole curriculum, so a visitor sees the other 13 chapters exist without us
# running them all live. Three of these (05/06/08) are the columns above; the rest
# are one click to the code. Titles kept short on purpose — this is a map, not a ToC.
CHAPTERS: list[dict[str, str]] = [
    {"n": "01", "title": "First model call", "folder": "01_first_call"},
    {"n": "02", "title": "Structured output", "folder": "02_structured_output"},
    {"n": "03", "title": "Schema as context", "folder": "03_schema_context"},
    {"n": "04", "title": "Tool calling", "folder": "04_tool_calling"},
    {"n": "05", "title": "Agent loop", "folder": "05_agent_loop"},
    {"n": "06", "title": "Plan · verify · repair", "folder": "06_plan_and_verify"},
    {"n": "07", "title": "Guardrails", "folder": "07_guardrails"},
    {"n": "08", "title": "Schema retrieval", "folder": "08_schema_retrieval"},
    {"n": "09", "title": "Model routing", "folder": "09_routing"},
    {"n": "10", "title": "Few-shot examples", "folder": "10_few_shot"},
    {"n": "11", "title": "Conversation memory", "folder": "11_conversation"},
    {"n": "12", "title": "Tracing & receipts", "folder": "12_tracing"},
    {"n": "13", "title": "Embeddings", "folder": "13_embeddings"},
    {"n": "14", "title": "MCP server", "folder": "14_mcp"},
    {"n": "15", "title": "MCP client", "folder": "15_mcp_connect"},
    {"n": "16", "title": "Your own database", "folder": "16_your_database"},
]


def public_chapters() -> list[dict[str, Any]]:
    """All chapters with their code links and a flag for the ones shown live above."""
    live = set(COLUMN_IDS)
    return [
        {**c, "link": f"{_REPO}/{c['folder']}", "live": f"ch{c['n']}" in live}
        for c in CHAPTERS
    ]

# The demo spine: one column per capability, left → right = the story of the repo.
# `plain` is the visitor-facing one-liner; `subtitle` is the technical tagline.
COLUMNS: list[dict[str, Any]] = [
    {
        "id": "ch05",
        "chapter": "05",
        "title": "Plain loop",
        "subtitle": "think → act → observe, no guardrails",
        "plain": "Just writes SQL and runs it. Fast — but it can be confidently wrong.",
        "link": f"{_REPO}/05_agent_loop",
        "run": _run_05,
    },
    {
        "id": "ch06",
        "chapter": "06",
        "title": "Plan · verify · repair",
        "subtitle": "checks its own SQL, refuses the impossible",
        "plain": "Checks its own SQL and refuses questions the data can't answer.",
        "link": f"{_REPO}/06_plan_and_verify",
        "run": _run_06,
    },
    {
        "id": "ch08",
        "chapter": "08",
        "title": "Schema retrieval",
        "subtitle": "finds the right table out of 253",
        "plain": "Finds the right tables first, so it still works when the schema is huge.",
        "link": f"{_REPO}/08_schema_retrieval",
        "run": _run_08,
    },
    {
        "id": "ch10",
        "chapter": "10",
        "title": "Few-shot examples",
        "subtitle": "worked examples retrieved into the prompt",
        "plain": "Studies similar solved questions first, then writes the SQL.",
        "link": f"{_REPO}/10_few_shot",
        "run": _run_10,
    },
]
COLUMN_IDS = [c["id"] for c in COLUMNS]
_BY_ID = {c["id"]: c for c in COLUMNS}
_PUBLIC_COLUMN_KEYS = ("id", "chapter", "title", "subtitle", "plain", "link")


def public_columns() -> list[dict[str, Any]]:
    """The column metadata safe to send to the browser (everything but the `run` fn)."""
    return [{k: c[k] for k in _PUBLIC_COLUMN_KEYS} for c in COLUMNS]


# What's in the warehouse, curated for a first-time visitor so they know what they
# can ask. Kept in sync by hand with scripts/build_warehouse.py — it's three fixed
# tables, so a readable summary beats dumping DDL at someone who's never seen it.
DATASET: dict[str, Any] = {
    "name": "NYC yellow-taxi rides — January 2024",
    "tables": [
        {
            "name": "trips",
            "rows": "300,000",
            "about": "one row per ride",
            "columns": [
                "pickup_at",
                "dropoff_at",
                "trip_distance_miles",
                "passenger_count",
                "fare_amount",
                "tip_amount",
                "tolls_amount",
                "total_amount",
                "pickup_zone_id",
                "dropoff_zone_id",
                "payment_type_id",
                "vendor_id",
            ],
        },
        {
            "name": "zones",
            "rows": "265",
            "about": "pickup / drop-off locations",
            "columns": ["zone_id", "borough", "zone_name", "service_zone"],
        },
        {
            "name": "payment_types",
            "rows": "7",
            "about": "how the fare was paid",
            "columns": ["payment_type_id", "payment_type"],
        },
    ],
    "relationships": [
        "trips.pickup_zone_id / dropoff_zone_id → zones.zone_id",
        "trips.payment_type_id → payment_types.payment_type_id",
    ],
    # Where a curious visitor goes to see exactly what's loaded — the build script
    # lists every table, column and row count. Public NYC TLC data underneath.
    "explore": f"{_REPO_ROOT}/blob/main/scripts/build_warehouse.py",
}

# Curated so the columns visibly diverge. The last one is unanswerable from this
# warehouse — the plain loop tends to invent a driver, plan/verify refuses. That
# contrast is the demo's whole point.
DEMO_QUESTIONS = [
    "What is the average tip amount by payment type? Show the payment type name.",
    "Which pickup zone has the most trips?",
    "How many trips had a total amount over 100 dollars?",
    "How many trips started in Manhattan?",
    "Who is the highest-earning driver?",
]


def demo_questions() -> list[str]:
    """Prefer the exact set that was captured, so replay always has an answer."""
    captured = load_runs().get("questions")
    return captured or DEMO_QUESTIONS


# Notes attached to specific example questions. The trap is the whole point of the
# demo, so it gets flagged. Keys must match a captured question exactly, or replay
# can't answer a click.
_EXAMPLE_NOTES = {
    "Who is the highest-earning driver?": {
        # The model behind this moves; what stays true is that they handle the
        # unanswerable question *differently*, and the badges show which ones
        # backed their refusal with an actual query.
        "note": "a trick — this data has no drivers; watch how differently they handle it",
        "trap": True,
    },
}


def examples() -> list[dict[str, Any]]:
    """Clickable example questions for the UI, the trap among them, flagged."""
    return [{"q": q, **_EXAMPLE_NOTES.get(q, {})} for q in demo_questions()]


def _last_sql(result: Any) -> str | None:
    """The SQL the agent actually ran, pulled from its own trace of tool calls."""
    sql = None
    for step in result.steps:
        for call in step.calls:
            args = getattr(call, "arguments", None)
            if isinstance(args, dict) and "sql" in args:
                sql = args["sql"]
    return sql


def settings_for(mode: str) -> Settings:
    """Cloud → Azure, local → Ollama, anything else → whatever .env already says."""
    base = load_settings()
    provider = {"cloud": "azure", "local": "ollama"}.get(mode)
    if provider is None:
        return base
    model, base_url = _model_for(provider)
    return replace(base, provider=provider, model=model, base_url=base_url)


def mode_available(mode: str) -> bool:
    if mode == "replay":
        return DATA_PATH.exists()
    return not missing_credentials(settings_for(mode))


def _column_payload(col: dict[str, Any], result: Any, tr: Tracer) -> dict[str, Any]:
    return {
        "id": col["id"],
        "chapter": col["chapter"],
        "title": col["title"],
        "subtitle": col["subtitle"],
        "answer": " ".join(result.answer.split()),
        "sql": _last_sql(result),
        "grounded": bool(result.grounded),
        "stop_reason": result.stop_reason.value,
        "tokens_in": result.usage.input_tokens,
        "tokens_out": result.usage.output_tokens,
        "cost_usd": round(result.usage.cost_usd, 6),
        "ms": round(sum(s.ms for s in tr.steps), 1),
        "steps": [asdict(s) for s in tr.steps],
    }


def run_column(column_id: str, question: str, mode: str) -> dict[str, Any]:
    """Run one column live. Raises nothing the caller can't render — errors come
    back as a payload with an `error` field so a single failure never blanks the UI."""
    col = _BY_ID[column_id]
    llm = LLM(settings_for(mode))  # fresh cost counter per column
    tr = Tracer(llm)
    try:
        result = col["run"](llm, question, tr)
    except Exception as e:  # noqa: BLE001 — a broken column renders its error, never crashes the board
        return {
            "id": col["id"],
            "chapter": col["chapter"],
            "title": col["title"],
            "subtitle": col["subtitle"],
            "error": str(e).splitlines()[0][:200] if str(e) else e.__class__.__name__,
        }
    return _column_payload(col, result, tr)


# ── Recorded replay ─────────────────────────────────────────────────────────────


def load_runs() -> dict[str, Any]:
    if not DATA_PATH.exists():
        return {"questions": [], "runs": {}}
    return json.loads(DATA_PATH.read_text())


def replay_columns(question: str) -> list[dict[str, Any]] | None:
    """The captured columns for a question, or None if it wasn't captured."""
    return load_runs().get("runs", {}).get(question)
