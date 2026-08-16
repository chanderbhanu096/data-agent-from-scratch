# 14 — Model Context Protocol (MCP)

```bash
python chapters/14_mcp/run.py
```

Every tool so far ran inside the agent's own process. **MCP** is the standard answer to a
different arrangement: the tool lives in a *separate process you didn't write*, and the agent
discovers what it offers by asking over a wire protocol. "Connect Claude to your database / your
files / your issue tracker" is this — a small server on the other end of a pipe.

This chapter builds both halves **from scratch**: a server and a client speaking JSON-RPC 2.0
over stdio (one JSON message per line), with no SDK — just `subprocess` and `json`.

## The one idea: the loop doesn't care where the tool runs

Chapter 05's loop executes a tool call with one line:

```python
result = execute(call.name, call.arguments)  # chapter 05
```

Chapter 14 changes **nothing** about that loop. It only points `execute` at an MCP client:

```python
_ch05.execute = client.call_tool          # ACT now crosses a process boundary
run_agent(llm, question, tools=client.tools(), ...)
```

`client.call_tool(name, arguments)` has the same signature as the local `execute`, so it drops
straight in. The model still emits a tool call; your code still runs it — the only difference is
that "runs it" now means *send JSON-RPC to another process and read the reply*. That the loop is
untouched is the point: MCP is a transport for the `execute()` seam, not a new kind of agent.

## What actually happens on the wire

```
client                          server (separate process)
  │  {"method":"initialize"}            │
  │ ───────────────────────────────────▶  handshake
  │  {"method":"tools/list"}            │
  │ ───────────────────────────────────▶  returns run_sql, sample_column
  │  {"method":"tools/call",            │
  │   "params":{"name":"run_sql", …}}   │
  │ ───────────────────────────────────▶  execute() runs the SQL *here*
  │  ◀─────────────────────────────────   {"content":[{"type":"text", …}]}
```

A real run:

```
handshake ok · discovered tools: ['run_sql', 'sample_column']
direct tools/call over stdio → 300000 trips
Q  What is the average tip amount by payment type?
A  Cash $0.0009935; Credit card $4.508; Dispute $0.05539; No charge $0.02414.
   the SQL ran in the MCP subprocess · grounded=True · stop=answered
```

The accuracy is identical to running the tool in-process — because it *is* the same tool, with
the same guardrails, just relocated. There is nothing to benchmark here: the measurement is that
the answer is unchanged while the execution moved across a process boundary. The guardrail proof
is in the tests — a `DROP TABLE` sent over the wire comes back as an error *result*, blocked
inside the server, and the server stays up.

## Where this is deliberately minimal (and honest)

- **A subset of MCP.** Just `initialize`, `tools/list`, `tools/call`. The real spec adds
  capability negotiation, notifications, resources, and prompts. None of them change the seam;
  they're more surface on the same idea.
- **Synchronous, one request at a time.** One JSON line out, one back. Real clients pipeline and
  handle server-initiated messages; that's concurrency plumbing, not a new concept.
- **stdio transport.** MCP also defines an HTTP/SSE transport for remote servers. Same messages,
  different pipe — swapping `subprocess` for an HTTP client is the whole change.
- **Trust.** A server you didn't write is code you didn't write. Here it's our own file; in the
  wild, an MCP server runs with whatever access you give it. The read-only, validated `run_sql`
  boundary matters *more* across a process line, not less.

## Exercise

1. Add a second tool to `server.py` (e.g. `count_rows(table)`) and watch the agent pick it up
   from `tools/list` with no client change — that's the plug-in property.
2. Kill the server mid-run. The client raises "server closed the connection" instead of hanging —
   find that line and decide what a production client should do instead.
3. Swap the stdio transport for HTTP: keep the JSON-RPC messages, replace `subprocess` with a
   tiny `http.server`. The agent loop should not change at all.

---

This is the last of the core architecture. From here the repo's frontier is operational:
multi-agent (a tool whose `execute()` is *another loop*) and deployment — both of which reuse
every seam built so far.
