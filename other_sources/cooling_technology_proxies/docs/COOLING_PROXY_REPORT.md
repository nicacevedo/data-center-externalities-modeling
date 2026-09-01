# Cooling technology energy–water proxy — pass report

This module is additive under `other_sources/cooling_technology_proxies/`. It does not modify `other_sources/masanet/`. Meta 2023–2024 water holdout files were not read and were not used to choose, fit, or validate cooling architecture.

## Question answered

What cooling technologies can we represent quantitatively, with what energy–water behavior, under what climates, with what uncertainty and empirical support, for Prineville and the downstream optimizer?

**Answer (HIGH confidence as a modeling-capability statement):** we can represent **annual joint** \((\mathrm{PUE},\mathrm{WUE}_{\mathrm{site}})\) as an empirical paired distribution conditional on Lei 2025 cooling label × climate zone × facility class. We **cannot** defensibly claim an hourly weather function for modern liquid cases from public code. Independent measured WUE by those labels is essentially absent. Prineville remains a **multi-scenario identification** problem, not a single-\(k\) calibration.

## Data acquired

| Source | File | Rows | Grain | Tech |
| --- | --- | --- | --- | --- |
| Lei 2025 GitHub `155b0216` | `UEs_16cases.csv` | 19,000 | annual pairs | 12 labels |
| same | `SPEC_2024.xlsx` | 330 | server SPEC | not cooling pairs |
| same | Sobol/SA CSVs + Rmd + notebook | analysis | — | workload water SA |
| User PDFs | Lei 2022 preprint, Lei 2025 paper, LBNL 2024, EU CoC BPG | — | prose/tables | catalog + priors |
| LBNL 2024 microdata | **not found** | — | — | labels only |
| NREL ESIF PUE parquet | **not downloaded** (electricity-only) | — | sub-hourly energy | one HPC site |

## Source reproduction

PASS on CSV semantics and R type-7 5/95 estimator. No typeset quantile table to match. Filename/case-gap and Rmd 17–18 filter documented in `docs/LEI2025_REPRODUCTION.md`.

## Model level

**A+B.** Paired empirical \(F_{k,c,\mathrm{class}}\). Hourly Level D **UNSUPPORTED** for liquid; 2022 hourly air-IT code exists but is a separate masanet experiment.

## Technology disposition

See `results/FINAL_COOLING_PROXY_STATUS.json` for the full matrix. Short form:

- Conventional air-IT (DX, ACC, WCC, AE, WE, adiabatic, dry cooler): **PARTIAL** quantitative proxy (source-rich, independent WUE-poor).
- Liquid IT + dry/adiabatic and liquid IT + WE: **PARTIAL** (pooled subtypes; no public hourly engine).
- Rear-door / cold-plate / immersion as distinct \(k\): **UNSUPPORTED** to unpool.
- Prineville 2011 OA evaporative (no chiller/tower): identified **HIGH** for that design epoch; Lei mapping is approximate (closest large-scale AE+adiabatic air class is not identical to 100% OA / no chiller).
- Prineville later CHW/CRAH: identified **HIGH** that equipment exists; Lei case **LOW**.

## Water boundary

WUE in this module is **onsite conditioning use**. City delivery, reclaimed share, wells, sewer, consumption fraction, and groundwater pumping remain in `analysis/WATER_SOURCE_BRIDGE_GAPS.csv`.

## Computation

Local only (`masanet_lei` Python). No HPC. No Masanet rerun.

## Next step

Use the annual paired lookup in optimization. Do **not** start a new hourly thermodynamic model this cycle. Highest-value missing dataset: **public hourly (or at least monthly) onsite makeup/blowdown meters with known cooling architecture**, independent of Meta 2023–2024 holdout water.
