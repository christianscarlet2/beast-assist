from beast_mcp import backend, tool


@tool()
async def get_task(key: str) -> dict:
    """One task in full: description, comments and history. key looks like SB-12."""
    return await backend().call("GET", f"/tasks/{backend().task_key(key)}")
