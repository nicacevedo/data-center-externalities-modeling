#!/usr/bin/env python3
"""Phase 2: full preregistered Monte Carlo sweep.

Refuses to run unless --authorize matches the frozen token AND DESIGN_HASH, CODE_HASH,
and the ANALYSIS seed-pool hash all match the freeze record.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import time
from pathlib import Path

import _bootstrap_path  # noqa: F401

from groundwater_identifiability_synthetic.src.design import (
    MODULE_ROOT,
    code_hash,
    design_hash,
    load_design,
    seed_list,
    seed_pool_hash,
)
from groundwater_identifiability_synthetic.src.evaluation import run_replicate
from groundwater_identifiability_synthetic.src.plan import all_cells, plan_summary

OUTPUTS = MODULE_ROOT / "outputs"
PROVENANCE = OUTPUTS / "provenance"
ANALYSIS_OUT = OUTPUTS / "analysis"
AUTHORIZATION_TOKEN = "I_AUTHORIZE_THE_FULL_PREREGISTERED_SWEEP"


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=MODULE_ROOT, text=True
        ).strip()
    except Exception:
        return ""


def validate_freeze(design: dict, freeze: dict) -> None:
    current_design = design_hash()
    current_code = code_hash()
    frozen_design = freeze["design_hash"]
    frozen_code = freeze["code_hash"]
    if current_design != frozen_design:
        raise SystemExit(
            "DESIGN HASH MISMATCH; refusing ANALYSIS\n"
            f"  current={current_design}\n"
            f"  frozen ={frozen_design}"
        )
    if current_code != frozen_code:
        raise SystemExit(
            "CODE HASH MISMATCH; refusing ANALYSIS\n"
            f"  current={current_code}\n"
            f"  frozen ={frozen_code}"
        )
    current_seed = seed_pool_hash(design, "ANALYSIS")
    frozen_seed = freeze["seed_pool_hashes"]["ANALYSIS"]
    if current_seed != frozen_seed:
        raise SystemExit(
            "ANALYSIS SEED POOL HASH MISMATCH; refusing ANALYSIS\n"
            f"  current={current_seed}\n"
            f"  frozen ={frozen_seed}"
        )
    analysis = set(seed_list(design, "ANALYSIS"))
    for pool in ("G0", "SMOKE", "CALIBRATION"):
        overlap = analysis & set(seed_list(design, pool))
        if overlap:
            raise SystemExit(f"ANALYSIS overlaps {pool}; refusing to run")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--authorize",
        default="",
        help=f"must equal {AUTHORIZATION_TOKEN} to launch the full sweep",
    )
    parser.add_argument("--bootstrap", action="store_true")
    args = parser.parse_args()

    if args.authorize != AUTHORIZATION_TOKEN:
        print(
            "REFUSING TO RUN.\n"
            "The full Monte Carlo sweep is Phase 2 and requires explicit authorization.\n"
            "Phase 1 ends at the external-review checkpoint after the runtime benchmark.\n"
            f"Re-run with --authorize {AUTHORIZATION_TOKEN} only after that review."
        )
        return 2

    design = load_design()
    freeze_path = PROVENANCE / "DESIGN_V2_FREEZE.json"
    if not freeze_path.exists():
        raise SystemExit("design is not frozen; run scripts/freeze_protocol.py first")
    with open(freeze_path, "r", encoding="utf-8") as handle:
        freeze = json.load(handle)
    validate_freeze(design, freeze)

    cells = all_cells(design)
    analysis_seeds = seed_list(design, "ANALYSIS")
    n_boot = int(design["uncertainty"]["n_bootstrap_analysis"]) if args.bootstrap else 0
    expected = len(cells) * len(analysis_seeds)

    print("FEATURE_COMMIT", _git_head())
    print("DESIGN_HASH", freeze["design_hash"])
    print("CODE_HASH", freeze["code_hash"])
    print("ANALYSIS_SEED_HASH", freeze["seed_pool_hashes"]["ANALYSIS"])
    print("EXPECTED_CELLS", len(cells))
    print("ANALYSIS_SEEDS_PER_CELL", len(analysis_seeds))
    print("EXPECTED_REPLICATES", expected)
    print("BOOTSTRAP", bool(args.bootstrap))
    print("ANALYSIS_SEEDS_INSPECTED_PRE_RUN", False)

    records: list[dict] = []
    started = time.perf_counter()
    for cell_id, regime in cells.items():
        for seed in analysis_seeds:
            rec = run_replicate(
                design, regime, seed, with_bootstrap=args.bootstrap, n_bootstrap=n_boot
            )
            rec["smoke"] = False
            rec["source_pool"] = "ANALYSIS"
            records.append(rec)
    elapsed = time.perf_counter() - started

    ANALYSIS_OUT.mkdir(parents=True, exist_ok=True)
    PROVENANCE.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for record in records for key in record})
    sweep_csv = ANALYSIS_OUT / "sweep_replicates.csv"
    with open(sweep_csv, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)

    manifest = {
        "source": "ANALYSIS",
        "design_hash": design_hash(),
        "code_hash": code_hash(),
        "analysis_seed_hash": seed_pool_hash(design, "ANALYSIS"),
        "plan": plan_summary(design),
        "n_cells": len(cells),
        "n_analysis_seeds": len(analysis_seeds),
        "n_records": len(records),
        "n_records_expected": expected,
        "wall_seconds": elapsed,
        "bootstrap": bool(args.bootstrap),
        "analysis_seeds": analysis_seeds,
        "smoke_seeds_excluded": seed_list(design, "SMOKE"),
        "g0_seeds_excluded": seed_list(design, "G0"),
        "calibration_seeds_excluded": seed_list(design, "CALIBRATION"),
        "full_sweep_launched": True,
        "analysis_seeds_inspected_pre_run": False,
        "feature_commit": _git_head(),
        "sweep_csv": str(sweep_csv.relative_to(MODULE_ROOT)),
    }
    with open(PROVENANCE / "SWEEP_MANIFEST.json", "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True, default=float)

    print(f"sweep complete: {len(records)} records in {elapsed/60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
