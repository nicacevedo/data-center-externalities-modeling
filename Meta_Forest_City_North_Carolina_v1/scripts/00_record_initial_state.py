#!/usr/bin/env python3
"""Record repository HEAD/status and frozen Prineville/CPU/H100/ESIF hashes. No commit."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FC / "src"))
from hashes import sha256_file, write_json  # noqa: E402

REQUESTED_BASELINE = "f9eaab96d7fed5419450ce3163a1b13e555aa39b"

EXPECTED = {
    "prineville_structural_v1.py": "f9649c489196cdc3e617f5b28574334aaaace5a94e7ade5ce461f6da22809a6a",
    "prineville_psychrometrics.py": "c10e1487a00ce32023bf3b630f915b2fe9ba303917951ff5f5bcbec3a3aafd30",
    "prineville_graybox.py": "8275ca5bfc23042e3af19b72f2adb260304ac95d692d0b3ecbcb526b020f0609",
    "prineville_architecture_states.yaml": "1f87a1846aa8254c758ab11e3bd9b6f639e6c64bc551c36bcf8201bd65e78604",
    "PRINEVILLE_STRUCTURAL_REFERENCE_V1_FREEZE.json": "decd095f59cc2249eee66d5b94ad30d30a53555eadbec3358bbb9aa80caaa81d",
    "OCP_REFERENCE_CONTROL_CONTRACT.json": "b320525efd2af8b553bbc933b6740605a2ddcecffca84677b8ba0ae4df316e4e",
    "Q2_2012_KRDM_hourly.parquet": "87c0beaf1f8223ebb9f4d02ff13b9efd9d2286aaddfec0a3cce9af4c4279d925",
    "FINAL_KESTREL_CPU_STATUS.json": "1f57b210a63d375ce8eff7d5043756ffe6efe04e8a408bf9429bfd10096528d9",
    "H100_COMPUTE_FINAL_FREEZE.json": "a620d649a932f2388aa2f35bac2730eb75fe1dc74529668de4f30ee814600076",
    "ESIF_HEAT_WATER_RESULT_FREEZE.json": "4e01139dd9365f62824ac00ff944468839e7873e47a5cea3df4714854af1b02c",
}

PATHS = {
    "prineville_structural_v1.py": ROOT / "Meta_Prineville_Oregon_v3/src/prineville_structural_v1.py",
    "prineville_psychrometrics.py": ROOT / "Meta_Prineville_Oregon_v3/src/prineville_psychrometrics.py",
    "prineville_ocp_controller.py": ROOT / "Meta_Prineville_Oregon_v3/src/prineville_ocp_controller.py",
    "prineville_graybox.py": ROOT / "Meta_Prineville_Oregon_v3/src/prineville_graybox.py",
    "prineville_architecture.py": ROOT / "Meta_Prineville_Oregon_v3/src/prineville_architecture.py",
    "prineville_architecture_states.yaml": ROOT / "Meta_Prineville_Oregon_v3/config/prineville_architecture_states.yaml",
    "PRINEVILLE_STRUCTURAL_REFERENCE_V1_FREEZE.json": ROOT
    / "Meta_Prineville_Oregon_v3/outputs/structural_revision_v1/PRINEVILLE_STRUCTURAL_REFERENCE_V1_FREEZE.json",
    "OCP_REFERENCE_CONTROL_CONTRACT.json": ROOT
    / "Meta_Prineville_Oregon_v3/outputs/structural_revision_v1/OCP_REFERENCE_CONTROL_CONTRACT.json",
    "PRN1_Q2_2012_PREBENCHMARK_FREEZE.json": ROOT
    / "Meta_Prineville_Oregon_v3/outputs/prn1_q2_2012_public_validation_v1/PRN1_Q2_2012_PREBENCHMARK_FREEZE.json",
    "PREBENCHMARK_OUTPUT_FREEZE.json": ROOT
    / "Meta_Prineville_Oregon_v3/outputs/prn1_q2_2012_public_validation_v1/PREBENCHMARK_OUTPUT_FREEZE.json",
    "Q2_2012_KRDM_hourly.parquet": ROOT
    / "Meta_Prineville_Oregon_v3/outputs/prn1_q2_2012_public_validation_v1/weather/Q2_2012_KRDM_hourly.parquet",
    "FINAL_KESTREL_CPU_STATUS.json": ROOT / "other_sources/nlr_esif_fullstack/analysis/FINAL_KESTREL_CPU_STATUS.json",
    "H100_COMPUTE_FINAL_FREEZE.json": ROOT
    / "other_sources/nlr_esif_fullstack/genai_h100/manifests/H100_COMPUTE_FINAL_FREEZE.json",
    "ESIF_HEAT_WATER_RESULT_FREEZE.json": ROOT
    / "other_sources/nlr_esif_fullstack/heat_rejection_water/manifests/ESIF_HEAT_WATER_RESULT_FREEZE.json",
}


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main() -> None:
    hashes = {}
    mismatches = []
    for name, path in PATHS.items():
        rec = {"path": str(path), "exists": path.exists()}
        if path.exists():
            rec["sha256"] = sha256_file(path)
            rec["bytes"] = path.stat().st_size
            if name in EXPECTED and rec["sha256"] != EXPECTED[name]:
                mismatches.append(name)
                rec["expected"] = EXPECTED[name]
                rec["match"] = False
            elif name in EXPECTED:
                rec["match"] = True
        hashes[name] = rec

    sub = subprocess.run(["git", "submodule", "status"], cwd=ROOT, text=True, capture_output=True)
    dirty_sub = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    ).stdout
    state = {
        "pass": "forest_city_north_carolina_public_validation_v1",
        "utc": datetime.now(timezone.utc).isoformat(),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "HEAD": git("rev-parse", "HEAD"),
        "requested_public_baseline": REQUESTED_BASELINE,
        "HEAD_matches_requested_baseline": git("rev-parse", "HEAD") == REQUESTED_BASELINE,
        "git_status_porcelain": dirty_sub,
        "git_submodule_status": (sub.stdout or sub.stderr or "no submodules"),
        "hashes": hashes,
        "hash_mismatches": mismatches,
        "prineville_must_remain_unchanged": True,
        "no_commit": True,
        "MODEL_CALIBRATED": "NO",
        "notes": [
            "Forest City is a new top-level module, not a Prineville calibration.",
            "Do not alter structural-reference-v1, PRN1 parameters, CPU/H100, or ESIF.",
        ],
    }
    out = FC / "outputs" / "INITIAL_STATE.json"
    write_json(out, state)
    print(json.dumps({"wrote": str(out), "HEAD": state["HEAD"], "mismatches": mismatches}, indent=2))
    if mismatches:
        raise SystemExit(f"FROZEN HASH MISMATCH: {mismatches}")


if __name__ == "__main__":
    main()
