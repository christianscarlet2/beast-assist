#!/usr/bin/env python3
"""new_server.py <name>-mcp: start a new single-platform server from mcp-template/."""
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if len(sys.argv) != 2 or not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*-mcp", sys.argv[1]):
    sys.exit("usage: new_server.py <name>-mcp   (kebab-case, ending in -mcp)")
name = sys.argv[1]
dest = ROOT / "servers" / name
if dest.exists():
    sys.exit(f"{dest} already exists")
shutil.copytree(ROOT / "mcp-template", dest)
for p in dest.rglob("*"):
    if p.is_file():
        p.write_text(p.read_text().replace("template-mcp", name))
print(f"created servers/{name}: edit src/backend.py, then add one file per tool in src/tools/")
