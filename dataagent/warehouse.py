"""The warehouse: a read-only DuckDB handle plus the guardrails around it.

The agent never touches DuckDB directly. It goes through `run_sql()`, which is
the single chokepoint where every safety rule lives. That is the pattern worth
copying: one narrow door, not rules scattered across the codebase.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass

import duckdb

from dataagent.config import WAREHOUSE_PATH


class UnsafeSQL(Exception):
    """Raised when a query is rejected before it ever reaches the database."""


class QueryTimeout(Exception):
    """Raised when a query runs past its time budget and is interrupted."""


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


def run_sql(sql: str, row_limit: int = 1000, timeout_s: float | None = None) -> QueryResult:
    """Validate, cap, execute. The only path from agent to database.

    `timeout_s` bounds *compute*, not just output. The row limit caps how many
    rows we fetch, but an aggregate over a cross join does all the work before it
    returns a single number — the row cap never sees it. A watchdog thread asks
    DuckDB to interrupt the query once the budget is spent.
    """
    assert_safe(sql)
    con = connect(read_only=True)
    watchdog = threading.Timer(timeout_s, con.interrupt) if timeout_s else None
    if watchdog is not None:
        watchdog.start()
    try:
        # Fetch one extra row so we can tell "exactly at the limit" from
        # "actually truncated" — the model should know which it got.
        cur = con.execute(sql)
        rows = cur.fetchmany(row_limit + 1)
        columns = [d[0] for d in cur.description]
        truncated = len(rows) > row_limit
        return QueryResult(columns, rows[:row_limit], truncated)
    except duckdb.InterruptException:
        raise QueryTimeout(f"Query exceeded its {timeout_s:g}s budget and was cancelled.") from None
    finally:
        if watchdog is not None:
            watchdog.cancel()
        con.close()


# A column with at most this many distinct values gets its values listed
# inline. The model cannot guess that payment_type is spelled 'Credit card'
# and not 'CREDIT CARD'; a name like `borough` does not tell it that 'EWR'
# and 'N/A' are real values. So we profile the low-cardinality columns and
# hand it the vocabulary. High-cardinality columns (ids, amounts, names of
# 265 zones) blow past the cap and are left as plain DDL.
_ENUM_MAX_DISTINCT = 16


def _value_hints(con: duckdb.DuckDBPyConnection, table: str, column: str) -> str | None:
    """Return `column in (...)` if the column is a small enum, else None.

    We fetch one more value than the cap and bail the moment we exceed it, so
    this never materialises the distinct set of a 300k-row float column.
    """
    rows = con.execute(
        f'SELECT DISTINCT "{column}" FROM "{table}" '
        f'WHERE "{column}" IS NOT NULL ORDER BY 1 LIMIT {_ENUM_MAX_DISTINCT + 1}'
    ).fetchall()
    if not rows or len(rows) > _ENUM_MAX_DISTINCT:
        return None
    values = [r[0] for r in rows]
    # Only worth listing text enums and small integer codes; a column of
    # distinct floats that happens to be short is noise, not vocabulary.
    if any(isinstance(v, float) for v in values):
        return None
    rendered = ", ".join(f"'{v}'" if isinstance(v, str) else str(v) for v in values)
    return f"{column} in ({rendered})"


def schema_text(only: list[str] | None = None) -> str:
    """The whole schema as compact DDL, for stuffing into a prompt.

    This works because the warehouse has 3 tables. Chapter 08 is about what to
    do when it has 300 and the schema no longer fits in the context window — and
    it needs to render just the tables retrieval selected, so `only` restricts
    the output to a set of table names while keeping the value-hint enrichment.
    """
    keep = set(only) if only is not None else None
    con = connect(read_only=True)
    try:
        tables = [
            r[0]
            for r in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' ORDER BY table_name"
            ).fetchall()
            if keep is None or r[0] in keep
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
            block = f"CREATE TABLE {table} (  -- {n:,} rows\n{body}\n);"

            hints = [hint for c, _ in cols if (hint := _value_hints(con, table, c)) is not None]
            if hints:
                block += "\n-- values: " + "; ".join(hints)
            blocks.append(block)
        return "\n\n".join(blocks)
    finally:
        con.close()
