# Next experiment: parameter identification (NOT executed)

v1 is frozen physics. Do not end-to-end fit Meta water.

## Hierarchy

**PRIORITY A — directly measurable air-side**
airflow; return T/RH; mixed/supply T/RH; OA fraction/damper; mist/conditioning water as `AIR_STREAM_EVAPORATED_WATER` or makeup (tagged).

**PRIORITY B — engineering bounds**
rack/server airflow; supply/return envelopes; design settings. Optional DCD aisle ΔT 30–35 F is containment, not facility \(m_{da}\). Status: `NOT_ACQUIRED_NOT_BLOCKING` for a dedicated rack-CFM package.

**PRIORITY C — water-system boundary**
mist circulation; recapture; RO recovery/reject; site conditioning input. Do not set makeup = air_vapor / 0.85.

**PRIORITY D — campus aggregation**
building/phase electrical or IT shares λ_b.

**PRIORITY E — later PRN1**
condenser/heat-rejection type. Quantitative CHW water stays unidentified until this exists.

## Status vocabulary

`DIRECTLY_IDENTIFIED` · `CALIBRATABLE_WITH_NEW_DATA` · `SCENARIO_ONLY` · `UNIDENTIFIED`

If no Priority A data exist, the next action is **DATA ACQUISITION**, not annual-water calibration.

Identify **one** class at a time. 2023–2024 Meta water remains `DIAGNOSTIC_PREVIOUSLY_EXPOSED`.
