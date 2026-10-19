"""@tool marks a function in src/tools/ as an MCP tool; backend() hands tools the server's one client."""
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable

_TOOLS: list["ToolSpec"] = []
_BACKENDS: dict[str, Any] = {}          # server name -> its one backend client
current_server: ContextVar[str] = ContextVar("beast_current_server", default="")


@dataclass
class ToolSpec:
    fn: Callable
    name: str
    write: bool          # changes the backend: needs the Tools.Write scope and an explicit allowed_tools entry
    tags: list[str] = field(default_factory=list)


def tool(write: bool = False, tags: list[str] | None = None, name: str | None = None):
    def wrap(fn):
        _TOOLS.append(ToolSpec(fn=fn, name=name or fn.__name__, write=write, tags=tags or []))
        return fn
    return wrap


def backend():
    """The backend of the server handling this call (one server per process in production)."""
    name = current_server.get()
    if name in _BACKENDS:
        return _BACKENDS[name]
    if len(_BACKENDS) == 1:
        return next(iter(_BACKENDS.values()))
    raise RuntimeError("backend not configured: create_app() sets it from src/backend.py")


def set_backend(server: str, client) -> None:
    _BACKENDS[server] = client


def collected() -> list[ToolSpec]:
    return list(_TOOLS)


def reset() -> None:
    _TOOLS.clear()
    _BACKENDS.clear()
