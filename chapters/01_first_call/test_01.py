"""Tests for chapter 01 — the gateway's plumbing, no network required.

The model call itself isn't tested here (it's non-deterministic and costs money).
What IS tested is the part that silently breaks things: message translation.
"""

from __future__ import annotations

from dataagent.llm import ToolCall, _to_anthropic, _to_openai, price


def test_plain_messages_pass_through():
    msgs = [{"role": "user", "content": "hi"}]
    assert _to_anthropic(msgs) == [{"role": "user", "content": "hi"}]
    assert _to_openai(msgs) == [{"role": "user", "content": "hi"}]


def test_anthropic_puts_tool_calls_inside_the_assistant_message():
    msgs = [
        {"role": "user", "content": "count trips"},
        {
            "role": "assistant",
            "content": "checking",
            "tool_calls": [ToolCall("t1", "run_sql", {"sql": "SELECT 1"})],
        },
    ]
    out = _to_anthropic(msgs)
    blocks = out[1]["content"]
    assert blocks[0] == {"type": "text", "text": "checking"}
    assert blocks[1]["type"] == "tool_use"
    assert blocks[1]["id"] == "t1"
    assert blocks[1]["input"] == {"sql": "SELECT 1"}


def test_anthropic_sends_tool_results_as_a_user_turn():
    """The detail that trips everyone up the first time."""
    msgs = [{"role": "tool", "tool_call_id": "t1", "content": "42"}]
    out = _to_anthropic(msgs)
    assert out[0]["role"] == "user"
    assert out[0]["content"][0]["type"] == "tool_result"
    assert out[0]["content"][0]["tool_use_id"] == "t1"


def test_parallel_tool_results_merge_into_one_turn():
    """Two tools called at once must come back in a single user message."""
    msgs = [
        {"role": "tool", "tool_call_id": "a", "content": "1"},
        {"role": "tool", "tool_call_id": "b", "content": "2"},
    ]
    out = _to_anthropic(msgs)
    assert len(out) == 1
    assert len(out[0]["content"]) == 2


def test_openai_serialises_tool_arguments_as_json():
    msgs = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [ToolCall("t1", "run_sql", {"sql": "SELECT 1"})],
        }
    ]
    fn = _to_openai(msgs)[0]["tool_calls"][0]["function"]
    assert fn["arguments"] == '{"sql": "SELECT 1"}'


def test_pricing_is_per_million_tokens():
    # 1M in + 1M out on Opus 5 = $5 + $25
    assert price("claude-opus-5", 1_000_000, 1_000_000) == 30.0
    # Unknown / local models are free, not a crash.
    assert price("qwen2.5:7b", 999, 999) == 0.0


def test_ollama_keeps_tool_arguments_as_an_object():
    """The bug a live run found: OpenAI wants a JSON string here, Ollama a dict.

    Sending OpenAI's shape to Ollama returns a 400 reading
    "Value looks like object, but can't find closing '}' symbol".
    """
    from dataagent.llm import _to_ollama

    msgs = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [ToolCall("t1", "run_sql", {"sql": "SELECT 1"})],
        }
    ]
    args = _to_ollama(msgs)[0]["tool_calls"][0]["function"]["arguments"]
    assert args == {"sql": "SELECT 1"}, "must stay a dict, not a serialised string"
    assert not isinstance(args, str)


def test_ollama_matches_tool_results_by_name_not_id():
    """Ollama ignores tool_call_id, so the name must be carried across."""
    from dataagent.llm import _to_ollama

    msgs = [
        {"role": "user", "content": "count"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [ToolCall("t1", "run_sql", {"sql": "SELECT 1"})],
        },
        {"role": "tool", "tool_call_id": "t1", "content": "1"},
    ]
    result = _to_ollama(msgs)[2]
    assert result["role"] == "tool"
    assert result["tool_name"] == "run_sql"
    assert result["content"] == "1"
