# 02 — Structured output you can trust

```bash
python chapters/02_structured_output/run.py
```

Chapter 01 returned prose. A program can't branch on prose. Here we get a typed object
back — and handle the case where the model gets the shape wrong, which it will.

## The one idea

> Getting valid JSON isn't a prompt trick. It's a **validate-and-repair loop**.

Every structured-output library — Instructor, Outlines, the SDKs' own helpers — is a
variation on `plan_question()` in `run.py`. Knowing that means you can debug it when it
misbehaves, and you'll know what you're giving up when you reach for one.

## Three things worth pausing on

### 1. The schema *is* the prompt

```python
schema = json.dumps(QuestionPlan.model_json_schema(), indent=2)
```

Pydantic's `Field(description=...)` text ends up in the JSON Schema, which ends up in the
system prompt. Writing a good field description is prompt engineering — it just doesn't
look like it. Vague descriptions produce vague classifications.

### 2. Parse defensively; don't prompt harder

```python
if fence := re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL):
```

Models wrap JSON in ` ```json ` fences and chatty preambles no matter how firmly you
forbid it — smaller local models especially. Ten lines of tolerant parsing beats an
escalating war of ALL-CAPS instructions, and it costs no tokens.

### 3. Repair prompts must name the error

The retry doesn't say "try again". It appends the model's broken output *and the exact
validation error*:

```python
{"role": "user", "content": f"That did not validate against the schema.\nError: {exc}\n..."}
```

The model can't see what your validator saw. Telling it `tables_needed: Input should be a
valid list` is specific enough to fix; "that was wrong" is not.

## The `unanswerable` case

The third question — *"What's the weather like in Berlin?"* — has no answer in a taxi
warehouse, and `intent: "unanswerable"` is a **required** part of the enum for a reason.

An agent with no way to decline will always produce something. In a text-to-SQL system
that means confidently querying the wrong columns and returning a number with no
relationship to the question. Every layer from here on gets an explicit escape hatch;
this is the first one.

## Note on API-native structured outputs

Several providers now enforce a JSON Schema server-side, so the response is guaranteed
to validate (`output_config.format` on the Claude API; `response_format` on OpenAI). It's
strictly better than this loop when available — fewer round trips, no parse failures.

We're doing it by hand first because:

1. It works identically on every provider, including local Ollama models that have no such
   feature — and this repo has to run for someone with no API key.
2. Server-side enforcement guarantees the *shape*, never the *content*. A schema-valid
   plan can still list a table that doesn't exist. The validate-and-repair habit is what
   catches that, and Chapter 06 reuses it verbatim for SQL errors.

## Exercise

1. Add a field: `confidence: float = Field(ge=0, le=1, description=...)`. Re-run. Note that
   models are poorly calibrated — a self-reported 0.95 means very little. Chapter 19 is
   where you get numbers that actually mean something.
2. Break it deliberately: change the `Literal` enum to values the model has never seen
   (`"alpha" | "beta"`). Watch the repair loop work, and watch how many attempts it takes.
3. Set `max_attempts=1` and run against a small local model. This is what production looks
   like without a retry loop.

---

Next: [03 — Schema as context](../03_schema_context/) — where it starts writing real SQL.
