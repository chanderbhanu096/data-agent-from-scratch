"""Tests for chapter 12 — tracing.

The live run needs a provider; these don't. They test the machinery: that the
Tracer turns the loop's cumulative counter into honest per-step deltas, and that
a run round-trips through JSONL unchanged. Driven with real Step/AgentResult
types and a fake counter — no model, no cost.
"""

from __future__ import annotations

from conftest import load_run
from dataagent.llm import ToolCall, Usage
from dataagent.trace import Tracer, load_jsonl, save_jsonl, trace_record

run = load_run(__file__)
Step = run._ch05.Step
AgentResult = run._ch05.AgentResult
StopReason = run._ch05.StopReason


class FakeLLM:
    """Just the one thing the Tracer reads: a cumulative Usage that grows."""

    def __init__(self) -> None:
        self.total = Usage()

    def add(self, i: int, o: int, c: float) -> None:
        self.total = self.total + Usage(i, o, c)  # new object, as the real loop does


def test_tracer_records_one_row_per_step_with_token_deltas():
    llm = FakeLLM()
    tr = Tracer(llm)

    llm.add(100, 20, 0.0010)
    tr(Step(n=1, thinking="  first   thought ", calls=[ToolCall("a", "run_sql", {})]))
    llm.add(50, 10, 0.0005)
    tr(Step(n=2, thinking="second", calls=[]))

    assert [s.n for s in tr.steps] == [1, 2]
    assert (tr.steps[0].input_tokens, tr.steps[0].output_tokens) == (100, 20)
    assert (tr.steps[1].input_tokens, tr.steps[1].output_tokens) == (50, 10)
    assert tr.steps[0].tools == ["run_sql"]
    assert tr.steps[1].tools == []
    assert tr.steps[0].thinking == "first thought"  # collapsed whitespace


def test_step_deltas_sum_to_the_cumulative_total():
    llm = FakeLLM()
    tr = Tracer(llm)
    for i in range(3):
        llm.add(10 * (i + 1), i + 1, 0.0001)
        tr(Step(n=i + 1, thinking="t", calls=[]))
    assert sum(s.input_tokens for s in tr.steps) == llm.total.input_tokens
    assert sum(s.output_tokens for s in tr.steps) == llm.total.output_tokens


def test_a_run_roundtrips_through_jsonl_unchanged(tmp_path):
    llm = FakeLLM()
    tr = Tracer(llm)
    llm.add(120, 30, 0.0012)
    tr(Step(n=1, thinking="t", calls=[]))
    result = AgentResult(
        answer="  42   trips ",
        steps=[Step(n=1, thinking="t", calls=[])],
        usage=llm.total,
        stop_reason=StopReason.ANSWERED,
    )

    rec = trace_record("How many?", result, tr, provider="x", model="y")
    assert rec["answer"] == "42 trips"
    assert rec["grounded"] is False  # no successful tool result was recorded
    assert rec["stop_reason"] == "answered"

    path = tmp_path / "traces.jsonl"
    save_jsonl(rec, path)
    save_jsonl(rec, path)  # appends — a file is a history, not a snapshot
    loaded = load_jsonl(path)
    assert len(loaded) == 2
    assert loaded[0] == rec
