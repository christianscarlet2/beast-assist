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

up:              ## build and start the local stack, wait until ready
	docker compose up -d --build
	$(PY) scripts/wait_ready.py $(READY)

seed:            ## publish the skills and index Scarlet College for RAG
	$(PY) scripts/upload_skills.py
	$(PY) rag/index_college.py

evals:           ## tool benchmark scenarios against the running stack
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

.PHONY: help install test up seed evals rag-eval ask agent new-server manifests down
