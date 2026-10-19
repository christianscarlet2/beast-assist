"""The one backend this server adapts: the Warden agile board's token API (/api/agile)."""
import os

import httpx

from beast_mcp import ToolFailure


class AgileBackend:
    def __init__(self, base: str, token: str, actor: str, transport: httpx.AsyncBaseTransport | None = None):
        self.http = httpx.AsyncClient(base_url=base.rstrip("/"), timeout=20, transport=transport, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/json", "X-Agile-Actor": actor})

    async def call(self, method: str, path: str, body: dict | None = None, params: dict | None = None):
        try:
            r = await self.http.request(method, path, json=body, params=params)
        except httpx.HTTPError as e:
            raise ToolFailure(f"agile board unreachable: {e}", hint="retry once; if it fails again, stop and report",
                              code="backend_unavailable") from None
        try:
            data = r.json()
        except ValueError:
            raise ToolFailure(f"agile board returned HTTP {r.status_code} without JSON", code="backend_error") from None
        # the board answers an unknown key with 422 "No task 'SB-9'"; to the agent that is not_found
        missing = r.status_code == 404 or (r.status_code == 422 and str(data.get("error", "")).startswith("No "))
        if missing:
            raise ToolFailure(data.get("error") or "not found", hint="check the key with list_tasks", code="not_found")
        if r.status_code == 422:
            raise ToolFailure(data.get("error") or "invalid input", hint="fix the named field and call again",
                              code="invalid_input")
        if r.status_code >= 400:
            raise ToolFailure(data.get("error") or f"HTTP {r.status_code}", code="backend_error")
        return data

    async def ready(self) -> bool:
        await self.call("GET", "/projects")
        return True

    async def aclose(self):
        await self.http.aclose()


def make_backend() -> AgileBackend:
    token = os.environ.get("AGILE_API_TOKEN", "")
    return AgileBackend(os.environ.get("AGILE_API_BASE", "https://living.scarletbeast.com/api/agile"), token,
                        os.environ.get("AGILE_ACTOR", "Beast Assist (MCP)"))
