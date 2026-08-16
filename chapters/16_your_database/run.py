"""Chapter 16 — point the agent at your own database.

    python chapters/16_your_database/run.py                 # the bundled sample
    DATAAGENT_DB=/path/to/your.sqlite python chapters/16_your_database/run.py

Every chapter so far queried our NYC taxi warehouse. This one queries *your*
SQLite file. The agent has never seen it, so before it can write a single query
it has to be *taught the database*: we introspect the file, hand the model the
schema and the relationships between tables (the ER information), and only then
does text-to-SQL work. That teaching step is the whole chapter.

Two things make it lazy. The guardrail (`assert_safe`) and the result renderer
(`QueryResult`) are reused straight from the warehouse — they were always pure
functions of the SQL string, not tied to the taxi data. And the agent loop is
Chapter 05, unchanged, driven through the same `execute` swap as Chapters 14–15.
The only new code is reading a schema out of SQLite and drawing it.

SQLite is the default because it needs nothing — no server, no auth. To point the
agent at a database that *isn't* SQLite (your real Postgres, on your machine), see
`README.md` → "Your own data, not in SQLite": same loop, a different `execute`.
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(
    0, str(Path(__file__).resolve().parent)
)  # so `build_sample_db` imports under pytest too

from build_sample_db import DEFAULT_DB, ensure
from rich.console import Console

from dataagent.cli import run_chapter
from dataagent.config import load_settings
from dataagent.llm import LLM, Tool, missing_credentials
from dataagent.warehouse import QueryResult, UnsafeSQL, assert_safe

console = Console()

_ENUM_MAX_DISTINCT = 16  # same threshold the warehouse uses to decide "this is an enum"


# ── Reading a schema out of SQLite ──────────────────────────────────────────────


@dataclass
class Column:
    name: str
    type: str
    pk: bool = False
    fk: bool = False


@dataclass
class ForeignKey:
    child_table: str
    child_col: str
    parent_table: str
    parent_col: str
    inferred: bool = False


@dataclass
class Table:
    name: str
    columns: list[Column]
    rows: int


@dataclass
class Schema:
    tables: list[Table] = field(default_factory=list)
    fks: list[ForeignKey] = field(default_factory=list)


def _read_only(path: str | Path) -> sqlite3.Connection:
    """Open SQLite so the OS itself forbids writes — defence in depth under assert_safe."""
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def introspect(path: str | Path) -> Schema:
    """Read tables, columns, primary keys and foreign keys via SQLite's own PRAGMAs.

    We go straight to SQLite rather than through DuckDB on purpose: DuckDB's SQLite
    reader drops foreign keys, and the foreign keys are exactly what the ER diagram
    and the model's JOINs need.
    """
    con = _read_only(path)
    try:
        names = [
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        schema = Schema()
        for name in names:
            cols = [
                Column(name=r[1], type=(r[2] or "").upper() or "ANY", pk=bool(r[5]))
                for r in con.execute(f'PRAGMA table_info("{name}")')
            ]
            for r in con.execute(f'PRAGMA foreign_key_list("{name}")'):
                child_col, parent_table, parent_col = r[3], r[2], r[4]
                schema.fks.append(ForeignKey(name, child_col, parent_table, parent_col))
                for c in cols:
                    if c.name == child_col:
                        c.fk = True
            n = con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
            schema.tables.append(Table(name, cols, n))
        _add_inferred_fks(schema)
        return schema
    finally:
        con.close()


def _add_inferred_fks(schema: Schema) -> None:
    """When a table declares no foreign keys, guess them from `<name>_id` columns.

    Real databases — our taxi warehouse included — often omit foreign-key
    constraints. Rather than draw a diagram with no edges, we infer relationships
    by naming convention and mark them clearly as guesses, never as fact.
    """
    by_name = {t.name.lower(): t.name for t in schema.tables}
    declared = {(fk.child_table, fk.child_col) for fk in schema.fks}
    for table in schema.tables:
        for col in table.columns:
            if not col.name.lower().endswith("_id") or (table.name, col.name) in declared:
                continue
            stem = col.name[:-3].lower()  # customer_id → customer
            parent = by_name.get(stem) or by_name.get(stem + "s")
            if parent and parent != table.name:
                col.fk = True
                schema.fks.append(ForeignKey(table.name, col.name, parent, "id", inferred=True))


# ── Drawing it: schema → Mermaid ER diagram ─────────────────────────────────────


def _ident(name: str) -> str:
    """Mermaid entity/attribute names must be bare tokens; quote anything odd."""
    return name if name.replace("_", "").isalnum() else f'"{name}"'


def er_mermaid(schema: Schema) -> str:
    """Render the schema as a Mermaid erDiagram — plain text, renders on GitHub,

    in the live demo, and in a Claude artifact, with no diagramming library.
    Declared foreign keys are solid (`||--o{`); inferred ones are dashed (`||..o{`).
    """
    lines = ["erDiagram"]
    for t in schema.tables:
        lines.append(f"  {_ident(t.name)} {{")
        for c in t.columns:
            key = " PK" if c.pk else (" FK" if c.fk else "")
            lines.append(f"    {_ident(c.type)} {_ident(c.name)}{key}")
        lines.append("  }")
    for fk in schema.fks:
        link = "||..o{" if fk.inferred else "||--o{"
        label = f"{fk.child_col} (inferred)" if fk.inferred else fk.child_col
        lines.append(f'  {_ident(fk.parent_table)} {link} {_ident(fk.child_table)} : "{label}"')
    return "\n".join(lines)


# ── Teaching the model the database ─────────────────────────────────────────────


def _value_hints(con: sqlite3.Connection, table: str, column: str) -> str | None:
    """`column in (...)` for a small text enum, so the model filters on real values."""
    rows = con.execute(
        f'SELECT DISTINCT "{column}" FROM "{table}" '
        f'WHERE "{column}" IS NOT NULL ORDER BY 1 LIMIT {_ENUM_MAX_DISTINCT + 1}'
    ).fetchall()
    values = [r[0] for r in rows]
    if (
        not values
        or len(values) > _ENUM_MAX_DISTINCT
        or not all(isinstance(v, str) for v in values)
    ):
        return None
    return f"{column} in (" + ", ".join(f"'{v}'" for v in values) + ")"


def schema_context(path: str | Path, schema: Schema) -> str:
    """The DDL, the real relationships, and enum values — everything the model needs.

    This is the "provide the schema and ER diagram to the model" step: the diagram's
    facts (which table points at which) go in as text, which is what the model can
    actually use to write correct JOINs.
    """
    con = _read_only(path)
    try:
        blocks = []
        for t in schema.tables:
            body = ",\n".join(
                f"  {c.name} {c.type}{' PRIMARY KEY' if c.pk else ''}" for c in t.columns
            )
            block = f"CREATE TABLE {t.name} (  -- {t.rows:,} rows\n{body}\n);"
            hints = [h for c in t.columns if (h := _value_hints(con, t.name, c.name))]
            if hints:
                block += "\n-- values: " + "; ".join(hints)
            blocks.append(block)
    finally:
        con.close()

    rels = [
        f"- {fk.child_table}.{fk.child_col} → {fk.parent_table}.{fk.parent_col}"
        + (" (inferred from naming, not a declared key)" if fk.inferred else "")
        for fk in schema.fks
    ]
    rel_text = "\n".join(rels) if rels else "- (no foreign-key relationships found)"
    return "\n\n".join(blocks) + "\n\nRelationships (use these for JOINs):\n" + rel_text


def build_system_prompt(path: str | Path, schema: Schema) -> str:
    return (
        "You are a data analyst answering questions about a SQLite database using the "
        "run_sql tool. Work in steps: read the schema below, write one SELECT, read the "
        "result, then answer.\n\n"
        f"{schema_context(path, schema)}\n\n"
        "Rules:\n"
        "- NEVER put SQL in your reply. SQL goes only in the run_sql tool call.\n"
        "- Use the relationships above to JOIN; do not invent columns or tables.\n"
        "- If a query errors, call run_sql again with a fix rather than explaining it.\n"
        "- Every number you state must come from a tool result you received.\n"
        "- Once you have the data, answer in one or two plain-English sentences."
    )


# ── Running SQL against the user's database (the reused chokepoint) ──────────────

RUN_SQL_TOOL = Tool(
    name="run_sql",
    description=(
        "Run a read-only SELECT against the connected SQLite database and return the rows. "
        "Only SELECT/WITH are permitted; writes are rejected. If it errors, fix the SQL and "
        "call again."
    ),
    parameters={
        "type": "object",
        "properties": {"sql": {"type": "string", "description": "A single SQLite SELECT"}},
        "required": ["sql"],
    },
)


def run_sql_sqlite(path: str | Path, sql: str, row_limit: int = 1000) -> str:
    """assert_safe → read-only execute → markdown. Same shape as the warehouse tool."""
    try:
        assert_safe(sql)
    except UnsafeSQL as exc:
        return f"REJECTED: {exc}"
    con = _read_only(path)
    try:
        cur = con.execute(sql)
        fetched = cur.fetchmany(row_limit + 1)
        cols = [d[0] for d in cur.description] if cur.description else []
        result = QueryResult(
            cols, [tuple(r) for r in fetched[:row_limit]], truncated=len(fetched) > row_limit
        )
        return result.to_markdown()
    except Exception as exc:  # noqa: BLE001 — return it so the agent can retry
        return f"SQL ERROR: {str(exc).splitlines()[0]}"
    finally:
        con.close()


def _load_chapter_05():
    p = Path(__file__).resolve().parents[1] / "05_agent_loop" / "run.py"
    spec = importlib.util.spec_from_file_location("agent_05_for_16", p)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_ch05 = _load_chapter_05()


def run_agent_over_db(llm, question: str, path: str | Path, schema: Schema, **kwargs):
    """Chapter 05's loop, unchanged — ACT now runs against your SQLite file."""
    _ch05.execute = lambda name, arguments: (
        run_sql_sqlite(path, arguments.get("sql", ""))
        if name == "run_sql"
        else f"ERROR: no tool {name!r}"
    )
    return _ch05.run_agent(
        llm, question, tools=[RUN_SQL_TOOL], system=build_system_prompt(path, schema), **kwargs
    )


def main() -> None:
    db = os.getenv("DATAAGENT_DB")
    if db:
        path = Path(db).expanduser()
        if not path.exists():
            console.print(f"[red]No database at {path}[/red]")
            return
    else:
        path = ensure(DEFAULT_DB)  # build the bundled sample on first run

    console.print("[bold cyan]Query your own database[/bold cyan]")
    console.print(f"[dim]{path.name} · SQLite{' (bundled sample)' if not db else ''}[/dim]\n")

    schema = introspect(path)
    console.print(
        f"[green]read schema[/green] · {len(schema.tables)} tables, {len(schema.fks)} relationships"
    )

    diagram = er_mermaid(schema)
    out = path.with_suffix(".mmd")
    out.write_text(diagram + "\n")
    console.print(f"[dim]ER diagram written to {out.name} (renders on GitHub / in the demo):[/dim]")
    console.print(diagram)

    if missing_credentials(load_settings()):
        console.print("\n[yellow]Set a provider in .env to ask the database a question.[/yellow]")
        return

    q = "Which customer has the highest total order value? Give the name and the amount."
    console.print(f"\n[cyan]Q[/cyan] {q}")
    result = run_agent_over_db(LLM(load_settings()), q, path, schema)
    console.print(f"[green]A[/green] {' '.join(result.answer.split())}")
    console.print(
        f"[dim]answered from your DB · {result.tool_calls_made} tool calls · "
        f"grounded={result.grounded} · stop={result.stop_reason.value}[/dim]"
    )


if __name__ == "__main__":
    run_chapter(main)
