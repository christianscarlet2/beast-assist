#!/usr/bin/env bash
# Provision the Azure side of Beast Assist: Entra app registrations + API Management (Consumption).
# Needs: az CLI signed in (az login --use-device-code), and a public HTTPS address for the MCP servers.
#
#   ./gateway/azure/setup.sh plan      show what would be created, change nothing
#   ./gateway/azure/setup.sh apply     create it (idempotent: re-running reuses what exists)
#   ./gateway/azure/setup.sh destroy   delete the resource group and the app registrations
set -euo pipefail

MODE=${1:-plan}
RG=${RG:-beast-assist}
LOCATION=${LOCATION:-eastus}
APIM=${APIM:-beast-assist-apim}
PUBLISHER_EMAIL=${PUBLISHER_EMAIL:-scarletbeast909@gmail.com}
BACKEND_URL=${BACKEND_URL:-https://mcp.scarletbeast.com}   # where the ingress serves /agile and /college
AUDIENCE=api://beast-assist
HERE=$(cd "$(dirname "$0")/.." && pwd)

TENANT=$(az account show --query tenantId -o tsv)
SUB=$(az account show --query id -o tsv)
echo "tenant $TENANT  subscription $SUB  mode $MODE"

app_id() { az ad app list --display-name "$1" --query "[0].appId" -o tsv; }

if [[ $MODE == plan ]]; then
  cat <<PLAN
Would create (free on a free account, APIM Consumption bills per call after 1M/month):
  resource group      $RG ($LOCATION)
  app registration    beast-assist-api   audience $AUDIENCE, app roles Tools.Read, Tools.Write, Skills.Publish
  app registration    beast-agent        granted Tools.Read + Tools.Write, client secret
  app registration    beast-evals        granted Tools.Read, client secret
  app registration    beast-publisher    granted Skills.Publish, client secret
  API Management      $APIM (Consumption) with APIs agile-mcp and college-mcp -> $BACKEND_URL
Existing: $(app_id beast-assist-api >/dev/null && echo "beast-assist-api=$(app_id beast-assist-api)")
PLAN
  exit 0
fi

if [[ $MODE == destroy ]]; then
  for a in beast-assist-api beast-agent beast-evals beast-publisher; do
    id=$(app_id $a); [[ -n $id ]] && az ad app delete --id "$id" && echo "deleted app $a"
  done
  az group delete -n "$RG" --yes --no-wait && echo "deleting resource group $RG"
  exit 0
fi

[[ $MODE == apply ]] || { echo "usage: $0 plan|apply|destroy"; exit 2; }

az group create -n "$RG" -l "$LOCATION" -o none

# --- the API: audience + app roles ---------------------------------------------------------------
API_ID=$(app_id beast-assist-api)
if [[ -z $API_ID ]]; then
  roles=$(python3 - <<'PY'
import json, uuid
print(json.dumps([{"allowedMemberTypes": ["Application"], "description": d, "displayName": n, "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, n)),
                   "isEnabled": True, "value": n} for n, d in [("Tools.Read", "Call read-only MCP tools"),
                   ("Tools.Write", "Call MCP tools that change a backend"), ("Skills.Publish", "Publish skills to the registry")]]))
PY
)
  API_ID=$(az ad app create --display-name beast-assist-api --identifier-uris "$AUDIENCE" \
             --app-roles "$roles" --query appId -o tsv)
  az ad sp create --id "$API_ID" -o none
  # v2 access tokens, so iss is https://login.microsoftonline.com/<tenant>/v2.0 as the servers expect
  az ad app update --id "$API_ID" --set api.requestedAccessTokenVersion=2
fi
API_SP=$(az ad sp show --id "$API_ID" --query id -o tsv)
role_id() { az ad sp show --id "$API_ID" --query "appRoles[?value=='$1'].id | [0]" -o tsv; }

client() {  # client <name> <role>...  -> creates the app + secret once, grants roles
  local name=$1; shift
  local id; id=$(app_id "$name")
  if [[ -z $id ]]; then
    id=$(az ad app create --display-name "$name" --query appId -o tsv)
    az ad sp create --id "$id" -o none
    secret=$(az ad app credential reset --id "$id" --display-name beast --years 1 --query password -o tsv)
    umask 077; mkdir -p ~/.beast-assist
    printf 'CLIENT_ID=%s\nCLIENT_SECRET=%s\nTENANT_ID=%s\n' "$id" "$secret" "$TENANT" > ~/.beast-assist/"$name".env
    echo "secret for $name saved to ~/.beast-assist/$name.env (mode 600)"
  fi
  local sp; sp=$(az ad sp show --id "$id" --query id -o tsv)
  for r in "$@"; do
    az rest -m POST -u "https://graph.microsoft.com/v1.0/servicePrincipals/$sp/appRoleAssignments" \
      --body "{\"principalId\":\"$sp\",\"resourceId\":\"$API_SP\",\"appRoleId\":\"$(role_id "$r")\"}" -o none 2>/dev/null \
      || true  # already assigned
  done
}
client beast-agent Tools.Read Tools.Write
client beast-evals Tools.Read
client beast-publisher Skills.Publish

# --- API Management (Consumption) ----------------------------------------------------------------
if ! az apim show -g "$RG" -n "$APIM" -o none 2>/dev/null; then
  az apim create -g "$RG" -n "$APIM" -l "$LOCATION" --sku-name Consumption \
     --publisher-email "$PUBLISHER_EMAIL" --publisher-name "Scarlet Beast" -o none
fi
az apim nv create -g "$RG" --service-name "$APIM" --named-value-id tenant-id --display-name tenant-id --value "$TENANT" -o none 2>/dev/null || true
az apim nv create -g "$RG" --service-name "$APIM" --named-value-id audience --display-name audience --value "$AUDIENCE" -o none 2>/dev/null || true

for srv in agile college; do
  az apim api create -g "$RG" --service-name "$APIM" --api-id "$srv-mcp" --path "$srv" \
     --display-name "$srv-mcp" --service-url "$BACKEND_URL/$srv" --protocols https --subscription-required false -o none
  az apim api operation create -g "$RG" --service-name "$APIM" --api-id "$srv-mcp" --operation-id mcp-post \
     --url-template /mcp --method POST --display-name "MCP (streamable HTTP)" -o none 2>/dev/null || true
  az apim api operation create -g "$RG" --service-name "$APIM" --api-id "$srv-mcp" --operation-id mcp-get \
     --url-template /mcp --method GET --display-name "MCP stream" -o none 2>/dev/null || true
  az rest -m PUT \
    -u "https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.ApiManagement/service/$APIM/apis/$srv-mcp/policies/policy?api-version=2022-08-01" \
    --body "$(python3 -c 'import json,sys;print(json.dumps({"properties":{"format":"rawxml","value":open(sys.argv[1]).read()}}))' "$HERE/apim/mcp-api-policy.xml")" -o none
done

GW=$(az apim show -g "$RG" -n "$APIM" --query gatewayUrl -o tsv)
cat <<DONE

Done. Point the agent and evals at Azure:
  ENTRA_TENANT_ID=$TENANT
  TOKEN_URL=https://login.microsoftonline.com/$TENANT/oauth2/v2.0/token
  MCP_SERVERS={"agile-mcp": "$GW/agile/mcp", "college-mcp": "$GW/college/mcp"}
  client ids and secrets: ~/.beast-assist/beast-{agent,evals,publisher}.env
DONE
