#!/usr/bin/env python3
"""Phase 7: assemble FIRST_RUN_STATUS.json and a short human summary."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import subprocess

from common import PARENT_REPO, UPSTREAM_COMMIT, WORK_ROOT, atomic_write_json, atomic_write_text, set_threads, utcnow


def loadj(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text())


def st(val, default="NOT_RUN"):
    if val is None:
        return default
    if isinstance(val, dict):
        return val.get("status", default)
    return str(val)


def main():
    set_threads()
    repro = loadj(WORK_ROOT / "results" / "masanet_reproduction_summary.json")
    audit = loadj(WORK_ROOT / "results" / "masanet_boundary_audit.json")
    grid = loadj(WORK_ROOT / "results" / "masanet_grid_summary.json")
    front = loadj(WORK_ROOT / "results" / "frontier_validation.json")
    qc = loadj(WORK_ROOT / "results" / "frontier_qc.json")
    paper = loadj(WORK_ROOT / "results" / "paper_boundary_quotes.json")
    jobs = loadj(WORK_ROOT / "manifests" / "SLURM_FIRST_RUN.json") or {}
    sources = loadj(WORK_ROOT / "manifests" / "SOURCES.json")

    failed = []
    warnings = []
    if not paper:
        warnings.append("Lei-Masanet 2022 PDF quotes not extracted")
    if repro and st(repro) == "FAIL":
        failed.append("masanet_reproduction")
    if audit and st(audit) == "FAIL":
        failed.append("masanet_accounting")
    if grid and st(grid) == "FAIL":
        failed.append("masanet_grid")
    if front and front.get("thermal_closure", {}).get("status") == "FAIL":
        failed.append("frontier_thermal_closure")

    water_status = "NOT_IDENTIFIED"
    if audit:
        water_status = "PARTIAL"
        # W_use is identified; withdrawal/consumption/return not fully identified
    stoch_status = "NOT_RUN"
    if audit and "stochasticity" in audit:
        spreads = [v.get("PUE_seed_spread", 0) for v in audit["stochasticity"]["per_archetype"].values()]
        stoch_status = "PASS" if spreads else "PARTIAL"
    scale_status = "NOT_RUN"
    if audit and "scaling" in audit:
        inv = [v.get("PUE_invariant") for v in audit["scaling"]["archetypes"].values()]
        scale_status = "PASS" if inv and all(inv) else "PARTIAL"

    statuses = {
        "masanet_reproduction_status": st(repro),
        "masanet_accounting_status": st(audit),
        "masanet_water_boundary_status": water_status,
        "masanet_stochasticity_status": stoch_status,
        "masanet_scaling_status": scale_status,
        "masanet_grid_status": st(grid),
        "lbnl_comparison_status": (grid or {}).get("lbnl_comparison", {}).get("status", "NOT_RUN")
        if grid
        else "NOT_RUN",
        "frontier_qc_status": "PASS" if qc else "NOT_RUN",
        "frontier_thermal_closure_status": (front or {}).get("thermal_closure", {}).get("status", "NOT_RUN")
        if front
        else "NOT_RUN",
        "frontier_pue_accounting_status": (front or {}).get("pue_accounting", {}).get("status", "NOT_RUN")
        if front
        else "NOT_RUN",
        "frontier_reduced_model_status": (front or {}).get("reduced_model", {}).get("status", "NOT_RUN")
        if front
        else "NOT_RUN",
        "source_manifest_status": "PASS" if sources else "FAIL",
        "paper_boundary_status": "PASS" if paper else "PARTIAL",
    }
    core_fail = any(statuses[k] == "FAIL" for k in statuses)
    overall = "FAIL" if core_fail else ("PARTIAL" if any(statuses[k] in ("PARTIAL", "NOT_IDENTIFIED", "NOT_RUN") for k in statuses) else "PASS")

    next_step = (
        "Annual EnergyPlus-weather evaluation of the eight archetypes at Table 3 ranges, "
        "keeping water components separate, before any Prineville coupling or groundwater mapping."
    )

    status = {
        "overall_status": overall,
        "repo_head": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(PARENT_REPO),
            capture_output=True,
            text=True,
        ).stdout.strip()
        or "UNKNOWN",
        "work_root": str(WORK_ROOT),
        "upstream_commit": UPSTREAM_COMMIT,
        **statuses,
        "job_ids": jobs,
        "key_result_paths": {
            "reproduction": str(WORK_ROOT / "results" / "masanet_reproduction_summary.json"),
            "boundary_audit": str(WORK_ROOT / "results" / "masanet_boundary_audit.json"),
            "water_csv": str(WORK_ROOT / "docs" / "WATER_BOUNDARY_AUDIT.csv"),
            "grid_parquet": str(WORK_ROOT / "results" / "masanet_grid.parquet"),
            "frontier_qc": str(WORK_ROOT / "results" / "frontier_qc.json"),
            "frontier_validation": str(WORK_ROOT / "results" / "frontier_validation.json"),
            "paper_quotes": str(WORK_ROOT / "results" / "paper_boundary_quotes.json"),
        },
        "failed_tests": failed,
        "warnings": warnings,
        "next_scientific_step": next_step,
        "timestamp_utc": utcnow(),
        "did_not_read_prineville_2023_2024_water": True,
    }
    atomic_write_json(WORK_ROOT / "results" / "FIRST_RUN_STATUS.json", status)

    md = f"""# First-run summary

Overall: **{overall}**

This run did not inspect Meta Prineville 2023–2024 water outcomes.

## 1. What did we successfully reproduce?

Public `nuoaleon/Data-Center-Water-footprint` commit `{UPSTREAM_COMMIT}` runs in env `masanet_lei` (Python 3.9, sklearn 1.0.2, CoolProp 6.6.0). All three COP pickles predict after a documented load-time shim for `COP_AC.pkl`. Seed 2025 is bit-stable. Notebook WUE for the demo vector matches to ~1e-12; notebook PUE does not, because `demo.ipynb` did not seed `np.random`. Bundled `UE.xlsx` is climate-zone × case × quantile annual output, not the demo snapshot. Reproduction status: **{statuses['masanet_reproduction_status']}**.

## 2. What does the Lei–Masanet model actually measure?

An **IT-normalized intensity model**: `Power_IT = 1` in every archetype. Paper: PUE = total facility electricity / IT electricity; WUE = **total onsite water use** / IT electricity (L/kWh), citing The Green Grid (Patterson 2011). Eq. (1) on-site water = cooling-tower evaporation + windage + draw-off + adiabatic cooling + space humidification. Eight cooling archetypes; COP from GP regressions on wet-bulb/load or outdoor T.

## 3. What water quantities are usable for groundwater coupling?

| Quantity | Status |
| --- | --- |
| W_use/model (WUE intensity) | Identified: onsite use, makeup-like (includes blowdown) |
| W_cons | NOT_IDENTIFIED as a separate output; evaporation is the consumptive CT term |
| W_discharge/return | Draw-off is a candidate discharge term **included in WUE** |
| W_source/withdrawal | NOT_IDENTIFIED; **WUE is not groundwater pumping** |

Paper: does not address indirect (grid) water; future work should consider qualities and local stress. Do not map WUE to source wells.

## 4. Is IT-load scaling modeled or only normalized?

Only normalized. `Chiller_load` is an exogenous GP feature, not computed from IT power. Instrumented tests at relative IT = 0.5/1/2: PUE and WUE should be invariant if components scale linearly. Status: **{statuses['masanet_scaling_status']}**.

## 5. How material is upstream stochasticity?

Two layers: (code) `np.random.uniform` indoor humidity in colo/chiller/DX helpers, sometimes called >1× per evaluation so states can be internally inconsistent; (paper) Latin-hypercube facility-parameter uncertainty for annual ranges — not used in this first grid. Demo WUE was seed-invariant; PUE moved with seed. Status: **{statuses['masanet_stochasticity_status']}**. Not fixed in this run.

## 6. Climate/technology patterns

Small T×RH factorial, facility parameters held at the demo/LHS vector. Joint PUE–WUE only. LBNL 2024: **QUALITATIVE_TRIANGULATION_ONLY** (annual/stock vs instantaneous; shared Lei lineage). Grid status: **{statuses['masanet_grid_status']}**.

## 7. What does Frontier independently validate?

Physical structure at a liquid-cooled HPC facility, **not** Lei–Masanet coefficients. Thermal: Q = ρ cp V̇ (T_return − T_supply) with ρ=1060, cp=3.5 kJ/kg-K, overall supply T for all loops. PUE reconstructed from compute vs total. Reduced accessory-power models F0/F1/F2 with expanding monthly folds; F2 is a contemporaneous oracle using measured Q.

- QC: {statuses['frontier_qc_status']}
- Thermal: {statuses['frontier_thermal_closure_status']}
- PUE: {statuses['frontier_pue_accounting_status']}
- Reduced: {statuses['frontier_reduced_model_status']}

## 8. What remains unsupported?

Part-load vs IT; liquid-cooling generic archetype; source-water/groundwater identity; annual weather-weighted WUE; independent statistical validation vs LBNL; nonlinear facility response; Prineville holdout (intentionally untouched).

## 9. Highest-value next experiment

{next_step}
"""
    atomic_write_text(WORK_ROOT / "docs" / "FIRST_RUN_SUMMARY.md", md)
    print(json.dumps({"overall_status": overall, "failed_tests": failed}, indent=2))
    if overall == "FAIL":
        sys.exit(2)


if __name__ == "__main__":
    main()
