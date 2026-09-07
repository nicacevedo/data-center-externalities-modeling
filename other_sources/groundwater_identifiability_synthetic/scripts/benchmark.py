#!/usr/bin/env python3
"""Stage 4: runtime and storage benchmark, then STOP.

Projects the cost of the full preregistered sweep from measured per-cell timings so that the
sweep size is decided from measurement rather than guesswork. Launches nothing.
"""

from __future__ import annotations

import json
import platform
import resource
import sys
import time
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
from groundwater_identifiability_synthetic.src.evaluation import run_replicate
from groundwater_identifiability_synthetic.src.plan import all_cells, plan_summary

OUTPUTS = MODULE_ROOT / "outputs"
PROVENANCE = OUTPUTS / "provenance"


def main() -> int:
    design = load_design()
    cells = all_cells(design)
    smoke_seeds = seed_list(design, "SMOKE")
    n_analysis = int(design["seeds"]["pools"]["ANALYSIS"]["n_seeds"])

    # Time one replicate per cell, without bootstrap, then separately with bootstrap on a
    # small subset so the bootstrap cost is attributed rather than hidden.
    per_cell: dict[str, float] = {}
    seed = smoke_seeds[0]
    for cell_id, regime in cells.items():
        t0 = time.perf_counter()
        try:
            run_replicate(design, regime, seed)
        except Exception:
            per_cell[cell_id] = float("nan")
            continue
        per_cell[cell_id] = time.perf_counter() - t0

    # Bootstrap overhead must be a PAIRED difference on the SAME cells. Comparing bootstrap
    # runs on a 3-cell subset against the mean over all 127 cells is apples-to-oranges and
    # can report negative overhead purely because the subset is cheap.
    boot_cell_ids = [
        cell_id for cell_id in cells
        if np.isfinite(per_cell.get(cell_id, float("nan")))
    ][:6]
    boot_deltas = []
    for cell_id in boot_cell_ids:
        t0 = time.perf_counter()
        try:
            run_replicate(
                design,
                cells[cell_id],
                seed,
                with_bootstrap=True,
                n_bootstrap=int(design["uncertainty"]["n_bootstrap_analysis"]),
            )
        except Exception:
            continue
        boot_deltas.append((time.perf_counter() - t0) - per_cell[cell_id])

    times = np.array([v for v in per_cell.values() if np.isfinite(v)])
    total_cells = len(cells)
    sweep_seconds = float(np.nansum(list(per_cell.values())) * n_analysis)
    boot_overhead = float(np.mean(boot_deltas)) if boot_deltas else float("nan")

    # Storage: one scalar record per replicate.
    example = run_replicate(design, next(iter(cells.values())), seed)
    bytes_per_record = len(json.dumps(example, default=float).encode("utf-8"))
    total_records = total_cells * n_analysis
    storage_mb = bytes_per_record * total_records / (1024 * 1024)

    peak_rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0

    report = {
        "design_hash": design_hash(),
        "code_hash": code_hash(),
        "plan": plan_summary(design),
        "n_cells": total_cells,
        "n_analysis_seeds_planned": n_analysis,
        "n_replicates_projected": total_records,
        "seconds_per_replicate_median": float(np.median(times)) if times.size else float("nan"),
        "seconds_per_replicate_mean": float(np.mean(times)) if times.size else float("nan"),
        "seconds_per_replicate_max": float(np.max(times)) if times.size else float("nan"),
        "slowest_cells": sorted(
            ((v, k) for k, v in per_cell.items() if np.isfinite(v)), reverse=True
        )[:5],
        "projected_sweep_seconds_single_core": sweep_seconds,
        "projected_sweep_minutes_single_core": sweep_seconds / 60.0,
        "projected_sweep_hours_single_core": sweep_seconds / 3600.0,
        "bootstrap_overhead_seconds_per_replicate": boot_overhead,
        "bootstrap_overhead_measured_on_n_cells": len(boot_deltas),
        "bootstrap_overhead_is_paired": True,
        # Upper bound: assumes EVERY replicate is bootstrapped.
        "projected_sweep_minutes_with_bootstrap_all_replicates": (
            (sweep_seconds + boot_overhead * total_records) / 60.0
            if np.isfinite(boot_overhead)
            else float("nan")
        ),
        "bytes_per_replicate_record": bytes_per_record,
        "projected_output_storage_mb": storage_mb,
        "peak_rss_mb": peak_rss_mb,
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "numpy_version": np.__version__,
        "slurm_expected_needed": bool(sweep_seconds > 4 * 3600),
        "slurm_preferred_partitions": design["execution"]["slurm"]["preferred_partitions"],
        "full_sweep_launched": False,
        "per_cell_seconds": per_cell,
    }

    PROVENANCE.mkdir(parents=True, exist_ok=True)
    with open(OUTPUTS / "RUNTIME_STORAGE_BENCHMARK.json", "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True, default=float)

    print(f"cells={total_cells} analysis_seeds={n_analysis} replicates={total_records}")
    print(
        f"per-replicate median={report['seconds_per_replicate_median']*1000:.0f} ms "
        f"max={report['seconds_per_replicate_max']*1000:.0f} ms"
    )
    print(
        f"projected full sweep: {report['projected_sweep_minutes_single_core']:.1f} min single-core "
        f"({report['projected_sweep_hours_single_core']:.2f} h)"
    )
    print(f"projected storage: {storage_mb:.2f} MB ({bytes_per_record} bytes/record)")
    print(f"slurm expected needed: {report['slurm_expected_needed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
