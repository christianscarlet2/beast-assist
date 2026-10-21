from beast_mcp import backend, tool


@tool()
async def list_projects() -> list[dict]:
    """List the projects this server may use: key, name and task counts."""
    return [{k: p.get(k) for k in ("key", "name", "description", "tasks_count")} for p in backend().visible(await backend().call("GET", "/projects"))]
