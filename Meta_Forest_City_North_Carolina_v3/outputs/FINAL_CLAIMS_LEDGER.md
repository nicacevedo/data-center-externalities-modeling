# FINAL CLAIMS LEDGER — Forest City v3

MODEL_CALIBRATED = NO. MODEL_REPLAY outputs are NOT_CAUSAL_IDENTIFICATION and NOT_WATER_USE.

| Claim | Status | Evidence class | Notes |
| --- | --- | --- | --- |
| V3_DEPENDENCY_AUDIT | PASS | PROVENANCE | v2 accessed only as frozen Git blobs; material worktree inputs hash-enforced |
| V2_REPRODUCTION | PASS | MODEL_REPLAY | exact hour counts against da7fd6f frozen blob |
| REGIME_TAXONOMY | PASS | MODEL_REPLAY | mutually exclusive and exhaustive on usable hours |
| SUMMER_DX_STATION_ROBUSTNESS | STRONG_SUPPORT | MODEL_REPLAY | zero summer DX at KFQD, KEHO, KGSP |
| DETAILED_REGIME_SHARE_STATION_ROBUSTNESS | PARTIAL | MODEL_REPLAY | cross-station sensitivity ranges differ; not confidence intervals |
| FOREST_CITY_PRINEVILLE_CLIMATE_COMPARISON | STRONG_SUPPORT | OBSERVED | identical n=1,251 timestamp support |
| WEATHER_CONTROLLER_DECOMPOSITION | STRONG_SUPPORT | MODEL_REPLAY | mechanism-specific contrasts; not causal and not water use |
| QUALITATIVE_PHYSICS_TRANSFER | PARTIAL | MODEL_REPLAY | shared moist-air mechanisms only |
| MASANET_TRANSFER | PARTIAL | TRANSFERRED_MODEL | Case 1 scenario; architecture-mismatched; not Forest City estimates |
| ESIF_TRANSFER | PARTIAL | SCENARIO_INPUT + TRANSFERRED_MODEL_OUTPUT | matched n=1,251 main support; architecture-mismatched |
| QUANTITATIVE_PHYSICS_TRANSFER | NOT_VALIDATED | UNIDENTIFIED | aggregate agreement cannot promote transfer |
| QUANTITATIVE_COOLING_WATER_TRANSFER | NOT_VALIDATED | UNIDENTIFIED | no identified airflow/heat/water boundary closes a quantitative transfer |
| FACILITY_EFFECTIVE_DELTA_T | UNIDENTIFIED | UNIDENTIFIED | 35 F remains IT/server design rise |
| FACILITY_AIRFLOW_CFM | UNIDENTIFIED | UNIDENTIFIED | CFM alone cannot identify effective Delta-T |
| REPLAY_SHARE_OVER_OBSERVED_USABLE_HOURS | IDENTIFIED_MODEL_REPLAY | MODEL_REPLAY | denominator is only observed usable weather hours |
| TRUE_FULL_PERIOD_REGIME_SHARE | UNIDENTIFIED | UNIDENTIFIED | missing KFQD hours are not silently filled or called observations |
| CAMPUS_ANNUAL_ELECTRICITY | PASS | OBSERVED | Meta campus disclosure at the reported annual boundary |
| CAMPUS_ANNUAL_WATER_WITHDRAWAL | PASS | OBSERVED | Meta campus disclosure; not consumption |
| CAMPUS_WITHDRAWAL_INTENSITY | PASS | DERIVED | campus withdrawal divided by campus facility electricity; not cooling WUE |
| CAMPUS_WATER_CONSUMPTION | UNIDENTIFIED | UNIDENTIFIED | withdrawal does not identify consumption |
| WITHDRAWAL_TO_CONSUMPTION_FRACTION | UNIDENTIFIED | UNIDENTIFIED | reuse, return, and blowdown accounting unavailable |
| FRC1_COOLING_ONLY_WATER_MAGNITUDE | UNIDENTIFIED | UNIDENTIFIED | cooling makeup meter boundary unavailable |
| CAMPUS_VS_FRC1_SCOPE_SEPARATION | PASS | OBSERVED | 2024 campus totals never substituted for 2012 FRC1 |
| FRC1_TO_LATER_CAMPUS_MAPPING | UNIDENTIFIED | UNIDENTIFIED | facility/address/temporal crosswalk absent |
| ACQUISITION_READINESS | PASS | QUALITATIVE_PRIORITY | engineering/utility record packages are binding |

A successful benchmark preserves QUANTITATIVE_PHYSICS_TRANSFER = NOT_VALIDATED and FACILITY_EFFECTIVE_DELTA_T = UNIDENTIFIED.

## Final reproducibility gate

- `CLEAN_V2_REPRODUCIBILITY = PASS`
- `CLEANROOM_FINAL_STATUS = PASS`
- `FOREST_CITY_V3_FINAL_FREEZE = TRUE`
- `STOP_MODEL_EXPANSION = TRUE`
