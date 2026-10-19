"""Skills Registry: the PostgreSQL-backed source of truth that agents load skills from.

    GET  /skills                    list (filter ?tag= &lifecycle=)
    GET  /skills/{name}             one skill in full, workflow body included
    GET  /resolve?q=                pick a skill from a user's words (alias, then name, then description)
    PUT  /skills/{name}             publish (Entra token with the Skills.Publish role); a version is immutable
    GET  /bundles/beast.tar.gz      OPA bundle: data.beast.skills = {name: {allowed_tools, lifecycle}}
    GET  /healthz, /readyz
"""
import hashlib
import io
import json
import os
import re
import tarfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field

from beast_mcp.auth import AuthError, TokenVerifier
from beast_mcp.settings import Settings

DSN = os.environ.get("REGISTRY_DSN", "postgresql://beast:beast@localhost:55432/beast")
LIFECYCLES = {"draft", "beta", "production", "deprecated"}
pool = AsyncConnectionPool(DSN, open=False, kwargs={"row_factory": dict_row})
verifier = TokenVerifier(Settings.load("skills-registry"))


@asynccontextmanager
async def lifespan(_app):
    await pool.open()
    async with pool.connection() as con:
        await con.execute((Path(__file__).parent / "schema.sql").read_text())
    yield
    await pool.close()


app = FastAPI(title="skills-registry", lifespan=lifespan)


class Preflight(BaseModel):
    name: str
    description: str
    required: bool = False
    default: str | None = None


class SkillDoc(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    lifecycle: str
    description: str
    owner: str
    tags: list[str] = []
    aliases: list[str] = []
    allowed_tools: list[str] = Field(min_length=1)
    preflight: list[Preflight] = []
    body: str
    sha256: str


def publisher(authorization: str | None = Header(None)) -> dict:
    try:
        claims = verifier.verify(authorization)
    except AuthError as e:
        raise HTTPException(401, str(e)) from None
    if "Skills.Publish" not in claims["permissions"]:
        raise HTTPException(403, "token lacks the Skills.Publish role")
    return claims


SUMMARY = "name, version, lifecycle, description, owner, tags, aliases, allowed_tools, updated_at"


@app.get("/skills")
async def list_skills(tag: str = "", lifecycle: str = ""):
    sql, args = f"SELECT {SUMMARY} FROM skills WHERE true", []
    if tag:
        sql += " AND tags ? %s"
        args.append(tag)
    if lifecycle:
        sql += " AND lifecycle = %s"
        args.append(lifecycle)
    async with pool.connection() as con:
        return await (await con.execute(sql + " ORDER BY name", args)).fetchall()


@app.get("/skills/{name}")
async def get_skill(name: str):
    async with pool.connection() as con:
        row = await (await con.execute("SELECT * FROM skills WHERE name = %s", (name,))).fetchone()
    if not row:
        raise HTTPException(404, f"no skill {name!r}")
    return row


@app.get("/resolve")
async def resolve(q: str):
    """Alias match first (the user's own words), then a name match, then description keywords."""
    text = q.lower()
    async with pool.connection() as con:
        rows = await (await con.execute(
            f"SELECT {SUMMARY} FROM skills WHERE lifecycle <> 'deprecated'")).fetchall()
    best, score = None, 0
    words = set(re.findall(r"[a-z]+", text))
    for r in rows:
        s = 0
        if any(a.lower() in text for a in r["aliases"]):
            s = 100 + max(len(a) for a in r["aliases"] if a.lower() in text)
        elif r["name"].replace("-", " ") in text:
            s = 50
        else:
            s = len(words & set(re.findall(r"[a-z]+", r["description"].lower())))
        if s > score:
            best, score = r, s
    if not best or score < 2:
        raise HTTPException(404, "no skill matches; list them with GET /skills")
    return {"skill": best, "score": score}


@app.put("/skills/{name}")
async def publish(name: str, doc: SkillDoc, claims: dict = Depends(publisher)):
    if doc.name != name:
        raise HTTPException(422, "name in the path and the document differ")
    if doc.lifecycle not in LIFECYCLES:
        raise HTTPException(422, f"lifecycle must be one of {sorted(LIFECYCLES)}")
    data = doc.model_dump()
    who = claims.get("azp") or claims.get("sub")
    async with pool.connection() as con:
        prior = await (await con.execute("SELECT sha256 FROM skill_versions WHERE name=%s AND version=%s",
                                         (name, doc.version))).fetchone()
        if prior and prior["sha256"] != doc.sha256:
            raise HTTPException(409, f"{name} {doc.version} is already published with different content; bump the version")
        if prior:
            return {"status": "unchanged"}
        await con.execute("INSERT INTO skill_versions (name, version, sha256, doc, published_by) VALUES (%s,%s,%s,%s,%s)",
                          (name, doc.version, doc.sha256, Jsonb(data), who))
        await con.execute("""
            INSERT INTO skills (name, version, lifecycle, description, owner, tags, aliases, allowed_tools,
                                preflight, body, sha256, published_by, updated_at)
            VALUES (%(name)s, %(version)s, %(lifecycle)s, %(description)s, %(owner)s, %(tags)s, %(aliases)s,
                    %(allowed_tools)s, %(preflight)s, %(body)s, %(sha256)s, %(who)s, now())
            ON CONFLICT (name) DO UPDATE SET version=EXCLUDED.version, lifecycle=EXCLUDED.lifecycle,
              description=EXCLUDED.description, owner=EXCLUDED.owner, tags=EXCLUDED.tags, aliases=EXCLUDED.aliases,
              allowed_tools=EXCLUDED.allowed_tools, preflight=EXCLUDED.preflight, body=EXCLUDED.body,
              sha256=EXCLUDED.sha256, published_by=EXCLUDED.published_by, updated_at=now()""",
            {**data, "tags": Jsonb(data["tags"]), "aliases": Jsonb(data["aliases"]),
             "allowed_tools": Jsonb(data["allowed_tools"]), "preflight": Jsonb(data["preflight"]), "who": who})
    return {"status": "published"}


@app.get("/bundles/beast.tar.gz")
async def bundle(if_none_match: str | None = Header(None)):
    """OPA polls this; the ETag is the content hash, so an unchanged registry costs a 304."""
    async with pool.connection() as con:
        rows = await (await con.execute("SELECT name, lifecycle, allowed_tools FROM skills ORDER BY name")).fetchall()
    data = {"skills": {r["name"]: {"lifecycle": r["lifecycle"], "allowed_tools": r["allowed_tools"]} for r in rows}}
    raw = json.dumps(data, sort_keys=True).encode()
    etag = hashlib.sha256(raw).hexdigest()[:32]
    if if_none_match and if_none_match.strip('"') == etag:
        return Response(status_code=304)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, content in (("/beast/data.json", raw),
                              ("/.manifest", json.dumps({"revision": etag, "roots": ["beast/skills"]}).encode())):
            info = tarfile.TarInfo(path.lstrip("/"))
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return Response(buf.getvalue(), media_type="application/gzip", headers={"ETag": f'"{etag}"'})


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/readyz")
async def readyz():
    try:
        async with pool.connection() as con:
            await con.execute("SELECT 1")
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return Response(json.dumps({"ok": False, "db": str(e)}), status_code=503, media_type="application/json")
