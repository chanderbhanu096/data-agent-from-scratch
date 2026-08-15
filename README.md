<div align="center">

# Data Agent From Scratch

### Stop writing SQL. Build the thing that writes it for you.

**Ask in plain English. The agent writes the SQL, checks it, runs it, and answers.**
You don't need to know SQL to use it — you need to know how to *build* it. That's this repo.

*No frameworks. No black boxes. No hardcoded demo.*

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Runs offline](https://img.shields.io/badge/Runs%20offline-Ollama%20%7C%20no%20API%20key-success)](#start-in-60-seconds)

</div>

---

> **Everything here runs.** Every chapter is executable code with a test. There is no
> demo mode, no canned response, no "imagine this returns…". If it can't run for real,
> it isn't in this repo.

## What that looks like

You type this:

> *"What is the average tip amount by payment type? Show the payment type name."*

It writes this, by itself, from nothing but the schema:

```sql
SELECT pt.payment_type, AVG(t.tip_amount) AS avg_tip_amount
FROM trips t
JOIN payment_types pt ON t.payment_type_id = pt.payment_type_id
GROUP BY pt.payment_type
LIMIT 100
```

And you get this:

| payment_type | avg_tip_amount |
|---|---|
| Credit card | 4.508 |
| Dispute | 0.055 |
| No charge | 0.024 |
| Cash | 0.0009935 |

Real output, real 300,000-row warehouse, `llama3.2:3b` running offline on a laptop. Not a
screenshot of someone else's demo.

*(And there's a genuine finding sitting in that table: cash tips are effectively zero —
not because nobody tips in cash, but because cash tips never get recorded. The agent
surfaced it; noticing what it means is still your job.)*

## Does it actually work? Measured, not claimed.

The agent is scored against a golden set where every question carries the SQL that computes
its own answer, so the truth is recomputed from the warehouse each run — no vibes, no
self-grading. The headline result is the payoff of Chapter 06: *checking the query in code*
instead of *asking the model nicely* to get it right.

| Model | plain loop | + plan · verify · repair | Δ | traps hit |
|-------|-----------:|-------------------------:|:--|:--|
| **`qwen2.5:3b`** — free, runs on a laptop | 51% | **69%** | **+18%** | 3 → **0** |
| **frontier model** (via Azure) | 94% | **100%** | **+6%** | 0 → 0 |

Verification helps the *weak* model three times more than the strong one, and drives
plausible-wrong "trap" answers to zero on both — because the guardrails exist for exactly the
model that needs them. Reproduce it yourself:

```bash
python scripts/run_evals.py --agent=05 --agent=06 --runs=3
```

## Why this exists

There are excellent courses on AI agents. Almost all of them teach you to build a
chatbot with a weather tool, and then stop right before the part that matters.

This one picks a target that is **objectively checkable**: text-to-SQL. Either the query
returns the right rows or it doesn't. That single property changes everything downstream —
it means Chapter 19's evals are *real measurements*, not an LLM grading its own homework.
It's the reason this domain is the best one to learn agents in, and almost nobody uses it.

You'll build the thing people pay for — [Vanna](https://github.com/vanna-ai/vanna),
[WrenAI](https://github.com/Canner/WrenAI) — from an empty file.

## Start in 60 seconds

```bash
git clone https://github.com/chanderbhanu096/data-agent-from-scratch
cd data-agent-from-scratch
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
python scripts/build_warehouse.py     # downloads 50 MB of real NYC taxi data
ollama pull qwen2.5:3b                # 1.9 GB, free, runs offline
python chapters/01_first_call/run.py
```

**No API key needed** to start — the default provider is [Ollama](https://ollama.com), free
and offline. But everything is provider-agnostic: **pick whichever model you want.**

## Run it on any model

One file — [`dataagent/llm.py`](dataagent/llm.py) — is the only place that knows a provider
exists. Set `DATAAGENT_PROVIDER` in `.env` and fill in the placeholders for your choice:

| Provider | `.env` | You supply |
|----------|--------|------------|
| **Ollama** (local, free) | `DATAAGENT_PROVIDER=ollama`<br>`OLLAMA_MODEL=<model>` | nothing — just `ollama pull <model>` |
| **Anthropic** | `DATAAGENT_PROVIDER=anthropic`<br>`ANTHROPIC_MODEL=<model>` | `ANTHROPIC_API_KEY=<key>` |
| **OpenAI** | `DATAAGENT_PROVIDER=openai`<br>`OPENAI_MODEL=<model>` | `OPENAI_API_KEY=<key>` |
| **Azure OpenAI** | `DATAAGENT_PROVIDER=azure`<br>`AZURE_OPENAI_DEPLOYMENT=<deployment>` | `AZURE_OPENAI_ENDPOINT=<endpoint>`<br>`AZURE_OPENAI_API_KEY=<key>` |

For **Azure OpenAI** (Azure AI Foundry), the endpoint is the OpenAI-compatible `/openai/v1`
surface and the model is your *deployment* name — paste the endpoint straight from **Keys and
Endpoint** and it's normalized for you:

```bash
DATAAGENT_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://<your-resource>.services.ai.azure.com/openai/v1
AZURE_OPENAI_API_KEY=<key>
AZURE_OPENAI_DEPLOYMENT=<your-deployment-name>
```

> **The benchmark numbers in this repo are measured on Azure OpenAI** (`gpt-chat-latest`) as
> the reference model. Swap in your own and re-run `scripts/run_evals.py` — the eval harness
> doesn't care which provider produced the answer.

## The warehouse you'll be querying

Real data, not a toy: **300,000 NYC taxi trips** from January 2024, plus zone and payment
lookups. It has NULLs, outliers, and a borough literally named `N/A` — because the failures
this repo teaches you to handle don't show up in clean synthetic data.

```
trips (300,000)  ──┬── zones (265)          "What's the average fare from JFK to Manhattan
                   └── payment_types (7)     on weekends, by payment method?"
```

## What you're building

Every chapter adds one capability to the same agent. Read `run.py` top to bottom in one
sitting — that's the constraint each chapter is written under.

<table>
<tr><td width="60"><b>Tier 0</b></td><td><b>Foundations</b> — what an LLM call actually is</td></tr>
<tr><td>01</td><td>Your first call · tokens, cost, and why the model can't answer yet ✅</td></tr>
<tr><td>02</td><td>Structured output · getting JSON you can trust, and retrying when you can't ✅</td></tr>
<tr><td>03</td><td>Schema as context · the moment it starts writing real SQL ✅</td></tr>
<tr><td>04</td><td>Tool calling · handing it the database, from scratch ✅</td></tr>
<tr><td><b>Tier 1</b></td><td><b>The agent loop</b></td></tr>
<tr><td>05</td><td><b>The loop from scratch, no framework</b> ← the centrepiece ✅</td></tr>
<tr><td>06</td><td>Self-correction · it reads its own SQL error and fixes it</td></tr>
<tr><td>07</td><td>Guardrails · step caps, cost caps, and blocking <code>DROP TABLE</code></td></tr>
<tr><td>08</td><td>The same agent on LangGraph · an honest comparison</td></tr>
<tr><td><b>Tier 2</b></td><td><b>Retrieval</b> — when the schema stops fitting</td></tr>
<tr><td>09–14</td><td>Embeddings from scratch (numpy, ~15 lines) → hybrid search → reranking → schema RAG</td></tr>
<tr><td><b>Tier 3</b></td><td><b>Interop</b></td></tr>
<tr><td>15–18</td><td>Build an MCP server · use it from Claude Desktop · memory · multi-agent</td></tr>
<tr><td><b>Tier 4</b></td><td><b>Production</b> — the tier that gets you hired</td></tr>
<tr><td>19–24</td><td>Execution-accuracy evals in CI · tracing · prompt-injection defence · human approval · cost routing · deploy</td></tr>
</table>

Chapters 01–05 are here and runnable now (✅). Later tiers land tier by tier — watch the repo.

## The one idea

An agent is a `while` loop. Everything else is engineering around it.

```python
while True:
    reply = model(messages, tools)  # 1. THINK
    messages.append(reply)

    if not reply.tool_calls:  # 2. DONE?
        return reply.text

    for call in reply.tool_calls:  # 3. ACT
        result = execute(call)
        messages.append(result)  # 4. OBSERVE
```

Four steps. A model cannot *do* anything — it can only emit text. A "tool call" is the
model emitting structured text that **your code** chooses to execute. The agent's power is
entirely the tools you give it and the loop you wrap around it.

Once that lands, the buzzwords collapse into one picture:

| Buzzword | What it actually is |
|---|---|
| **RAG** | Putting relevant knowledge into `messages` before the model thinks |
| **Agentic RAG** | Retrieval as an entry in `tools`, so the model decides *when* to look |
| **MCP** | A wire protocol for where `tools` come from — a separate process you didn't write |
| **Memory** | What survives in `messages` between runs of the loop |
| **Multi-agent** | A tool whose `execute()` is *another loop* |
| **Guardrails** | Validation inside `execute()` |
| **Evals** | Unit tests for a function that returns something different every time |

Every chapter is "one more thing you can do to that loop."

## Architecture

```
            ┌──────────────────────────────────────────┐
            │  CONTROL      the loop, step + $ budgets │   ch 05, 06, 07
            └───────┬──────────────────────────────────┘
                    │
     ┌──────────────┼───────────────┬─────────────────┐
     ▼              ▼               ▼                 ▼
┌─────────┐  ┌────────────┐  ┌───────────┐  ┌──────────────┐
│ GATEWAY │  │   TOOLS    │  │  CONTEXT  │  │  RETRIEVAL   │
│ ollama/ │  │ run_sql,   │  │ what goes │  │ schema RAG,  │
│ claude/ │  │ inspect,   │  │ in, what  │  │ few-shot     │
│ gpt     │  │ + MCP      │  │ gets cut  │  │ examples     │
└─────────┘  └────────────┘  └───────────┘  └──────────────┘
  ch 01        ch 04, 15        ch 06          ch 09–14
                    │
            ┌───────▼──────────────────────────────────┐
            │  OBSERVABILITY   traces, evals, cost     │   ch 19, 20, 23
            └──────────────────────────────────────────┘
```

Swap the model → only `GATEWAY` changes. Add a data source → only `RETRIEVAL` changes.
That separation is the difference between an engineer and someone who copied a quickstart.

## Repo layout

```
dataagent/          the small shared library (gateway, warehouse, config)
  llm.py            ← the only file that knows a provider exists
  warehouse.py      ← the only path from agent to database
chapters/NN_name/
  README.md         the concept, and why it's built this way
  run.py            runnable, readable top to bottom
  test_*.py         proof it works
scripts/            build_warehouse.py
evals/              golden questions with expected result sets   (ch 19)
```

## Contributing

Issues tagged `good first issue` are genuinely good first issues. Ports to other
warehouses (Postgres, BigQuery, Snowflake) are especially welcome — the interface to
implement is `dataagent/warehouse.py`, and it's under 120 lines.

## License

MIT — see [LICENSE](LICENSE). NYC TLC trip data is public domain.
