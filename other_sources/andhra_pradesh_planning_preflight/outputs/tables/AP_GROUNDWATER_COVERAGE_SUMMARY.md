# Andhra Pradesh public groundwater coverage audit

Evidence class: `OBSERVED` for the downloaded groundwater-level values. No heads were interpolated and no groundwater model was fit.

| Metric | Result |
|---|---:|
| source | NWDP/CGWB manual quarterly Andhra Pradesh CSV resources |
| measurement_class | OBSERVED |
| no_interpolation | True |
| raw_rows | 87239 |
| numeric_rows | 87217 |
| numeric_rows_excluding_khammam_label | 87096 |
| numeric_khammam_rows_excluded_as_current_non_ap | 121 |
| candidate_rows_missing_coordinates | 998 |
| candidate_rows_outside_published_ap_coordinate_envelope | 14714 |
| spatial_qa_usable_rows | 71384 |
| spatial_qa_retention_percent | 81.960136 |
| distinct_name_keys_lower_bound | 2584 |
| station_location_series_upper_bound | 2746 |
| name_keys_with_multiple_coordinate_pairs | 160 |
| series_date_groups_with_conflicting_values | 3 |
| first_spatial_qa_usable_observation | 1996-01-05T06:00:00 |
| last_spatial_qa_usable_observation | 2023-08-20T06:00:00 |
| years_with_spatial_qa_usable_observations | 28 |
| district_labels_after_alias_normalization | 16 |
| series_with_at_least_24_distinct_times | 1011 |
| series_with_at_least_60_distinct_times | 384 |
| series_spanning_at_least_5_years | 1304 |
| series_spanning_at_least_10_years | 701 |
| median_distinct_observations_per_series | 17.0 |
| median_series_span_years | 4.0 |
| median_of_series_median_intervals_days | 92.0 |
| frequency_category_series_counts | {"46-90": 617, "91-180": 1627, "<=45": 7, ">180": 212, "SINGLE_OBSERVATION": 283} |
| official_network_count_reported | 1473 |
| official_dug_wells_reported | 676 |
| official_piezometers_reported | 797 |
| official_participatory_weekly_wells_reported | 105 |
| official_primary_manual_cadence | four rounds/year (May, August, November, January) |
| official_count_date_discrepancy | Yearbook prose says March 2025; Table 6.1 and Figure 1.1 say March 2024 for the same 1,473 total. |
| advertised_2021_2025_resource_actual_last_date | 2023-08-20T06:00:00 |
| raw_qa_flags_present | False |
| raw_screen_layer_fields_present | False |
| raw_stable_station_id_present | False |
| public_high_frequency_ap_machine_readable_status | NOT_LOCATED |
| dynamic_model_fit_performed | False |

## Identity and geography boundary

The CSVs provide station names but no stable source station ID. `distinct_name_keys_lower_bound` counts normalized agency + district + name; `station_location_series_upper_bound` additionally distinguishes coordinate pairs. Neither is asserted to be the exact number of physical wells. The official current network count is taken from the CGWB yearbook.

The coordinate screen uses the published state latitude/longitude envelope only. It is a QA plausibility screen, not a basin/state polygon join. Rows outside it are preserved in the raw and derived observation table and excluded only from spatial-coverage summaries.

## Blocking limitations

- No stable station ID, QA flag, measurement-method field, screen interval, or authoritative aquifer/layer is present in the downloaded CSVs.
- The nominal 2021-2025 file ends in August 2023 in the downloaded artifact.
- Thousands of rows have missing or geographically implausible coordinates, including clearly non-Andhra station names labeled as Anantapur.
- Public AP high-frequency telemetry files were not listed in the audited NWDP CGWB telemetry dataset, despite state pages documenting telemetry existence.
- Annual GWRA recharge/extraction estimates do not provide monthly observed forcing for local dynamic estimation.
