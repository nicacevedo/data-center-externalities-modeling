#!/usr/bin/env python3
"""Preflight: freeze, crosswalk tests, weather, annual smoke-short. Fail loud."""
from __future__ import annotations

import subprocess
import sys

from common import PY, WORK_ROOT, atomic_write_json, set_threads, utcnow
from followup_common import FOLLOWUP, FOLLOWUP_DOCS, FOLLOWUP_LOGS


def run(args):
    print("+", " ".join(args), flush=True)
    r = subprocess.run(args, cwd=str(WORK_ROOT))
    if r.returncode != 0:
        raise SystemExit(r.returncode)


def main():
    set_threads()
    FOLLOWUP.mkdir(parents=True, exist_ok=True)
    FOLLOWUP_DOCS.mkdir(parents=True, exist_ok=True)
    FOLLOWUP_LOGS.mkdir(parents=True, exist_ok=True)
    py = str(PY)
    run([py, str(WORK_ROOT / "scripts" / "followup_freeze.py")])
    run(
        [
            py,
            "-m",
            "pytest",
            str(WORK_ROOT / "tests" / "test_followup_v1_crosswalk.py"),
            "-q",
            "--tb=short",
        ]
    )
    run([py, str(WORK_ROOT / "scripts" / "followup_crosswalk.py")])
    run([py, str(WORK_ROOT / "scripts" / "followup_weather.py")])
    run([py, str(WORK_ROOT / "scripts" / "followup_annual.py"), "--mode", "smoke-short", "--workers", "2"])
    atomic_write_json(
        FOLLOWUP / "preflight.json",
        {"status": "PASS", "timestamp_utc": utcnow()},
    )
    print("PREFLIGHT PASS", flush=True)


if __name__ == "__main__":
    main()
