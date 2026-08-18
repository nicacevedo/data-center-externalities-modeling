# Remaining manual / access-controlled acquisition steps

Everything in this file is here because it is not reliably obtainable as a machine-ready public download from this environment, or because a records custodian must answer it.

## 1. Oregon Water Resources Department — reported monthly water use

Source: https://apps.wrd.state.or.us/apps/wr/wateruse_query/

### Current status (bundled in this package)

The City of Prineville entity export (2010-2025) and Vitesse LLC c/o Facebook Inc entity export (2011-2024) have now been acquired and are bundled under `data/raw/owrd/`. The source-level crosswalk is in `data/canonical/prineville_owrd_source_crosswalk.csv`, and `python run_prineville.py water` creates the normalized monthly datasets.

Do **not** repeat the broad entity exports unless refreshing to a newer water year. Remaining OWRD follow-up is narrow: resolve DT14/DT18 if a separate POD/report link is needed, and optionally verify the DT4-DT12 candidate mappings at location level.

The query explicitly supports searches by **Water User (Entity)**, **Point of Diversion (Facility)**, **Water Right**, and area summary. OWRD warns that reports may be measured or estimated and that only a subset of rights are subject to reporting. Preserve the method/quality field.

### A. City-wide entity export

1. Open the Water Use Report Query.
2. Select **Water User (Entity)**.
3. In `Company/Government`, search `CITY OF PRINEVILLE`.
4. Start Water Year: `2010` (or earliest available).
5. End Water Year: `2025`.
6. Run query.
7. Export/save the complete result as Excel/text/CSV if offered.
8. Save the untouched export in `data/raw/owrd/`.

### B. Point-of-diversion searches

Repeat **Point of Diversion (Facility)** searches for the named sources in `data/canonical/city_water_sources.csv`, using the **official OHA facility IDs and well-log identifiers already curated** in `data/canonical/city_water_sources.csv`. Search by both facility name and City of Prineville entity where possible. This is more robust than using only common well names.

Use 2010-2025 and export every matching series. For the Crooked River Park wellfield, preserve individual source IDs rather than collapsing them prematurely.

### C. Direct Meta/Facebook right search

Repeat the entity search using each of:

- `FACEBOOK`
- `FACEBOOK INC`
- `META`
- `META PLATFORMS`
- `META PLATFORMS INC`

Also search any LLC/project owner names discovered in building permits. If a right has a `View Reported Water Use` link, export it separately.

### D. Normalize

Populate `data/manual_templates/owrd_monthly_well_use.csv`.

Critical caution: OWRD commonly organizes records by **water year (Oct 1-Sep 30)**. Convert months to actual calendar timestamps before joining weather/electricity. Preserve whether each value is measured or estimated.

## 2. Public ASR engineering documents — already accessible, no request needed

Use these immediately as groundwater/ASR priors and event evidence:

- 2020 OWRD ASR application: `https://www.oregon.gov/owrd/programs/FundingOpportunities/WaterProjectGrantAndLoans/Documents/Applications%20Received%202020%20Cycle/PrinevilleASR_Application.pdf`
- 2018 feasibility study / 2020 attachments: `https://www.oregon.gov/owrd/programs/FundingOpportunities/WaterProjectGrantAndLoans/Documents/Applications%20Received%202020%20Cycle/PrinevilleASR_Attachments.pdf`

They include aquifer/hydrogeologic characterization, Heliport/Millican context, ASR design and pilot-test chronology, source-water rights context, and storage/recovery assumptions. They do **not** replace actual monthly operational injection/recovery or groundwater-head time series.

## 3. City of Prineville public-record request — highest-value request

Official City page: https://www.cityofprineville.com/1294/Public-Records

The City states that non-police public-record requests may be submitted to `recorder@cityofprineville.com` (phone 541-447-5627, ext. 106). Use that channel; do not send this utility/infrastructure request to the police-records address.

### Ready-to-copy request

> I am conducting academic research on the historical water and infrastructure impacts of the Prineville data-center campus. I request existing electronic records, preferably in CSV/XLSX format where maintained, for January 2010 through December 2025 for the following: (1) monthly potable-water volume billed/delivered to Facebook/Meta data-center accounts or, if account-level records cannot be released, monthly aggregate volume for the Facebook/Meta campus; (2) monthly reclaimed/non-potable water supplied to the campus, if any; (3) monthly wastewater/sewer discharge volume attributable to the campus, if separately metered; (4) monthly production/pumping volume for each municipal production well and the Crooked River Wellfield; (5) monthly aquifer-storage-and-recovery injection and recovery volumes; (6) groundwater level/head observations collected for the ASR or municipal well system; and (7) meter installation/replacement dates or material changes in how these quantities were measured. I am not requesting personal customer information, payment information, or security-sensitive facility details. If account-level records are exempt, please provide the least aggregated non-exempt historical time series that preserves the monthly total.

Save all responses/raw files under `data/raw/city/` and then map them into:
- `city_meta_monthly_meter.csv`
- `city_well_production_monthly.csv`
- `asr_monthly.csv`

Do not overwrite raw records.

## 4. Crook County / City building-permit request

Goal: obtain the **actual commissioning/retrofit chronology** rather than infer it from press announcements.

### Ready-to-copy request

> I request an electronic index/export of commercial building, electrical, mechanical and plumbing permits associated with Facebook/Meta data-center facilities in or near Prineville from January 2010 through December 2025. For each permit, please provide the permit number, project/site identifier or address, permit type, issue date, final inspection/closure/certificate-of-occupancy date if applicable, project description, building square footage, and any non-security-sensitive description of electrical capacity or cooling/mechanical system. I am especially interested in records identifying new data-center buildings, major expansions, cooling-system changes, or server/electrical-capacity upgrades. I do not request security drawings, detailed site-security plans, or other sensitive records.

Populate `data/manual_templates/campus_buildings.csv`.

A building becomes a model capacity breakpoint only when a completion/final/CO/operation date is supported; an announcement date is not enough.

## 5. EIA-930 PACW historical workbook (canonical) and optional API overlap

Source: https://www.eia.gov/electricity/gridmonitor/dashboard/electric_overview/balancing_authority/PACW

The canonical file is already bundled as the untouched Grid Monitor download `data/raw/eia930/historical/PACW.xlsx`. Do not edit it. Run `python run_prineville.py eia` to build `data/processed/pacw_hourly.csv` through 2024-12-31.

The EIA API is optional overlap validation and future updating, not a replacement for the workbook:

1. Register for a free EIA API key at https://www.eia.gov/opendata/
2. Set `EIA_API_KEY` in the environment.
3. Run `python src/download_eia930.py --discover` first.
4. Then pull 2019-2024 PACW region data as documented in `README.md`.

The API downloader discovers current route metadata/facets before downloading. Do not concatenate API rows onto the workbook.

## 6. EPA eGRID annual cross-check

Source: https://www.epa.gov/egrid

US-customary detailed workbooks for 2010-2023 are already organized under `data/raw/egrid/`. Do not edit them. The historical ZIP remains the provenance archive for 2010-2016. The EPA Power Profiler zip-code tool is `data/raw/egrid/power_profiler/power_profiler_zipcode_tool_v14.2.xlsx` (source: https://www.epa.gov/system/files/documents/2025-06/power_profiler_zipcode_tool_v14.2.xlsx). Run `python run_prineville.py egrid` to rebuild:

- `data/processed/egrid_prineville_annual.csv`
- `outputs/egrid_meta_annual_compare.csv`
- `outputs/egrid_prepare_checks.csv`
- `outputs/egrid_subregion_crosswalk.csv`

This is an annual physical-grid cross-check against Meta campus MWh, not a replacement for hourly EIA-930 and not campus-meter data.

## 6b. Oregon CAMPD / EIA-860 / EIA-923 / cooling (already downloaded)

Raw files are under `data/raw/campd/`, `data/raw/epa_eia_crosswalk/`, `data/raw/eia860/`, `data/raw/eia923/`, and `data/raw/eia_cooling/`. Do not edit them. Rebuild the Oregon-only 2011-2024 pilot with:

```bash
python run_prineville.py oregon
```

This is pipeline validation of plant/unit joins and coverage. It does not identify generators serving the Prineville campus.

## 7. NOAA weather — scripted, but this environment could not bundle the remote CSVs

The package already contains the official NCEI downloader and cleaner. Run locally:

```bash
python src/download_noaa_global_hourly.py --start 2011 --end 2024
python src/prepare_weather.py
```

Baseline station: KRDM / Roberts Field (`72692024230`). Because it is not on campus, also search NOAA/MADIS for a complete Prineville Airport/S39-AWOS historical hourly archive. If obtained, do not blindly splice it: quantify overlap bias by month and weather variable first.

## 8. Truly unavailable without cooperation

These are not normal public datasets. Do not invent them:

- true hourly Meta IT workload;
- rack/server utilization;
- campus feeder-level hourly electricity;
- building-specific PUE/WUE through time;
- building-specific cooling-control setpoints/mode telemetry;
- exact hourly onsite generator dispatch unless logs are released;
- exact campus wastewater discharge unless separately metered/released.

Correct fallback: represent them as latent/fitted states or uncertain parameters and propagate uncertainty. The annual Meta site totals remain the hard closure/validation targets.
