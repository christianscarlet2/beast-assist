# Beast Assist: the common tasks. `make help` lists them.
PY ?= .venv/bin/python
READY = http://localhost:8410/readyz http://localhost:8421/readyz http://localhost:8422/readyz

help:            ## this list
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/'

install:         ## venv + all Python dependencies
	python3 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -e ".[dev,agent]"

test:            ## unit tests + skill gates + policy tests (no stack needed)
	$(PY) -m pytest -q
	$(PY) scripts/validate_skills.py
	$(PY) scripts/audit_skill_config.py
	docker run --rm -v "$$PWD/policy:/p" openpolicyagent/opa:1.4.2 test /p

APIM_URL ?= https://beast-assist-apim.azure-api.net

up:              ## build and start the local stack, wait until ready
	docker compose up -d --build
	$(PY) scripts/wait_ready.py $(READY)

seed:            ## publish the skills and index Scarlet College for RAG
	$(PY) scripts/upload_skills.py
	$(PY) rag/index_college.py

evals:           ## tool benchmark scenarios against the running stack
	$(PY) evals/run_evals.py

azure-up:        ## start the Entra-trusting server pair behind mcp.scarletbeast.com (needs ENTRA_TENANT_ID, AZURE_API_AUDIENCE in .env)
	docker compose -f docker-compose.yml -f docker-compose.azure.yml up -d --build agile-mcp-azure college-mcp-azure

evals-azure:     ## the same scenarios through Azure APIM with a real Entra token (secrets from ~/.beast-assist/beast-evals.env)
	@set -a; . $(HOME)/.beast-assist/beast-evals.env; set +a; \
	EVALS_CLIENT_ID=$$CLIENT_ID EVALS_CLIENT_SECRET=$$CLIENT_SECRET \
	AUTH_AUDIENCE=$$(sed -n 's/^AZURE_API_AUDIENCE=//p' .env) \
	TOKEN_URL=https://login.microsoftonline.com/$$TENANT_ID/oauth2/v2.0/token \
	MCP_SERVERS='{"agile-mcp": "$(APIM_URL)/agile/mcp", "college-mcp": "$(APIM_URL)/college/mcp"}' \
	$(PY) evals/run_evals.py

rag-eval:        ## retrieval quality: hit@1, hit@5, MRR
	$(PY) rag/eval_retrieval.py

ask:             ## RAG from the command line: make ask Q="how do I validate a JWT?"
	$(PY) rag/ask.py "$(Q)"

agent:           ## run the coordinator: make agent R="standup for SB" (needs BEDROCK_MODEL_ID)
	$(PY) -m agent.coordinator "$(R)"

new-server:      ## scaffold a server: make new-server NAME=jira-mcp
	$(PY) scripts/new_server.py $(NAME)

manifests:       ## render the k8s overlays
	kubectl kustomize deploy/k8s/overlays/dev >/dev/null && kubectl kustomize deploy/k8s/overlays/prod >/dev/null && echo ok

down:            ## stop the stack (data volume kept)
	docker compose down

.PHONY: help install test up seed evals azure-up evals-azure rag-eval ask agent new-server manifests down
