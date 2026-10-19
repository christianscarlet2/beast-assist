from beast_mcp import backend, tool


@tool()
async def list_courses() -> list[dict]:
    """The college's courses: key, name, how many lessons are written, and the syllabus if it has one."""
    cat = await backend().get("/api/catalog")
    n = {}
    for l in cat["lessons"]:
        n[l["track"]] = n.get(l["track"], 0) + 1
    return [{"key": t["key"], "name": t["name"], "lessons": n.get(t["key"], 0), "syllabus": t.get("syllabus") or []}
            for t in cat["tracks"]]
