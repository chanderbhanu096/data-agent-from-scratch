"""Execution-accuracy scoring for the golden question set.

Ground truth is not written down — it is *computed*. Each case carries a
reference SQL, and the expected answer is whatever that query returns against
the live warehouse. Rebuild the data and the eval set stays correct.

Many cases also carry a trap SQL: a plausible wrong query models actually write
(dropping a HAVING clause, counting zones instead of trips). Its result must NOT
appear in the answer. That distinction — expected present AND trap absent — is
what separates "said a number" from "answered the question".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from dataagent.warehouse import run_sql

GOLDEN_PATH = Path(__file__).resolve().parent.parent / "evals" / "golden.yaml"


@dataclass
class Case:
    id: str
    question: str
    difficulty: str
    expect: str
    reference_sql: str | None = None
    trap_sql: str | None = None
    trap_note: str | None = None
    refuse_keywords: tuple[str, ...] = ()

    @property
    def must_refuse(self) -> bool:
        return self.expect == "refuse"


@dataclass
class Score:
    case_id: str
    correct: bool
    hit_trap: bool
    grounded: bool
    answer: str
    expected: str | None
    seconds: float = 0.0


def load_cases(path: Path | None = None) -> list[Case]:
    raw = yaml.safe_load((path or GOLDEN_PATH).read_text())
    return [
        Case(
            id=c["id"],
            question=c["question"],
            difficulty=c.get("difficulty", "medium"),
            expect=c["expect"],
            reference_sql=c.get("reference_sql"),
            trap_sql=c.get("trap_sql"),
            trap_note=c.get("trap_note"),
            refuse_keywords=tuple(c.get("refuse_keywords", ())),
        )
        for c in raw
    ]


def truth_of(sql: str) -> str | None:
    """Run a reference/trap query and return row 0, column 0 as a string."""
    result = run_sql(sql, row_limit=5)
    if not result.rows:
        return None
    value = result.rows[0][0]
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


_NUMERIC = re.compile(r"^-?\d+(\.\d+)?$")
_NUMBER_TOKEN = re.compile(r"-?\d+(?:\.\d+)?")


def _decimals(value: str) -> int:
    return len(value.split(".")[1]) if "." in value else 0


def value_in_answer(answer: str, value: str) -> bool:
    """Is `value` present in `answer`, allowing for formatting differences?

    Numbers are the hard case. Two failure modes to avoid, pulling opposite ways:

      * Too loose: "3.5" matching inside "13.53", or a tolerance so wide a wrong
        count passes. A loose matcher silently inflates every future score —
        exactly the fabrication this repo is about, one level up.
      * Too strict: rejecting "3.865" when the reference rounded to "3.86". The
        model gave a *more precise* correct answer and we called it wrong.

    The rule: pull every number out of the answer and compare it to the
    reference at the reference's own precision. An integer reference (a count)
    must match exactly. A reference with N decimals matches any answer number
    that rounds to it at N places.
    """
    if not value:
        return False

    if not _NUMERIC.match(value):
        return value.lower() in answer.lower()

    target = float(value)
    ref_places = _decimals(value)
    haystack = answer.replace(",", "").replace("$", "")

    for token in _NUMBER_TOKEN.findall(haystack):
        candidate = float(token)

        if ref_places == 0:
            # A count. Exact, so "69" never passes for "257614" and a near miss
            # never sneaks through on a tolerance.
            if candidate == target:
                return True
            continue

        # A decimal reference. Only trust an answer token that carries its own
        # decimal — "4" must not stand in for an average of 3.86.
        token_places = _decimals(token)
        if token_places == 0:
            continue

        # Agree to within half a unit at the coarser of the two precisions. That
        # accepts 3.865 and 8.13 for references 3.86 and 8.127, while keeping
        # genuinely different values (4.51 vs 4.52) apart.
        places = min(ref_places, token_places)
        if abs(candidate - target) <= 0.5 * 10 ** (-places) + 1e-9:
            return True

    return False


def _normalize(text: str) -> str:
    """Lower-case and straighten smart punctuation.

    Models emit typographic apostrophes ("can't", U+2019), so a keyword written
    with an ASCII apostrophe ("can't") never matches. That mismatch scored real
    refusals as failures — the eval must not be defeated by a curly quote.
    """
    return (
        (text or "")
        .replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
        .lower()
    )


def score_answer(case: Case, answer: str, grounded: bool, seconds: float = 0.0) -> Score:
    if case.must_refuse:
        lowered = _normalize(answer)
        refused = any(_normalize(k) in lowered for k in case.refuse_keywords)
        return Score(case.id, refused, False, grounded, answer, "(a refusal)", seconds)

    expected = truth_of(case.reference_sql) if case.reference_sql else None
    trap = truth_of(case.trap_sql) if case.trap_sql else None

    correct = bool(expected) and value_in_answer(answer, expected)
    hit_trap = bool(trap) and trap != expected and value_in_answer(answer, trap)

    # Quoting the trap value disqualifies the answer even if the right value is
    # also present — "Staten Island, or Queens if you exclude small samples" is
    # not a correct answer to a question that specified the threshold.
    return Score(case.id, correct and not hit_trap, hit_trap, grounded, answer, expected, seconds)


@dataclass
class Report:
    scores: list[Score]
    label: str = ""

    @property
    def total(self) -> int:
        return len(self.scores)

    @property
    def correct(self) -> int:
        return sum(s.correct for s in self.scores)

    @property
    def grounded(self) -> int:
        return sum(s.grounded for s in self.scores)

    @property
    def traps_hit(self) -> int:
        return sum(s.hit_trap for s in self.scores)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0
