# Contributing

Thanks for looking. This repo teaches by being readable, so contributions are held to a
slightly unusual standard: **clarity beats cleverness, every time.**

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"
cp .env.example .env
python scripts/build_warehouse.py
pytest -q
```

No API key needed to run the tests. CI runs without one too.

## The rules that make this repo work

1. **Every chapter's `run.py` must be readable top to bottom in one sitting.** If it
   doesn't fit in your head, it's too long — split the chapter instead.
2. **No demo modes. No canned responses.** If a code path a user can reach returns a
   hardcoded answer, it doesn't ship. `dataagent/testing.py` exists for tests only, and
   its docstring explains the line.
3. **Comments explain *why*, not *what*.** `# increment i` is noise. `# fetch one extra
   row so we can distinguish "at the limit" from "truncated"` is the reason the code
   looks the way it does.
4. **Every chapter has a test**, and the test should fail if you break the chapter. Try
   mutating your code to check — a test that passes against broken code is worse than no
   test, because it buys false confidence.
5. **Prose is part of the product.** Chapter READMEs get the same review as code.

## Especially welcome

**Other warehouses.** The interface to implement is `dataagent/warehouse.py` — under 120
lines, three functions. Postgres, BigQuery, Snowflake, and ClickHouse ports would each be
genuinely useful, and would prove the abstraction is real.

**Other providers.** `dataagent/llm.py` is the only file that knows a provider exists. Add
a `_yourprovider()` method and a translation function; the rest of the repo won't notice.

**Better domain notes.** `DOMAIN_NOTES` in Chapter 03 is accumulated debugging. If you
find a question the agent answers plausibly and wrongly, that's a bug report *and* a
contribution — send the question and the note that fixes it.

**Translations.** Chapter READMEs in other languages, as `README.<lang>.md`.

## Before you open a PR

```bash
ruff check --fix . && ruff format . && pytest -q
```

## Reporting a wrong answer

Wrong answers are the most valuable issues in a text-to-SQL repo. Please include:

- the question you asked
- the SQL it produced
- what you expected instead
- your provider and model

That's exactly the shape of a golden-set eval case (Chapter 19), so a good bug report
often becomes a test directly.
