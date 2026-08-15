# Live demo — watch the agent get smarter, one chapter at a time

```bash
python demo/serve.py          # then open http://localhost:8000
```

Type one question. It runs through **three real chapter agents side by side**, so you *see*
what each capability adds:

| Column | Chapter | What it demonstrates |
|--------|---------|----------------------|
| Plain loop | 05 | the raw think→act→observe loop |
| Plan · verify · repair | 06 | checks its own SQL; **refuses the unanswerable** instead of inventing |
| Schema retrieval | 08 | finds the right table out of a 253-table catalog |

Under every answer are the **receipts from [Chapter 12](../chapters/12_tracing/)** — steps, tokens,
cost, and `grounded`. These are genuine runs. There is no mock-up.

The sharpest moment: ask *"Who is the highest-earning driver?"* (the warehouse has no drivers).
The plain loop quietly answers with *vendor* as a stand-in; plan·verify **declines** — "that can't
be answered from this warehouse." Same question, visibly different judgement.

## Three modes, one rule: the link is never broken

| Mode | What it does | Needs |
|------|--------------|-------|
| **Cloud** | real calls to a hosted frontier model (Azure) — the full live experience | your Azure keys in `.env` |
| **Local** | real calls to your own Ollama — live, offline, no key | `ollama` running |
| **Replay** | plays back captured real runs from `data/runs.json` | nothing |

If a live mode isn't configured — **or your cloud credits run out** — the server automatically
falls back to the recorded run for that question and **says so** with a banner. It degrades to
honest, never to fake.

## Refreshing the recorded runs

`data/runs.json` is what the Replay mode (and the hosted page) plays back. Regenerate it any time
an agent changes:

```bash
python demo/capture.py --mode cloud     # or --mode local
```

It runs the same spine the live server uses over the demo question set and writes the results —
so the recording can never drift from a second, separate code path.

## Hosting it (a link recruiters can click)

`index.html` is fully self-contained and needs **no backend for Replay**: when there's no server,
it loads `data/runs.json` as a static file and runs in Replay mode. So the whole `demo/` folder
can be served as static files (e.g. GitHub Pages) and the demo just works — real captured runs,
zero keys, zero cost. Run `serve.py` locally when you want the live Cloud/Local modes.

## How it stays honest about "no changes to main code"

Everything here lives under `demo/`. `spine.py` **imports** the chapter agents read-only — the exact
`importlib` pattern chapters 11 and 13 already use — and derives the display fields from the public
`AgentResult`. It never edits `dataagent/` or any chapter. `git diff` those paths after adding this
folder and you'll see nothing.

## Files

```
demo/
  serve.py     stdlib HTTP server — routes only; the agents do the work
  spine.py     read-only orchestrator: one question → three real columns + tracer receipts
  capture.py   record real runs → data/runs.json (the replay source)
  index.html   one self-contained page; live via serve.py, static via data/runs.json
  data/runs.json   captured real runs (committed, so the hosted demo works with no key)
  test_spine.py    offline tests for the pure glue
```
