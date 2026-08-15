"""Embeddings: retrieval by meaning, three ways behind one interface.

Chapter 08 retrieved tables with BM25 — it matches *words*. "expensive rides"
shares no word with `total_amount`, so a lexical scorer never connects them. An
embedding turns text into a vector whose *position* encodes meaning: near
vectors mean near meanings, shared words or not. Retrieve by cosine distance
instead of word overlap and the seam downstream (retrieve → prompt) is unchanged.

Three ways to get the vectors, same `Embedder` interface, so the retriever never
learns which one it got:

    lsa    From scratch, numpy only. TF-IDF + truncated SVD — the classic
           pre-neural embedding (latent semantic analysis). It learns latent
           structure from how words co-occur *in the catalog itself*. No model,
           no key, no network. The honest limit: it only knows words that appear
           in your tables, so a synonym the catalog never uses is invisible to
           it. This is the default.

    model  A small pre-trained sentence-transformer (~90MB, runs offline). Real
           semantic quality — it was trained on the world, so it knows
           "expensive" ~ "amount" without either appearing together in your data.
           Needs `pip install sentence-transformers`.

    api    The provider's embedding endpoint. Best quality, needs a key + network
           — the only option that breaks "runs offline".

Every embedder returns L2-normalised rows, so cosine similarity is a plain dot
product. Which one is worth its cost is not asserted here — chapter 13 measures
it. ponytail: the retriever, the metric, and the seam are shared; only the
vectors differ.
"""

from __future__ import annotations

import math
import os
from collections import Counter
from typing import Protocol

import numpy as np

from dataagent.retrieval import _WORD, TableCard


def card_text(card: TableCard) -> str:
    """The text an embedder sees for a table: its own bag of words, joined."""
    return " ".join(card.as_terms())


def _l2_normalize(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0  # a zero row (all-OOV) stays zero, no div-by-zero
    return m / norms


class Embedder(Protocol):
    name: str

    def fit(self, corpus: list[str]) -> Embedder: ...

    def encode(self, texts: list[str]) -> np.ndarray: ...


class LsaEmbedder:
    """Latent Semantic Analysis from scratch: TF-IDF, then truncated SVD.

    `fit` learns the vocabulary, the IDF weights, and the SVD basis from the
    corpus. `encode` projects any text (a table or a query) into that same
    low-dimensional space, so documents and questions become comparable. The
    semantics are entirely co-occurrence: two terms that appear in similar tables
    end up with similar directions. Nothing is pre-trained — which is the point
    and the ceiling.
    """

    name = "lsa"

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim
        self.vocab: dict[str, int] = {}
        self.idf: np.ndarray = np.zeros(0)
        self.components: np.ndarray = np.zeros((0, 0))  # (terms, dim)

    def _tfidf(self, texts: list[str]) -> np.ndarray:
        rows = np.zeros((len(texts), len(self.vocab)), dtype=np.float64)
        for r, text in enumerate(texts):
            counts = Counter(t for t in _WORD.findall(text.lower()) if t in self.vocab)
            for term, tf in counts.items():
                rows[r, self.vocab[term]] = tf
        return rows * self.idf  # broadcast idf across columns

    def fit(self, corpus: list[str]) -> LsaEmbedder:
        docs = [[t for t in _WORD.findall(text.lower())] for text in corpus]
        df: Counter = Counter()
        for doc in docs:
            for term in set(doc):
                df[term] += 1
        self.vocab = {term: i for i, term in enumerate(sorted(df))}
        n = len(corpus)
        idf = np.zeros(len(self.vocab))
        for term, i in self.vocab.items():
            idf[i] = math.log((1 + n) / (1 + df[term])) + 1.0  # smoothed idf
        self.idf = idf

        x = self._tfidf(corpus)  # (docs, terms)
        # Economy SVD: X ≈ U·S·Vᵀ. The right singular vectors V (terms × dim) are
        # the semantic basis; project anything into it with `text_tfidf @ V`.
        _u, _s, vt = np.linalg.svd(x, full_matrices=False)
        self.components = vt[: self.dim].T
        return self

    def encode(self, texts: list[str]) -> np.ndarray:
        if self.components.size == 0:
            raise RuntimeError("LsaEmbedder.encode called before fit().")
        return _l2_normalize(self._tfidf(texts) @ self.components)


class ModelEmbedder:
    """A pre-trained sentence-transformer. Offline, but not from scratch.

    This is where real semantics come from: the model saw enough text to learn
    that "fare", "cost", and "amount" live together, without any of them
    appearing in your catalog. `fit` is a no-op — nothing to learn here.
    """

    name = "model"

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            # Keep the demo output clean — no progress bars, no hub rate-limit chatter.
            import logging

            os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
            os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
            logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:  # pragma: no cover - depends on optional dep
                raise RuntimeError(
                    "The 'model' embedder needs sentence-transformers: "
                    "pip install sentence-transformers"
                ) from e
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def fit(self, corpus: list[str]) -> ModelEmbedder:
        return self

    def encode(self, texts: list[str]) -> np.ndarray:
        vecs = self._load().encode(
            texts, normalize_embeddings=True, show_progress_bar=False
        )
        return np.asarray(vecs, dtype=np.float64)


class ApiEmbedder:
    """The provider's embedding endpoint (OpenAI / Azure). Best quality, needs a key.

    Reuses the same client wiring as the chat gateway. `fit` is a no-op. The
    model is a *deployment* name on Azure (set AZURE_OPENAI_EMBED_DEPLOYMENT) and
    a model id on OpenAI (OPENAI_EMBED_MODEL, default text-embedding-3-small).
    """

    name = "api"

    def __init__(self, provider: str = "openai") -> None:
        self.provider = provider

    def _client_and_model(self):
        from openai import OpenAI

        if self.provider == "azure":
            from dataagent.llm import _azure_base_url

            endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
            client = OpenAI(
                base_url=_azure_base_url(endpoint),
                api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            )
            model = os.getenv("AZURE_OPENAI_EMBED_DEPLOYMENT")
            if not model:
                raise RuntimeError(
                    "Set AZURE_OPENAI_EMBED_DEPLOYMENT to an embedding deployment "
                    "(e.g. text-embedding-3-small) to use the 'api' embedder on Azure."
                )
            return client, model
        return OpenAI(), os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

    def fit(self, corpus: list[str]) -> ApiEmbedder:
        return self

    def encode(self, texts: list[str]) -> np.ndarray:
        client, model = self._client_and_model()
        resp = client.embeddings.create(model=model, input=texts)
        return _l2_normalize(np.asarray([d.embedding for d in resp.data], dtype=np.float64))


def get_embedder(name: str | None = None, *, provider: str = "openai") -> Embedder:
    """Pick an embedder by name (default: DATAAGENT_EMBEDDER, else 'lsa')."""
    name = (name or os.getenv("DATAAGENT_EMBEDDER", "lsa")).lower()
    if name == "lsa":
        return LsaEmbedder()
    if name == "model":
        return ModelEmbedder()
    if name == "api":
        return ApiEmbedder(provider=provider)
    raise ValueError(f"unknown embedder '{name}' — use lsa, model, or api.")


class SemanticIndex:
    """Embed the catalog once, then rank tables against a query by cosine.

    The BM25 analogue from chapter 08, meaning-based. Fit is done up front so a
    benchmark over many questions embeds the 253 cards a single time.
    """

    def __init__(self, cards: list[TableCard], embedder: Embedder) -> None:
        self.cards = cards
        corpus = [card_text(c) for c in cards]
        self.embedder = embedder.fit(corpus)
        self.matrix = self.embedder.encode(corpus)  # (n_cards, dim)

    def top_k(self, query: str, k: int = 5) -> list[tuple[TableCard, float]]:
        q = self.embedder.encode([query])  # (1, dim)
        sims = (self.matrix @ q.T).ravel()
        order = np.argsort(-sims)[:k]
        return [(self.cards[i], float(sims[i])) for i in order]
