from beast_mcp import ToolFailure, backend, tool


@tool()
async def list_lessons(course: str) -> list[dict]:
    """Written lessons in one course (course = a key from list_courses), easiest first."""
    cat = await backend().get("/api/catalog")
    if course not in {t["key"] for t in cat["tracks"]}:
        raise ToolFailure(f"no course {course!r}", hint="use a key from list_courses", code="not_found")
    rows = [{k: l[k] for k in ("id", "level", "title", "summary")} for l in cat["lessons"] if l["track"] == course]
    return sorted(rows, key=lambda r: (r["level"], r["title"]))
