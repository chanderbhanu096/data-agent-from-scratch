"""Tests for chapter 08 — retrieval, the contribution, and its honest limits.

The retriever is only useful if it reliably surfaces the real tables out of the
decoys, and only trustworthy if the chapter is straight about where it fails. Both
are tested here — including the value-vs-vocabulary gap the README warns about.
"""

from __future__ import annotations

from dataagent.retrieval import (
    Bm25,
    decoy_cards,
    full_catalog,
    render_for_prompt,
    retrieve,
    warehouse_cards,
)

REAL = {"trips", "zones", "payment_types"}


def test_the_real_tables_hide_among_many_decoys():
    catalog = full_catalog()
    names = {c.name for c in catalog}
    assert REAL <= names
    assert len(catalog) == len(warehouse_cards()) + len(decoy_cards())
    assert len(catalog) > 200, "the haystack has to be big enough to be a problem"


def test_payment_question_retrieves_the_payment_table():
    picked = {c.name for c in retrieve("average tip by payment type", full_catalog(), k=6)}
    assert "payment_types" in picked
    assert "trips" in picked


def test_zone_question_retrieves_the_zone_table():
    picked = {c.name for c in retrieve("which pickup zone has the most trips", full_catalog(), k=6)}
    assert "zones" in picked


def test_a_clean_question_pulls_only_real_tables():
    picked = {c.name for c in retrieve("average tip by payment type", full_catalog(), k=6)}
    assert picked <= REAL, "no enterprise decoy should score on a taxi-vocabulary question"


def test_value_not_vocabulary_is_the_known_gap():
    # 'Manhattan' is a value in zones.borough, not a word in the schema, so a
    # lexical retriever cannot connect the two. This is the limitation the README
    # is explicit about — pinned here so a future embedding upgrade has a target.
    picked = {c.name for c in retrieve("how many trips started in Manhattan", full_catalog(), k=6)}
    assert "trips" in picked
    assert "zones" not in picked


def test_the_rendered_prompt_keeps_the_value_hints():
    picked = retrieve("average tip by payment type", full_catalog(), k=6)
    rendered = render_for_prompt(picked)
    assert "'Credit card'" in rendered, "real tables must stay enriched after retrieval"


def test_bm25_ranks_the_real_table_above_a_decoy():
    catalog = full_catalog()
    index = Bm25(catalog)
    by_name = {c.name: i for i, c in enumerate(catalog)}
    trip_score = index.score("trips distance", by_name["trips"])
    decoy_score = index.score("trips distance", by_name["hr_employee"])
    assert trip_score > decoy_score > -1  # decoy may be 0; the real table must beat it
