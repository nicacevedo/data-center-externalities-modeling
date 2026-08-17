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
