from beast_mcp import ToolFailure, backend, tool


@tool()
async def get_task(key: str) -> dict:
    """One task in full: description, comments and history. key looks like SB-12."""
    if "-" not in key:
        raise ToolFailure(f"{key!r} is not a task key", hint="pass a key like SB-12", code="invalid_input")
    return await backend().call("GET", f"/tasks/{key}")
