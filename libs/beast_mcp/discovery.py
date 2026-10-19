"""Auto-discovery: every public module in <server>/src/tools/ is imported; its @tool functions register.

Files are loaded by path under a per-server module prefix, so thirty servers can share one test run
without their `src` packages colliding."""
import importlib.util
import sys
from pathlib import Path

from . import registry


def _load(path: Path, modname: str):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


def discover(server_root: Path, server_name: str):
    """Import src/backend.py and src/tools/*.py; returns (backend module, [ToolSpec])."""
    prefix = "beast_srv_" + server_name.replace("-", "_")
    before = len(registry.collected())
    backend_mod = _load(server_root / "src" / "backend.py", f"{prefix}.backend")
    for path in sorted((server_root / "src" / "tools").glob("*.py")):
        if path.name.startswith("_"):
            continue
        _load(path, f"{prefix}.tools.{path.stem}")
    specs = registry.collected()[before:]
    names = [s.name for s in specs]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise RuntimeError(f"{server_name}: duplicate tool names {sorted(dupes)}")
    return backend_mod, specs
