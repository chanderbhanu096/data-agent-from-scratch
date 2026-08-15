"""Tests for chapter 10 — few-shot, where the danger is measuring a lie.

The one thing that would invalidate this chapter is leakage: retrieving a golden
question's own answer as an "example". So the load-time invariant — examples are
disjoint from the eval set, and every example SQL runs — is tested hardest.
"""

from __future__ import annotations

import pytest

from conftest import load_run
from dataagent.evals import load_cases
from dataagent.fewshot import load_examples, render_examples, retrieve_examples
from dataagent.warehouse import run_sql

run = load_run(__file__)


def test_examples_do_not_leak_the_eval_questions():
    golden = {c.question.strip().lower() for c in load_cases()}
    example_qs = {e.question.strip().lower() for e in load_examples()}
    assert golden.isdisjoint(example_qs), "an example equal to a golden question is leakage"


@pytest.mark.parametrize("example", load_examples())
def test_every_example_sql_actually_runs(example):
    result = run_sql(example.sql, timeout_s=10)
    assert result.rows, f"example SQL returned nothing: {example.question}"


def test_retrieval_returns_the_requested_count():
    picked = retrieve_examples("average tip by borough with a minimum trip count", k=3)
    assert len(picked) == 3


def test_a_threshold_question_retrieves_a_having_example():
    picked = retrieve_examples(
        "Which borough has the highest average tip, ignoring boroughs under 1000 trips?", k=3
    )
    assert any("having" in ex.sql.lower() for ex in picked), "should surface a HAVING pattern"


def test_the_block_is_labelled_as_patterns_not_answers():
    block = render_examples(list(load_examples())[:2])
    assert "do not copy" in block.lower()


def test_the_few_shot_prompt_extends_the_plain_prompt():
    from dataagent.tools import build_system_prompt

    plain = build_system_prompt()
    augmented = run.build_few_shot_system("How many trips were paid by credit card?")
    assert plain in augmented and len(augmented) > len(plain)
