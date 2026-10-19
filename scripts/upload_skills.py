#!/usr/bin/env python3
"""upload_skills.py: publish skills to the Skills Registry (PUT /skills/{name}).

Refuses to publish anything that fails validate_skills.py or audit_skill_config.py. Authenticates with
the client-credentials flow as the publisher app (Skills.Publish role).

  python scripts/upload_skills.py [skill ...]      default: every skill
Env: REGISTRY_URL, TOKEN_URL, PUBLISH_CLIENT_ID, PUBLISH_CLIENT_SECRET, AUTH_AUDIENCE"""
import hashlib
import os
import subprocess
import sys

import httpx

from _skills import ROOT, all_skills


def token() -> str:
    r = httpx.post(os.environ.get("TOKEN_URL", "http://localhost:8400/beast-dev-tenant/oauth2/v2.0/token"), data={
        "grant_type": "client_credentials",
        "client_id": os.environ.get("PUBLISH_CLIENT_ID", "beast-publisher"),
        "client_secret": os.environ.get("PUBLISH_CLIENT_SECRET", "dev-publisher-secret"),
        "scope": os.environ.get("AUTH_AUDIENCE", "api://beast-assist") + "/.default"}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def main(names: list[str]) -> int:
    for gate in ("validate_skills.py", "audit_skill_config.py"):
        if subprocess.run([sys.executable, str(ROOT / "scripts" / gate)], capture_output=True).returncode:
            print(f"refusing to upload: {gate} fails (run it to see why)")
            return 1
    base = os.environ.get("REGISTRY_URL", "http://localhost:8410").rstrip("/")
    h = {"Authorization": f"Bearer {token()}"}
    for path, meta in all_skills():
        if names and meta["name"] not in names:
            continue
        doc = {k: v for k, v in meta.items() if not k.startswith("_")}
        doc["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        r = httpx.put(f"{base}/skills/{meta['name']}", json=doc, headers=h, timeout=10)
        print(f"{r.status_code} {meta['name']} {meta['version']} ({meta['lifecycle']}): {r.json().get('status', r.text)}")
        if r.status_code >= 400:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
