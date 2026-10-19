"""The one backend this server adapts: Scarlet College (its public JSON API) plus its pgvector index."""
import os

import httpx
import psycopg

from beast_mcp import ToolFailure


class CollegeBackend:
    def __init__(self, base: str, dsn: str, transport: httpx.AsyncBaseTransport | None = None):
        self.http = httpx.AsyncClient(base_url=base.rstrip("/"), timeout=20, transport=transport,
                                      headers={"Accept": "application/json"})
        self.dsn = dsn

    async def get(self, path: str):
        try:
            r = await self.http.get(path)
        except httpx.HTTPError as e:
            raise ToolFailure(f"college unreachable: {e}", hint="retry once, then stop and report",
                              code="backend_unavailable") from None
        if r.status_code == 404:
            raise ToolFailure("no such lesson", hint="find ids with list_lessons or search_lessons", code="not_found")
        if r.status_code >= 400:
            raise ToolFailure(f"college returned HTTP {r.status_code}", code="backend_error")
        return r.json()

    async def search(self, qvec: str, k: int, track: str = "") -> list[dict]:
        sql = ("SELECT lesson_id, track, level, title, heading, body, 1 - (embedding <=> %s::vector) AS score "
               "FROM college_chunks " + ("WHERE track = %s " if track else "") +
               "ORDER BY embedding <=> %s::vector LIMIT %s")
        args = (qvec, track, qvec, k) if track else (qvec, qvec, k)
        try:
            async with await psycopg.AsyncConnection.connect(self.dsn) as con:
                cur = await con.execute(sql, args)
                cols = [d.name for d in cur.description]
                return [dict(zip(cols, row)) for row in await cur.fetchall()]
        except psycopg.Error as e:
            raise ToolFailure(f"search index unavailable: {e.__class__.__name__}",
                              hint="use list_lessons instead", code="backend_unavailable") from None

    async def ready(self) -> bool:
        await self.get("/api/catalog")
        return True

    async def aclose(self):
        await self.http.aclose()


def make_backend() -> CollegeBackend:
    return CollegeBackend(os.environ.get("COLLEGE_BASE", "https://college.scarletbeast.com"),
                          os.environ.get("RAG_DSN", "postgresql://beast:beast@localhost:55432/beast"))
