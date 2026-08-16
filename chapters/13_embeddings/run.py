"""Chapter 13 — Embeddings: retrieve by meaning, and measure what it buys.

    python chapters/13_embeddings/run.py

Chapter 08 retrieved tables with BM25 — it matches words. This chapter swaps the
scorer for one that matches *meaning*, three different ways, and puts all of them
on the same scoreboard against BM25 so you can see exactly how much each is worth:

    bm25   the lexical baseline from chapter 08 (words only)
    lsa    embeddings from scratch, numpy only (TF-IDF + SVD) — the default
    model  a small pre-trained sentence-transformer (needs the optional dep)
    api    the provider's embedding endpoint (needs a key)

The task: given a paraphrased question, find the right *real* table hidden in a
253-table catalog. Some questions share a word with the table (BM25's home turf);
some are pure paraphrase with no shared word at all (where only real semantics
help). The numbers below are computed live — nothing here is asserted.

ponytail: one catalog, one metric, one seam. Only the vectors change. Methods
whose dependency or key is missing are skipped and named, not faked.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import os

from rich.console import Console
from rich.table import Table

from dataagent.cli import run_chapter
from dataagent.embeddings import SemanticIndex, get_embedder
from dataagent.retrieval import Bm25, TableCard, full_catalog

console = Console()

# (question, the table that actually answers it). The first block shares a word
# with the target (lexical anchor); the second block is pure paraphrase — no
# shared word — so only genuine semantics can win it.
EVAL: list[tuple[str, str]] = [
    # lexical anchor present — BM25 should already do well
    ("total amount collected in fares", "trips"),
    ("how much passengers tip drivers", "trips"),
    ("distance travelled on each journey", "trips"),
    ("which borough each zone sits in", "zones"),
    ("taxi service area names", "zones"),
    ("credit card or cash", "payment_types"),
    ("the different methods used to pay", "payment_types"),
    ("employee salary and payroll records", "hr_payroll"),
    ("vendor invoices and their amounts", "finance_invoice"),
    # pure paraphrase — no shared word with the target table
    ("expensive rides", "trips"),
    ("where did the cab let people out", "trips"),
    ("neighbourhoods of the city", "zones"),
    ("ways a customer can settle the bill", "payment_types"),
]


def _bm25_ranking(bm: Bm25, query: str, n: int) -> list[str]:
    return [c.name for c, _ in bm.top_k(query, k=n)]  # positive-score only


def _semantic_ranking(index: SemanticIndex, query: str, n: int) -> list[str]:
    return [c.name for c, _ in index.top_k(query, k=n)]


def _rank_of(names: list[str], gold: str) -> int | None:
    return names.index(gold) + 1 if gold in names else None


def _score(ranker, n: int) -> dict[str, float]:
    r1 = r3 = 0
    mrr = 0.0
    for question, gold in EVAL:
        rank = _rank_of(ranker(question, n), gold)
        if rank is not None:
            r1 += rank == 1
            r3 += rank <= 3
            mrr += 1.0 / rank
    total = len(EVAL)
    return {
        "recall@1": r1 / total,
        "recall@3": r3 / total,
        "mrr": mrr / total,
    }


def _available_embedders(
    provider: str, cards: list[TableCard]
) -> list[tuple[str, object | None, str]]:
    """(name, built index or None, note). None index → skipped, note says why.

    Built once and reused for both the scoreboard and the worked example — the
    model embedder loads ~90MB, and loading it twice is exactly the waste this
    repo argues against.
    """
    out: list[tuple[str, object | None, str]] = []
    for name in ("lsa", "model", "api"):
        try:
            index = SemanticIndex(cards, get_embedder(name, provider=provider))
            out.append((name, index, "default" if name == "lsa" else "available"))
        except Exception as e:  # noqa: BLE001 — any build failure means "skip and name it", never crash the board
            out.append((name, None, str(e).split("\n")[0][:60]))
    return out


def main() -> None:
    provider = os.getenv("DATAAGENT_PROVIDER", "ollama")
    console.print("[bold cyan]Embeddings — retrieve by meaning, measured against BM25[/bold cyan]")
    console.print(f"[dim]{len(EVAL)} paraphrased questions · 253-table catalog[/dim]\n")

    cards: list[TableCard] = full_catalog()
    n = len(cards)
    bm = Bm25(cards)
    embedders = _available_embedders(provider, cards)

    rows: list[tuple[str, dict[str, float] | None, str]] = [
        ("bm25", _score(lambda q, k: _bm25_ranking(bm, q, k), n), "lexical baseline"),
    ]
    for name, index, note in embedders:
        if index is None:
            rows.append((name, None, note))
            continue
        rows.append((name, _score(lambda q, k, ix=index: _semantic_ranking(ix, q, k), n), note))

    table = Table(title="Find the right table in 253 — higher is better", title_style="bold")
    table.add_column("method")
    for col in ("recall@1", "recall@3", "MRR"):
        table.add_column(col, justify="right")
    table.add_column("note", style="dim")
    for name, scores, note in rows:
        if scores is None:
            table.add_row(name, "[dim]—[/dim]", "[dim]—[/dim]", "[dim]—[/dim]", f"skipped: {note}")
        else:
            table.add_row(
                name,
                f"{scores['recall@1']:.0%}",
                f"{scores['recall@3']:.0%}",
                f"{scores['mrr']:.2f}",
                note,
            )
    console.print(table)

    # Make it concrete: a pure-paraphrase question, top-3 per available method.
    demo_q = "expensive rides"
    console.print(
        f'\n[bold]Top-3 for a word-free paraphrase:[/bold] "{demo_q}" [dim](answer: trips)[/dim]'
    )
    console.print(
        f"  [cyan]bm25[/cyan]  {_bm25_ranking(bm, demo_q, 3) or '[dim](nothing scored > 0)[/dim]'}"
    )
    for name, index, _note in embedders:
        if index is not None:
            console.print(f"  [cyan]{name:<5}[/cyan] {_semantic_ranking(index, demo_q, 3)}")

    console.print(
        "\n  [dim]Read the gap between the two question blocks: BM25 and LSA both lean on words "
        "the catalog already uses; only a model trained on the world reliably wins the paraphrases.[/dim]"
    )


if __name__ == "__main__":
    run_chapter(main)
