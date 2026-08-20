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

## `data/processed/owrd/owrd_city_monthly_report_use.csv`
Long-form OWRD City export with one row per Report ID/calendar month. Preserves raw facility/source/location/TRSQQ, measurement method, reported-zero vs blank, and accepted/candidate/conflict mapping fields. OWRD values are acre-feet and `volume_m3` is a deterministic unit conversion. Normalized OWRD products live under `data/processed/owrd/`; integrated joins live under `data/processed/water/` only.

## `data/processed/owrd/owrd_city_monthly_model_use.csv`
Accepted-only model-facing municipal source/reporting groups. A combined POD such as Airport Wells #1/#2 is represented once under a combined key; its volume is not duplicated across the two physical sources.

## `data/processed/owrd/owrd_city_monthly_candidate_use.csv`
High-confidence candidate mappings (currently DT4-DT12 sequence) for review/sensitivity only. These are not used by the default model.

## `data/processed/owrd/owrd_meta_direct_monthly_use.csv`
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

FERC Form 714 uses a different time convention (hour-ending local Pacific prevailing time) and is stored in separate files below. This EIA table is never overwritten by the FERC preparer.

## `data/processed/ferc714/pacw_west_monthly.csv`
Reported FERC Form 714 PacifiCorp-West monthly net energy for load, net generation, net actual interchange, monthly peak, and monthly minimum, 2011–2018. Balancing-authority evidence, not campus electricity. NEL ≈ net generation + net interchange within source precision.

## `data/processed/ferc714/pacificorp_east_west_hourly.csv`
Reported FERC Form 714 Schedule 2 hourly demand for the **PacifiCorp East+West combined planning area**. This is not PACW-West hourly demand. Columns include original FERC date/hour-ending, `local_timestamp`, `timestamp_utc`, `year_local`, `month_local` (FERC operating date; hour 24 stays on that date), timezone tags, and `series_label=pacificorp_east_west_combined_planning_area`. Missing spring-forward clock hours and unrepeated fall-back hours follow the filing; they are not interpolated.

## `data/processed/ferc714/pacw_hourly_backcast.csv`
FERC-only PACW-West hourly **proxy**: East+West intramonth shape scaled to West monthly NEL with a nonnegative monthly `b_m` chosen against West peak and minimum. Monthly energy closes to West NEL. Not reported PACW hourly demand and not campus electricity. EIA-930 is not used to fit this series.

## `data/processed/pacw_demand_hourly_extended.csv`
Separate from `pacw_hourly.csv`, which remains the pure EIA-930 source and is never overwritten.

Columns: `demand_reported_raw_mwh` (EIA reported as published, including unusable points), `demand_reported_usable_mwh` (same physical screen as FERC↔EIA validation: reported in (0, 8000] MW), `demand_adjusted_mwh` (EIA adjusted; sensitivity/reference only), `demand_ferc_proxy_mwh` (FERC-constrained hourly proxy **only** before first usable EIA coverage), `demand_best_available_mwh`, `provenance`, `provenance_class`.

`demand_best_available_mwh` hierarchy: usable EIA-930 reported demand where available; otherwise FERC hourly proxy only before EIA coverage; otherwise missing. Adjusted/imputed EIA is **not** substituted into `best_available`.

Row-level `provenance` is one of `EIA-930 reported usable`, `FERC constrained proxy`, or `missing`. FERC proxy is never labeled as observed PACW demand.

Validation: `outputs/ferc714_qa.csv`, `outputs/ferc714_eia930_validation.csv`, `outputs/ferc714_eia930_monthly_compare.csv`.

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
Oregon EIA-923 Page 1 generation/fuel melted to plant × prime mover × fuel × month. Confidential `.` / `W` remain missing. `reporting_frequency` is the Plant Frame code (`A`, `M`, `AM`, `AM/A`). `monthly_generation_basis` is `eia_allocated_from_annual` for `A` and `respondent_monthly` otherwise. For frequency `A`, `provenance_class=eia_published_monthly_allocation` on monthly Netgen; the Page 1 annual column remains the respondent calendar-year total.

## `data/processed/eia923_plant_frame_annual.csv`
Oregon rows from EIA-923 Page 6 Plant Frame. One row per plant-year with `reporting_frequency` and the native frequency column name.

## `outputs/oregon_campd_eia923_generation_compare.csv`
Plant-month CAMPD gross generation vs EIA-923 published net generation. Includes `reporting_frequency` and `monthly_generation_basis`. Monthly ratios for frequency=`A` are diagnostics, not primary QC.

## `outputs/oregon_campd_eia923_annual_reconciliation.csv`
Plant-year CAMPD gross vs EIA-923 net for CAMPD plants. Primary generation QC for annual EIA-923 respondents. `qc_status` is `ok`, `annual_comparability_warning`, `campd_only`, `eia923_only`, or `not_comparable`. The documented ok envelope is annual ratio 0.85–1.15 (gross vs net plus ordinary noise). Sources are not rescaled. `annual_comparability_warning` is a documented limitation, not a correction.

## `outputs/oregon_plant_55544_generation_outlier_diagnosis.csv`
Audit artifact from the plant-55544 monthly-outlier investigation. Not used as pipeline or exception logic.

## `data/processed/eia923_cooling_operations.csv`
Oregon plant-month cooling water. 2014-2024 from EIA cooling-detail (water unique on cooling system, not generator rows). 2013 from EIA-923 Schedule 8 million-gallon volumes. 2011-2012 water_m3 left missing.

## `data/processed/oregon_generator_externalities_monthly.csv`
Oregon plant-month integration table. Emission intensities are CAMPD mass / CAMPD gross generation (MWh). Water intensities are cooling-water / cooling-associated generation. EIA-923 `generation_mwh` is net generation and is not forced equal to CAMPD gross generation. Negative official cooling consumption is preserved as reported and excluded from intensity.

## `outputs/oregon_generator_data_checks.csv`
PASS/FAIL implementation and data-quality checks for the Oregon pilot. Monthly CAMPD/EIA-923 plausibility is evaluated on respondent monthly reporters only. Annual respondents are checked on the plant-year reconciliation table.

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

## `data/canonical/deq_document_inventory.csv`
Collected Oregon DEQ air PDFs and GHG workbooks. `document_calendar_year` is the reporting/permit year of the file; observation months still come from table tokens. `scan_only` files were not OCR'd. GHG workbooks other than `ghgElectricityEms.xlsx` are provenance-only.

## `data/canonical/meta_backup_generator_inventory.csv`
Onsite emergency generators. `nameplate_kw` is backup emergency capacity, never IT or facility load. `state_2018` is existing vs proposed from RR_2018 Table 1. `latest_state` is proposed / authorized / installed_listed / active / retired. Proposed units stay proposed unless listed in extracted hours tables. Conflicting kW/model strings are preserved via `nameplate_kw_alt`.

## `data/canonical/meta_backup_generator_events.csv`
Permit issuances, additions, commissioning, well-house retirement/replacement notice. Does not rewrite `campus_events_seed.csv`.

## `data/processed/meta_backup_operation_monthly.csv`
Canonical unique `generator_id` × year × month hours. Monthly testing/emergency/demand-response hours are the observation; `*_rolling12` columns are not used as monthly operations. Missing hours stay missing.

## `data/processed/meta_backup_emissions_monthly.csv`
Facility-wide DEQ-calculated annual-report emissions (short tons), non-emergency vs emergency. Not PSEL, not source tests, not Scope 2 / eGRID / PACW.

## `data/processed/meta_backup_fuel_monthly.csv`
Facility-wide diesel gallons from annual-report fuel summaries. Monthly gallons are the observation; rolling 12-month gallons are diagnostic.

## `data/processed/meta_backup_source_tests.csv`
RR_2018 source-test runs and DEQ-approved NOx factors (lb/hr). Separate from annual-report calculated tons.

## `data/processed/pacific_power_deq_ghg_annual.csv`
Oregon DEQ electricity-supplier GHG for Pacific Power (PacifiCorp), 2010-2024. Utility Oregon-delivery energy and anthropogenic MTCO2e. Not Vitesse onsite backup CO2e and not campus eGRID/PACW Scope 2.

## `data/canonical/campus_events_seed.csv`
High-confidence public events only. Event timing does not imply commissioning unless explicitly supported. DEQ matches are in `outputs/deq_campus_event_crosswalk.csv` only.

## `data/source_manifest.csv`
Source registry. Every final result should be traceable to one or more `source_id` values.

## USGS NWAA HUC12 water module

Modeled USGS National Water Availability Assessment series at HUC12 × month. **None of these variables are Meta water-meter observations.** They are regional modeled context for later merge with Meta, OWRD, weather, and event-timing data.

### Spatial interpretation
- Site HUC12 `170703051002` is designated `site_point_huc12`. The repository does not contain a Meta campus polygon, so full-footprint containment remains outstanding.
- The HUC12 containing the Meta buildings is not necessarily the HUC12 from which Prineville withdraws water that serves Meta. See `data/canonical/municipal_source_huc12_crosswalk.csv`.
- `scope_local`: site HUC12 plus touching HUC12s (9).
- `same_site_huc8`: all HUC12s in HUC8 `17070305` (52).
- IWA `strflow` / `consum` are **cumulative** (upstream + local), not local-only.

### Units and conversions
Native units are preserved. Processed tables add `*_m3_month`:
- IWA mm/month: `m3 = mm * areasqkm * 1000`.
- MGD monthly mean: `m3 = mgd * days_in_month * 3785.411784`.
Documented in `data/processed/usgs_nwaa/UNIT_CONVERSIONS.md`.

### Variable definitions (processed names)

| Processed name | Native USGS | Model | Units | Period | Meaning |
|---|---|---|---|---|---|
| `iwa_sui` | `sui` / `sui_frac` | `iwa-assessment-outputs-conus-2025` | fraction | 2009-10–2020-09 | Modeled surface-water supply/use indicator |
| `iwa_cumulative_streamflow_mm_month` | `strflow` | IWA | mm/month | 2009-10–2020-09 | Cumulative upstream + local surface-water supply |
| `iwa_cumulative_consumption_mm_month` | `consum` | IWA | mm/month | 2009-10–2020-09 | Cumulative upstream + local consumptive use (not local HUC12 alone) |
| `iwa_surface_water_availability_mm_month` | `availab` | IWA | mm/month | 2009-10–2020-09 | `strflow - consum`; **internal consistency check**, not independent validation |
| `public_supply_consumption_mgd` | `pscutot` | `wu-public-supply-cu` | mgd | 2009-01–2020-12 | Modeled public-supply consumptive use, **not Meta-specific** |
| `public_supply_withdrawal_total_mgd` | `pswdtot` | `wu-public-supply-wd` | mgd | 2000-01–2020-12 | Modeled total public-supply withdrawals |
| `public_supply_withdrawal_groundwater_mgd` | `pswdgw` | `wu-public-supply-wd` | mgd | 2000-01–2020-12 | Modeled groundwater public-supply withdrawals |
| `public_supply_withdrawal_surface_water_mgd` | `pswdsw` | `wu-public-supply-wd` | mgd | 2000-01–2020-12 | Modeled surface-water public-supply withdrawals |
| `irrigation_withdrawal_mgd` | `irrwdtot` | `wu-irrigation-wd` | mgd | 2000-01–2020-12 | Modeled crop-irrigation withdrawals |
| `irrigation_consumption_mgd` | `irrcutot` | `wu-irrigation-cu` | mgd | 2000-01–2020-12 | Modeled crop-irrigation consumptive use |

Withdrawal ≠ consumption. Consumption is water not returned to the local hydrologic cycle. IWA already incorporates sectoral consumptive-use components; **do not add `pscutot` or `irrcutot` into IWA `consum`**.

IWA **ends 2020-09** and cannot by itself support 2021–2024 Prineville analysis. Public-supply CU ends 2020-12; withdrawal and irrigation series end 2020-12.

### Files
- Raw API responses: `data/raw/usgs_nwaa/` (aggregates + per-HUC12 extracts). Source values are not modified.
- Source-specific full-period panels: `data/processed/usgs_nwaa/usgs_{iwa,public_supply_cu,public_supply_wd,irrigation}_huc12_monthly_{scope}.csv`
- Common-overlap panel (2009-10–2020-09): `data/processed/usgs_nwaa/usgs_huc12_monthly_overlap_{scope}.csv`
- QA: `outputs/qc/usgs_nwaa_qa.csv`, `outputs/qc/usgs_nwaa_download_log.csv`
- Municipal source → HUC12: `data/canonical/municipal_source_huc12_crosswalk.csv`

### `data/canonical/municipal_source_huc12_crosswalk.csv`
Links City of Prineville PWS 00682 sources to HUC12 using official coordinates only (inventory lat/lon or OWRD well-log decimal degrees + WBD point-in-polygon). Missing coordinates stay unresolved; TRSQQ is not converted to a point. Yancey Well #3 (`SRC-DC`) is flagged `out_of_study_geography` and is not treated as a Prineville HUC12 assignment.

## `data/processed/water/water_source_monthly_context.csv`
Finest defensible OWRD source/reporting-group × month table with USGS HUC12 context attached only where a verified in-study HUC12 exists. Boundaries (`city_municipal_production`, `city_municipal_candidate_sensitivity`, `vitesse_facebook_direct_pod`) are never summed. Candidate rows are identifiable and excluded from primary City totals.

## `data/processed/water/prineville_water_monthly_context.csv`
Calendar-month spine with **separate** columns for accepted City production, Vitesse/Facebook direct POD use, Meta annual campus withdrawal (labeled annual, not monthly), site-HUC12 USGS variables, and canonical KS39/KRDM monthly weather. USGS values are missing after their official coverage ends.

## Groundwater scaffold (`python run_prineville.py groundwater-context`)

Existing OHA/OWRD/Meta identities remapped to well nodes and joined to local OWRD GWIS exports on official well/tag/log IDs only. HUC12 is a location attribute only, never an aquifer/network node. Combined OWRD PODs are not split across physical wells. Duplicate GWIS files are hash-deduplicated; observations are unique on `gw_measured_water_level_id`.

- `data/canonical/groundwater/groundwater_well_inventory.csv`: municipal, Vitesse/Facebook, and unmatched GWIS candidate wells. Official coordinates only (HUC or GWIS).
- `data/canonical/groundwater/water_source_groundwater_crosswalk.csv`: source/report IDs → `well_node_id` / pumping group. Unmatched GWIS wells are `candidate_unresolved`.
- `data/canonical/groundwater/hydrogeologic_parameter_inventory.csv`: GWIS well depth / open interval / aquifer unit where reported; 260 MG/y ASR application citation as document context; T/S/Sy and pumping tests unresolved.
- `data/processed/groundwater/groundwater_pumping_monthly.csv`: accepted City groups, Vitesse/Facebook direct PODs, and Meta annual campus withdrawal as distinct boundaries.
- `data/processed/groundwater/groundwater_level_observations.csv`: time-indexed GWIS measured water levels (ft BLS; AMSL preserved with datum as a paired representation of the same measurement, not an independent observation).
- `outputs/qc/groundwater_context_qa.csv`, `outputs/groundwater/`: feasibility diagnostics plus identifiability audit tables/figures (`groundwater_identifiability_by_well.csv`, `groundwater_identifiability_summary.csv`) and measurement-QC tables (`gwis_measurement_model_qc.csv`, `gwis_measurement_qc_summary.csv`, `gwis_large_change_audit.csv`). Identifiability uses the measurement-QC eligible subset. `bls_anomaly_ft` = BLS − well-mean BLS; `head_anomaly_ft` = −`bls_anomaly_ft`. `ESTIMATION_CANDIDATE` means sufficient data to attempt a validated empirical response model, not identified dynamics. No groundwater-response model is fitted. Mixed datums are compared only as within-well anomaly/Δh. Combined Airport pumping is not split.

## `data/canonical/facility/prn1_addition_facts.csv`
High-confidence PRN1 addition facts from `data/raw/prineville_strictly_valuable_permits_v2/`. Provenance `reported_permit_document_evidence`. Area is a range/proxy (~82.7k ft²); `exact_final_area` and `electrical_capacity_mw` are missing. Circuit counts are not converted to MW. Not a gray-box or water-holdout input.

## `data/processed/water/meta_water_early_proxy_envelope.csv`
2011–2013 only. Direct OWRD POD water, 2011-design WUE×IT proxy (`PUE=1.07`, `WUE=0.31 L/kWh_IT`), and the existing train-only statistical backcast. Does not fill Meta-reported water and does not force a center estimate.

## `data/processed/egrid_2011_location_based_scope2_proxy.csv`
2011 location-based accounting proxy = Meta 2011 MWh × eGRID2010 NWPP CO2e factor. Provenance `eGRID_location_based_accounting_proxy`. Not Meta-reported Scope 2.

## `data/processed/water/regional_electricity_water_intensity.csv`
Partial-coverage Oregon cooling EWIF. Missing cooling water is not treated as zero. `regional_average_indirect_water_proxy_m3` is a regional average, not Meta generator attribution. QA: `outputs/qc/regional_electricity_water_qa.csv`.

## `data/processed/electricity/meta_campus_monthly_electricity_reconstruction.csv`
Annual-closed monthly reconstruction of reported Meta electricity using flat and conditional (gray-box) shapes from the existing hourly reconstruction. Labeled reconstructed / annual-closed, not meter data. Stochastic hourly shape is not available for 2011–2024.

## `data/processed/water/meta_campus_monthly_water_scenarios.csv`
Scenario allocations of reported annual Meta water (2014–2024) using flat, gray-box evaporation, and direct-POD seasonal shapes. Flat and gray-box series annual-close whenever the year has reported Meta water. The direct-POD seasonal scenario is constructed only when all 12 calendar months are observed (including explicit zeros); an incomplete POD year is skipped (`skipped_incomplete_direct_pod_shape`) rather than filling missing months with zero. Labeled scenario allocation, not observation or prediction.

## `outputs/data_gap_priority_assessment.csv`
Ranked assessment of GWIS, OpenET, and NHM/NWM/streamflow/recharge. Does not download those datasets.

## `data/processed/weather_krdm_hourly.csv`

KRDM / Roberts Field (NCEI Global Hourly `72692024230`) 2011–2024 UTC hourly backbone. Measured dry-bulb, dewpoint, and sea-level pressure after official NCEI/ISD QC (reject 2/3/6/7; retain passed and documented editorial codes; unknown codes rejected conservatively). Station pressure from sea-level pressure via the existing hypsometric conversion at 929 m, or standard-atmosphere fallback when SLP is unusable; RH and wet-bulb **derived**. This file is the preserved KRDM-only baseline and is not overwritten by the KS39 merge.

## `data/processed/weather_ks39_hourly.csv`

KS39 / Prineville Airport MADIS METAR, one row per physical UTC hour of `timeObs`. Temperature/dewpoint/wind are means of QC-usable unique reports in the hour. `precip1Hour` is an overlapping 1-hour accumulation (meters in MADIS); the hourly value is the last usable report in the hour, converted to mm — reports are not summed. Station pressure is **derived** from altimeter setting (Pa) and station elevation using the ICAO standard atmosphere. MADIS QC fields remain on the raw report table.

## `data/processed/weather_hourly.csv`

Canonical model weather for Prineville local calendar years 2011–2024: `2011-01-01 00:00` local `<= timestamp_local < 2025-01-01 00:00` local. UTC remains the unique physical-hour key. Hierarchy: QC-usable KS39 observed (from 2015-09-01 local) > KRDM gap-fill > KRDM observed > missing. After final T/Td/pressure selection, RH and wet-bulb are **recomputed**. Row-level `pressure_method` is `ks39_altimeter_derived`, `krdm_slp_derived`, or `krdm_standard_atmosphere_fallback`. Reconstruction and water-context months use `year_local` / local month.

Exact coverage: `outputs/ks39_coverage_monthly.csv`, `outputs/ks39_coverage_annual.csv`, `outputs/ks39_gap_summary.csv`. Overlap: `outputs/ks39_krdm_overlap_summary.csv`. Discovery sample rates in `madis_test/outputs/` are not exact completeness.

## Provenance labels for modeled hourly data
- `reported`: directly published source value.
- `measured`: meter/monitor record supplied by agency/utility.
- `derived`: exact deterministic transformation of reported/measured data.
- `fitted`: estimated parameter/latent state.
- `proxy`: external observed series standing in for unavailable site telemetry.
- `scenario`: counterfactual or assumed input.
- `gap_filled`: substituted/interpolated observation; preserve method/source.
