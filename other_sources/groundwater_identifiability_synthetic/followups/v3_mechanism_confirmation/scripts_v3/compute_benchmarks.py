#!/usr/bin/env python3
"""Compute seed-independent V3 benchmarks for all 21 cells. No ANALYSIS."""

from __future__ import annotations

import csv
import json

import _bootstrap_path  # noqa: F401

from src_v3.benchmarks import (
    cell_structural_diagnostics,
    f_intervention_for_system,
    f_train_for_cell,
)
from src_v3.design import MODULE_ROOT, load_design, rng_for, seed_list, v3_all_cells
from src_v3.modes import RNG_NAMED, SEED_ORTHOGONAL
from src_v3.rng import StreamBank
from src_v3 import dgp
from src_v3.evaluation import scenario_options
from src_v3.observations import make_observations

OUT = MODULE_ROOT / "outputs" / "benchmarks"


def main() -> int:
    design = load_design()
    cells = v3_all_cells(design)
    seed = seed_list(design, "V3_BENCHMARK")[0]
    rows = []
    for cell_id, regime in cells.items():
        options = scenario_options(design, regime)
        system = dgp.build_system(
            design,
            regime.topology,
            regime.memory,
            regime.gamma,
            recharge_efficiency=float(options.get("recharge_efficiency", 1.0)),
            system_seed_mode=SEED_ORTHOGONAL,
        )
        streams = StreamBank(int(seed))
        traj = dgp.simulate(design, system, regime, rng_for(int(seed)), options, streams=streams)
        bundle = make_observations(design, system, traj, regime, rng_for(int(seed)), streams=streams)
        structural = cell_structural_diagnostics(design, regime, system, traj)
        f_int = f_intervention_for_system(design, system, traj, bundle)
        f_tr = f_train_for_cell(design, regime, RNG_NAMED, SEED_ORTHOGONAL)
        row = {
            "cell_id": cell_id,
            "rng_mode": RNG_NAMED,
            "system_seed_mode": SEED_ORTHOGONAL,
            **structural,
            **f_int,
            **f_tr,
            "F_train_is_monte_carlo": True,
            "F_intervention_is_deterministic": True,
        }
        rows.append(row)
        print(cell_id, "F_train", row.get("F_train"), "F_int", row.get("F_intervention"))

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "BENCHMARKS_V3.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    with open(OUT / "BENCHMARKS_V3.json", "w", encoding="utf-8") as handle:
        json.dump({"n_cells": len(rows), "rows": rows, "non_inferential": True}, handle, indent=2)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
