# 08 — Schema retrieval

```bash
python chapters/08_schema_retrieval/run.py

# benchmark it (Azure reference model):
python scripts/run_evals.py --agent=05 --agent=08 --runs=3
```

Every chapter so far handed the model the **whole** schema. That is a three-table luxury.
A real warehouse has hundreds of tables, and two things break at once:

1. **It doesn't fit.** Dump this chapter's 253-table catalog and you've spent ~9,000 tokens on
   schema before the question is even asked — on a real warehouse, more than the window holds.
2. **Even when it fits, it hurts.** Bury `trips` and `zones` among 250 irrelevant tables and the
   model picks the wrong ones. It's a needle-in-a-haystack you built for yourself.

So we stop dumping and start **retrieving**: score every table against the question, keep the
few that matter, and prompt with only those. The agent is Chapter 05's exact loop — the single
change is the schema it's handed.

## The seam: retrieve, then prompt

```python
retrieved = retrieve(question, full_catalog(), k)  # score 253 tables, keep the top few
system = build_system_prompt(schema=render_for_prompt(retrieved))
return run_agent(llm, question, tools=TOOLS, system=system)  # Chapter 05, unchanged
```

That's the whole idea, and it's the shape every "RAG" system has under the branding: retrieve
context, then generate. Swap the retriever and nothing downstream changes.

## The retriever is BM25, built from scratch

No embeddings, no vector database, no network — `dataagent/retrieval.py` is ~100 lines of
lexical scoring. BM25 rewards a query term that is frequent in a table and rare across the
catalog: "payment" hits `payment_types` hard because the word is right there and nowhere else.

```
Q What is the average tip by payment type?   → payment_types, trips
Q Which pickup zone has the most trips?       → trips, zones
```

It is the honest baseline. You can read every line and know exactly why a table was chosen.

## Where lexical retrieval runs out — stated plainly

Two failures show up the moment you look, and the chapter keeps them in view instead of hiding
them behind a cherry-picked demo:

- **Values aren't vocabulary.** *"How many trips started in Manhattan?"* retrieves `trips` but
  **not** `zones` — because "Manhattan" is a value in `zones.borough`, not a word in the schema.
  A lexical matcher cannot know that. This is the single clearest argument for embeddings, and
  there's a test pinning the gap (`test_value_not_vocabulary_is_the_known_gap`) so an upgrade has
  a target.
- **Ambiguous words pull in noise.** *"…total amount over 100 dollars"* also drags in
  `finance_invoice`, `finance_ledger` and friends, because "amount" lives in both worlds. The
  real table still ranks first; the decoys are just noise a stronger model has to ignore.

Embeddings fix the first by matching meaning, not spelling. That's the next tier — and because
the seam is unchanged, it's a drop-in swap, not a rewrite.

## Did it work? Measured on the reference model.

The test: does retrieving from 253 tables keep the accuracy you'd get by handing the model a
clean, hand-picked three-table schema? Golden set, `--runs=3`, on the Azure reference model:

| Agent | Schema it sees | Accuracy | Grounded |
|-------|----------------|---------:|---------:|
| **05** — plain loop | the 3 real tables, hand-picked | 94% (48/51) | 45/51 |
| **08** — retrieve, then answer | top-k of **253** tables, chosen by BM25 | 94% (48/51) | 48/51 |

**Identical accuracy — and that is the win.** Retrieval didn't make the model smarter; it kept
it exactly as good while the schema grew 84× (3 hand-picked tables → 253). That's the whole
value: without retrieval, scaling the catalog either overflows the prompt or drowns the right
tables in noise; with it, the agent performs as if you'd hand-picked the schema for every
question. Grounding even ticked *up* (45 → 48) — a focused schema gives the model less
irrelevant surface to hallucinate against. Retrieval is not an accuracy booster. It is what lets
everything you already built keep working when the warehouse is real.

## Exercise

1. Turn off retrieval: prompt agent 08 with the *entire* 253-table catalog and re-run the evals.
   Watch accuracy fall (or the request overflow). That regression is the whole reason this
   chapter exists.
2. Swap BM25 for embeddings (e.g. an Ollama embed model) behind the same `retrieve()` signature.
   Does *"trips in Manhattan"* now find `zones`? Measure the value-vocabulary gap closing.
3. Add a decoy table named `taxi_surge_pricing` and ask about surge pricing. Does the retriever
   correctly return *nothing useful* — and does the agent decline rather than invent?

---

Next: **09 — Routing**, where cheap questions go to a cheap model and only the hard ones pay for
a frontier one — measured, so "cheaper" is a number, not a hope.
