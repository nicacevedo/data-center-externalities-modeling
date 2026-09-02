# ESIF measured facility-overhead experiment — closed report

CPU `FROZEN_PASS_WITH_DOMAIN_RESTRICTIONS` and H100 `FROZEN_PASS_WITH_DOMAIN_RESTRICTIONS` were not modified. No F0–F4 refit. TEST was evaluated once and left untouched. This document is the canonical scientific close of the **electrical** overhead layer.

Canonical status: `analysis/FINAL_ESIF_FACILITY_OVERHEAD_STATUS.json`.

## 1. Provenance

- DOI `10.7799/3015212` (NLR HPC Facility PUE Data)
- Power parquet SHA-256 `19cd12405dde9144b1a360e8c8418666c399a3d0d15a7f846880d71ab22f9dd4`
- Weather parquet SHA-256 `97b424993fa77a15117fb2c4659a2c327fc83280f943fab47d9036260289a6a0`
- README SHA-256 `f69d32f1af598c48a899d54d48b26def2ca78a0c11d848516169570ecae4c029`
- Primary input: measured `it_power_kw` + outside weather. Not Kestrel replay, H100 replay, TDP, M100, or Meta.

Clock: `ALIGNED_SAME_CLOCK_NEAREST_CADENCE` (nearest p50 = 12 s; 60 s tolerance frozen from cadence). Timezone UTC vs Denver was not reopened.

## 2. Frozen design

- Native ~60 s for QA/identity/energy integration; **hourly** modeling resolution; daily for evaluation.
- Coverage ≥90% per hour; gaps >180 s do not contribute energy.
- DEV: 2016-06-12 06:00 → 2024-08-29 03:00 (58,482 h)
- TEST: 2024-08-29 03:00 → 2025-08-29 03:00 (8,470 h, 352 days)
- 46 expanding DEV folds (180-day minimum train, 60-day blocks). TEST unused for selection.
- Hierarchy F0–F4 only; parsimony ~1% relative daily-energy WAPE; F2_PHYS preferred to F2_RAW if equivalent.
- PUE derived, never fitted.

## 3. Accounting closure

Published fields close source PUE:

`pue ≈ (IT + cooling + HVAC + pump + plug_and_light) / IT`

n = 4,432,570 native samples; median difference 0; MAE 0.00019.

`PUE_ACCOUNTING_CLOSURE = PASS` means **same-source accounting identity**, not independent physical PUE validation.

## 4. Selected specifications (DEV/CV; frozen)

| Target | Spec | CV daily-energy WAPE | Notes |
| --- | --- | --- | --- |
| cooling | **F4** | 0.337 | F0 0.338; F4 wins on energy bias |
| HVAC | **F0** | 0.147 | intercept 19.49 kW; F1–F4 did not beat F0 on **equal-weight** folds |
| pumps | **F4** | 0.276 | IT + weather |
| plug/light | **F2_PHYS** | 0.329 | intercept ~3.52 kW; IT coefficient ≈ 0 |
| direct aux (diagnostic) | **F2_PHYS** | 0.195 | DEV component-sum 0.397 vs direct 0.388 → keep decomposition |

DEV HVAC F0 **full-window** daily-energy WAPE is already 0.986: equal-weight CV hid the late-2024 shift (see §11). Specs were **not** changed after that observation.

## 5. Held-out TEST (untouched)

| Target | n | Mean kW | MAE | RMSE | WAPE | Energy bias | R² | Daily energy WAPE |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cooling | 8470 | 12.27 | 8.14 | 9.56 | 0.663 | +0.423 | 0.410 | 0.563 |
| HVAC | 8470 | **134.10** | 114.61 | 120.43 | **0.855** | **−0.855** | **−9.60** | 0.855 |
| pumps | 8470 | 37.83 | 6.66 | 8.53 | 0.176 | −0.082 | **−0.736** | 0.174 |
| plug/light | 8470 | 3.76 | 1.21 | 1.55 | 0.321 | −0.138 | 0.138 | 0.217 |
| aux component-sum | 8470 | 187.96 | 113.03 | 119.15 | **0.601** | **−0.601** | −10.09 | 0.602 |
| aux direct | 8470 | 187.96 | 89.01 | 98.18 | 0.474 | −0.474 | −6.53 | 0.474 |

7-day block bootstrap TEST aux WAPE p05/p50/p95 = 0.580 / 0.600 / 0.623.

## 6. Cooling interpretation

F4 is the protocol-selected DEV/CV spec. Coefficients were not forced to a preconceived sign: `cooling_kw` includes outdoor fans, trace heaters, and the ~2.67 kW filter pump, so cold-weather electricity can be non-monotonic.

TEST hourly WAPE 0.66 and energy bias +0.42: F4 is **not** a strongly validated transferable cooling law. Residual ACF (DEV, preserved exactly): 1 h = 0.8288581320055117, 6 h = 0.5862897847418319, 24 h = 0.5458957558201557. Optional lagged-input fallback was **not** run. `COOLING_DYNAMICS_UNRESOLVED = true`. `protocol_deviation = false`.

## 7. HVAC regime failure

Stationary IT+weather **fails**. TEST mean HVAC 134 kW vs F0 19.5 kW.

Post-hoc localization (not a fitted breakpoint): HVAC remains ~12 kW through **2024-03-27** at IT ~3.6 MW, then steps to ~200 kW on **2024-03-29** with IT unchanged. AUX and source PUE rise with HVAC. Other published components do not fall enough to support category reclassification. Native HVAC is not a new integer channel or ×2/×10 rescaling.

Disposition: `PHYSICAL_OR_OPERATIONAL_INFRASTRUCTURE_CHANGE_SUPPORTED_EXACT_CAUSE_UNRESOLVED`. Compatible with NLR-documented 2024 5→7.5 MW electrical **and** cooling-capacity work. **Not** claimed: GPU-caused, Eagle-caused, or new-fan-wall HVAC. Original ESIF design already had fan walls.

`HVAC_STATIONARY_IT_WEATHER_MODEL = FAIL`. `HVAC_REGIME_SHIFT = PASS` (existence). No epoch HVAC model fitted.

## 8. Pumps: aggregate vs hourly

Do not globally call pump prediction PASS. TEST hourly R² is **negative**. Daily-energy WAPE 0.17 and energy bias −0.08 show **useful aggregate energy structure** from IT/weather. Hourly dynamics are **not** reproduced.

`PUMP_POWER_MODEL = PARTIAL`  
`PUMP_AGGREGATE_ENERGY_STRUCTURE = PARTIAL`  
`PUMP_HOURLY_DYNAMICS = FAIL`

## 9. Auxiliary / PUE masking

Component-sum TEST WAPE 0.60 is HVAC-dominated. Direct-total F2_PHYS is better by error cancellation (WAPE 0.47) and remains diagnostic only.

Derived PUE (not fitted): hourly MAE 0.052; energy-weighted 1.076 vs 1.030 (bias −0.046); facility energy 22.51 vs 21.55 GWh (−4.3%). Relative PUE error is modest **because aux ≪ IT**. That masks the HVAC kW failure.

`PUE_RECONSTRUCTION = PARTIAL`. `STATIONARY_IT_WEATHER_TOTAL_AUX_HYPOTHESIS = FAIL`.

## 10. Thermosyphon correction

Prior `EPOCH_STABILITY.json` stated commissioning `NOT_IN_SAMPLE` because TSC supposedly predated 2015. **False.**

Sickinger et al. (NREL/TP-2C00-72196): installed/operational **August 2016**; first full year **2016-09-01 through 2017-08-31**. Common sample begins 2016-06-12.

Electrical overlap is real. First-full-year mean IT 885 kW vs Sickinger 888 kW; mean PUE 1.034, consistent with “TSC did not degrade energy efficiency.” Pre-period is ~7 summer weeks: **no causal TSC electrical effect** is estimated. August is transitional (Sickinger also notes an unrelated August 2016 planned-outage PUE jump).

## 11. Validation lesson (future protocol only)

The original 46-fold equal-weight CV is **unchanged**. It underweighted a late persistent HVAC regime occupying few DEV folds. Future facility time-series experiments should **predeclare both**:

1. mean rolling-origin CV performance;
2. latest-regime / final-pretest-epoch stability.

Do not apply this retroactively here.

## 12. Heat reuse residual

TEST `energy_reuse` is present on all 8470 h. Quartile mean aux residuals 98–123 kW vs overall |resid| 113 kW → `LOW_FOR_TESTED_DIAGNOSTIC`. Not added as a predictor. This does **not** imply heat reuse is unimportant thermally.

## 13. Project implications

1. Minimum supported overhead **structure**: `f(IT, weather, A_t, S_t)` with component meters that **account** PUE. Stationary IT+weather is **not** sufficient for total aux.
2. Unnecessary as universal laws: HVAC~IT on 2016–2023; F3/F4 for plug; direct PUE fit; energy_reuse as electrical predictor; 8-GPU/H100 replay as facility IT.
3. Generic IT/cooling/other split: **accounting yes**; chiller-like cooling electricity **no**.
4. Prineville gray-box: review regime-dependent fan/HVAC intercepts and pump **aggregate** IT/Twb structure — not ESIF numbers.
5. Must **not** transfer: coefficients, PUE 1.03–1.08, 2.67 kW filter pump, 2024 HVAC kW, thermosyphon water/WUE levels.
6. Electrical layer is **partially** validated. It is **closed**. Next experiment is heat-rejection → water/WUE with the boundary restrictions in `HEAT_REJECTION_WATER_HANDOFF.md`.

## 14. Final capability statuses

See `analysis/FINAL_ESIF_FACILITY_OVERHEAD_STATUS.json`. Overall: `FACILITY_OVERHEAD_FINAL_DISPOSITION = PARTIAL`. `READY_FOR_HEAT_REJECTION_WATER_WUE = PASS_WITH_BOUNDARY_RESTRICTIONS`.
