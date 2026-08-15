# 06 — Plan, verify, repair

```bash
python chapters/06_plan_and_verify/run.py

# the number that matters:
python scripts/run_evals.py --agent=05 --agent=06 --runs=3
```

Chapter 05 left us with a fluent, unreliable agent. It drops constraints and then
claims it applied them; it invents a driver out of a `vendor_id` and reports the answer
with a straight face. The failure is invisible until you measure it end to end — which is
why Chapter 06 leans on the eval harness from the previous section.

This chapter is about the only thing that reliably fixes that class of error: **checking in
code what you cannot trust the model to do.**

## Why not just write a better prompt?

We tried — twice, and measured it both times. Chapter 05's system prompt already said
*"every number in your answer must come from a tool result you actually read."* The agent
invented numbers anyway. Building this chapter, we added explicit rules — *"a zone_id is
not a name, join for the name"*, *"a taxi zone is a row in `zones`, not a borough"* — clear,
correct, and aimed straight at the cases that were failing.

It **didn't fix those cases**, and it nudged the overall score *down*. The rules were right;
the model just didn't follow them. That result is the whole chapter:

> A rule in the system prompt is a **request**.
> A rule you can check in code is a **rule**.

Everything below is applying that sentence.

## The three moves

### 1. PLAN — extract requirements before any SQL exists

The question is turned into a typed object *first*:

```python
class Requirements(BaseModel):
    metric: str
    grouping: str | None
    filters: list[str]
    min_count: int | None      # ← the one that gets dropped
    sort: str | None
    limit: int | None
    answerable: bool           # ← the one that stops a confident hallucination
```

A dropped constraint is now a **missing field**, not a subtlety buried in a sentence.
`min_count` — "at least 500 trips" — gets its own slot, because ignoring it produces an
average over one row presented as a finding. And `answerable` is the gate that turns
"Vendor 2 earned the most in tips" into "this warehouse has no driver data."

### 2. VERIFY — the tool refuses SQL that doesn't implement the plan

`run_sql` is wrapped. Before a query touches the database, it is checked against the plan:

```python
if req.min_count and not _HAS_HAVING_COUNT.search(sql):
    return f"CHECK FAILED: ...add HAVING COUNT(*) >= {req.min_count}"
```

Ask for "at least 500 trips" and send SQL with no `HAVING COUNT`, and the query is
**rejected before execution**, with the exact fix. Same for grouping without selecting
`COUNT(*)` (so sample size is visible), a missing `LIMIT`, and selecting a bare `zone_id`
instead of joining for the name.

These checks are deliberately shallow — cheap syntactic facts, not a SQL semantics engine.
They catch the specific mistakes we *measured*. Chapter 19 measures what they still miss.

### 3. REPAIR — failures are instructions, not dead ends

Every failure returns text the model can act on: `CHECK FAILED: add HAVING…`,
`EMPTY RESULT: your filter is probably wrong, use sample_column…`. Two empty-result cases
matter here, because the baseline read both as "the data isn't there":

- **zero rows** — a filter value that doesn't exist (`WHERE zone_name = 'JFK'` when it's
  `'JFK Airport'`);
- **one row of all NULLs** — an aggregate over zero matching rows, which is *not* zero rows,
  so the naive check misses it. Both now come back as: your filter matched nothing, go look
  at the real values.

## Did it work? The honest answer.

Measured on the golden set, `--runs=3`, on two models — the free 3B you can run on a laptop,
and a frontier model through Azure:

| Model | agent 05 (plain loop) | agent 06 (plan · verify · repair) | Δ |
|-------|----------------------:|----------------------------------:|:--|
| `qwen2.5:3b` (local, free) | 51% (26/51) · 3 traps hit | **69% (35/51)** · 0 traps hit | **+18%** |
| Azure `gpt-chat-latest` | 94% (48/51) · 0 traps hit | **100% (51/51)** · 0 traps hit | **+6%** |

Read the table carefully, because the story is not just "number went up."

**Verification helps the weak model three times more than the strong one** — +18 points
versus +6 — and that is the point, not a footnote. The 3B model is the one that drops
constraints and falls for traps; the guardrails exist for exactly that model. On both, the
verifier drove trap-hits to zero: the plausible-wrong query that omits the `HAVING` filter
never reaches the database.

**Verification helps the strong model too, and you can see exactly why.** On the frontier
model the plain loop's *only* remaining failures are all one case: asked "which driver
earned the most in tips", it answers "Vendor 2" every single time — confidently inventing a
driver from a vendor id. Agent 06's PLAN step marks the question unanswerable and declines,
3 for 3. The entire +6% is verification catching a confident answer to an unanswerable
question. That is a safety property, not a rounding artifact.

But the 3B model is left at 69%, not 100%, and that gap is honest: it fails in ways the
checks can't see. A wrong join direction or a sum where an average was asked is *grammatically*
fine SQL — it passes every syntactic check and still answers the wrong question. The score
also moves several points between runs; that variance is the error bar on every single-run
number in this repo.

## What still fails, and why that's honest

Even at 100% on one model, this agent is not "solved." The syntactic checks pass SQL that is
grammatically fine and semantically wrong, and no amount of `HAVING COUNT` fixes a model that
misunderstands the question. Closing that gap is the job of later tiers: few-shot example
retrieval (Tier 2) and stronger models via routing (Tier 4). The verifier is a floor, not a
ceiling.

> `grounded` told us the agent didn't hallucinate a tool result.
> The verifier makes it implement the constraints it agreed to.
> Neither makes it *understand the question*. That's what's left.

## Exercise

1. Add a golden case with a filter the checks don't cover (e.g. "only weekday trips"), run
   `--agent=06`, and watch it pass the checks and still get the answer wrong. You've just
   found the next check — or the argument for Chapter 19.
2. Weaken `check_sql` to only test `min_count`. Re-run the evals. Which cases regress?
3. Run the same head-to-head on your own model (`DATAAGENT_PROVIDER=...`). Does verification
   help a strong model as much as a weak one? Explain the gap.
4. Run `--runs=3` twice. The score moves between runs — by how much? That is the error bar on
   every number above.

---

Next: **07 — Guardrails**, where we stop trusting the query and start attacking it on
purpose — prompt injection, resource limits, and the difference between a prompt that asks
for safety and a sandbox that enforces it.
