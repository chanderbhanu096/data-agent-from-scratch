"""Tests for chapter 15 — talking to a real, third-party MCP server.

These spawn the official filesystem MCP server (a program we did not write) and
drive it over stdio: the full handshake, discovery, a real file read, and the
server's own sandbox refusal. No model — the agent driving is verified live and
shown in the README. Skipped where `npx` isn't installed, so the suite still runs
on a machine without Node.
"""

from __future__ import annotations

import shutil

import pytest

from conftest import load_run

run = load_run(__file__)

pytestmark = pytest.mark.skipif(shutil.which("npx") is None, reason="needs Node/npx")


def _client():
    return run.MCPClient(run.filesystem_server())


def test_client_discovers_a_server_we_did_not_write():
    client = _client()
    try:
        names = {t.name for t in client.tools()}
        # The read tools we rely on are really there, offered by the external server.
        assert {"list_directory", "read_text_file"} <= names
    finally:
        client.close()


def test_it_reads_a_file_that_lives_only_in_the_external_server():
    client = _client()
    try:
        # Root-relative path; the server resolves it against its allowed folder.
        text = client.call_tool("read_text_file", {"path": "taxi_zones.csv"})
        assert "132" in text and "JFK Airport" in text
    finally:
        client.close()


def test_the_servers_own_sandbox_blocks_a_path_escape():
    client = _client()
    try:
        out = client.call_tool("read_text_file", {"path": "/etc/passwd"})
        assert out.startswith("ERROR:")  # came back as a result, not a crash
        assert client.tools()  # server still alive afterwards
    finally:
        client.close()


def test_we_expose_only_read_only_tools_to_the_model():
    client = _client()
    try:
        offered = {t.name for t in client.tools()}
        # The server *can* write and delete; our SAFE_TOOLS filter must not pass those on.
        assert "write_file" in offered
        assert "write_file" not in run.SAFE_TOOLS
        assert "move_file" not in run.SAFE_TOOLS
    finally:
        client.close()
