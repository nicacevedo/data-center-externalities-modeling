#!/usr/bin/env python3
"""Stage 2: SGI_G0 deterministic implementation sanity.

Refuses to run if the design hash does not match the freeze. If SGI_G0 fails, no downstream
scientific conclusion is valid and the pipeline must stop.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import _bootstrap_path  # noqa: F401
import numpy as np

from groundwater_identifiability_synthetic.src.design import (
    MODULE_ROOT,
    code_hash,
    design_hash,
    load_design,
    resolve_regime,
    seed_list,
)
from groundwater_identifiability_synthetic.src.evaluation import (
    _nanmax,
    _nanmean,
    evaluate_g0,
    run_replicate,
)

OUTPUTS = MODULE_ROOT / "outputs"
PROVENANCE = OUTPUTS / "provenance"


def require_frozen_design() -> dict:
    freeze_path = PROVENANCE / "DESIGN_FREEZE.json"
    if not freeze_path.exists():
        raise SystemExit("design is not frozen; run scripts/freeze_protocol.py first")
    with open(freeze_path, "r", encoding="utf-8") as handle:
        freeze = json.load(handle)
    current = design_hash()
    if current != freeze["design_hash"]:
        raise SystemExit(
            f"DESIGN HASH MISMATCH\n  frozen : {freeze['design_hash']}\n  current: {current}\n"
            "Scientific design changed after freeze. Create design_v2 and rerun."
        )
    # A code change after freeze does NOT require design_v2, but it does invalidate outputs,
    # so it must be visible rather than silent.
    running_code_hash = code_hash()
    if running_code_hash != freeze["code_hash"]:
        print(
            "WARNING: code changed since freeze.\n"
            f"  frozen code_hash : {freeze['code_hash']}\n"
            f"  running code_hash: {running_code_hash}\n"
            "  Outputs from before this change are invalid and must be regenerated."
        )
    freeze["code_hash_at_run"] = running_code_hash
    return freeze


def main() -> int:
    design = load_design()
    freeze = require_frozen_design()

    spec = design["gates"]["SGI_G0"]["required_cells"]["C_G0"]
    regime = resolve_regime(
        design, "C_G0", spec["scenario"], spec["topology"], overrides=spec.get("overrides")
    )
    seeds = seed_list(design, design["gates"]["SGI_G0"]["seed_pool"])

    records = [run_replicate(design, regime, seed) for seed in seeds]
    result = evaluate_g0(design, records)
    result["design_hash"] = freeze["design_hash"]
    result["code_hash_at_freeze"] = freeze["code_hash"]
    result["code_hash_at_run"] = freeze["code_hash_at_run"]
    result["seeds"] = seeds
    result["regime"] = {
        "cadence": regime.cadence,
        "topology": regime.topology,
        "memory": regime.memory,
        "pumping_quality": regime.pumping_quality,
        "recharge_quality": regime.recharge_quality,
        "snr_head": regime.snr_head,
        "process_noise_sd": regime.process_noise_sd,
    }
    def mean_of(key: str) -> float:
        return _nanmean(r.get(key, np.nan) for r in records)

    result["identifiability"] = {
        "condition_number_L_mean": mean_of("condition_number_L"),
        "smallest_singular_value_L_mean": mean_of("smallest_singular_value_L"),
        "max_vif_L_mean": mean_of("max_vif_L"),
        "pumping_excitation_fraction_L_mean": mean_of("pumping_excitation_fraction_L"),
        "rank_L_mean": mean_of("rank_L"),
        "rank_deficiency_max": _nanmax(r.get("rank_deficiency_max_L", np.nan) for r in records),
        "n_rows_L_mean": mean_of("n_rows_L"),
        "singular_values_note": "per-node singular spectra are in SGI_G0_REPLICATES.csv",
    }
    result["tau_relax_realized"] = float(records[0]["tau_relax_realized"])
    result["cadence_over_tau_relax"] = float(records[0]["cadence_over_tau_relax"])
    result["clip_fraction_max"] = _nanmax(r["clip_fraction"] for r in records)

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    with open(OUTPUTS / "SGI_G0_RESULT.json", "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True, default=float)

    fields = sorted({key for record in records for key in record})
    with open(OUTPUTS / "SGI_G0_REPLICATES.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)

    print(f"SGI_G0 = {'PASS' if result['pass'] else 'FAIL'}  ({len(seeds)} seeds)")
    for name, payload in result["criteria"].items():
        status = "PASS" if payload["pass"] else "FAIL"
        print(f"  {name:26s} {status}  value={payload['value']:.3e} threshold={payload['threshold']:.1e}")
    ident = result["identifiability"]
    print(
        f"  design rank={ident['rank_L_mean']:.0f} deficiency={ident['rank_deficiency_max']:.0f} "
        f"cond={ident['condition_number_L_mean']:.4g} maxVIF={ident['max_vif_L_mean']:.4g} "
        f"pumping_excitation={ident['pumping_excitation_fraction_L_mean']:.4f}"
    )
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
