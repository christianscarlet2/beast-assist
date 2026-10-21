#!/usr/bin/env python3
"""validate_skills.py: is every SKILL.md well-formed? Run before audit and before upload.

Checks the shape only (no catalog): frontmatter fields and types, name == folder, semver, lifecycle,
allowed_tools written as <server>-mcp:<tool>, preflight inputs, aliases unique across skills, and the
body has Workflow and Errors sections with a numbered workflow."""
import re
import sys

from _skills import LIFECYCLES, TOOL_RE, all_skills, sections

REQUIRED = {"name": str, "description": str, "version": str, "lifecycle": str, "owner": str,
            "tags": list, "aliases": list, "allowed_tools": list, "preflight": list}


def check(meta: dict) -> list[str]:
    errs = []
    for k, t in REQUIRED.items():
        if k not in meta:
            errs.append(f"missing field {k!r}")
        elif not isinstance(meta[k], t):
            errs.append(f"{k!r} must be a {t.__name__}")
    if errs:
        return errs
    if meta["name"] != meta["_dir"]:
        errs.append(f"name {meta['name']!r} does not match its folder {meta['_dir']!r}")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", meta["name"]):
        errs.append("name must be kebab-case")
    if not re.fullmatch(r"\d+\.\d+\.\d+", meta["version"]):
        errs.append("version must be semver like 1.2.0")
    if meta["lifecycle"] not in LIFECYCLES:
        errs.append(f"lifecycle must be one of {LIFECYCLES}")
    if not 20 <= len(meta["description"]) <= 200:
        errs.append("description must be 20-200 characters (it is what agents read to pick a skill)")
    if not meta["allowed_tools"]:
        errs.append("allowed_tools is empty")
    for t in meta["allowed_tools"]:
        if not isinstance(t, str) or not TOOL_RE.match(t):
            errs.append(f"allowed_tools entry {t!r} must look like agile-mcp:list_tasks")
    if len(set(meta["allowed_tools"])) != len(meta["allowed_tools"]):
        errs.append("allowed_tools has duplicates")
    for i, p in enumerate(meta["preflight"]):
        if not isinstance(p, dict) or not p.get("name") or not p.get("description"):
            errs.append(f"preflight[{i}] needs name and description")
        elif p.get("required") and "default" in p:
            errs.append(f"preflight {p['name']!r} is required, so it cannot have a default")
        elif "from_request" in p and not isinstance(p["from_request"], bool):
            errs.append(f"preflight {p['name']!r}: from_request must be true or false")
    sec = sections(meta["body"])
    for s in ("workflow", "errors"):
        if s not in sec:
            errs.append(f"body is missing a '## {s.title()}' section")
    if "workflow" in sec and not re.search(r"^1\. ", sec["workflow"], re.M):
        errs.append("Workflow must be a numbered list")
    return errs


def main() -> int:
    seen_alias, failed = {}, 0
    results = all_skills()
    for path, meta in results:
        errs = [f"cannot parse: {meta}"] if isinstance(meta, Exception) else check(meta)
        if not isinstance(meta, Exception):
            for a in meta.get("aliases") or []:
                key = str(a).lower().strip()
                if key in seen_alias:
                    errs.append(f"alias {a!r} is also used by {seen_alias[key]}")
                seen_alias[key] = meta.get("name")
        name = path.parent.name
        if errs:
            failed += 1
            print(f"FAIL {name}")
            for e in errs:
                print(f"     - {e}")
        else:
            print(f"ok   {name}")
    print(f"\n{len(results) - failed}/{len(results)} skills valid")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
