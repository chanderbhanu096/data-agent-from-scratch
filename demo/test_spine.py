"""Offline tests for the demo spine.

The live runs are verified by running the thing; these cover the pure glue that
has no business calling a model: SQL extraction from a trace, the mode→provider
mapping, and replay lookup. No network, no key.
"""

from __future__ import annotations

from types import SimpleNamespace

from demo import spine


def _step(sql=None):
    call = SimpleNamespace(name="run_sql", arguments={"sql": sql} if sql else {})
    return SimpleNamespace(calls=[call])


def test_last_sql_takes_the_final_query_run():
    result = SimpleNamespace(steps=[_step("SELECT 1"), _step("SELECT 2 FROM trips")])
    assert spine._last_sql(result) == "SELECT 2 FROM trips"


def test_last_sql_is_none_when_no_sql_was_run():
    result = SimpleNamespace(steps=[SimpleNamespace(calls=[])])
    assert spine._last_sql(result) is None


def test_settings_for_maps_modes_to_providers():
    assert spine.settings_for("cloud").provider == "azure"
    assert spine.settings_for("local").provider == "ollama"


def test_columns_are_the_three_chapters_in_order():
    assert spine.COLUMN_IDS == ["ch05", "ch06", "ch08"]


def test_replay_returns_captured_columns_or_none():
    runs = spine.load_runs()
    if runs.get("questions"):
        q = runs["questions"][0]
        cols = spine.replay_columns(q)
        assert cols and {c["id"] for c in cols} == set(spine.COLUMN_IDS)
    assert spine.replay_columns("a question nobody ever captured") is None


def test_replay_mode_available_tracks_the_data_file():
    assert spine.mode_available("replay") == spine.DATA_PATH.exists()
