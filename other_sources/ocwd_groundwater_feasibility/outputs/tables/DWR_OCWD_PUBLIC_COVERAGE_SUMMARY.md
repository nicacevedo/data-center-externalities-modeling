# DWR Basin 8-001 public head-data coverage

Counts are a data-availability audit. Groundwater levels were not interpolated and no wells were selected using model performance.

| metric | value |
| --- | --- |
| basin_id | 8-001 |
| basin_name | COASTAL PLAIN OF ORANGE COUNTY |
| spatial_join_method | point-in-polygon against official DWR Bulletin 118 GeoJSON |
| n_dwr_stations_inside | 626 |
| n_with_usable_head_observations | 552 |
| n_with_at_least_24_observations | 359 |
| n_with_at_least_60_observations | 230 |
| n_spanning_at_least_5_years | 417 |
| n_spanning_at_least_10_years | 333 |
| n_overlapping_1990_11_to_1999_11 | 274 |
| n_overlapping_2008_plus | 225 |
| n_with_perforation_metadata | 121 |
| share_with_perforation_metadata | 0.19329073482428116 |
| n_head_records_all_qa | 74585 |
| n_usable_head_observations | 60751 |
| earliest_usable_observation | 1901-01-01 00:00:00 |
| latest_usable_observation | 2026-06-25 11:57:00 |
| median_of_well_median_intervals_days | 37.97361111111111 |
| maximum_observed_gap_days | 20656.0 |
| max_wells_observed_in_every_year_of_a_5y_window | 179 |
| best_5y_window | [1995, 1999] |
| max_wells_observed_in_every_year_of_a_10y_window | 146 |
| best_10y_window | [2001, 2010] |
| n_station_official_code_vs_spatial_join_mismatches | 0 |
| dwr_measurement_source_counts | {'DWR_DISCRETE': 74585} |
| usable_head_independence_counts | {'OCWD_ORIGIN_REPUBLISHED_BY_DWR': 56222, 'INDEPENDENT_AGENCY_OBSERVATION': 4529} |
| n_months_with_at_least_50_observed_wells | 471 |
| longest_consecutive_monthly_support_run_at_50_wells | {'start_month': '1991-10', 'end_month': '1998-11', 'consecutive_months': 86, 'minimum_wells_in_month': 50, 'median_wells_in_month': 85.0} |
| no_interpolation | True |
| usable_definition | numeric groundwater elevation and timestamp with QA Good or blank-as-good per DWR dictionary |
