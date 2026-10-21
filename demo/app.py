"""cognizant.scarletbeast.com: the Beast Assist live console (SERVICE=demo).

Runs in Azure Container Apps. The browser only talks to this app; this app holds the client credentials
and does what an agent host would do, in the open, so every hop can be shown:

    browser -> demo (Azure Container Apps) -> Entra ID token -> Azure API Management -> MCP server
            (Azure Container Apps) -> OPA (Azure Container Apps) -> the backend the tool wraps

    GET  /                  the page
    GET  /api/where         evidence of where this runs (replica, outbound network owner, DNS)
    GET  /api/health        each hop's health, measured from here
    GET  /api/status        the status board: every Azure and AWS service, checked in the background
    POST /api/run           one fixed scenario over MCP through APIM, with the full trace
    POST /api/agent         the LangGraph coordinator on Amazon Bedrock, read-only token, rate limited

Visitors cannot send arbitrary MCP calls: scenarios are fixed, free text is length-capped, the token is
read-only (Tools.Read), and the agile server is scoped to the public BA project.
"""
import asyncio
import json
import os
import socket
import time
from collections import defaultdict, deque
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

HERE = Path(__file__).parent
TENANT = os.environ.get("ENTRA_TENANT_ID", "")
AUDIENCE = os.environ.get("AUTH_AUDIENCE", "")
CLIENT_ID = os.environ.get("DEMO_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("DEMO_CLIENT_SECRET", "")
GATEWAY = os.environ.get("APIM_URL", "https://beast-assist-apim.azure-api.net").rstrip("/")
REGISTRY = os.environ.get("REGISTRY_URL", "").rstrip("/")
OPA = os.environ.get("OPA_URL", "").rstrip("/")
REGION = os.environ.get("AZURE_REGION", "")
HOST = os.environ.get("PUBLIC_HOST", "cognizant.scarletbeast.com")
AGENT_PER_IP_HOUR = int(os.environ.get("AGENT_PER_IP_HOUR", "6"))
AGENT_PER_DAY = int(os.environ.get("AGENT_PER_DAY", "150"))
RUN_PER_IP_HOUR = int(os.environ.get("RUN_PER_IP_HOUR", "120"))
TOKEN_URL = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(monitor())
    yield
    task.cancel()


app = FastAPI(title="beast-assist-demo", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
http = httpx.AsyncClient(timeout=45)


# ---- the Entra token, cached until shortly before it expires ------------------------------------------
_tok: dict = {"value": "", "exp": 0.0, "claims": {}}


async def token() -> tuple[str, dict]:
    if _tok["value"] and _tok["exp"] - 120 > time.time():
        return _tok["value"], {"cached": True, "ms": 0}
    t0 = time.perf_counter()
    r = await http.post(TOKEN_URL, data={"grant_type": "client_credentials", "client_id": CLIENT_ID,
                                         "client_secret": CLIENT_SECRET, "scope": f"{AUDIENCE}/.default"})
    r.raise_for_status()
    body = r.json()
    import base64
    payload = body["access_token"].split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    _tok.update(value=body["access_token"], exp=time.time() + int(body.get("expires_in", 3599)),
                claims={k: claims.get(k) for k in ("iss", "aud", "roles", "azp", "ver", "tid")})
    return _tok["value"], {"cached": False, "ms": round((time.perf_counter() - t0) * 1000)}


# ---- rate limits (one replica, so in memory is exact) ----------------------------------------------------
_hits: dict[str, deque] = defaultdict(deque)
_day = {"date": "", "agent": 0}


def client_ip(req: Request) -> str:
    return (req.headers.get("x-forwarded-for") or (req.client.host if req.client else "?")).split(",")[0].strip()


def limit(key: str, per_hour: int):
    q, now = _hits[key], time.time()
    while q and q[0] < now - 3600:
        q.popleft()
    if len(q) >= per_hour:
        raise HTTPException(429, f"limit reached ({per_hour} an hour); try again later")
    q.append(now)


# ---- one MCP call through APIM, traced ------------------------------------------------------------------
async def mcp(server: str, method: str, params: dict, skill: str | None, with_token: bool = True) -> dict:
    url = f"{GATEWAY}/{server}/mcp"
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    tok_info = None
    if with_token:
        tok, tok_info = await token()
        headers["Authorization"] = f"Bearer {tok}"
    if skill:
        headers["X-Skill-Id"] = skill
    rpc = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    t0 = time.perf_counter()
    r = await http.post(url, json=rpc, headers=headers)
    ms = round((time.perf_counter() - t0) * 1000)
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text[:2000]}
    keep = ("x-beast-gateway", "x-beast-gateway-request-id", "x-served-by", "x-beast-policy", "content-type", "date")
    shown = dict(headers)
    if "Authorization" in shown:
        shown["Authorization"] = "Bearer eyJ… (Entra ID access token, redacted)"
    return {"url": url, "status": r.status_code, "ms": ms, "token": tok_info,
            "request": {"headers": shown, "body": rpc},
            "response": {"headers": {k: v for k, v in r.headers.items() if k.lower() in keep}, "body": body}}


def tool_text(res: dict) -> tuple[bool, object]:
    """(is_error, parsed content) from a tools/call result."""
    result = (res["response"]["body"] or {}).get("result") or {}
    text = "".join(c.get("text", "") for c in result.get("content", []))
    data = result.get("structuredContent")
    if isinstance(data, dict) and set(data) == {"result"}:
        data = data["result"]
    if data is None:
        try:
            data = json.loads(text)
        except ValueError:
            data = text
    return bool(result.get("isError")), data


SCENARIOS = {
    "tools": dict(title="What can the board-standup skill see?", server="agile", method="tools/list",
                  params={}, skill="board-standup",
                  expect="Only the tools in the skill's allowed_tools. The server filters tools/list per skill."),
    "standup": dict(title="Open work on the BA board", server="agile", method="tools/call",
                    params={"name": "list_tasks", "arguments": {"project": "BA", "status": "in_progress,todo"}},
                    skill="board-standup", expect="A real read from the agile board, through every gate."),
    "search": dict(title="Semantic search over Scarlet College (pgvector)", server="college", method="tools/call",
                   params={"name": "search_lessons", "arguments": {"query": "", "k": 3}}, skill="college-tutor",
                   expect="Top passages by cosine similarity from Azure Database for PostgreSQL + pgvector."),
    "denied_write": dict(title="The standup skill tries to create a task", server="agile", method="tools/call",
                         params={"name": "create_task", "arguments": {"title": "should never exist", "project": "BA"}},
                         skill="board-standup",
                         expect="Refused by OPA: create_task is not in board-standup's allowed_tools."),
    "cross_skill": dict(title="The tutor skill tries to reach the agile board", server="agile", method="tools/call",
                        params={"name": "list_tasks", "arguments": {"project": "BA"}}, skill="college-tutor",
                        expect="Refused by OPA: college-tutor may only use college-mcp tools."),
    "scope": dict(title="Read a project outside the server's scope", server="agile", method="tools/call",
                  params={"name": "list_tasks", "arguments": {"project": "SB"}}, skill="board-standup",
                  expect="Refused by the server: this deployment is scoped to the BA project."),
    "no_skill": dict(title="A call with no skill header", server="agile", method="tools/call",
                     params={"name": "list_tasks", "arguments": {}}, skill=None,
                     expect="Refused by API Management (HTTP 400) before it reaches any server."),
    "no_token": dict(title="A call with no token", server="agile", method="tools/call",
                     params={"name": "list_tasks", "arguments": {}}, skill="board-standup", no_token=True,
                     expect="Refused by API Management's validate-jwt (HTTP 401)."),
}


class RunReq(BaseModel):
    scenario: str
    query: str = Field("", max_length=200)


@app.post("/api/run")
async def run(req: RunReq, request: Request):
    sc = SCENARIOS.get(req.scenario)
    if not sc:
        raise HTTPException(404, "unknown scenario")
    limit(f"run:{client_ip(request)}", RUN_PER_IP_HOUR)
    params = json.loads(json.dumps(sc["params"]))
    if req.scenario == "search":
        params["arguments"]["query"] = req.query.strip() or "how do I override a FastAPI dependency in a test?"
    res = await mcp(sc["server"], sc["method"], params, sc["skill"], with_token=not sc.get("no_token"))
    out = {"scenario": req.scenario, "title": sc["title"], "expect": sc["expect"], **res}
    if sc["method"] == "tools/call" and res["status"] == 200:
        out["is_error"], out["content"] = tool_text(res)
    elif sc["method"] == "tools/list" and res["status"] == 200:
        tools = ((res["response"]["body"] or {}).get("result") or {}).get("tools", [])
        out["is_error"], out["content"] = False, [t["name"] for t in tools]
    else:
        out["is_error"], out["content"] = True, res["response"]["body"]
    out["claims"] = _tok["claims"] if not sc.get("no_token") else None
    return out


# ---- the agent: LangGraph coordinator on Bedrock ---------------------------------------------------------
class AgentReq(BaseModel):
    question: str = Field(..., min_length=3, max_length=300)
    skill: str = Field("", pattern="^(|board-standup|college-tutor)$")


@app.post("/api/agent")
async def agent(req: AgentReq, request: Request):
    today = time.strftime("%Y-%m-%d")
    if _day["date"] != today:
        _day.update(date=today, agent=0)
    if _day["agent"] >= AGENT_PER_DAY:
        raise HTTPException(429, "the agent's daily limit is used up; the console scenarios still work")
    limit(f"agent:{client_ip(request)}", AGENT_PER_IP_HOUR)
    _day["agent"] += 1
    from langchain_core.messages import AIMessage, ToolMessage
    from agent.coordinator import build
    from agent.model import bedrock_model
    tok, _ = await token()
    inputs = {"project": "BA", **({"skill": req.skill} if req.skill else {})}  # the public board project
    t0 = time.perf_counter()
    try:
        state = await asyncio.wait_for(build(bedrock_model(), token=tok).ainvoke(
            {"request": req.question, "inputs": inputs}), timeout=90)
    except asyncio.TimeoutError:
        raise HTTPException(504, "the agent took longer than 90 s") from None
    steps, bedrock = [], []
    for m in state.get("messages", []):
        if isinstance(m, AIMessage):
            meta = m.response_metadata or {}
            rm = meta.get("ResponseMetadata") or {}
            bedrock.append({"request_id": rm.get("RequestId"), "latency_ms": (meta.get("metrics") or {}).get("latencyMs"),
                            "model": meta.get("model_name") or meta.get("model_id"),
                            "endpoint": f"bedrock-runtime.{os.environ.get('AWS_REGION', 'us-east-1')}.amazonaws.com",
                            "tokens": getattr(m, "usage_metadata", None)})
            for tc in m.tool_calls or []:
                steps.append({"kind": "tool_call", "tool": tc["name"], "args": tc["args"]})
        elif isinstance(m, ToolMessage):
            steps.append({"kind": "tool_result", "tool": m.name, "text": str(m.content)[:1500]})
    return {"answer": state.get("answer") or state.get("question") or "", "skill": (state.get("skill") or {}).get("name"),
            "steps": steps, "bedrock": bedrock, "ms": round((time.perf_counter() - t0) * 1000),
            "model": os.environ.get("BEDROCK_MODEL_ID"), "left_today": AGENT_PER_DAY - _day["agent"]}


# ---- where this runs ----------------------------------------------------------------------------------------
_where: dict = {}


@app.get("/api/where")
async def where():
    if not _where or _where.get("_at", 0) < time.time() - 600:
        info = {"container_app": os.environ.get("CONTAINER_APP_NAME"),
                "revision": os.environ.get("CONTAINER_APP_REVISION"),
                "replica": os.environ.get("CONTAINER_APP_REPLICA_NAME") or socket.gethostname(),
                "environment_domain": os.environ.get("CONTAINER_APP_ENV_DNS_SUFFIX"), "region": REGION}
        try:
            ip = (await http.get("https://api.ipify.org", timeout=5)).text.strip()
            org = (await http.get(f"https://ipinfo.io/{ip}/json", timeout=5)).json()
            info["outbound_ip"], info["outbound_network"] = ip, org.get("org")
            info["outbound_location"] = ", ".join(x for x in (org.get("city"), org.get("region")) if x)
        except Exception as e:  # noqa: BLE001 - evidence is best effort
            info["outbound_error"] = str(e)
        try:
            d = (await http.get("https://cloudflare-dns.com/dns-query", params={"name": HOST, "type": "CNAME"},
                                headers={"accept": "application/dns-json"}, timeout=5)).json()
            info["dns_cname"] = [a["data"].rstrip(".") for a in d.get("Answer", [])]
        except Exception as e:  # noqa: BLE001
            info["dns_error"] = str(e)
        info.update(gateway=GATEWAY, token_issuer=f"https://login.microsoftonline.com/{TENANT}/v2.0",
                    bedrock=f"bedrock-runtime.{os.environ.get('AWS_REGION', 'us-east-1')}.amazonaws.com",
                    model=os.environ.get("BEDROCK_MODEL_ID"))
        _where.clear()
        _where.update(info, _at=time.time())
    return {k: v for k, v in _where.items() if not k.startswith("_")}


@app.get("/api/health")
async def health():
    async def probe(name, url, **kw):
        t0 = time.perf_counter()
        try:
            r = await http.get(url, timeout=10, **kw)
            return name, {"ok": r.status_code < 400, "status": r.status_code, "ms": round((time.perf_counter() - t0) * 1000),
                          "served_by": r.headers.get("x-served-by")}
        except Exception as e:  # noqa: BLE001
            return name, {"ok": False, "error": e.__class__.__name__}
    checks = [probe("agile-mcp", os.environ.get("AGILE_MCP_URL", "") + "/readyz"),
              probe("college-mcp", os.environ.get("COLLEGE_MCP_URL", "") + "/readyz"),
              probe("registry", REGISTRY + "/readyz"), probe("opa", OPA + "/health"),
              probe("entra", f"https://login.microsoftonline.com/{TENANT}/v2.0/.well-known/openid-configuration")]
    return dict(await asyncio.gather(*checks))


# ---- the GitHub repository card (cached: unauthenticated GitHub API allows 60 calls an hour) --------------
REPO = os.environ.get("GITHUB_REPO", "christianscarlet2/beast-assist")
_repo: dict = {}


@app.get("/api/repo")
async def repo():
    if _repo.get("_at", 0) > time.time() - 600:
        return {k: v for k, v in _repo.items() if not k.startswith("_")}
    gh, hdr = f"https://api.github.com/repos/{REPO}", {"Accept": "application/vnd.github+json"}
    try:
        meta, commits, runs, langs, tree = await asyncio.gather(
            http.get(gh, headers=hdr, timeout=10), http.get(f"{gh}/commits", params={"per_page": 5}, headers=hdr, timeout=10),
            http.get(f"{gh}/actions/runs", params={"per_page": 1, "branch": "main"}, headers=hdr, timeout=10),
            http.get(f"{gh}/languages", headers=hdr, timeout=10), http.get(f"{gh}/contents", headers=hdr, timeout=10))
        m = meta.json()
        run = (runs.json().get("workflow_runs") or [{}])[0]
        link = commits.headers.get("link", "")
        out = {
            "description": m.get("description"), "topics": m.get("topics", []), "pushed_at": m.get("pushed_at"),
            "languages": langs.json() if langs.status_code == 200 else {},
            "commits": [{"sha": c["sha"][:7], "message": c["commit"]["message"].splitlines()[0],
                         "at": time.mktime(time.strptime(c["commit"]["author"]["date"], "%Y-%m-%dT%H:%M:%SZ")) - time.timezone}
                        for c in commits.json()][:5] if commits.status_code == 200 else [],
            "ci": {"status": run.get("status"), "ok": run.get("conclusion") == "success", "url": run.get("html_url")} if run else None,
            "tree": sorted(({"name": f["name"], "dir": f["type"] == "dir"} for f in tree.json()), key=lambda f: (not f["dir"], f["name"]))
                    if tree.status_code == 200 else [],
        }
        import re as _re
        last = _re.search(r'page=(\d+)>; rel="last"', link)
        out["commit_count"] = None
        if last:
            per = await http.get(f"{gh}/commits", params={"per_page": 1}, headers=hdr, timeout=10)
            lp = _re.search(r'page=(\d+)>; rel="last"', per.headers.get("link", ""))
            out["commit_count"] = int(lp.group(1)) if lp else None
    except Exception as e:  # noqa: BLE001 - the card falls back to its static text
        return {"error": e.__class__.__name__}
    _repo.clear()
    _repo.update(out, _at=time.time())
    return out


@app.get("/api/config.js")
async def config_js():
    from fastapi.responses import Response
    cfg = {"video": os.environ.get("VIDEO_URL", "")}
    return Response(f"window.BEAST_VIDEO = {json.dumps(cfg['video'])};", media_type="application/javascript",
                    headers={"Cache-Control": "no-cache"})


# ---- status board: every Azure and AWS service, checked in the background --------------------------------
# Each check returns (ok, detail). The board keeps the last result, the last time each service was healthy,
# and a short history, so the page can show a light per service with its last status underneath.
BEDROCK_EVERY = int(os.environ.get("BEDROCK_CHECK_SECONDS", "300"))   # a real (tiny) model call costs money
CHECK_EVERY = int(os.environ.get("STATUS_CHECK_SECONDS", "60"))
STATUS: dict[str, dict] = {}


async def _get(url: str, **kw) -> httpx.Response:
    return await http.get(url, timeout=10, **kw)


async def chk_self():
    return True, f"replica {os.environ.get('CONTAINER_APP_REPLICA_NAME') or socket.gethostname()}"


async def chk_ready(url: str):
    r = await _get(url + "/readyz")
    return r.status_code == 200, f"HTTP {r.status_code}" + (f" · {r.headers['x-served-by']}" if r.headers.get("x-served-by") else "")


async def chk_opa():
    r = await http.post(OPA + "/v1/data/beast/tools/allow", json={"input": {}}, timeout=10)
    skills = (await _get(OPA + "/v1/data/beast/skills")).json().get("result") or {}
    return r.status_code == 200 and bool(skills), f"policy answering · {len(skills)} skills loaded from the registry bundle"


async def chk_registry():
    r = await _get(REGISTRY + "/skills")
    n = len(r.json()) if r.status_code == 200 else 0
    return r.status_code == 200, f"HTTP {r.status_code} · {n} skills published"


async def chk_postgres():
    dsn = os.environ.get("RAG_DSN", "")
    if not dsn:
        return False, "no database configured"
    import psycopg
    async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=10) as con:
        chunks = (await (await con.execute("SELECT count(*) FROM college_chunks")).fetchone())[0]
        ver = (await (await con.execute("SELECT extversion FROM pg_extension WHERE extname='vector'")).fetchone())[0]
    return True, f"{chunks} RAG chunks · pgvector {ver}"


async def chk_entra():
    _tok["exp"] = 0  # force a fresh token: proves the client credentials still work
    _, info = await token()
    return True, f"token issued in {info['ms']} ms · roles {', '.join(_tok['claims'].get('roles') or [])}"


async def chk_apim():
    res = await mcp("agile", "tools/list", {}, "board-standup")
    tools = ((res["response"]["body"] or {}).get("result") or {}).get("tools", [])
    gw = res["response"]["headers"].get("x-beast-gateway", "")
    return res["status"] == 200 and bool(tools), f"end-to-end tools/list: {len(tools)} tools · {gw}"


async def chk_unauth():
    r = await http.post(f"{GATEWAY}/agile/mcp", json={}, headers={"X-Skill-Id": "board-standup"}, timeout=10)
    return r.status_code == 401, f"unauthenticated call refused with HTTP {r.status_code}, as it should be"


async def chk_bedrock():
    import boto3
    region = os.environ.get("AWS_REGION", "us-east-1")
    rt = boto3.client("bedrock-runtime", region_name=region)
    r = await asyncio.to_thread(rt.converse, modelId=os.environ.get("BEDROCK_MODEL_ID", ""),
                                messages=[{"role": "user", "content": [{"text": "Reply with: ok"}]}],
                                inferenceConfig={"maxTokens": 5})
    return True, f"{r['metrics']['latencyMs']} ms · request {r['ResponseMetadata']['RequestId'][:8]}… · {region}"


async def chk_blob():
    url = os.environ.get("VIDEO_URL", "")
    if not url:
        return False, "no video configured"
    r = await http.head(url, timeout=10)
    size = int(r.headers.get("content-length", 0)) / 1e6
    return r.status_code == 200, f"HTTP {r.status_code} · walkthrough video {size:.0f} MB"


SERVICES = [  # id, name, cloud, what it is, check, every
    ("demo", "cognizant.scarletbeast.com", "azure", "Azure Container Apps · this page", chk_self, CHECK_EVERY),
    ("agile", "agile-mcp", "azure", "Azure Container Apps · MCP server", lambda: chk_ready(os.environ.get("AGILE_MCP_URL", "")), CHECK_EVERY),
    ("college", "college-mcp", "azure", "Azure Container Apps · MCP server", lambda: chk_ready(os.environ.get("COLLEGE_MCP_URL", "")), CHECK_EVERY),
    ("opa", "OPA", "azure", "Azure Container Apps · policy engine", chk_opa, CHECK_EVERY),
    ("registry", "Skills Registry", "azure", "Azure Container Apps · FastAPI", chk_registry, CHECK_EVERY),
    ("postgres", "PostgreSQL + pgvector", "azure", "Azure Database for PostgreSQL", chk_postgres, CHECK_EVERY),
    ("apim", "API Management", "azure", "Azure API Management · gateway", chk_apim, CHECK_EVERY),
    ("apim_guard", "Gateway auth guard", "azure", "Azure API Management · validate-jwt", chk_unauth, CHECK_EVERY),
    ("entra", "Entra ID", "azure", "Microsoft Entra ID · OAuth tokens", chk_entra, CHECK_EVERY),
    ("blob", "Video storage", "azure", "Azure Blob Storage", chk_blob, CHECK_EVERY),
    ("bedrock", "Bedrock model", "aws", "Amazon Bedrock · " + os.environ.get("BEDROCK_MODEL_ID", ""), chk_bedrock, BEDROCK_EVERY),
]


async def check_one(sid, fn):
    t0 = time.perf_counter()
    try:
        ok, detail = await asyncio.wait_for(fn(), timeout=30)
    except Exception as e:  # noqa: BLE001 - a failed check is a red light, not a crash
        ok, detail = False, f"{e.__class__.__name__}: {str(e)[:140]}"
    st = STATUS[sid]
    now = time.time()
    if st.get("ok") is not None and st["ok"] != ok:
        st["changed_at"] = now
    st.update(ok=ok, detail=detail, ms=round((time.perf_counter() - t0) * 1000), checked_at=now,
              checks=st.get("checks", 0) + 1, fails=st.get("fails", 0) + (not ok))
    if ok:
        st["last_ok"] = now
    st.setdefault("changed_at", now)
    st["history"] = (st.get("history", []) + [1 if ok else 0])[-30:]


async def monitor():
    for sid, name, cloud, what, _fn, every in SERVICES:
        STATUS[sid] = {"id": sid, "name": name, "cloud": cloud, "what": what, "every": every}
    due = {sid: 0.0 for sid, *_ in SERVICES}
    started = time.time()
    while True:
        now = time.time()
        await asyncio.gather(*(check_one(sid, fn) for sid, _n, _c, _w, fn, every in SERVICES if due[sid] <= now))
        for sid, _n, _c, _w, _fn, every in SERVICES:
            if due[sid] <= now:
                due[sid] = now + every
        STATUS["_meta"] = {"started_at": started}
        await asyncio.sleep(5)


@app.get("/api/status")
async def status():
    rows = [v for k, v in STATUS.items() if not k.startswith("_")]
    return {"now": time.time(), "services": rows, "monitor_started": STATUS.get("_meta", {}).get("started_at"),
            "all_ok": bool(rows) and all(r.get("ok") for r in rows)}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(HERE / "static" / "favicon.svg", media_type="image/svg+xml")


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/")
async def index():
    return FileResponse(HERE / "static" / "index.html", headers={"Cache-Control": "no-cache"})


@app.exception_handler(httpx.HTTPError)
async def upstream_error(_req, exc):
    return JSONResponse({"detail": f"upstream error: {exc.__class__.__name__}"}, status_code=502)
