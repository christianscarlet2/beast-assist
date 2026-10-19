"""Fixtures that run a real MCP server over real HTTP, with Entra and OPA replaced in-process:

- tokens are RS256 JWTs signed by a test key the verifier trusts (same checks as production)
- policy is a Python port of policy/tools.rego fed from the repo's own SKILL.md files, so the
  scopes under test are the real ones (the Rego itself is tested with `opa test policy/`)
"""
import asyncio
import socket
import sys
import threading
import time
from pathlib import Path

import jwt
import pytest
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWKSet
from jwt.algorithms import RSAAlgorithm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from _skills import all_skills  # noqa: E402

ISS, AUD, KID = "https://login.example/test-tenant/v2.0", "api://beast-assist", "test-1"
_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_jwks = PyJWKSet.from_dict({"keys": [RSAAlgorithm.to_jwk(_key.public_key(), as_dict=True) | {"kid": KID, "alg": "RS256"}]})
SKILLS = {m["name"]: m for _, m in all_skills()}
STAGES = {"dev": {"draft", "beta", "production"}, "staging": {"beta", "production"}, "prod": {"production"}}


def make_token(roles=("Tools.Read",), aud=AUD, iss=ISS, exp_in=600, key=_key, kid=KID) -> str:
    now = int(time.time())
    return jwt.encode({"iss": iss, "aud": aud, "sub": "t", "oid": "test-oid", "roles": list(roles),
                       "iat": now, "exp": now + exp_in}, key, algorithm="RS256", headers={"kid": kid})


def py_policy(env, skill, qualified_tool, write, perms) -> dict:
    """Same rules as policy/tools.rego."""
    s = SKILLS.get(skill)
    reasons = []
    if not skill:
        reasons.append("no skill named in the X-Skill-Id header")
    elif not s:
        reasons.append(f'skill "{skill}" is not in the registry')
    else:
        if s["lifecycle"] not in STAGES[env]:
            reasons.append(f'skill "{skill}" is {s["lifecycle"]} and cannot run in {env}')
        if qualified_tool not in s["allowed_tools"]:
            reasons.append(f'{qualified_tool} is not in the allowed_tools of skill "{skill}"')
    for p in ["Tools.Read"] + (["Tools.Write"] if write else []):
        if p not in perms:
            reasons.append(f"token lacks {p}")
    return {"allow": not reasons, "reasons": reasons}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def serve(monkeypatch):
    """serve(server_name, fake_backend, env="dev") -> base URL of a live server on a free port."""
    from beast_mcp import auth, policy, registry

    monkeypatch.setenv("AUTH_ISSUER", ISS)
    monkeypatch.setenv("AUTH_AUDIENCE", AUD)
    monkeypatch.setenv("AUTH_JWKS_URL", "http://unused.invalid/keys")
    monkeypatch.setattr(auth.TokenVerifier, "_jwks", lambda self, force=False: _jwks)
    servers = []

    def start(name, fake, env="dev"):
        monkeypatch.setenv("BEAST_ENV", env)

        async def decide(self, *, claims, skill, tool, write):
            return py_policy(self.s.env, skill, f"{self.s.server_name}:{tool}", write, claims["permissions"])

        async def allowed(self, skill):
            s = SKILLS.get(skill)
            pre = self.s.server_name + ":"
            return [t[len(pre):] for t in (s["allowed_tools"] if s else []) if t.startswith(pre)]

        monkeypatch.setattr(policy.PolicyClient, "decide", decide)
        monkeypatch.setattr(policy.PolicyClient, "allowed_tools", allowed)
        registry.reset()
        from beast_mcp import create_app
        app = create_app(ROOT / "servers" / name, name)
        registry.set_backend(name, fake)
        port = _free_port()
        srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        th = threading.Thread(target=srv.run, daemon=True)
        th.start()
        for _ in range(200):
            if srv.started:
                break
            time.sleep(0.05)
        servers.append((srv, th))
        return f"http://127.0.0.1:{port}"

    yield start
    for srv, th in servers:
        srv.should_exit = True
        th.join(timeout=5)


async def mcp_call(base: str, tool: str | None, args=None, skill="", token=None, list_tools=False):
    """-> (is_error, payload) through the real MCP client over HTTP."""
    from mcp import ClientSession
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
    h = {}
    if token is not None:
        h["Authorization"] = f"Bearer {token}"
    if skill:
        h["X-Skill-Id"] = skill
    async with streamable_http_client(base + "/mcp", http_client=create_mcp_http_client(headers=h)) as st:
        async with ClientSession(st[0], st[1]) as s:
            await s.initialize()
            if list_tools:
                return False, sorted(t.name for t in (await s.list_tools()).tools)
            r = await s.call_tool(tool, args or {})
            text = "".join(getattr(c, "text", "") for c in r.content)
            data = r.structured_content
            if isinstance(data, dict) and set(data) == {"result"}:
                data = data["result"]
            if r.is_error:
                return True, text
            if data is None:
                import json
                try:
                    data = json.loads(text)
                except ValueError:
                    data = text
            return False, data
