"""OPA decides every tool call. Input: who is calling, under which skill, which tool, read or write.

The skill's allowed_tools list (from the Skills Registry, served to OPA as a bundle) is the
authorization scope: a tool outside it is refused even if the caller's token could reach it."""
import httpx

from .settings import Settings


class PolicyError(Exception):
    pass


class PolicyClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self._http = httpx.AsyncClient(timeout=3)

    async def decide(self, *, claims: dict, skill: str, tool: str, write: bool) -> dict:
        if self.s.policy_disabled:
            return {"allow": True, "reasons": ["policy disabled"]}
        body = {"input": {
            "env": self.s.env,
            "server": self.s.server_name,
            "tool": tool,
            "qualified_tool": f"{self.s.server_name}:{tool}",
            "write": write,
            "skill": skill,
            "subject": {"oid": claims.get("oid") or claims.get("sub"),
                        "permissions": sorted(claims.get("permissions", []))},
        }}
        try:
            r = await self._http.post(f"{self.s.opa_url}/v1/data/beast/tools/decision", json=body)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise PolicyError(f"policy engine unreachable: {e}") from None  # fail closed
        return r.json().get("result") or {"allow": False, "reasons": ["no decision"]}

    async def allowed_tools(self, skill: str) -> list[str] | None:
        """The skill's allowed tools on THIS server, for filtering tools/list. None = no filter."""
        if self.s.policy_disabled or not skill:
            return None
        try:
            r = await self._http.get(f"{self.s.opa_url}/v1/data/beast/skills/{skill}/allowed_tools")
            r.raise_for_status()
            tools = r.json().get("result") or []
        except httpx.HTTPError:
            return []
        prefix = self.s.server_name + ":"
        return [t[len(prefix):] for t in tools if t.startswith(prefix)]
