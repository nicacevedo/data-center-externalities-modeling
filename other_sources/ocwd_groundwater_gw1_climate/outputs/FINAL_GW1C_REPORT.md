# Final OCWD GW-1C report

## A. Repository and frozen dependencies

- Repository: `/home/nacevedo/RA/data-center-externalities-modeling`
- Branch / HEAD: `main` / `9e7ff6c43f28fcc66760681695459445283f6396`
- Scientific baseline: `9e7ff6c43f28fcc66760681695459445283f6396`; both frozen parent modules verified byte-for-byte against their committed blobs and committed hash manifests.
- Task-start dirty state: ` m Data-center-PUE-prediction-tool` only. No pre-existing path or frozen parent was modified.
- Python: `/home/nacevedo/.conda/envs/dc_externalities/bin/python` (3.11.15).
- Submodule status could not be enumerated because Git reports no `.gitmodules` mapping for the existing PUE path; that path was not touched.

The dependency manifest in `outputs/provenance/GW1C_DEPENDENCY_MANIFEST.csv` pins every material input. Frozen B1 reproduction passed at tolerance 1e-08; maximum prediction difference was 0 ft.

## B. Climate source and fixed features

The climate source is the official University of Idaho / Northwest Knowledge Network **gridMET** THREDDS OPeNDAP service. Only a 208-cell (13 × 16) WGS84 subset covering Basin 8-001 plus a fixed 0.1° buffer was acquired for 1991-07-01 through 1998-11-30. It contains daily precipitation and short-grass reference ET0 in millimetres. The rectangular source subset preserves 102980 masked values in ocean/non-land cells; all selected well cells have complete required coverage. Raw bounded DODS responses and metadata are retained and SHA-256 hashed.

Each frozen well was mapped once to the nearest temporally complete land grid cell using only data availability and coordinates. For transition `(t0,t1)`, the six frozen features are daily sums: `P_interval_mm` and `ET0_interval_mm` over calendar dates `(date(t0), date(t1)]`; and precipitation/ET0 over exactly 30 and 90 complete days strictly before `date(t0)`. No alternative lag, climate variable, well outcome, or target interpolation entered feature construction.

## C. Models and OOS results

- **B1:** frozen season/trend response baseline.
- **B1C:** B1 plus the six fixed gridMET features.
- **B1CH:** B1C plus the two unchanged GW-1A Prado features.

All models predict `delta_h` with pooled OLS after TRAIN-only centering/scaling. Validation and TEST were not used for fitting, scaling, or selection. Results below are TEST only, in feet, on common support. Since `h_hat = h_prev + delta_hat`, head-level and delta-head residuals are algebraically identical and are not presented as independent findings.

| regime | model | n_transitions | n_wells | RMSE_delta_h_ft | MAE_delta_h_ft | bias_delta_h_ft | sign_accuracy_delta_h | RMSE_skill_vs_B1 | MAE_skill_vs_B1 | median_well_RMSE_ft | well_RMSE_IQR_ft |
|---|---|---|---|---|---|---|---|---|---|---|---|
| T1_TEMPORAL_OOS | B1 | 1217 | 144 | 13.1569 | 7.0247 | -2.4183 | 0.7286 | 0.0000 | 0.0000 | 6.3541 | 6.4026 |
| T1_TEMPORAL_OOS | B1C | 1217 | 144 | 12.6842 | 6.7599 | -1.8170 | 0.7496 | 0.0359 | 0.0377 | 6.6909 | 4.9958 |
| T1_TEMPORAL_OOS | B1CH | 1217 | 144 | 12.8030 | 6.9124 | -2.3420 | 0.7303 | 0.0269 | 0.0160 | 6.7729 | 4.8039 |
| T2_SPATIOTEMPORAL_OOS | B1 | 1241 | 149 | 14.9739 | 7.5806 | -2.4703 | 0.7117 | 0.0000 | 0.0000 | 6.7859 | 6.0870 |
| T2_SPATIOTEMPORAL_OOS | B1C | 1241 | 149 | 14.8164 | 7.4997 | -1.9979 | 0.7339 | 0.0105 | 0.0107 | 7.0926 | 5.8636 |
| T2_SPATIOTEMPORAL_OOS | B1CH | 1241 | 149 | 14.8849 | 7.6189 | -2.5086 | 0.7035 | 0.0059 | -0.0051 | 7.4111 | 5.6013 |

## D. Pre-registered incremental comparisons and well bootstrap

Positive improvement means the more complex model has lower error. Intervals are 95% well-level bootstrap intervals (1,000 resamples; fixed seed family based on 20260904).

| regime | comparison | RMSE_improvement_ft | RMSE_improvement_ci95_low_ft | RMSE_improvement_ci95_high_ft | MAE_improvement_ft | MAE_improvement_ci95_low_ft | MAE_improvement_ci95_high_ft | median_well_RMSE_improvement_ft | well_RMSE_improvement_IQR_ft | fraction_wells_RMSE_improved |
|---|---|---|---|---|---|---|---|---|---|---|
| T1_TEMPORAL_OOS | B1C_minus_B1 | 0.4727 | 0.2502 | 0.7069 | 0.2648 | 0.0070 | 0.5195 | 0.2943 | 2.4080 | 0.6458 |
| T2_SPATIOTEMPORAL_OOS | B1C_minus_B1 | 0.1575 | 0.0011 | 0.3421 | 0.0809 | -0.1838 | 0.3359 | -0.0150 | 1.9490 | 0.4832 |
| T1_TEMPORAL_OOS | B1CH_minus_B1C | -0.1189 | -0.1682 | -0.0818 | -0.1525 | -0.2121 | -0.1005 | -0.1229 | 0.5436 | 0.3889 |
| T2_SPATIOTEMPORAL_OOS | B1CH_minus_B1C | -0.0684 | -0.1187 | -0.0317 | -0.1192 | -0.1715 | -0.0667 | -0.0882 | 0.4281 | 0.3960 |

- `CLIMATE_INCREMENTAL_SKILL = PARTIAL`
- `PRADO_AFTER_CLIMATE_SKILL = NONE`
- Frozen GW-1B background model: **B1C**.

These classifications concern held-out predictive information, not causal hydrologic coefficients. Climate remains mandatory background/confounding control in GW-1B regardless of its standalone increment. Prado is retained in the primary background model only when its post-climate support is positive under the frozen rule; otherwise it remains a sensitivity control.

## E. Cadence and gap-threshold robustness

The primary protocol remains ≤120 days. Cadence-group metrics subset the primary fits without refitting; ≤90 and ≤180 sensitivity results refit on their corresponding frozen gap thresholds.

| regime | cadence_group | model | n_transitions | n_wells | RMSE_delta_h_ft | MAE_delta_h_ft | RMSE_skill_vs_B1 | MAE_skill_vs_B1 |
|---|---|---|---|---|---|---|---|---|
| T1_TEMPORAL_OOS | GT_45_LE_90 | B1 | 388 | 105 | 15.8407 | 8.7670 | 0.0000 | 0.0000 |
| T1_TEMPORAL_OOS | GT_45_LE_90 | B1C | 388 | 105 | 15.1349 | 8.4277 | 0.0446 | 0.0387 |
| T1_TEMPORAL_OOS | GT_45_LE_90 | B1CH | 388 | 105 | 15.2911 | 8.6283 | 0.0347 | 0.0158 |
| T1_TEMPORAL_OOS | GT_90_LE_120 | B1 | 28 | 19 | 17.3202 | 10.2342 | 0.0000 | 0.0000 |
| T1_TEMPORAL_OOS | GT_90_LE_120 | B1C | 28 | 19 | 15.2327 | 10.0004 | 0.1205 | 0.0228 |
| T1_TEMPORAL_OOS | GT_90_LE_120 | B1CH | 28 | 19 | 15.4475 | 10.1723 | 0.1081 | 0.0060 |
| T1_TEMPORAL_OOS | LE_45 | B1 | 801 | 129 | 11.4442 | 6.0686 | 0.0000 | 0.0000 |
| T1_TEMPORAL_OOS | LE_45 | B1C | 801 | 129 | 11.1971 | 5.8388 | 0.0216 | 0.0379 |
| T1_TEMPORAL_OOS | LE_45 | B1CH | 801 | 129 | 11.2892 | 5.9673 | 0.0135 | 0.0167 |
| T2_SPATIOTEMPORAL_OOS | GT_45_LE_90 | B1 | 397 | 108 | 15.9068 | 8.8233 | 0.0000 | 0.0000 |
| T2_SPATIOTEMPORAL_OOS | GT_45_LE_90 | B1C | 397 | 108 | 15.6342 | 8.8677 | 0.0171 | -0.0050 |
| T2_SPATIOTEMPORAL_OOS | GT_45_LE_90 | B1CH | 397 | 108 | 15.7342 | 8.9937 | 0.0108 | -0.0193 |
| T2_SPATIOTEMPORAL_OOS | GT_90_LE_120 | B1 | 29 | 20 | 17.2555 | 10.5816 | 0.0000 | 0.0000 |
| T2_SPATIOTEMPORAL_OOS | GT_90_LE_120 | B1C | 29 | 20 | 15.7848 | 10.2065 | 0.0852 | 0.0355 |
| T2_SPATIOTEMPORAL_OOS | GT_90_LE_120 | B1CH | 29 | 20 | 15.9932 | 10.4159 | 0.0732 | 0.0157 |
| T2_SPATIOTEMPORAL_OOS | LE_45 | B1 | 815 | 134 | 14.4072 | 6.8684 | 0.0000 | 0.0000 |
| T2_SPATIOTEMPORAL_OOS | LE_45 | B1C | 815 | 134 | 14.3646 | 6.7370 | 0.0030 | 0.0191 |
| T2_SPATIOTEMPORAL_OOS | LE_45 | B1CH | 815 | 134 | 14.4109 | 6.8497 | -0.0003 | 0.0027 |

| regime | gap_threshold_days | model | n_transitions | n_wells | RMSE_delta_h_ft | MAE_delta_h_ft | RMSE_skill_vs_B1 | MAE_skill_vs_B1 |
|---|---|---|---|---|---|---|---|---|
| T1_TEMPORAL_OOS | 90 | B1 | 1189 | 139 | 13.1225 | 7.0055 | 0.0000 | 0.0000 |
| T1_TEMPORAL_OOS | 90 | B1C | 1189 | 139 | 12.7413 | 6.7441 | 0.0290 | 0.0373 |
| T1_TEMPORAL_OOS | 90 | B1CH | 1189 | 139 | 12.8717 | 6.9185 | 0.0191 | 0.0124 |
| T1_TEMPORAL_OOS | 180 | B1 | 1225 | 145 | 13.3515 | 7.1251 | 0.0000 | 0.0000 |
| T1_TEMPORAL_OOS | 180 | B1C | 1225 | 145 | 12.8509 | 6.9087 | 0.0375 | 0.0304 |
| T1_TEMPORAL_OOS | 180 | B1CH | 1225 | 145 | 12.9956 | 7.1205 | 0.0267 | 0.0006 |
| T2_SPATIOTEMPORAL_OOS | 90 | B1 | 1212 | 144 | 14.9447 | 7.5198 | 0.0000 | 0.0000 |
| T2_SPATIOTEMPORAL_OOS | 90 | B1C | 1212 | 144 | 14.8390 | 7.4097 | 0.0071 | 0.0146 |
| T2_SPATIOTEMPORAL_OOS | 90 | B1CH | 1212 | 144 | 14.9191 | 7.5524 | 0.0017 | -0.0043 |
| T2_SPATIOTEMPORAL_OOS | 180 | B1 | 1250 | 151 | 15.1474 | 7.6916 | 0.0000 | 0.0000 |
| T2_SPATIOTEMPORAL_OOS | 180 | B1C | 1250 | 151 | 15.0290 | 7.7226 | 0.0078 | -0.0040 |
| T2_SPATIOTEMPORAL_OOS | 180 | B1CH | 1250 | 151 | 15.1033 | 7.8791 | 0.0029 | -0.0244 |

## F. GW-1B readiness and identification boundary

The single permitted local filename scan found no OCWD WRMS delivery. Therefore `GW1B_DATA_STATUS = WAITING_FOR_WRMS`; B4–B7, pumping and recharge features, placebos, spatial kernels, and groundwater coupling were not fitted. The dated protocol amendment was frozen from GW-1A/GW-1C findings before any WRMS response analysis.

What this pass identifies is how well frozen heads can be predicted from the observed origin state, season/trend, fixed natural climate, and (when supported) public Prado background hydrology. Managed-recharge value, pumping predictive value, spatial forcing value, and network added value remain **UNIDENTIFIED WITHOUT WRMS**.

Tracer and MBI records remain reserved outside training, feature selection, scale selection, and model selection. No external physical validation is run before a future B7 is frozen.

The frozen GW-1A primary window contains zero eligible independent-agency transitions, so an independent-source T3 climate comparison remains `NOT_FEASIBLE_IN_FROZEN_WINDOW`; it was not forced by mixing provenance or extrapolating dates.

## G. Exact next action

When the OCWD WRMS delivery arrives, preserve it byte-for-byte, hash it, audit schemas/units/QA/evidence classes and exact well/facility identities, and re-evaluate pumping, recharge, vertical-identity, and common-support gates. Only after those gates pass should the frozen amendment be executed: B4 managed recharge/injection, B5 basin pumping, B6 spatial forcing plus its placebos, and B7 only if its network gate is earned. The static-versus-dynamic planning comparison remains downstream and must not begin in this pass.
