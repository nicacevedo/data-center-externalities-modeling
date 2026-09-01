#!/usr/bin/env python3
"""Tiny fixed-seed Masanet eval for partition/environment preflight."""
from __future__ import annotations

import json
import os
import platform
import socket
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import DEMO_VECTOR, load_upstream, set_threads  # noqa: E402
from v2_common import MAN, atomic_write_json, utcnow  # noqa: E402


def main():
    set_threads()
    tag = os.environ.get("V2_PREFLIGHT_TAG", socket.gethostname())
    rec = {
        "timestamp_utc": utcnow(),
        "tag": tag,
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "executable": sys.executable,
        "python": sys.version.split()[0],
        "PYTHONNOUSERSITE": os.environ.get("PYTHONNOUSERSITE"),
        "partition": os.environ.get("SLURM_JOB_PARTITION"),
        "job_id": os.environ.get("SLURM_JOB_ID"),
    }
    try:
        import numpy, scipy, sklearn, pandas

        rec["versions"] = {
            "numpy": numpy.__version__,
            "scipy": scipy.__version__,
            "sklearn": sklearn.__version__,
            "pandas": pandas.__version__,
            "scipy_file": scipy.__file__,
        }
        import CoolProp

        rec["versions"]["CoolProp"] = CoolProp.__version__
        mod, notes = load_upstream()
        rec["cop_notes"] = notes
        np.random.seed(2025)
        pue, wue = mod.PUE_WUE_WE_Chiller_Colo(DEMO_VECTOR)
        rec["pue"] = float(pue)
        rec["wue"] = float(wue)
        rec["status"] = "PASS"
    except Exception as e:
        rec["status"] = "FAIL"
        rec["error"] = f"{type(e).__name__}: {e}"
    dest = MAN / f"preflight_{tag}.json"
    atomic_write_json(dest, rec)
    print(json.dumps({k: rec.get(k) for k in ("status", "tag", "pue", "wue", "versions", "error")}, indent=2, default=str))
    if rec.get("status") != "PASS":
        sys.exit(2)


if __name__ == "__main__":
    main()
