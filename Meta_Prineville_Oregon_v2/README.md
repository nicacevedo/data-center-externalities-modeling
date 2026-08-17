# Meta Prineville public-data reconstruction seed

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

1. Register for a free EIA API key if using API access.
2. Set it in your shell:

```bash
export EIA_API_KEY='YOUR_KEY'
```

3. Discover route metadata/facets before pulling data:

```bash
python src/download_eia930.py --discover
```

4. Pull PACW hourly regional data:

```bash
python src/download_eia930.py --start 2019-01-01 --end 2024-12-31
```

The script intentionally discovers available facets/columns from EIA metadata rather than freezing undocumented type codes. EIA returns at most 5,000 rows per JSON request, so the script paginates.

Use:
- PACW demand/net generation/interchange as grid context;
- EIA hourly CO2 if present in the returned route/version;
- EPA eGRID annual plant/subregion emission rates as an independent annual cross-check.

Treat `PACW CO2 / PACW load` as an **average regional physical-intensity proxy**, not campus marginal emissions. A later phase can improve this using generator-level CEMS plus interchange/consumption-based accounting.

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

- `outputs/hourly_conditional_reconstruction.csv`
- `outputs/conditional_annual_compare.csv`
- `outputs/conditional_water_model.csv`

This is the correct baseline to improve once monthly City/OWRD data arrive.

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
4. external city/OWRD water-system consistency;
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
| Campus backup-generator hourly operation | Air permits/CEMS/local logs if reported | Model only testing/outage scenarios within permit bounds; do not assume continuous onsite generation |

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
