# Final OCWD GW-1A report

## A. Repository/preflight state

- Repository: `/home/nacevedo/RA/data-center-externalities-modeling`
- Branch / HEAD: `main` / `f5d2cedb3c5ba8f75aabe06801a42d274eafe692`
- Frozen feasibility baseline: `f5d2cedb3c5ba8f75aabe06801a42d274eafe692`; package-integrity check **PASS**.
- Task-start status: ` m Data-center-PUE-prediction-tool`; no pre-existing path was modified.
- Python: `/home/nacevedo/.conda/envs/dc_externalities/bin/python` (3.11.15).
- Submodule inspection remains unavailable because Git reports no `.gitmodules` mapping for the existing PUE path.

## B. Dependency hashes

| logical_input | path | worktree_sha256 | tracked_at_frozen_commit | worktree_matches_frozen |
|---|---|---|---|---|
| well_master | other_sources/ocwd_groundwater_feasibility/data/derived/DWR_OCWD_WELL_MASTER.parquet | f1c3acdb5e8a7ee45eefa6a833f9d0ceedf2f429fba15d8c7b16735098d1aebc | False | True |
| head_observations | other_sources/ocwd_groundwater_feasibility/data/derived/DWR_OCWD_HEAD_OBSERVATIONS.parquet | b190d0525b927821acbba4f864a61f715333a040884a21327639bcbbb5e13101 | False | True |
| perforations | other_sources/ocwd_groundwater_feasibility/data/derived/DWR_OCWD_PERFORATIONS.parquet | 254a663d16f35349fc3c2d31a382e6b604bc793cf1a6600db7fb57ddb2c65687 | False | True |
| observation_independence | other_sources/ocwd_groundwater_feasibility/outputs/tables/OBSERVATION_INDEPENDENCE_LEDGER.csv | f4349b06cebe2f93c4cf245d1ab0bff3ce569f556e0a3c93720137bec7022c00 | True | True |
| basin_8_001_geometry | other_sources/ocwd_groundwater_feasibility/data/derived/DWR_BASIN_8_001.geojson | e78e967ae9038236b456445a3f4bac21b2c13628a3914019112c8f736a43ec03 | False | True |
| official_bulletin_118_geometry | other_sources/ocwd_groundwater_feasibility/data/raw/dwr/bulletin118_groundwater_basins.geojson | 6ef98b660f7c81a900122fd3773c5d03fea70604161aded2d5b06e7c315dc097 | False | True |
| usgs_11074000_daily_derived | other_sources/ocwd_groundwater_feasibility/data/derived/USGS_11074000_SANTA_ANA_RIVER_DAILY.parquet | a23cf9f155566ce72eb53faef87c76bd503e35b5c4f637e6c5bc791a7b93b3b7 | False | True |
| usgs_11074000_daily_raw | other_sources/ocwd_groundwater_feasibility/data/raw/usgs/USGS_11074000_discharge_daily.rdb | 5f7d90dce443b9a8f17a6cf7fa77200cbb1688b7fe5e1e739a0a0814cbc4ee9c | False | True |
| event_registry | other_sources/ocwd_groundwater_feasibility/outputs/tables/EVENT_REGISTRY.csv | 9d54bd00674c692aedebae9031eb4897b82bdd204be67ee1ac7fd80e01a001ce | True | True |
| tracer_registry | other_sources/ocwd_groundwater_feasibility/outputs/tables/TRACER_VALIDATION_REGISTRY.csv | 46821ade16c946d0e719b87058fe2dae6b8c264f28fb14dd775d1d29eded381d | True | True |
| source_registry_csv | other_sources/ocwd_groundwater_feasibility/sources/source_registry.csv | b6e6e6860d8d03fe4636c6564d574c2b90bcc58ad4ccc3d46c9d6acacc32d51c | True | True |
| source_registry_yaml | other_sources/ocwd_groundwater_feasibility/sources/source_registry.yaml | 684ee564e1fc97c261a7fefb5efe072251ebd5bb5a92a6222b6f43e0b3830519 | True | True |
| feasibility_package_hashes | other_sources/ocwd_groundwater_feasibility/outputs/provenance/PACKAGE_FILE_HASHES.csv | a9700eac61447b4dbdd0bbeb80294aa68f76648eb2c7084c62e34a46f5681311 | True | True |
| raw_download_hashes_csv | other_sources/ocwd_groundwater_feasibility/outputs/provenance/RAW_DOWNLOAD_HASH_MANIFEST.csv | bff89f2fc7d788fe38490c8e549b7ddc8cd84127acda4304c92d617e175a2e00 | True | True |
| raw_download_hashes_json | other_sources/ocwd_groundwater_feasibility/outputs/provenance/RAW_DOWNLOAD_HASH_MANIFEST.json | 5f6e00de084dcfa64879e200aa6f64ba3be69b3b05ceb11f2a9796525600b6bc | True | True |
| feasibility_output_hashes | other_sources/ocwd_groundwater_feasibility/outputs/provenance/OUTPUT_HASHES.csv | 3006ed4f3a7d51bb9e746912e3ff09ecaabacf3c3918ea68589fc43946977f19 | True | True |
| basin_geometry_provenance | other_sources/ocwd_groundwater_feasibility/outputs/provenance/BASIN_GEOMETRY_PROVENANCE.json | c6c75dc6eb6f0bd744b935185f05511a551cddbfcb454200166bac3dfd370a2b | True | True |
| usgs_coverage | other_sources/ocwd_groundwater_feasibility/outputs/tables/USGS_11074000_COVERAGE.json | d0b34c7af59a703a06dbaaa8054d9f3d8cc5815943fa9270c11329eaeb66251f | True | True |
| final_feasibility_status | other_sources/ocwd_groundwater_feasibility/outputs/feasibility/FINAL_FEASIBILITY_STATUS.json | f4bec6959d8e7cf4df01a88d3eb0c107cecaf0a57c8a2c41d8041e867ebe6f15 | True | True |

Ignored raw/derived feasibility artifacts are pinned by the committed package hash manifest; tracked artifacts additionally match their exact frozen Git blobs. The source package tree was rechecked after GW-1A and remained byte-identical.

## C. Primary dense window

Coverage selection independently reproduced **1991-10 through 1998-11 (86 consecutive months)** with at least 50 wells observed in every month. Dates used observation availability only, never predictive performance.

## D. Data representations

- Monthly matrix: 268 wells × 86 months; 8144 observed cells and 14904 missing cells retained.
- Usable source observations in window: 9723.
- Consecutive unique-time transitions: 9406; ≤45: 6726, ≤90: 8533, ≤120: 8744, ≤180: 8837.
- Exact well/timestamp duplicates were collapsed by median solely to avoid fabricating an order at zero elapsed time. No target or missing head was interpolated.
- USGS daily discharge is complete for all required calendar days. Fifty-eight ≤120-day transitions contained no complete calendar day between a same-day origin and target (55 TRAIN, 3 VALIDATION, 0 TEST); the common B0–B3 fitting support excludes them rather than imputing an interval-flow value.

## E. Temporal split

- TRAIN: 1991-10-01 through 1996-09-01 (60 months)
- VALIDATION: 1996-10-01 through 1997-10-01 (13 months)
- TEST: 1997-11-01 through 1998-11-01 (13 months)

Validation was not used because ordinary least squares required no tuning. TEST data never entered fitting or scaling.

## F. Spatial folds

| spatial_fold | n_wells | easting_min_m | easting_max_m | northing_min_m | northing_max_m | n_transitions_total_le_120 | n_train_transitions | n_validation_transitions | n_test_transitions | fold_construction_inputs |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 42 | 398919 | 408474 | 3.73534e+06 | 3.74662e+06 | 1273 | 917 | 210 | 146 | coordinates_only_EPSG26911 |
| 2 | 70 | 403188 | 417445 | 3.72439e+06 | 3.73785e+06 | 2544 | 1721 | 462 | 361 | coordinates_only_EPSG26911 |
| 3 | 62 | 407172 | 420490 | 3.73687e+06 | 3.75473e+06 | 1870 | 1279 | 315 | 276 | coordinates_only_EPSG26911 |
| 4 | 60 | 418588 | 431178 | 3.72504e+06 | 3.73814e+06 | 1848 | 1309 | 300 | 239 | coordinates_only_EPSG26911 |
| 5 | 34 | 420763 | 435790 | 3.73929e+06 | 3.75083e+06 | 1209 | 815 | 175 | 219 | coordinates_only_EPSG26911 |

Folds are deterministic KMeans clusters in EPSG:26911 from coordinates only (`k=5`, `random_state=20260904`, `n_init=50`), relabeled west-to-east. Heads, screens, forcing, residuals, and skill were excluded.

## G. Independent-agency holdout

Every one of the 9723 usable source observations in the frozen primary window is classified `OCWD_ORIGIN_REPUBLISHED_BY_DWR`. There are zero within-window independent-agency transitions, so T3 is **NOT FEASIBLE IN THE FROZEN COHORT** and is not forced through temporal extrapolation or provenance mixing.

## H. Exact B0–B3 specifications

- **B0:** `h_hat_target = h_prev`; no fitting.
- **B1:** pooled OLS for `delta_h` from gap days, target-day seasonal sine/cosine, and linear target-time trend.
- **B2:** pooled OLS for `h_target` from `h_prev` plus the B1 inputs.
- **B3:** B2 plus `log1p` mean USGS 11074000 discharge on origin-date through day-before-target and `log1p` mean discharge over the 30 complete days before target. No target-day or later flow enters a feature.

B3 is public background/boundary hydrology, **not managed recharge**. A hydrologic feature is missing if any required daily discharge is missing; no discharge is imputed. All feature centering/scaling is learned from TRAIN only. No hyperparameter search or regularization was used.

## I–J. T1 temporal and T2 spatiotemporal TEST results

Errors are feet. Bias is prediction minus observation. Positive skill means lower error than persistence. Head and change residual errors are algebraically identical conditional on the observed origin head; change metrics prevent a misleading interpretation based on between-well level heterogeneity. R² is retained only in machine-readable output as secondary.

| regime | model | n_transitions | n_wells | MAE_h_ft | RMSE_h_ft | bias_h_ft | MAE_delta_h_ft | RMSE_delta_h_ft | sign_accuracy_delta_h | RMSE_skill_vs_persistence | MAE_skill_vs_persistence | median_well_RMSE_ft | well_RMSE_IQR_ft | fraction_wells_RMSE_improved_vs_B0 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T1_TEMPORAL_OOS | B0 | 1217 | 144 | 7.3912 | 14.1506 | -1.4573 | 7.3912 | 14.1506 |  | 0 | 0 | 7.3847 | 10.0145 | 0 |
| T1_TEMPORAL_OOS | B1 | 1217 | 144 | 7.0247 | 13.1569 | -2.4183 | 7.0247 | 13.1569 | 0.7286 | 0.0702 | 0.0496 | 6.3541 | 6.4026 | 0.6528 |
| T1_TEMPORAL_OOS | B2 | 1217 | 144 | 7.374 | 13.2174 | -3.0527 | 7.374 | 13.2174 | 0.7429 | 0.066 | 0.0023 | 7.3969 | 5.9399 | 0.6111 |
| T1_TEMPORAL_OOS | B3 | 1217 | 144 | 7.5395 | 13.3167 | -3.327 | 7.5395 | 13.3167 | 0.7353 | 0.0589 | -0.0201 | 7.6735 | 5.8792 | 0.6181 |
| T2_SPATIOTEMPORAL_OOS | B0 | 1241 | 149 | 7.7104 | 15.6478 | -1.3823 | 7.7104 | 15.6478 |  | 0 | 0 | 7.4 | 10.2024 | 0 |
| T2_SPATIOTEMPORAL_OOS | B1 | 1241 | 149 | 7.5806 | 14.9739 | -2.4703 | 7.5806 | 14.9739 | 0.7117 | 0.0431 | 0.0168 | 6.7859 | 6.087 | 0.6443 |
| T2_SPATIOTEMPORAL_OOS | B2 | 1241 | 149 | 8.7829 | 15.7443 | -3.7279 | 8.7829 | 15.7443 | 0.7315 | -0.0062 | -0.1391 | 7.961 | 8.0864 | 0.604 |
| T2_SPATIOTEMPORAL_OOS | B3 | 1241 | 149 | 8.8468 | 15.7982 | -3.9487 | 8.8468 | 15.7982 | 0.7298 | -0.0096 | -0.1474 | 8.2739 | 8.4128 | 0.604 |

## K. T3 independent-source result

T3 is unavailable within the frozen interval (zero eligible independent-agency transitions). Independent observations outside the interval remain preserved and were not repurposed.

## L. Cadence robustness

| regime | cadence_group | model | n_transitions | n_wells | RMSE_delta_h_ft | MAE_delta_h_ft | RMSE_skill_vs_persistence | MAE_skill_vs_persistence |
|---|---|---|---|---|---|---|---|---|
| T1_TEMPORAL_OOS | LE_45 | B0 | 801 | 129 | 12.1151 | 6.2363 | 0 | 0 |
| T1_TEMPORAL_OOS | LE_45 | B1 | 801 | 129 | 11.4442 | 6.0686 | 0.0554 | 0.0269 |
| T1_TEMPORAL_OOS | LE_45 | B2 | 801 | 129 | 11.488 | 6.3618 | 0.0518 | -0.0201 |
| T1_TEMPORAL_OOS | LE_45 | B3 | 801 | 129 | 11.6027 | 6.5203 | 0.0423 | -0.0455 |
| T2_SPATIOTEMPORAL_OOS | LE_45 | B0 | 815 | 134 | 14.721 | 6.7389 | 0 | 0 |
| T2_SPATIOTEMPORAL_OOS | LE_45 | B1 | 815 | 134 | 14.4072 | 6.8684 | 0.0213 | -0.0192 |
| T2_SPATIOTEMPORAL_OOS | LE_45 | B2 | 815 | 134 | 15.3286 | 8.3156 | -0.0413 | -0.234 |
| T2_SPATIOTEMPORAL_OOS | LE_45 | B3 | 815 | 134 | 15.3728 | 8.3685 | -0.0443 | -0.2418 |
| T1_TEMPORAL_OOS | GT_45_LE_90 | B0 | 388 | 105 | 17.3324 | 9.5776 | 0 | 0 |
| T1_TEMPORAL_OOS | GT_45_LE_90 | B1 | 388 | 105 | 15.8407 | 8.767 | 0.0861 | 0.0846 |
| T1_TEMPORAL_OOS | GT_45_LE_90 | B2 | 388 | 105 | 15.9093 | 9.1483 | 0.0821 | 0.0448 |
| T1_TEMPORAL_OOS | GT_45_LE_90 | B3 | 388 | 105 | 16.0202 | 9.3468 | 0.0757 | 0.0241 |
| T2_SPATIOTEMPORAL_OOS | GT_45_LE_90 | B0 | 397 | 108 | 17.2099 | 9.5283 | 0 | 0 |
| T2_SPATIOTEMPORAL_OOS | GT_45_LE_90 | B1 | 397 | 108 | 15.9068 | 8.8233 | 0.0757 | 0.074 |
| T2_SPATIOTEMPORAL_OOS | GT_45_LE_90 | B2 | 397 | 108 | 16.3557 | 9.46 | 0.0496 | 0.0072 |
| T2_SPATIOTEMPORAL_OOS | GT_45_LE_90 | B3 | 397 | 108 | 16.4511 | 9.5695 | 0.0441 | -0.0043 |
| T1_TEMPORAL_OOS | GT_90_LE_120 | B0 | 28 | 19 | 18.4821 | 10.1325 | 0 | 0 |
| T1_TEMPORAL_OOS | GT_90_LE_120 | B1 | 28 | 19 | 17.3202 | 10.2342 | 0.0629 | -0.01 |
| T1_TEMPORAL_OOS | GT_90_LE_120 | B2 | 28 | 19 | 17.6183 | 11.7435 | 0.0467 | -0.159 |
| T1_TEMPORAL_OOS | GT_90_LE_120 | B3 | 28 | 19 | 17.3241 | 11.6542 | 0.0627 | -0.1502 |
| T2_SPATIOTEMPORAL_OOS | GT_90_LE_120 | B0 | 29 | 20 | 18.2553 | 10.1279 | 0 | 0 |
| T2_SPATIOTEMPORAL_OOS | GT_90_LE_120 | B1 | 29 | 20 | 17.2555 | 10.5816 | 0.0548 | -0.0448 |
| T2_SPATIOTEMPORAL_OOS | GT_90_LE_120 | B2 | 29 | 20 | 18.4992 | 12.6448 | -0.0134 | -0.2485 |
| T2_SPATIOTEMPORAL_OOS | GT_90_LE_120 | B3 | 29 | 20 | 18.2775 | 12.394 | -0.0012 | -0.2237 |

Threshold sensitivities at ≤90, ≤120, and ≤180 days are in `outputs/tables/SENSITIVITY_METRICS.csv`; each threshold refits the same declared OLS ladder on TRAIN only. Gap-band results above subset the primary ≤120-day TEST predictions.

## M–N. Strongest baseline and public hydrologic increment

- `STRONGEST_NO_PUMPING_BASELINE = B1` under the predeclared mean T1/T2 RMSE-skill ranking.
- `PUBLIC_HYDROLOGIC_INCREMENTAL_SKILL = NONE` for B3 relative to B2.
- `TEMPORAL_PREDICTION_DIFFICULTY = HIGH` and `SPATIAL_GENERALIZATION_DIFFICULTY = HIGH` under the frozen RMSE-to-test-change-IQR rule.

Well-bootstrap differences (positive means the comparison model lowers error):

| regime | comparison_model | reference_model | difference_direction | n_wells | n_transitions | bootstrap_resamples | resampling_unit | seed | MAE_improvement_ft | MAE_improvement_ci95_low_ft | MAE_improvement_ci95_high_ft | RMSE_improvement_ft | RMSE_improvement_ci95_low_ft | RMSE_improvement_ci95_high_ft | MAE_skill_vs_reference | MAE_skill_ci95_low | MAE_skill_ci95_high | RMSE_skill_vs_reference | RMSE_skill_ci95_low | RMSE_skill_ci95_high |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T1_TEMPORAL_OOS | B1 | B0 | positive_means_comparison_model_has_lower_error | 144 | 1217 | 1000 | well | 20260905 | 0.3665 | -0.0477 | 0.8005 | 0.9937 | 0.7683 | 1.2542 | 0.0496 | -0.0071 | 0.0955 | 0.0702 | 0.0518 | 0.1045 |
| T1_TEMPORAL_OOS | B2 | B0 | positive_means_comparison_model_has_lower_error | 144 | 1217 | 1000 | well | 20260906 | 0.0172 | -0.5652 | 0.617 | 0.9333 | 0.5492 | 1.2778 | 0.0023 | -0.0867 | 0.0739 | 0.066 | 0.0423 | 0.0922 |
| T1_TEMPORAL_OOS | B3 | B0 | positive_means_comparison_model_has_lower_error | 144 | 1217 | 1000 | well | 20260907 | -0.1483 | -0.7003 | 0.4007 | 0.8339 | 0.4438 | 1.1722 | -0.0201 | -0.1046 | 0.0491 | 0.0589 | 0.0358 | 0.0839 |
| T2_SPATIOTEMPORAL_OOS | B1 | B0 | positive_means_comparison_model_has_lower_error | 149 | 1241 | 1000 | well | 20260908 | 0.1298 | -0.3158 | 0.5063 | 0.6739 | 0.452 | 0.9264 | 0.0168 | -0.0467 | 0.0622 | 0.0431 | 0.0258 | 0.0719 |
| T2_SPATIOTEMPORAL_OOS | B2 | B0 | positive_means_comparison_model_has_lower_error | 149 | 1241 | 1000 | well | 20260909 | -1.0724 | -2.336 | -0.0227 | -0.0965 | -0.9925 | 0.5789 | -0.1391 | -0.342 | -0.0028 | -0.0062 | -0.0752 | 0.0373 |
| T2_SPATIOTEMPORAL_OOS | B3 | B0 | positive_means_comparison_model_has_lower_error | 149 | 1241 | 1000 | well | 20260910 | -1.1364 | -2.2524 | -0.1337 | -0.1504 | -1.0174 | 0.4706 | -0.1474 | -0.3294 | -0.0156 | -0.0096 | -0.0761 | 0.0293 |
| T1_TEMPORAL_OOS | B3 | B2 | positive_means_comparison_model_has_lower_error | 144 | 1217 | 1000 | well | 20261005 | -0.1655 | -0.2293 | -0.1042 | -0.0993 | -0.1872 | -0.0143 | -0.0224 | -0.0329 | -0.0139 | -0.0075 | -0.0174 | -0.001 |
| T2_SPATIOTEMPORAL_OOS | B3 | B2 | positive_means_comparison_model_has_lower_error | 149 | 1241 | 1000 | well | 20261006 | -0.0639 | -0.1325 | 0.0095 | -0.0539 | -0.1151 | 0.0054 | -0.0073 | -0.0158 | 0.0011 | -0.0034 | -0.0088 | 0.0004 |

## O–P. Frozen GW-1B and placebo protocol

GW-1B retains B0–B3, then adds B4 observed managed recharge/injection, B5 observed pumping, B6 spatially structured forcing, and B7 the smallest physically constrained groundwater network. `B5-B4` tests incremental pumping information; `B7-B5` separately tests network structure. The temporal placebo permutes pumping across years within calendar month. The spatial placebo permutes pumping-well identities only within authoritative future aquifer/layer strata. Neither is run now.

## Q. Reserved external validation

The 35-row tracer registry and five MBI start events remain outside features, fitting, tuning, fold construction, and ranking. They are reserved for post-freeze physical validation.

## R. Tests

The guard suite checks frozen source integrity, input hashes, non-imputation, split isolation, coordinate-only folds, independent-source exclusion, hydrologic time direction, forcing labels, reserved-validation isolation, absence of pumping/network/GNN/MODFLOW fitting, and OOS-only ranking. Exact execution result is recorded after the final test run in the handoff.

## S. Scientific conclusion

Without pumping, `B1` is the strongest transparent held-out baseline under the frozen joint T1/T2 ranking. Public Prado discharge contributes `none` incremental support relative to head history under the preregistered rule. These results quantify conditional one-step response predictability, not an operational forecast and not pumping causality. Because observed WRMS pumping and managed-recharge panels are absent, pumping-response coefficients, source attribution, and spatial/network added value remain unidentified.

Future evidence that pumping matters requires robust B5-over-B4 held-out improvement, a well-bootstrap interval excluding zero, positive median well-level improvement, broad well support, and superiority to the season-preserving temporal placebo. Future evidence that network structure matters separately requires B7 to outperform B5 and the spatial pumping placebo after authoritative well/layer crosswalks exist.

## T. Exact next action

`READY_FOR_GW1B = NO_UNTIL_WRMS`. When the requested WRMS export arrives, hash and schema-audit it first; map well/facility/layer identities only from authoritative crosswalks; then reuse the immutable GW-1A months and spatial folds and run the frozen B4→B7 ladder and placebos without consulting tracer or MBI responses until the groundwater model is frozen.
