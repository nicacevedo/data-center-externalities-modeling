#!/usr/bin/env python3
"""Record git/v1/Prineville/CPU hashes. Do not modify v1 or Prineville."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

FC2 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FC2 / "src"))
from hashes import sha256_file, write_json  # noqa: E402
from paths import (  # noqa: E402
    OUTPUTS,
    PRINEVILLE_ROOT,
    REPO_ROOT,
    V1_OUTPUTS,
    V1_ROOT,
    V1_SRC,
)

EXPECTED = {
    "prineville_structural_v1.py": "f9649c489196cdc3e617f5b28574334aaaace5a94e7ade5ce461f6da22809a6a",
    "prineville_psychrometrics.py": "c10e1487a00ce32023bf3b630f915b2fe9ba303917951ff5f5bcbec3a3aafd30",
    "prineville_graybox.py": "8275ca5bfc23042e3af19b72f2adb260304ac95d692d0b3ecbcb526b020f0609",
    "prineville_architecture_states.yaml": "1f87a1846aa8254c758ab11e3bd9b6f639e6c64bc551c36bcf8201bd65e78604",
    "PRINEVILLE_STRUCTURAL_REFERENCE_V1_FREEZE.json": "decd095f59cc2249eee66d5b94ad30d30a53555eadbec3358bbb9aa80caaa81d",
    "OCP_REFERENCE_CONTROL_CONTRACT.json": "b320525efd2af8b553bbc933b6740605a2ddcecffca84677b8ba0ae4df316e4e",
    "Q2_2012_KRDM_hourly.parquet": "87c0beaf1f8223ebb9f4d02ff13b9efd9d2286aaddfec0a3cce9af4c4279d925",
    "cpu": "1f57b210a63d375ce8eff7d5043756ffe6efe04e8a408bf9429bfd10096528d9",
    "h100": "a620d649a932f2388aa2f35bac2730eb75fe1dc74529668de4f30ee814600076",
    "esif": "4e01139dd9365f62824ac00ff944468839e7873e47a5cea3df4714854af1b02c",
    "fc_v1_controller": "99ecc213fa181ab1fe7144087da5874b0a8f3f79478a6a8b5aed83fe0ea77c78",
    "fc_v1_structural": "085a893cd63665b37d027877e9d80efbc99489a6c813a9f8da150e41a529568d",
    "fc_v1_control_contract": "56d3ef12b0ab3584886892a3283f068ebe7bcfc0adc827543dc6b8910da450c2",
    "fc_v1_airflow_contract": "f1cdc03bea8f5103e8951c6fbef7e965d16248e511fd4ad4874e19d5054ddc37",
}

FILES = {
    "prineville_structural_v1.py": PRINEVILLE_ROOT / "src" / "prineville_structural_v1.py",
    "prineville_psychrometrics.py": PRINEVILLE_ROOT / "src" / "prineville_psychrometrics.py",
    "prineville_graybox.py": PRINEVILLE_ROOT / "src" / "prineville_graybox.py",
    "prineville_architecture_states.yaml": PRINEVILLE_ROOT / "config" / "prineville_architecture_states.yaml",
    "PRINEVILLE_STRUCTURAL_REFERENCE_V1_FREEZE.json": PRINEVILLE_ROOT
    / "outputs"
    / "structural_revision_v1"
    / "PRINEVILLE_STRUCTURAL_REFERENCE_V1_FREEZE.json",
    "OCP_REFERENCE_CONTROL_CONTRACT.json": PRINEVILLE_ROOT
    / "outputs"
    / "structural_revision_v1"
    / "OCP_REFERENCE_CONTROL_CONTRACT.json",
    "Q2_2012_KRDM_hourly.parquet": PRINEVILLE_ROOT
    / "outputs"
    / "prn1_q2_2012_public_validation_v1"
    / "weather"
    / "Q2_2012_KRDM_hourly.parquet",
    "cpu": REPO_ROOT / "other_sources/nlr_esif_fullstack/analysis/FINAL_KESTREL_CPU_STATUS.json",
    "h100": REPO_ROOT / "other_sources/nlr_esif_fullstack/genai_h100/manifests/H100_COMPUTE_FINAL_FREEZE.json",
    "esif": REPO_ROOT
    / "other_sources/nlr_esif_fullstack/heat_rejection_water/manifests/ESIF_HEAT_WATER_RESULT_FREEZE.json",
    "fc_v1_controller": V1_SRC / "forest_city_controller.py",
    "fc_v1_structural": V1_SRC / "forest_city_structural_reference_v1.py",
    "fc_v1_control_contract": V1_ROOT / "config" / "FOREST_CITY_REFERENCE_CONTROL_CONTRACT.json",
    "fc_v1_airflow_contract": V1_ROOT / "config" / "FOREST_CITY_AIRFLOW_BOUNDARY_CONTRACT.json",
    "fc_v1_freeze": V1_OUTPUTS / "FOREST_CITY_PUBLIC_VALIDATION_FREEZE.json",
}


def git(cmd: str) -> str:
    r = subprocess.run(cmd, shell=True, cwd=REPO_ROOT, capture_output=True, text=True)
    return (r.stdout or r.stderr).strip()


def main() -> None:
    hashes = {}
    mismatches = []
    for k, p in FILES.items():
        rec = {"path": str(p), "exists": p.exists()}
        if p.exists():
            rec["sha256"] = sha256_file(p)
            rec["bytes"] = p.stat().st_size
            exp = EXPECTED.get(k)
            if exp:
                rec["match"] = rec["sha256"] == exp
                rec["expected"] = exp
                if not rec["match"]:
                    mismatches.append(k)
        hashes[k] = rec

    v1_extra = {}
    for p in sorted(V1_SRC.glob("*.py")) + sorted((V1_ROOT / "config").glob("*")):
        v1_extra[str(p.relative_to(V1_ROOT))] = {
            "sha256": sha256_file(p),
            "bytes": p.stat().st_size,
        }

    state = {
        "pass": "forest_city_north_carolina_v2_robustness",
        "requested_public_baseline": "3cfcd63fecb01f8396f0f440ddf08dffef65bdbc",
        "branch": git("git rev-parse --abbrev-ref HEAD"),
        "HEAD": git("git rev-parse HEAD"),
        "HEAD_matches_requested_baseline": git("git rev-parse HEAD")
        == "3cfcd63fecb01f8396f0f440ddf08dffef65bdbc",
        "git_status_porcelain": git("git status --porcelain=v1"),
        "utc": datetime.now(timezone.utc).isoformat(),
        "MODEL_CALIBRATED": "NO",
        "no_commit": True,
        "v1_must_remain_unchanged": True,
        "prineville_must_remain_unchanged": True,
        "hashes": hashes,
        "hash_mismatches": mismatches,
        "v1_src_config_hashes": v1_extra,
    }
    write_json(OUTPUTS / "INITIAL_STATE.json", state)

    inherit = {
        "v1_root": str(V1_ROOT),
        "reuse_by_path_do_not_duplicate": {
            "v1_raw_weather": str(V1_ROOT / "data/raw/weather"),
            "v1_processed_kfq_parquet": str(V1_ROOT / "data/processed/forest_city_weather_2012_hourly.parquet"),
            "v1_sustainability_pdfs": str(V1_ROOT / "data/raw/sustainability"),
            "v1_lwsp": str(V1_ROOT / "data/raw/lwsp"),
            "v1_annual_electricity": str(V1_ROOT / "data/processed/FOREST_CITY_ANNUAL_ELECTRICITY.csv"),
            "v1_annual_water": str(V1_ROOT / "data/processed/FOREST_CITY_ANNUAL_WATER_WITHDRAWAL.csv"),
            "v1_scope2": str(V1_ROOT / "data/processed/FOREST_CITY_SCOPE2_LOCATION.csv"),
            "v1_municipal_monthly": str(V1_ROOT / "data/processed/forest_city_municipal_water_monthly.csv"),
            "krdm_hourly_csv": str(PRINEVILLE_ROOT / "data/processed/weather_krdm_hourly.csv"),
            "krdm_q2_parquet": str(
                PRINEVILLE_ROOT / "outputs/prn1_q2_2012_public_validation_v1/weather/Q2_2012_KRDM_hourly.parquet"
            ),
        },
        "v1_controller_sha256": hashes["fc_v1_controller"].get("sha256"),
        "v1_structural_sha256": hashes["fc_v1_structural"].get("sha256"),
        "v1_validation_freeze_sha256": hashes["fc_v1_freeze"].get("sha256") if FILES["fc_v1_freeze"].exists() else None,
        "v1_control_contract_sha256": hashes["fc_v1_control_contract"].get("sha256"),
        "v1_airflow_contract_sha256": hashes["fc_v1_airflow_contract"].get("sha256"),
        "prineville_structural_v1_sha256": hashes["prineville_structural_v1.py"].get("sha256"),
        "prn1_q2_weather_sha256": hashes["Q2_2012_KRDM_hourly.parquet"].get("sha256"),
        "note": "v2 imports v1/Prineville modules read-only. Large weather/PDF files are referenced, not copied.",
    }
    write_json(OUTPUTS / "V1_INHERITANCE_MANIFEST.json", inherit)
    print(json.dumps({"HEAD": state["HEAD"], "mismatches": mismatches}, indent=2))


if __name__ == "__main__":
    main()
