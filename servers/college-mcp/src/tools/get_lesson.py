import re

from beast_mcp import ToolFailure, backend, tool


@tool()
async def get_lesson(lesson_id: str, include_body: bool = False) -> dict:
    """One lesson: title, difficulty, objectives, key terms and summary; include_body adds the full text."""
    if not re.fullmatch(r"[a-f0-9]{12}", lesson_id):
        raise ToolFailure(f"{lesson_id!r} is not a lesson id", hint="ids are 12 hex characters", code="invalid_input")
    v = (await backend().get(f"/api/lesson/{lesson_id}"))["lesson"]
    if v.get("status") != "ready":
        raise ToolFailure(f"lesson is {v.get('status')}", hint="it is still being written; try another", code="not_ready")
    c = v["content"]
    out = {"id": v["id"], "course": v["track"], "level": v["level"], "title": c.get("title"),
           "objectives": c.get("objectives", []), "key_terms": [t.get("term") for t in c.get("key_terms", [])],
           "summary": c.get("summary"), "url": f"https://college.scarletbeast.com/?lesson={v['id']}"}
    if include_body:
        out["body_md"] = c.get("body_md")
    return out
