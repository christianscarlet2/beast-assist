#!/usr/bin/env python3
"""audit_skill_config.py: does each skill's scope match the real tool catalog? Must pass with no FAIL
before a skill is promoted to production.

FAIL  an allowed tool that no server provides
FAIL  a write tool granted but never named in the Workflow (a write grant nobody uses is an open door)
FAIL  a production skill with no eval scenario in evals/scenarios
FAIL  a production skill that grants write tools but is not tagged `writes`
WARN  a read tool granted but never named in the Workflow (trim it: least privilege)
WARN  a skill spanning more than three servers (split it)"""
import sys

import yaml

from _skills import ROOT, all_skills, catalog, sections


def audit(meta: dict, cat: dict, eval_skills: set) -> list[tuple[str, str]]:
    out = []
    workflow = sections(meta["body"]).get("workflow", "")
    for t in meta["allowed_tools"]:
        if t not in cat:
            out.append(("FAIL", f"{t} is not provided by any server"))
            continue
        used = t in workflow
        if cat[t]["write"] and not used:
            out.append(("FAIL", f"write tool {t} is granted but the Workflow never calls it"))
        elif not used and "bootstrap_guide" not in t:
            out.append(("WARN", f"{t} is granted but the Workflow never calls it"))
    writes = [t for t in meta["allowed_tools"] if cat.get(t, {}).get("write")]
    if meta["lifecycle"] == "production":
        if meta["name"] not in eval_skills:
            out.append(("FAIL", "production skill has no eval scenario in evals/scenarios"))
        if writes and "writes" not in meta["tags"]:
            out.append(("FAIL", "production skill grants write tools but is not tagged `writes`"))
    servers = {t.split(":")[0] for t in meta["allowed_tools"]}
    if len(servers) > 3:
        out.append(("WARN", f"spans {len(servers)} servers; consider splitting"))
    return out


def main() -> int:
    cat = catalog()
    eval_skills = set()
    for f in (ROOT / "evals" / "scenarios").glob("*.yaml"):
        for sc in yaml.safe_load(f.read_text()) or []:
            eval_skills.add(sc.get("skill"))
    fails = 0
    for path, meta in all_skills():
        if isinstance(meta, Exception):
            print(f"FAIL {path.parent.name}: unparseable (run validate_skills.py)")
            fails += 1
            continue
        findings = audit(meta, cat, eval_skills)
        bad = [f for f in findings if f[0] == "FAIL"]
        fails += bool(bad)
        print(f"{'FAIL' if bad else 'pass'} {meta['name']} ({meta['lifecycle']}, {len(meta['allowed_tools'])} tools)")
        for lvl, msg in findings:
            print(f"     {lvl}: {msg}")
    print(f"\ncatalog: {len(cat)} tools across {len({k.split(':')[0] for k in cat})} servers")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
