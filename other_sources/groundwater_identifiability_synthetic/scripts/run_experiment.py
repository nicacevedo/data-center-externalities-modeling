#!/usr/bin/env python3
"""Phase 2: full preregistered Monte Carlo sweep.

IMPLEMENTED BUT DELIBERATELY NOT EXECUTED IN PHASE 1.

Phase 1 terminates at a mandatory external-review checkpoint after
pytest -> SGI_G0 -> engineering smoke -> runtime/storage benchmark. Running this script
requires the explicit authorization flag below, which exists so the sweep cannot be launched
by accident or by a stray scheduler.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

import _bootstrap_path  # noqa: F401

from groundwater_identifiability_synthetic.src.design import (
    MODULE_ROOT,
    code_hash,
    design_hash,
    load_design,
    seed_list,
)
from groundwater_identifiability_synthetic.src.evaluation import run_replicate
from groundwater_identifiability_synthetic.src.plan import all_cells, plan_summary

OUTPUTS = MODULE_ROOT / "outputs"
PROVENANCE = OUTPUTS / "provenance"
AUTHORIZATION_TOKEN = "I_AUTHORIZE_THE_FULL_PREREGISTERED_SWEEP"


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
    freeze_path = PROVENANCE / "DESIGN_FREEZE.json"
    if not freeze_path.exists():
        raise SystemExit("design is not frozen; run scripts/freeze_protocol.py first")
    with open(freeze_path, "r", encoding="utf-8") as handle:
        freeze = json.load(handle)
    if design_hash() != freeze["design_hash"]:
        raise SystemExit("DESIGN HASH MISMATCH; create design_v2 and rerun")

    cells = all_cells(design)
    analysis_seeds = seed_list(design, "ANALYSIS")
    smoke_seeds = set(seed_list(design, "SMOKE"))
    if set(analysis_seeds) & smoke_seeds:
        raise SystemExit("analysis and smoke seed pools overlap; refusing to run")

    n_boot = int(design["uncertainty"]["n_bootstrap_analysis"]) if args.bootstrap else 0
    records: list[dict] = []
    started = time.perf_counter()
    for cell_id, regime in cells.items():
        for seed in analysis_seeds:
            records.append(
                run_replicate(
                    design, regime, seed, with_bootstrap=args.bootstrap, n_bootstrap=n_boot
                )
            )
    elapsed = time.perf_counter() - started

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for record in records for key in record})
    with open(OUTPUTS / "sweep_replicates.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)

    manifest = {
        "design_hash": design_hash(),
        "code_hash": code_hash(),
        "plan": plan_summary(design),
        "n_cells": len(cells),
        "n_analysis_seeds": len(analysis_seeds),
        "n_records": len(records),
        "wall_seconds": elapsed,
        "bootstrap": bool(args.bootstrap),
        "analysis_seeds": analysis_seeds,
        "smoke_seeds_excluded": sorted(smoke_seeds),
        "full_sweep_launched": True,
    }
    with open(PROVENANCE / "SWEEP_MANIFEST.json", "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True, default=float)

    print(f"sweep complete: {len(records)} records in {elapsed/60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
