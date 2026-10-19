#!/usr/bin/env python3
"""wait_ready.py URL... : poll readiness endpoints until all answer 200 (or 180 s pass)."""
import sys
import time

import httpx

deadline = time.time() + 180
pending = list(sys.argv[1:])
while pending and time.time() < deadline:
    for u in list(pending):
        try:
            if httpx.get(u, timeout=3).status_code == 200:
                print("ready", u)
                pending.remove(u)
        except httpx.HTTPError:
            pass
    time.sleep(2)
sys.exit(f"not ready: {pending}" if pending else 0)
