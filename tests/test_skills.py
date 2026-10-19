"""The skill gates themselves: the repo's skills pass, and broken skills are caught."""
import subprocess
import sys
from pathlib import Path

import validate_skills
from _skills import catalog, load_skill

import audit_skill_config

ROOT = Path(__file__).resolve().parents[1]

GOOD = """---
name: demo-skill
description: A demo skill used to test the validator end to end.
version: 1.0.0
lifecycle: draft
owner: test@example.com
tags: [demo]
aliases: [demo]
allowed_tools: [agile-mcp:list_tasks]
preflight:
  - {name: project, description: key, required: false, default: SB}
---
# Demo

## Workflow

1. Call `agile-mcp:list_tasks`.

## Errors

| Error | Meaning | Do this |
| --- | --- | --- |
"""


def write(tmp_path, text, name="demo-skill"):
    d = tmp_path / name
    d.mkdir()
    (d / "SKILL.md").write_text(text)
    return load_skill(d / "SKILL.md")


def test_repo_skills_validate_and_audit():
    for script in ("validate_skills.py", "audit_skill_config.py"):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / script)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr


def test_good_skill_has_no_errors(tmp_path):
    assert validate_skills.check(write(tmp_path, GOOD)) == []


def test_validator_catches_shape_errors(tmp_path):
    bad = GOOD.replace("version: 1.0.0", "version: one").replace("agile-mcp:list_tasks]", "list_tasks]") \
              .replace("## Workflow", "## Steps")
    errs = " ".join(validate_skills.check(write(tmp_path, bad)))
    assert "semver" in errs and "agile-mcp:list_tasks" in errs and "Workflow" in errs


def test_name_must_match_folder(tmp_path):
    assert any("does not match its folder" in e for e in validate_skills.check(write(tmp_path, GOOD, "other")))


def test_audit_catches_unknown_and_unused_write_tools(tmp_path):
    meta = write(tmp_path, GOOD.replace("allowed_tools: [agile-mcp:list_tasks]",
                                        "allowed_tools: [agile-mcp:list_tasks, agile-mcp:create_task, agile-mcp:nope]"))
    found = audit_skill_config.audit(meta, catalog(), set())
    msgs = [m for lvl, m in found if lvl == "FAIL"]
    assert any("agile-mcp:nope is not provided" in m for m in msgs)
    assert any("write tool agile-mcp:create_task is granted but the Workflow never calls it" in m for m in msgs)


def test_production_skill_needs_an_eval(tmp_path):
    meta = write(tmp_path, GOOD.replace("lifecycle: draft", "lifecycle: production"))
    assert ("FAIL", "production skill has no eval scenario in evals/scenarios") in audit_skill_config.audit(meta, catalog(), set())
