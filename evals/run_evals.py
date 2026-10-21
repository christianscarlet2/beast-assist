#!/usr/bin/env python3
"""run_evals.py: run every benchmark scenario in evals/scenarios through the real path
(Entra token -> MCP over HTTP -> OPA -> tool -> backend) and check the result.

  python evals/run_evals.py [-k text]        writes evals/results/<time>.json; exit 1 on any failure
Env: MCP_SERVERS (JSON name -> url), TOKEN_URL, EVALS_CLIENT_ID / EVALS_CLIENT_SECRET"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx
import yaml
from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
from mcp.shared.exceptions import MCPError

HERE = Path(__file__).parent
SERVERS = json.loads(os.environ.get("MCP_SERVERS", json.dumps({
    "agile-mcp": "http://localhost:8421/mcp", "college-mcp": "http://localhost:8422/mcp"})))


def token() -> str:
    r = httpx.post(os.environ.get("TOKEN_URL", "http://localhost:8400/beast-dev-tenant/oauth2/v2.0/token"), data={
        "grant_type": "client_credentials", "client_id": os.environ.get("EVALS_CLIENT_ID", "beast-evals"),
        "client_secret": os.environ.get("EVALS_CLIENT_SECRET", "dev-evals-secret"),
        "scope": os.environ.get("AUTH_AUDIENCE", "api://beast-assist") + "/.default"}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def _has(exc: BaseException, kind) -> bool:
    return isinstance(exc, kind) or any(_has(e, kind) for e in getattr(exc, "exceptions", ()))


async def _gateway_refusal(sc: dict, headers: dict) -> str | None:
    """A gateway (APIM) refuses with a plain HTTP 4xx before MCP starts. The SDK turns that into a bare
    MCPError and drops the body, so replay the initialize as plain HTTP to read what the gateway said."""
    body = {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "beast-evals", "version": "1"}}}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(SERVERS[sc["server"]], json=body,
                         headers={**headers, "Accept": "application/json, text/event-stream"})
    return f"HTTP {r.status_code}: {r.text}" if 400 <= r.status_code < 500 else None


def _headers(sc: dict, tok: str) -> dict:
    headers = {"Authorization": f"Bearer {tok}"}
    if sc.get("skill"):
        headers["X-Skill-Id"] = sc["skill"]
    return headers


async def call(sc: dict, tok: str):
    try:
        return await _call(sc, tok)
    except Exception as e:  # noqa: BLE001
        if not _has(e, MCPError) or not (refusal := await _gateway_refusal(sc, _headers(sc, tok))):
            raise
        return True, refusal


async def _call(sc: dict, tok: str):
    headers = _headers(sc, tok)
    async with streamable_http_client(SERVERS[sc["server"]], http_client=create_mcp_http_client(headers=headers)) as streams:
        async with ClientSession(streams[0], streams[1]) as s:
            await s.initialize()
            if sc.get("list_tools"):
                return False, [t.name for t in (await s.list_tools()).tools]
            res = await s.call_tool(sc["tool"], sc.get("args") or {})
            text = "".join(getattr(c, "text", "") for c in res.content)
            if res.is_error:
                return True, text
            data = res.structured_content
            if isinstance(data, dict) and set(data) == {"result"}:
                data = data["result"]
            if data is None:
                try:
                    data = json.loads(text)
                except ValueError:
                    data = text
            return False, data


def check(exp: dict, is_err: bool, out) -> list[str]:
    bad = []
    if "error_contains" in exp:
        if not is_err or exp["error_contains"] not in str(out):
            bad.append(f"expected an error containing {exp['error_contains']!r}, got {str(out)[:160]!r}")
        return bad
    if is_err:
        return [f"unexpected error: {str(out)[:200]}"]
    if exp.get("type") == "list" and not isinstance(out, list):
        bad.append(f"expected a list, got {type(out).__name__}")
    if "keys" in exp and not all(k in out for k in exp["keys"]):
        bad.append(f"missing keys {[k for k in exp['keys'] if k not in out]}")
    if isinstance(out, list):
        if len(out) < exp.get("min_items", 0):
            bad.append(f"expected at least {exp['min_items']} items, got {len(out)}")
        for k in exp.get("item_keys", []):
            if out and k not in out[0]:
                bad.append(f"items lack {k!r}")
        for k, v in (exp.get("all_items") or {}).items():
            if any(i.get(k) != v for i in out):
                bad.append(f"not every item has {k}={v!r}")
        if "first_score_at_least" in exp and (not out or out[0].get("score", 0) < exp["first_score_at_least"]):
            bad.append(f"top score {out[0].get('score') if out else None} < {exp['first_score_at_least']}")
        if "exactly" in exp and sorted(out) != sorted(exp["exactly"]):
            bad.append(f"expected exactly {sorted(exp['exactly'])}, got {sorted(out)}")
    if "contains" in exp and exp["contains"] not in json.dumps(out):
        bad.append(f"output does not mention {exp['contains']!r}")
    return bad


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", default="")
    a = ap.parse_args()
    tok = token()
    scenarios = [dict(sc, file=f.stem) for f in sorted((HERE / "scenarios").glob("*.yaml"))
                 for sc in yaml.safe_load(f.read_text()) if a.k.lower() in sc["name"].lower()]
    results, failed = [], 0
    for sc in scenarios:
        t0 = time.perf_counter()
        try:
            is_err, out = await call(sc, tok)
            problems = check(sc.get("expect") or {}, is_err, out)
        except Exception as e:  # noqa: BLE001 - a crash is a failed scenario, reported, not raised
            problems = [f"crashed: {e.__class__.__name__}: {e}"]
        ms = (time.perf_counter() - t0) * 1000
        failed += bool(problems)
        print(f"{'FAIL' if problems else 'pass'}  {ms:6.0f} ms  [{sc['file']}] {sc['name']}")
        for p in problems:
            print(f"        {p}")
        results.append({"name": sc["name"], "file": sc["file"], "ok": not problems, "ms": round(ms), "problems": problems})
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"{time.strftime('%Y%m%d-%H%M%S')}.json").write_text(json.dumps(results, indent=1))
    print(f"\n{len(results) - failed}/{len(results)} scenarios passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
