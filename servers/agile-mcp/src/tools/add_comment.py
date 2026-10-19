from beast_mcp import backend, tool


@tool(write=True)
async def add_comment(key: str, body: str) -> dict:
    """Comment on a task (key like SB-12). Use it to record why something changed."""
    c = await backend().call("POST", f"/tasks/{key}/comments", {"body": body})
    return {"key": key, "comment_id": c.get("id")}
