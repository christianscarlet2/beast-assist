"""create_app(): one FastAPI app per MCP server.

    GET  /healthz   liveness: the process is up
    GET  /readyz    readiness: the backend and OPA answer
    POST /mcp       MCP over streamable HTTP (stateless, JSON responses: any replica can serve any call)

Every tools/call passes three gates in order: the Entra token (who), OPA with the skill's
allowed_tools (may this skill use this tool), then the tool itself inside a trace span.
tools/list is filtered to the skill's allowed tools, so an agent never sees what it cannot call.
"""
import functools
import inspect
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from . import registry, telemetry
from .auth import AuthError, TokenVerifier
from .discovery import discover
from .errors import ToolFailure
from .policy import PolicyClient, PolicyError
from .settings import Settings

SKILL_HEADER = "x-skill-id"


def _refusal(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


def _wrap(spec):
    """Turn a ToolFailure into an MCP tool error whose text tells the model what to do next."""
    fn = spec.fn

    @functools.wraps(fn)
    async def run(*a, **kw):
        try:
            out = fn(*a, **kw)
            return await out if inspect.isawaitable(out) else out
        except ToolFailure as e:
            raise ToolError(e.text()) from None
    return run


def create_app(server_root: str | Path, name: str, instructions: str = "") -> FastAPI:
    server_root = Path(server_root)
    settings = Settings.load(name)
    tracer = telemetry.setup(name)
    verifier = TokenVerifier(settings)
    policy = PolicyClient(settings)

    backend_mod, specs = discover(server_root, name)
    client = backend_mod.make_backend()
    registry.set_backend(name, client)
    by_name = {s.name: s for s in specs}

    async def guard(ctx, call_next):
        """SDK middleware: the single chokepoint for tools/list and tools/call."""
        if ctx.method not in ("tools/call", "tools/list"):
            return await call_next(ctx)
        registry.current_server.set(name)
        req = getattr(ctx, "request", None)  # the Starlette request on HTTP transports; None on stdio
        headers = {k.lower(): v for k, v in (getattr(req, "headers", None) or {}).items()}
        skill = headers.get(SKILL_HEADER, "")
        try:
            claims = verifier.verify(headers.get("authorization"))
        except AuthError as e:
            return _refusal(f"unauthorized: {e}")

        if ctx.method == "tools/list":
            result = await call_next(ctx)
            allowed = await policy.allowed_tools(skill)
            if allowed is None:
                return result
            data = result.model_dump(by_alias=True, exclude_none=True) if hasattr(result, "model_dump") else dict(result)
            data["tools"] = [t for t in data.get("tools", []) if t["name"] in allowed]
            return data

        tool = (ctx.params or {}).get("name", "")
        spec = by_name.get(tool)
        with tracer.start_as_current_span(f"tool {name}:{tool}") as span:
            span.set_attribute("beast.skill", skill)
            span.set_attribute("beast.tool", f"{name}:{tool}")
            t0 = time.perf_counter()
            if spec is None:
                return await call_next(ctx)  # the SDK answers unknown tools itself
            try:
                d = await policy.decide(claims=claims, skill=skill, tool=tool, write=spec.write)
            except PolicyError as e:
                telemetry.log_call(server=name, tool=tool, skill=skill, outcome="policy_error", error=str(e))
                return _refusal(f"forbidden: {e}")
            if not d.get("allow"):
                reasons = "; ".join(d.get("reasons") or ["denied"])
                span.set_attribute("beast.outcome", "denied")
                telemetry.log_call(server=name, tool=tool, skill=skill, outcome="denied", reasons=reasons,
                                   caller=claims.get("oid"))
                return _refusal(f"forbidden: {reasons}")
            result = await call_next(ctx)
            is_err = bool(getattr(result, "is_error", None) or (isinstance(result, dict) and result.get("isError")))
            outcome = "error" if is_err else "ok"
            span.set_attribute("beast.outcome", outcome)
            telemetry.log_call(server=name, tool=tool, skill=skill, outcome=outcome, caller=claims.get("oid"),
                               ms=round((time.perf_counter() - t0) * 1000, 1))
            return result

    mcp = MCPServer(name=name, instructions=instructions, middleware=[guard])
    for s in specs:
        mcp.add_tool(_wrap(s), name=s.name, description=inspect.getdoc(s.fn),
                     annotations=ToolAnnotations(readOnlyHint=not s.write, destructiveHint=False))

    hosts = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]
    starlette = mcp.streamable_http_app(
        stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=bool(hosts),
                                                     allowed_hosts=hosts))

    @asynccontextmanager
    async def lifespan(_app):
        async with starlette.router.lifespan_context(starlette):
            yield
        if hasattr(client, "aclose"):
            await client.aclose()

    app = FastAPI(title=name, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.tools = specs
    app.state.settings = settings

    @app.get("/healthz")
    async def healthz():
        return {"ok": True, "server": name, "tools": len(specs)}

    @app.get("/readyz")
    async def readyz():
        checks = {}
        try:
            checks["backend"] = bool(await client.ready())
        except Exception as e:  # noqa: BLE001 - readiness reports, it does not raise
            checks["backend"] = f"down: {e}"
        if not settings.policy_disabled:
            try:
                r = await policy._http.get(f"{settings.opa_url}/health")
                checks["opa"] = r.status_code == 200
            except Exception as e:  # noqa: BLE001
                checks["opa"] = f"down: {e}"
        ok = all(v is True for v in checks.values())
        return JSONResponse({"ok": ok, **checks}, status_code=200 if ok else 503)

    app.mount("/", starlette)
    return app
