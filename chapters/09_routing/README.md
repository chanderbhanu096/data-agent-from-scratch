# 09 — Routing

```bash
python chapters/09_routing/run.py

# benchmark it (strong = your Azure reference, cheap = a free local model):
python scripts/run_evals.py --agent=05 --agent=09 --runs=3
```

Chapter 08 made a real warehouse fit in the *context window*. This chapter makes it fit in a
*budget*. Look at the golden set: more than half the questions are a count or a single average —
things a free 3B model answers correctly. Sending those to a frontier model is paying frontier
prices for `SELECT count(*)`.

So route by the **shape** of the question. Easy questions go to a cheap tier; hard ones — a
ranked aggregate, a minimum-count threshold — go to the strong tier. The agent is Chapter 05's
loop; the only new thing is which model runs it.

## The router reads the question, never the data

```python
if _THRESHOLD.search(question):   # "at least 500 trips", "ignore boroughs under 1000"
    score += 2                    # the constraint weak models silently drop
if _RANKING.search(question) and _AGGREGATE.search(question):
    score += 2                    # group, aggregate, then order — where 3B models fumble
...
tier = "strong" if score >= ESCALATE_AT else "cheap"
```

It is a transparent heuristic on purpose. Every escalation comes with its reasons, so you can
audit *why* a question cost money:

```
→ STRONG  Which borough has the highest average tip? Ignore boroughs with fewer than 1000 trips.
          a minimum-count threshold; a ranked aggregate; names a thing, so it needs a join
→ cheap   How many trips started in Queens?
```

Across the golden set, the router sends **8 of 17 questions (47%) to the paid tier** and answers
the rest for free. That fraction is the cost lever, and unlike a dollar figure it doesn't depend
on anyone's current token price.

## Did it work? Measured — cheap tier local, strong tier on Azure.

The honest question isn't "does it save money" (of course it does — 53% of questions never touch
the paid model). It's "does the cheap tier get its share *right*?" Three configurations, golden
set:

| Configuration | Accuracy | Paid-tier calls |
|---------------|---------:|----------------:|
| **All cheap** — free local `qwen2.5:3b` only | ~51% | 0% |
| **Routed** — cheap for easy, Azure for hard | **79%** (27/34) | 47% |
| **All strong** — Azure `gpt-chat-latest` only | 94% | 100% |

**Read the routed number against the right baseline.** At 79% it sits 15 points below all-strong
— routing is not free. But the alternative to paying isn't the frontier model, it's the free one,
and that alone gets 51%. Routing lifts it to **79% by escalating only the 47% of questions that
need it** — about two-thirds of the way from free to frontier, for less than half the paid calls.
The missing 15 points are the misrouted questions (below). Whether that trade is worth it is now a
number you can decide on, not a hope.

## Where a shape-router misroutes — stated plainly

The router reads shape, not meaning, so it misses join-heavy questions that *look* simple.
*"How many trips starting in Manhattan were paid by credit card?"* is two joins and a filter, but
it has no threshold, no ranking, no superlative — so it scores 0 and goes to the cheap tier,
which may get it wrong. That is the failure mode routing trades for cost, and it's why you
**measure** the trade instead of assuming it. A better router (or a cheap tier made stronger by
Chapter 10's few-shot examples) shrinks that gap.

## Choose your own tiers

Both tiers are configurable — the default is the pairing most people already have (free local +
paid API), but nothing is hard-coded:

```bash
# strong tier = your main provider (DATAAGENT_PROVIDER / model)
ROUTER_CHEAP_PROVIDER=ollama          # or anthropic / openai / azure
ROUTER_CHEAP_MODEL=qwen2.5:3b         # whatever your cheap tier should be
```

## Exercise

1. Move `ESCALATE_AT` from 2 to 1. More questions go strong — does accuracy rise enough to justify
   the extra spend? Now try 3. This one knob *is* the cost/accuracy dial.
2. Add a cue for join-implying words (`borough`, `zone`, `payment`). Does routing the
   Manhattan-credit-card question to the strong tier close the accuracy gap? At what cost?
3. Replace the heuristic with a one-call classifier on the *cheap* model ("is this simple? yes/no").
   Is the extra call worth it versus regex cues you can read?

---

Next: **10 — Few-shot examples**, where we make the *cheap* tier smarter by retrieving similar
solved questions into its prompt — so the router can send even more to the free model and still
be right.
