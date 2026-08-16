"""Tracing — turn "it worked" into something you can read after the fact.

The agent loop (chapter 05) already carries every fact a trace needs: each Step
with its thinking and tool calls, the cumulative Usage, why it stopped, whether
it was grounded. What it does *not* carry is a record you can open after the run
and diff across runs. This adds exactly that, and nothing more — without touching
the loop:

  - a `Tracer` you pass as the loop's `on_step` callback;
  - per-step wall-clock and cost, derived by diffing snapshots of `llm.total`
    (the loop only exposes the running total, and subtracting is enough);
  - one run → one JSON line you can grep, diff, or replay.

ponytail: per-step cost is a delta of the cumulative counter, not a new counter
threaded through the loop — reuse the number that's already there.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from dataagent.llm import Usage


@dataclass
class StepTrace:
    """One loop iteration, priced and timed. Deltas since the previous step."""

    n: int
    thinking: str
    tools: list[str]
    ms: float
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass
class Tracer:
    """A loop `on_step` callback that records a timed, priced timeline.

    Pass it in: `run_agent(..., on_step=tracer)`. After the run, `tracer.steps`
    is the receipt. Cost and tokens per step are the change in `llm.total`
    between calls, so this works for any provider without the loop knowing.
    """

    llm: Any
    steps: list[StepTrace] = field(default_factory=list)
    _t0: float = field(default_factory=time.perf_counter)
    _last: Usage = field(default_factory=Usage)
    _last_t: float = 0.0

    def __call__(self, step: Any) -> None:
        now = time.perf_counter() - self._t0
        total = self.llm.total  # a fresh Usage each step (loop does total = total + usage)
        self.steps.append(
            StepTrace(
                n=step.n,
                thinking=" ".join(step.thinking.split())[:200],
                tools=[c.name for c in step.calls],
                ms=round((now - self._last_t) * 1000, 1),
                input_tokens=total.input_tokens - self._last.input_tokens,
                output_tokens=total.output_tokens - self._last.output_tokens,
                cost_usd=round(total.cost_usd - self._last.cost_usd, 6),
            )
        )
        self._last = total
        self._last_t = now


def trace_record(question: str, result: Any, tracer: Tracer, *, provider: str, model: str) -> dict:
    """A full run as one serialisable dict — the line that gets saved."""
    return {
        "question": question,
        "provider": provider,
        "model": model,
        "answer": " ".join(result.answer.split()),
        "stop_reason": result.stop_reason.value,
        "grounded": result.grounded,
        "tool_calls": result.tool_calls_made,
        "steps": [asdict(s) for s in tracer.steps],
        "total": {
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "cost_usd": round(result.usage.cost_usd, 6),
            "ms": round(sum(s.ms for s in tracer.steps), 1),
        },
    }


def save_jsonl(record: dict, path: Path) -> None:
    """Append one run. JSONL so a file is a run history, not a single snapshot."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
