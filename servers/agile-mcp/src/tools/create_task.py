from beast_mcp import ToolFailure, backend, tool

TYPES = {"story", "task", "bug", "spike", "epic"}
PRIORITIES = {"highest", "high", "medium", "low", "lowest"}


@tool(write=True)
async def create_task(title: str, project: str = "SB", type: str = "task", description: str = "",
                      priority: str = "medium", labels: str = "") -> dict:
    """Create a backlog task. labels: comma-separated. Returns the new task's key."""
    if type not in TYPES:
        raise ToolFailure(f"type {type!r} is not one of {sorted(TYPES)}", code="invalid_input")
    if priority not in PRIORITIES:
        raise ToolFailure(f"priority {priority!r} is not one of {sorted(PRIORITIES)}", code="invalid_input")
    body = {"title": title.strip(), "project": project, "type": type, "priority": priority}
    if description:
        body["description"] = description
    if labels:
        body["labels"] = labels
    t = await backend().call("POST", "/tasks", body)
    return {"key": t.get("key"), "title": t.get("title"), "status": t.get("status")}
