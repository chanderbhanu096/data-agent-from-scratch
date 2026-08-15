"""Tests for chapter 07 — the guardrails, which are the whole contribution.

Each layer is tested on its own, because defence in depth is only real if every
layer holds when the ones in front of it are removed. So we also check the
read-only handle directly — the wall behind assert_safe, for the query that
should never get there but might.
"""

from __future__ import annotations

import time

import duckdb
import pytest

from conftest import load_run
from dataagent.warehouse import QueryTimeout, UnsafeSQL, assert_safe, connect, run_sql

run = load_run(__file__)


# ── Layer 1: the door refuses every attack the chapter names ─────────────────


@pytest.mark.parametrize("label,sql", run.BLOCKED_AT_THE_DOOR)
def test_every_named_attack_is_blocked(label, sql):
    with pytest.raises(UnsafeSQL):
        assert_safe(sql)


def test_a_plain_select_is_allowed():
    assert_safe("SELECT count(*) FROM trips")  # no exception


def test_a_cte_is_allowed():
    assert_safe("WITH x AS (SELECT 1) SELECT * FROM x")


def test_a_trailing_semicolon_is_not_a_second_statement():
    assert_safe("SELECT 1;")  # one statement, terminated — fine


def test_a_comment_cannot_smuggle_a_second_statement():
    with pytest.raises(UnsafeSQL):
        assert_safe("SELECT 1 -- oops\n; DROP TABLE trips")


# ── Layer 2: the handle is read-only, even for SQL that slips past layer 1 ────


def test_the_connection_itself_refuses_writes():
    con = connect(read_only=True)
    try:
        with pytest.raises(duckdb.Error):
            con.execute("CREATE TABLE loot AS SELECT * FROM trips")
    finally:
        con.close()


# ── Layer 3: a time budget bounds compute, which the row cap can't ───────────


def test_the_compute_bomb_is_interrupted_by_the_budget():
    started = time.monotonic()
    with pytest.raises(QueryTimeout):
        run_sql(run.COMPUTE_BOMB, timeout_s=0.5)
    assert time.monotonic() - started < 5, "the interrupt must be prompt, not eventual"


def test_a_normal_query_does_not_false_timeout():
    result = run_sql("SELECT count(*) FROM trips", timeout_s=10)
    assert result.rows[0][0] == 300_000


def test_the_row_cap_bounds_a_flood():
    result = run_sql(run.ROW_FLOOD, row_limit=10, timeout_s=5)
    assert len(result.rows) == 10
    assert result.truncated is True
