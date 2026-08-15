# 12 — Tracing

```bash
python chapters/12_tracing/run.py
```

Every chapter so far ended the same way: an answer appeared, it looked right, we moved on.
That's **hope**, not evidence. "It works" was a feeling about a string. This chapter replaces
the feeling with a **record** — the run, on paper, that you can reopen after it's gone.

## The move: read the receipt the loop was already writing

The loop from Chapter 05 already produced everything a trace needs. It builds a `Step` per
iteration (the comment on it literally says *"kept for the trace"*), it accumulates `Usage`
(tokens and dollars), it knows why it stopped, and it already exposes `grounded` — whether a
single tool call ever returned real data or the model just talked. All that was missing was
somewhere to put it.

So this chapter adds **no machinery to the loop**. It hangs a `Tracer` on the `on_step`
callback the loop already fires, and derives per-step cost by subtracting snapshots of the
running total:

```python
llm = LLM(settings)
tracer = Tracer(llm)
result = run_agent(llm, question, tools=TOOLS, system=..., on_step=tracer)
save_jsonl(trace_record(question, result, tracer, ...), path)   # one run → one line
```

> The cost of a step is the *change* in the total between steps — not a new counter threaded
> through the loop. Reuse the number that's already there.

## What a trace looks like

A real run on the reference model (Azure `gpt-chat-latest`), average-tip-by-payment-type:

```
       Timeline — one row per loop step
┏━━━━━━┳━━━━━━━━━┳━━━━━━┳━━━━━┳━━━━━┳━━━━━━━━━┓
┃ step ┃ tools   ┃   ms ┃  in ┃ out ┃       $ ┃
┡━━━━━━╇━━━━━━━━━╇━━━━━━╇━━━━━╇━━━━━╇━━━━━━━━━┩
│    1 │ run_sql │ 2786 │ 845 │  64 │ 0.00000 │
│    2 │ —       │ 1343 │ 984 │  42 │ 0.00000 │
└──────┴─────────┴──────┴─────┴─────┴─────────┘

  grounded: yes  ·  stop: answered  ·  1829 in + 106 out
```

Two steps: it wrote SQL and ran it (step 1), then read the result and answered (step 2). The
input tokens *grow* between steps — step 2 is bigger because it carries step 1's tool result
back into the prompt. That's the cost of memory, and now you can see it instead of guessing.

**A note on the `$` column.** It's real — it reports `Usage.cost_usd` straight from the
gateway. It reads `0.00000` here only because this particular Azure deployment has no price
mapped, so tokens are the ground truth for this model; point it at a priced model (or add the
rate) and the same column fills in. The chapter doesn't ship a pricing engine — the tokens are
what you meter, and the dollars are one multiplication away when you need them.

## Why JSONL, and why that's the whole point

Each run appends **one JSON line**. A run isn't a snapshot you glance at and lose — the file
is a **history**. That unlocks the things "it looked right" never could:

- **Diff two runs** of the same question — did a prompt change cost more tokens, or take more
  steps, for the same answer?
- **Grep for the failures** — `grounded: false` is every answer where no tool ever returned
  data, i.e. every number the model invented. You can find them without re-running anything.
- **Replay a bad run** — the exact question, steps, and stop reason are on file.

This is the seam every later observability idea attaches to: evals score these records in bulk,
dashboards chart the `total` field, alerts fire on `grounded: false`. They're all just reading
the line this chapter writes.

## Where this stays honest

- **Timing is wall-clock, not billed compute** — it includes network round-trips to the
  provider, which is what you actually wait for, but don't read it as pure model time.
- **Per-step cost is a delta of the cumulative counter.** It's exact when the counter is (real
  providers report usage per call); a provider that only reports a final total would collapse
  everything into the last step. Every gateway here reports per-call, so the split is real.
- **A trace records what happened, not whether it was right.** `grounded: yes` means a tool
  returned data — not that the SQL answered the question. That check is the eval harness's job,
  and the trace is what it reads.

## Exercise

1. Run the same question twice and `diff` the two JSON lines. What's stable, what drifts?
2. Add a `--question` flag and trace a question you *expect* to fail (ask for a column that
   doesn't exist). Watch `grounded` go to `false` and the step count climb as it retries.
3. Write a five-line script that loads `traces.jsonl` and prints the mean tokens per run. You've
   just built the smallest possible cost dashboard — no new dependency.

---

Next: **embeddings as the retrieval upgrade** — Chapter 08 retrieved schema with BM25, which
matches words. Real questions and real column names rarely share words ("expensive rides" vs
`total_amount`), so the next step is retrieval by *meaning* — and, kept honest, the measurement
of when it actually beats the lexical version and when it doesn't.
