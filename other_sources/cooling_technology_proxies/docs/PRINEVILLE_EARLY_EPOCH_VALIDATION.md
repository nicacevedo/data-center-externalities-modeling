# Early Prineville external validation (predeclared)

Specification frozen in `manifests/PRINEVILLE_EARLY_VALIDATION_FREEZE.json` **before** residual inspection. Technology class was chosen from **architecture documents**, not from Meta 2023–2024 water and not from closeness of WUE.

## Predeclared cell

`AE_AD_ACC × climate 5B × Large-scale × liquid=NOT_APPLICABLE`  
Approximate: Lei still has a supplemental air-cooled chiller; PRN1 does not.

## Operator evidence used

| Quantity | Value | Class |
| --- | --- | --- |
| PUE commissioning | 1.07 | OPERATOR_REPORTED_MEASURED |
| PUE operating Apr–Sep 2011 | 1.06–1.1 | OPERATOR_REPORTED_MEASURED |
| WUE PRN1 Q2 2012 | 0.22 L/kWh cooling-only quarterly | OPERATOR_REPORTED_MEASURED |
| WUE 2011 design | 0.31 L/kWh | DESIGN (not a meter) |

Dashboard TTM Mar 2013 PUE 1.09 / WUE 0.52 from Wayback `fbpuewue.com/prineville` is recorded but **not** used to select `k`.

## Source-scenario cell (n=50)

PUE 5/50/95 ≈ **1.098 / 1.151 / 1.209**  
WUE_site_model 5/50/95 ≈ **0.009 / 0.024 / 0.038** L/kWh

## Result

**Classification: materially discrepant** (predeclared rule: commissioning PUE 1.07 is below source p05 **and** Q2 2012 WUE 0.22 is above source p95).

Interpretation (not a retune):

- Energy: small miss. Operating upper bound 1.10 is **inside** the source 5–95. Commissioning 1.07 is ~0.03 below p05 — plausible given Lei’s extra chiller overhead.
- Water: large miss (~9× median). Boundary differences (RO reject, recapture, quarterly vs annual TMY) go in the right direction but do not close the gap. This matches LBNL’s caveat that simulated adiabatic WUE can run low versus hyperscale reports 0.1–0.3.

No Lei parameters were calibrated. No alternate cooling label was selected because it fits 0.22.
