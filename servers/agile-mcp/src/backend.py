"""The one backend this server adapts: the Warden agile board's token API (/api/agile)."""
import os

import httpx

from beast_mcp import ToolFailure


class ProjectScope:
    """projects: when set, the only project keys this server may touch (AGILE_PROJECTS=BA). A public demo
    runs scoped to its own project, so the rest of the board stays invisible even to a valid token."""

    def __init__(self, projects: list[str] | None = None, default_project: str = ""):
        self.projects = [p.upper() for p in projects] if projects else None
        self.default_project = (default_project or (self.projects[0] if self.projects else "SB")).upper()

    def project(self, key: str = "") -> str:
        """The project a tool acts on: the one asked for, else the default; refused outside the scope."""
        key = (key or self.default_project).upper()
        if self.projects is not None and key not in self.projects:
            raise ToolFailure(f"project {key} is outside this server's scope", code="forbidden",
                              hint=f"use one of: {', '.join(self.projects)}")
        return key

    def task_key(self, key: str) -> str:
        """Check a task key like BA-7 against the scope; returns it upper-cased."""
        if "-" not in key:
            raise ToolFailure(f"{key!r} is not a task key", hint=f"pass a key like {self.default_project}-12",
                              code="invalid_input")
        self.project(key.rsplit("-", 1)[0])
        return key.upper()

    def visible(self, projects: list[dict]) -> list[dict]:
        return [p for p in projects if self.projects is None or str(p.get("key", "")).upper() in self.projects]


class AgileBackend(ProjectScope):
    def __init__(self, base: str, token: str, actor: str, transport: httpx.AsyncBaseTransport | None = None,
                 projects: list[str] | None = None, default_project: str = ""):
        super().__init__(projects, default_project)
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
    scope = [p.strip() for p in os.environ.get("AGILE_PROJECTS", "").split(",") if p.strip()]
    return AgileBackend(os.environ.get("AGILE_API_BASE", "https://living.scarletbeast.com/api/agile"), token,
                        os.environ.get("AGILE_ACTOR", "Beast Assist (MCP)"), projects=scope or None,
                        default_project=os.environ.get("AGILE_DEFAULT_PROJECT", ""))
