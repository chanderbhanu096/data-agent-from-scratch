# 13 — Embeddings

```bash
python chapters/13_embeddings/run.py
```

Chapter 08 found the right table out of 253 with **BM25** — it matches *words*. Its ceiling
is a sentence you've heard before: you ask about *"expensive rides"*, the column is called
`total_amount`, and they share **zero words**. A word-matcher can't connect them. This chapter
swaps in a scorer that matches **meaning** — and then measures, honestly, how much that's
actually worth.

## What an embedding is (one paragraph)

An embedding turns text into a **vector** — a point in space — positioned so that things which
*mean* similar things land near each other, whether or not they share words. Retrieval becomes
geometry: embed the question, embed every table, return the nearest tables. The seam is
identical to Chapter 08 (retrieve → prompt); only the ruler changes.

## Three ways to get the vectors — all built, all measured

The user asked to see all of them and what each buys, so all three ship behind one interface,
and BM25 stays on the board as the baseline:

| `DATAAGENT_EMBEDDER` | What draws the map | Offline? | Key? | Extra install |
|---|---|:--:|:--:|---|
| `lsa` | **From scratch, numpy only.** TF-IDF + truncated SVD (classic Latent Semantic Analysis) | ✅ | ✅ none | none |
| `model` | A pre-trained sentence-transformer (`all-MiniLM-L6-v2`, ~90MB) | ✅ | ✅ none | `pip install -e ".[embeddings]"` |
| `api` | The provider's embedding endpoint | ❌ | ❌ needs key | your provider SDK |

**The default is "best available."** With no `DATAAGENT_EMBEDDER` set, the agent uses `model`
when you've installed `[embeddings]` (best output out of the box) and falls back to `lsa` on a
bare clone — so it's never a crash, and installing the extra is how you opt into the stronger
one. Set `DATAAGENT_EMBEDDER` explicitly to pin a specific method for a fair comparison.

## The measurement

13 paraphrased questions, each answerable by one real table hidden in the 253-table catalog.
Two blocks: the first shares a word with the target (BM25's home turf); the second is **pure
paraphrase — no shared word at all**, where only real meaning can win. Metric: did the right
table land at rank 1 / in the top 3, across all 13.

| method | recall@1 | recall@3 | MRR | what it tells you |
|--------|:--------:|:--------:|:---:|-------------------|
| **bm25** (words) | 62% | 62% | 0.62 | the lexical baseline from Chapter 08 |
| **lsa** (from scratch) | 62% | 62% | 0.62 | **identical to BM25 — the honest headline** |
| **model** (pre-trained) | **92%** | **92%** | **0.94** | meaning, learned from the world |
| **api** (endpoint) | — | — | — | run it with your key (below) |

*(Numbers are printed live by `run.py`; the `api` row fills in once you point it at an embedding
deployment. `recall@1 == recall@3` throughout because these methods, on this task, either nail
the table at rank 1 or miss the top 3 entirely — there's little middle ground.)*

### Why LSA ties BM25 instead of beating it — and why that's the lesson

You'd expect "embeddings" to beat "keywords." They don't here, and the reason is the whole
point: **LSA learns its meaning from the catalog itself.** Its entire vocabulary is the words
your 253 tables happen to use. "expensive", "cost", "money" appear in *none* of them, so LSA's
vector for "expensive rides" is built from nothing — it's blind to exactly the synonyms it was
supposed to rescue. From-scratch embeddings don't manufacture world knowledge; they reorganise
the words you already had.

The pre-trained `model` was trained on a large slice of the internet, so it *already knows*
`expensive ≈ costly ≈ amount ≈ fare` before it ever sees your schema. That prior is the entire
92% − 62% = **30-point gap**. It's not a cleverer algorithm — it's knowledge the from-scratch
version has no way to have.

The single clearest frame, straight from the run — top-3 for `"expensive rides"` (answer:
`trips`):

```
bm25   (nothing scored > 0)                              ← no shared word, no result
lsa    ['payment_types', 'logistics_route_plan', ...]    ← guesses; "expensive" is invisible to it
model  ['trips', 'product_usage_event_3', ...]           ← trips at #1
```

## Turning on the other two

**`model` — the semantic win, still offline:**

```bash
pip install -e ".[embeddings]"
DATAAGENT_EMBEDDER=model python chapters/13_embeddings/run.py
```

**`api` — best quality, needs a key.** Create an *embedding* deployment (e.g.
`text-embedding-3-small`) and point at it:

```bash
# Azure
AZURE_OPENAI_EMBED_DEPLOYMENT=text-embedding-3-small
DATAAGENT_EMBEDDER=api python chapters/13_embeddings/run.py
# OpenAI: set OPENAI_API_KEY and OPENAI_EMBED_MODEL instead
```

## Where this stays honest

- **This measures retrieval, not the final answer.** Getting the right table in front of the
  model is necessary, not sufficient — the SQL still has to be right (that's the eval harness).
- **LSA isn't useless — it's *bounded*.** On a corpus with rich, repeated domain text it recovers
  real structure. On 253 terse table cards it has too little to learn from. Knowing *why* it
  ties BM25 is worth more than a number that just says it did.
- **The `model` numbers depend on the model.** A bigger embedder scores higher and costs more
  memory; the point is the *shape* of the gap, not the exact 92%.
- **"Offline" has a size.** The `model` option keeps you key-free but pulls in torch (~hundreds
  of MB). That's the real, non-zero price of the semantic win — named, not hidden.

## Exercise

1. Add a question whose answer needs a synonym the catalog *does* contain (e.g. "gratuity" only
   works if a table says "tip"). Watch which methods get it.
2. Bump `LsaEmbedder(dim=...)`. Does more dimensions help on this tiny corpus, or just add noise?
3. Feed LSA a *bigger* corpus — concatenate each table's rows' text, not just its column names.
   Does its recall move toward the model's? That's the co-occurrence signal getting the data it
   was missing.

---

Next: **an MCP server** — so far every tool has lived in this repo. MCP is the wire protocol that
lets the agent call tools it didn't ship with: a separate process, a standard interface, the
same `execute()` seam from Chapter 04 — now across a socket.
