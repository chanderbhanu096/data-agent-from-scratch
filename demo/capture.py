"""Capture real runs for the offline / hosted replay.

    python demo/capture.py                 # cloud (Azure) by default
    python demo/capture.py --mode local    # or your local Ollama

Runs every demo question through all three chapter columns for real, and writes
the results to demo/data/runs.json. That file is what the static page replays —
so the hosted demo is genuine output, captured once, not a mock-up. Re-run this
whenever an agent changes and the recorded runs would otherwise drift.

ponytail: this is the same spine the live server uses, looped over the question
set and dumped to disk. No second code path to keep in sync.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from demo import spine


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="cloud", choices=["cloud", "local"])
    args = ap.parse_args()

    if not spine.mode_available(args.mode):
        print(f"{args.mode} mode isn't configured — set it up in .env first.")
        raise SystemExit(1)

    questions = spine.DEMO_QUESTIONS
    columns = [{k: c[k] for k in ("id", "chapter", "title", "subtitle")} for c in spine.COLUMNS]
    runs: dict[str, list] = {}

    for qi, question in enumerate(questions, 1):
        print(f"[{qi}/{len(questions)}] {question}")
        cols = []
        for col in spine.COLUMNS:
            t0 = time.perf_counter()
            payload = spine.run_column(col["id"], question, args.mode)
            dt = time.perf_counter() - t0
            mark = "ok" if not payload.get("error") else f"ERR {payload['error']}"
            print(f"    {col['id']}: {mark}  ({dt:.1f}s)  → {payload.get('answer', '')[:60]}")
            cols.append(payload)
        runs[question] = cols

    out = {
        "captured_with": args.mode,
        "questions": questions,
        "columns": columns,
        "runs": runs,
    }
    spine.DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    spine.DATA_PATH.write_text(json.dumps(out, indent=2))
    print(f"\nwrote {spine.DATA_PATH.relative_to(HERE.parent)} — {len(questions)} questions x {len(columns)} columns")


if __name__ == "__main__":
    main()
