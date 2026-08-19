# Meta Prineville public-data reconstruction seed

This is the **canonical Prineville v3 package**. Develop here, not under `simulation/`. Earlier packages remain at `Meta_Prineville_Oregon/` and `Meta_Prineville_Oregon_v2/`.

This package is a curated starting point for a **public-data gray-box reconstruction** of the Meta Prineville data-center campus. Its intended standard is:

1. exact reproduction of published annual site quantities;
2. physics-constrained subannual reconstruction using real weather/grid/water-system data;
3. chronological held-out validation;
4. sensitivity and counterfactual analysis with explicit uncertainty.

It is **not** a claim that public data identify Meta's private hourly IT workload or meter telemetry.

## What is already curated here

- `data/canonical/meta_prineville_annual.csv`: canonical 2011-2024 site electricity, 2014-2024 water withdrawal, location-based Scope 2 where separately reported, and operational Scope 1+2; plus transparent derived annual intensities.
- `data/canonical/meta_prineville_source_vintages.csv`: known historical revisions, especially the 2014-2016 water series.
- `data/canonical/meta_fleet_kpis.csv`: fleet PUE/WUE, explicitly marked non-site-specific.
- `data/canonical/campus_events_seed.csv`: only events sufficiently supported to seed change-point interpretation.
- `data/canonical/city_water_sources.csv`: official Oregon Drinking Water Services PWS 00682 source inventory, including source IDs and well-log identifiers for the Prineville municipal system.
- `data/canonical/prineville_owrd_source_crosswalk.csv`: conservative OHA↔OWRD Report-ID crosswalk with accepted, candidate, conflict and unresolved mappings.
- `data/canonical/owrd_report_index.csv`: the 57 City of Prineville OWRD report IDs from the 2010-2025 entity export.
- `data/canonical/meta_owrd_direct_sources.csv`: verified OWRD POD registry for the three Vitesse LLC c/o Facebook Inc reports (64500, 64845, 64846).
- `data/raw/owrd/wateruse_entity_report.csv` and `wateruse_entity_report_facebook.txt`: raw City and Vitesse/Facebook OWRD entity exports.
- `data/raw/eia930/historical/PACW.xlsx` and `src/prepare_eia930.py`: canonical PACW EIA-930 history (`python run_prineville.py eia`).
- `data/raw/egrid/` and `src/prepare_egrid.py`: EPA eGRID subregion output rates × Meta campus MWh (`python run_prineville.py egrid`).
- `data/raw/deq_air/` and `data/raw/deq_ghg/`: Oregon DEQ Vitesse 07-0037 air-permit PDFs (2012-2025) and DEQ electricity-supplier GHG workbooks. Independent onsite-generation module (`python run_prineville.py deq`); not grid Scope 2.
- `src/prepare_owrd_wateruse.py`: deterministic water-year/calendar-month normalization and confidence-aware source joining.
- `data/source_manifest.csv`: exact source URLs, role, resolution, quality and whether manual action is needed.
- `data/canonical/source_priority_matrix.csv`: one-row-per-quantity preferred source, fallback and validation role.
- `SOURCE_INSTRUCTIONS.md`: exact source-by-source extraction/use instructions.
- `MISSING_DATA_PROTOCOL.md`: strict rules for filling/downscaling only what is legitimately inferable.
- `DATA_DICTIONARY.md`: canonical columns and provenance labels.
- `data/manual_templates/`: schemas for the high-value records that are not already public in machine-ready form.
- source download/cleaning/validation scripts under `src/`.

## Canonical source-selection rule

When Meta retrospectively revises a quantity, prefer the **latest retrospective value that still reports the historical year**, and preserve the older values in the source-vintage table. This avoids silently mixing reporting vintages.

Examples:
- Prineville 2014 water was first reported as 15.0 million gal, later 11.0 million gal, then 10.5 million gal. The canonical file uses 10.5 million gal = 39,746.823732 m3.
- For 2015-2019 water, the 2019 disclosure is canonical because it is the latest retrospective site table found for those years.

## Recommended build order

### Stage 0 — install

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
```

### Stage 1 — validate the curated annual ground truth

```bash
python src/build_targets.py
```

This checks:
- complete electricity coverage 2011-2024;
- no negative quantities;
- correct annual hour counts including leap years;
- unit-consistent derived water/emission intensities;
- no accidental use of fleet KPIs as site targets.

### Stage 2 — download NOAA hourly weather

The stable public baseline station is **KRDM / Redmond Roberts Field**. NCEI Global Hourly files for this modern record use file ID `72692024230`. This is a nearby reference station, **not an on-campus station**. A closer Prineville Airport/S39-AWOS record should be acquired when a complete hourly archive is verified and used for overlap bias testing before replacing the KRDM baseline.

```bash
python src/download_noaa_global_hourly.py --start 2011 --end 2024
python src/prepare_weather.py
```

The downloader uses:

```text
https://www.ncei.noaa.gov/data/global-hourly/access/{YEAR}/72692024230.csv
```

The cleaner parses NOAA scaled temperature/dew-point/pressure fields, removes missing sentinels/failed values, resamples to a regular hourly UTC index, computes RH, and uses PsychroLib for pressure-aware wet-bulb temperature.

**Fallback rule:** if a year is absent or has material gaps, do not silently interpolate long gaps. Add a secondary nearby NCEI station/reanalysis only for the missing intervals and add a provenance flag.

### Stage 3 — normalize the bundled OWRD monthly water-use exports

The project now bundles the 2010-2025 City of Prineville OWRD entity export plus the 2011-2024 Vitesse LLC c/o Facebook Inc entity export. Run:

```bash
python run_prineville.py water
```

This creates:
- `data/processed/owrd_city_monthly_report_use.csv`: every City report-month, including unmapped/legacy reports;
- `data/processed/owrd_city_monthly_model_use.csv`: **accepted-only** canonical source/reporting groups;
- `data/processed/owrd_city_monthly_candidate_use.csv`: high-confidence DT4-DT12 candidates kept separate from the default model;
- `data/processed/owrd_meta_direct_monthly_use.csv`: the three Vitesse/Facebook direct OWRD POD series;
- annual calendar-year summaries and `outputs/owrd_mapping_audit.csv`.

OWRD water years are converted to actual calendar months. OWRD's query reports these values in acre-feet; zero is preserved as a reported zero and blank remains missing. Airport Wells #1/#2 share Report 62423 and therefore remain a single combined reporting group so their volume is not double-counted.

The default model uses only accepted mappings. Candidate D4-D12 mappings are available for sensitivity/review but are not automatically promoted. DT13 is explicitly excluded from D13/Report 68003 because the well identifiers conflict. DT14 and DT18 remain unresolved on the water-use-report side and are not imputed as zero.

The City municipal series and Vitesse/Facebook direct POD series have different accounting boundaries and are never summed automatically. Remaining high-value acquisition is City/Meta meter data, City well-production/ASR records, discharge, and final resolution of unresolved POD identities where needed.

### Stage 3.5 — USGS NWAA HUC12 water module (modeled regional context)

This step finishes the USGS National Water Availability Assessment (NWAA) HUC12 water layer for the Meta Prineville study geography. It does **not** estimate Meta water use, assign treatment timing, or run an event study.

```bash
python run_prineville.py usgs
```

Verified geography is preserved: site HUC12 `170703051002` (designated `site_point_huc12`; campus-footprint verification remains outstanding), 9-HUC local scope, 52-HUC same-HUC8 scope. Raw API responses stay under `data/raw/usgs_nwaa/`; processed panels under `data/processed/usgs_nwaa/`; QA under `outputs/qc/`.

Processed IWA names are explicit because the native labels are easy to misread:

- `iwa_cumulative_streamflow_mm_month` (`strflow`) is cumulative upstream + local surface-water supply.
- `iwa_cumulative_consumption_mm_month` (`consum`) is cumulative upstream + local consumptive use, not local HUC12 consumption alone.
- `iwa_surface_water_availability_mm_month` (`availab`) = `strflow - consum` (internal consistency check, not independent validation).
- `iwa_sui` is a modeled surface-water supply/use indicator.
- `pscutot` / `public_supply_consumption_mgd` is modeled public-supply consumptive use, not Meta-specific use.

IWA ends in **2020-09** and cannot by itself support the 2021–2024 portion of the Prineville analysis. None of these USGS series are campus water-meter observations. Do not add `pscutot` or `irrcutot` into IWA `consum`.

### Stage 4 — build the campus chronology

Use `data/canonical/campus_events_seed.csv` as the seed, then complete `data/manual_templates/campus_buildings.csv` from Crook County/City permit records.

The highest-value fields are:
- permit/building identifier;
- permit issue date;
- substantial completion/final/CO date;
- square footage;
- electrical service/capacity if stated;
- cooling/mechanical system description;
- retrofit dates.

Do **not** assign a technology epoch merely because an expansion was announced. Use commissioning/final dates or statistically detected structural breaks, then interpret those breaks against the permit chronology.

### Stage 5 — grid/emissions series

Prineville's renewable-accounting relationship with PacifiCorp is documented separately from physical electricity delivery. For physical regional grid behavior, use EIA-930 with balancing authority `PACW`.

The canonical historical file is the untouched Grid Monitor workbook:

```text
data/raw/eia930/historical/PACW.xlsx
```

Prepare the reconstruction-window hourly table (through 2024-12-31 23:59 UTC) with EIA quality fields retained:

```bash
python run_prineville.py eia
```

This writes `data/processed/pacw_hourly.csv`. Reported, imputed, and adjusted MWh remain separate columns. The EIA API is **not** concatenated into this history; it is for overlap validation and future updating:

```bash
export EIA_API_KEY='YOUR_KEY'
python src/download_eia930.py --discover
python src/download_eia930.py --start 2019-01-01 --end 2024-12-31
```

EPA eGRID annual subregion **total output emission rates** are the independent annual physical-grid cross-check. They are not PACW hourly data and not campus meters:

```bash
python run_prineville.py egrid
```

`python run_prineville.py grid` runs EIA-930 preparation then eGRID. Do not put these workbook rebuilds inside `audit`.

Use:
- PACW demand, demand forecast, net generation, total interchange, bilateral interchange, and generation-by-fuel as **regional balancing-authority context** (workbook from 2015-07-01; `NG:*` fuel mix and EIA-reported CO2 intensity from 2018-07);
- EIA-reported PACW consumed CO2 intensity as the preferred regional physical carbon-shape diagnostic when present; the fuel/import score is a named sensitivity proxy only;
- Meta-reported annual campus MWh × eGRID NWPP (WECC Northwest) total output rates as the annual location-based physical benchmark, with NWPP selected from EPA Power Profiler ZIP 97754 (PacifiCorp/Pacific Power service; plant files corroborate only).

Never treat PACW demand as campus electricity. Never treat eGRID non-baseload rates as ordinary Scope 2 factors. Never treat either PACW series as Meta-specific marginal emissions. Market-based/REC accounting stays separate.

eGRID vintage map used here: 2011→2010, 2012–2013→2012, 2014–2015→2014, 2016–2017→2016, then matching years through 2023, and **2024→eGRID2023**.

### Stage 5.5 — Oregon generator/emissions/cooling pilot (pipeline validation)

This step integrates CAMPD, the EPA/EIA unit crosswalk, EIA-860, EIA-923, and EIA cooling **for Oregon 2011–2024 only**. It does **not** infer which plants served the Prineville campus and must pass QC before any other-state expansion.

```bash
python run_prineville.py oregon
```

Writes Oregon-filtered processed tables under `data/processed/` and QC files under `outputs/oregon_*`. CAMPD posted mass and heat input are not multiplied by Operating Time. CAMPD Gross Load (MW) is converted to hourly MWh as rate × Operating Time. Crosswalk joins are not exploded to generator rows. 2011–2012 Schedule 8 cooling volumes are left missing because the native flow-rate units are not defensibly comparable to the 2013+ / 2014–2024 million-gallon product.

EIA-923 Plant Frame `Reporting Frequency` / `Respondent Frequency` is joined at plant-year. For frequency `A`, published monthly Netgen is not treated as a respondent monthly observation; primary CAMPD/EIA-923 generation QC is the plant-year reconciliation in `outputs/oregon_campd_eia923_annual_reconciliation.csv` (gross vs net, envelope 0.85–1.15). Monthly ratios remain diagnostics. Monthly reporters (`M`, `AM`, `AM/A`) stay eligible for monthly discrepancy QC. Neither source is rescaled.

### Stage 5.6 — Oregon DEQ onsite generation / local emissions (independent module)

This step reads the collected Oregon DEQ Vitesse/Meta Prineville air-permit PDFs (`data/raw/deq_air/`, permit 07-0037) and DEQ GHG workbooks (`data/raw/deq_ghg/`). It does **not** change OWRD, EIA-930, eGRID, Oregon CAMPD/EIA, gray-box, or stochastic outputs.

```bash
python run_prineville.py deq
```

Writes canonical inventory/events, processed monthly hours/fuel/emissions/source tests, Pacific Power DEQ GHG annual rows, and `outputs/deq_*` QC. Backup nameplate MW is emergency capacity, not IT or facility load. PSEL/PTE are not actual emissions. Source tests stay separate from annual-report calculated emissions. Onsite DEQ tons stay separate from Scope 2 / eGRID / PACW. Scan-only pages are not OCR'd. Proposed generators are not treated as active without hours-table evidence.

### Stage 6 — run the baseline audit

```bash
python run_prineville.py audit
```

This produces `outputs/annual_audit.csv` and fails on accounting/provenance errors.


### Stage 6.5 — run the strongest defensible annual-data-only conditional reconstruction

Once `data/processed/weather_hourly.csv` exists:

```bash
python run_prineville.py conditional
```

This does **not** invent hourly IT telemetry. For each year it fits one latent IT-power scale so modeled facility electricity closes exactly to the reported Meta annual MWh, uses hourly weather/psychrometrics to generate PUE/cooling/water shape, fits a parsimonious global or one-break water scale on **2014-2022 training years only**, and predicts 2023-2024 water as holdout. The break, if selected, is statistical evidence only until an independent permit/engineering event explains it. Outputs are:

- `outputs/hourly_conditional_reconstruction.csv` (generated; not tracked in git)
- `outputs/conditional_annual_compare.csv`
- `outputs/conditional_water_model.csv`

This is the correct baseline to improve once monthly City customer-meter records arrive. Bundled OWRD series are **not** used as campus-meter substitutes or calibration targets.

The same command rebuilds the hourly reconstruction and then runs the OWRD external consistency layer (`src/owrd_water_model_validation.py`). `python run_prineville.py validate` and `owrd-validate` also rebuild before comparing, so they cannot silently use a stale hourly file:

```bash
python run_prineville.py owrd-validate
```

Outputs:
- `outputs/owrd_water_model_validation.csv`
- `outputs/owrd_water_model_validation_annual.csv`
- `outputs/owrd_water_model_validation_checks.csv`
- `outputs/owrd_water_model_validation.png`

City production is municipal-system context. Vitesse/Facebook OWRD observations are direct groundwater POD records. Meta annual withdrawal remains the primary campus-level annual observation. Actual monthly campus deliveries remain unavailable until City customer-meter records are obtained.

### Stage 6.6 — run the stochastic conditional proxy

```bash
python run_prineville.py simulate
```

This single-file generative proxy implements a first executable subset of the
modeling glossary: scale-free Cox-process workload arrivals, aggregate
queue/service dynamics carried continuously across 2011-2024, IT-power shaping, weather-dependent facility overhead,
direct-water shaping and location-emissions shaping. Every ensemble member
closes exactly to reported annual facility electricity. Where annual site water
and location-based Scope 2 are reported, a separate retrospective mode closes
to those observations so that internally consistent hourly scenarios can be
generated.

The script also pre-registers energy-only, evaporation-only and two-component
nonnegative annual water candidates, selects among them with expanding-window
one-step scoring through 2022, and evaluates the frozen choice on 2023-2024.
This diagnostic is intentionally separate from
retrospective closure; poor holdout skill must not be hidden by the simulation.
Hourly arrivals, workload, IT power, PUE, withdrawal and emissions remain
fitted/scenario quantities rather than recovered telemetry.

By default, reported annual location Scope 2 is allocated over hourly facility
energy without inventing a regional carbon shape. `--use-pacw-shape` uses PACW
as an explicit average-regional relative-shape sensitivity: EIA-reported consumed
CO2 intensity when present (from 2018-07), otherwise the named fuel/import proxy
(demand/interchange from 2015-07). It is not a Meta-specific marginal-emissions
estimate, and 2011 through mid-2015 have no PACW EIA-930 coverage. The annual
eGRID × Meta MWh benchmark is a separate location-based physical check.

Main outputs are:
- `outputs/stochastic_proxy_annual_summary.csv`
- `outputs/stochastic_proxy_hourly_2024.csv`
- `outputs/stochastic_proxy_scenarios_2024.csv`
- `outputs/stochastic_proxy_monthly_uncertainty_2024.csv`
- `outputs/stochastic_proxy_summary.json`
- `outputs/stochastic_proxy_*.png`

Use `python run_prineville.py simulate --help` for ensemble size, scenario, seed,
selected-year and train-end-year options.

### Stage 7 — gray-box fit

After weather is present:

```bash
python run_prineville.py calibrate
```

The starter model in `src/prineville_graybox.py` deliberately exposes a **small physics-consistent parameter set** rather than a high-dimensional black box. Its state is:

- latent IT power `P_IT(t)`;
- electrical losses/auxiliaries;
- airflow/fan power;
- direct evaporative/humidification water;
- total facility power;
- PUE/WUE outputs.

The initial 2011 architecture is constrained by Meta's published design facts. Later epochs are allowed only after the event/change-point evidence supports them.

### Stage 8 — chronological validation

Default final holdout: 2023-2024.

```bash
python run_prineville.py validate
```

Validation hierarchy:
1. exact identities and units;
2. calibration closure on train years;
3. annual held-out electricity/water/location-Scope-2 prediction;
4. external city/OWRD water-system consistency (`python run_prineville.py validate` now runs this against the reconstructed monthly campus water series; OWRD is not a calibration target);
5. grid/eGRID carbon consistency;
6. weather-year counterfactuals and sensitivity.

If a quantity was used as a fitting constraint, call the agreement **closure**, not validation.

## What is missing, and how to fill it

| Missing quantity | Best source | Correct treatment if unavailable |
|---|---|---|
| Exact hourly IT load | Meta internal telemetry | Latent utilization process constrained by annual facility energy; report uncertainty; never call recovered hourly load observed |
| Monthly/hourly campus electricity | PacifiCorp/Meta | Public-record/cooperation request if possible; otherwise annual Meta target + physical load-shape priors |
| Monthly campus water | City utility/Meta | Public-record request; otherwise physics-based weather shape closed to annual Meta withdrawal |
| Site water consumption vs withdrawal | City sewer/discharge + Meta | `consumption = withdrawal - discharge` if discharge observed; otherwise use cooling mass balance/CoC range and report interval |
| Building commissioning dates | Crook County/City permits | Permit/final/CO request; use change points only as statistical candidates, not facts |
| Building-specific cooling systems | Mechanical permits/Meta | Use initial design only for initial epoch; later architecture uncertain until evidence supports it |
| Exact physical source of each campus MWh | Utility/dispatch records | PACW regional average/consumption-based proxy; keep separate from REC market accounting |
| Campus backup-generator hourly operation | Air permits/CEMS/local logs if reported | Monthly DEQ hours exist for extracted years; do not treat nameplate MW as IT load or PSEL as actuals; hourly dispatch remains missing |

## Provenance classes

Every final field should be one of:
- `reported`: directly published by Meta/agency;
- `measured`: meter/monitor record supplied by a utility/agency;
- `derived`: exact unit/accounting transformation from reported/measured data;
- `fitted`: estimated model parameter/state;
- `proxy`: external series standing in for unavailable site telemetry;
- `scenario`: counterfactual/assumed input.

## Non-negotiable modeling rules

1. Do not mix water **withdrawal** and **consumption**.
2. Do not mix facility electricity and IT electricity.
3. Do not use fleet PUE/WUE as if they were Prineville site measurements.
4. Do not use REC/market-based Scope 2 as physical grid emissions.
5. Do not randomly split hourly observations across seasons for validation.
6. Preserve all historical source vintages and revisions.
7. Do not infer exact building commissioning dates from an announcement.
8. Every downscaled hourly series must aggregate back to the observed annual total when used in a calibration year, but that annual closure is not a validation result.

See `SOURCE_INSTRUCTIONS.md` for every source and `MANUAL_ACQUISITION.md` for the exact remaining user actions. The most important distinction is that the annual Meta ground truth, source vintages, OHA well crosswalk, ASR engineering evidence, source registry, change-point screening, physics scaffold and acquisition scripts are already prepared; only the access-controlled/interactive series remain for the user to obtain.

### Stage 4 permit chronology status (2026-08-12)

Crook County ePermitting Inspection Summary PDFs have been reviewed for the early campus and the prioritized 2015-2025 permit set. The populated code-compatible view is `data/manual_templates/campus_buildings.csv`; the full permit-level provenance table is `data/canonical/campus_permit_evidence.csv`; and high-confidence dated milestones are in `data/canonical/campus_permit_events.csv`.

Important semantics: the inspection PDFs do not expose a true permit issue date, square footage, or MW/kVA service capacity. `campus_buildings.csv::issue_date` therefore uses the ePermitting search-result `Opened` date as an explicitly documented proxy. `final_or_co_date` uses an approved final inspection where available. Partial/final milestone detail is preserved in the evidence table and quality notes. Do not interpret support-only/expired permits or the 2022 STR-01 closeout as new capacity epochs.

### Stage 4 audit integration

`python run_prineville.py audit` now validates the populated campus permit evidence and chronology in addition to the annual targets and OWRD normalization. It writes `outputs/campus_permit_audit.csv`. Candidate annual breaks are written in two forms: `candidate_annual_breaks_exploratory.csv` (all available years) and `candidate_annual_breaks_train_only.csv` (through 2022, suitable for model selection when 2023-2024 remain held out). `candidate_annual_breaks.csv` is retained as a backward-compatible alias for the exploratory table.
