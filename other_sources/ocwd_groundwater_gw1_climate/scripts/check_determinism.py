#!/usr/bin/env python3
"""Re-run model stages and verify canonical output hashes are unchanged."""

import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.gw1c import PROVENANCE, run_gw1c, sha256_file, write_json  # noqa: E402


if __name__ == "__main__":
    before = pd.read_csv(PROVENANCE / "GW1C_OUTPUT_HASHES.csv")
    before_map = dict(zip(before["path"], before["sha256"]))
    run_gw1c()
    after = pd.read_csv(PROVENANCE / "GW1C_OUTPUT_HASHES.csv")
    after_map = dict(zip(after["path"], after["sha256"]))
    mismatches = [path for path in sorted(set(before_map) | set(after_map)) if before_map.get(path) != after_map.get(path)]
    result = {
        "status": "PASS" if not mismatches else "FAIL",
        "comparison": "two complete deterministic model/report replays without re-downloading raw gridMET",
        "files_compared": len(set(before_map) | set(after_map)),
        "mismatches": mismatches,
        "manifest_sha256_after": sha256_file(PROVENANCE / "GW1C_OUTPUT_HASHES.csv"),
    }
    write_json(PROVENANCE / "DETERMINISTIC_REPLAY_STATUS.json", result)
    if mismatches:
        raise SystemExit(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))

