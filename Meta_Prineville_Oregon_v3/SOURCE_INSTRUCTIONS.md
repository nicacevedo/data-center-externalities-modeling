# Exact source-by-source acquisition and use instructions

This file is the operational source guide for the Meta Prineville reconstruction. The governing rule is: **download/preserve the raw source first; normalize second; never overwrite a raw file; never use a lower-quality proxy when a higher-quality site measurement exists.**

## 1. Meta annual site ground truth — electricity, water withdrawal, carbon

### Current canonical source for 2020-2024
- Source ID: `META_2025_INDEX`
- Official source: `https://sustainability.atmeta.com/wp-content/uploads/2025/10/Meta_2025-Environmental-Data-Index.pdf`
- Extract Prineville rows from:
  - Electricity Consumption by Facility, MWh.
  - Water Withdrawal by Facility, megaliters.
  - Market-Based Scope 1 and 2 Emissions by data center.
  - Market-Based vs. Location-Based Scope 2 Emissions by data center.
- Do **not** assign the company-wide electricity/water source mix to Prineville.
- Do **not** treat fleet PUE/WUE as site-specific Prineville observations.

Already curated in: `data/canonical/meta_prineville_annual.csv`.

### Historical sources
Use the latest retrospective disclosure that still reports the historical year:
- `META_2016_DISCLOSURE`: `https://sustainability.atmeta.com/asset/2016-sustainability-data-disclosure/`
  - canonical electricity 2011-2016;
  - canonical early water through 2014 and historical Scope 2 where available.
- `META_2019_DISCLOSURE`: `https://sustainability.atmeta.com/asset/fb_sustainability-data-disclosure-2019/`
  - canonical electricity 2017-2019;
  - canonical water 2015-2019;
  - site carbon for 2017-2019.
- `META_2015_DISCLOSURE`: `https://sustainability.atmeta.com/asset/2015-sustainability-data-disclosure/`
  - retained for 2012 location-based Scope 2 and source-vintage audit.
- `META_2014_DISCLOSURE`: `https://sustainability.atmeta.com/asset/2014-sustainability-data-disclosure/`
  - retained for first-published 2014 water and revision tracking.

Revision audit is already curated in `data/canonical/meta_prineville_source_vintages.csv`. Never replace those revision histories with a single silent value.

### Exact normalization
- MWh: use as reported.
- ML to m3: multiply by 1,000.
- US gallons to m3: multiply by `0.003785411784`.
- tCO2e to kgCO2e: multiply by 1,000.
- average facility MW = annual MWh / actual hours in calendar year.
- facility water intensity L/kWh = annual m3 / annual MWh numerically.

Run `python src/build_targets.py` after edits.

## 2. Meta definitions — PUE, WUE, withdrawal, consumption, discharge

- Source ID: `META_2023_DATA_INDEX`
- Official source: `https://sustainability.atmeta.com/wp-content/uploads/2023/07/Meta-2023-Environmental-Data-Index.pdf`

Use this source to define—not fit—accounting boundaries:
- PUE = total data-center energy / IT electricity load.
- WUE = water withdrawal in liters / IT electricity load in kWh.
- Meta says these metrics can use internal meters, design estimates and utility bills.
- Meta estimates data-center water consumption either as withdrawal minus wastewater discharge or from cooling-system cycles of concentration.

Therefore the model must carry distinct fields for facility energy, IT energy, withdrawal, consumption and discharge.

## 3. Initial Prineville engineering design — physical prior

- Source ID: `META_ENGINEERING_2011`
- Official source: `https://engineering.fb.com/2011/04/14/core-infra/designing-a-very-efficient-data-center/`

Use only for the **initial design epoch**:
- full-load PUE 1.07;
- WUE 0.31 L/kWh;
- 100% outside-air evaporative cooling/humidification;
- winter return-air recirculation;
- no chiller plant/cooling tower;
- hot-aisle containment/ductless distribution;
- reported electrical-system total loss 7.5% for the described design.

Do not propagate these values unchanged to later campus buildings unless permits/engineering evidence supports it.

Implementation: `src/prineville_graybox.py`.

## 4. Campus building / expansion chronology

### Public high-level history
- Meta expansion source: `https://datacenters.atmeta.com/2021/03/facebooks-prineville-data-center-is-growing-again/`
- City 2026 Economic Opportunities Analysis: source URL in `data/source_manifest.csv`.

Already seeded in `data/canonical/campus_events_seed.csv`.

### Required high-value chronology
Obtain the actual permit/final/CO dates from City/Crook County records using the exact request text in `MANUAL_ACQUISITION.md`.
Populate `data/manual_templates/campus_buildings.csv`.

**Rule:** announcement dates are not commissioning dates. If only a date interval is known, encode lower/upper bounds and propagate the date uncertainty; do not invent a point date.

## 5. Official Prineville municipal water-source inventory

- Source ID: `OHA_PWS_00682`
- Official Oregon Drinking Water Services inventory: `https://yourwater.oregon.gov/inventory.php?pwsno=00682`
- Public-water-system ID: 00682.

The package already contains the source/facility IDs, well-log identifiers and status fields in `data/canonical/city_water_sources.csv` for the named municipal wells and individual Crooked River Park wellfield sources.

Use the OHA inventory for **identity/crosswalk**, not for monthly pumping volume.

## 6. OWRD monthly reported water use

- Source ID: `OWRD_WUR_QUERY`
- Official query: `https://apps.wrd.state.or.us/apps/wr/wateruse_query/`

The current project bundles two manual exports already obtained from this query:
- City of Prineville entity export, water years 2010-2025;
- Vitesse LLC c/o Facebook Inc entity export, water years 2011-2024, Report IDs 64500/64845/64846.

Run `python run_prineville.py water` to normalize them. The script preserves measurement method, converts OWRD water-year months to calendar months, labels OWRD's standardized acre-foot unit, and attaches the confidence-aware source crosswalk in `data/canonical/prineville_owrd_source_crosswalk.csv`.

Accepted and candidate source mappings are deliberately separate. Do not treat a blank as zero, do not allocate the combined Airport Well #1/#2 POD across individual wells without another meter, and do not map current DT13 to D13/Report 68003.

OWRD is now used as an **external water-model validation / consistency layer**, not as a replacement for Meta-reported annual campus withdrawal and not as a calibration target. `python run_prineville.py validate` (or `owrd-validate`) rebuilds the conditional reconstruction, then joins:

- reconstructed monthly campus withdrawal (fitted/proxy);
- OWRD Vitesse/Facebook direct groundwater POD use (facility-adjacent evidence; reports 64500/64845/64846);
- OWRD City accepted municipal production (system context only).

These three series remain separately identified. City production is not Meta meter data. Direct POD use is not assumed to be a strict lower bound on campus withdrawal. Actual monthly campus deliveries remain unavailable until City customer-meter records are obtained.

Additional interactive searching is only needed to refresh the exports or resolve still-unlinked sources such as DT14/DT18.

## 7. Prineville ASR / groundwater engineering evidence

### 2020 grant application
- Source ID: `OWRD_ASR_2020_APP`
- Official PDF: `https://www.oregon.gov/owrd/programs/FundingOpportunities/WaterProjectGrantAndLoans/Documents/Applications%20Received%202020%20Cycle/PrinevilleASR_Application.pdf`

Use for:
- intervention/event chronology;
- ASR well/pipeline project scope;
- planned storage capacity;
- pilot/construction date ranges;
- municipal peak-demand context.

### 2018 feasibility study / 2020 attachments
- Source ID: `OWRD_ASR_2020_ATTACH`
- Official PDF: `https://www.oregon.gov/owrd/programs/FundingOpportunities/WaterProjectGrantAndLoans/Documents/Applications%20Received%202020%20Cycle/PrinevilleASR_Attachments.pdf`

Use for:
- hydrogeologic architecture;
- aquifer/storage coefficients and ranges;
- Heliport/Millican hydrographs and well information;
- ASR injection/recovery assumptions;
- groundwater-model priors and sensitivity ranges.

These are regional water-system priors/validation evidence, **not Meta-specific meter readings**.

## 8. City utility records — highest-value missing site water data

- Official public-record page: `https://www.cityofprineville.com/1294/Public-Records`
- Non-police record requests: `recorder@cityofprineville.com`.

Use the ready-to-copy request in `MANUAL_ACQUISITION.md` for:
- monthly Meta/Facebook water delivered;
- monthly wastewater/sewer discharge if separately metered;
- municipal well production by well;
- ASR injection/recovery;
- groundwater-head observations;
- meter methodology/change dates.

Raw responses go under `data/raw/city/` and are never overwritten.

## 9. Weather — NOAA/NCEI Global Hourly

- Source ID: `NOAA_ISD`
- Documentation: `https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database`
- Stable baseline station used by the package: KRDM / Roberts Field, Global Hourly file ID `72692024230`.
- Direct yearly file template: `https://www.ncei.noaa.gov/data/global-hourly/access/{YEAR}/72692024230.csv`

Run:
```bash
python src/download_noaa_global_hourly.py --start 2011 --end 2024
python src/prepare_weather.py
```

Why KRDM is the baseline: the direct NCEI Global Hourly archive is stable across the target years. It is **not on the campus**. A closer Prineville Airport/S39-AWOS record should be acquired when a complete hourly archive can be verified, then used to quantify local station bias or replace KRDM only after overlap validation.

Required weather columns after processing:
- UTC timestamp;
- dry-bulb temperature;
- dew point;
- station pressure;
- RH derived from T/dewpoint;
- wet-bulb derived psychrometrically;
- precipitation/wind where reliable;
- source/gap-fill flags.

## 10. Physical grid context — EIA-930 / PacifiCorp West

- Source IDs: `EIA930`, `EIA_PACW`
- Grid Monitor: `https://www.eia.gov/electricity/gridmonitor/about`
- PACW dashboard: `https://www.eia.gov/electricity/gridmonitor/dashboard/electric_overview/balancing_authority/PACW`
- Balancing authority: `PACW`.

Canonical historical file (leave untouched):

```text
data/raw/eia930/historical/PACW.xlsx
```

This is EIA's individual-BA full reported history. It is balancing-authority demand, forecast, generation and interchange—not campus feeder data. Prepare:

```bash
python run_prineville.py eia
```

`src/prepare_eia930.py` keeps reported/imputed/adjusted MWh as separate columns, joins EIA known-data-issue flags, and cuts the reconstruction window at `2024-12-31 23:59 UTC`. It compares 2019-2024 workbook values with the API when `PACW_region-data_2019_2024.csv` is present; it does **not** concatenate the two.

The API remains useful for overlap checks and later updates:

```bash
export EIA_API_KEY='YOUR_FREE_EIA_KEY'
python src/download_eia930.py --discover
python src/download_eia930.py --start 2019-01-01 --end 2024-12-31
```

Use PACW only as a regional physical-grid context/proxy. It is not the campus feeder meter.

## 11. Annual physical-emissions cross-check — EPA eGRID

- Source ID: `EPA_EGRID`
- Current detailed-data page: `https://www.epa.gov/egrid/detailed-data`
- Historical archive: `https://www.epa.gov/egrid/historical-egrid-data`

For each model year, download the matching/historical eGRID data workbook when available and extract the relevant subregion/plant/BA fields after verifying the campus electricity-service crosswalk.

Use eGRID output emission rates as an annual physical-grid cross-check. Keep Meta market-based/REC accounting separate.

## 12. Renewable accounting / Schedule 272 context

- Source ID: `OREGON_BER_RENEWABLE`
- URL is in `data/source_manifest.csv`.

Use only to interpret the market-vs-location emissions break and renewable certificate arrangement. Do not infer that the campus physically consumed the same generators' output each hour.

## 13. What cannot be obtained from these public sources

Do not manufacture:
- true hourly IT workload;
- rack/server utilization;
- building-specific PUE/WUE through time;
- campus feeder-level hourly electricity;
- exact cooling setpoint/control telemetry;
- exact hourly backup-generator dispatch;
- site-specific water consumption unless discharge/CoC evidence is obtained.

Use the missing-data protocol in `MISSING_DATA_PROTOCOL.md` instead.
