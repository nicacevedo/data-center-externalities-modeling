# Forest City v3 — Cross-Site Transportability, Partial Identification, and Acquisition-Readiness

MODEL_CALIBRATED = NO. QUANTITATIVE_PHYSICS_TRANSFER = NOT_VALIDATED. FACILITY_EFFECTIVE_DELTA_T = UNIDENTIFIED.

Run HEAD `b44e262c598a75d13d8aa2a25a99e3245af9ba46` on `main`; v2 targets read only from `da7fd6f55e1aef5216ceabe80bfc3e31265f7927` Git blobs.

## External-validity synthesis
- On identical n=1,251 timestamps, Forest City was warmer (24.0 °C) and much more humid (77.9% RH) than Prineville (19.5 °C; 44.0% RH). This is OBSERVED station climate.
- The 2×2 MODEL_REPLAY is mechanism-specific: the Forest City controller strongly increases OA-free occupancy and reduces evaporative occupancy; Forest City humidity strongly increases high-RH mixing; Prineville humidification is a dry-climate/controller interaction.
- These are replay counterfactuals: NOT_CAUSAL_IDENTIFICATION and NOT_WATER_USE.
- SUMMER_DX_STATION_ROBUSTNESS = STRONG_SUPPORT; DETAILED_REGIME_SHARE_STATION_ROBUSTNESS = PARTIAL. Missing KFQD hours remain unidentified.
- MASANET_TRANSFER = PARTIAL. Case 1 is architecture-mismatched; its PUE/WUE values are scenario outputs, not Forest City estimates. Main support matched: True.
- ESIF_TRANSFER = PARTIAL. Main support matched: True; synthetic IT is the frozen ESIF training-window mean, 1,406.288535 kW.
- Reported 2024 campus withdrawal intensities differ descriptively by 6.3525× (Prineville / Forest City), but the physical mechanism is unidentified.

## Identification boundary
- Campus annual electricity and water withdrawal are identified at the disclosure boundary; campus withdrawal intensity is identified-derived.
- Campus consumption, withdrawal-to-consumption fraction, facility airflow, effective facility Delta-T, FRC1 cooling-only water, reuse/blowdown, retrofit effects, and FRC1-to-campus mapping remain UNIDENTIFIED.
- Replay shares are known only over observed usable hours. The true full-period shares remain UNIDENTIFIED.
- CFM alone identifies airflow, not effective facility Delta-T. SAT/RAT and a matched heat/load boundary are required to close Q = m_dot cp DeltaT.

## Accounting boundary
- Forest City 2024: 535,555 MWh, 16,000 m³ withdrawal, 0.0298755 L/kWh_facility.
- Prineville 2024: 1,728,291 MWh, 328,000 m³ withdrawal, 0.189783 L/kWh_facility.
- This is not cooling WUE and does not identify cooling-only water, consumption, causal architecture effects, FRC1, workload differences, reuse/blowdown, or retrofit effects.

## Stop rule
Further generic computation has low marginal value. Engineering and utility records are now the binding information source; see the qualitative acquisition matrix.


## Final reproducibility and freeze

The clean checkout at the exact frozen dependency commit regenerated required intermediates, passed the committed v2 guards and v3 guards, and matched every material development output by exact hash or declared numerical tolerance.

`CLEAN_V2_REPRODUCIBILITY = PASS`  
`CLEANROOM_FINAL_STATUS = PASS`  
`FOREST_CITY_V3_FINAL_FREEZE = TRUE`  
`STOP_MODEL_EXPANSION = TRUE`
