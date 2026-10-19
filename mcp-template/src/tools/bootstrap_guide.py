from beast_mcp import tool


@tool(tags=["guide"])
def bootstrap_guide() -> dict:
    """Call first. What template-mcp covers and which tool to start with."""
    return {"server": "template-mcp", "backend": "describe it", "start_with": "list_items"}
