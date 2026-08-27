#!/usr/bin/env python3
"""Run adapter unit tests after the annual gate. Exit nonzero on failure."""
from __future__ import annotations

import json
import subprocess
import sys

from common import PY, WORK_ROOT, atomic_write_json, set_threads, utcnow
from followup_common import FOLLOWUP


def main():
    set_threads()
    gate = json.loads((FOLLOWUP / "MASANET_ANNUAL_CLOSURE_STATUS.json").read_text())
    if not gate.get("proceed_to_adapter"):
        print("gate forbids adapter")
        sys.exit(2)
    r = subprocess.run(
        [
            str(PY),
            "-m",
            "pytest",
            str(WORK_ROOT / "tests" / "test_followup_v1_adapter.py"),
            "-q",
            "--tb=short",
        ],
        cwd=str(WORK_ROOT),
    )
    out = {
        "status": "PASS" if r.returncode == 0 else "FAIL",
        "timestamp_utc": utcnow(),
        "pytest_returncode": r.returncode,
        "interpretation": (
            "Adapter is a homogeneous intensity map: P_fac = P_IT * PUE(w,theta), "
            "W_conditioning = P_IT * WUE(w,theta). Chiller_load is a scenario parameter. "
            "No groundwater/source names."
        ),
    }
    atomic_write_json(FOLLOWUP / "adapter_status.json", out)
    print(json.dumps(out, indent=2))
    if r.returncode != 0:
        sys.exit(2)


if __name__ == "__main__":
    main()
