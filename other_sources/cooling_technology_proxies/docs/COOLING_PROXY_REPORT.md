# Cooling-proxy freeze report

Additive module. Masanet not modified. Meta 2023–2024 water not used to choose `k`.

## Corrections vs prior pass

1. Liquid subtypes **are** separable via `Case (Original)` (SI Rmd). Status **PARTIAL**, not UNSUPPORTED.
2. Case **15** = liquid WE; Case **16** = liquid dry/adiabatic (CSV). Prior taxonomy had them swapped.
3. 19,000 rows are a **source-model scenario ensemble**, not empirical observations. Equal weights = `DESIGN_PRIOR_UNIFORM`.
4. Ten **PAPER_CORE** technologies; Cases 17/18 **SOURCE_EXTRA_EXTENDED** (opt-in).
5. Removed the unmatched global “frontier” figure.
6. Early Prineville operator PUE/WUE used as **external validation**, not calibration.

## Canonical object

Level 1 fail-closed annual paired source scenarios. Level 2 hourly **UNSUPPORTED**.

## Matched / liquid results (source-model only)

Within Large-scale × climate, heat-rejection (tower/WE vs dry/adiabatic) is **first-order for WUE** (median |ΔWUE| ≈ 1.82 L/kWh; relative ≈ 12×). Liquid subtype range within the same rejection is **second-order** (median PUE range ≈ 0.006; WUE range ≈ 0.016 L/kWh). Not empirically validated.

## Early Prineville

Architecture: OA + ECH, no chiller/tower. Closest class AE_AD_ACC 5B Large-scale (approximate).  
Operator PUE 1.07 (and 1.06–1.1); WUE 0.22 (Q2 2012).  
Source cell PUE 1.10–1.21; WUE 0.009–0.038.  
**Materially discrepant** on the predeclared rule; PUE is a small miss, WUE is large. Do not switch to a wet tower class to fit 0.22.

Dashboard JSON timeseries: **not recovered**. Wayback TTM Mar 2013 PUE 1.09 / WUE 0.52 recorded only.

## Next layer

Prineville epoch-specific cooling + conditioning-water → source-water / return / consumption accounting. Not a new hourly liquid simulator.
