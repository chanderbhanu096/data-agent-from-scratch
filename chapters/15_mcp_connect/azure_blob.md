# → Connect Chapter 15 to the cloud (Azure over MCP, and the honest limit)

The chapter reads a CSV's **contents** from a local MCP server and answers from the data. This
guide points the *same client* at the cloud. The client and loop don't change; the server on the
other end does. But which cloud server you pick decides what the agent can actually do — and
there's one limit worth knowing **before** you spend time on setup.

## The limit I verified (read this first)

I probed Microsoft's official Azure MCP server (`@azure/mcp@3.0.0-beta.35`) directly. Its blob
command, `storage_blob_get`, reports:

> Returns: blob name, size, lastModified, contentType, contentHash, metadata, and blob properties.

That's **metadata, not the file's contents** — and there is no download/content command anywhere
in its storage tools. So the official Azure server **cannot** reproduce this chapter's demo
(*read the CSV rows and answer from them*). It can tell the agent *that* `taxi_zones.csv` exists
and how big it is; it cannot hand over the rows.

That splits the cloud path in two:

| You want… | Use | Cost |
|-----------|-----|------|
| The agent to **read a cloud file's data** and answer (the strong demo) | A **content-capable** server — **Google Drive**'s MCP server reads file content | A one-time Google Cloud OAuth project |
| Low-friction Azure that **reuses your `az login`** | `@azure/mcp` — the agent **inspects live storage** (containers, blobs, sizes) | Metadata only, no file contents |

The **filesystem** version in `run.py` is the complete content-read demo and needs neither. Pick a
cloud leg below only for the "it's live in the cloud" flourish.

---

## Option A — Azure: inspect live storage over MCP (reuses your `az login`)

The agent connects to your real Azure and answers questions *about* your storage — "what
containers exist, what blobs are in `inbox`, how big is `taxi_zones.csv`". Real cloud, real MCP,
no new OAuth. Just not file contents.

**What's verified vs. what you run.** Verified here: the package, that it needs **Node ≥ 22**
(you have 24 — good), that `server start` speaks stdio JSON-RPC, and its tool shape (below). You
run: the actual Azure calls, since they need your account.

**How its tools work.** Unlike the filesystem server's flat `read_text_file`, Azure exposes one
namespaced `storage` meta-tool. The model calls it twice: first `{"learn": true}` to list child
commands, then `{"command": "...", "parameters": {...}}` to run one. Verified child commands:
`storage_account_get`, `storage_blob_container_get`, `storage_blob_get`, `storage_blob_upload`,
`storage_table_list`.

### 1. Clear the security-defaults wall, then create + fill a container

Listing storage fails with `AADSTS530035` until you re-login with the management scope (the error
prescribes this exact command):

```bash
az login --scope "https://management.core.windows.net//.default"
```

```bash
RG=data-agent-demo-rg
ACCT=dataagentblob$RANDOM        # 3–24 lowercase letters/numbers, globally unique
LOC=francecentral

az storage account create -g $RG -n $ACCT -l $LOC --sku Standard_LRS
az storage container create --account-name $ACCT -n inbox --auth-mode login
az storage blob upload --account-name $ACCT -c inbox --auth-mode login \
  -f chapters/15_mcp_connect/inbox/taxi_zones.csv -n taxi_zones.csv
```

### 2. Grant yourself data-plane read

Subscription Owner is *control-plane*; reading storage over AAD needs a data-plane role. The Azure
MCP server authenticates as you (`DefaultAzureCredential`), so assign it to your identity:

```bash
ME=$(az ad signed-in-user show --query id -o tsv)
SCOPE=$(az storage account show -g $RG -n $ACCT --query id -o tsv)
az role assignment create --role "Storage Blob Data Reader" --assignee $ME --scope $SCOPE
```

### 3. Point the same client at Azure

Save as `chapters/15_mcp_connect/run_azure.py`. The client class is unchanged; only the launch
command and the prompt (which names Azure's meta-tool) differ:

```python
from run import MCPClient, run_agent_over_mcp
import run as ch15
from dataagent.config import load_settings
from dataagent.llm import LLM

client = MCPClient(["npx", "-y", "@azure/mcp@latest", "server", "start"])

# Azure exposes a single 'storage' meta-tool with a learn-then-call pattern.
ch15.SAFE_TOOLS = {"storage"}
ch15.SYSTEM = (
    "You inspect Azure Storage through ONE tool named 'storage'. First call it with "
    '{"learn": true} to see its commands. Then call it with a "command" (e.g. '
    '"storage_blob_get") and "parameters" (account, container, subscription). Answer '
    "strictly from what the tool returns. It returns blob metadata (name, size, dates) — "
    "not file contents — so answer questions about the storage, not the file's rows."
)

q = "In my 'inbox' container, list the blobs and give the size of taxi_zones.csv."
result = run_agent_over_mcp(LLM(load_settings()), q, client)
print("A", result.answer, "| grounded:", result.grounded)
client.close()
```

```bash
node --version                 # 22+ (you have 24)
cd chapters/15_mcp_connect && python run_azure.py
```

You should see the agent discover the `storage` tool, learn its commands, and report your
container's blobs and `taxi_zones.csv`'s size — proof it's driving **live Azure over MCP** with no
bespoke Azure code. (Not executed in this repo — it needs your account.)

**Teardown:** `az group delete -n data-agent-demo-rg --yes --no-wait`

---

## Option B — Google Drive: read a cloud file's contents (the strong demo)

If you want the agent to actually **read the CSV and answer from its rows** in the cloud, use a
server that returns file **content**. Google Drive's MCP server does. The shape is identical to
the filesystem chapter — same client, same loop, and the prompt stays almost the same because
Drive, like the filesystem server, exposes a real "read this file" tool.

The only real cost is setup: Google Drive needs a **new Google Cloud project + OAuth consent
screen** you create yourself, then a one-time browser sign-in. That's the price of content access
Azure's official server doesn't offer. Upload `inbox/taxi_zones.csv` to a Drive folder, launch the
Drive MCP server, point `MCPClient([...])` at it, and ask the chapter's original question — the
agent reads the file and answers "132 → Queens / JFK Airport", now sourced from Drive.

I haven't scripted the Google Cloud project here (it's clicks in a console, not CLI you'd want
copy-pasted blind). If you go this route, say so and I'll write the exact console steps.
