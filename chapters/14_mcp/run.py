"""Chapter 14 — Model Context Protocol: the tool runs in a process you didn't write.

    python chapters/14_mcp/run.py

Every chapter so far executed tools in the same Python process as the agent. MCP
breaks that assumption: the tool lives in a separate process, reached over a wire
protocol, and the agent discovers what it can do by asking. That is the whole idea
behind "MCP" — a standard way to plug in tools from somewhere else.

The striking part is how little the agent changes. Chapter 05's loop calls
`execute(name, arguments)` for the ACT step. Point that one name at an MCP client
instead of the local function and the exact same loop now drives a tool across a
process boundary. The client here is written from scratch — `subprocess` plus
`json`, speaking JSON-RPC over stdio. No SDK.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rich.console import Console

from dataagent.cli import run_chapter
from dataagent.config import load_settings
from dataagent.llm import LLM, Tool, missing_credentials
from dataagent.tools import build_system_prompt

console = Console()
_SERVER = Path(__file__).resolve().parent / "server.py"


class MCPClient:
    """Launches an MCP server subprocess and talks JSON-RPC 2.0 over its stdio.

    Synchronous request/response: one JSON line out, one JSON line back. Enough
    to discover tools and call them — which is all the agent loop needs.
    """

    def __init__(self, server_path: Path = _SERVER) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, str(server_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._id = 0
        self._rpc("initialize")

    def _rpc(self, method: str, params: dict | None = None) -> Any:
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("MCP server closed the connection")
        reply = json.loads(line)
        if "error" in reply:
            raise RuntimeError(reply["error"]["message"])
        return reply["result"]

    def tools(self) -> list[Tool]:
        """Discover the server's tools and hand them to the model as Tool objects."""
        return [
            Tool(name=t["name"], description=t["description"], parameters=t["inputSchema"])
            for t in self._rpc("tools/list")["tools"]
        ]

    def call_tool(self, name: str, arguments: dict) -> str:
        """Same signature as dataagent.tools.execute, so it drops straight into the loop."""
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        return "".join(part["text"] for part in result.get("content", []))

    def close(self) -> None:
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001 — best-effort teardown
            self.proc.kill()


def _load_chapter_05():
    path = Path(__file__).resolve().parents[1] / "05_agent_loop" / "run.py"
    spec = importlib.util.spec_from_file_location("agent_05_for_14", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_ch05 = _load_chapter_05()


def run_agent_over_mcp(llm, question: str, client: MCPClient, **kwargs):
    """Chapter 05's loop, unchanged — except ACT now happens in the MCP process.

    Reassigning the `execute` name in chapter 05's module is the entire trick:
    the loop resolves it at call time, so the tool call goes over the wire.
    """
    _ch05.execute = client.call_tool
    return _ch05.run_agent(
        llm, question, tools=client.tools(), system=build_system_prompt(), **kwargs
    )


def main() -> None:
    settings = load_settings()
    console.print("[bold cyan]MCP — the tool runs in another process[/bold cyan]")
    console.print(f"[dim]{settings.provider}/{settings.model}[/dim]\n")

    client = MCPClient()
    console.print(
        f"[green]handshake ok[/green] · discovered tools: {[t.name for t in client.tools()]}"
    )
    # Prove the boundary directly: a query executed entirely in the server process.
    direct = client.call_tool("run_sql", {"sql": "SELECT COUNT(*) AS trips FROM trips"})
    console.print(f"[dim]direct tools/call over stdio →[/dim]\n{direct}")

    if missing_credentials(settings):
        console.print("\n[yellow]Set a provider in .env to drive the full agent over MCP.[/yellow]")
        client.close()
        return

    q = "What is the average tip amount by payment type? Show the payment type name."
    console.print(f"\n[cyan]Q[/cyan] {q}")
    result = run_agent_over_mcp(LLM(settings), q, client)
    console.print(f"[green]A[/green] {' '.join(result.answer.split())}")
    console.print(
        f"[dim]the SQL ran in the MCP subprocess · grounded={result.grounded} · "
        f"stop={result.stop_reason.value}[/dim]"
    )
    client.close()


if __name__ == "__main__":
    run_chapter(main)
