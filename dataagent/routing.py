"""Route each question to the cheapest model that can answer it.

Not every question needs a frontier model. "How many trips are there?" is a
single count; a 3B model you run for free gets it right. "Which borough has the
highest average tip, ignoring boroughs under 1000 trips?" has a join, an
aggregate, a ranking, and a threshold — that is where the weak model drops a
constraint and the expensive model earns its price.

So route by *shape*. The router reads the question — never the data — for the
cues that predict difficulty, and sends the easy ones to the cheap tier and the
hard ones to the strong tier. It is a cheap, transparent heuristic on purpose:
you can see exactly why a question was escalated, and the cost lever is honest —
the fraction of questions that reach the paid model.

The models on each tier are yours to choose (see the README placeholders). The
default pairing is the one most people already have: a free local model for the
easy questions, a paid API model for the hard ones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Each cue is a pattern that predicts a query the weak tier tends to get wrong,
# with the weight it adds. Two points escalates to the strong tier.
_THRESHOLD = re.compile(
    r"at least|more than|fewer than|no fewer|ignore .*(under|below)|"
    r"with over|over \d|minimum of|at most",
    re.IGNORECASE,
)
_RANKING = re.compile(r"highest|lowest|top|most|least|maximum|minimum|best|worst", re.IGNORECASE)
_AGGREGATE = re.compile(r"average|avg|per |by each|for each|grouped|group by| by ", re.IGNORECASE)
_NAME_JOIN = re.compile(r"\bwhich\b|name of|named|called", re.IGNORECASE)
_MULTI = re.compile(r"\band\b|\bamong\b|excluding|without|between .* and ", re.IGNORECASE)

ESCALATE_AT = 2


@dataclass
class Route:
    """Where a question is going, and the evidence for the decision."""

    tier: str  # "cheap" | "strong"
    score: int
    reasons: list[str] = field(default_factory=list)


def route(question: str) -> Route:
    """Read the question's shape and pick a tier. Deterministic and explainable."""
    score = 0
    reasons: list[str] = []

    if _THRESHOLD.search(question):
        score += 2
        reasons.append("a minimum-count threshold (the constraint weak models drop)")
    if _RANKING.search(question) and _AGGREGATE.search(question):
        score += 2
        reasons.append("a ranked aggregate (group, aggregate, then order)")
    elif _RANKING.search(question):
        score += 1
        reasons.append("a superlative")
    if _NAME_JOIN.search(question):
        score += 1
        reasons.append("names a thing, so it needs a join")
    if _MULTI.search(question):
        score += 1
        reasons.append("more than one condition")
    if len(question.split()) > 14:
        score += 1
        reasons.append("a long, multi-clause question")

    tier = "strong" if score >= ESCALATE_AT else "cheap"
    return Route(tier, score, reasons)
