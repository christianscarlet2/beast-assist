"""Shared by the skill scripts: read SKILL.md files and the live tool catalog."""
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "libs")]

LIFECYCLES = ("draft", "beta", "production", "deprecated")
TOOL_RE = re.compile(r"^[a-z0-9-]+-mcp:[a-z_][a-z0-9_]*$")


def load_skill(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError("no YAML frontmatter between --- lines")
    meta = yaml.safe_load(m.group(1)) or {}
    meta["body"] = m.group(2)
    meta["_dir"] = path.parent.name
    return meta


def all_skills(root: Path | None = None) -> list[tuple[Path, dict | Exception]]:
    out = []
    for p in sorted((root or ROOT / "skills").glob("*/SKILL.md")):
        try:
            out.append((p, load_skill(p)))
        except Exception as e:  # noqa: BLE001 - reported per file
            out.append((p, e))
    return out


def catalog() -> dict[str, dict]:
    """{"agile-mcp:list_tasks": {"write": False, ...}} discovered from servers/*/src/tools, no backends started."""
    from beast_mcp import registry
    from beast_mcp.discovery import discover
    cat = {}
    for srv in sorted((ROOT / "servers").glob("*-mcp")):
        registry.reset()
        _, specs = discover(srv, srv.name)
        for s in specs:
            cat[f"{srv.name}:{s.name}"] = {"write": s.write, "tags": s.tags}
    return cat


def sections(body: str) -> dict[str, str]:
    parts = re.split(r"^## +(.+)$", body, flags=re.M)
    return {parts[i].strip().lower(): parts[i + 1] for i in range(1, len(parts) - 1, 2)}
