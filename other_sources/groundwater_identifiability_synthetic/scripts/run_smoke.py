#!/usr/bin/env python3
"""Stage 3: ENGINEERING SMOKE RUN.

Purpose, and the only purpose: detect implementation failures and exercise every code path
on every frozen cell. Smoke results are NOT scientific results.

Hard rules enforced here and in tests:
  - smoke uses the SMOKE seed pool only, which is disjoint from ANALYSIS;
  - smoke output is written to a clearly quarantined file;
  - no smoke seed may appear in any substantive output;
  - no threshold, gate, regime choice, or scientific claim may be derived from smoke output.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
import traceback
from pathlib import Path

import _bootstrap_path  # noqa: F401
import numpy as np

from groundwater_identifiability_synthetic.src.design import (
    MODULE_ROOT,
    code_hash,
    design_hash,
    load_design,
    seed_list,
)
from groundwater_identifiability_synthetic.src.evaluation import _nanmax, run_replicate
from groundwater_identifiability_synthetic.src.plan import all_cells, plan_summary

OUTPUTS = MODULE_ROOT / "outputs"
PROVENANCE = OUTPUTS / "provenance"

SMOKE_BANNER = (
    "ENGINEERING SMOKE OUTPUT -- NOT A SCIENTIFIC RESULT. "
    "Detects implementation failures and measures runtime only. "
    "Must not be used to set thresholds, choose regimes, tune gates, or make claims."
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", action="store_true", help="exercise the bootstrap path")
    args = parser.parse_args()

    design = load_design()
    freeze_path = PROVENANCE / "DESIGN_FREEZE.json"
    if not freeze_path.exists():
        raise SystemExit("design is not frozen; run scripts/freeze_protocol.py first")
    with open(freeze_path, "r", encoding="utf-8") as handle:
        freeze = json.load(handle)
    if design_hash() != freeze["design_hash"]:
        raise SystemExit("DESIGN HASH MISMATCH; refusing to run")
    running_code_hash = code_hash()
    if running_code_hash != freeze["code_hash"]:
        print(f"WARNING: code changed since freeze ({running_code_hash[:12]} != "
              f"{freeze['code_hash'][:12]}); earlier outputs are invalid")

    cells = all_cells(design)
    smoke_seeds = seed_list(design, "SMOKE")
    analysis_seeds = set(seed_list(design, "ANALYSIS"))
    if set(smoke_seeds) & analysis_seeds:
        raise SystemExit("smoke and analysis seed pools overlap; refusing to run")

    n_boot = int(design["uncertainty"]["n_bootstrap_smoke"]) if args.bootstrap else 0

    records: list[dict] = []
    failures: list[dict] = []
    timings: dict[str, list[float]] = {}

    started = time.perf_counter()
    for cell_id, regime in cells.items():
        for seed in smoke_seeds:
            t0 = time.perf_counter()
            try:
                record = run_replicate(
                    design, regime, seed, with_bootstrap=args.bootstrap, n_bootstrap=n_boot
                )
                record["smoke"] = True
                records.append(record)
            except Exception as exc:  # a smoke run must surface, not hide, failures
                failures.append(
                    {
                        "cell_id": cell_id,
                        "seed": int(seed),
                        "error": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc(limit=6),
                    }
                )
            timings.setdefault(cell_id, []).append(time.perf_counter() - t0)
    elapsed = time.perf_counter() - started

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    smoke_csv = OUTPUTS / "SMOKE_ENGINEERING_REPLICATES.csv"
    if records:
        fields = sorted({key for record in records for key in record})
        with open(smoke_csv, "w", encoding="utf-8", newline="") as handle:
            handle.write(f"# {SMOKE_BANNER}\n")
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(records)

    # Validity checks are about the IMPLEMENTATION, not about the science.
    validity = implementation_validity(records, cells)
    summary = {
        "banner": SMOKE_BANNER,
        "design_hash": freeze["design_hash"],
        "code_hash_at_freeze": freeze["code_hash"],
        "code_hash_at_run": running_code_hash,
        "plan": plan_summary(design),
        "n_cells": len(cells),
        "n_smoke_seeds": len(smoke_seeds),
        "n_replicates_attempted": len(cells) * len(smoke_seeds),
        "n_replicates_succeeded": len(records),
        "n_failures": len(failures),
        "failures": failures[:25],
        "wall_seconds_total": elapsed,
        "seconds_per_replicate_mean": elapsed / max(len(cells) * len(smoke_seeds), 1),
        "seconds_per_replicate_by_cell": {k: float(np.mean(v)) for k, v in timings.items()},
        "bootstrap_exercised": bool(args.bootstrap),
        "implementation_validity": validity,
        "smoke_seeds": smoke_seeds,
        "scientific_interpretation": "NONE_PERMITTED",
    }
    with open(OUTPUTS / "SMOKE_ENGINEERING_SUMMARY.json", "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True, default=float)

    print(SMOKE_BANNER)
    print(f"cells={len(cells)} seeds={len(smoke_seeds)} "
          f"ok={len(records)} failed={len(failures)} wall={elapsed:.1f}s "
          f"({summary['seconds_per_replicate_mean']*1000:.0f} ms/replicate)")
    for name, value in validity.items():
        print(f"  {name}: {value}")
    for failure in failures[:5]:
        print(f"  FAILURE {failure['cell_id']} seed={failure['seed']}: {failure['error']}")
    return 1 if failures else 0


def implementation_validity(records: list[dict], cells: dict) -> dict:
    """Code-path coverage and invariant checks. Deliberately contains no scientific verdict."""
    if not records:
        return {"status": "NO_RECORDS"}

    def frac_finite(key: str) -> float:
        values = np.array([r.get(key, np.nan) for r in records], dtype=float)
        return float(np.mean(np.isfinite(values)))

    covered = {r["cell_id"] for r in records}
    clip = np.array([r.get("clip_fraction", np.nan) for r in records], dtype=float)
    stability_ok = all(
        np.isfinite(r.get("rho_A", np.nan)) and r["rho_A"] < 1.0 for r in records
    )
    return {
        "cells_covered": f"{len(covered)}/{len(cells)}",
        "all_cells_covered": len(covered) == len(cells),
        "all_systems_contracting": bool(stability_ok),
        "max_clip_fraction": _nanmax(clip),
        "frac_finite_rmse_test_L": frac_finite("rmse_test_L"),
        "frac_finite_nire_persistent_step_h26_L": frac_finite("nire_persistent_step_h26_L"),
        "frac_finite_nire_persistent_step_h26_N": frac_finite("nire_persistent_step_h26_N"),
        "frac_finite_edge_f1": frac_finite("edge_f1"),
        "frac_finite_masked_node_nmpe_N": frac_finite("masked_node_nmpe_N"),
        "frac_finite_condition_number_L": frac_finite("condition_number_L"),
        "n_records": len(records),
    }


if __name__ == "__main__":
    raise SystemExit(main())
