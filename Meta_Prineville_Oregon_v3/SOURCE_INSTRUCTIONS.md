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

A high-value local package is already present at `data/raw/prineville_strictly_valuable_permits_v2/`. Integrate it with `src/integrate_prn1_permit_evidence.py` (called from `python run_prineville.py audit`). Do not rescan unrelated `permits_pdfs/` for this package. Do not convert amp/circuit counts to MW or pipe diameter to consumption. The PRN1 late-2023/early-2024 transition is interpretation/scenario evidence and is not used to retune gray-box or the 2023–2024 water holdout.

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

Run `python run_prineville.py water` to normalize them. Outputs are written under `data/processed/owrd/`. The script preserves measurement method, converts OWRD water-year months to calendar months, labels OWRD's standardized acre-foot unit, and attaches the confidence-aware source crosswalk in `data/canonical/prineville_owrd_source_crosswalk.csv`.

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

The catalogued filenames `PrinevilleASR_Application.pdf` and `PrinevilleASR_Attachments.pdf` were not present under `data/raw/` (including `data/raw/permits_pdfs/`) at the GWIS integration stage. Local Crook County permit PDFs were scanned with machine-readable text extraction; they are inspection-summary documents and currently add no transmissivity, storativity, specific yield, or pumping-test values. Do not re-download in the no-download pipeline. Prefer tabular GWIS water levels over digitizing ASR hydrograph figures. `python run_prineville.py groundwater-identifiability` audits pumping↔head overlap for a possible small empirical subsystem; it does not fit a groundwater-response model.

### Local GWIS well/level exports
- Source ID: `OWRD_GWIS`
- Local files: `data/raw/gwis_data_new/`

Use for:
- official well/tag/log identifiers and coordinates;
- measured water levels (ft below land surface and GWIS-reported AMSL with datum);
- well depth, open-interval construction, lithology/aquifer names as reported.

Do not map a Vitesse-named GWIS well to POD reports 64500/64845/64846 unless the official well/tag/log ID matches. Duplicate export files must not double-count observations. Mixed vertical datums are not converted. This is not a groundwater dynamics model.

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

## 9. Weather — NOAA/NCEI Global Hourly and NOAA MADIS KS39

- Source ID: `NOAA_ISD` / `NOAA_GH_KRDM_FILES`
- Documentation: `https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database`
- KRDM / Roberts Field, Global Hourly file ID `72692024230`. Nearby reference station, not on campus.
- Direct yearly file template: `https://www.ncei.noaa.gov/data/global-hourly/access/{YEAR}/72692024230.csv`

- Source ID: `NOAA_MADIS_KS39`
- Official MADIS METAR archive: `https://madis-data.ncep.noaa.gov/madisPublic1/data/archive/YYYY/MM/DD/point/metar/netcdf/YYYYMMDD_HH00.gz`
- Station: KS39 / Prineville Airport. Coordinates/elevation are taken from the extracted records (approximately 44.28 N, −120.90 W, 991 m).
- QC: NOAA MADIS surface QC notes (`https://madis.ncep.noaa.gov/madis_sfc_qc_notes.shtml`). Model aggregates exclude DD `X`/`B`/`Q` and QCR validity-bit failures. ICA/ICR words are preserved; their bit layout is not interpreted.
- Acquisition window: 2015-08-01 00:00 UTC through 2025-01-02 00:00 UTC. Do not bulk-download 2011–2014; sampled MADIS files showed no regular KS39 then.
- Scientific canonical rule: KRDM through 2015-08-31 local (`America/Los_Angeles`); from 2015-09-01 local, QC-usable KS39 when present, else KRDM gap-fill. August 2015 KS39 is audit-only.
- Pressure: MADIS `seaLevelPress` is often missing. Usable input is `altimeter` (Pa). Station pressure is **derived** via ICAO standard atmosphere from altimeter + elevation. RH and wet-bulb remain derived from T, Td, and pressure.
- Outputs: `data/raw/noaa_madis_ks39/`, `data/processed/weather_ks39_hourly.csv`, `data/processed/weather_krdm_hourly.csv`, canonical `data/processed/weather_hourly.csv`, `outputs/ks39_coverage_*.csv`, `outputs/ks39_krdm_overlap_*.csv`.

Run:
```bash
python src/download_noaa_global_hourly.py --start 2011 --end 2024
python src/prepare_weather.py
python src/download_madis_ks39.py --workers 4
python src/download_madis_ks39.py --export-only
python src/prepare_weather_ks39.py
```

`prepare_weather.py` writes the KRDM baseline only (`weather_krdm_hourly.csv`). Canonical model weather is assembled by `prepare_weather_ks39.py`. Pre-2015 KRDM monthly additive bias correction is tested on KS39 overlap holdout years and adopted only if that station test is stable and material; it is not tuned on Meta water.

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

EIA-930 measures **balancing-authority operations**: demand, demand forecast, net generation, total interchange, bilateral interchange, generation by fuel, and (from 2018-07) EIA-reported CO2 emissions/intensity for generated and consumed electricity. Those series are observed PACW values, not Prineville campus meters. The fuel/import carbon score, if used, is a derived proxy. There is no EIA-930 PACW coverage before 2015-07-01. Do not invent EIA-930 hours. A separate FERC-constrained proxy (section 10.5) may fill pre-EIA PACW **demand shape** only and must remain labeled proxy.

The API remains useful for overlap checks and later updates:

The API remains useful for overlap checks and later updates:

```bash
export EIA_API_KEY='YOUR_FREE_EIA_KEY'
python src/download_eia930.py --discover
python src/download_eia930.py --start 2019-01-01 --end 2024-12-31
```

Use PACW only as a regional physical-grid context/proxy. It is not the campus feeder meter.

Time semantics: EIA-930 PACW hours are **hour-ending UTC**. FERC Form 714 Schedule 2 hours are **hour-ending local Pacific prevailing time**. Do not mix the two clocks.

## 10.5 FERC Form 714 — PacifiCorp West monthly and East+West hourly (2011–2018)

- Source ID: `FERC_FORM_714`
- Leave all files under `data/raw/ferc_form_714/` untouched.
- Discover filings programmatically (`src/prepare_ferc714.py`); do not hard-code filenames.
- West-specific annual filings: extract monthly `west_net_energy_for_load_mwh`, `west_net_generation_mwh`, `west_net_interchange_mwh`, `west_monthly_peak_mw`, `west_monthly_minimum_mw`, plus filing/source identifiers and timezone/provenance.
- East+West combined Schedule 2 filings: extract the complete reported hourly demand series with original date/hour/time-zone metadata. **Never label this series PACW-West.**
- Prepare:

```bash
python run_prineville.py ferc
```

Writes `data/processed/ferc714/pacw_west_monthly.csv`, `pacificorp_east_west_hourly.csv`, `pacw_hourly_backcast.csv`, optional `data/processed/pacw_demand_hourly_extended.csv`, and `outputs/ferc714_*.csv`. Does **not** overwrite `data/processed/pacw_hourly.csv`.

The FERC-only backcast uses East+West hours for intramonth shape and West monthly NEL/peak/minimum for level (`Dhat_W = mean_W + b_m (D_EW - mean_EW)`, `b_m ≥ 0`, exact monthly energy closure to NEL). EIA-930 is not used to fit `b_m`. Monthly NEL vs EIA-930 is a cross-source consistency test, not a calibration target. If definitions or magnitudes disagree, keep both series and do not promote the early hourly backcast as observed PACW demand.

FERC is regional/grid context only. Do not use it to manufacture consumed CO2 intensity, fuel mix, hourly interchange, Meta campus electricity, or marginal emissions. Do not replace the EIA PACW file used by stochastic carbon sensitivity.

`python run_prineville.py grid` is EIA-930 → FERC 714 → eGRID.

## 11. Annual physical-emissions cross-check — EPA eGRID

- Source ID: `EPA_EGRID`
- Current detailed-data page: `https://www.epa.gov/egrid/detailed-data`
- Historical archive: `https://www.epa.gov/egrid/historical-egrid-data`

Raw US-customary detailed workbooks are organized under `data/raw/egrid/` (leave them untouched). The 1996-2016 archive ZIP stays in `data/raw/egrid/historical/`; 2010/2012/2014/2016 detailed files were extracted from that ZIP without modifying it.

```bash
python run_prineville.py egrid
```

`src/prepare_egrid.py` reads eGRID **subregion total output emission rates** (lb/MWh) for electricity-consumption accounting. Non-baseload rates are stored separately and are not ordinary Scope 2 factors. CH4/N2O rates labeled lb/GWh (eGRID 2010/2012/2014) are converted to lb/MWh. Resource-mix codes are labeled "percent" in every vintage; 2010-2016 store 0-100 and 2018+ store 0-1 fractions. The script detects the scale from the selected subregion row instead of guessing.

The Prineville consumption-location subregion is selected from EPA's Power Profiler zip-code tool (`data/raw/egrid/power_profiler/power_profiler_zipcode_tool_v14.2.xlsx`, sheet `Zip-subregion`). Campus ZIP **97754** maps uniquely to **NWPP (WECC Northwest)**; Subregion 2/3 are blank, so EPA does not require a utility tie-breaker. PacifiCorp / Pacific Power is recorded as the campus service utility. Each eGRID vintage's plant file is retained only as corroboration (Crook County / Oregon plants agree with NWPP; PACW generators may include a CAMX/MROW tail and are not the selection rule).

Model-year vintage map:

```text
2011 → eGRID2010
2012 → eGRID2012
2013 → eGRID2012
2014 → eGRID2014
2015 → eGRID2014
2016 → eGRID2016
2017 → eGRID2016
2018 → eGRID2018
2019 → eGRID2019
2020 → eGRID2020
2021 → eGRID2021
2022 → eGRID2022
2023 → eGRID2023
2024 → eGRID2023
```

The annual benchmark is:

`CO2_y^{eGRID} = E_y^{Meta} × EF_y^{eGRID}`

with pounds converted to metric tonnes by dividing by 2204.6226218487757. `E_y^{Meta}` is Meta-reported campus electricity from `data/canonical/meta_prineville_annual.csv`, not PACW regional demand. Compare location-based physical totals with Meta location-based Scope 2 where disclosed. Keep market-based/REC accounting separate.

eGRID measures annual generation-weighted subregion output rates, not hourly campus intensity and not PACW BA demand.

## 12. Oregon generator / CEMS / cooling pilot (pipeline validation only)

- Sources: CAMPD Oregon hourly (2011-2024), EPA/EIA unit crosswalk, EIA-860 annual, EIA-923 annual, EIA standardized cooling-detail (2014-2024).
- Command: `python run_prineville.py oregon`
- Raw files under `data/raw/campd/`, `data/raw/epa_eia_crosswalk/`, `data/raw/eia860/`, `data/raw/eia923/`, and `data/raw/eia_cooling/` are never modified.

Rules:
- Filter EIA-derived analysis tables to Oregon after read; do not alter national ZIPs/xlsx.
- CAMPD native key is Facility ID × Unit ID × Date × Hour. Posted CO2/NOx/SO2 mass and heat input are **not** multiplied by Operating Time. `Gross Load (MW)` is a rate; hourly gross generation is Gross Load (MW) × Operating Time when both are reported.
- Blanks stay missing; reported zeros stay zero.
- Join CAMD Facility+Unit to the EPA/EIA crosswalk, then to EIA plant/generator/boiler IDs. Do not explode CEMS hours across generator rows. Stop if that join would duplicate emissions.
- Aggregate CAMPD to EIA plant × year × month. Compare CAMPD gross generation (MW × Operating Time) with EIA-923 net generation as a join/coverage diagnostic; inequality is expected.
- Standardized cooling water (million gallons) is used for 2014-2024. 2013 Schedule 8 volumes are used where reported in million gallons. 2011-2012 Schedule 8 flow rates are **not** converted: native units are not defensibly the same as the later product.
- Water intensities use cooling-product water over cooling-associated generation only. Emission intensities use CAMPD mass over CAMPD gross generation only. Negative official cooling consumption is not clipped and is not used for intensity.
- This layer does **not** identify which generators served the Prineville campus. Do not expand to other states until Oregon QC passes.

## 12.5 Oregon DEQ Vitesse air permit / GHG (onsite generation, independent)

- Sources: collected PDFs under `data/raw/deq_air/` (permit 07-0037, 2012-2025) and workbooks under `data/raw/deq_ghg/`.
- Command: `python run_prineville.py deq`
- Scripts: `src/prepare_deq_prineville.py`, `src/prepare_deq_ghg.py`, `src/audit_deq_prineville.py`.
- Raw files are never modified.

Rules:
- Observation year/month come from the table token (`Jan-20`), not the filename. A 2012 annual report may still contain 2013 month cells; those are 2013 observations.
- Rolling 12-month totals are diagnostics only. Canonical monthly operations use the monthly column. Repeated reprints of the same generator-month across later annual reports are collapsed to one row (prefer the same-year annual report) rather than summed.
- Preserve conflicting vintages. Flag, do not silently pick, the 150 kW vs 177 kW John Deere rating, the 6068HF285 vs 4045HF285 model strings, the 2018 2.5 MW vs 2019 3.0 MW class for PRN3-EG-N1..N4, and the 2019 PMRR 148.7 vs 248.7 MW arithmetic.
- Generator states are separate: proposed / authorized / installed-listed / active / retired. Never treat proposed units as active without hours-table or commissioning evidence.
- Never interpret backup nameplate MW as IT capacity or facility load.
- Never treat PSEL/PTE permit limits as actual emissions.
- Keep source-test measurements (`data/processed/meta_backup_source_tests.csv`) separate from DEQ-calculated annual-report emissions.
- Keep onsite DEQ tons separate from grid Scope 2, eGRID NWPP, and PACW.
- Missing stays missing. Scan-only PDFs (2019/2021 ARs; 2020 and 2022 permit/review scans) are not OCR'd.
- Process `ghgElectricityEms.xlsx` for Pacific Power (PacifiCorp) Oregon deliveries. Other GHG workbooks are provenance unless they contain Vitesse 07-0037 observations (none identified).
- Do not rewrite `data/canonical/campus_events_seed.csv`. The join is `outputs/deq_campus_event_crosswalk.csv`.

## 12.6 USGS NWAA HUC12 water (modeled regional context)

- API: `https://api.water.usgs.gov/nwaa-data/data`
- Catalog: `https://api.water.usgs.gov/nwaa-data/models`
- Command: `python run_prineville.py usgs`
- Scripts: `src/download_usgs_nwaa.py`, `src/build_usgs_huc12_panels.py`, `src/build_municipal_huc12_crosswalk.py`, `src/audit_usgs_nwaa.py`
- Order: download/organize → HUC12 panels → municipal HUC12 crosswalk → audit.
- Raw files under `data/raw/usgs_nwaa/` are never modified after retrieval.

Official model IDs (do not guess):
- `iwa-assessment-outputs-conus-2025` (`sui`, `availab`, `strflow`, `consum`), 2009-10–2020-09
- `wu-public-supply-cu` (`pscutot`), 2009-01–2020-12
- `wu-public-supply-wd` (`pswdtot`, `pswdgw`, `pswdsw`), 2000-01–2020-12
- `wu-irrigation-wd` (`irrwdtot`), 2000-01–2020-12
- `wu-irrigation-cu` (`irrcutot`), 2000-01–2020-12

Rules:
- Preserve raw API responses separately from processed panels. HUC12 IDs stay 12-character strings.
- IWA `strflow` is cumulative upstream + local supply. IWA `consum` is cumulative upstream + local consumptive use. `availab = strflow - consum` is an internal consistency check, not independent validation.
- `pscutot` is modeled public-supply consumptive use, not Meta-specific use. None of these USGS variables are campus water-meter observations.
- Do not force source-specific tables onto the shorter IWA period. Overlap panels are separate and cover 2009-10–2020-09.
- Do not sum `pscutot` or `irrcutot` into IWA `consum`.
- IWA cannot support 2021–2024 analysis by itself.
- Thermoelectric (`wu-thermoelectric`) is screened for HUC8 `17070305` only. If modeled withdrawals are zero, do not add the series to panels.
- Municipal source → HUC12 assignment uses official coordinates only. Do not infer well locations from TRSQQ.

## 12.7 Source-aware water context

- Command: `python run_prineville.py water-context`
- Script: `src/build_water_context.py`
- Inputs: existing `data/processed/owrd/` monthly products, USGS HUC12 panels, municipal HUC12 crosswalk, Meta annual water, canonical KS39/KRDM hourly weather.
- Outputs: `data/processed/water/water_source_monthly_context.csv`, `data/processed/water/prineville_water_monthly_context.csv`, `outputs/qc/water_context_qa.csv`.
- Layout: raw OWRD/USGS/City under `data/raw/<source>/`; geography under `data/canonical/usgs/`; source-specific products under `data/processed/owrd/` and `data/processed/usgs_nwaa/`; integrated tables only under `data/processed/water/`.

Rules:
- Reuse the OWRD monthly layer; do not rebuild it here.
- Never sum or equate City production, Vitesse/Facebook PODs, Meta annual withdrawal, and USGS modeled HUC12 series.
- If a source has no verified in-study HUC12, USGS columns stay missing. Do not infer from well names or the Meta campus.
- USGS values are missing after their official end dates (IWA 2020-09; public-supply CU/WD and irrigation 2020-12). Do not extrapolate.
- Meta campus withdrawal is annual; do not treat it as a monthly meter.
- Candidate/conflict City mappings never enter primary City totals.

## 13. Renewable accounting / Schedule 272 context

- Source ID: `OREGON_BER_RENEWABLE`
- URL is in `data/source_manifest.csv`.

Use only to interpret the market-vs-location emissions break and renewable certificate arrangement. Do not infer that the campus physically consumed the same generators' output each hour.

## 14. What cannot be obtained from these public sources

Do not manufacture:
- true hourly IT workload;
- rack/server utilization;
- building-specific PUE/WUE through time;
- campus feeder-level hourly electricity;
- exact cooling setpoint/control telemetry;
- exact hourly backup-generator dispatch;
- site-specific water consumption unless discharge/CoC evidence is obtained.

Use the missing-data protocol in `MISSING_DATA_PROTOCOL.md` instead.
