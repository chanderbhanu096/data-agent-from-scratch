# → Run Chapter 15 against Azure Blob Storage

The chapter reads a CSV from a **local** MCP server. This guide moves that same CSV into **Azure
Blob Storage** and reads it over Microsoft's official **Azure MCP Server** — so the agent answers
from a file in the cloud. The agent loop, the client, and the tests do not change; the server on
the other end of the pipe does.

## What's verified vs. what you run

Being straight about this, because I couldn't run it end-to-end from the repo session:

**Verified in this repo:**
- The filesystem version of this chapter runs and is tested (that's `run.py` / `test_15.py`).
- `@azure/mcp` is a real package (currently `3.0.0-beta.35`).
- It **requires Node ≥ 22**. On Node 20 it prints nothing on stdio and does not start.

**You run (needs your Azure account, so it isn't executed here):**
- Everything below. The tool *names* the Azure server exposes are discovered at runtime via
  `tools/list` — I don't hard-code them, and neither should you.

## Prerequisites

1. **Node 22+.** You likely have 20 (`node --version`). Upgrade for this leg only:
   ```bash
   nvm install 22 && nvm use 22
   ```
2. **Azure CLI, logged in.** Clear the tenant's *security-defaults* wall first — listing storage
   fails with `AADSTS530035` until you re-login with the management scope (the error prescribes
   this exact command):
   ```bash
   az login --scope "https://management.core.windows.net//.default"
   ```

## 1. Put the CSV in the cloud

Storage-account names are globally unique, 3–24 lowercase letters/numbers. Pick your own.

```bash
RG=data-agent-demo-rg
ACCT=dataagentblob$RANDOM
LOC=francecentral

az storage account create -g $RG -n $ACCT -l $LOC --sku Standard_LRS
az storage container create --account-name $ACCT -n inbox --auth-mode login
az storage blob upload --account-name $ACCT -c inbox --auth-mode login \
  -f chapters/15_mcp_connect/inbox/taxi_zones.csv -n taxi_zones.csv
```

## 2. Grant yourself data-plane read

Being subscription Owner is a *control-plane* role; reading blob **data** over AAD needs a
data-plane role. The Azure MCP server authenticates as you (`DefaultAzureCredential`), so assign
it to your own identity:

```bash
ME=$(az ad signed-in-user show --query id -o tsv)
SCOPE=$(az storage account show -g $RG -n $ACCT --query id -o tsv)
az role assignment create --role "Storage Blob Data Reader" --assignee $ME --scope $SCOPE
```

(Role assignments can take a minute to propagate.)

## 3. Point the same client at Azure

The only code change is the launch command. Save as `chapters/15_mcp_connect/run_azure.py`:

```python
from run import MCPClient, run_agent_over_mcp
from dataagent.config import load_settings
from dataagent.llm import LLM

# Same client class as the filesystem chapter — different server on the other end.
client = MCPClient(["npx", "-y", "@azure/mcp@latest", "server", "start"])
print("Azure MCP tools:", [t.name for t in client.tools()])  # discover what it offers

# The Azure server offers storage tools instead of filesystem tools, so the system
# prompt names *those*. Everything else — the loop, the client, grounding — is unchanged.
SYSTEM = (
    "You answer using ONLY the tools provided, which read Azure Blob Storage. "
    "Find the storage account, list the 'inbox' container, read 'taxi_zones.csv', "
    "and answer strictly from its contents. Never guess."
)
import run as ch15

ch15.SYSTEM = SYSTEM  # reuse run_agent_over_mcp with the cloud-flavored prompt

q = "Using the taxi-zone lookup in blob storage, which borough is LocationID 132?"
result = run_agent_over_mcp(LLM(load_settings()), q, client)
print("A", result.answer, "| grounded:", result.grounded)
client.close()
```

```bash
node --version   # must be 22+
cd chapters/15_mcp_connect && python run_azure.py
```

You should see the agent discover the Azure storage tools, read the blob, and give the same
answer it gave for the local file — now sourced from the cloud. That screenshot is the portfolio
shot: *your* text-to-SQL agent reading live Azure data over MCP, with no bespoke Azure code.

## Teardown

```bash
az group delete -n data-agent-demo-rg --yes --no-wait
```

## Google Drive instead?

Identical shape, different server: launch the Google Drive MCP server rather than the Azure one
and authorize it once. The catch is setup, not MCP — Google Drive needs a **new Google Cloud
project and OAuth consent screen** you build yourself, whereas Azure reuses the `az login` you
already have. That's the only reason this guide leads with Azure.
