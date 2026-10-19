from beast_mcp import tool


@tool(tags=["guide"])
def bootstrap_guide() -> dict:
    """Call first. How this server's tools fit together."""
    return {
        "server": "college-mcp",
        "backend": "Scarlet College: self-writing courses; each lesson has a difficulty 1-10",
        "start_with": "list_courses; then search_lessons(query) to find material on a topic",
        "ids": "lesson ids are 12 hex characters; get_lesson takes one",
        "search": "search_lessons is semantic (meaning, not keywords): ask in plain words",
        "read_only": True,
    }
