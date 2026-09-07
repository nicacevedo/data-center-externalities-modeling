#!/usr/bin/env python3
"""Hard V2 bit-for-bit parity: G1R1, G2R3, G3R3 × 3 frozen V2 ANALYSIS seeds."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import _bootstrap_path  # noqa: F401
import numpy as np

from groundwater_identifiability_synthetic.src.design import (
    gate_cells,
    load_design as load_v2,
    seed_list as v2_seed_list,
)
from groundwater_identifiability_synthetic.src.evaluation import run_replicate as run_v2
from src_v3.design import MODULE_ROOT, V2_PARENT_ROOT
from src_v3.evaluation import run_replicate as run_v3

OUT = MODULE_ROOT / "outputs" / "determinism"
CELLS = ("G1R1", "G2R3", "G3R3")
SKIP = {"rng_mode", "system_seed_mode", "pairing_group", "identification_regime", "block"}


def _nan_eq(a, b) -> bool:
    if a is None and b is None:
        return True
    try:
        fa, fb = float(a), float(b)
        if math.isnan(fa) and math.isnan(fb):
            return True
        return fa == fb
    except (TypeError, ValueError):
        return str(a) == str(b)


def _load_csv_rows():
    path = V2_PARENT_ROOT / "outputs" / "analysis" / "sweep_replicates.csv"
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    v2_design = load_v2(V2_PARENT_ROOT / "config" / "design_v2.yaml")
    cells = gate_cells(v2_design)
    seeds = v2_seed_list(v2_design, "ANALYSIS")[:3]
    frozen = _load_csv_rows()
    results = []
    mismatches = []
    for cell_id in CELLS:
        regime = cells[cell_id]
        for seed in seeds:
            live_v2 = run_v2(v2_design, regime, int(seed))
            live_v3 = run_v3(
                v2_design,
                regime,
                int(seed),
                rng_mode="legacy_sequential",
                system_seed_mode="legacy_v2",
            )
            shared = [k for k in live_v2 if k in live_v3 and k not in SKIP]
            live_mismatch = []
            for key in shared:
                if not _nan_eq(live_v2[key], live_v3[key]):
                    live_mismatch.append(
                        {"key": key, "v2": live_v2[key], "v3": live_v3[key]}
                    )
            csv_row = next(
                r
                for r in frozen
                if r["cell_id"] == cell_id and str(r["seed"]) == str(int(seed))
            )
            csv_mismatch = []
            for key in shared:
                if key not in csv_row:
                    continue
                raw = csv_row[key]
                if raw == "":
                    csv_val = live_v3[key] if live_v3[key] in ("", None) else float("nan")
                else:
                    try:
                        csv_val = type(live_v3[key])(raw) if not isinstance(live_v3[key], (float, np.floating, int, np.integer, bool)) else float(raw)
                    except Exception:
                        csv_val = raw
                    if isinstance(live_v3[key], bool):
                        csv_val = str(raw).lower() in ("true", "1")
                if not _nan_eq(live_v3[key], csv_val):
                    # CSV serialization of bool/float; allow tight float match
                    try:
                        if np.isclose(float(live_v3[key]), float(csv_val), rtol=0, atol=0, equal_nan=True):
                            continue
                        if np.isclose(float(live_v3[key]), float(csv_val), rtol=1e-12, atol=1e-15, equal_nan=True):
                            continue
                    except Exception:
                        pass
                    csv_mismatch.append({"key": key, "csv": raw, "v3": live_v3[key]})
            entry = {
                "cell_id": cell_id,
                "seed": int(seed),
                "rng_mode": "legacy_sequential",
                "system_seed_mode": "legacy_v2",
                "n_shared_fields": len(shared),
                "live_v2_vs_v3_mismatches": live_mismatch,
                "bit_identical_live": not live_mismatch,
                "csv_mismatches": csv_mismatch[:20],
                "csv_match": not csv_mismatch,
            }
            results.append(entry)
            if live_mismatch:
                mismatches.append(entry)

    report = {
        "n_replicates": len(results),
        "all_live_bit_identical": not mismatches,
        "replicates": results,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "V2_PARITY_REPORT.json", "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, default=str)
        handle.write("\n")
    if mismatches:
        print("PARITY FAILED")
        for row in mismatches:
            print(row["cell_id"], row["seed"], row["live_v2_vs_v3_mismatches"][:5])
        raise SystemExit("V2 parity mismatch; STOP")
    print("V2 parity ok: 9/9 live bit-identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
