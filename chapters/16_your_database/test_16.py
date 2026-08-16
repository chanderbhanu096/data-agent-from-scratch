"""Tests for chapter 16 — querying your own SQLite database.

No model. These check the parts that make text-to-SQL possible on an unknown DB:
reading the schema (including foreign keys), drawing it, inferring relationships
when none are declared, and the read-only guardrail on the query path.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_sample_db

from conftest import load_run

run = load_run(__file__)


def test_introspect_reads_tables_and_declared_foreign_keys(tmp_path):
    db = build_sample_db.build(tmp_path / "shop.sqlite")
    schema = run.introspect(db)
    assert {t.name for t in schema.tables} == {"customers", "orders", "line_items"}
    declared = {(fk.child_table, fk.parent_table) for fk in schema.fks if not fk.inferred}
    assert ("orders", "customers") in declared
    assert ("line_items", "orders") in declared


def test_er_mermaid_draws_entities_and_relationships():
    schema = run.Schema(
        tables=[
            run.Table("customers", [run.Column("id", "INTEGER", pk=True)], 3),
            run.Table("orders", [run.Column("customer_id", "INTEGER", fk=True)], 5),
        ],
        fks=[run.ForeignKey("orders", "customer_id", "customers", "id")],
    )
    mermaid = run.er_mermaid(schema)
    assert mermaid.startswith("erDiagram")
    assert "customers ||--o{ orders" in mermaid  # declared → solid line


def test_relationships_are_inferred_when_none_are_declared(tmp_path):
    db = tmp_path / "noforeign.sqlite"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE users(id INTEGER PRIMARY KEY);"
        "CREATE TABLE posts(id INTEGER PRIMARY KEY, user_id INTEGER);"  # no REFERENCES
    )
    con.close()
    schema = run.introspect(db)
    inferred = [fk for fk in schema.fks if fk.inferred]
    assert any(fk.child_table == "posts" and fk.parent_table == "users" for fk in inferred)
    assert "||..o{" in run.er_mermaid(schema)  # inferred → dashed line


def test_run_sql_is_read_only(tmp_path):
    db = build_sample_db.build(tmp_path / "shop.sqlite")
    ok = run.run_sql_sqlite(
        db,
        "SELECT c.name, SUM(o.total) FROM customers c JOIN orders o ON o.customer_id=c.id GROUP BY 1",
    )
    assert "Bob" in ok
    assert run.run_sql_sqlite(db, "DELETE FROM orders").startswith("REJECTED")
    # the OS-level read-only handle is the second lock: the rows are still there.
    assert sqlite3.connect(db).execute("SELECT count(*) FROM orders").fetchone()[0] == 5
