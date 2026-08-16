"""Tests for chapter 14 — MCP over stdio.

These spawn the real server subprocess and talk to it, so they exercise the whole
wire path: handshake, discovery, a tool call, an error, and an unknown method.
No model — the agent driving is verified live. The warehouse must exist (CI builds
it) for the run_sql call.
"""

from __future__ import annotations

import pytest

from conftest import load_run

run = load_run(__file__)
MCPClient = run.MCPClient


def test_client_discovers_the_server_tools():
    client = MCPClient()
    try:
        names = {t.name for t in client.tools()}
        assert {"run_sql", "sample_column"} <= names
    finally:
        client.close()


def test_a_tool_call_executes_in_the_server_process():
    client = MCPClient()
    try:
        out = client.call_tool("run_sql", {"sql": "SELECT COUNT(*) AS n FROM trips"})
        assert "n" in out and "300000" in out.replace(",", "")
    finally:
        client.close()


def test_a_blocked_query_comes_back_as_an_error_result_not_a_crash():
    client = MCPClient()
    try:
        out = client.call_tool("run_sql", {"sql": "DROP TABLE trips"})
        assert "ERROR" in out.upper() or "REJECT" in out.upper()
        # server still alive afterwards
        assert client.tools()
    finally:
        client.close()


def test_unknown_method_surfaces_as_a_jsonrpc_error():
    client = MCPClient()
    try:
        with pytest.raises(RuntimeError):
            client._rpc("does/not/exist")
    finally:
        client.close()
