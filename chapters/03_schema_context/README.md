# 03 — Schema as context

```bash
python chapters/03_schema_context/run.py
```

Same model. Same gateway. Same code path as Chapter 01. The only thing that changed is
**what we put in front of it** — and now it writes working SQL.

## The one idea

> The capability you thought was missing was context you hadn't supplied.

This is worth sitting with, because it's the single most common misdiagnosis in AI
engineering. When an agent underperforms, the instinct is to reach for a bigger model or a
cleverer prompt. Far more often the model simply didn't have the facts.

## What's in the system prompt

Three things, and the order of importance is not what you'd guess:

```
1. The schema        ← generated, free, and the obvious part
2. Domain notes      ← hand-written, and where the real work is
3. Output rules      ← "one SELECT, no prose"
```

**`DOMAIN_NOTES` is the part that matters.** Look at it:

```
- payment_type_id is meaningless on its own; join payment_types for the name.
- borough 'N/A' and 'Unknown' are real values in zones — not nulls.
- total_amount already includes tip and tolls.
```

None of that is in the schema. Every line came from a query that returned a plausible,
confidently-wrong answer. **That block is accumulated debugging**, and building it up is
most of the actual work of shipping a text-to-SQL system. Nobody's tutorial mentions it
because it isn't glamorous, and it's the difference between a demo and a product.

## Why `schema_text()` is generated, not written

```python
f"{schema_text()}\n\n"
```

It reads `information_schema` at runtime. A hand-maintained schema string goes stale the
first time someone ships a migration, and a stale schema produces SQL that references
columns that no longer exist — with no error until execution.

It also includes row counts per table, which helps the model judge whether a `GROUP BY` is
going to return 7 rows or 300,000.

## Where this breaks

Two failure modes you can see right now, and both get fixed later:

**Invalid SQL is fatal.** If the model writes a bad query, we print the error and give up.
Nothing recovers. Chapter 06 hands that error message back to the model — which turns out
to fix the large majority of cases on the first retry.

**The schema won't always fit.** Three tables is ~800 characters. Three hundred tables is
past the context window, and stuffing it all in would be wasteful even if it fit. That's
Tier 2 (chapters 09–14): retrieving *only the relevant* schema. Notice that "schema RAG"
is a real, unglamorous instance of RAG — not a document chatbot.

## On the guardrail

`run_sql()` calls `assert_safe()` before anything reaches DuckDB. The system prompt also
says "never write INSERT, UPDATE, DELETE, DROP".

**Both exist deliberately, and the prompt is the weaker one.** A system prompt is a
request; a validator is a rule. Anything a user can influence can talk a model out of a
prompt instruction, so the prompt is there to help the model succeed, and the validator is
there for when it doesn't. Chapter 07 attacks this on purpose.

## Exercise

1. **Delete `DOMAIN_NOTES` and re-run.** Watch question 2 return raw `payment_type_id`
   integers instead of names — a plausible-looking answer nobody can read. This is the
   single most useful experiment in the chapter.
2. Ask something ambiguous: *"what's the busiest zone?"* — busiest by pickups, dropoffs, or
   total? Note that the model picks one silently and never mentions the ambiguity. Chapter
   19 is where you start measuring how often that costs you.
3. Add a note to `DOMAIN_NOTES` about excluding `total_amount <= 0` (refunds and errors are
   in the real data). Re-run question 3 and compare the numbers.

---

Next: [04 — Tool calling](../04_tool_calling/) — stop running the SQL for it.
