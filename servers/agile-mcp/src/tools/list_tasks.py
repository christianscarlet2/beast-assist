from beast_mcp import backend, tool

FIELDS = ("key", "type", "title", "status", "priority", "points", "assignee", "labels", "due_date")


@tool()
async def list_tasks(project: str = "", status: str = "", q: str = "", label: str = "", limit: int = 25) -> list[dict]:
    """Search tasks. status: one or comma-separated (todo,in_progress). q: text in title or description.
    Done tasks are left out unless status asks for them. project defaults to the server's default project.
    Returns slim rows; use get_task for detail."""
    project = backend().project(project)
    params = {k: v for k, v in dict(project=project, status=status, q=q, label=label, limit=min(limit, 100)).items() if v}
    return [{k: t.get(k) for k in FIELDS} for t in await backend().call("GET", "/tasks", params=params)]
