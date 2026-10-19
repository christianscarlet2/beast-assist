"""The one backend this server adapts. Replace ExampleBackend with a real client."""
import os

import httpx

from beast_mcp import ToolFailure


class ExampleBackend:
    def __init__(self, base: str, token: str):
        self.http = httpx.AsyncClient(base_url=base, timeout=20, headers={"Authorization": f"Bearer {token}"})

    async def get(self, path: str, **params):
        try:
            r = await self.http.get(path, params=params)
        except httpx.HTTPError as e:
            raise ToolFailure(f"backend unreachable: {e}", hint="retry once", code="backend_unavailable") from None
        if r.status_code == 404:
            raise ToolFailure("not found", code="not_found")
        r.raise_for_status()
        return r.json()

    async def ready(self) -> bool:
        return True

    async def aclose(self):
        await self.http.aclose()


def make_backend() -> ExampleBackend:
    return ExampleBackend(os.environ.get("BACKEND_URL", "https://example.invalid"), os.environ.get("BACKEND_TOKEN", ""))
