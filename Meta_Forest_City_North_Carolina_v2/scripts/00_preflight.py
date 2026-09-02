#!/usr/bin/env python3
"""Step 0: repository preflight and upstream hash freeze. Read-only on v1/Prineville."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hashes import sha256_file, write_json  # noqa: E402
from fc2_paths import FC2, PRN, REPO, V1  # noqa: E402

EXPECTED = {
    "fc_controller": "99ecc213fa181ab1fe7144087da5874b0a8f3f79478a6a8b5aed83fe0ea77c78",
    "fc_structural": "085a893cd63665b37d027877e9d80efbc99489a6c813a9f8da150e41a529568d",
    "fc_control_contract": "56d3ef12b0ab3584886892a3283f068ebe7bcfc0adc827543dc6b8910da450c2",
    "fc_airflow_contract": "f1cdc03bea8f5103e8951c6fbef7e965d16248e511fd4ad4874e19d5054ddc37",
    "prn_structural_v1": "f9649c489196cdc3e617f5b28574334aaaace5a94e7ade5ce461f6da22809a6a",
    "prn_psychrometrics": "c10e1487a00ce32023bf3b630f915b2fe9ba303917951ff5f5bcbec3a3aafd30",
    "fc_weather_parquet": "f87a2e61120cf2d8e3117ff20e838567d0f8525a650a7fdaad221f9b3044e1d9",
    "prn_graybox": "8275ca5bfc23042e3af19b72f2adb260304ac95d692d0b3ecbcb526b020f0609",
    "prn_registry": "1f87a1846aa8254c758ab11e3bd9b6f639e6c64bc551c36bcf8201bd65e78604",
    "cpu": "1f57b210a63d375ce8eff7d5043756ffe6efe04e8a408bf9429bfd10096528d9",
    "h100": "a620d649a932f2388aa2f35bac2730eb75fe1dc74529668de4f30ee814600076",
    "esif": "4e01139dd9365f62824ac00ff944468839e7873e47a5cea3df4714854af1b02c",
}

PATHS = {
    "fc_controller": V1 / "src/forest_city_controller.py",
    "fc_structural": V1 / "src/forest_city_structural_reference_v1.py",
    "fc_control_contract": V1 / "config/FOREST_CITY_REFERENCE_CONTROL_CONTRACT.json",
    "fc_airflow_contract": V1 / "config/FOREST_CITY_AIRFLOW_BOUNDARY_CONTRACT.json",
    "fc_validation_status": V1 / "outputs/FOREST_CITY_PUBLIC_VALIDATION_STATUS.json",
    "fc_validation_freeze": V1 / "outputs/FOREST_CITY_PUBLIC_VALIDATION_FREEZE.json",
    "fc_event_validation": V1 / "outputs/control_validation/HISTORICAL_EVENT_VALIDATION.json",
    "fc_summer_dx": V1 / "outputs/control_validation/SUMMER_2012_DX_VALIDATION.json",
    "fc_weather_qa": V1 / "outputs/weather/FOREST_CITY_2012_WEATHER_QA.json",
    "fc_weather_parquet": V1 / "data/processed/forest_city_weather_2012_hourly.parquet",
    "prn_structural_v1": PRN / "src/prineville_structural_v1.py",
    "prn_psychrometrics": PRN / "src/prineville_psychrometrics.py",
    "prn_graybox": PRN / "src/prineville_graybox.py",
    "prn_registry": PRN / "config/prineville_architecture_states.yaml",
    "cpu": REPO / "other_sources/nlr_esif_fullstack/analysis/FINAL_KESTREL_CPU_STATUS.json",
    "h100": REPO / "other_sources/nlr_esif_fullstack/genai_h100/manifests/H100_COMPUTE_FINAL_FREEZE.json",
    "esif": REPO / "other_sources/nlr_esif_fullstack/heat_rejection_water/manifests/ESIF_HEAT_WATER_RESULT_FREEZE.json",
}


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def main() -> int:
    sinfo = subprocess.check_output(["sinfo", "-o", "%P %a %l %D %t"], text=True)
    hashes = {}
    mismatches = []
    for key, path in PATHS.items():
        rec = {"path": str(path), "exists": path.exists()}
        if path.exists():
            rec["sha256"] = sha256_file(path)
            rec["bytes"] = path.stat().st_size
            if key in EXPECTED and rec["sha256"] != EXPECTED[key]:
                mismatches.append(key)
                rec["expected"] = EXPECTED[key]
                rec["match"] = False
            elif key in EXPECTED:
                rec["match"] = True
        hashes[key] = rec
    if mismatches:
        raise SystemExit(f"UPSTREAM HASH MISMATCH before v2 work: {mismatches}")
    py = sys.executable
    state = {
        "utc": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(REPO),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "head": git("rev-parse", "HEAD"),
        "git_status_short": git("status", "--short"),
        "python": py,
        "python_version": sys.version.split()[0],
        "CONDA_DEFAULT_ENV": os.environ.get("CONDA_DEFAULT_ENV"),
        "sloan_partition_inventory": sinfo,
        "preferred_partition": "sched_mit_sloan_batch",
        "forbid_partition": ["mit_normal"],
        "pre_existing_dirty_note": "Do not modify v1 or Prineville in this pass.",
        "MODEL_CALIBRATED": "NO",
        "v1_untouched_rule": True,
    }
    out = FC2 / "outputs" / "preflight"
    write_json(out / "INITIAL_STATE.json", state)
    write_json(out / "UPSTREAM_HASHES.json", {"expected": EXPECTED, "observed": hashes, "mismatches": mismatches})
    print(json.dumps({"head": state["head"], "branch": state["branch"], "hash_ok": not mismatches}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
