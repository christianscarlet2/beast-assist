# Beast Assist

**Governed MCP tools and skills for Scarlet Beast's AI agents.**

Beast Assist is a working, small-scale enterprise agent platform. AI agents get capabilities from two
building blocks:

- **MCP tool servers** that each expose one Scarlet Beast system (the Warden agile board, Scarlet
  College) as small, typed, LLM-readable tools, served over MCP streamable HTTP with FastAPI.
- **Skills**: `SKILL.md` manifests that package those tools with business instructions, an
  authorization scope (`allowed_tools`), pre-flight inputs, a lifecycle stage and a workflow with an
  error table.

Every tool call is authenticated with an Entra ID token, authorized by Open Policy Agent against the
skill's `allowed_tools`, traced with OpenTelemetry, and logged. Skills are validated, audited and
published to a PostgreSQL-backed Skills Registry, which OPA reads as a policy bundle. A LangGraph
coordinator agent on Amazon Bedrock resolves a request to a skill and runs it with only that skill's
tools. A RAG pipeline indexes every Scarlet College lesson into pgvector for semantic search.

It runs end to end on one machine with Docker (a dev token issuer stands in for Entra ID), deploys to
Kubernetes with Kustomize, and puts Azure API Management in front with a single script.

---

## Contents

1. [What is implemented](#what-is-implemented)
2. [Architecture](#architecture)
3. [Repository layout](#repository-layout)
4. [Install and run locally](#install-and-run-locally)
5. [The MCP servers](#the-mcp-servers)
6. [Building a new MCP server](#building-a-new-mcp-server)
7. [Skills](#skills)
8. [Skill tooling: validate, audit, upload](#skill-tooling-validate-audit-upload)
9. [The Skills Registry](#the-skills-registry)
10. [Authorization with OPA](#authorization-with-opa)
11. [Authentication: Entra ID and the dev issuer](#authentication-entra-id-and-the-dev-issuer)
12. [RAG over Scarlet College](#rag-over-scarlet-college)
13. [The agent: LangGraph coordinator on Bedrock](#the-agent-langgraph-coordinator-on-bedrock)
14. [Evaluation suites](#evaluation-suites)
15. [Observability](#observability)
16. [Tests](#tests)
17. [Kubernetes deployment](#kubernetes-deployment)
18. [Azure: Entra ID and API Management](#azure-entra-id-and-api-management)
19. [CI/CD](#cicd)
20. [Configuration reference](#configuration-reference)
21. [Troubleshooting](#troubleshooting)
22. [Status and known limits](#status-and-known-limits)

---

## What is implemented

| Component | Where | What it does |
| --- | --- | --- |
| MCP template library | `libs/beast_mcp/` | `create_app()` builds a FastAPI + MCP server: tool auto-discovery from `src/tools/`, Entra JWT validation, OPA check on every call, `tools/list` filtered to the skill, OpenTelemetry spans, JSON call logs, `/healthz` and `/readyz` |
| Server template | `mcp-template/` | The skeleton every new server is copied from (`scripts/new_server.py`) |
| agile-mcp | `servers/agile-mcp/` | Single-platform adapter for the Warden agile board API: `bootstrap_guide`, `list_projects`, `list_tasks`, `get_task`, `create_task`, `add_comment` |
| college-mcp | `servers/college-mcp/` | Single-platform adapter for Scarlet College: `bootstrap_guide`, `list_courses`, `list_lessons`, `get_lesson`, `search_lessons` (RAG) |
| Skills | `skills/*/SKILL.md` | `board-standup` (production, read-only), `college-tutor` (production, RAG), `study-plan-from-job` (beta, writes to the board) |
| Skill tooling | `scripts/` | `validate_skills.py` (shape), `audit_skill_config.py` (scope vs the real catalog), `upload_skills.py` (publish through both gates), `new_server.py` |
| Skills Registry | `registry/` | FastAPI + PostgreSQL: list, get, resolve-by-words, publish (immutable versions, `Skills.Publish` role), and the OPA bundle |
| Policy | `policy/tools.rego` | Deny by default; allow only a registered skill, in an allowed lifecycle stage, calling a tool in its `allowed_tools`, with the right token role. Unit-tested with `opa test` |
| Dev identity provider | `auth/mock_entra.py` | Issues RS256 tokens with Entra v2's claim shape (iss, aud, roles, oid, tid) and serves JWKS + OpenID config |
| RAG | `libs/beast_rag/`, `rag/` | Ingest, chunk, embed (local bge-small or Bedrock Titan), store in pgvector, retrieve, generate with Bedrock; retrieval-quality eval |
| Agent | `agent/` | LangGraph coordinator: resolve skill, check pre-flight inputs, run a ReAct specialist scoped to the skill's tools over MCP; Bedrock model, plus a scripted model for tests |
| Evals | `evals/` | Benchmark scenarios (YAML) run through the full token, MCP, OPA and backend path; results saved as JSON |
| Local stack | `docker-compose.yml`, `Dockerfile` | PostgreSQL + pgvector, dev issuer, registry, OPA, both servers, Jaeger |
| Kubernetes | `deploy/k8s/` | Kustomize base + dev/prod overlays: Deployments with an OPA sidecar, probes, HPA, PDB, NetworkPolicies, cert-manager Certificate, Ingress |
| Azure | `gateway/` | APIM policy (`validate-jwt`, required skill header) and `setup.sh` that creates the Entra app registrations and APIM Consumption |
| CI | `.github/workflows/ci.yml` | Tests, skill gates, policy tests, manifest render + schema check, integration publish, image build |

## Architecture

```mermaid
flowchart LR
  user([User]) --> agent
  subgraph Agent["Agent (LangGraph, Bedrock)"]
    agent[coordinator] -->|resolve skill| reg
    agent --> spec[specialist ReAct agent<br/>tools = skill.allowed_tools]
  end
  entra[(Entra ID<br/>or mock-entra)] -.client credentials.-> agent
  spec -->|Bearer JWT + X-Skill-Id| apim[Azure APIM<br/>validate-jwt, rate limit]
  apim --> ing[Ingress + TLS]
  ing --> agile[agile-mcp]
  ing --> college[college-mcp]
  agile --- opa1[OPA sidecar]
  college --- opa2[OPA sidecar]
  reg[Skills Registry<br/>FastAPI + PostgreSQL] -->|bundle| opa1
  reg --> opa2
  agile --> board[(Warden agile board)]
  college --> site[(Scarlet College)]
  college --> pg[(pgvector)]
  ci[[CI: validate, audit, upload]] --> reg
```

The full walk-through of one tool call, and why each boundary sits where it does, is in
[docs/architecture.md](docs/architecture.md).

## Repository layout

```
beast-assist/
├── libs/
│   ├── beast_mcp/              shared server runtime (the template's engine)
│   │   ├── app.py              create_app(): FastAPI + MCP, the auth/policy/trace guard, health
│   │   ├── discovery.py        imports src/backend.py and every src/tools/*.py by path
│   │   ├── registry.py         @tool decorator, backend() accessor
│   │   ├── auth.py             Entra JWT verification with a cached, rotation-aware JWKS
│   │   ├── policy.py           OPA client (decisions + allowed_tools for tools/list)
│   │   ├── telemetry.py        OpenTelemetry setup, JSON call log
│   │   ├── settings.py         all config from the environment
│   │   └── errors.py           ToolFailure(message, hint, code)
│   └── beast_rag/              chunking, embeddings (local or Bedrock), pgvector schema
├── mcp-template/               copy this to start a server (scripts/new_server.py does it)
├── servers/
│   ├── agile-mcp/src/{backend.py, main.py, tools/*.py}
│   └── college-mcp/src/{backend.py, main.py, tools/*.py}
├── skills/<name>/SKILL.md      board-standup, college-tutor, study-plan-from-job
├── scripts/                    validate_skills, audit_skill_config, upload_skills, new_server, wait_ready
├── registry/                   Skills Registry service + schema.sql
├── policy/                     tools.rego + tools_test.rego
├── auth/mock_entra.py          dev identity provider with Entra's token shape
├── rag/                        index_college, ask, eval_retrieval, questions.yaml, README
├── agent/                      coordinator.py (LangGraph), mcp_tools.py (MCP -> LangChain), model.py (Bedrock / scripted)
├── evals/                      run_evals.py + scenarios/*.yaml
├── tests/                      pytest: platform guarantees over real MCP HTTP, skills, RAG, deploy
├── deploy/
│   ├── opa/config.yaml         local OPA bundle config
│   └── k8s/                    base/ + overlays/{dev,prod}
├── gateway/
│   ├── apim/mcp-api-policy.xml
│   └── azure/setup.sh          plan | apply | destroy
├── docs/architecture.md
├── Dockerfile, docker-compose.yml, Makefile, pyproject.toml, .env.example
└── .github/workflows/ci.yml
```

## Install and run locally

### Requirements

- Linux or macOS with **Docker** (Compose v2) and **Python 3.10+**
- About 3 GB of disk for images and the embedding model
- For live tool calls: network access to `living.scarletbeast.com` (agile board) and
  `college.scarletbeast.com`, plus the board's API token. Without them the unit tests still run
  everything against fakes.
- Optional: AWS credentials with Bedrock access (agent and RAG answers), an Azure account (gateway)

### Steps

```bash
git clone <this repo> beast-assist && cd beast-assist

# 1. Python environment
make install                    # .venv with the platform, agent and test dependencies

# 2. Configuration
cp .env.example .env            # then set AGILE_API_TOKEN (the board's token)
chmod 600 .env

# 3. Tests that need nothing running
make test                       # pytest + validate_skills + audit_skill_config + opa test

# 4. Start the stack and wait for readiness
make up                         # postgres+pgvector, mock-entra, registry, opa, agile-mcp, college-mcp, jaeger

# 5. Publish the skills (through both gates) and build the RAG index
make seed

# 6. Run the benchmark scenarios against the live stack
make evals
make rag-eval
```

Local ports (all bound to 127.0.0.1):

| Service | Port | Check |
| --- | --- | --- |
| mock-entra (dev issuer) | 8400 | `curl localhost:8400/beast-dev-tenant/discovery/v2.0/keys` |
| Skills Registry | 8410 | `curl localhost:8410/skills` |
| agile-mcp | 8421 | `curl localhost:8421/readyz` |
| college-mcp | 8422 | `curl localhost:8422/readyz` |
| OPA | 18181 | `curl localhost:18181/v1/data/beast/skills` |
| PostgreSQL + pgvector | 55432 | `psql postgresql://beast:beast@localhost:55432/beast` |
| Jaeger UI (traces) | 16686 | open http://localhost:16686 |

### Calling a tool by hand

```bash
TOKEN=$(curl -s localhost:8400/beast-dev-tenant/oauth2/v2.0/token \
  -d grant_type=client_credentials -d client_id=beast-evals -d client_secret=dev-evals-secret \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

.venv/bin/python - <<PY
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

async def main():
    h = {"Authorization": "Bearer $TOKEN", "X-Skill-Id": "board-standup"}
    async with streamable_http_client("http://localhost:8421/mcp", http_client=create_mcp_http_client(headers=h)) as st:
        async with ClientSession(st[0], st[1]) as s:
            await s.initialize()
            print([t.name for t in (await s.list_tools()).tools])   # only the skill's tools
            r = await s.call_tool("list_tasks", {"project": "SB", "status": "todo"})
            print(r.content[0].text[:500])
asyncio.run(main())
PY
```

## The MCP servers

Each server is a **single-platform adapter**: one backend, one credential, one deployment.

### agile-mcp: the Warden agile board

Backend: the board's token API (`/api/agile`), the same service the Warden UI uses, so every change
shows on the board within seconds and in the task history under the actor `Beast Assist (MCP)`.

| Tool | Kind | Purpose |
| --- | --- | --- |
| `bootstrap_guide` | read | Call first: vocabulary (statuses, types, priorities, key format) and where to start |
| `list_projects` | read | Projects with task counts |
| `list_tasks` | read | Search by project, status, text, label; slim rows only |
| `get_task` | read | One task in full; validates the key before calling the backend |
| `create_task` | **write** | Backlog task with validated type and priority |
| `add_comment` | **write** | Comment on a task |

### college-mcp: Scarlet College

Backend: the college's public JSON API (`/api/catalog`, `/api/lesson/{id}`) and the pgvector index
built by `rag/index_college.py`.

| Tool | Kind | Purpose |
| --- | --- | --- |
| `bootstrap_guide` | read | What the college is, id format, how search works |
| `list_courses` | read | Courses, lesson counts and syllabi |
| `list_lessons` | read | Lessons in one course, easiest first |
| `get_lesson` | read | Objectives, key terms, summary, URL; optional full text; validates the id |
| `search_lessons` | read | Semantic search over every lesson (RAG retrieval), scores 0 to 1 |

### Tool design rules

- `list_*` / `get_*` / `create_*` operations, each doing one thing, with a docstring written for the
  model (it is the tool description the agent reads).
- Outputs are small, structured and stable: slim rows instead of raw payloads, never secrets.
- Inputs are validated before the backend is touched (`invalid_input`).
- Failures are `ToolFailure(message, hint, code)` and reach the model as
  `code: message Next: hint`, with codes `not_found`, `invalid_input`, `not_ready`,
  `backend_unavailable` and `backend_error`, which skills' error tables match on.
- Writes are marked `@tool(write=True)`: they need the Tools.Write role **and** an explicit grant in the
  skill, and the audit fails a skill that grants a write tool its workflow never uses.
- Every tool is annotated with MCP `readOnlyHint`, so clients can show read and write differently.

## Building a new MCP server

```bash
make new-server NAME=jira-mcp        # copies mcp-template/ to servers/jira-mcp
```

Then:

1. **`src/backend.py`**: write the client for the one backend, async, with `ready()` (used by
   `/readyz`) and `aclose()`. Map backend errors to `ToolFailure` with a code and a hint. Read
   credentials from the environment only.
2. **`src/tools/<tool>.py`**: one file per tool:

   ```python
   from beast_mcp import ToolFailure, backend, tool

   @tool()                                   # @tool(write=True) if it changes the backend
   async def get_issue(key: str) -> dict:
       """One issue in full. key looks like ABC-12."""
       return await backend().get(f"/issue/{key}")
   ```

   Files are discovered automatically; a name starting with `_` is skipped (shared helpers).
3. **`tests/`**: unit tests with a fake backend using the `serve` fixture in `tests/conftest.py`, and
   integration tests marked `@pytest.mark.integration` for the real backend.
4. **Compose and Kubernetes**: copy the `agile-mcp` service in `docker-compose.yml` and
   `deploy/k8s/base/agile-mcp.yaml`, changing the name. The image is shared; `SERVICE=<name>` selects
   the server.
5. **Evals**: add `evals/scenarios/<server>.yaml`. A skill cannot become `production` without one.

## Skills

A skill is a folder under `skills/` with one `SKILL.md`: YAML frontmatter plus a Markdown body.

```yaml
---
name: board-standup                      # kebab-case, equal to the folder name
description: Summarise what is in progress, blocked and next on an agile board.   # 20-200 chars
version: 1.0.0                           # semver; a published version is immutable
lifecycle: production                    # draft | beta | production | deprecated
owner: platform@scarletbeast.com
tags: [agile, reporting, read-only]      # `writes` is required on production skills with write tools
aliases: [standup, daily standup summary]    # the user's words; unique across all skills
allowed_tools:                           # THE AUTHORIZATION SCOPE, enforced by OPA
  - agile-mcp:bootstrap_guide
  - agile-mcp:list_tasks
  - agile-mcp:get_task
preflight:                               # inputs checked before anything runs
  - {name: project, description: Board project key, required: false, default: SB}
---
# Board standup
## Workflow        numbered steps naming each tool as server:tool
## Errors          table: error code -> meaning -> what to do
## Gotchas         things that trip agents up
```

| Skill | Lifecycle | Tools | Writes |
| --- | --- | --- | --- |
| `board-standup` | production | agile: guide, list_tasks, get_task | no |
| `college-tutor` | production | college: guide, list_courses, search_lessons, get_lesson | no |
| `study-plan-from-job` | beta | college: search_lessons, get_lesson; agile: list_tasks, create_task | yes |

`study-plan-from-job` turns a job description into one study task per skill gap on the board, each
linked to the best Scarlet College lesson. It is idempotent (it checks for existing `study` tasks
first) and, as a beta skill, OPA blocks it in prod until it is promoted.

## Skill tooling: validate, audit, upload

```bash
python scripts/validate_skills.py      # shape: fields, types, name == folder, semver, lifecycle,
                                       # allowed_tools format, preflight, unique aliases,
                                       # ## Workflow (numbered) and ## Errors sections
python scripts/audit_skill_config.py   # scope against the REAL tool catalog (discovered from servers/)
python scripts/upload_skills.py        # runs both gates, then PUTs each skill to the registry
```

The audit's rules:

| Level | Rule |
| --- | --- |
| FAIL | an allowed tool that no server provides |
| FAIL | a write tool granted but never named in the Workflow |
| FAIL | a production skill with no scenario in `evals/scenarios` |
| FAIL | a production skill with write tools that is not tagged `writes` |
| WARN | a read tool granted but never named in the Workflow (trim it) |
| WARN | a skill spanning more than three servers |

Promotion is therefore: change `lifecycle`, bump `version`, make the audit pass, add an eval
scenario, upload. OPA picks the new lifecycle up from the registry within seconds.

## The Skills Registry

`registry/app.py`, FastAPI on PostgreSQL (`registry/schema.sql`, created on startup).

| Endpoint | Auth | Purpose |
| --- | --- | --- |
| `GET /skills?tag=&lifecycle=` | none (internal) | List skills |
| `GET /skills/{name}` | none (internal) | One skill with its workflow body |
| `GET /resolve?q=` | none (internal) | Pick a skill from the user's words: aliases, then name, then description |
| `PUT /skills/{name}` | Entra token with `Skills.Publish` | Publish; a version already published with different content is refused (409) |
| `GET /bundles/beast.tar.gz` | none (internal) | OPA bundle with `data.beast.skills`, ETag = content hash |
| `GET /healthz`, `/readyz` | none | Probes |

Every publish is also appended to `skill_versions` with the publisher's app id, so the history of
who changed which scope is kept.

## Authorization with OPA

`policy/tools.rego` (package `beast.tools`). Input from the server:

```json
{"env": "prod", "server": "agile-mcp", "tool": "create_task", "qualified_tool": "agile-mcp:create_task",
 "write": true, "skill": "study-plan-from-job",
 "subject": {"oid": "…", "permissions": ["Tools.Read", "Tools.Write"]}}
```

A call is allowed only when all of these hold:

1. the request names a skill (`X-Skill-Id`) that is in the registry
2. the skill's lifecycle may run in this environment (dev: draft, beta, production; staging: beta,
   production; prod: production only)
3. `server:tool` is in the skill's `allowed_tools`
4. the token carries `Tools.Read`, plus `Tools.Write` for a write tool

`decision` returns `{"allow": …, "reasons": [...]}`; the reasons go back to the model, so a refusal
is explained (for example, `agile-mcp:create_task is not in the allowed_tools of skill "board-standup"`).
The servers fail closed: if OPA cannot be reached, every call is refused.

```bash
docker run --rm -v "$PWD/policy:/p" openpolicyagent/opa:1.4.2 test /p -v     # 6 policy tests
```

## Authentication: Entra ID and the dev issuer

The servers accept **Entra ID v2 access tokens**: RS256, verified against the tenant's JWKS (cached
10 minutes, refetched once on an unknown `kid` to follow key rotation), with issuer, audience and
expiry required. App roles (`roles`, client-credentials tokens) and delegated scopes (`scp`) are both
read into one permission set.

| App registration | Roles | Used by |
| --- | --- | --- |
| `beast-assist-api` | defines Tools.Read, Tools.Write, Skills.Publish; audience `api://beast-assist` | the servers and registry |
| `beast-agent` | Tools.Read, Tools.Write | the coordinator agent |
| `beast-evals` | Tools.Read | the evaluation runner (so evals can never write) |
| `beast-publisher` | Skills.Publish | CI's `upload_skills.py` |

Locally, `auth/mock_entra.py` plays Entra: the same discovery, JWKS and token endpoints and the same
claim shape, with the four clients above (dev secrets in `auth/mock_entra.py`). To switch to the real
tenant, set `ENTRA_TENANT_ID` (the issuer and JWKS URLs are derived from it) and remove
`AUTH_ISSUER` / `AUTH_JWKS_URL`. No code changes.

## RAG over Scarlet College

The full walkthrough is in [rag/README.md](rag/README.md). In short:

```bash
python rag/index_college.py            # ingest -> chunk -> embed -> store in pgvector (incremental)
python rag/ask.py "how do I override a FastAPI dependency in a test?"   # retrieve -> generate
python rag/eval_retrieval.py           # hit@1, hit@5, MRR over rag/questions.yaml
```

- **Ingest**: every ready lesson from `/api/catalog`, with its body, practice and key terms.
- **Chunk**: on `##`/`###` headings, at most about 1,400 characters, long sections cut at paragraph
  breaks; each chunk is embedded with its lesson title and heading as context.
- **Embed**: `BAAI/bge-small-en-v1.5` on CPU via fastembed (384 dims, baked into the image), or Amazon
  Titan Text Embeddings V2 with `EMBEDDINGS=bedrock` (512 dims: Titan offers only 256, 512 or 1024).
- **Store**: PostgreSQL with an HNSW index on cosine distance, one table per embedding model
  (`college_chunks` for bge-small, `college_chunks_titan` for Titan), so both indexes live side by side
  and `EMBEDDINGS` picks which one indexing, `ask.py`, the eval and `search_lessons` use. A per-lesson
  content hash makes re-indexing skip unchanged lessons.
- **Retrieve**: `college-mcp:search_lessons` (the agent's way in) or `rag/ask.py`.
- **Generate**: Bedrock Converse with an "answer only from the numbered passages, cite them" prompt.
  The `college-tutor` skill does the same inside the agent and refuses to answer from memory when the
  best score is under 0.55 (a threshold tuned on bge-small scores; re-tune it for Titan).

Measured on the 8 questions in `rag/questions.yaml` (2026-10-20, 33 lessons, 521 chunks):

| Embeddings | hit@1 | hit@5 | MRR | Index time |
| --- | --- | --- | --- | --- |
| bge-small-en-v1.5, local CPU, 384 dims | 1.00 | 1.00 | 1.00 | about 2 min |
| Titan Text Embeddings V2, Bedrock, 512 dims | 0.88 | 1.00 | 0.92 | 464 s (one call per chunk) |

Titan ranked the right lesson third for "Test the 404 and 422 paths of an API with pytest TestClient".
Eight questions is far too few to call either model better; it shows how to run the comparison.

## The agent: LangGraph coordinator on Bedrock

`agent/coordinator.py` is a LangGraph state graph using the coordinator (supervisor) pattern:

```
resolve_skill ──► preflight ──► run_specialist ──► END
                      │
                      └──► ask_user ──► END      (a required input is missing)
```

- **resolve_skill** asks the registry which skill fits (`/resolve`), or uses `skill=` if given.
- **preflight** fills defaults and stops with a question when a required input is missing.
- **run_specialist** gets the agent's own client-credentials token, connects to only the servers in
  the skill's `allowed_tools` (sending `X-Skill-Id`), keeps only the allowed tools (the servers filter
  too), and runs a ReAct agent whose system prompt is the skill's workflow. MCP tools become LangChain
  tools through `agent/mcp_tools.py`, a small adapter on the MCP SDK 2.x (`langchain-mcp-adapters`
  0.3.2 still requires `mcp<2.0`).

```bash
export AWS_REGION=us-east-1 BEDROCK_MODEL_ID=us.amazon.nova-pro-v1:0   # or a Claude model, see below
python -m agent.coordinator "standup for the SB board"
python -m agent.coordinator "make me a study plan for this job" job_description="$(cat jd.txt)"
```

`agent/model.py` also has `ScriptedModel`, which replays fixed tool calls so the graph, the scoping
and the MCP plumbing can be tested without a model.

### Connecting Bedrock

Credentials are the standard AWS chain, so either works:

- a **Bedrock API key** in `AWS_BEARER_TOKEN_BEDROCK` (boto3 1.39 or later picks it up), or
- normal IAM credentials (`aws configure`, an instance role, or IRSA on EKS).

Model ids are **inference profiles** (`us.` or `global.` prefix), which route each call across regions.
List what an account can see with `aws bedrock list-inference-profiles`; seeing a profile does not
mean the account may call it.

Anthropic models need a one-time **use case form** per AWS account: Bedrock console → Model catalog →
any Anthropic model → submit use case details. Until it is approved, every Claude call fails with
`ResourceNotFoundException: Model use case details have not been submitted`. Amazon's models (Nova,
Titan) need no form, which is why the verified run below used Nova Pro. After the form:
`BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-6`.

Verified 2026-10-20 on Bedrock (us-east-1, Nova Pro): the coordinator answered "standup for the SB
project" by calling `list_tasks` twice and `get_task` once under the `board-standup` skill, and
`rag/ask.py` answered from the retrieved passages with citations.

## Evaluation suites

`evals/scenarios/*.yaml` are benchmark scenarios. Each names a skill, a server, a tool, arguments and
expectations; `evals/run_evals.py` runs them with the read-only `beast-evals` identity through the
real path (token, MCP over HTTP, OPA, tool, backend) and writes `evals/results/<time>.json`.

Expectations supported: `keys`, `type: list`, `min_items`, `item_keys`, `all_items`,
`first_score_at_least` (RAG relevance), `contains`, `exactly` (for `list_tools: true`) and
`error_contains` (for scenarios that must be refused). The suites cover:

- functional checks on every read tool against the live backends
- clean error codes for missing and malformed inputs
- **scope**: a skill calling a tool outside `allowed_tools`, a write without Tools.Write, no skill
  header, `tools/list` filtering, a skill reaching a server it has no tools on
- RAG relevance: the top passage for a known question scores at least 0.55 and stays in its course

```bash
make evals              # all scenarios
python evals/run_evals.py -k scope     # a subset by name
```

## Observability

- **Traces**: one OpenTelemetry span per tool call, `tool <server>:<tool>`, with `beast.skill`,
  `beast.tool` and `beast.outcome` (ok, error, denied). With `OTEL_EXPORTER_OTLP_ENDPOINT` set, spans
  go out over OTLP/HTTP: Jaeger locally (http://localhost:16686), or an OpenTelemetry collector that
  forwards to Azure Monitor / Grafana in Kubernetes.
- **Tool-call log**: one JSON line per call on stdout (server, tool, skill, caller oid, outcome,
  milliseconds, trace id), ready for any log pipeline to aggregate by tool, skill or outcome.
- **OPA decision logs**: OPA logs every decision with its input on its console.
- **Health**: `/healthz` (process up, tool count) and `/readyz` (backend and OPA reachable; 503
  otherwise), used by the Kubernetes probes.

## Tests

```bash
make test                                   # or: .venv/bin/python -m pytest -q
.venv/bin/python -m pytest -q -m integration   # needs `make up` and `make seed`
```

| Suite | What it proves |
| --- | --- |
| `tests/test_platform.py` | Over **real MCP streamable HTTP** against a running server: valid tokens work; missing, wrong-audience, wrong-issuer and expired tokens are refused before the backend; out-of-scope tools are forbidden; writes need Tools.Write; beta skills are blocked in prod; a missing skill header is refused; `tools/list` is filtered; backend errors reach the agent with a hint; inputs are validated before the backend; health endpoints answer |
| `tests/test_auth.py` | JWKS caching and signing-key rotation: a new key (new or reused kid) is picked up without a restart; forged tokens stay refused |
| `servers/agile-mcp/tests/test_backend.py` | The board's real error shapes map to the codes skills use (its 422 "No task" is `not_found`); the token and actor headers are sent |
| `tests/test_agent_live.py` (integration) | The coordinator against the running stack with the scripted model: resolves the skill, fills defaults, calls only allowed tools through OPA, asks instead of running when a required input is missing, retrieves from the college |
| `tests/test_skills.py` | The repo's skills pass both gates; the validator and the audit catch broken skills |
| `tests/test_rag.py` | Chunking follows headings and respects size; vector literals |
| `tests/test_deploy.py` | The policy copy shipped to Kubernetes is identical to `policy/tools.rego` |
| `policy/tools_test.rego` | The Rego rules themselves (`opa test`) |
| `evals/` | The live stack, end to end (`make evals`) |

The platform tests run servers in-process on free ports with a test RSA key in place of Entra's JWKS
and a Python port of the Rego rules fed from the repo's own `SKILL.md` files, so the scopes under test
are the real ones.

## Kubernetes deployment

`deploy/k8s/base` (Kustomize), with `overlays/dev` (kind or minikube: one replica, dev issuer,
local image) and `overlays/prod` (your tenant id, APIM's outbound IPs):

- **Deployments** for agile-mcp, college-mcp and the registry; each MCP pod runs **OPA as a sidecar**
  on localhost, pulling the registry bundle.
- **Probes**: startup and liveness on `/healthz`, readiness on `/readyz`; OPA readiness waits for the
  bundle.
- **Security**: non-root UID 10001, read-only root filesystem, all capabilities dropped,
  `RuntimeDefault` seccomp; **NetworkPolicies** deny by default and open only ingress to MCP pods, MCP
  pods to the registry, and the registry and college-mcp to PostgreSQL.
- **Scaling**: HPA (2 to 6 replicas at 70% CPU) and a PodDisruptionBudget; stateless MCP over HTTP
  means no session affinity.
- **TLS**: a cert-manager `Certificate` for `mcp.scarletbeast.com` and an Ingress that routes
  `/agile/*` and `/college/*` and only admits APIM's outbound IPs.
- **Config**: `beast-config` ConfigMap; `beast-secrets` is created out of band (see
  `base/secret.example.yaml`) or synced from Azure Key Vault.

```bash
kubectl kustomize deploy/k8s/overlays/dev            # render
kind create cluster --name beast                     # a local cluster
docker build -t beast-assist:dev . && kind load docker-image beast-assist:dev --name beast
kubectl apply -k deploy/k8s/overlays/dev
kubectl -n beast-assist get pods
```

## Azure: Entra ID and API Management

How to open the free account and connect it is in the separate Azure sign-up guide. With the Azure CLI
signed in (`az login --use-device-code`):

```bash
./gateway/azure/setup.sh plan        # what would be created; changes nothing
BACKEND_URL=https://mcp.scarletbeast.com ./gateway/azure/setup.sh apply
./gateway/azure/setup.sh destroy     # remove it all
```

Installing the CLI on Ubuntu: Microsoft's one-line installer (`aka.ms/InstallAzureCLIDeb`) aborts if any
other apt source is broken. Adding `packages.microsoft.com/repos/azure-cli/` as a deb822 source with
its key in `/etc/apt/keyrings/microsoft.gpg` and running `apt-get install azure-cli` works regardless.

`apply` creates the resource group, the four app registrations (with app roles and role
assignments, and secrets saved to `~/.beast-assist/<app>.env` with mode 600), an API Management
instance on the **Consumption** tier, one API per server, and applies
`gateway/apim/mcp-api-policy.xml`:

- `validate-jwt` against your tenant's OpenID configuration, audience = the `beast-assist-api` app id,
  a Tools role required
- the `X-Skill-Id` header required
- no per-app rate limit: the Consumption tier does not allow `rate-limit-by-key` (add it on Developer/Standard)
- caller oid and request id forwarded to the servers, which check the token again

It prints the values to switch the agent and evals to Azure (`ENTRA_TENANT_ID`, `AZURE_API_AUDIENCE`,
`TOKEN_URL`, `MCP_SERVERS`).

### The audience on a real tenant

The local stack uses the audience `api://beast-assist`. A real tenant differs in two ways, both met on
the first live run:

- New tenants refuse an identifier URI that does not contain the tenant id, the app id or a verified
  domain. `setup.sh` gives the API `api://<app id>`.
- Entra **v2** access tokens carry the API's **app id** (a GUID) in `aud`, not the identifier URI. So
  the servers, APIM and the clients all use the app id: `AUTH_AUDIENCE=<app id>`, scope
  `<app id>/.default`. A fresh app has an empty `api` object, so `setup.sh` sets
  `requestedAccessTokenVersion=2` through Microsoft Graph (`az ad app update --set` cannot reach it).

### Serving the servers to APIM

APIM needs a public HTTPS backend. `docker-compose.azure.yml` runs a second pair of servers that trust
the real tenant (`BEAST_ENV=staging`, so draft skills are refused) on ports 8431/8432, next to the
dev pair that keeps trusting mock-entra. Apache serves them as `https://mcp.scarletbeast.com/agile/`
and `/college/` (everything else is 403), with the wildcard certificate:

```bash
# ENTRA_TENANT_ID and AZURE_API_AUDIENCE in .env (setup.sh prints both)
make azure-up
make evals-azure     # the 13 scenarios through APIM with a real Entra token
```

Without the skill header APIM answers a plain HTTP 400 before MCP starts. The MCP SDK turns that into
a bare `MCPError` with no body, so `run_evals.py` replays the request as plain HTTP to read the
gateway's message, and that scenario passes either way.

## CI/CD

`.github/workflows/ci.yml`:

1. **test**: pytest, `validate_skills.py`, `audit_skill_config.py`, `opa test`
2. **manifests**: the policy copy matches; both overlays render and pass `kubeconform -strict`
3. **integration** (on push): compose up the registry, OPA and the dev issuer; publish the skills
   through the gates; assert OPA serves the published scopes
4. **image** (main): build and push `ghcr.io/<owner>/beast-assist`

## Configuration reference

| Variable | Used by | Default | Meaning |
| --- | --- | --- | --- |
| `BEAST_ENV` | servers | `dev` | `dev`, `staging` or `prod`: which skill lifecycles OPA allows |
| `ENTRA_TENANT_ID` | servers, registry | | Real tenant: issuer and JWKS derived from it |
| `AUTH_ISSUER`, `AUTH_JWKS_URL` | servers, registry | | Explicit issuer/JWKS (the dev issuer) |
| `AUTH_AUDIENCE` | all | `api://beast-assist` | Expected `aud` |
| `AUTH_DISABLED` | servers | `0` | `1` skips token checks (never in a shared environment) |
| `OPA_URL` | servers | `http://localhost:8181` | Policy engine |
| `POLICY_DISABLED` | servers | `0` | `1` allows everything (local debugging only) |
| `ALLOWED_HOSTS` | servers | | Host header allow-list (DNS-rebinding protection) |
| `AGILE_API_BASE`, `AGILE_API_TOKEN`, `AGILE_ACTOR` | agile-mcp | | Board API and its token |
| `COLLEGE_BASE` | college-mcp, RAG | `https://college.scarletbeast.com` | College API |
| `RAG_DSN` | college-mcp, RAG | `postgresql://beast:beast@localhost:55432/beast` | pgvector database |
| `REGISTRY_DSN` | registry | same | Registry database |
| `EMBEDDINGS` | RAG | `local` | `local` (fastembed, 384 dims) or `bedrock` (Titan V2, 512 dims, own table) |
| `AWS_REGION`, `BEDROCK_MODEL_ID` | agent, RAG | | Bedrock |
| `REGISTRY_URL`, `TOKEN_URL`, `MCP_SERVERS` | agent, evals, upload | local | Where things are |
| `AGENT_CLIENT_ID/SECRET`, `EVALS_CLIENT_ID/SECRET`, `PUBLISH_CLIENT_ID/SECRET` | agent, evals, upload | dev values | Client credentials |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | servers | | OTLP/HTTP endpoint for spans |

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Every call says `forbidden: policy engine unreachable` | OPA is down or `OPA_URL` is wrong; the servers fail closed | `curl localhost:18181/health` |
| `forbidden: skill "x" is not in the registry` | The skill was never published, or OPA has not pulled the bundle yet | `make seed`; `curl localhost:18181/v1/data/beast/skills` |
| `unauthorized: invalid token: Invalid issuer` | `AUTH_ISSUER` does not match the token's `iss` | For the dev issuer both are `http://localhost:8400/beast-dev-tenant/v2.0` |
| `/readyz` 503 with `backend: down` | The backend URL or token is wrong, or the host cannot reach it | Check `.env`; the compose file maps the Scarlet Beast hosts to the Docker host |
| `search index unavailable` | `rag/index_college.py` has not run, or PostgreSQL is down | `make seed` |
| `421 Misdirected` / host errors behind a proxy | `ALLOWED_HOSTS` does not list the public host | Add it |
| Upload refused with 409 | That version was already published with different content | Bump `version` in the SKILL.md |

## Status and known limits

Verified on 2026-10-19 on the development server, against the live Warden board and Scarlet College:

| Check | Result |
| --- | --- |
| Unit tests (`pytest -q`) | 30 passed |
| Agent integration tests (`pytest -m integration`) | 3 passed |
| Rego policy tests (`opa test policy/`) | 6 of 6 passed |
| `validate_skills.py` / `audit_skill_config.py` | 3 of 3 skills valid; audit passes (11 tools across 2 servers) |
| Benchmark scenarios (`evals/run_evals.py`) | 13 of 13 passed |
| The same scenarios through Azure APIM with real Entra tokens (`make evals-azure`, 2026-10-20) | 13 of 13 passed |
| RAG index | 33 lessons, 521 chunks, 6 courses (both bge-small and Titan indexes) |
| Retrieval quality (`rag/eval_retrieval.py`) | bge-small: hit@1 1.00, MRR 1.00; Titan: hit@1 0.88, MRR 0.92 (8 questions) |
| Agent and RAG generation on Bedrock (Nova Pro, 2026-10-20) | standup and cited RAG answer produced |
| Kubernetes overlays (`kustomize build` + `kubeconform -strict`) | dev 23 valid, prod 21 valid, 1 skipped each (the cert-manager CRD) |

The evals found two real bugs on their first run, both fixed with tests: the board answers an unknown
task with HTTP 422 rather than 404 (now mapped to `not_found`), and a restarted token issuer re-keyed
under the same key id, which cached verifiers rejected (the dev issuer now derives the kid from the key,
as Entra does, and verifiers refetch the JWKS once on a signature failure).

Limits:

- **Azure is live** since 2026-10-20 (resource group `beast-assist`, APIM `beast-assist-apim`, East US).
  The first run needed three fixes, all in `setup.sh` and the policy now: the identifier URI rule, the
  v2 token setting, and Consumption refusing `rate-limit-by-key`.
- **Bedrock is live** since 2026-10-20 with Amazon Nova Pro and Titan embeddings. Claude on Bedrock
  waits on the account's Anthropic use case form (see "Connecting Bedrock").
- The Azure client secrets expire after one year (2027-10-20). Renew one with
  `az ad app credential reset --id <client id> --years 1` and update `~/.beast-assist/<app>.env`.
- The Skills Registry's read endpoints are unauthenticated by design (cluster-internal, protected by
  NetworkPolicy); put them behind APIM before exposing them.
- The dev issuer's secrets are public dev values. It exists only for local use.
