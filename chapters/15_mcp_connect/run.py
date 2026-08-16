"""Chapter 15 — connect to an MCP server you didn't write.

    python chapters/15_mcp_connect/run.py

Chapter 14 built both ends of MCP ourselves: our server, our client, talking to
each other. That proved the wire works, but it was a loopback — like plugging a
USB cable from a laptop back into the same laptop. It never showed the *point* of
MCP, which is reaching a tool somebody else wrote.

This chapter throws away our toy server and connects the same agent loop to the
**official filesystem MCP server** — a real, `npx`-installed program we did not
write. The agent gains a file-reading tool it never had, and answers a question
whose answer lives *only* in an external file (a taxi-zone lookup that isn't in
our warehouse). The moment it works, "MCP connects your agent to other apps"
stops being a slogan and becomes forty lines you can read.

The client below talks to *any* MCP server. Point it at the filesystem server
today; point it at Azure Blob Storage or Google Drive tomorrow (see
`azure_blob.md`) — same client, same loop, one different launch command.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rich.console import Console

from dataagent.cli import run_chapter
from dataagent.config import load_settings
from dataagent.llm import LLM, Tool, missing_credentials

console = Console()

INBOX = Path(__file__).resolve().parent / "inbox"

# Pinned so the tests are reproducible; unpin (`@latest`) to track upstream. The
# server's tool names have changed across versions (read_file → read_text_file),
# which is exactly why a teaching repo pins.
FS_SERVER_PKG = "@modelcontextprotocol/server-filesystem@2026.7.10"

# Only hand the model read-only tools. The server also exposes write_file,
# edit_file, move_file — a server you didn't write runs with whatever access you
# give it, so give it the least. This is the guardrail that matters *more* across
# a process boundary, not less.
SAFE_TOOLS = {"list_allowed_directories", "list_directory", "read_text_file", "search_files"}

SYSTEM = (
    "You answer questions using ONLY the tools provided. The tools read files from "
    "a folder served by an external MCP server. To answer: first call "
    "list_allowed_directories to find the folder, then list_directory to see what's "
    "in it, then read_text_file to read the relevant file. Base every fact strictly "
    "on the file contents. If the files do not contain the answer, say so — never guess."
)


def filesystem_server(inbox: Path = INBOX) -> list[str]:
    """The launch command for the official filesystem MCP server, rooted at `inbox`."""
    return ["npx", "-y", FS_SERVER_PKG, str(inbox)]


class MCPClient:
    """Talks JSON-RPC 2.0 over stdio to *any* MCP server — including ones you didn't write.

    Chapter 14's client spoke only to our own toy server, so it could skip the
    formalities. A real server expects the full `initialize` handshake and an
    `initialized` notification before it will serve requests. Those two lines are
    the entire difference. Everything after — discover tools, call a tool — is
    identical, which is the whole promise of MCP: one client, any server.
    """

    def __init__(self, command: list[str]) -> None:
        self.proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,  # the server logs startup noise here; we don't need it
            text=True,
            bufsize=1,
        )
        self._id = 0
        self._rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "data-agent", "version": "0.1"},
            },
        )
        self._notify("notifications/initialized")

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

    def _notify(self, method: str) -> None:
        """A notification has no id and gets no reply — the one wire shape ch14 skipped."""
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.proc.stdin.flush()

    def tools(self) -> list[Tool]:
        return [
            Tool(name=t["name"], description=t["description"], parameters=t["inputSchema"])
            for t in self._rpc("tools/list")["tools"]
        ]

    def call_tool(self, name: str, arguments: dict) -> str:
        """Same signature as dataagent.tools.execute, so it drops straight into ch05's loop."""
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        text = "".join(part.get("text", "") for part in result.get("content", []))
        # Mark server-side failures so the loop's grounding check treats them as failures.
        return f"ERROR: {text}" if result.get("isError") else text

    def close(self) -> None:
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001 — best-effort teardown
            self.proc.kill()


def _load_chapter_05():
    path = Path(__file__).resolve().parents[1] / "05_agent_loop" / "run.py"
    spec = importlib.util.spec_from_file_location("agent_05_for_15", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_ch05 = _load_chapter_05()


def run_agent_over_mcp(llm, question: str, client: MCPClient, **kwargs):
    """Chapter 05's loop, unchanged — ACT now runs a tool in a program we didn't write.

    Same trick as chapter 14: point ch05's `execute` name at the MCP client and
    the loop resolves it at call time, so the tool call goes over the wire. The
    only new thing here is *whose* code is on the other end.
    """
    _ch05.execute = client.call_tool
    safe = [t for t in client.tools() if t.name in SAFE_TOOLS]
    return _ch05.run_agent(llm, question, tools=safe, system=SYSTEM, **kwargs)


def main() -> None:
    if shutil.which("npx") is None:
        console.print("[red]npx not found.[/red] Install Node.js to run the filesystem MCP server.")
        return

    settings = load_settings()
    console.print("[bold cyan]MCP — connect to a server you didn't write[/bold cyan]")
    console.print(f"[dim]server: {FS_SERVER_PKG}  ·  folder: {INBOX.name}/[/dim]\n")

    client = MCPClient(filesystem_server())
    names = [t.name for t in client.tools()]
    console.print(f"[green]handshake ok[/green] · the server offers {len(names)} tools")
    console.print(f"[dim]we let the model use only: {sorted(SAFE_TOOLS & set(names))}[/dim]")

    # Prove the boundary directly: read a file that lives in a process we didn't write.
    listing = client.call_tool("list_directory", {"path": str(INBOX)})
    console.print(f"[dim]direct list_directory over stdio →[/dim] {listing.strip()}")

    if missing_credentials(settings):
        console.print("\n[yellow]Set a provider in .env to drive the full agent over MCP.[/yellow]")
        client.close()
        return

    q = (
        "Using the taxi-zone lookup, which borough and zone is LocationID 132? "
        "Also, how many of the listed zones are in Queens?"
    )
    console.print(f"\n[cyan]Q[/cyan] {q}")
    result = run_agent_over_mcp(LLM(settings), q, client)
    console.print(f"[green]A[/green] {' '.join(result.answer.split())}")
    console.print(
        f"[dim]read from an external MCP server · {result.tool_calls_made} tool calls · "
        f"grounded={result.grounded} · stop={result.stop_reason.value}[/dim]"
    )
    client.close()


if __name__ == "__main__":
    run_chapter(main)
