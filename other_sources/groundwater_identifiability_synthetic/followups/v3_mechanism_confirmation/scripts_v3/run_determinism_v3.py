#!/usr/bin/env python3
"""Deterministic / near-machine sanity using V3_DETERMINISM. Engineering only."""

from __future__ import annotations

import json
from pathlib import Path

import _bootstrap_path  # noqa: F401
import numpy as np

from src_v3.design import MODULE_ROOT, load_design, resolve_regime, seed_list
from src_v3.evaluation import run_replicate
from src_v3.modes import RNG_NAMED, SEED_ORTHOGONAL

OUT = MODULE_ROOT / "outputs" / "determinism"


def main() -> int:
    design = load_design()
    seed = seed_list(design, "V3_DETERMINISM")[0]
    regime = resolve_regime(
        design,
        "DET_S0",
        "S0",
        "single",
        overrides={
            "memory": "MED",
            "cadence": 1,
            "gamma": "NONE",
            "pumping_quality": "P-EXACT",
            "recharge_quality": "R-EXACT",
            "confounding_rho": 0.0,
            "mcar_fraction": 0.0,
            "blocks_per_node": 0,
            "observed_node_fraction": 1.0,
            "snr_head": 0.0,
            "process_noise_sd": 0.0,
        },
    )
    rec = run_replicate(
        design, regime, seed, rng_mode=RNG_NAMED, system_seed_mode=SEED_ORTHOGONAL
    )
    report = {
        "engineering_only": True,
        "seed_pool": "V3_DETERMINISM",
        "rng_mode": rec["rng_mode"],
        "system_seed_mode": rec["system_seed_mode"],
        "g0_max_abs_transition_residual": rec.get("g0_max_abs_transition_residual"),
        "g0_max_abs_relative_coef_error": rec.get("g0_max_abs_relative_coef_error"),
        "g0_storage_relative_error": rec.get("g0_storage_relative_error"),
        "partial_reliability_q": rec.get("partial_reliability_q"),
        "nire_persistent_step_h26_L": rec.get("nire_persistent_step_h26_L"),
        "placebo_false_effect_L": rec.get("placebo_false_effect_L"),
        "A_diag_relative_error_L": rec.get("A_diag_relative_error_L"),
        "B_Q_relative_error_median": rec.get("B_Q_relative_error_median"),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "DETERMINISM_V3.json", "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    # Floating-point exact-recovery tolerances.
    for key in (
        "g0_max_abs_transition_residual",
        "g0_max_abs_relative_coef_error",
        "g0_storage_relative_error",
        "A_diag_relative_error_L",
        "B_Q_relative_error_median",
        "nire_persistent_step_h26_L",
    ):
        val = report[key]
        if val is None or not np.isfinite(val):
            raise SystemExit(f"{key} missing")
        if val > 1e-8:
            raise SystemExit(f"{key}={val} exceeds 1e-8")
    if abs(report["partial_reliability_q"] - 1.0) > 1e-10:
        raise SystemExit("P-EXACT reliability is not 1")
    print("DETERMINISM_V3 ok", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
