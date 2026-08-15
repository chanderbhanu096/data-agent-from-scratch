"""Tests for chapter 13 — embeddings.

Only the from-scratch LSA path is tested: it's deterministic, numpy-only, needs
no network or key, and it's the default. The model/api embedders are thin
wrappers over external systems — testing those would test sentence-transformers
and OpenAI, not this repo. What's asserted here is the machinery: fit/encode
shapes, unit vectors, that projection is meaningful, and that a synonym the
corpus never uses is invisible to LSA — the honest ceiling the chapter measures.
"""

from __future__ import annotations

import numpy as np
import pytest

from dataagent.embeddings import (
    LsaEmbedder,
    SemanticIndex,
    card_text,
    get_embedder,
)
from dataagent.retrieval import TableCard, full_catalog

CORPUS = [
    "fare amount tip total distance trip payment",
    "zone borough service area name",
    "payment method credit card cash type",
    "employee salary payroll department manager",
    "invoice vendor amount ledger account",
]


def test_default_embedder_is_lsa():
    assert get_embedder().name == "lsa"


def test_unknown_embedder_is_rejected():
    with pytest.raises(ValueError):
        get_embedder("word2vec")


def test_fit_then_encode_returns_unit_rows_of_the_right_shape():
    emb = LsaEmbedder(dim=4).fit(CORPUS)
    vecs = emb.encode(CORPUS)
    assert vecs.shape == (len(CORPUS), 4)
    norms = np.linalg.norm(vecs, axis=1)
    # Every row is unit length (a zero row would be exactly 0, not near 1).
    assert np.allclose(norms, 1.0, atol=1e-9)


def test_encode_before_fit_is_an_error():
    with pytest.raises(RuntimeError):
        LsaEmbedder().encode(["anything"])


def test_projection_reflects_co_occurrence():
    # LSA's whole claim: shared vocabulary pulls vectors together. The invoice
    # card and the trips card both say "amount"; the payroll card shares nothing
    # with invoice — so invoice should sit closer to trips than to payroll.
    emb = LsaEmbedder(dim=4).fit(CORPUS)
    trips, payroll, invoice = emb.encode(CORPUS)[[0, 3, 4]]
    assert float(invoice @ trips) > float(invoice @ payroll)


def test_a_word_the_corpus_never_uses_is_invisible_to_lsa():
    # LSA only knows the corpus vocabulary. "expensive" appears nowhere, so its
    # query vector is all-zero — the ceiling the chapter measures against.
    emb = LsaEmbedder(dim=4).fit(CORPUS)
    assert np.allclose(emb.encode(["expensive"]), 0.0)
    assert not np.allclose(emb.encode(["fare amount"]), 0.0)


def test_semantic_index_ranks_the_lexically_obvious_table_first():
    cards = full_catalog()
    index = SemanticIndex(cards, LsaEmbedder())
    top = [c.name for c, _ in index.top_k("borough and zone name", k=3)]
    assert "zones" in top


def test_card_text_is_the_cards_own_terms():
    card = TableCard("payment_types", ["payment_type_id", "payment_type"], "credit card cash")
    text = card_text(card)
    assert "payment" in text and "credit" in text
