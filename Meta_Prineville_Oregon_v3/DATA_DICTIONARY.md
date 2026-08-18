# Data dictionary and provenance

## `data/canonical/meta_prineville_annual.csv`

- `year`: calendar year.
- `hours_in_year`: 8760/8784 as appropriate.
- `electricity_mwh_reported`: site-level annual facility electricity reported by Meta.
- `avg_facility_power_mw_derived`: exact annual mean = MWh/hours.
- `water_withdrawal_m3_reported`: site-level annual water withdrawal. Blank where unavailable.
- `water_intensity_L_per_kWh_facility_derived`: withdrawal / **facility** electricity. This is a diagnostic and is not Meta's WUE denominator.
- `location_based_scope2_tco2e_reported`: site location-based purchased-electricity Scope 2, where separately disclosed.
- `location_based_scope2_kg_per_mwh_derived`: reported location Scope 2 / reported facility MWh.
- `operational_scope1_2_tco2e_reported`: source-vintage operational Scope 1+2 value. Reporting/accounting methods changed across years; use with source-vintage caution.
- `*_source_id`: foreign key to `data/source_manifest.csv`.
- `*_status`: reported/missing status.

## `data/canonical/meta_prineville_source_vintages.csv`
Preserves previously published values and revisions. Do not collapse revisions away.

## `data/canonical/meta_fleet_kpis.csv`
Fleet-wide PUE/WUE. These are external envelopes/weak priors only, never Prineville site truth.

## `data/canonical/city_water_sources.csv`
Official Prineville public-water-system source inventory crosswalk.
- `oha_facility_id`: Oregon Drinking Water Services facility/source ID.
- `well_log`: official well-log identifier where listed.
- `status` / `availability`: official inventory status where available.
- `model_use`: how to join/search the source in OWRD/City datasets.


## `data/canonical/prineville_owrd_source_crosswalk.csv`
Confidence-aware crosswalk between OHA PWS 00682 sources and OWRD water-use Report IDs.
- `accepted_owrd_report_ids`: safe default joins.
- `candidate_owrd_report_ids`: high-confidence candidates retained separately.
- `related_or_conflicting_report_ids`: historical/ambiguous/conflicting records that must not be auto-joined.
- `mapping_status` / `confidence`: machine-readable mapping decision.
- `production_handling`: explicit double-counting/exclusion instructions.

## `data/canonical/meta_owrd_direct_sources.csv`
Verified registry of the three OWRD POD reports associated with `VITESSE LLC C/O FACEBOOK INC`: 64500, 64845 and 64846. Treat them as direct-groundwater evidence with a separate boundary from City municipal production.

## `data/processed/owrd_city_monthly_report_use.csv`
Long-form OWRD City export with one row per Report ID/calendar month. Preserves raw facility/source/location/TRSQQ, measurement method, reported-zero vs blank, and accepted/candidate/conflict mapping fields. OWRD values are acre-feet and `volume_m3` is a deterministic unit conversion.

## `data/processed/owrd_city_monthly_model_use.csv`
Accepted-only model-facing municipal source/reporting groups. A combined POD such as Airport Wells #1/#2 is represented once under a combined key; its volume is not duplicated across the two physical sources.

## `data/processed/owrd_city_monthly_candidate_use.csv`
High-confidence candidate mappings (currently DT4-DT12 sequence) for review/sensitivity only. These are not used by the default model.

## `data/processed/owrd_meta_direct_monthly_use.csv`
Calendar-month-normalized Vitesse/Facebook direct POD reports. This is not automatically substituted for Meta's reported site withdrawal because the reporting boundary is not proven identical.

## `data/processed/pacw_hourly.csv`
Hourly PacifiCorp West (PACW) EIA-930 series from the untouched Grid Monitor workbook `data/raw/eia930/historical/PACW.xlsx`, cut at 2024-12-31 23:59 UTC. This is balancing-authority grid context, not campus feeder electricity. `timestamp_utc` is EIA's hour-ending UTC time.

Key columns:
- `demand_reported_mwh` / `demand_imputed_mwh` / `demand_adjusted_mwh`: EIA reported, imputed-when-made, and adjusted demand. Adjusted equals reported unless EIA imputed.
- Analogous reported/imputed/adjusted fields for net generation and total interchange.
- `ng_*_mwh`: generation by energy source (`COL`, `NG`, `WAT`, `SUN`, `WND`, `OTH`, …). Several codes are unused for PACW.
- `interchange_*_mwh`: bilateral interchange with neighboring BAs.
- `known_data_issue` and range-error flags from the workbook `Known Data Issues` sheet.

Also retained, from 2018-07-02: EIA-reported `co2_emissions_consumed` / `co2_emissions_generated` and `co2_intensity_consumed` / `co2_intensity_generated`. Those are PACW regional physical series, not campus meters and not marginal emissions.

The EIA API is not concatenated into this file. Overlap diagnostics are in `outputs/eia930_xlsx_api_overlap.csv`. Series start/end dates are in `outputs/eia930_series_coverage.csv`. The regional carbon-shape comparison of EIA consumed intensity vs the named fuel/import proxy is `outputs/pacw_carbon_shape_compare.csv`.

## `data/processed/egrid_prineville_annual.csv`
EPA eGRID subregion **total output emission rates** mapped to Prineville model years 2011-2024. Observed eGRID fields; CH4/N2O may be unit-converted from lb/GWh; fuel shares are stored as 0-1 fractions. This is not a campus meter series.

Key columns:
- `model_year` / `egrid_data_year`: study year vs EPA workbook year (2024 uses eGRID2023).
- `egrid_subregion`: consumption-location subregion from EPA Power Profiler ZIP 97754 (`NWPP`). Plant geography is corroboration only.
- `co2_lb_per_mwh` / `co2e_lb_per_mwh` / `nox_lb_per_mwh` / `so2_lb_per_mwh`: total output rates (ordinary location-based factors).
- `co2_nonbaseload_lb_per_mwh`: non-baseload rate; do not use as an ordinary Scope 2 factor.
- `coal_share` … `solar_share`: generation mix as fractions 0-1. eGRID 2010-2016 store 0-100 percent; 2018+ store 0-1 fractions under the same "percent" header.
- `source_file` / `source_revision` / `provenance_class`.

## `data/processed/campd_or_unit_hourly.csv`
Oregon CAMPD unit-hour extract, 2011-2024. Native key `Facility ID` × `Unit ID` × `Date` × `Hour`. Posted CO2/NOx/SO2 mass and heat input are not multiplied by `Operating Time`. `Gross Load (MW)` is the posted hourly rate. `gross_generation_mwh` = `Gross Load (MW)` × `Operating Time` when both are reported. Blanks remain missing.

## `data/processed/campd_or_plant_monthly.csv`
CAMPD aggregated to EIA plant × year × month after a unique unit→plant map. `campd_co2_tonnes` is metric tonnes from short tons; NOx/SO2 are kg from pounds. `campd_gross_generation_mwh` is the sum of hourly `Gross Load (MW) * Operating Time`. `campd_posted_gross_load_mw_sum` is the sum of posted MW (not energy). Mass and heat input are not multiplied by Operating Time.

## `data/processed/eia860_generator_annual.csv`
Oregon EIA-860 generator-year attributes (operable/proposed/retired sheets). Status, operating/retirement years, prime mover, fuel, and nameplate are native.

## `data/processed/eia923_generation_fuel_monthly.csv`
Oregon EIA-923 Page 1 generation/fuel melted to plant × prime mover × fuel × month. Confidential `.` / `W` remain missing.

## `data/processed/eia923_cooling_operations.csv`
Oregon plant-month cooling water. 2014-2024 from EIA cooling-detail (water unique on cooling system, not generator rows). 2013 from EIA-923 Schedule 8 million-gallon volumes. 2011-2012 water_m3 left missing.

## `data/processed/oregon_generator_externalities_monthly.csv`
Oregon plant-month integration table. Emission intensities are CAMPD mass / CAMPD gross generation (MWh). Water intensities are cooling-water / cooling-associated generation. EIA-923 `generation_mwh` is net generation and is not forced equal to CAMPD gross generation. Negative official cooling consumption is preserved as reported and excluded from intensity.

## `outputs/oregon_generator_data_checks.csv`
PASS/FAIL implementation and data-quality checks for the Oregon pilot.

## `outputs/egrid_meta_annual_compare.csv`
Derived annual benchmark: Meta campus `electricity_mwh_reported` × eGRID total output rates, converted to metric tonnes. PACW demand is not the energy input. `difference_tonnes` compares eGRID CO2e tonnes with Meta location-based Scope 2 (tCO2e) where Meta reported it. Market-based/REC values are not used.

## `outputs/owrd_water_model_validation.csv`
Calendar-month join of reconstructed campus withdrawal, OWRD Vitesse/Facebook direct groundwater POD use, and OWRD City accepted municipal production. Diagnostic only: OWRD is not a calibration target. Missing OWRD values remain missing. Candidate City mappings appear only as `owrd_city_candidate_production_m3`.

Key columns:
- `modeled_campus_withdrawal_m3`: monthly sum of the conditional reconstruction's `water_withdrawal_proxy_m3_per_h`.
- `owrd_meta_direct_groundwater_m3`: sum of reported volumes for registry POD reports 64500/64845/64846.
- `owrd_city_production_m3`: sum of accepted City source groups.
- `meta_annual_reported_withdrawal_m3`: Meta annual campus withdrawal repeated onto months of that year.
- `validation_flag`: `no_diagnostic_trigger` / `review_boundary` / `missing_owrd` / `partial_owrd_coverage`. `no_diagnostic_trigger` means the simple overlap thresholds were not fired; it does **not** mean OWRD validates the reconstruction.
- `owrd_meta_direct_expected_report_count`: number of registry POD reports whose bundled export interval covers that month. Report 64500 is not expected before it appears in the export.
- OWRD provenance is `reported OWRD water-use record` (may be measured or estimated). `owrd_meta_direct_measurement_method` and `owrd_city_measurement_method` retain the source method text.

## `outputs/owrd_water_model_validation_annual.csv`
Calendar-year descriptive totals of the same three boundaries versus Meta-reported annual withdrawal. Equality is not expected. OWRD annual sums use reported months only. Direct annual ratios (`direct_pod_to_modeled_ratio`, `direct_pod_to_meta_reported_ratio`) are NaN unless `direct_annual_complete` is true, which requires every interval-expected report-month to have a reported value.

## `data/canonical/campus_events_seed.csv`
High-confidence public events only. Event timing does not imply commissioning unless explicitly supported.

## `data/source_manifest.csv`
Source registry. Every final result should be traceable to one or more `source_id` values.

## Provenance labels for modeled hourly data
- `reported`: directly published source value.
- `measured`: meter/monitor record supplied by agency/utility.
- `derived`: exact deterministic transformation of reported/measured data.
- `fitted`: estimated parameter/latent state.
- `proxy`: external observed series standing in for unavailable site telemetry.
- `scenario`: counterfactual or assumed input.
- `gap_filled`: substituted/interpolated observation; preserve method/source.
