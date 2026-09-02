# Forest City v3 — Cross-Site Transportability, Partial Identification, and Acquisition-Readiness

MODEL_CALIBRATED = NO.
QUANTITATIVE_PHYSICS_TRANSFER = NOT_VALIDATED.
FACILITY_EFFECTIVE_DELTA_T = UNIDENTIFIED.

A scientifically successful run. Those two claims remain closed in the negative.

## What is OBSERVED

- NOAA hourly weather with missingness preserved:
  - KFQD 2012: 4,174 / 8,784 usable hours; first usable 2012-06-21 17:00Z; JJA 1,253 usable / 955 missing.
  - KEHO JJA: 1,916 usable / 292 missing.
  - KGSP JJA: 2,208 usable / 0 missing.
  - KRDM JJA: 2,206 usable / 2 missing.
- Same-period intersection KFQD∩KRDM: **1,251 hours**, 2012-06-21 00:00Z to 2012-09-01 00:00Z.
- Common-period climate (n=1,251): Forest City mean Tdb 24.0 °C, RH 77.9%, Twb 20.8 °C; Prineville mean Tdb 19.5 °C, RH 44.0%, Twb 11.1 °C.
- Meta 2024 campus disclosures: Forest City 535,555 MWh and 16,000 m³; Prineville 1,728,291 MWh and 328,000 m³.

## What is DERIVED

- Forest City 2024 site withdrawal intensity = 16,000 / 535,555 = **0.02988 L/kWh_facility**. Not FRC1 cooling WUE. Not ISO WUE.
- Prineville 2024 campus intensity = **0.1898 L/kWh_facility**. Comparable only at campus-disclosure scope.

## What is MODEL_REPLAY

v2 JJA KFQD reproduction (exact hour counts): OA_FREE 677, HIGH_RH_MIXING 443, EVAP_COOLING 133, DX 0 / 1,253. **PASS.**

Independent JJA DX = 0 at KFQD, KEHO, and KGSP. Stations were not chosen by that outcome.

Weather × controller 2×2 on 1,251 intersection hours (matches committed v2 to 1e-9):

| Combination | HUMID | OA_FREE | MIX | EVAP |
| --- | --- | --- | --- | --- |
| PRN wx + PRN ctrl | 0.430 | 0.137 | 0.206 | 0.226 |
| PRN wx + FC ctrl | 0 | 0.836 | 0.031 | 0.133 |
| FC wx + PRN ctrl | 0 | 0.020 | 0.745 | 0.235 |
| FC wx + FC ctrl | 0 | 0.540 | 0.354 | 0.106 |

Interpretation (regime occupancy only; **not gallons**):

- Humidification is a **Prineville-controller** effect (present only on PRN weather + PRN controller).
- High-RH mixing is an **interaction**: Forest City humidity × Prineville’s tighter RH cap (0.745) versus Forest City’s 90% RH envelope.
- OA-free cooling is highest when Prineville’s drier climate meets Forest City’s looser envelope (0.836).
- Native Forest City evap share (0.106) is **not** higher than native Prineville evap (0.226) on these dates.
- Hour-to-hour transition rates: 0.145 (FC native), 0.166 (PRN native), 0.088 (FC wx + PRN ctrl), 0.064 (PRN wx + FC ctrl).

## What is TRANSFERRED_MODEL (not calibration)

Frozen Masanet Case 1 (airside economizer + adiabatic + water-cooled chiller; P_IT=1; Table 3 midpoints; seed 2025):

- KFQD mean PUE 1.261, WUE 1.841 L/kWh; corr(PUE, Tdb) = **−0.206**.
- KRDM mean PUE 1.137, WUE 0.282 L/kWh; corr(PUE, Tdb) = **+0.524**.
- Architecture mismatch vs Forest City direct-evap + unused DX. Not FC PUE/WUE/water-magnitude validation.

Frozen ESIF F4 cooling + F0 HVAC, synthetic IT = ESIF training-window mean (1,406 kW):

- KFQD mean cooling 28.3 kW; corr vs Tdb +0.17.
- KRDM mean cooling 14.3 kW; corr vs Tdb **−0.42**.
- ESIF outdoor fan/heater on a liquid/thermosyphon plant ≠ Forest City evaporative AHU.

## What remains UNIDENTIFIED

FACILITY_EFFECTIVE_DELTA_T, facility CFM, cooling-only makeup, blowdown, reuse/return, withdrawal vs consumption, FRC1 street address, quantitative cooling-water transfer.

35 °F remains IT/server design rise. It was **not** used as `m = Q/(cp ΔT)` and was **not** chosen to match annual water.

## Acquisition

Engineering and utility records now outrank additional weather. Highest-value: TAB CFM; SAT/RAT; sequence of operations; cooling makeup meter IDs (2012 and 2022–2024); blowdown/reuse; retrofit chronology; P&IDs.
