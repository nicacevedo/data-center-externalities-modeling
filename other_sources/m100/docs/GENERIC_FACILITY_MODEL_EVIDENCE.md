# Generic facility-model evidence (from M100 closure)

M100 is an **external measured facility-physics benchmark**, not generic-DC calibration data.

## STRUCTURALLY SUPPORTED

- **P_facility = P_IT + P_cooling + P_aux** — STRONG SUPPORT
  - M100 cooling aggregate accounts for nearly all non-IT energy; aux is residual, not a generic fraction
- **P_cooling = f_k(P_IT, weather, optional_state)** — {'claim': 'P_cooling = f_k(P_IT, weather, optional_state)', 'weather_additive': 'STRONG SUPPORT', 'weather_interaction': 'MIXED / REGIME-DEPENDENT', 'regime_interaction': 'MIXED / REGIME-DEPENDENT', 'note': 'k is a cooling/facility archetype; M100 coefficients are not generic'}
  - k is a cooling/facility archetype; M100 coefficients are not generic
- **PUE = P_facility / P_IT is a derived output, not a primitive** — STRONG SUPPORT
- **operational form may need state_(t+1) = g_k(state_t, P_IT_t, weather_t)** — STRONG SUPPORT
  - D1 is an identifiability diagnostic, not the physical model

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

## Evidence snapshot

```json
{
  "n_chronological_folds": 8,
  "facility_decomposition": "STRONG SUPPORT",
  "weather_additive": "STRONG SUPPORT",
  "weather_interaction": "MIXED / REGIME-DEPENDENT",
  "weather_within_month": "MIXED / REGIME-DEPENDENT",
  "weather_descriptor_robustness": "STRONG SUPPORT",
  "hq_robustness": "STRONG SUPPORT",
  "wetbulb_qa": "STRONG SUPPORT",
  "regime_interaction": "MIXED / REGIME-DEPENDENT",
  "temporal_state": "STRONG SUPPORT",
  "recursive_dynamics_skill": "MIXED / REGIME-DEPENDENT",
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
  "literature_reproduction": "REPRODUCED_SAMPLE",
  "cooling_target_weather": "STRONG SUPPORT",
  "october_retained": true
}
```

## Stop rule

STOP M100 MODEL DEVELOPMENT. Next: NLR/H100/MLPerf IT layer; Lei–Masanet/LBNL climate-technology-water; independent thermal/control datasets.
