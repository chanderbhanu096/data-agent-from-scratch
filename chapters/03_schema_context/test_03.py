"""Tests for chapter 03 — SQL extraction and the safety layer under it."""

from __future__ import annotations

import pytest

from conftest import load_run
from dataagent.warehouse import UnsafeSQL, assert_safe, run_sql, schema_text

extract_sql = load_run(__file__).extract_sql


def test_extract_plain_sql():
    assert extract_sql("SELECT 1") == "SELECT 1"


def test_extract_strips_sql_fence_and_semicolon():
    assert extract_sql("```sql\nSELECT 1;\n```") == "SELECT 1"


def test_extract_strips_prose_free_fence():
    assert extract_sql("```\nSELECT 1\n```") == "SELECT 1"


def test_schema_text_lists_every_table_with_row_counts():
    schema = schema_text()
    for table in ("trips", "zones", "payment_types"):
        assert f"CREATE TABLE {table}" in schema
    assert "rows" in schema


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE trips",
        "DELETE FROM trips",
        "UPDATE trips SET fare_amount = 0",
        "SELECT 1; DROP TABLE trips",
        "ATTACH '/etc/passwd' AS leak",
        "COPY trips TO '/tmp/stolen.csv'",
        "PRAGMA database_list",
        "",
    ],
)
def test_guardrail_blocks_dangerous_sql(sql):
    with pytest.raises(UnsafeSQL):
        assert_safe(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "select count(*) from trips",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "SELECT 1 -- DROP TABLE trips",  # the keyword is in a comment, not the query
    ],
)
def test_guardrail_allows_read_only_sql(sql):
    assert_safe(sql)


def test_row_limit_is_enforced_and_flagged():
    result = run_sql("SELECT * FROM trips", row_limit=10)
    assert len(result.rows) == 10
    assert result.truncated is True


def test_real_query_returns_real_numbers():
    result = run_sql(
        "SELECT count(*) AS n FROM trips t "
        "JOIN zones z ON t.pickup_zone_id = z.zone_id WHERE z.borough = 'Manhattan'"
    )
    assert result.rows[0][0] > 100_000
