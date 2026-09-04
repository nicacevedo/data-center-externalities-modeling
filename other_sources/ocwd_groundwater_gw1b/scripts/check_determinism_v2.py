#!/usr/bin/env python3
"""Replay the additive waiting/readiness outputs without rescanning WRMS."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from freeze_gw1b_v2 import freeze  # noqa: E402
from src.gw1b_v2 import PROVENANCE, sha256_file, write_json  # noqa: E402


if __name__ == "__main__":
    before = pd.read_csv(PROVENANCE / "GW1B_V2_OUTPUT_HASHES.csv")
    before_map = dict(zip(before["path"], before["sha256"]))
    freeze()
    after = pd.read_csv(PROVENANCE / "GW1B_V2_OUTPUT_HASHES.csv")
    after_map = dict(zip(after["path"], after["sha256"]))
    mismatches = [path for path in sorted(set(before_map) | set(after_map)) if before_map.get(path) != after_map.get(path)]
    result = {
        "status": "PASS" if not mismatches else "FAIL",
        "scope": "canonical GW1B v2 waiting/readiness outputs; WRMS availability scan not rerun",
        "files_compared": len(set(before_map) | set(after_map)),
        "mismatches": mismatches,
        "output_manifest_sha256": sha256_file(PROVENANCE / "GW1B_V2_OUTPUT_HASHES.csv"),
        "second_WRMS_scan_performed": False,
    }
    write_json(PROVENANCE / "GW1B_V2_DETERMINISTIC_REPLAY_STATUS.json", result)
    print(json.dumps(result, indent=2))
    if mismatches:
        raise SystemExit(1)

