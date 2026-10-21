#!/usr/bin/env bash
# Run Beast Assist itself in Azure: Container Apps for the MCP servers, OPA, the registry and the demo,
# Azure Database for PostgreSQL (pgvector) for the registry and RAG, and a Container Apps job that
# re-indexes Scarlet College daily. Run gateway/azure/setup.sh first (Entra + APIM).
#
#   TAG=<git sha> ./gateway/azure/deploy_apps.sh      deploy or update every app to that image
#
# Needs: az signed in; the Container Apps environment and the Postgres server below already created
# (see the README); secrets in ~/.beast-assist/{beast-evals,postgres}.env and AGILE_API_TOKEN,
# AWS_BEARER_TOKEN_BEDROCK in the environment.
set -euo pipefail

RG=${RG:-beast-assist}
ENV=${ENV:-beast-assist-env}
REGION=${REGION:-centralus}
APIM=${APIM:-beast-assist-apim}
IMAGE=${IMAGE:-ghcr.io/christianscarlet2/beast-assist:${TAG:?set TAG to an image tag}}
OPA_IMAGE=openpolicyagent/opa:1.4.2
MODEL=${BEDROCK_MODEL_ID:-us.amazon.nova-pro-v1:0}
PUBLIC_HOST=${PUBLIC_HOST:-cognizant.scarletbeast.com}
: "${AGILE_API_TOKEN:?}" "${AWS_BEARER_TOKEN_BEDROCK:?}"

set -a; . ~/.beast-assist/beast-evals.env; . ~/.beast-assist/postgres.env; set +a
TENANT=$(az account show --query tenantId -o tsv)
AUDIENCE=$(az ad app list --display-name beast-assist-api --query "[0].appId" -o tsv)
DOMAIN=$(az containerapp env show -g "$RG" -n "$ENV" --query properties.defaultDomain -o tsv)
GW=$(az apim show -g "$RG" -n "$APIM" --query gatewayUrl -o tsv)
DSN="host=$PGHOST user=$PGUSER password=$PGPASSWORD dbname=$PGDATABASE sslmode=require"
url() { echo "https://$1.$DOMAIN"; }

AUTH="ENTRA_TENANT_ID=$TENANT AUTH_ISSUER=https://login.microsoftonline.com/$TENANT/v2.0
      AUTH_JWKS_URL=https://login.microsoftonline.com/$TENANT/discovery/v2.0/keys AUTH_AUDIENCE=$AUDIENCE
      BEAST_ENV=staging AZURE_REGION=$REGION OPA_URL=http://beast-opa"

app() {  # app <name> <cpu> <mem> <ingress external|internal> <port> <image> [--secrets ...] -- <env...> [-- <args...>]
  local name=$1 cpu=$2 mem=$3 ingress=$4 port=$5 image=$6; shift 6
  local secrets=() envs=() args=()
  while [[ $# -gt 0 && $1 != -- ]]; do secrets+=("$1"); shift; done; [[ $# -gt 0 ]] && shift
  while [[ $# -gt 0 && $1 != -- ]]; do envs+=("$1"); shift; done; [[ $# -gt 0 ]] && shift
  args=("$@")
  if az containerapp show -g "$RG" -n "$name" -o none 2>/dev/null; then
    [[ ${#secrets[@]} -gt 0 ]] && az containerapp secret set -g "$RG" -n "$name" --secrets "${secrets[@]}" -o none
    az containerapp update -g "$RG" -n "$name" --image "$image" --cpu "$cpu" --memory "$mem" \
      --replace-env-vars "${envs[@]}" ${args:+--args "${args[@]}"} -o none
  else
    az containerapp create -g "$RG" -n "$name" --environment "$ENV" --image "$image" --cpu "$cpu" --memory "$mem" \
      --ingress "$ingress" --target-port "$port" --min-replicas 1 --max-replicas 1 \
      ${secrets:+--secrets "${secrets[@]}"} --env-vars "${envs[@]}" ${args:+--args "${args[@]}"} -o none
  fi
  echo "deployed $name -> $(url "$name")"
}

# registry: also serves OPA's bundle, with the Rego inside it (BUNDLE_POLICY)
app beast-registry 0.25 0.5Gi external 8000 "$IMAGE" "dsn=$DSN" -- \
  SERVICE=registry REGISTRY_DSN=secretref:dsn BUNDLE_POLICY=policy/tools.rego $AUTH

# OPA: no files mounted; it pulls policy + skills from the registry every 5-15 s. Sent straight to the ARM
# API as JSON: `az containerapp create --args` reads OPA's own --flags as its own, and its --yaml path
# rejected this definition with an opaque "could not be converted to System.Boolean".
ENV_ID=$(az containerapp env show -g "$RG" -n "$ENV" --query id -o tsv)
SUB=$(az account show --query id -o tsv)
OPA_BODY=$(REG="$(url beast-registry)" ENV_ID="$ENV_ID" REGION="$REGION" OPA_IMAGE="$OPA_IMAGE" python3 - <<'PYJ'
import json, os
reg = os.environ["REG"]
print(json.dumps({"location": os.environ["REGION"], "properties": {
    "environmentId": os.environ["ENV_ID"],
    "configuration": {"ingress": {"external": False, "targetPort": 8181, "transport": "http"}},
    "template": {"scale": {"minReplicas": 1, "maxReplicas": 1}, "containers": [{
        "name": "opa", "image": os.environ["OPA_IMAGE"], "resources": {"cpu": 0.25, "memory": "0.5Gi"},
        "args": ["run", "--server", "--addr=0.0.0.0:8181", "--log-level=error",
                 f"--set=services.registry.url={reg}", "--set=bundles.beast.service=registry",
                 "--set=bundles.beast.resource=/bundles/beast.tar.gz",
                 "--set=bundles.beast.polling.min_delay_seconds=5",
                 "--set=bundles.beast.polling.max_delay_seconds=15"]}]}}}))
PYJ
)
az rest -m PUT -o none \
  -u "https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.App/containerApps/beast-opa?api-version=2024-03-01" \
  --body "$OPA_BODY"
echo "deployed beast-opa (internal) -> http://beast-opa"

app beast-agile-mcp 0.25 0.5Gi external 8000 "$IMAGE" "agile-token=$AGILE_API_TOKEN" -- \
  SERVICE=agile-mcp AGILE_API_TOKEN=secretref:agile-token AGILE_PROJECTS=BA "AGILE_ACTOR=Beast Assist (Azure)" \
  ALLOWED_HOSTS=beast-agile-mcp.$DOMAIN $AUTH

app beast-college-mcp 0.5 1Gi external 8000 "$IMAGE" "dsn=$DSN" -- \
  SERVICE=college-mcp RAG_DSN=secretref:dsn EMBEDDINGS=local ALLOWED_HOSTS=beast-college-mcp.$DOMAIN $AUTH

app beast-demo 0.5 1Gi external 8000 "$IMAGE" \
  "demo-secret=$CLIENT_SECRET" "bedrock-key=$AWS_BEARER_TOKEN_BEDROCK" "dsn=$DSN" -- \
  SERVICE=demo DEMO_CLIENT_ID=$CLIENT_ID DEMO_CLIENT_SECRET=secretref:demo-secret \
  AWS_BEARER_TOKEN_BEDROCK=secretref:bedrock-key AWS_REGION=us-east-1 BEDROCK_MODEL_ID=$MODEL RAG_DSN=secretref:dsn \
  ENTRA_TENANT_ID=$TENANT AUTH_AUDIENCE=$AUDIENCE AZURE_REGION=$REGION APIM_URL=$GW \
  REGISTRY_URL=$(url beast-registry) OPA_URL=http://beast-opa \
  AGILE_MCP_URL=$(url beast-agile-mcp) COLLEGE_MCP_URL=$(url beast-college-mcp) PUBLIC_HOST=$PUBLIC_HOST \
  "MCP_SERVERS={\"agile-mcp\": \"$GW/agile/mcp\", \"college-mcp\": \"$GW/college/mcp\"}" \
  ${VIDEO_URL:+VIDEO_URL=$VIDEO_URL}

# RAG ingestion as a scheduled job (daily 06:00 UTC), also started once now
if ! az containerapp job show -g "$RG" -n beast-index -o none 2>/dev/null; then
  az containerapp job create -g "$RG" -n beast-index --environment "$ENV" --image "$IMAGE" \
    --trigger-type Schedule --cron-expression "0 6 * * *" --replica-timeout 1800 --cpu 1 --memory 2Gi \
    --secrets "dsn=$DSN" --env-vars RAG_DSN=secretref:dsn EMBEDDINGS=local \
    --command python --args rag/index_college.py -o none
else
  az containerapp job update -g "$RG" -n beast-index --image "$IMAGE" -o none
fi
az containerapp job start -g "$RG" -n beast-index -o none && echo "started beast-index (RAG ingestion)"

# point APIM at the Container Apps instead of any self-hosted backend, and refresh its policy
SUB=$(az account show --query id -o tsv)
HERE=$(cd "$(dirname "$0")/.." && pwd)
for srv in agile college; do
  az apim api update -g "$RG" --service-name "$APIM" --api-id "$srv-mcp" --service-url "$(url beast-$srv-mcp)" -o none
  az rest -m PUT \
    -u "https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.ApiManagement/service/$APIM/apis/$srv-mcp/policies/policy?api-version=2022-08-01" \
    --body "$(python3 -c 'import json,sys;print(json.dumps({"properties":{"format":"rawxml","value":open(sys.argv[1]).read()}}))' "$HERE/apim/mcp-api-policy.xml")" -o none >/dev/null
  echo "APIM $srv-mcp -> $(url beast-$srv-mcp)"
done
