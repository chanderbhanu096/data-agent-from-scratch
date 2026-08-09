"""Provider failures must arrive as instructions, not stack traces.

Every case here is a real error someone hits on their first run. The messages
are part of the product: this repo's promise is that it runs for a stranger, and
a stranger's first experience is usually an error.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dataagent.cli import run_chapter
from dataagent.llm import ProviderError, _translate_api_error


class FakeAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def test_no_credits_points_at_billing_and_the_free_alternative():
    """The exact error a real key with an empty balance produces."""
    exc = _translate_api_error(
        FakeAPIError("Your credit balance is too low to access the Anthropic API.", 400),
        "Anthropic",
        "claude-sonnet-5",
    )
    text = str(exc)
    assert "no credits" in text
    assert "billing" in text
    assert "DATAAGENT_PROVIDER=ollama" in text, "must offer the free path"


def test_bad_key_mentions_the_variable_people_actually_get_wrong():
    exc = _translate_api_error(FakeAPIError("authentication_error", 401), "Anthropic", "m")
    assert "ANTHROPIC_API_KEY" in str(exc)
    assert "ANTHROPIC_MODEL" in str(exc)


def test_unknown_model_says_model_names_go_stale():
    exc = _translate_api_error(FakeAPIError("model not_found", 404), "Anthropic", "claude-2")
    text = str(exc)
    assert "claude-2" in text
    assert "ANTHROPIC_MODEL" in text


def test_rate_limit_and_outage_are_distinguished():
    assert "Rate limited" in str(_translate_api_error(FakeAPIError("rate limit", 429), "X", "m"))
    assert "unavailable" in str(_translate_api_error(FakeAPIError("overloaded", 529), "X", "m"))


def test_unrecognised_errors_still_offer_a_way_forward():
    exc = _translate_api_error(FakeAPIError("something weird happened", 418), "Anthropic", "m")
    assert "something weird happened" in str(exc), "never swallow the original detail"
    assert "ollama" in str(exc)


def test_provider_error_is_a_runtime_error():
    """run_chapter() catches RuntimeError — this is what keeps it a clean exit."""
    assert issubclass(ProviderError, RuntimeError)


def test_run_chapter_exits_cleanly_instead_of_raising(capsys):
    def boom():
        raise ProviderError("Anthropic request failed.\n\nno credits\n\nadd credits")

    with pytest.raises(SystemExit) as exit_info:
        run_chapter(boom)

    assert exit_info.value.code == 1
    assert "no credits" in capsys.readouterr().err
