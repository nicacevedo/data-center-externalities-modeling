# Follow-up v1 summary

Evidence-only. First-run artifacts were not overwritten. Meta 2023–2024 water was not read.

## 1. Is Lei–Masanet sufficiently reproduced at annual scale?

Annual gate: **FAIL**. Selected-cell vs `UE.xlsx`: **INCONSISTENT**. Smoke: **PASS**. Paper-style mean vs equal-Δt energy ratio identity: **PASS**.

We did not rerun all 10×15 cells. Consistency is claimed only for the locked diagnostic subset.

## 2. What do the 10 cases map to?

Final article is closed OA; ranges are from the 2022 preprint Table 3 + public code. Bundled `UE.xlsx` (15 zones, 300 rows) is the reproduction target.

- Case 1 (large-scale): Airside economizer + adiabatic cooling + (water-cooled chiller) → `PUE_WUE_AE_Chiller`
- Case 2 (large-scale): Waterside economizer + (water-cooled chiller) → `PUE_WUE_Chiller_Watereconomier`
- Case 3 (midsize): Airside economizer + (water-cooled chiller) → `PUE_WUE_AE_Chiller_Colo`
- Case 4 (midsize): Waterside economizer + (water-cooled chiller) → `PUE_WUE_WE_Chiller_Colo`
- Case 5 (midsize): Water-cooled chiller → `PUE_WUE_Chiller` (shared with case 8)
- Case 6 (midsize): Airside economizer + (air-cooled chiller) → `PUE_WUE_AE_AIRChiller`
- Case 7 (midsize): Air-cooled chiller → `PUE_WUE_AIRChiller` (shared with case 9)
- Case 8 (small): Water-cooled chiller → `PUE_WUE_Chiller` (shared with case 5)
- Case 9 (small): Air-cooled chiller → `PUE_WUE_AIRChiller` (shared with case 7)
- Case 10 (small): Direct expansion system → `PUE_WUE_DX`

Cases 5 and 8 share `PUE_WUE_Chiller`; 7 and 9 share `PUE_WUE_AIRChiller`; they differ by Table 3 ranges. Cases 8–9: Table 2 lists isothermal humidification but the shared functions still take a humidification pump (medium confidence).

RH table labels are physically reversed: high-RH numbers → code `RH_up`; low-RH → `RH_lw`.

## 3. Are bundled annual envelopes consistent with the pinned implementation?

**INCONSISTENT**. Classification uses bootstrap / extra LHS quantile-estimator variability, not an invented percent tolerance.

## 4. Is internal RNG material at annual scale?

**ANNUAL_RNG_IMMATERIAL**. PUE ratio seed/facility = 0.0; WUE ratio = 0.0. Upstream stochastic helpers were not modified.

## 5. What can we safely transfer?

If the gate allows the adapter: a **normalized climate/technology intensity model**

`(P_IT, weather, case k, theta_k) → (P_fac = P_IT * PUE, W_conditioning = P_IT * WUE, explicit CT/humidification components)`.

`Chiller_load` is a scenario parameter, not a dynamic function of `P_IT`. Variable-IT annual PUE/WUE must be energy-weighted, not an unweighted mean of hourly intensities. Water components are conditioning-side only (humidification/adiabatic, CT evaporation, windage, draw-off). They are not groundwater, municipal source, or consumption-only.

## 6. What remains unsupported?

Workload → `P_IT`; dynamic part-load vs actual IT; liquid cooling; conditioning-water → source/return; source pumping → groundwater; operations/siting optimization; the full 150-cell paper table; sklearn 0.23 unless a later COP discrepancy appears.

## 7. What did the corrected Frontier analysis change?

Missing expected 10-minute timestamps (first run counted NaT rows only): coverage=0.934341704718417, missing hours=575.1666666666666. F1-vs-F0 qualitative change flag: **False**. Thermal `ρ c_p V ΔT` check is published-formula reproduction, not independent conservation. F2 remains a contemporaneous oracle. Closure: **CLOSED**.

## 8. Large-scale cases under Prineville 2022 weather (no Meta water)

Year 2022 because the canonical pipeline holdout is 2023–2024. `P_IT=1`, 50 LHS draws, cases 1 and 2 only. Not a ranking and not a calibration.

- Case 1 PUE 5/50/95: None, None, None; WUE 5/50/95: None, None, None
- Case 2 PUE 5/50/95: None, None, None; WUE 5/50/95: None, None, None

## 9. Single highest-value next experiment

Do not translate into the project model until the annual gate is resolved (mapping, UE envelopes, or RNG).
