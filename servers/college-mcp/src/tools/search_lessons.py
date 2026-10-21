import asyncio

from beast_rag import embed, vec

from beast_mcp import backend, tool


@tool(tags=["rag"])
async def search_lessons(query: str, course: str = "", k: int = 5) -> list[dict]:
    """Semantic search across every written lesson. Returns the best-matching passages with their lesson id,
    course, difficulty, a 0-1 relevance score and the lesson's url (cite that url; never build one); open one
    with get_lesson."""
    qv = (await asyncio.to_thread(embed, [query], "query"))[0]
    rows = await backend().search(vec(qv), max(1, min(k, 10)), course)
    return [{"lesson_id": r["lesson_id"], "course": r["track"], "level": r["level"], "title": r["title"],
             "section": r["heading"], "score": round(float(r["score"]), 3), "passage": r["body"][:600],
             "url": f"https://college.scarletbeast.com/?lesson={r['lesson_id']}"} for r in rows]
