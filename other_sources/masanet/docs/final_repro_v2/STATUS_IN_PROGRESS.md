# Final Lei–Masanet closure (v2) — in progress

This file will be replaced by `FINAL_MASANET_SUMMARY.md` when the 160 publication-scale replications and RNG jobs finish. It is **not** a PASS/PARTIAL/FAIL verdict.

## Already closed (do not rerun)

- V1 annual gate: **FAIL** (`results/followup_v1/MASANET_ANNUAL_CLOSURE_STATUS.json`). Adapter and Prineville V1 jobs were CANCELLED on `afterok`.
- V1 cells 2×1A, 7×8, 10×5A: consistent under the V1 5th/95th bootstrap (no extra LHS).
- V1 cells 1×1A, 2×8, 5×2A: INCONSISTENT (full 50-rep V2 retest).
- Positive control chosen from V1 only: **case 7×8**, 10 replications.
- Notebook stored PUE 1.33916: **NON_REPRODUCIBLE_STORED_SNAPSHOT**. Clean kernel and seed-2025 both sit in the 1.4445 island; WUE matches stored. Seeds 0:9999 were **not** rerun.
- `UE.xlsx` labels are **5th/95th quantiles**, not min/max. Preprint §4.3 names 5th quantiles as practical minima. Original LHS seed/library are not in the public clone.
- Chicago weather is TMY3 O’Hare WMO 725300 (intended 5A station).
- User-requested `dc_externalities` cannot import sklearn/CoolProp. Science uses `masanet_lei` + `PYTHONNOUSERSITE=1` (scipy 1.7.3).

## Running

160 tasks × 50 LHS × 8760 h, frozen in `manifests/final_repro_v2/TASK_MANIFEST.json` (`tasks_sha256` sidecar). Not modified after results became visible.

Do not tune ranges, weather, seeds, or upstream physics to change the eventual verdict.
