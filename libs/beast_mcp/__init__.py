"""beast_mcp: the shared runtime every Beast Assist MCP tool server is built on.

A server is a folder with src/backend.py (one backend client) and src/tools/*.py (one tool per file).
create_app() discovers the tools, wraps every call in auth -> policy -> tracing, and serves MCP over
streamable HTTP next to /healthz and /readyz.
"""
from .registry import tool, backend
from .errors import ToolFailure
from .app import create_app

__all__ = ["tool", "backend", "ToolFailure", "create_app"]
