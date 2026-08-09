"""Tests for chapter 04 — the dispatch layer, which is the security boundary."""

from __future__ import annotations

from conftest import load_run

run = load_run(__file__)
execute, TOOLS, tool_sample_column = run.execute, run.TOOLS, run.tool_sample_column


def test_every_tool_declares_a_schema_and_a_handler():
    for tool in TOOLS:
        assert tool.description.strip(), f"{tool.name} has no description"
        assert tool.parameters["type"] == "object"
        assert tool.parameters.get("required"), f"{tool.name} declares no required args"
        assert callable(tool.handler)


def test_unknown_tool_returns_an_error_the_model_can_read():
    out = execute("delete_everything", {})
    assert "no tool named" in out
    # It must also list what IS available, so the model can recover.
    assert "run_sql" in out


def test_bad_arguments_do_not_raise():
    """A malformed tool call must come back as text, never as a crash."""
    out = execute("run_sql", {"wrong_kwarg": "SELECT 1"})
    assert out.startswith("ERROR:")


def test_run_sql_returns_rows():
    out = execute("run_sql", {"sql": "SELECT count(*) AS n FROM trips"})
    assert "300000" in out.replace(",", "")


def test_dangerous_sql_is_rejected_as_a_readable_message():
    out = execute("run_sql", {"sql": "DROP TABLE trips"})
    assert out.startswith("REJECTED:")
    assert "DROP" in out


def test_invalid_sql_comes_back_as_text_not_an_exception():
    out = execute("run_sql", {"sql": "SELECT * FROM table_that_does_not_exist"})
    assert out.startswith("SQL ERROR:")


def test_sample_column_shows_real_values():
    out = tool_sample_column("zones", "borough")
    assert "Manhattan" in out
    # 'N/A' is a genuine borough value in this dataset, not a null.
    assert "N/A" in out


def test_sample_column_survives_a_bad_column_name():
    assert tool_sample_column("zones", "nope").startswith("ERROR:")
