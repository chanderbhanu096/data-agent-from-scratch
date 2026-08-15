"""Few-shot retrieval: show the model a few solved questions like this one.

A weak model doesn't fail for lack of instructions — Chapter 06 proved that. It
fails because it hasn't *seen* the shape of the answer: which tables join, how a
threshold becomes a HAVING clause, that 'Cash' is capitalised. Few-shot fixes
that the way you'd teach a person — with worked examples.

The retrieval is the same BM25 from Chapter 08, pointed at a library of solved
question→SQL pairs instead of tables. For a new question we pull the handful most
similar and put them in the prompt. The examples (`evals/examples.yaml`) are
deliberately *not* the eval questions: they teach the pattern, never the answer,
so a gain on the held-out golden set is generalisation, not leakage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from dataagent.retrieval import Bm25

_WORD = re.compile(r"[a-z0-9]+")
_EXAMPLES_PATH = Path(__file__).resolve().parent.parent / "evals" / "examples.yaml"


@dataclass
class Example:
    """One solved question and the SQL that answers it."""

    question: str
    sql: str

    def as_terms(self) -> list[str]:
        # Matches the interface BM25 scores against — here, the question's words.
        return _WORD.findall(self.question.lower())


@lru_cache(maxsize=1)
def load_examples(path: str | None = None) -> tuple[Example, ...]:
    raw = yaml.safe_load(Path(path or _EXAMPLES_PATH).read_text())
    return tuple(Example(e["question"], e["sql"].strip()) for e in raw)


def retrieve_examples(question: str, k: int = 3) -> list[Example]:
    """The k solved questions most similar to this one, by BM25."""
    examples = list(load_examples())
    return [ex for ex, _ in Bm25(examples).top_k(question, k)]


def render_examples(examples: list[Example]) -> str:
    """A prompt block: patterns to follow, explicitly not answers to copy."""
    if not examples:
        return ""
    blocks = [
        "Worked examples — follow the pattern, do not copy the values:",
    ]
    for ex in examples:
        blocks.append(f"\n-- {ex.question}\n{ex.sql}")
    return "\n".join(blocks)
