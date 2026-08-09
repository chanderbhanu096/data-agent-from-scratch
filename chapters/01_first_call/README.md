# 01 — Your first LLM call

```bash
python chapters/01_first_call/run.py
```

## What you should see

The model fails to answer. That's the lesson.

Asked "how many taxi trips started in Manhattan in January 2024?", it will either say it
doesn't have access to your data, or — more interestingly — **confidently invent a number**.
Both outcomes teach the same thing.

## The one idea

> A language model is a function from text to text. It has no memory, no database
> connection, and no way to act on the world.

Everything people call "AI engineering" is the scaffolding that turns that function into
something useful. There is no hidden intelligence you're failing to unlock — there is only
what you put into `messages` and what you let it call.

## Three things in the code worth pausing on

### 1. The conversation is a list you own

```python
messages = [{"role": "user", "content": QUESTION}]
```

There is no session on the server. Every request resends the **entire** history. When a
long conversation gets expensive or hits a context limit, that's why — and Chapter 06 is
about what to do when it does.

### 2. `system` is a different channel, not just another message

The system prompt sets standing behaviour for the whole conversation. Later chapters put
the schema, the safety rules, and the output contract here. It is the highest-leverage
text in the whole system.

### 3. Tokens are the unit of everything

The run prints input tokens, output tokens, and cost. Cost, latency, and context limits are
all denominated in tokens — so this counter, added in chapter one, is what makes Chapter 23
(cost routing) measurable rather than vibes.

On a local model the cost is `$0` but the token count still matters: context length is a
hard limit even when the money isn't.

## Look inside the gateway

Open [`dataagent/llm.py`](../../dataagent/llm.py). One `chat()` method, three providers
behind it. Two details are worth your attention:

**`_to_anthropic()`** translates the canonical message list into Anthropic's content-block
format. Reading it is the fastest way to understand what a message *really* is — and it's
where you'll see that a tool result is sent as a **user** message, which surprises most
people the first time.

**No `temperature`.** Current Claude models reject `temperature`, `top_p`, and `top_k`
outright — a request carrying them fails. If you learned "turn temperature down for
determinism," that lever is gone; you steer with the prompt now. Chapter 03 is about doing
that well.

## Exercise

1. Change `QUESTION` to something the model *can* answer from general knowledge
   ("what does the NYC TLC regulate?"). Watch it succeed. The failure above wasn't a
   capability problem — it was a **context** problem.
2. Switch providers in `.env` and re-run. Same code, different model. That's the gateway
   earning its keep.
3. Ask it the same question three times. Note that the answers differ — you're going to
   need Chapter 19 (evals) to say anything reliable about a system like this.

---

Next: [02 — Structured output](../02_structured_output/) — getting back something your
code can actually use.
