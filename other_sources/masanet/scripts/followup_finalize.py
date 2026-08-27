#!/usr/bin/env python3
"""Phase 11: FOLLOWUP_V1_STATUS.json and concise summary. No Meta 2023-2024 water."""
from __future__ import annotations

import json
from pathlib import Path

from common import PARENT_REPO, UPSTREAM, UPSTREAM_COMMIT, WORK_ROOT, atomic_write_json, atomic_write_text, set_threads, utcnow
from followup_common import FOLLOWUP, FOLLOWUP_DOCS, SELECTED_CELLS


def _load(p: Path):
    return json.loads(p.read_text()) if p.exists() else None


def _git(cmd):
    import subprocess

    r = subprocess.run(cmd, cwd=str(PARENT_REPO), capture_output=True, text=True)
    return (r.stdout or "").strip()


def main():
    set_threads()
    FOLLOWUP.mkdir(parents=True, exist_ok=True)
    FOLLOWUP_DOCS.mkdir(parents=True, exist_ok=True)
    slurm = _load(WORK_ROOT / "manifests" / "SLURM_FOLLOWUP_V1.json") or {}
    freeze = _load(WORK_ROOT / "manifests" / "FOLLOWUP_V1_FREEZE.json")
    weather = _load(WORK_ROOT / "manifests" / "FOLLOWUP_V1_WEATHER.json")
    cross = _load(FOLLOWUP / "paper_code_crosswalk.json")
    nb = _load(FOLLOWUP / "notebook_pue_sweep.json")
    front = _load(FOLLOWUP / "FRONTIER_CLOSURE_STATUS.json")
    frontv = _load(FOLLOWUP / "frontier_validation_v2.json")
    smoke_s = _load(FOLLOWUP / "annual_smoke_short.json")
    smoke_f = _load(FOLLOWUP / "annual_smoke_full.json")
    cmp_ = _load(FOLLOWUP / "annual_selected_comparison.json")
    rng = _load(FOLLOWUP / "annual_rng.json")
    gate = _load(FOLLOWUP / "MASANET_ANNUAL_CLOSURE_STATUS.json")
    adapter = _load(FOLLOWUP / "adapter_status.json")
    prv = _load(FOLLOWUP / "prineville_weather_smoke.json")

    failed = list((gate or {}).get("failed_tests") or [])
    warnings = list((gate or {}).get("warnings") or [])
    if (nb or {}).get("status") == "NOTEBOOK_VALUE_NOT_REACHED":
        warnings.append("Stored demo.ipynb PUE was not reached in seeds 0:9999; treated as stale/non-reproducible.")
    if (front or {}).get("qualitative_change"):
        warnings.append("Frontier F0/F1/F2 qualitative conclusion CHANGED after missing-time correction.")

    pieces = [
        (cross or {}).get("status"),
        (gate or {}).get("status"),
        (adapter or {}).get("status") if adapter else "NOT_RUN",
        (prv or {}).get("status") if prv else "NOT_RUN",
    ]
    if "FAIL" in pieces or (gate or {}).get("status") == "FAIL":
        overall = "FAIL"
    elif "NOT_RUN" in pieces or (gate or {}).get("status") == "PARTIAL":
        overall = "PARTIAL"
    else:
        overall = "PASS"

    key_paths = {
        "freeze": str(WORK_ROOT / "manifests" / "FOLLOWUP_V1_FREEZE.json"),
        "weather": str(WORK_ROOT / "manifests" / "FOLLOWUP_V1_WEATHER.json"),
        "crosswalk_csv": str(WORK_ROOT / "docs" / "followup_v1" / "PAPER_CODE_CASE_CROSSWALK.csv"),
        "frontier_qc_v2": str(FOLLOWUP / "frontier_qc_v2.json"),
        "frontier_validation_v2": str(FOLLOWUP / "frontier_validation_v2.json"),
        "annual_comparison": str(FOLLOWUP / "annual_selected_comparison.json"),
        "annual_rng": str(FOLLOWUP / "annual_rng.json"),
        "annual_gate": str(FOLLOWUP / "MASANET_ANNUAL_CLOSURE_STATUS.json"),
        "adapter": str(FOLLOWUP / "adapter_status.json"),
        "prineville": str(FOLLOWUP / "prineville_weather_smoke.json"),
    }
    status = {
        "overall_status": overall,
        "repo_head": _git(["git", "rev-parse", "HEAD"]),
        "upstream_commit": UPSTREAM_COMMIT,
        "final_paper_source_status": (cross or {}).get("final_paper_source_status", "PREPRINT_USED_JOURNAL_CLOSED"),
        "frontier_gap_fix_status": (front or {}).get("status"),
        "notebook_pue_discrepancy_status": (nb or {}).get("status"),
        "paper_code_crosswalk_status": (cross or {}).get("status"),
        "parameter_range_status": (cross or {}).get("status"),
        "weather_source_status": (weather or {}).get("status"),
        "annual_smoke_status": (smoke_f or {}).get("status") or (smoke_s or {}).get("status"),
        "annual_selected_cells": SELECTED_CELLS,
        "annual_reproduction_status": (cmp_ or {}).get("status"),
        "annual_rng_status": (rng or {}).get("status"),
        "paper_aggregation_identity_status": (gate or {}).get("paper_aggregation_identity_status"),
        "project_weighted_aggregation_status": (adapter or {}).get("status"),
        "adapter_status": (adapter or {}).get("status", "NOT_RUN"),
        "prineville_weather_smoke_status": (prv or {}).get("status", "NOT_RUN"),
        "did_read_meta_2023_2024_water": False,
        "warnings": warnings,
        "failed_tests": failed,
        "job_ids": slurm.get("job_ids"),
        "key_result_paths": key_paths,
        "single_next_scientific_step": (
            "If annual envelopes are consistent: couple the adapter to a workload→P_IT scenario "
            "with an explicit control policy, keeping conditioning-water components separate from source/groundwater."
            if (gate or {}).get("proceed_to_adapter")
            else "Do not translate into the project model until the annual gate is resolved (mapping, UE envelopes, or RNG)."
        ),
        "timestamp_utc": utcnow(),
        "freeze_present": freeze is not None,
        "frontier_f1_beats_f0": None if not frontv else frontv.get("reduced_model", {}).get("pointwise_F1_beats_F0_unchanged"),
    }
    atomic_write_json(FOLLOWUP / "FOLLOWUP_V1_STATUS.json", status)

    c1 = ((prv or {}).get("cases") or {}).get("1") or {}
    c2 = ((prv or {}).get("cases") or {}).get("2") or {}
    mapping_lines = []
    if cross:
        for row in range(1, 11):
            from followup_common import PAPER_CASES

            m = PAPER_CASES[row]
            mapping_lines.append(
                f"- Case {row} ({m['size_class']}): {m['paper_cooling_configuration']} → `{m['top_level_code_function']}`"
                + (f" (shared with case {m['shared_function_with_other_case']})" if m["shared_function_with_other_case"] else "")
            )
    summary = f"""# Follow-up v1 summary

Evidence-only. First-run artifacts were not overwritten. Meta 2023–2024 water was not read.

## 1. Is Lei–Masanet sufficiently reproduced at annual scale?

Annual gate: **{(gate or {}).get('status')}**. Selected-cell vs `UE.xlsx`: **{(cmp_ or {}).get('status')}**. Smoke: **{(smoke_f or {}).get('status')}**. Paper-style mean vs equal-Δt energy ratio identity: **{(gate or {}).get('paper_aggregation_identity_status')}**.

We did not rerun all 10×15 cells. Consistency is claimed only for the locked diagnostic subset.

## 2. What do the 10 cases map to?

Final article is closed OA; ranges are from the 2022 preprint Table 3 + public code. Bundled `UE.xlsx` (15 zones, 300 rows) is the reproduction target.

{chr(10).join(mapping_lines) if mapping_lines else '(crosswalk not available)'}

Cases 5 and 8 share `PUE_WUE_Chiller`; 7 and 9 share `PUE_WUE_AIRChiller`; they differ by Table 3 ranges. Cases 8–9: Table 2 lists isothermal humidification but the shared functions still take a humidification pump (medium confidence).

RH table labels are physically reversed: high-RH numbers → code `RH_up`; low-RH → `RH_lw`.

## 3. Are bundled annual envelopes consistent with the pinned implementation?

**{(cmp_ or {}).get('status')}**. Classification uses bootstrap / extra LHS quantile-estimator variability, not an invented percent tolerance.

## 4. Is internal RNG material at annual scale?

**{(rng or {}).get('status')}**. PUE ratio seed/facility = {(rng or {}).get('ratio_seed_over_facility_PUE')}; WUE ratio = {(rng or {}).get('ratio_seed_over_facility_WUE')}. Upstream stochastic helpers were not modified.

## 5. What can we safely transfer?

If the gate allows the adapter: a **normalized climate/technology intensity model**

`(P_IT, weather, case k, theta_k) → (P_fac = P_IT * PUE, W_conditioning = P_IT * WUE, explicit CT/humidification components)`.

`Chiller_load` is a scenario parameter, not a dynamic function of `P_IT`. Variable-IT annual PUE/WUE must be energy-weighted, not an unweighted mean of hourly intensities. Water components are conditioning-side only (humidification/adiabatic, CT evaporation, windage, draw-off). They are not groundwater, municipal source, or consumption-only.

## 6. What remains unsupported?

Workload → `P_IT`; dynamic part-load vs actual IT; liquid cooling; conditioning-water → source/return; source pumping → groundwater; operations/siting optimization; the full 150-cell paper table; sklearn 0.23 unless a later COP discrepancy appears.

## 7. What did the corrected Frontier analysis change?

Missing expected 10-minute timestamps (first run counted NaT rows only): coverage={(front or {}).get('coverage_fraction')}, missing hours={(front or {}).get('missing_hours')}. F1-vs-F0 qualitative change flag: **{(front or {}).get('qualitative_change')}**. Thermal `ρ c_p V ΔT` check is published-formula reproduction, not independent conservation. F2 remains a contemporaneous oracle. Closure: **{(front or {}).get('status')}**.

## 8. Large-scale cases under Prineville 2022 weather (no Meta water)

Year 2022 because the canonical pipeline holdout is 2023–2024. `P_IT=1`, 50 LHS draws, cases 1 and 2 only. Not a ranking and not a calibration.

- Case 1 PUE 5/50/95: {c1.get('PUE_q05')}, {c1.get('PUE_q50')}, {c1.get('PUE_q95')}; WUE 5/50/95: {c1.get('WUE_q05')}, {c1.get('WUE_q50')}, {c1.get('WUE_q95')}
- Case 2 PUE 5/50/95: {c2.get('PUE_q05')}, {c2.get('PUE_q50')}, {c2.get('PUE_q95')}; WUE 5/50/95: {c2.get('WUE_q05')}, {c2.get('WUE_q50')}, {c2.get('WUE_q95')}

## 9. Single highest-value next experiment

{status['single_next_scientific_step']}
"""
    atomic_write_text(FOLLOWUP_DOCS / "FOLLOWUP_V1_SUMMARY.md", summary)
    print(json.dumps({"overall_status": overall, "summary": str(FOLLOWUP_DOCS / "FOLLOWUP_V1_SUMMARY.md")}, indent=2))


if __name__ == "__main__":
    main()
