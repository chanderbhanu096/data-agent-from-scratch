#!/usr/bin/env bash
# Deploy the live demo to Azure Static Web Apps (Free tier — $0, no credit burn).
#
# Prereqs: `az login` (interactive) and Node/npm on PATH. Run from the repo root:
#     bash demo/deploy_azure.sh
#
# It hosts the static replay (demo/index.html + demo/data/runs.json): a real,
# always-on HTTPS link that plays back captured runs with no key and no cost.
# The live Cloud/Local modes stay local (python demo/serve.py) on purpose — a
# public backend would burn your model credits on every visitor.
set -euo pipefail

RG=${RG:-data-agent-demo-rg}
LOC=${LOC:-eastus2}            # a Static Web Apps Free region accepting new apps
APP=${APP:-data-agent-live-demo}

echo "→ resource group: $RG ($LOC)"
az group create -n "$RG" -l "$LOC" -o none

echo "→ static web app: $APP (Free)"
az staticwebapp create -n "$APP" -g "$RG" -l "$LOC" --sku Free -o none

echo "→ fetching deployment token"
TOKEN=$(az staticwebapp secrets list -n "$APP" -g "$RG" --query "properties.apiKey" -o tsv)

echo "→ uploading demo/ (static replay)"
npx -y @azure/static-web-apps-cli deploy ./demo \
  --deployment-token "$TOKEN" --env production

HOST=$(az staticwebapp show -n "$APP" -g "$RG" --query "defaultHostname" -o tsv)
echo
echo "✅ Live at: https://$HOST"
echo "   Tear it all down later with:  az group delete -n $RG --yes --no-wait"
