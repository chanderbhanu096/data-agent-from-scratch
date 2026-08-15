#!/usr/bin/env bash
# Deploy the FULL live-demo backend to Azure App Service (Free F1 plan).
#
# This is the "real live experience" host: visitors get genuine model calls, not
# just recorded runs. It reads your Azure OpenAI creds from .env and sets them as
# server-side app settings. Cost: the F1 compute is free; the model calls spend
# your Azure OpenAI credits (one reason Local is hidden and Replay stays as the
# fallback). For the zero-cost, always-on, static-replay-only option, use
# deploy_azure.sh instead.
#
# Prereqs: `az login`, Node/npm not needed here. Run from the repo root:
#     bash demo/deploy_backend_azure.sh
set -euo pipefail

RG=${RG:-data-agent-demo-rg}
APP=${APP:-data-agent-live-demo}
PLAN=${PLAN:-data-agent-plan}
# F1 is refused in some regions ("not accepting new customers"); try a few.
REGIONS=(${REGIONS:-francecentral northeurope eastus2 uksouth westus2 centralus})

command -v az >/dev/null || { echo "az CLI required"; exit 1; }
[ -f .env ] || { echo "need .env with the Azure OpenAI creds"; exit 1; }

echo "→ resource group $RG"
az group create -n "$RG" -l "${REGIONS[0]}" -o none 2>/dev/null || true

echo "→ App Service plan $PLAN (Free F1) — finding a region that accepts it"
LOC=""
for r in "${REGIONS[@]}"; do
  if az appservice plan create -n "$PLAN" -g "$RG" -l "$r" --is-linux --sku F1 -o none 2>/dev/null; then
    LOC="$r"; echo "  created in $r"; break
  fi
  echo "  $r refused, trying next"
done
[ -n "$LOC" ] || { echo "no region accepted a Free plan; try a paid --sku B1"; exit 1; }

echo "→ web app $APP (Python 3.11)"
az webapp create -n "$APP" -g "$RG" -p "$PLAN" --runtime "PYTHON:3.11" -o none

echo "→ app settings (creds from .env, server-side)"
set -a; source <(grep -E '^(DATAAGENT_PROVIDER|AZURE_OPENAI_ENDPOINT|AZURE_OPENAI_API_KEY|AZURE_OPENAI_DEPLOYMENT)=' .env); set +a
az webapp config appsettings set -n "$APP" -g "$RG" --settings \
  DATAAGENT_PROVIDER="${DATAAGENT_PROVIDER:-azure}" \
  AZURE_OPENAI_ENDPOINT="$AZURE_OPENAI_ENDPOINT" \
  AZURE_OPENAI_API_KEY="$AZURE_OPENAI_API_KEY" \
  AZURE_OPENAI_DEPLOYMENT="$AZURE_OPENAI_DEPLOYMENT" \
  DEMO_DISABLE_LOCAL=1 \
  SCM_DO_BUILD_DURING_DEPLOYMENT=true \
  -o none

echo "→ startup command"
az webapp config set -n "$APP" -g "$RG" --startup-file "python demo/serve.py" -o none

echo "→ building deploy zip (code + 7MB warehouse)"
ZIP=$(mktemp -t dataagent-app-XXXX).zip
zip -r -q "$ZIP" dataagent chapters demo evals scripts data/taxi.duckdb requirements.txt pyproject.toml \
  -x '*/__pycache__/*' '*.pyc' '*/.pytest_cache/*' '*/.ruff_cache/*' '*.parquet'

echo "→ enabling SCM basic auth (some tenants block the AAD deploy channel)"
az resource update -g "$RG" --namespace Microsoft.Web --parent "sites/$APP" \
  --resource-type basicPublishingCredentialsPolicies -n scm --set properties.allow=true -o none

echo "→ pushing to Kudu zipdeploy (installs requirements, then starts serve.py)"
PUSER=$(az webapp deployment list-publishing-credentials -n "$APP" -g "$RG" --query publishingUserName -o tsv)
PPASS=$(az webapp deployment list-publishing-credentials -n "$APP" -g "$RG" --query publishingPassword -o tsv)
curl -sS -X POST -u "$PUSER:$PPASS" --data-binary @"$ZIP" -H "Content-Type: application/zip" \
  "https://$APP.scm.azurewebsites.net/api/zipdeploy?isAsync=false" --max-time 600 -o /dev/null -w "  deploy HTTP %{http_code}\n"
rm -f "$ZIP"

echo
echo "✅ Live at: https://$APP.azurewebsites.net"
echo "   Tear down everything:  az group delete -n $RG --yes --no-wait"
