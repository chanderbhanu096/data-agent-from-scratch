"""The warehouse: a read-only DuckDB handle plus the guardrails around it.

The agent never touches DuckDB directly. It goes through `run_sql()`, which is
the single chokepoint where every safety rule lives. That is the pattern worth
copying: one narrow door, not rules scattered across the codebase.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import duckdb

from dataagent.config import WAREHOUSE_PATH


class UnsafeSQL(Exception):
    """Raised when a query is rejected before it ever reaches the database."""


# Anything that writes, drops, or reaches outside the database. DuckDB opens
# read-only below, so this is defence in depth rather than the only line — but
# a clear error beats a driver-level permission error the model can't act on.
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|GRANT|REVOKE|"
    r"ATTACH|DETACH|COPY|EXPORT|INSTALL|LOAD|PRAGMA|SET)\b",
    re.IGNORECASE,
)


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool = False

    def to_markdown(self, max_rows: int = 30) -> str:
        """Render for the model. Compact beats pretty — every cell costs tokens."""
        if not self.rows:
            return "(0 rows)"
        shown = self.rows[:max_rows]
        head = " | ".join(self.columns)
        sep = " | ".join("---" for _ in self.columns)
        body = "\n".join(" | ".join(_fmt(c) for c in row) for row in shown)
        out = f"{head}\n{sep}\n{body}"
        if len(self.rows) > max_rows:
            out += f"\n... ({len(self.rows) - max_rows} more rows)"
        if self.truncated:
            out += "\n(result was truncated by the row limit)"
        return out


def _fmt(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def connect(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    if not WAREHOUSE_PATH.exists():
        raise FileNotFoundError(
            f"No warehouse at {WAREHOUSE_PATH}.\nRun:  python scripts/build_warehouse.py"
        )
    return duckdb.connect(str(WAREHOUSE_PATH), read_only=read_only)


def assert_safe(sql: str) -> None:
    """Reject anything that isn't a single read-only statement.

    Deliberately strict. A text-to-SQL agent that can only ever read is a
    fundamentally different risk profile from one that might not.
    """
    stripped = re.sub(r"--[^\n]*", " ", sql)
    stripped = re.sub(r"/\*.*?\*/", " ", stripped, flags=re.DOTALL).strip()

    if not stripped:
        raise UnsafeSQL("Empty query.")

    if ";" in stripped.rstrip(";"):
        raise UnsafeSQL("Multiple statements are not allowed — send one query at a time.")

    first = stripped.lstrip("( \n\t").split(None, 1)[0].upper()
    if first not in {"SELECT", "WITH"}:
        raise UnsafeSQL(f"Only SELECT/WITH queries are allowed, got {first}.")

    if match := _FORBIDDEN.search(stripped):
        raise UnsafeSQL(f"{match.group(0).upper()} is not allowed — this agent is read-only.")


def run_sql(sql: str, row_limit: int = 1000) -> QueryResult:
    """Validate, cap, execute. The only path from agent to database."""
    assert_safe(sql)
    con = connect(read_only=True)
    try:
        # Fetch one extra row so we can tell "exactly at the limit" from
        # "actually truncated" — the model should know which it got.
        cur = con.execute(sql)
        rows = cur.fetchmany(row_limit + 1)
        columns = [d[0] for d in cur.description]
        truncated = len(rows) > row_limit
        return QueryResult(columns, rows[:row_limit], truncated)
    finally:
        con.close()


def schema_text() -> str:
    """The whole schema as compact DDL, for stuffing into a prompt.

    This works because the warehouse has 3 tables. Chapter 08 is about what to
    do when it has 300 and the schema no longer fits in the context window.
    """
    con = connect(read_only=True)
    try:
        tables = [
            r[0]
            for r in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' ORDER BY table_name"
            ).fetchall()
        ]

        blocks = []
        for table in tables:
            cols = con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = ? ORDER BY ordinal_position",
                [table],
            ).fetchall()
            n = con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            body = ",\n".join(f"  {c} {t}" for c, t in cols)
            blocks.append(f"CREATE TABLE {table} (  -- {n:,} rows\n{body}\n);")
        return "\n\n".join(blocks)
    finally:
        con.close()
