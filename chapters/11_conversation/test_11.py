"""Tests for chapter 11 — conversation memory and its plumbing.

The follow-up resolution itself is the model's job (measured live). What's tested
here is the machinery around it: that history is carried, rendered into the next
turn, and that the scored sequences are answerable at all.
"""

from __future__ import annotations

import pytest

from conftest import load_run
from dataagent.llm import Reply
from dataagent.testing import ScriptedLLM
from dataagent.warehouse import run_sql

run = load_run(__file__)
Conversation = run.Conversation


def test_history_is_empty_before_the_first_turn():
    assert run.render_history([]) == ""


def test_history_contains_prior_questions_and_answers():
    rendered = run.render_history([("How many trips?", "300,000 trips.")])
    assert "How many trips?" in rendered
    assert "300,000 trips." in rendered
    assert "follow-up" in rendered.lower()


def test_a_conversation_accumulates_its_turns():
    llm = ScriptedLLM([Reply(text="First answer."), Reply(text="Second answer.")])
    conv = Conversation(llm)
    conv.ask("First question?")
    conv.ask("Second question?")
    assert conv.turns == [
        ("First question?", "First answer."),
        ("Second question?", "Second answer."),
    ]


def test_the_second_turn_sees_the_first_in_its_prompt():
    llm = ScriptedLLM([Reply(text="300,000 trips."), Reply(text="257,614 in Manhattan.")])
    conv = Conversation(llm)
    conv.ask("How many trips are there?")
    conv.ask("How many in Manhattan?")
    second_turn_system = llm.calls[1].system
    assert "How many trips are there?" in second_turn_system
    assert "300,000 trips." in second_turn_system, "the follow-up must see the prior answer"


@pytest.mark.parametrize("convo", run.load_conversations(), ids=lambda c: c["id"])
def test_every_scored_followup_is_actually_answerable(convo):
    result = run_sql(convo["reference_sql"], timeout_s=10)
    assert result.rows and result.rows[0][0] is not None
