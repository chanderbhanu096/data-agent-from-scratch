# 04 — Tool calling

```bash
python chapters/04_tool_calling/run.py
```

Until now, *we* ran the SQL. Here the model picks a tool and its arguments, and our code
executes it.

## The one idea

> A tool call is the model emitting **structured text**. It cannot run anything.
> Your code reads that text and decides whether to comply.

This is the most misunderstood thing in agent engineering. "Giving the model database
access" does not connect the model to your database. It means:

1. You describe some functions in the request.
2. The model may reply "I would like `run_sql` with `{"sql": "SELECT ..."}`".
3. **Your code** decides whether to run it.
4. You send the result back as another message.

Step 3 is a decision point you fully control. It's why an agent can be safe at all, and
`execute()` in `run.py` is where every guardrail in Chapter 07 will live.

## The tool description is a prompt

```python
description = (
    "List up to 15 distinct values from one column. Call this BEFORE filtering on "
    "a text column, so you filter on values that actually exist rather than "
    "guessing at their spelling or capitalisation."
)
```

Note what that does: it doesn't just say what the tool *is*, it says **when to reach for
it**. That phrasing is the difference between a tool that gets used and one that gets
ignored. If your agent isn't calling a tool you gave it, the description is the first
thing to fix — before the system prompt, and long before the model.

## Errors are returned, not raised

```python
except Exception as exc:
    return f"SQL ERROR: {str(exc).splitlines()[0]}"
```

A failed tool is not a crashed program. The error goes back to the model as an ordinary
tool result — which is what makes self-correction possible in Chapter 06. Raise, and the
run dies. Return, and the agent gets a chance to read what went wrong and try again.

Same for the guardrail: `REJECTED: DROP is not allowed` is information the model can act
on. A stack trace is not.

## Two failure modes you may see, and both are informative

**It answers without calling a tool.** Common on small local models. The tools were
offered and ignored, and the answer is invented. Sharpen the descriptions, or use a
stronger model. Either way, notice that *nothing crashed* — a fabricated answer looks
exactly like a real one, which is Chapter 19's entire reason for existing.

**It wants a second tool call and we stop.** One `sample_column` to see the boroughs, then
a `run_sql` to aggregate — that's two rounds, and this chapter only does one. That unmet
request is the motivation for the next chapter, and you should see it as a feature of this
one.

## What actually happened when we ran this

Not a hypothetical. This is a real transcript, `llama3.2:3b`, first try:

```
→ run_sql({'sql': 'SELECT z.borough FROM trips t JOIN zones z
                   ON t.pickup_zone_id = z.zone_id
                   GROUP BY z.borough ORDER BY AVG(t.tip_amount) DESC LIMIT 1'})

borough
---
Staten Island

Answer  The borough with the highest average tip is Staten Island,
        with an average tip amount of $2.38.
```

Read the tool result again. It is one word: `Staten Island`. The query never put
`AVG(t.tip_amount)` in the SELECT list — only in the ORDER BY — so **no number was ever
returned.**

The model reported `$2.38` anyway. The system prompt says, in as many words, *"Never state
a figure you did not read from a tool result."* It did it regardless.

The true value is **$14.08**. `$2.38` corresponds to nothing in the warehouse.

Two lessons, and the second is worse than the first:

**A system prompt is a request, not a constraint.** "Never state a figure you didn't read"
is a wish. If a number must be grounded, your *code* has to check it — the model cannot be
trusted to enforce a rule about itself. This is the same lesson as the SQL guardrail in
Chapter 03, arriving from a different direction.

**Nothing failed.** No exception, no warning, no red text. A wrong answer is
byte-for-byte indistinguishable from a right one. This is the single strongest argument
for Chapter 19 (evals): once an agent is fluent, *reading its output tells you nothing
about whether it's correct.*

### And the "correct" answer is a trap too

Staten Island genuinely does have the highest average tip — computed from **7 trips**,
out of 300,000:

| borough | avg_tip | trips |
|---|---|---|
| Staten Island | 14.08 | **7** |
| EWR | 12.74 | 67 |
| Queens | 8.13 | 37,548 |
| Manhattan | 2.81 | 257,614 |

So even a perfectly grounded answer here is useless. The agent answered the question it
was asked, and the question was bad. Real analysts add "with at least N observations"
automatically; an agent will not unless you make it. That's a `DOMAIN_NOTES` entry
waiting to be written — and a reminder that most text-to-SQL failures in production are
not syntax errors, they're statistically meaningless answers delivered with total
confidence.

## What Chapter 05 changes

Look at the shape of `main()`:

```
round 1 → execute tools → round 2
```

Now wrap it in `while True:` and stop when `not reply.wants_tools`. That's the agent loop.
Everything after Chapter 05 is a refinement of those ten lines.

## Exercise

1. Delete the `sample_column` tool and re-run. Does it still get the borough names right?
   (It probably does — they're in the schema. Now ask about a zone name and watch it guess.)
2. Weaken a description to just `"Runs SQL."` and see whether the model still chooses it.
3. Add a `count_rows(table)` tool. Notice you now have two tools that could answer
   "how many trips are there?" — overlapping tools make the model hesitate, which is why
   fewer, clearly-bounded tools beat many fuzzy ones.
4. In `execute()`, hardcode a return of `"ERROR: database is offline"` and re-run. Watch
   how the model responds to a failure it can't fix — this is worth seeing before you rely
   on one in production.

---

Next: **05 — The agent loop from scratch.** Roughly 200 lines, no framework, and the
centrepiece of the whole repo.
