#!/usr/bin/env python3
"""Engineering smoke: 21 cells × 3 V3_SMOKE seeds. NON-INFERENTIAL. No ANALYSIS."""

from __future__ import annotations

import csv
import json
import time
import traceback
from pathlib import Path

import _bootstrap_path  # noqa: F401
import numpy as np

from src_v3.design import MODULE_ROOT, load_design, seed_list, v3_all_cells
from src_v3.evaluation import run_replicate
from src_v3.modes import RNG_NAMED, SEED_ORTHOGONAL
from src_v3.summarize_v3 import summarize_records

OUT = MODULE_ROOT / "outputs" / "smoke"
BANNER = "ENGINEERING SMOKE OUTPUT -- NOT A SCIENTIFIC RESULT."
BENCHMARK_JSON = MODULE_ROOT / "outputs" / "benchmarks" / "BENCHMARKS_V3.json"


def main() -> int:
    design = load_design()
    cells = v3_all_cells(design)
    if len(cells) != 21:
        raise SystemExit("expected 21 cells")
    smoke_seeds = seed_list(design, "V3_SMOKE")
    analysis_seeds = set(seed_list(design, "V3_ANALYSIS"))
    if set(smoke_seeds) & analysis_seeds:
        raise SystemExit("smoke/analysis overlap")
    records = []
    failures = []
    t0 = time.perf_counter()
    for cell_id, regime in cells.items():
        for seed in smoke_seeds:
            started = time.perf_counter()
            try:
                rec = run_replicate(
                    design,
                    regime,
                    int(seed),
                    rng_mode=RNG_NAMED,
                    system_seed_mode=SEED_ORTHOGONAL,
                )
                rec["elapsed_s"] = time.perf_counter() - started
                rec["source_pool"] = "V3_SMOKE"
                rec["smoke"] = True
                records.append(rec)
            except Exception as exc:
                failures.append(
                    {
                        "cell_id": cell_id,
                        "seed": int(seed),
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    }
                )
    elapsed = time.perf_counter() - t0
    OUT.mkdir(parents=True, exist_ok=True)
    if records:
        fields = sorted({k for r in records for k in r})
        with open(OUT / "SMOKE_V3_REPLICATES.csv", "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in records:
                writer.writerow(row)

    benchmarks = None
    convergence = None
    if BENCHMARK_JSON.exists():
        with open(BENCHMARK_JSON, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        benchmarks = {str(r["cell_id"]): r for r in payload.get("rows", [])}
        convergence = payload.get("convergence") or None

    n_bytes = (OUT / "SMOKE_V3_REPLICATES.csv").stat().st_size if records else 0
    bytes_per_replicate = n_bytes / max(len(records), 1)
    storage_projection = {
        "smoke_csv_bytes": n_bytes,
        "bytes_per_replicate_approx": bytes_per_replicate,
        "projected_analysis_4200_bytes": bytes_per_replicate * 4200,
        "note": "NON-INFERENTIAL engineering projection only",
    }
    summary = {
        "banner": BANNER,
        "non_inferential": True,
        "n_expected": 63,
        "n_completed": len(records),
        "n_failures": len(failures),
        "failures": failures,
        "elapsed_s": elapsed,
        "rng_mode": RNG_NAMED,
        "system_seed_mode": SEED_ORTHOGONAL,
        "NOT_ESTIMABLE": sum(
            1 for r in records if r.get("estimability_status_L") == "NOT_ESTIMABLE"
        ),
        "FIT_FAILED": sum(
            1 for r in records if r.get("estimability_status_L") == "FIT_FAILED"
        ),
        "summarizer": summarize_records(
            records, benchmarks=benchmarks, convergence=convergence
        ),
        "benchmarks_merged": bool(benchmarks),
        "storage_projection": storage_projection,
        "V3_ANALYSIS_REPLICATES_RUN": 0,
    }
    with open(OUT / "SMOKE_V3_SUMMARY.json", "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, default=str)
        handle.write("\n")

    # CRN parity on Block A smoke seed 0: exact Q_true / z equality already unit-tested;
    # record pairing metadata here.
    crn = {
        "banner": BANNER,
        "tier1_cells": ["A_PEXACT", "A_S025", "A_S050", "A_S100", "A_S200"],
        "note": "array-equality CRN is in tests_v3/test_modes_and_crn.py",
        "smoke_pairing_groups": sorted({r.get("pairing_group") for r in records}),
    }
    with open(OUT / "CRN_PARITY_REPORT.json", "w", encoding="utf-8") as handle:
        json.dump(crn, handle, indent=2)
        handle.write("\n")
    if failures or len(records) != 63:
        raise SystemExit(f"smoke incomplete: {len(records)}/63 failures={len(failures)}")
    print(f"SMOKE ok 63/63 in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
