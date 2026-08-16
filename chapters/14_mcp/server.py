"""Chapter 14 — an MCP server, from scratch. Runs as a SEPARATE PROCESS.

    python chapters/14_mcp/server.py     # then feed it JSON-RPC lines on stdin

It speaks JSON-RPC 2.0 over stdio — one JSON message per line, the same transport
the Model Context Protocol uses — and exposes the agent's existing tools (run_sql,
sample_column) to whatever client launches it. Nothing about the tools changes:
this file only puts a wire protocol in front of the `execute()` seam from
Chapter 04, so the guardrails inside those tools still run here, in this process.

This is a deliberately minimal MCP subset — `initialize`, `tools/list`,
`tools/call` — enough to show the one idea that matters: the tools come from a
process you didn't write. The full spec adds notifications, resources, prompts,
and capability negotiation; none of that changes the seam.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dataagent.tools import TOOLS, execute


def _schema(tool: Any) -> dict:
    return {"name": tool.name, "description": tool.description, "inputSchema": tool.parameters}


def handle(req: dict) -> dict:
    """Map a JSON-RPC method to a result. Raising means an unknown method."""
    method = req.get("method")
    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "dataagent-sql", "version": "0.1"},
        }
    if method == "tools/list":
        return {"tools": [_schema(t) for t in TOOLS]}
    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            text = execute(name, args)
            return {"content": [{"type": "text", "text": text}], "isError": False}
        except Exception as e:  # noqa: BLE001 — a tool error is a result to report, not a transport crash
            return {"content": [{"type": "text", "text": f"ERROR: {e}"}], "isError": True}
    raise ValueError(f"unknown method {method!r}")


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        try:
            resp = {"jsonrpc": "2.0", "id": req.get("id"), "result": handle(req)}
        except Exception as e:  # noqa: BLE001 — report as a JSON-RPC error, keep the server alive
            resp = {
                "jsonrpc": "2.0",
                "id": req.get("id"),
                "error": {"code": -32601, "message": str(e)},
            }
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
