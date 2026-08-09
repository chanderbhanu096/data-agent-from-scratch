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
