#!/usr/bin/env python3
"""Compute the frozen V3 benchmark layers for all 21 cells. No ANALYSIS seeds are read.

Emits, per cell:

    F_intervention_all        layer 1, planning-relevant, deterministic
    F_intervention_pumped     layer-1 companion, pumped node only, deterministic
    neighbor_unmodeled_floor  exact known-truth representational floor, deterministic
    F_train_true              layer 2, latent-true one-step pseudo-true target (MC)
    F_train_obs               layer 3, observed-data one-step pseudo-true target (MC)

plus nested-prefix convergence at 16 / 32 / 64 / 128 for both training benchmarks, with
coefficient convergence as well as NIRE convergence.

These values are pre-defined benchmark diagnostics. They may not be used to alter cells,
sigma, gamma, n_ANALYSIS, hypotheses or SESOI.
"""

from __future__ import annotations

import csv
import json

import _bootstrap_path  # noqa: F401
import numpy as np

from src_v3.benchmarks import (
    GAP_SEMANTICS,
    LAYER_SEMANTICS,
    benchmark_prefixes,
    cell_structural_diagnostics,
    f_intervention_for_system,
    pseudo_true_targets,
)
from src_v3.design import MODULE_ROOT, load_design, rng_for, seed_list, v3_all_cells
from src_v3.diagnostics import RECOMBINATION_SEMANTICS
from src_v3.modes import RNG_NAMED, SEED_ORTHOGONAL
from src_v3.rng import StreamBank
from src_v3 import dgp
from src_v3.evaluation import scenario_options
from src_v3.observations import make_observations

OUT = MODULE_ROOT / "outputs" / "benchmarks"
BANNER = "PRE-DEFINED BENCHMARK DIAGNOSTICS -- NOT A V3 ANALYSIS OUTCOME."


def main() -> int:
    design = load_design()
    cells = v3_all_cells(design)
    if len(cells) != 21:
        raise SystemExit(f"expected 21 cells, found {len(cells)}")
    prefixes = benchmark_prefixes(design)
    seed = seed_list(design, "V3_BENCHMARK")[0]

    rows: list[dict] = []
    convergence_rows: list[dict] = []
    violations: list[dict] = []

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
        if options.get("null_mode") == "matched_local_dynamics":
            system = dgp.as_matched_local_dynamics_null(system)
        streams = StreamBank(int(seed))
        traj = dgp.simulate(design, system, regime, rng_for(int(seed)), options, streams=streams)
        bundle = make_observations(
            design, system, traj, regime, rng_for(int(seed)), streams=streams
        )

        structural = cell_structural_diagnostics(design, regime, system, traj)
        f_int = f_intervention_for_system(design, system, traj, bundle)
        f_tr = pseudo_true_targets(design, regime, RNG_NAMED, SEED_ORTHOGONAL)
        convergence = f_tr.pop("F_train_convergence", [])
        for entry in convergence:
            convergence_rows.append({"cell_id": cell_id, **entry})

        row = {
            "cell_id": cell_id,
            "block": (regime.extra or {}).get("block", ""),
            "rng_mode": RNG_NAMED,
            "system_seed_mode": SEED_ORTHOGONAL,
            "cadence": regime.cadence,
            "topology": regime.topology,
            **structural,
            **f_int,
            **f_tr,
            "F_train_is_monte_carlo": True,
            "F_intervention_is_deterministic": True,
            "gap_representation_to_train_true": float(
                f_tr["F_train_true"] - f_int["F_intervention_all"]
            ),
            "gap_train_true_to_train_obs": float(f_tr["F_train_obs"] - f_tr["F_train_true"]),
        }
        rows.append(row)

        # Hard invariant: the frozen all-node NIRE can never beat the exact
        # own-pumping-only representational floor.
        floor = float(f_int["neighbor_unmodeled_floor"])
        all_nire = float(f_int["F_intervention_all"])
        if np.isfinite(floor) and np.isfinite(all_nire) and all_nire < floor - 1e-9:
            violations.append(
                {"cell_id": cell_id, "kind": "floor_violation", "all": all_nire, "floor": floor}
            )
        if not bool(f_int["F_intervention_global_certified"]):
            violations.append(
                {
                    "cell_id": cell_id,
                    "kind": "global_certification_failed",
                    "cross_check": f_int["F_intervention_cross_check_abs_delta"],
                }
            )
        print(
            f"{cell_id:14s} F_int_all={all_nire:.6f} F_int_pumped={f_int['F_intervention_pumped']:.3e} "
            f"floor={floor:.6f} F_train_true={f_tr['F_train_true']:.6f} "
            f"F_train_obs={f_tr['F_train_obs']:.6f}"
        )

    OUT.mkdir(parents=True, exist_ok=True)
    fields = sorted({k for r in rows for k in r})
    with open(OUT / "BENCHMARKS_V3.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    conv_fields = sorted({k for r in convergence_rows for k in r})
    with open(
        OUT / "BENCHMARK_CONVERGENCE_V3.csv", "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=conv_fields)
        writer.writeheader()
        writer.writerows(convergence_rows)

    worst: dict[str, dict] = {}
    if len(prefixes) >= 2:
        tag = f"{prefixes[-2]}_to_{prefixes[-1]}"
        for key in (
            "F_train_true_nire",
            "F_train_obs_nire",
            "F_train_true_a_pumped",
            "F_train_obs_a_pumped",
            "F_train_true_beta_q_pumped",
            "F_train_obs_beta_q_pumped",
        ):
            field = f"delta_{key}_{tag}"
            candidates = [
                (abs(float(r[field])), r["cell_id"], float(r[field]))
                for r in rows
                if field in r and np.isfinite(float(r[field]))
            ]
            if candidates:
                magnitude, cell_id, signed = max(candidates)
                worst[key] = {
                    "prefix_step": tag,
                    "worst_cell": cell_id,
                    "worst_signed_delta": signed,
                    "worst_abs_delta": magnitude,
                }

    payload = {
        "banner": BANNER,
        "n_cells": len(rows),
        "benchmark_pool": "V3_BENCHMARK",
        "benchmark_pool_n": int(design["seeds"]["pools"]["V3_BENCHMARK"]["n_seeds"]),
        "benchmark_convergence_prefixes": list(prefixes),
        "layer_semantics": LAYER_SEMANTICS,
        "gap_semantics": GAP_SEMANTICS,
        "recombination_semantics": RECOMBINATION_SEMANTICS,
        "decomposition_is_additive": False,
        "decomposition_note": (
            "Nested benchmark comparisons only. The frozen NIRE is a mean over included nodes of "
            "per-node ratios of L2 norms; that algebra does not license an additive error "
            "decomposition."
        ),
        "worst_last_prefix_step_changes": worst,
        "invariant_violations": violations,
        "V3_ANALYSIS_REPLICATES_RUN": 0,
        "non_inferential": True,
        "rows": rows,
        "convergence": convergence_rows,
    }
    with open(OUT / "BENCHMARKS_V3.json", "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)
        handle.write("\n")

    if violations:
        for entry in violations:
            print("INVARIANT VIOLATION", entry)
        raise SystemExit("benchmark invariant violation; STOP")
    print(f"benchmarks ok for {len(rows)} cells; prefixes {list(prefixes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
