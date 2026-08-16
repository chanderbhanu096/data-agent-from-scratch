"""Tests for chapter 09 — the router, which is the whole decision.

The router is a heuristic, so it will misroute; what it must never do is escalate
nothing (paying frontier prices for everything) or escalate everything (the cheap
tier never used). These pin the behaviour that makes routing worth doing.
"""

from __future__ import annotations

from dataagent.routing import ESCALATE_AT, route


def test_a_plain_count_goes_cheap():
    assert route("How many taxi trips are in the warehouse?").tier == "cheap"


def test_a_single_average_goes_cheap():
    assert route("What is the average trip distance in miles?").tier == "cheap"


def test_a_threshold_escalates():
    d = route(
        "Which borough has the highest average tip? Ignore boroughs with fewer than 1000 trips."
    )
    assert d.tier == "strong"
    assert d.score >= ESCALATE_AT
    assert any("threshold" in r for r in d.reasons)


def test_a_ranked_aggregate_escalates():
    d = route(
        "Which pickup zone has the highest average total fare, among zones with at least 500 trips?"
    )
    assert d.tier == "strong"
    assert any("ranked aggregate" in r for r in d.reasons)


def test_the_decision_is_always_explained_when_it_escalates():
    d = route("Which payment type has the highest average tip?")
    assert d.tier == "strong"
    assert d.reasons, "an escalation with no stated reason is not auditable"


def test_the_router_uses_both_tiers_on_a_mixed_set():
    questions = [
        "How many trips are in the warehouse?",
        "How many trips started in Queens?",
        "Which borough has the highest average tip, ignoring boroughs under 1000 trips?",
        "Which pickup zone has the longest average trip distance among zones with at least 200 trips?",
    ]
    tiers = {route(q).tier for q in questions}
    assert tiers == {"cheap", "strong"}, "a router that always picks one tier is not routing"
