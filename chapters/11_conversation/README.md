# 11 — Conversation

```bash
python chapters/11_conversation/run.py
```

Every question so far arrived whole. Real users don't talk that way:

> **User:** How many trips started in Manhattan?
> **Agent:** 257,614.
> **User:** And Queens?

"And Queens?" is not a question a text-to-SQL model can answer. On its own it has no metric, no
table, no verb — it means nothing without the turn before it. The agent has to carry the intent
forward.

## The mechanism: keep the dialogue, hand it back

The loop is still Chapter 05's. What's new is memory, and one judgement call about *what* to
remember:

```python
def ask(self, question):
    system = build_system_prompt() + render_history(self.turns)  # the dialogue so far
    result = run_agent(self.llm, question, tools=TOOLS, system=system)
    self.turns.append((question, result.answer))  # remember Q and A, nothing else
    return result
```

We remember the **questions and answers**, not the intermediate tool calls. A turn's transcript
— its failed queries, its retries — is noise to the next turn; keeping it would bury the thread
in the agent's own scratch work. So the memory is the conversation a *person* would remember, and
the prompt tells the model to rewrite a follow-up into a standalone question before answering it.

## Did it work? Measured on the reference model.

Five sequences, each leaving something implicit that only the previous turn supplies. The
**follow-up** turn is the one scored — the one that's meaningless without memory. On Azure
`gpt-chat-latest`:

| Sequence | The follow-up | What it must recover | Result |
|----------|---------------|----------------------|:------:|
| `borough_swap` | "And how many started in Queens?" | the metric "trips started in _" | ✓ |
| `payment_swap` | "What about cash?" | "how many trips paid by _" | ✓ |
| `entity_carryover` | "How many zones does Manhattan have?" | the subject is still *zones* | ✓ |
| `those_pronoun` | "How many of those cost more than 100 dollars?" | "those" = all the trips | ✓ |
| `add_filter` | "What about only for trips longer than 10 miles?" | same metric, plus a filter | ✓ |

**5 / 5.** A capable model resolves references cleanly once it can *see* the dialogue — the work
isn't a clever algorithm, it's giving it the context and being disciplined about what that context
contains.

## Where this gets hard (and why 5/5 isn't "solved")

This is a capability demo, not a stress test, and the honest edges are worth naming:

- **Long conversations** blow the context window — turn 40 can't carry turns 1–39 verbatim. That's
  summarisation, and it's own set of failure modes (a summary that drops the constraint you're
  about to reference).
- **Ambiguous reference.** "What about the other one?" — which other one? A strong model guesses; a
  correct system asks.
- **Stale context.** Three turns about Manhattan, then "and the airport?" — is that still filtered
  to Manhattan? The model has to know when a filter *stops* applying.

Each is a real chapter's worth of problems. The point here is the seam — memory in, standalone
question out — that they all attach to.

## Exercise

1. Add a sixth sequence with an ambiguous follow-up ("what about the other borough?"). Does the
   agent ask for clarification, or guess? Which do you want?
2. Cap history at the last two turns and add a sequence that references turn 1 from turn 4. Watch it
   break — you've just motivated conversation summarisation.
3. Feed the *whole* prior transcript (tool calls included) instead of just Q&A. Does accuracy change?
   Does latency? That's the cost of remembering too much.

---

Next: **12 — Tracing**, where we stop trusting that the agent did what it said and record every
step, token, and dollar — so "it works" becomes something you can see, not something you hope.
