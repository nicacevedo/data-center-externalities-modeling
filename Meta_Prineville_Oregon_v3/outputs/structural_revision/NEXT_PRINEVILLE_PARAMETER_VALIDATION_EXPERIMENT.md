# Next Prineville parameter-calibration / empirical-validation experiment

**NOT EXECUTED in the structural pass.** Design only.

Structural object: `PRINEVILLE_STRUCTURAL_REVISION_FREEZE.json`  
2023–2024 Meta water: `DIAGNOSTIC_PREVIOUSLY_EXPOSED` — not a pristine model-selection holdout.

## 1. Which parameters are actually identifiable?

Identifiable **now** (engineering, not statistical): OCP DESIGN_SPEC thresholds; mixing **form**; humidification vs evap **structure**; CHW **presence** at PRN1; early PRN1 class `DIRECT_OUTSIDE_AIR_EVAP`.

Not identifiable now: as-operated OA fraction; ε; ΔT; λ_b; CHW condenser; CCO/PRN2–6 class; mist loss; withdrawal mapping as physics.

## 2. Which should stay engineering scenarios?

Until independent measurements exist: ε=0.85, ΔT=12 K, return 35 C, fan/other/evap-aux fractions, DESIGN_SPEC vs as-operated control. Do not let one annual water residual identify all of these at once.

## 3. Which data calibrate airflow?

Supply–return ΔT, fan-array flow, or building airflow. **Not** annual Meta withdrawal. Electrical P_IT helps only if ΔT or flow is known.

## 4. Which data calibrate evaporative effectiveness?

Supply T vs mixed T vs wet-bulb, or staged mist water vs predicted adiabatic Δw. **Not** campus withdrawal.

## 5. Which data validate conditioning water directly?

Mist makeup / ECH water; drain/recycle. Tag `CONDITIONING_SITE_WATER`. City or Meta withdrawal is a **different** boundary.

## 6. Which data validate withdrawal mapping separately?

City meter with resolved boundary; POD completeness; Meta annual withdrawal as `G_site(W_conditioning, local_water_system)`. Fit mapping **after** physics freeze, never inside the psychrometric equation. Do not rename that scale “evaporative efficiency.”

## 7. How will building load shares be handled?

Keep λ_b = UNKNOWN until building electrical/IT is obtained. Do not equal-weight. If only campus P_IT exists, report early-PRN1 **building** scenarios, not a identified campus total. Optional sensitivity: labeled scenarios with declared λ, not fitted to water.

## 8. What if PRN1 condenser type remains unknown?

CHW water stays `UNIDENTIFIED`. No tower, dry-cooler, or WUE coefficient. Do not infer condenser from the word “chiller.” Campus 2023–2024 water cannot identify condenser type.

## 9. What validation evidence is genuinely new?

Prefer: new City monthly series with resolved boundary; future Meta vintage; building telemetry; condenser schedule. Previously exposed 2023–2024 Meta water is diagnostic only.

## 10. How will previously exposed 2023–2024 Meta water be used?

Score as `DIAGNOSTIC_PREVIOUSLY_EXPOSED` **after** freeze, never to choose structure, ε, ΔT, OA fraction, or λ. Report discrepancy by boundary (conditioning vs withdrawal) and by architecture epoch. Do not call the model “better” because holdout error fell.

## Protocol (separate pass)

1. Keep this structural freeze hashed.  
2. Declare which **one** parameter class is being calibrated (airflow **or** ε **or** G_site — not all).  
3. Use 2011–2022 only if the target is the accounting map, and only after physics is frozen.  
4. Validate with new City/future Meta/telemetry.  
5. Stop if residuals can be absorbed by several unlabeled knobs.

Must not: SPLC; campus-wide chillers; ESIF/Lei coefficients; 2011 WUE 0.31 as later-campus truth; IEC as installed.
