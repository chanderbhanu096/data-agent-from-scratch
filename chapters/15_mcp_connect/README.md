# 15 — Connect to an MCP server you didn't write

```bash
python chapters/15_mcp_connect/run.py
```

Chapter 14 built *both* ends of MCP ourselves — our server, our client, talking to each
other. It proved the wire works, but it was a **loopback**: a USB cable plugged from a laptop
back into the same laptop. It never showed the point of MCP, which is reaching a tool
**somebody else wrote**.

This chapter throws away our toy server and points the same agent loop at the **official
filesystem MCP server** — a real program installed with `npx`, none of whose code is ours. The
agent gains a file-reading tool it never had, and answers a question whose answer lives *only*
in an external file: a NYC taxi-zone lookup (`inbox/taxi_zones.csv`) that isn't in our
warehouse. That's "MCP connects your agent to your files / your database / your apps" — made
real, in forty lines you can read.

## The one change from Chapter 14

Chapter 14's client could skip the formalities because it talked to our own compliant server. A
**real** server expects the full handshake before it serves anything:

```python
self._rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {...}})
self._notify("notifications/initialized")  # a message with no id and no reply
```

That notification — one line, no response — is the only wire shape Chapter 14 didn't need.
Everything after it is identical: `tools/list` to discover, `tools/call` to run. And the agent
loop itself is **still** Chapter 05, unchanged. As in Chapter 14, we point its `execute` name at
the client:

```python
_ch05.execute = client.call_tool  # ACT now runs in a program we didn't write
run_agent(llm, question, tools=safe, system=SYSTEM)
```

The only new thing is *whose code* is on the other end of the pipe.

## What a real run looks like

```
handshake ok · the server offers 14 tools
we let the model use only: ['list_allowed_directories', 'list_directory', 'read_text_file', 'search_files']
direct list_directory over stdio → [FILE] taxi_zones.csv

Q Using the taxi-zone lookup, which borough and zone is LocationID 132? Also, how many of the listed zones are in Queens?
A LocationID 132 is in Queens, zone "JFK Airport." There are 4 listed zones in Queens.
read from an external MCP server · 3 tool calls · grounded=True · stop=answered
```

The agent discovered the folder (`list_allowed_directories`), listed it, read the CSV, and
answered from data that exists nowhere in our own code or warehouse — three tool calls, all
executed inside a process we didn't write. `grounded=True` means the same thing it has meant
since Chapter 05: a tool actually returned the data the answer rests on.

## Least privilege across the process line

The filesystem server offers **14** tools — including `write_file`, `edit_file`, `move_file`.
We hand the model only four, all read-only:

```python
SAFE_TOOLS = {"list_allowed_directories", "list_directory", "read_text_file", "search_files"}
```

A server you didn't write runs with whatever access you give it, so give it the least. Two
guardrails prove out in the tests: the model is never shown a tool that can mutate the disk, and
the server's **own** sandbox rejects a path escape — `read_text_file("/etc/passwd")` comes back
as an error *result* ("Access denied - path outside allowed directories"), not a breach, and the
server stays up. Across a process boundary the boundary matters *more*, not less.

## → Same client, now on the cloud (Azure Blob / Google Drive)

Here's the payoff the loopback couldn't show. The client above talks to *any* MCP server, so
moving the file into the cloud changes essentially **one thing — the launch command** (the loop
and client are byte-for-byte identical; the prompt just names whatever tools the new server
offers):

```python
# today:   a local folder
MCPClient(["npx", "-y", "@modelcontextprotocol/server-filesystem", "inbox"])
# tomorrow: the same CSV in Azure Blob Storage, read over Microsoft's official Azure MCP server
MCPClient(["npx", "-y", "@azure/mcp", "server", "start"])
```

Same loop, same client, same answer — the file just lives in Azure now.
**[`azure_blob.md`](azure_blob.md)** is the turnkey guide: it reuses your existing `az login`
(no new OAuth app), uploads the sample CSV to a storage account, and runs this exact chapter
against the cloud. Google Drive works identically — swap in its MCP server and authorize once.

## Where this is deliberately minimal (and honest)

- **Node required.** The filesystem server is a Node program; `python run.py` and the tests skip
  cleanly if `npx` isn't installed. The pin (`@2026.7.10`) keeps the tests reproducible — the
  server's tool names have changed across versions (`read_file` → `read_text_file`), which is
  exactly why a teaching repo pins.
- **stdio transport, synchronous.** One JSON line out, one back. Real clients also speak MCP's
  HTTP/SSE transport and pipeline requests; same messages, different plumbing.
- **The answer is only as good as the file.** MCP moved *where* the data comes from, not whether
  it's true. Grounding still means "a tool returned it" — garbage in the CSV would ground a
  garbage answer. That's a feature: the source is now explicit.

## Exercise

1. Drop a second CSV in `inbox/` and ask a question that spans both files — the agent will
   `list_directory`, then read what it needs. No code change; that's the plug-in property.
2. Add `write_file` to `SAFE_TOOLS` and ask the agent to "save a summary." Watch it gain the
   ability to *change your disk*, and decide whether you'd ever want that on by default.
3. Do the cloud swap in [`azure_blob.md`](azure_blob.md). The only line that changes is the one
   that launches the server.

---

Chapters 14 and 15 are the two halves of MCP: **serve** a tool to the world, and **consume** one
the world serves you. Both reuse Chapter 05's loop untouched — because MCP was never a new kind
of agent, only a new place for the `execute()` seam to reach.
