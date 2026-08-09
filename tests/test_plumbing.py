"""End-to-end tests of the agent's plumbing, using a scripted model.

These cover the logic no unit test reaches: does the repair loop actually
re-prompt, does a tool round-trip build a conversation the API would accept,
does cost accumulate across turns.

What they deliberately do NOT cover: whether a real model behaves sensibly.
That needs a real provider — see the README.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dataagent.llm import Reply, ToolCall, Usage, _to_anthropic, _to_openai
from dataagent.testing import ScriptedLLM


def load_chapter(folder: str):
    import importlib.util

    path = REPO_ROOT / "chapters" / folder / "run.py"
    spec = importlib.util.spec_from_file_location(f"plumbing_{folder}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ── Chapter 02: the validate-and-repair loop ──────────────────────────────────

ch02 = load_chapter("02_structured_output")

GOOD_JSON = (
    '{"intent": "aggregate", "tables_needed": ["trips", "zones"], '
    '"time_filtered": true, "reasoning": "Averages tips by borough."}'
)


def test_valid_first_response_costs_exactly_one_call():
    llm = ScriptedLLM([Reply(text=GOOD_JSON)])
    plan = ch02.plan_question(llm, "avg tip by borough?")
    assert plan.intent == "aggregate"
    assert llm.call_count == 1


def test_repair_loop_recovers_from_invalid_json():
    llm = ScriptedLLM([Reply(text="I'd be happy to help!"), Reply(text=GOOD_JSON)])
    plan = ch02.plan_question(llm, "avg tip by borough?")
    assert plan.intent == "aggregate"
    assert llm.call_count == 2


def test_repair_prompt_shows_the_model_its_own_output_and_the_error():
    """The whole point of the loop: the retry must be specific, not 'try again'."""
    llm = ScriptedLLM([Reply(text='{"intent": "teleport"}'), Reply(text=GOOD_JSON)])
    ch02.plan_question(llm, "avg tip by borough?")

    second_turn = llm.calls[1].messages
    assert second_turn[1]["role"] == "assistant"
    assert second_turn[1]["content"] == '{"intent": "teleport"}'

    repair = second_turn[2]["content"]
    assert repair.startswith("That did not validate")
    assert "intent" in repair, "the repair prompt must name the offending field"


def test_repair_loop_gives_up_rather_than_looping_forever():
    llm = ScriptedLLM([Reply(text="nope")] * 3)
    with pytest.raises(ValueError):
        ch02.plan_question(llm, "avg tip by borough?", max_attempts=3)
    assert llm.call_count == 3


def test_schema_is_sent_in_the_system_prompt():
    llm = ScriptedLLM([Reply(text=GOOD_JSON)])
    ch02.plan_question(llm, "avg tip by borough?")
    system = llm.calls[0].system
    assert "tables_needed" in system and "unanswerable" in system


# ── Chapter 04: a full tool round-trip ────────────────────────────────────────

ch04 = load_chapter("04_tool_calling")


def test_tool_round_trip_builds_a_conversation_the_api_would_accept():
    """Replays chapter 04's exact message-building, then validates the result."""
    call = ToolCall("t1", "run_sql", {"sql": "SELECT count(*) FROM trips"})
    llm = ScriptedLLM(
        [
            Reply(text="", tool_calls=[call], usage=Usage(100, 20, 0.001), stop_reason="tool_use"),
            Reply(text="There are 300,000 trips.", usage=Usage(400, 30, 0.003)),
        ]
    )

    messages: list[dict] = [{"role": "user", "content": "how many trips?"}]
    first = llm.chat(messages, system=ch04.SYSTEM, tools=ch04.TOOLS)
    assert first.wants_tools

    messages.append({"role": "assistant", "content": first.text, "tool_calls": first.tool_calls})
    for c in first.tool_calls:
        result = ch04.execute(c.name, c.arguments)
        messages.append({"role": "tool", "tool_call_id": c.id, "content": result})

    final = llm.chat(messages, system=ch04.SYSTEM, tools=ch04.TOOLS)
    assert not final.wants_tools

    # The tool actually hit the real warehouse.
    assert "300000" in messages[2]["content"].replace(",", "")

    # And the conversation translates into a valid shape for both providers.
    anthropic = _to_anthropic(messages)
    assert [m["role"] for m in anthropic] == ["user", "assistant", "user"]
    assert anthropic[1]["content"][0]["type"] == "tool_use"
    assert anthropic[2]["content"][0]["type"] == "tool_result"
    assert anthropic[2]["content"][0]["tool_use_id"] == "t1"

    openai = _to_openai(messages)
    assert [m["role"] for m in openai] == ["user", "assistant", "tool"]
    assert openai[2]["tool_call_id"] == "t1"

    # Cost accumulated across both turns.
    assert llm.total.input_tokens == 500
    assert llm.total.cost_usd == pytest.approx(0.004)


def test_a_rejected_tool_call_still_produces_a_valid_conversation():
    """A guardrail rejection must be a normal tool result, not a broken turn."""
    call = ToolCall("t9", "run_sql", {"sql": "DROP TABLE trips"})
    messages: list[dict] = [
        {"role": "user", "content": "delete everything"},
        {"role": "assistant", "content": "", "tool_calls": [call]},
    ]
    result = ch04.execute(call.name, call.arguments)
    assert result.startswith("REJECTED:")

    messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
    anthropic = _to_anthropic(messages)
    assert anthropic[2]["content"][0]["content"].startswith("REJECTED:")


def test_scripted_llm_catches_a_runaway_loop():
    """Guard on the guard: the double must fail loudly if the loop won't stop."""
    llm = ScriptedLLM([Reply(text="x")])
    llm.chat([{"role": "user", "content": "hi"}])
    with pytest.raises(AssertionError, match="ran longer than expected"):
        llm.chat([{"role": "user", "content": "hi again"}])
