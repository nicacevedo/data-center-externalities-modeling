# Generic facility-model evidence (from M100 closure)

M100 is an **external measured facility-physics benchmark**, not generic-DC calibration data.

## STRUCTURALLY SUPPORTED

- **P_facility = P_IT + P_cooling + P_aux** — STRONG SUPPORT
  - M100 cooling aggregate accounts for nearly all non-IT energy; aux is residual, not a generic fraction
- **P_cooling = f_k(P_IT, weather)** — STRONG_SUPPORT; weather_additive=STRONG_SUPPORT; weather_interaction=NOT_REQUIRED_BY_M100_EVIDENCE; regime_interaction=NOT_STABLY_SUPPORTED_AS_GENERIC_INPUT
  - k is a cooling/facility archetype; M100 coefficients are not generic. IT×weather interaction: NOT_REQUIRED_BY_M100_EVIDENCE. M100 Free_Cooling_Status / regime interaction: NOT_STABLY_SUPPORTED_AS_GENERIC_INPUT.
- **PUE = P_facility / P_IT is a derived output, not a primitive** — STRONG SUPPORT
- **strong temporal dependence is supported, but the tested recursive D1 model is not supported as a forward simulator** — STRONG_SUPPORT; temporal_dependence=STRONG_SUPPORT; recursive_d1_forward_simulator=NOT_SUPPORTED
  - Static-map residual autocorrelation supports temporal memory as an identifiability result. The tested D1 recursion is not a validated state equation and is not an operational simulator.

## NOT IDENTIFIED BY M100

Do not write production parameters from M100 for:

- generic coefficients (NOT IDENTIFIED BY M100)
- generic PUE values (NOT IDENTIFIED BY M100)
- generic cooling fractions (NOT IDENTIFIED BY M100)
- universal weather variable (NOT IDENTIFIED BY M100)
- universal cooling thresholds (NOT IDENTIFIED BY M100)
- generic state parameters (NOT IDENTIFIED BY M100)
- site WUE (UNSUPPORTED BY AVAILABLE DATA)
- water withdrawal (UNSUPPORTED BY AVAILABLE DATA)
- modern AI workload -> IT power (NOT IDENTIFIED BY M100)
- validated D1 state equation / recursive forward simulator (NOT_SUPPORTED)
- IT×weather interaction as a required generic term (NOT_REQUIRED_BY_M100_EVIDENCE)
- M100 Free_Cooling_Status as a generic planning input (NOT_STABLY_SUPPORTED_AS_GENERIC_INPUT)

## Evidence snapshot

```json
{
  "n_chronological_folds": 8,
  "facility_decomposition": "STRONG SUPPORT",
  "weather_additive": "STRONG_SUPPORT",
  "weather_interaction": "NOT_REQUIRED_BY_M100_EVIDENCE",
  "weather_within_month": "MIXED / REGIME-DEPENDENT",
  "weather_descriptor_robustness": "STRONG SUPPORT",
  "source_coverage_robustness": "NOT_TESTABLE_FROM_PROCESSED_FIELDS",
  "energy_quality_robustness": "STRONG_SUPPORT",
  "wetbulb_qa": "STRONG SUPPORT",
  "regime_interaction": "NOT_STABLY_SUPPORTED_AS_GENERIC_INPUT",
  "temporal_dependence": "STRONG_SUPPORT",
  "temporal_state": "STRONG_SUPPORT",
  "recursive_d1_forward_simulator": "NOT_SUPPORTED",
  "recursive_dynamics_skill": "NOT_SUPPORTED",
  "node_bridge": "STRONG SUPPORT",
  "thermal_sanity": "STRONG SUPPORT",
  "thermal_load_closure": "UNSUPPORTED BY AVAILABLE DATA",
  "pue_derived": "STRONG SUPPORT",
  "water": "UNSUPPORTED BY AVAILABLE DATA",
  "generic_coefficients": "NOT IDENTIFIED BY M100",
  "generic_pue": "NOT IDENTIFIED BY M100",
  "generic_cooling_fraction": "NOT IDENTIFIED BY M100",
  "universal_weather_variable": "NOT IDENTIFIED BY M100",
  "universal_thresholds": "NOT IDENTIFIED BY M100",
  "generic_state_parameters": "NOT IDENTIFIED BY M100",
  "modern_ai_it": "NOT IDENTIFIED BY M100",
  "n_folds_W0_to_W1_ge5pct": 8,
  "n_folds_W1_to_W2_ge5pct": 0,
  "n_folds_W2_to_R1_ge5pct": 2,
  "frac_folds_W0_to_W1_ge5pct": 1.0,
  "literature_reproduction": "EXECUTED_SAMPLE_WITH_NUMERICAL_DISCREPANCY",
  "cooling_target_weather": "STRONG SUPPORT",
  "october_retained": true
}
```

## Stop rule

STOP M100 MODEL DEVELOPMENT. M100 CLOSED/FROZEN. Next: NLR/H100/MLPerf IT layer; Lei–Masanet/LBNL climate-technology-water; independent thermal/control datasets.
