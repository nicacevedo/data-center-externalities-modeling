# FINAL CLAIMS LEDGER — Forest City v3

Statuses use only: PASS, STRONG_SUPPORT, PARTIAL, NOT_VALIDATED, UNIDENTIFIED, NEEDS_DATA, FAIL.

| Claim | Status | Evidence class | Notes |
| --- | --- | --- | --- |
| V2_REPRODUCTION | PASS | MODEL_REPLAY | KFQD JJA hour counts vs committed v2 |
| WEATHER_ROBUSTNESS | STRONG_SUPPORT | OBSERVED + MODEL_REPLAY | Inherited: 0 DX at KFQD/KEHO/KGSP independently; station not chosen by DX |
| REGIME_TAXONOMY | PASS | MODEL_REPLAY | mutually exclusive; exhaustive on usable hours |
| FOREST_CITY_PRINEVILLE_CLIMATE_COMPARISON | STRONG_SUPPORT | OBSERVED | same UTC window; FC more humid |
| WEATHER_CONTROLLER_DECOMPOSITION | STRONG_SUPPORT | MODEL_REPLAY | humidification ≈ PRN controller; mixing ≈ FC climate × tighter PRN RH cap |
| QUALITATIVE_PHYSICS_TRANSFER | PARTIAL | MODEL_REPLAY | shared moist-air physics useful; not quantitative |
| MASANET_TRANSFER | PARTIAL | TRANSFERRED_MODEL | Case 1 adiabatic+chiller is architecture-mismatched to FC direct-evap |
| ESIF_TRANSFER | PARTIAL | TRANSFERRED_MODEL | weather-signed cooling term; ESIF plant ≠ FC AHU |
| QUANTITATIVE_PHYSICS_TRANSFER | NOT_VALIDATED | UNIDENTIFIED | prohibited to flip this via annual-aggregate match |
| FACILITY_EFFECTIVE_DELTA_T | UNIDENTIFIED | UNIDENTIFIED | 35 F remains IT design rise |
| COOLING_WATER_MAGNITUDE | UNIDENTIFIED | UNIDENTIFIED | no CFM / makeup meter |
| FRC1_ADDRESS | UNIDENTIFIED | UNIDENTIFIED | INTERVAL/SET_UNRESOLVED |
| CAMPUS_FACILITY_SCOPE | PASS | OBSERVED | 2024 totals labeled campus, not FRC1 |
| ACQUISITION_READINESS | PASS | DERIVED | engineering/utility records outrank more weather |

MODEL_CALIBRATED = NO

A scientifically successful v3 run still ends with QUANTITATIVE_PHYSICS_TRANSFER = NOT_VALIDATED and FACILITY_EFFECTIVE_DELTA_T = UNIDENTIFIED.
