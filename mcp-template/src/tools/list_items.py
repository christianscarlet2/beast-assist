from beast_mcp import backend, tool


@tool()
async def list_items(q: str = "", limit: int = 25) -> list[dict]:
    """List items, optionally filtered by text q. Returns id and name only; use get_item for detail."""
    rows = await backend().get("/items", q=q, limit=min(limit, 100))
    return [{"id": r["id"], "name": r["name"]} for r in rows]
