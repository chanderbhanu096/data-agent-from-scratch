"""Schema retrieval: find the few tables a question needs, out of hundreds.

`schema_text()` dumps the whole schema into the prompt. That works for three
tables and falls over at three hundred — the schema alone blows the context
window, and burying the two relevant tables in 298 irrelevant ones measurably
hurts the model. So before writing any SQL, we *retrieve*: score every table
against the question and keep the top handful.

The retriever here is lexical (BM25), built from scratch — no embeddings, no
vector store, no network. It is the honest baseline: it understands that
"payment" matches a `payment_types` table because the word is right there, and
nothing more. Chapter 08's README is explicit about where that runs out and why
embeddings are the upgrade. The point is the *seam* — retrieve, then prompt —
which is identical whichever scorer you drop into it.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from dataagent.warehouse import connect, schema_text

_WORD = re.compile(r"[a-z0-9]+")

# Human descriptions for the real tables — the schema can't carry these, and a
# one-line gloss is the single most useful thing a retriever can match against.
_WAREHOUSE_DESCRIPTIONS = {
    "trips": "NYC taxi trips: fares, tips, distance, pickup and dropoff, payment.",
    "zones": "Taxi zone lookup: zone name, borough, service zone.",
    "payment_types": "Payment method lookup: id to name like Credit card, Cash.",
}


@dataclass
class TableCard:
    """Everything the retriever knows about one table — no rows, just identity."""

    name: str
    columns: list[str]
    description: str = ""

    def as_terms(self) -> list[str]:
        """The bag of words a query is scored against: name, columns, gloss.

        Identifiers are split on both non-word characters and snake_case, so
        `payment_type_id` contributes payment, type, id — the words a question
        actually uses.
        """
        text = " ".join([self.name, *self.columns, self.description]).lower()
        return _WORD.findall(text)

    def to_ddl(self) -> str:
        cols = ",\n".join(f"  {c}" for c in self.columns)
        gloss = f"  -- {self.description}\n" if self.description else ""
        return f"CREATE TABLE {self.name} (\n{gloss}{cols}\n);"


def warehouse_cards() -> list[TableCard]:
    """The real tables, introspected, with their human glosses attached."""
    con = connect(read_only=True)
    try:
        tables = [
            r[0]
            for r in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' ORDER BY table_name"
            ).fetchall()
        ]
        cards = []
        for table in tables:
            cols = [
                r[0]
                for r in con.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = ? ORDER BY ordinal_position",
                    [table],
                ).fetchall()
            ]
            cards.append(TableCard(table, cols, _WAREHOUSE_DESCRIPTIONS.get(table, "")))
        return cards
    finally:
        con.close()


# A synthetic enterprise catalog, so the real tables have somewhere to hide. These
# are metadata only — names, columns, a gloss — deliberately drawn from domains
# (HR, finance, CRM, logistics…) that share no vocabulary with taxi questions, so
# a correct retrieval is a real signal and not luck.
_DECOY_DOMAINS = {
    "hr": (
        [
            "employee",
            "manager",
            "department",
            "payroll",
            "leave",
            "benefit",
            "role",
            "review",
            "candidate",
            "onboarding",
        ],
        ["id", "employee_id", "name", "email", "hired_at", "salary", "status"],
    ),
    "finance": (
        [
            "invoice",
            "ledger",
            "budget",
            "expense",
            "vendor",
            "purchase",
            "account",
            "tax_filing",
            "asset",
            "depreciation",
        ],
        ["id", "amount", "currency", "issued_at", "due_at", "status", "account_id"],
    ),
    "crm": (
        [
            "lead",
            "opportunity",
            "contact",
            "campaign",
            "ticket",
            "subscription",
            "churn",
            "nps_survey",
            "quote",
            "renewal",
        ],
        ["id", "customer_id", "stage", "created_at", "owner", "value", "source"],
    ),
    "logistics": (
        [
            "warehouse",
            "shipment",
            "inventory",
            "supplier",
            "carrier",
            "return",
            "pallet",
            "route_plan",
            "dock",
            "restock",
        ],
        ["id", "sku", "quantity", "location", "shipped_at", "carrier_id", "status"],
    ),
    "product": (
        [
            "feature_flag",
            "release",
            "experiment",
            "usage_event",
            "session",
            "device",
            "app_version",
            "crash_report",
            "cohort",
            "funnel",
        ],
        ["id", "user_id", "flag", "created_at", "platform", "value", "variant"],
    ),
}


def decoy_cards(per_domain: int = 50) -> list[TableCard]:
    """Deterministic filler tables — same set every run, so tests are stable."""
    cards: list[TableCard] = []
    for domain, (nouns, base_cols) in _DECOY_DOMAINS.items():
        for i in range(per_domain):
            noun = nouns[i % len(nouns)]
            suffix = "" if i < len(nouns) else f"_{i // len(nouns) + 1}"
            name = f"{domain}_{noun}{suffix}"
            cards.append(
                TableCard(
                    name,
                    list(base_cols),
                    f"{domain} system: {noun.replace('_', ' ')} records.",
                )
            )
    return cards


def full_catalog(per_domain: int = 50) -> list[TableCard]:
    """The real tables plus the decoys — the haystack the retriever searches."""
    return warehouse_cards() + decoy_cards(per_domain)


# ── BM25, from scratch ────────────────────────────────────────────────────────


@dataclass
class Bm25:
    """A tiny BM25 over table cards. Built once, queried many times.

    BM25 rewards a query term that is frequent in a table and rare across the
    catalog, with diminishing returns and a correction for table size. That is
    the whole idea; the constants k1 and b are the usual defaults.
    """

    cards: list[TableCard]
    k1: float = 1.5
    b: float = 0.75
    _docs: list[list[str]] = field(default_factory=list)
    _df: Counter = field(default_factory=Counter)
    _avg_len: float = 0.0

    def __post_init__(self) -> None:
        self._docs = [c.as_terms() for c in self.cards]
        for doc in self._docs:
            for term in set(doc):
                self._df[term] += 1
        self._avg_len = (sum(len(d) for d in self._docs) / len(self._docs)) if self._docs else 0.0

    def _idf(self, term: str) -> float:
        n = len(self._docs)
        df = self._df.get(term, 0)
        # Standard BM25 idf, floored at zero so a term in every table can't push
        # a score negative.
        return max(0.0, math.log((n - df + 0.5) / (df + 0.5) + 1.0))

    def score(self, query: str, doc_index: int) -> float:
        terms = _WORD.findall(query.lower())
        doc = self._docs[doc_index]
        if not doc:
            return 0.0
        counts = Counter(doc)
        length = len(doc)
        total = 0.0
        for term in terms:
            tf = counts.get(term, 0)
            if not tf:
                continue
            denom = tf + self.k1 * (1 - self.b + self.b * length / self._avg_len)
            total += self._idf(term) * (tf * (self.k1 + 1)) / denom
        return total

    def top_k(self, query: str, k: int = 5) -> list[tuple[TableCard, float]]:
        scored = [(self.cards[i], self.score(query, i)) for i in range(len(self.cards))]
        scored = [pair for pair in scored if pair[1] > 0]
        scored.sort(key=lambda p: p[1], reverse=True)
        return scored[:k]


def retrieve(question: str, cards: list[TableCard], k: int = 5) -> list[TableCard]:
    """The seam: question in, the k most relevant tables out."""
    return [card for card, _ in Bm25(cards).top_k(question, k)]


def render_schema(cards: list[TableCard]) -> str:
    """Just the retrieved tables, as DDL, ready to drop into a prompt."""
    return "\n\n".join(card.to_ddl() for card in cards)


def render_for_prompt(cards: list[TableCard]) -> str:
    """Render retrieved tables for the agent, keeping the real ones enriched.

    A retrieved real table is rendered by `schema_text` so it still carries its
    value hints (the 'Credit card' casing fix from earlier); a retrieved decoy
    has no data to profile, so it falls back to plain DDL.
    """
    real = {c.name for c in warehouse_cards()}
    real_retrieved = [c.name for c in cards if c.name in real]
    blocks = []
    if real_retrieved:
        blocks.append(schema_text(only=real_retrieved))
    blocks.extend(c.to_ddl() for c in cards if c.name not in real)
    return "\n\n".join(blocks)
