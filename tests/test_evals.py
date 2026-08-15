"""Tests for the eval matcher itself.

A scoring bug is the worst kind of bug in this repo: it doesn't crash, it just
quietly makes every future number wrong, in the confident direction. So the
matcher is tested harder than most of the code it scores.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dataagent.evals import Case, load_cases, score_answer, truth_of, value_in_answer

# ── Counts must match exactly ─────────────────────────────────────────────────


def test_exact_count_matches_with_commas():
    assert value_in_answer("There are 257,614 trips.", "257614")


def test_wrong_count_does_not_match():
    assert not value_in_answer("There are 69 zones.", "257614")


def test_a_count_does_not_match_a_substring_of_a_bigger_number():
    assert not value_in_answer("processed 2576140 rows", "257614")


def test_no_tolerance_on_counts():
    """5979 must not be satisfied by a close-but-wrong 5980."""
    assert not value_in_answer("about 5980 trips", "5979")


# ── Decimals match at the reference's precision ───────────────────────────────


def test_more_precise_answer_still_matches():
    """The bug found in the first eval run: 3.865 rejected for reference 3.86."""
    assert value_in_answer("The average trip distance is 3.865 miles.", "3.86")


def test_rounded_answer_matches():
    assert value_in_answer("roughly $8.13 per trip", "8.127")


def test_dollars_and_words_around_the_number_are_ignored():
    assert value_in_answer("the average tip was $4.51 on card", "4.51")


def test_a_clearly_wrong_decimal_does_not_match():
    assert not value_in_answer("the average was 5.20", "3.86")


def test_integer_answer_matches_integer_reference_written_as_float():
    # reference computed as 7.0 should still match the answer "7"
    assert value_in_answer("7 boroughs", "7")


# ── Labels ────────────────────────────────────────────────────────────────────


def test_label_match_is_case_insensitive():
    assert value_in_answer("The winner is queens.", "Queens")


def test_absent_label_does_not_match():
    assert not value_in_answer("The winner is Manhattan.", "Queens")


# ── Scoring: correct requires the trap to be absent ──────────────────────────


def test_hitting_the_trap_value_fails_even_if_the_right_value_is_present():
    case = Case(
        id="x",
        question="q",
        difficulty="hard",
        expect="first_label",
        reference_sql="SELECT 'Queens'",
        trap_sql="SELECT 'Staten Island'",
    )
    both = score_answer(case, "Staten Island leads, or Queens above 1000 trips.", grounded=True)
    assert both.hit_trap is True
    assert both.correct is False, "quoting the trap answer is not a correct answer"


def test_a_clean_correct_answer_scores_correct():
    case = Case(
        id="x",
        question="q",
        difficulty="hard",
        expect="first_label",
        reference_sql="SELECT 'Queens'",
        trap_sql="SELECT 'Staten Island'",
    )
    assert score_answer(case, "Queens has the highest average tip.", grounded=True).correct


def test_refusal_case_scores_on_declining():
    case = Case(
        id="x",
        question="q",
        difficulty="medium",
        expect="refuse",
        refuse_keywords=("no data", "cannot"),
    )
    assert score_answer(case, "There is no data on drivers.", grounded=True).correct
    assert not score_answer(case, "The top driver earned $900.", grounded=True).correct


# ── The golden file itself must stay runnable ────────────────────────────────


def test_every_reference_and_trap_query_executes_and_they_differ():
    for case in load_cases():
        if case.must_refuse:
            continue
        expected = truth_of(case.reference_sql)
        assert expected is not None, f"{case.id}: reference query returned nothing"
        if case.trap_sql:
            trap = truth_of(case.trap_sql)
            assert trap != expected, f"{case.id}: trap equals reference — it traps nothing"
