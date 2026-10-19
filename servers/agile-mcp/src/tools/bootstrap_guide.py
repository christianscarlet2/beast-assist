from beast_mcp import tool


@tool(tags=["guide"])
def bootstrap_guide() -> dict:
    """Call first. How this server's tools fit together and the board's vocabulary."""
    return {
        "server": "agile-mcp",
        "backend": "Warden agile board (projects, sprints, tasks keyed like SB-12)",
        "start_with": "list_projects, then list_tasks(project=...)",
        "task_keys": "KEY-N, e.g. SB-12; get_task takes one",
        "statuses": ["backlog", "todo", "in_progress", "review", "done"],
        "types": ["story", "task", "bug", "spike", "epic"],
        "priorities": ["highest", "high", "medium", "low", "lowest"],
        "writes": "create_task and add_comment change the board; only call them when the skill's workflow says so",
    }
