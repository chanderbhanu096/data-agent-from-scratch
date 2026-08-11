"""Tests for chapter 05 — the loop, driven by a scripted model.

The loop is the one piece of this repo where a bug is expensive: it spends money
and it can run forever. So the limits are tested harder than anything else here.
"""

from __future__ import annotations

import pytest

from conftest import load_run
from dataagent.llm import Reply, ToolCall, Usage
from dataagent.testing import ScriptedLLM
from dataagent.tools import TOOLS, build_system_prompt

run = load_run(__file__)
StopReason, run_agent = run.StopReason, run.run_agent

SYSTEM = build_system_prompt()


def agent(llm, question="q", **kw):
    return run_agent(llm, question, tools=TOOLS, system=SYSTEM, **kw)


def sql_call(sql, cid="t1"):
    return ToolCall(cid, "run_sql", {"sql": sql})


# ── The happy path ────────────────────────────────────────────────────────────


def test_a_reply_with_no_tool_calls_ends_the_loop_immediately():
    llm = ScriptedLLM([Reply(text="42 trips.")])
    result = agent(llm)
    assert result.stop_reason is StopReason.ANSWERED
    assert result.answer == "42 trips."
    assert llm.call_count == 1


def test_a_tool_call_produces_a_second_turn():
    llm = ScriptedLLM(
        [
            Reply(tool_calls=[sql_call("SELECT count(*) FROM trips")]),
            Reply(text="There are 300,000 trips."),
        ]
    )
    result = agent(llm)
    assert result.stop_reason is StopReason.ANSWERED
    assert result.tool_calls_made == 1
    assert "300000" in result.steps[0].results[0].replace(",", "")


def test_the_tool_result_is_actually_sent_back_to_the_model():
    """If OBSERVE is broken the agent still 'works' — it just answers blind."""
    llm = ScriptedLLM(
        [Reply(tool_calls=[sql_call("SELECT count(*) FROM trips")]), Reply(text="done")]
    )
    agent(llm)

    second_turn = llm.calls[1].messages
    assert second_turn[1]["role"] == "assistant"
    assert second_turn[1]["tool_calls"], "the assistant's own request must be replayed"
    assert second_turn[2]["role"] == "tool"
    assert "300000" in second_turn[2]["content"].replace(",", "")


def test_parallel_tool_calls_in_one_step_all_execute():
    llm = ScriptedLLM(
        [
            Reply(
                tool_calls=[
                    sql_call("SELECT count(*) FROM trips", "a"),
                    ToolCall("b", "sample_column", {"table": "zones", "column": "borough"}),
                ]
            ),
            Reply(text="done"),
        ]
    )
    result = agent(llm)
    assert result.tool_calls_made == 2
    assert "Manhattan" in result.steps[0].results[1]


# ── The limits, which are the whole reason this isn't just a while loop ───────


def test_step_limit_stops_an_agent_that_never_answers():
    """Without this the loop runs until the money or the patience runs out."""
    llm = ScriptedLLM([Reply(tool_calls=[sql_call("SELECT 1")])] * 10)
    result = agent(llm, max_steps=4)
    assert result.stop_reason is StopReason.MAX_STEPS
    assert llm.call_count == 4
    assert len(result.steps) == 4


def test_budget_limit_stops_before_the_next_call_not_after():
    """Checked at the top of the loop, so an over-budget agent never spends again."""
    expensive = Reply(tool_calls=[sql_call("SELECT 1")], usage=Usage(1000, 500, 0.40))
    llm = ScriptedLLM([expensive, expensive, expensive])
    result = agent(llm, max_usd=0.50)

    assert result.stop_reason is StopReason.MAX_BUDGET
    # Two calls costs $0.80, which is over budget; the third must never happen.
    assert llm.call_count == 2
    assert "budget" in result.answer.lower()


def test_a_sql_error_does_not_kill_the_run():
    """The loop's accidental superpower: an error is just another observation."""
    llm = ScriptedLLM(
        [
            Reply(tool_calls=[sql_call("SELECT * FROM nope")]),
            Reply(tool_calls=[sql_call("SELECT count(*) FROM trips", "t2")]),
            Reply(text="recovered"),
        ]
    )
    result = agent(llm)
    assert result.stop_reason is StopReason.ANSWERED
    assert result.steps[0].results[0].startswith("SQL ERROR")
    assert result.answer == "recovered"


def test_a_blocked_query_is_reported_and_the_loop_continues():
    llm = ScriptedLLM(
        [Reply(tool_calls=[sql_call("DROP TABLE trips")]), Reply(text="I can't do that.")]
    )
    result = agent(llm)
    assert result.steps[0].results[0].startswith("REJECTED")
    assert result.stop_reason is StopReason.ANSWERED


def test_an_unknown_tool_is_survivable():
    llm = ScriptedLLM([Reply(tool_calls=[ToolCall("x", "rm_rf", {})]), Reply(text="no such tool")])
    result = agent(llm)
    assert "no tool named" in result.steps[0].results[0]
    assert result.stop_reason is StopReason.ANSWERED


# ── Bookkeeping ───────────────────────────────────────────────────────────────


def test_usage_accumulates_across_every_step():
    llm = ScriptedLLM(
        [
            Reply(tool_calls=[sql_call("SELECT 1")], usage=Usage(100, 50, 0.01)),
            Reply(text="done", usage=Usage(200, 25, 0.02)),
        ]
    )
    result = agent(llm)
    assert result.usage.input_tokens == 300
    assert result.usage.output_tokens == 75
    assert result.usage.cost_usd == pytest.approx(0.03)


def test_on_step_fires_once_per_iteration_including_the_last():
    seen = []
    llm = ScriptedLLM([Reply(tool_calls=[sql_call("SELECT 1")]), Reply(text="done")])
    agent(llm, on_step=seen.append)
    assert [s.n for s in seen] == [1, 2]


# ── Detecting an answer you shouldn't trust ──────────────────────────────────


def test_an_answer_after_a_successful_tool_call_is_grounded():
    llm = ScriptedLLM(
        [Reply(tool_calls=[sql_call("SELECT count(*) FROM trips")]), Reply(text="300,000.")]
    )
    assert agent(llm).grounded is True


def test_an_answer_where_every_tool_call_failed_is_not_grounded():
    """The real failure seen on llama3.2:3b: error, then prose, then 'answered'."""
    llm = ScriptedLLM(
        [
            Reply(tool_calls=[sql_call("SELECT borough FROM trips")]),
            Reply(text="The highest is Staten Island at $2.38."),
        ]
    )
    result = agent(llm)
    assert result.stop_reason is StopReason.ANSWERED
    assert result.grounded is False, "no tool ever returned data — the number is invented"


def test_an_answer_with_no_tool_calls_at_all_is_not_grounded():
    llm = ScriptedLLM([Reply(text="Manhattan, obviously.")])
    assert agent(llm).grounded is False


def test_a_rejected_query_does_not_count_as_grounding():
    llm = ScriptedLLM([Reply(tool_calls=[sql_call("DROP TABLE trips")]), Reply(text="Done!")])
    assert agent(llm).grounded is False


def test_sql_in_the_final_answer_is_flagged():
    """The model typed the tool call instead of making it."""
    llm = ScriptedLLM([Reply(text="Here is the corrected version:\n```sql\nSELECT 1\n```")])
    assert agent(llm).wrote_sql_as_prose is True


def test_a_plain_english_answer_is_not_flagged_as_sql():
    llm = ScriptedLLM([Reply(text="Manhattan has the highest average tip, at $2.81.")])
    assert agent(llm).wrote_sql_as_prose is False
