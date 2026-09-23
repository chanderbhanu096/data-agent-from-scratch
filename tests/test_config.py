"""Configuration should fail early when safety limits are invalid."""

from __future__ import annotations

import pytest

from dataagent.config import load_settings


def test_invalid_integer_setting_names_the_variable(monkeypatch):
    monkeypatch.setenv("DATAAGENT_MAX_STEPS", "many")

    with pytest.raises(ValueError, match="DATAAGENT_MAX_STEPS"):
        load_settings()


def test_non_positive_limits_are_rejected(monkeypatch):
    monkeypatch.setenv("DATAAGENT_SQL_ROW_LIMIT", "0")

    with pytest.raises(ValueError, match="DATAAGENT_SQL_ROW_LIMIT"):
        load_settings()


def test_zero_budget_is_allowed_but_negative_budget_is_not(monkeypatch):
    monkeypatch.setenv("DATAAGENT_MAX_USD", "0")
    assert load_settings().max_usd == 0

    monkeypatch.setenv("DATAAGENT_MAX_USD", "-0.01")
    with pytest.raises(ValueError, match="DATAAGENT_MAX_USD"):
        load_settings()
