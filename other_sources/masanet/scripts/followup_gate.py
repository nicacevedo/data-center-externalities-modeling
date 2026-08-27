#!/usr/bin/env python3
"""Phase 7: hard gate for project translation. Exit nonzero if adapter would be invalid."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from common import PY, UPSTREAM_COMMIT, WORK_ROOT, atomic_write_json, set_threads, utcnow
from followup_common import FOLLOWUP, FOLLOWUP_DOCS, SELECTED_CELLS


def _load(p: Path):
    if not p.exists():
        return None
    return json.loads(p.read_text())


def main():
    set_threads()
    FOLLOWUP.mkdir(parents=True, exist_ok=True)
    FOLLOWUP_DOCS.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [str(PY), str(WORK_ROOT / "scripts" / "followup_annual.py"), "--mode", "compare"],
        cwd=str(WORK_ROOT),
        check=False,
    )
    cross = _load(FOLLOWUP / "paper_code_crosswalk.json")
    smoke_s = _load(FOLLOWUP / "annual_smoke_short.json")
    smoke_f = _load(FOLLOWUP / "annual_smoke_full.json")
    cmp_ = _load(FOLLOWUP / "annual_selected_comparison.json")
    rng = _load(FOLLOWUP / "annual_rng.json")
    front = _load(FOLLOWUP / "FRONTIER_CLOSURE_STATUS.json")
    nb = _load(FOLLOWUP / "notebook_pue_sweep.json")
    weather = _load(WORK_ROOT / "manifests" / "FOLLOWUP_V1_WEATHER.json")

    failed = []
    warnings = []
    mapping = (cross or {}).get("status")
    if mapping != "PASS":
        failed.append("paper_code_crosswalk")
    if (smoke_s or {}).get("status") != "PASS":
        failed.append("annual_smoke_short")
    if (smoke_f or {}).get("status") != "PASS":
        failed.append("annual_smoke_full")
    if cmp_ is None:
        failed.append("annual_selected_comparison_missing")
        annual_rep = "NOT_RUN"
    else:
        annual_rep = cmp_.get("status")
        if annual_rep == "INCONSISTENT":
            failed.append("annual_reproduction_INCONSISTENT")
        elif annual_rep == "NOT_RUN":
            failed.append("annual_cells_not_run")
        elif annual_rep == "NEEDS_REPLICATE":
            failed.append("annual_needs_replicate_unresolved")
    rng_st = (rng or {}).get("status")
    if rng_st == "ANNUAL_RNG_MATERIAL":
        failed.append("annual_rng_material")
    elif rng_st != "ANNUAL_RNG_IMMATERIAL":
        failed.append("annual_rng_unresolved")
        rng_st = rng_st or "UNRESOLVED"

    identity = True
    for cell in SELECTED_CELLS:
        p = FOLLOWUP / f"annual_case{cell['paper_case']}_{cell['climate_zone']}_r0.json"
        d = _load(p)
        if not d:
            identity = False
            continue
        if not d.get("identity_all_pass", False):
            identity = False
            failed.append(f"identity_case{cell['paper_case']}_{cell['climate_zone']}")

    structural_partial = mapping != "PASS"
    mc_only = annual_rep in ("CONSISTENT_WITH_PUBLISHED_RANGE", "PARTIAL_NUMERIC_DIFFERENCE") and not structural_partial
    if failed:
        if structural_partial or rng_st == "ANNUAL_RNG_MATERIAL" or annual_rep == "INCONSISTENT":
            closure = "FAIL"
        else:
            closure = "PARTIAL"
    elif annual_rep == "CONSISTENT_WITH_PUBLISHED_RANGE" and rng_st == "ANNUAL_RNG_IMMATERIAL" and identity:
        closure = "PASS"
    elif mc_only:
        closure = "PARTIAL"
        warnings.append("Monte-Carlo/non-recoverable-seed variation only; physics/envelopes treated as consistent.")
    else:
        closure = "PARTIAL"

    proceed = closure in ("PASS", "PARTIAL") and rng_st == "ANNUAL_RNG_IMMATERIAL" and mapping == "PASS" and annual_rep != "INCONSISTENT"
    if closure == "PARTIAL" and structural_partial:
        proceed = False

    out = {
        "status": closure,
        "proceed_to_adapter": proceed,
        "timestamp_utc": utcnow(),
        "upstream_commit": UPSTREAM_COMMIT,
        "paper_code_crosswalk_status": mapping,
        "annual_smoke_short_status": (smoke_s or {}).get("status"),
        "annual_smoke_full_status": (smoke_f or {}).get("status"),
        "annual_reproduction_status": annual_rep,
        "annual_rng_status": rng_st,
        "paper_aggregation_identity_status": "PASS" if identity else "FAIL",
        "weather_source_status": (weather or {}).get("status"),
        "frontier_closure": (front or {}).get("status"),
        "notebook_pue_discrepancy_status": (nb or {}).get("status"),
        "selected_cells": SELECTED_CELLS,
        "failed_tests": failed,
        "warnings": warnings,
        "did_read_meta_2023_2024_water": False,
        "stop_if_not_proceed": (
            "Do not build/use the project adapter if proceed_to_adapter is false. "
            "Ask before modifying control/setpoint treatment if RNG is MATERIAL."
        ),
    }
    atomic_write_json(FOLLOWUP / "MASANET_ANNUAL_CLOSURE_STATUS.json", out)
    print(json.dumps({k: out[k] for k in ("status", "proceed_to_adapter", "annual_reproduction_status", "annual_rng_status", "failed_tests")}, indent=2))
    if not proceed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
