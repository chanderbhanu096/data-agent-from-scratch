"""Tests for chapter 02 — the defensive parser, which is where the bugs live."""

from __future__ import annotations

import pytest

from conftest import load_run

run = load_run(__file__)
QuestionPlan, extract_json = run.QuestionPlan, run.extract_json


def test_bare_json():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_fenced_json():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_unlabelled_fence():
    assert extract_json('```\n{"a": 1}\n```') == {"a": 1}


def test_json_buried_in_prose():
    """The single most common real-world response shape."""
    text = 'Sure! Here is the plan:\n\n{"a": 1}\n\nLet me know if you need anything else.'
    assert extract_json(text) == {"a": 1}


def test_nested_objects_keep_their_closing_brace():
    text = 'prefix {"a": {"b": 2}} suffix'
    assert extract_json(text) == {"a": {"b": 2}}


def test_no_json_raises_rather_than_returning_garbage():
    with pytest.raises(ValueError, match="No JSON object"):
        extract_json("I'm afraid I can't help with that.")


def test_plan_rejects_an_intent_outside_the_enum():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        QuestionPlan.model_validate(
            {"intent": "teleport", "tables_needed": [], "time_filtered": False, "reasoning": "x"}
        )


def test_plan_accepts_a_valid_payload():
    plan = QuestionPlan.model_validate(
        {
            "intent": "aggregate",
            "tables_needed": ["trips", "zones"],
            "time_filtered": True,
            "reasoning": "Averages tips grouped by borough.",
        }
    )
    assert plan.intent == "aggregate"
    assert "zones" in plan.tables_needed
