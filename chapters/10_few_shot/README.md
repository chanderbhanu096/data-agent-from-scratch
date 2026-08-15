# 10 — Few-shot examples

```bash
python chapters/10_few_shot/run.py

# benchmark it — the point is the cheap tier, so measure there and on Azure:
DATAAGENT_PROVIDER=ollama python scripts/run_evals.py --agent=05 --agent=10 --runs=3
```

Chapter 06 proved that *telling* a weak model the rules doesn't work. This chapter is the
thing that does: not rules, **examples**. Before the model writes SQL, retrieve a few solved
questions shaped like this one and put them in the prompt — the way anyone learns a query
language, by reading queries.

It's the same move as Chapter 08, one layer over: BM25, but the corpus is a library of solved
question→SQL pairs instead of tables.

```python
examples = retrieve_examples(question, k=3)              # BM25 over solved Q→SQL pairs
system   = build_system_prompt() + render_examples(examples)
return run_agent(llm, question, tools=TOOLS, system=system)   # Chapter 05, unchanged
```

## The honesty that makes the number mean something

The failure mode of every few-shot demo is **leakage**: retrieve a question's own answer as an
"example" and you've measured memorisation, then called it intelligence. So the examples
(`evals/examples.yaml`) are a *separate* set, disjoint from the golden questions — checked by a
test that fails if they ever overlap, and by a second test that runs every example's SQL against
the warehouse. They teach the pattern (a borough join, a `HAVING` threshold, the `'Cash'`
casing); they are never the answer.

For the threshold question in the demo, none of the three retrieved examples *is* the question —
but between them they carry every piece it needs:

```
~ Which pickup borough has the lowest average fare?              (borough join, ranked average)
~ What is the average total amount by pickup borough,            (GROUP BY borough + HAVING count)
    for boroughs with over 2000 trips?
~ What is the average tip for trips longer than 5 miles?         (an average with a filter)
```

## Did it work? Measured — and the honest answer is "it's complicated."

| Model | plain (05) | + few-shot (10) | Δ |
|-------|-----------:|----------------:|:--|
| **cheap tier** — free local `qwen2.5:3b` | 47% (16/34) | 50% (17/34) | +3% |
| **reference** — Azure `gpt-chat-latest` | 97% (33/34) | 97% (33/34) | +0% |

If you stopped at the totals you'd call few-shot useless: nothing on the frontier model (it's at
the ceiling already), and a rounding-error +3% on the cheap one. **But the total is a lie of
averages.** Look at what actually moved on the cheap tier:

| Few-shot **helped** | Few-shot **hurt** |
|---------------------|-------------------|
| `dropoff_borough_avg_total` 0/2 → **2/2** | `manhattan_trip_count` 2/2 → 1/2 |
| `top_zone_longest_trips` 0/2 → 1/2 | `queens_trip_count` 2/2 → 1/2 |
| `top_payment_type_by_tip` 0/2 → 1/2 | `card_trips_manhattan` 1/2 → 0/2 |

Four cases up, four down — a wash that hides a clear signal. Few-shot **helped the questions that
needed a pattern the model was missing** (a borough join with a `HAVING` threshold — `dropoff_borough`
went from never to always) and **hurt the ones that didn't** (a plain `count` of Manhattan trips,
which the model got right until three join-heavy examples talked it into overcomplicating).

That is the real lesson, and you only get it by reading past the average:

> Few-shot is not free context. An example the question doesn't need is a **distraction**, and on
> an easy question a distraction is a regression.

The fix isn't more examples — it's *relevance and restraint*: give few-shot to the questions that
lack the pattern, and leave the easy ones alone. Which is to say: **route your few-shot** (Chapter
09), don't spray it. (n=2 here; the simple-count dips are partly variance, but the
`dropoff_borough` gain repeats across runs — that one is real.)

## Why this chapter comes after routing

Chapter 09 sent the *hard* questions to the paid tier. Those are exactly the ones few-shot helps —
the joins and thresholds a 3B model hasn't internalised — and exactly the ones where an extra
example is worth its distraction. Applied there and not on the easy counts, few-shot is the lever
that lets the cheap tier keep more of what routing would otherwise escalate. Retrieval (Chapter
08), routing (Chapter 09), and few-shot (here) are the same idea — *fetch the right context, then
generate* — aimed at schema, at models, and at examples; the discipline is knowing when *not* to.

## Exercise

1. Raise `k` from 3 to 6. Does more context keep helping, or does accuracy plateau (or dip) as the
   prompt fills with less-relevant examples? Find the knee.
2. Delete the two `HAVING`-clause examples from `examples.yaml`. Which golden cases regress? You've
   just measured which pattern those examples were carrying.
3. Add an example whose SQL is subtly *wrong* and re-run. Watch a bad example teach a bad habit —
   the reason the example library is validated by a test.

---

Next: **11 — Conversation**, where the question stops being self-contained — "and just for
Manhattan?" — and the agent has to carry state across turns without losing the thread.
