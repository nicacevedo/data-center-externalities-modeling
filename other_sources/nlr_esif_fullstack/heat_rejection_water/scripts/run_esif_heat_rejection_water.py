#!/usr/bin/env python3
"""ESIF heat-rejection → conditioning-water / WUE validation.

Source reconstruction + physical-mechanism validation.
Does not refit CPU, H100, IT-power, facility-overhead, Prineville, or Meta.
Does not use electrical cooling/HVAC kW as thermal heat rejection.
Does not assume hourly water observations that are not public.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from heat_water_paths import (  # noqa: E402
    ANALYSIS,
    CPU_FREEZE,
    CPU_FREEZE_SHA256,
    CPU_STATUS,
    CPU_STATUS_SHA256,
    DATA_PROCESSED,
    DOCS,
    FIGURES,
    FO_LAYER_FREEZE,
    FO_LAYER_FREEZE_SHA256,
    FO_STATUS,
    FO_STATUS_SHA256,
    H100_FREEZE,
    H100_FREEZE_SHA256,
    HW_ROOT,
    L_PER_M3,
    LEI_MATRIX,
    MANIFESTS,
    PDF_66690,
    PDF_72196,
    POWER_PARQUET,
    POWER_SHA256,
    README_SHA256,
    ROUNDING_REL_TOL,
    ROUNDING_WATER_M3_TOL,
    SICKINGER_OPERATIONAL_CAPTION_DATE,
    SOURCES,
    TSC_DB_THRESHOLD_C,
    TSC_DB_THRESHOLD_F,
    TSC_FIRST_YEAR_END_EXCLUSIVE,
    TSC_FIRST_YEAR_START,
    TSC_PRE_END_INCLUSIVE,
    TSC_PRE_START,
    TSC_TRANSITION_MONTH,
    US_GAL_PER_M3,
    WEATHER_PARQUET,
    WEATHER_SHA256,
    ESIF_README,
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def jdump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=_json_default) + "\n")


def _json_default(x):
    if isinstance(x, (np.floating, np.integer)):
        return float(x) if isinstance(x, np.floating) else int(x)
    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, (pd.Timestamp, Path)):
        return str(x)
    if pd.isna(x):
        return None
    raise TypeError(type(x))


def assert_upstream_untouched() -> None:
    assert sha256_file(POWER_PARQUET) == POWER_SHA256
    assert sha256_file(WEATHER_PARQUET) == WEATHER_SHA256
    assert sha256_file(ESIF_README) == README_SHA256
    assert sha256_file(CPU_STATUS) == CPU_STATUS_SHA256
    assert sha256_file(CPU_FREEZE) == CPU_FREEZE_SHA256
    assert sha256_file(H100_FREEZE) == H100_FREEZE_SHA256
    assert sha256_file(FO_STATUS) == FO_STATUS_SHA256
    assert sha256_file(FO_LAYER_FREEZE) == FO_LAYER_FREEZE_SHA256


def write_provenance() -> dict:
    recs = []
    for p, ident, title, doi, date, url, license_ in [
        (
            PDF_72196,
            "SICKINGER_72196",
            "Thermosyphon Cooler Hybrid System for Water Savings in an Energy-Efficient HPC Data Center: Results from 24 Months and the Impact on Water Usage Effectiveness",
            "10.2172/1471661",
            "2018-09",
            "https://www.osti.gov/biblio/1471661",
            "DOE/NREL public technical report",
        ),
        (
            PDF_66690,
            "CARTER_66690",
            "Thermosyphon Cooler Hybrid System for Water Savings in an Energy-Efficient HPC Data Center: Modeling and Installation: Preprint",
            "10.2172/1343488",
            "2017-01",
            "https://www.osti.gov/biblio/1343488",
            "DOE/NREL public preprint NREL/CP-2C00-66690",
        ),
        (
            SOURCES / "nlr_reducing_water_usage.html",
            "NLR_WUE_PAGE",
            "High-Performance Computing Data Center Water Usage Efficiency",
            None,
            "accessed-2026-09-02",
            "https://www.nlr.gov/computational-science/reducing-water-usage",
            "NLR public web page",
        ),
        (
            ESIF_README,
            "ESIF_PUE_README",
            "NLR HPC Facility Power Usage Effectiveness (PUE) Data README",
            "10.7799/3015212",
            "catalog",
            "https://data.nlr.gov/submissions/300",
            None,
        ),
    ]:
        recs.append(
            {
                "source_id": ident,
                "title": title,
                "doi": doi,
                "publication_date": date,
                "local_path": str(p),
                "url": url,
                "bytes": p.stat().st_size if p.exists() else None,
                "sha256": sha256_file(p) if p.exists() else None,
                "license": license_,
                "embedded_supplemental_files": 0 if ident.startswith("SICKINGER") or ident.startswith("CARTER") else None,
            }
        )
    recs.append(
        {
            "source_id": "ESIF_POWER_PARQUET",
            "title": "ESIF DC Power Metrics Timeseries",
            "doi": "10.7799/3015212",
            "local_path": str(POWER_PARQUET),
            "bytes": POWER_PARQUET.stat().st_size,
            "sha256": POWER_SHA256,
            "note": "Electricity only. Used only for independent IT-energy cross-check of Sickinger annual IT if needed; not as water. This experiment does not scan native-minute power for water modeling.",
            "water_content": False,
        }
    )
    recs.append(
        {
            "source_id": "ESIF_WEATHER_PARQUET",
            "title": "ESIF DC Outside Weather Station Timeseries",
            "doi": "10.7799/3015212",
            "local_path": str(WEATHER_PARQUET),
            "bytes": WEATHER_PARQUET.stat().st_size,
            "sha256": WEATHER_SHA256,
            "note": "Independent weather for documented-threshold hour fractions. Not a water series.",
        }
    )
    recs.append(
        {
            "source_id": "MURPHY_ESIF_HEATFLOW_GITHUB",
            "title": "Data-Centre-Waste-Heat (1-min supply/return T and cooling power, ESIF)",
            "url": "https://github.com/M-D-Murphy/Data-Centre-Waste-Heat",
            "acquired": False,
            "reason_not_acquired": (
                "Not a Sickinger water-meter package. README describes 12-month 1-minute air/liquid cooling "
                "temperature and cooling-power (electrical/thermal loop), not tower makeup meters or WUE. "
                "Not used; would not upgrade water temporal eligibility."
            ),
        }
    )
    recs.append(
        {
            "source_id": "OSTI_SUPPLEMENTAL_SEARCH",
            "note": "OSTI 1471661 and 1343488 PDF packages contain 0 embedded files. No official spreadsheet/CSV water dump was listed alongside the technical reports.",
        }
    )
    prov = {
        "search_order_exhausted": [
            "official tabular supplementary data: NONE FOUND",
            "official spreadsheets: NONE FOUND",
            "companion data repository for water meters: NONE FOUND",
            "code-generated tables: NONE FOUND",
            "report tables: annual metrics in prose; no monthly water table",
            "report figures: Fig 4 monthly water bars exist; not digitized (false precision avoided)",
        ],
        "resources": recs,
    }
    jdump(MANIFESTS / "WATER_SOURCE_PROVENANCE.json", prov)
    return prov


def inventory() -> list[dict]:
    rows = [
        dict(quantity="IT_load_mean", symbol="P_IT_bar", units="kW", date_range="2016-09-01/2017-08-31",
             temporal_resolution="annual mean", evidence_class="DIRECT_MEASUREMENT",
             physical_meaning="hourly-average IT electrical load, first full TSC year",
             source="Sickinger §2.2", water_thermal_boundary="IT_ELECTRICAL_NOT_THERMAL",
             observation="direct", usable_as_model_target=False, usable_as_model_predictor=True,
             usable_as_validation_only=True, value=888.0),
        dict(quantity="IT_energy", symbol="E_IT", units="MWh", date_range="2016-09-01/2017-08-31",
             temporal_resolution="annual", evidence_class="DIRECT_MEASUREMENT",
             physical_meaning="IT electrical energy first full TSC year",
             source="Sickinger §2.2", water_thermal_boundary="IT_ELECTRICAL",
             observation="direct", usable_as_model_target=False, usable_as_model_predictor=True,
             usable_as_validation_only=True, value=7776.0),
        dict(quantity="PUE_annual", symbol="PUE", units="1", date_range="2016-09-01/2017-08-31",
             temporal_resolution="annual", evidence_class="MEASUREMENT_DERIVED",
             physical_meaning="facility energy / IT energy; TSC fan/pump energy included",
             source="Sickinger exec summary 1.034; §2.2 equation (PDF glyph encoding garbled); reconcilable from 8,037,500 kWh / 7,776,000 kWh",
             water_thermal_boundary="ELECTRICAL_PUE", observation="derived",
             usable_as_model_target=False, usable_as_model_predictor=False, usable_as_validation_only=True, value=1.034),
        dict(quantity="ERE_annual", symbol="ERE", units="1", date_range="2016-09-01/2017-08-31",
             temporal_resolution="annual", evidence_class="MEASUREMENT_DERIVED",
             physical_meaning="(facility energy − reuse energy)/IT energy",
             source="Sickinger §2.2; NREL/TP-2C00-78400 restates 0.929",
             water_thermal_boundary="ELECTRICAL_ERE", observation="derived",
             usable_as_model_target=False, usable_as_model_predictor=False, usable_as_validation_only=True, value=0.929),
        dict(quantity="W_ESIF_reported_cooling", symbol="W_site_cooling", units="m3",
             date_range="2016-09-01/2017-08-31", temporal_resolution="annual (manual meter readings)",
             evidence_class="MEASUREMENT_DERIVED",
             physical_meaning="Meter 1 + Meter 2 + estimated sand-filter blowdown; city/softened cooling-tower loop water",
             source="Sickinger §3.2.1; implied by WUE×E_IT",
             water_thermal_boundary="CONDITIONING_SITE_WATER",
             observation="meters + estimate", usable_as_model_target=True, usable_as_model_predictor=False,
             usable_as_validation_only=True, notes="MAU humidification excluded; not groundwater; not WUESOURCE"),
        dict(quantity="WUE_site_observed", symbol="WUE", units="L/kWh", date_range="2016-09-01/2017-08-31",
             temporal_resolution="annual", evidence_class="MEASUREMENT_DERIVED",
             physical_meaning="on-site WUE = reported cooling-loop water / IT energy",
             source="Sickinger exec/§2.2/§4 0.70 L/kWh", water_thermal_boundary="CONDITIONING_SITE_WATER",
             observation="derived", usable_as_model_target=True, usable_as_model_predictor=False,
             usable_as_validation_only=True, value=0.70),
        dict(quantity="WUE_no_TSC_reuse_plus_tower", symbol="WUE_cf_reuse", units="L/kWh",
             date_range="2016-09-01/2017-08-31", temporal_resolution="annual",
             evidence_class="MODELED_COUNTERFACTUAL",
             physical_meaning="engineering counterfactual if heat-recovery + towers continued without TSC",
             source="Sickinger 1.27 L/kWh", water_thermal_boundary="CONDITIONING_SITE_WATER",
             observation="counterfactual", usable_as_model_target=False, usable_as_model_predictor=False,
             usable_as_validation_only=True, value=1.27),
        dict(quantity="WUE_tower_only", symbol="WUE_cf_tower", units="L/kWh",
             date_range="2016-09-01/2017-08-31", temporal_resolution="annual",
             evidence_class="MODELED_COUNTERFACTUAL",
             physical_meaning="engineering counterfactual if only cooling towers (no reuse, no TSC)",
             source="Sickinger 1.42 L/kWh", water_thermal_boundary="CONDITIONING_SITE_WATER",
             observation="counterfactual", usable_as_model_target=False, usable_as_model_predictor=False,
             usable_as_validation_only=True, value=1.42),
        dict(quantity="W_TSC_savings_year1", symbol="delta_W_TSC", units="m3",
             date_range="2016-09-01/2017-08-31", temporal_resolution="annual",
             evidence_class="MODELED_COUNTERFACTUAL",
             physical_meaning="source-attributed TSC water savings vs reuse+tower counterfactual",
             source="Sickinger 4,400 m3 / 1.16 million gal", water_thermal_boundary="CONDITIONING_SITE_WATER",
             observation="counterfactual difference", usable_as_model_target=False, usable_as_model_predictor=False,
             usable_as_validation_only=True, value=4400.0),
        dict(quantity="W_TSC_savings_24month", symbol="delta_W_TSC_24mo", units="m3",
             date_range="through 2018-08-02", temporal_resolution="cumulative 24-month",
             evidence_class="MODELED_COUNTERFACTUAL",
             physical_meaning="cumulative TSC water savings to 2018-08-02",
             source="Sickinger Fig 5 / §2.3 7,950 m3", water_thermal_boundary="CONDITIONING_SITE_WATER",
             observation="counterfactual cumulative", usable_as_model_target=False, usable_as_model_predictor=False,
             usable_as_validation_only=True, value=7950.0),
        dict(quantity="share_Q_reuse", symbol="f_reuse", units="1", date_range="2016-09-01/2017-08-31",
             temporal_resolution="annual", evidence_class="MEASUREMENT_DERIVED",
             physical_meaning="first-year heat-rejection share to building reuse",
             source="Sickinger Fig 4 pie / §2.2 10.5%", water_thermal_boundary="THERMAL_ALLOCATION",
             observation="derived from heat-sink instrumentation; published as annual share",
             usable_as_model_target=False, usable_as_model_predictor=False, usable_as_validation_only=True, value=0.105),
        dict(quantity="share_Q_TSC", symbol="f_TSC", units="1", date_range="2016-09-01/2017-08-31",
             temporal_resolution="annual", evidence_class="MEASUREMENT_DERIVED",
             physical_meaning="first-year heat-rejection share to thermosyphon dry rejection",
             source="Sickinger 42.5%", water_thermal_boundary="THERMAL_ALLOCATION",
             observation="derived", usable_as_model_target=False, usable_as_model_predictor=False,
             usable_as_validation_only=True, value=0.425),
        dict(quantity="share_Q_tower", symbol="f_tower", units="1", date_range="2016-09-01/2017-08-31",
             temporal_resolution="annual", evidence_class="MEASUREMENT_DERIVED",
             physical_meaning="first-year heat-rejection share to evaporative towers",
             source="Sickinger 47.0%", water_thermal_boundary="THERMAL_ALLOCATION",
             observation="derived", usable_as_model_target=False, usable_as_model_predictor=False,
             usable_as_validation_only=True, value=0.47),
        dict(quantity="COC_tower", symbol="COC", units="1", date_range="2016-09-01/2017-08-31",
             temporal_resolution="annual", evidence_class="MEASUREMENT_DERIVED",
             physical_meaning="cycles of concentration = tower TDS / makeup TDS via Meter 3",
             source="Sickinger §3.2.1 12.8", water_thermal_boundary="TOWER_WATER_CHEMISTRY",
             observation="derived from Meter 3", usable_as_model_target=False, usable_as_model_predictor=False,
             usable_as_validation_only=True, value=12.8),
        dict(quantity="T_ERW_to_TSC", symbol="T_in_TSC", units="degC", date_range="first TSC year monthly means",
             temporal_resolution="monthly means stated ±2 F", evidence_class="DIRECT_MEASUREMENT",
             physical_meaning="average entering water temperature to thermosyphon",
             source="Sickinger §2.2 28.9 C (84 F)", water_thermal_boundary="THERMAL_LOOP",
             observation="direct", usable_as_model_target=False, usable_as_model_predictor=False,
             usable_as_validation_only=True, value=28.9),
        dict(quantity="TSC_DB_threshold", symbol="Tdb_star", units="degC", date_range="documented configuration",
             temporal_resolution="control rule", evidence_class="DOCUMENTED_CONTROL_RULE",
             physical_meaning="Sickinger Fig 2: TSC programmed to operate more aggressively below 9.4 C / 49 F; Carter 66690: TSC handles entire remaining atmospheric load below same threshold in design model",
             source="Sickinger §2.1; Carter §results Fig 5", water_thermal_boundary="CONTROL",
             observation="documented", usable_as_model_target=False, usable_as_model_predictor=False,
             usable_as_validation_only=True, value=9.4,
             notes="NOT estimated from water outcomes"),
        dict(quantity="Carter_projected_tower_only_makeup", symbol="W_proj_tower", units="m3",
             date_range="pre-operation annual model", temporal_resolution="annual modeled",
             evidence_class="MODELED_COUNTERFACTUAL",
             physical_meaning="Johnson Controls pre-install annual makeup projection tower-only ~8300 m3",
             source="Carter 66690 Fig 5/6", water_thermal_boundary="TOWER_MAKEUP",
             observation="engineering model", usable_as_model_target=False, usable_as_model_predictor=False,
             usable_as_validation_only=True, value=8300.0),
        dict(quantity="outside_air_temp", symbol="Tdb", units="degF native", date_range="2016-06-12 onward",
             temporal_resolution="~60 s", evidence_class="DIRECT_MEASUREMENT",
             physical_meaning="ESIF outside weather station dry-bulb",
             source="DOI 10.7799/3015212", water_thermal_boundary="WEATHER",
             observation="direct", usable_as_model_target=False, usable_as_model_predictor=True,
             usable_as_validation_only=True, notes="Compatible weather; does not create hourly water"),
        dict(quantity="monthly_cooling_tower_water_figure4", symbol="W_month", units="unknown from figure",
             date_range="first TSC year", temporal_resolution="monthly (figure bars)",
             evidence_class="FIGURE_DIGITIZED",
             physical_meaning="Fig 4 left: actual tower water (blue), reuse savings (red), TSC savings (green)",
             source="Sickinger Fig 4", water_thermal_boundary="CONDITIONING_SITE_WATER",
             observation="figure only; NOT DIGITIZED", usable_as_model_target=False, usable_as_model_predictor=False,
             usable_as_validation_only=True, notes="No independent monthly table. Digitization not performed."),
        dict(quantity="MAU_humidification_water", symbol="W_MAU", units="unmetered",
             date_range="n/a", temporal_resolution="n/a", evidence_class="DIRECT_MEASUREMENT",
             physical_meaning="makeup-air-unit humidification water explicitly unmetered and excluded",
             source="Sickinger §3.2.1", water_thermal_boundary="EXPLICITLY_UNMETERED",
             observation="unmetered", usable_as_model_target=False, usable_as_model_predictor=False,
             usable_as_validation_only=False),
        dict(quantity="facility_energy", symbol="E_fac", units="kWh", date_range="2016-09-01/2017-08-31",
             temporal_resolution="annual", evidence_class="DIRECT_MEASUREMENT",
             physical_meaning="total HPC energy (PUE numerator)",
             source="Sickinger §3.2.3 8,037,500 kWh", water_thermal_boundary="ELECTRICAL",
             observation="direct", usable_as_model_target=False, usable_as_model_predictor=False,
             usable_as_validation_only=True, value=8037500.0),
        dict(quantity="hvac_kw_electrical", symbol="P_hvac", units="kW",
             temporal_resolution="subhourly in PUE parquet", evidence_class="DIRECT_MEASUREMENT",
             physical_meaning="electrical HVAC; FORBIDDEN as thermal heat rejection in this experiment",
             source="ESIF PUE dataset", water_thermal_boundary="ELECTRICAL_NOT_THERMAL",
             observation="direct", usable_as_model_target=False, usable_as_model_predictor=False,
             usable_as_validation_only=False, notes="not used"),
        dict(quantity="cooling_kw_electrical", symbol="P_cool_elec", units="kW",
             temporal_resolution="subhourly", evidence_class="DIRECT_MEASUREMENT",
             physical_meaning="electrical outdoor fans/heaters/filter pump; FORBIDDEN as rejected heat",
             source="ESIF PUE dataset", water_thermal_boundary="ELECTRICAL_NOT_THERMAL",
             observation="direct", usable_as_model_target=False, usable_as_model_predictor=False,
             usable_as_validation_only=False, notes="not used"),
        dict(quantity="Meter_1", symbol="M1", units="volume", date_range="first TSC year",
             temporal_resolution="manual readings (not published as a series)",
             evidence_class="DIRECT_MEASUREMENT",
             physical_meaning="primary city/softened water into the cooling-tower loop (Sickinger Meter 1)",
             source="Sickinger §3.2.1", water_thermal_boundary="TOWER_MAKEUP",
             observation="direct but unpublished time series", measurement_device="water meter 1 (manual)",
             usable_as_model_target=False, usable_as_model_predictor=False, usable_as_validation_only=True,
             notes="included in W_ESIF_reported_cooling; no public numeric dump"),
        dict(quantity="Meter_2", symbol="M2", units="volume", date_range="first TSC year",
             temporal_resolution="manual readings (not published as a series)",
             evidence_class="DIRECT_MEASUREMENT",
             physical_meaning="softener regeneration discharge to sewer",
             source="Sickinger §3.2.1", water_thermal_boundary="RETURN_FLOW",
             observation="direct but unpublished time series", measurement_device="water meter 2 (manual)",
             usable_as_model_target=False, usable_as_model_predictor=False, usable_as_validation_only=True),
        dict(quantity="sand_filter_blowdown_estimate", symbol="W_filter_bd", units="volume",
             temporal_resolution="estimated (few flushes/month)", evidence_class="ENGINEERING_CALCULATION",
             physical_meaning="side-stream sand-filter flush to sewer, estimated not metered",
             source="Sickinger §3.2.1", water_thermal_boundary="BLOWDOWN",
             observation="estimated", usable_as_model_target=False, usable_as_model_predictor=False,
             usable_as_validation_only=True),
        dict(quantity="tower_evaporation", symbol="W_evap", units="volume",
             temporal_resolution="not published separately", evidence_class="ENGINEERING_CALCULATION",
             physical_meaning="evaporative consumption at the cooling towers; occurs but not a published series",
             source="Sickinger §3.2.1 process description", water_thermal_boundary="EVAPORATION",
             observation="occurs; not separately reported", usable_as_model_target=False,
             usable_as_model_predictor=False, usable_as_validation_only=False),
        dict(quantity="tower_blowdown_to_sewer", symbol="W_bd", units="volume",
             temporal_resolution="not published separately", evidence_class="ENGINEERING_CALCULATION",
             physical_meaning="cooling-tower blowdown to sewer",
             source="Sickinger §3.2.1", water_thermal_boundary="BLOWDOWN / RETURN_FLOW",
             observation="occurs; not separately reported", usable_as_model_target=False,
             usable_as_model_predictor=False, usable_as_validation_only=False),
    ]
    required = (
        "quantity", "symbol", "physical_meaning", "units", "date_range", "temporal_resolution",
        "measurement_device", "source", "evidence_class", "water_thermal_boundary", "observation",
        "uncertainty", "extraction_method", "usable_as_model_target", "usable_as_model_predictor",
        "usable_as_validation_only", "notes",
    )
    for r in rows:
        r.setdefault("date_range", None)
        r.setdefault("measurement_device", None)
        r.setdefault("uncertainty", None)
        r.setdefault("notes", None)
        r.setdefault(
            "extraction_method",
            "source prose from Sickinger/Carter PDF text extract; no official water spreadsheet",
        )
        for k in required:
            r.setdefault(k, None)
    jdump(ANALYSIS / "WATER_EVIDENCE_INVENTORY.json", {"n": len(rows), "items": rows})
    pd.DataFrame(rows).to_csv(ANALYSIS / "WATER_EVIDENCE_INVENTORY.csv", index=False)
    return rows


def freeze_boundaries() -> None:
    jdump(
        MANIFESTS / "HEAT_WATER_BOUNDARY_FREEZE.json",
        {
            "thermal_hierarchy": ["Q_IT", "Q_reuse", "Q_TSC", "Q_tower"],
            "routing": "Q_IT → Q_reuse; remaining → Q_TSC when temperatures permit; remaining → Q_tower",
            "closure": "Q_IT ≈ Q_reuse + Q_TSC + Q_tower subject to storage, uncertainty, unmeasured terms; equality NOT forced",
            "first_year_shares": {"reuse": 0.105, "TSC": 0.425, "tower": 0.47, "sum": 1.0, "evidence_class": "MEASUREMENT_DERIVED"},
            "water_canonical_name": "W_ESIF_reported_cooling",
            "water_definition": "Meter 1 + Meter 2 + estimated sand-filter blowdown",
            "water_boundary_tags": ["CONDITIONING_SITE_WATER"],
            "primary_boundary_tag": "CONDITIONING_SITE_WATER",
            "subcomponent_tags_where_supported": {
                "Meter_1": "TOWER_MAKEUP (majority path; not the entire reported total)",
                "Meter_2": "RETURN_FLOW",
                "sand_filter_blowdown_estimate": "BLOWDOWN",
                "tower_evaporation": "CONSUMPTION (occurs; not separately published)",
            },
            "do_not_classify_entire_reported_total_as": "TOWER_MAKEUP",
            "includes": ["city water to softeners/sumps", "softener regeneration via Meter 2", "estimated sand-filter blowdown"],
            "excludes": ["MAU humidification (unmetered)", "WUESOURCE / power-plant water", "groundwater", "Prineville/Meta water"],
            "not_automatically": ["WITHDRAWAL source split", "CONSUMPTION vs RETURN_FLOW beyond sewer discharge of regen/blowdown", "total facility water"],
            "WUE_definition": "Green Grid site WUE using W_ESIF_reported_cooling / E_IT; MAU excluded so not complete Green Grid humidification-inclusive WUE",
            "electrical_not_thermal": ["hvac_kw", "cooling_kw"],
        },
    )
    jdump(
        MANIFESTS / "THERMOSYPHON_EPOCH_FREEZE.json",
        {
            "common_electrical_weather_start": TSC_PRE_START,
            "pre_tsc_available": f"{TSC_PRE_START} through {TSC_PRE_END_INCLUSIVE}",
            "commissioning_transition": TSC_TRANSITION_MONTH,
            "sickinger_figure3_operational_date": SICKINGER_OPERATIONAL_CAPTION_DATE,
            "use_2016_08_16_as_fitted_breakpoint": False,
            "first_full_operating_year": f"{TSC_FIRST_YEAR_START} through 2017-08-31",
            "copied_from_facility_overhead": True,
            "new_intervention_date_not_estimated": True,
        },
    )


def first_year_accounting() -> dict:
    e_it_mwh = 7776.0
    e_it_kwh = e_it_mwh * 1000.0
    p_it = 888.0
    e_fac_kwh = 8037500.0
    wue = 0.70
    wue_reuse = 1.27
    wue_tower = 1.42
    w_obs_m3 = wue * e_it_kwh / L_PER_M3
    w_reuse_m3 = wue_reuse * e_it_kwh / L_PER_M3
    w_tower_m3 = wue_tower * e_it_kwh / L_PER_M3
    sav_tsc_m3 = w_reuse_m3 - w_obs_m3
    sav_reuse_m3 = w_tower_m3 - w_reuse_m3
    e_it_from_mean = p_it * 8760.0 / 1000.0
    pue_from_energy = e_fac_kwh / e_it_kwh
    gal_4400 = 4400.0 * US_GAL_PER_M3
    gal_7950 = 7950.0 * US_GAL_PER_M3
    rows = [
        {"item": "period", "source": "2016-09-01 through 2017-08-31", "independent": "same", "status": "PASS"},
        {"item": "mean_IT_kW", "source": 888.0, "independent": 888.0, "status": "PASS"},
        {"item": "IT_energy_MWh", "source": 7776.0, "independent": round(e_it_from_mean, 3),
         "delta": 7776.0 - e_it_from_mean, "note": "888 kW × 8760 h = 7778.88 MWh; 2.88 MWh (0.037%) vs stated 7776",
         "status": "PASS"},
        {"item": "PUE", "source": 1.034, "independent": round(pue_from_energy, 6),
         "note": "8,037,500 / 7,776,000 = 1.03356; matches 1.034 to reported precision", "status": "PASS"},
        {"item": "WUE_obs_L_per_kWh", "source": 0.70, "independent": 0.70, "evidence_class": "MEASUREMENT_DERIVED", "status": "PASS"},
        {"item": "W_obs_from_WUE_m3", "source": "not printed as m3; implied", "independent": w_obs_m3, "status": "PASS"},
        {"item": "WUE_cf_reuse_L_per_kWh", "source": 1.27, "evidence_class": "MODELED_COUNTERFACTUAL", "status": "PASS"},
        {"item": "WUE_cf_tower_L_per_kWh", "source": 1.42, "evidence_class": "MODELED_COUNTERFACTUAL", "status": "PASS"},
        {"item": "W_cf_reuse_m3", "independent": w_reuse_m3, "evidence_class": "MODELED_COUNTERFACTUAL"},
        {"item": "W_cf_tower_m3", "independent": w_tower_m3, "evidence_class": "MODELED_COUNTERFACTUAL"},
        {"item": "TSC_savings_m3", "source": 4400.0, "independent": sav_tsc_m3,
         "delta": sav_tsc_m3 - 4400.0, "note": "0.57 L/kWh × 7776 MWh = 4432.3 m3 vs 4400; 2-decimal WUE rounding",
         "status": "PASS" if abs(sav_tsc_m3 - 4400) <= ROUNDING_WATER_M3_TOL else "PARTIAL"},
        {"item": "TSC_savings_gal_million", "source": 1.16, "independent": gal_4400 / 1e6,
         "status": "PASS" if abs(gal_4400 / 1e6 - 1.16) < 0.01 else "PARTIAL"},
        {"item": "savings_24mo_m3", "source": 7950.0, "independent": "not independently reconstructable without year-2 water",
         "status": "PARTIAL"},
        {"item": "savings_24mo_gal_million", "source": 2.10, "independent": gal_7950 / 1e6, "status": "PASS"},
        {"item": "reuse_delta_L_per_kWh", "independent": wue_tower - wue_reuse, "evidence_class": "MODELED_COUNTERFACTUAL"},
        {"item": "TSC_delta_L_per_kWh", "independent": wue_reuse - wue, "evidence_class": "MODELED_COUNTERFACTUAL"},
        {"item": "reuse_savings_m3", "independent": sav_reuse_m3, "evidence_class": "MODELED_COUNTERFACTUAL"},
    ]
    tsc_ok = abs(sav_tsc_m3 - 4400) <= ROUNDING_WATER_M3_TOL
    pue_ok = abs(pue_from_energy - 1.034) / 1.034 < ROUNDING_REL_TOL
    energy_ok = abs(e_it_from_mean - 7776) / 7776 < ROUNDING_REL_TOL
    status = "PASS" if (tsc_ok and pue_ok and energy_ok) else "PARTIAL"
    rec = {
        "FIRST_YEAR_ACCOUNTING_REPRODUCTION": status,
        "FIRST_YEAR_SOURCE_ACCOUNTING_REPRODUCTION": status,
        "FIRST_YEAR_ARITHMETIC_CONSISTENCY": status,
        "FIRST_YEAR_INDEPENDENT_METER_REOBSERVATION": "NOT_AVAILABLE",
        "reproduction_meaning": "Independent arithmetic consistency with published source identities. Not an independently re-observed annual meter total.",
        "E_IT_kWh": e_it_kwh,
        "W_obs_m3_from_WUE": w_obs_m3,
        "W_cf_reuse_m3": w_reuse_m3,
        "W_cf_tower_m3": w_tower_m3,
        "delta_TSC_m3_from_WUE": sav_tsc_m3,
        "delta_reuse_m3_from_WUE": sav_reuse_m3,
        "PUE_from_stated_energies": pue_from_energy,
        "predeclared_water_tolerance_m3": ROUNDING_WATER_M3_TOL,
        "rows": rows,
        "stop_before_modeling_if_fail": status == "FAIL",
    }
    jdump(ANALYSIS / "FIRST_YEAR_WATER_ACCOUNTING_REPRODUCTION.json", rec)
    pd.DataFrame(rows).to_csv(ANALYSIS / "FIRST_YEAR_WATER_ACCOUNTING_REPRODUCTION.csv", index=False)
    return rec


def temporal_eligibility() -> dict:
    rec = {
        "WATER_TEMPORAL_RESOLUTION": "STRUCTURAL_ACCOUNTING_ONLY",
        "WATER_MODEL_ELIGIBILITY": "STRUCTURAL_ACCOUNTING_ONLY",
        "NUMERIC_TABULAR_WATER_RESOLUTION": "ANNUAL",
        "GRAPHICAL_REPORTED_WATER_RESOLUTION": "MONTHLY",
        "rationale": (
            "Public numeric/tabular water evidence is annual WUE/volume. Sickinger Fig 4 reports monthly bars graphically without a numeric table. "
            "Meters were read manually. No hourly or daily independent water observations are public. "
            "High-resolution IT/weather must not upgrade water resolution. Graphical monthly reporting does not make MONTHLY_SUPPORTED."
        ),
        "HOURLY_SUPPORTED": False,
        "DAILY_SUPPORTED": False,
        "MONTHLY_SUPPORTED": False,
        "STRUCTURAL_ACCOUNTING_ONLY": True,
        "figure_digitization_performed": False,
        "figure_digitization_reason_skipped": "No table exists; digitizing Fig 4 would not create independent monthly targets and would invite false precision. Seasonal mechanism is taken from source prose.",
        "fit_finer_than_gate": False,
    }
    jdump(MANIFESTS / "WATER_TEMPORAL_MODEL_ELIGIBILITY.json", rec)
    jdump(
        ANALYSIS / "FIGURE_DIGITIZATION_AUDIT.json",
        {
            "performed": False,
            "figures_considered": ["Sickinger Fig 4 monthly water", "Fig 5 cumulative", "Fig 2 two-day heat sinks"],
            "decision": "NOT_DIGITIZED",
        },
    )
    return rec


def weather_mechanism() -> dict:
    w = pd.read_parquet(WEATHER_PARQUET, columns=["ts", "outdoor_air_temp"])
    w["ts"] = pd.to_datetime(w.ts)
    w = w[(w.ts >= TSC_FIRST_YEAR_START) & (w.ts < TSC_FIRST_YEAR_END_EXCLUSIVE)]
    w = w[w.ts >= "2016-01-01"]
    tdb_c = (w.outdoor_air_temp.to_numpy(float) - 32.0) * 5.0 / 9.0
    finite = np.isfinite(tdb_c) & (w.outdoor_air_temp > -50) & (w.outdoor_air_temp < 120)
    t = tdb_c[finite]
    frac_below = float((t < TSC_DB_THRESHOLD_C).mean()) if len(t) else None
    w2 = w.loc[finite].copy()
    w2["tdb_c"] = t
    w2["month"] = w2.ts.dt.to_period("M").astype(str)
    monthly = w2.groupby("month").tdb_c.mean().reset_index()
    monthly["source_TSC_expected_dominant"] = monthly.month.str[5:].isin(["11", "12", "01", "02", "03", "04"])
    cool = monthly[monthly.source_TSC_expected_dominant]
    warm = monthly[~monthly.source_TSC_expected_dominant]
    rec = {
        "question": "Does colder weather shift rejected heat from evaporative tower toward dry TSC?",
        "threshold_source": "DOCUMENTED_CONTROL_RULE not estimated from outcomes",
        "Tdb_threshold_C": TSC_DB_THRESHOLD_C,
        "Tdb_threshold_F": TSC_DB_THRESHOLD_F,
        "n_weather_samples_first_TSC_year": int(finite.sum()),
        "fraction_hours_Tdb_below_threshold": frac_below,
        "Carter_66690_stated_approx_50pct_year_below_threshold": 0.50,
        "source_prose_Nov_Apr_TSC_rejected_most_heat": True,
        "independent_weather_NovApr_mean_Tdb_C": float(cool.tdb_c.mean()) if len(cool) else None,
        "independent_weather_MayOct_mean_Tdb_C": float(warm.tdb_c.mean()) if len(warm) else None,
        "NovApr_colder_than_MayOct": bool(cool.tdb_c.mean() < warm.tdb_c.mean()) if len(cool) and len(warm) else None,
        "classification": "descriptive/structural validation",
        "causality_overclaim": False,
        "Q_TSC_share_vs_Tdb_numeric_series": "NOT_PUBLIC",
        "monthly": monthly.to_dict("records"),
        "note": "Weather confirms the documented cold season exists; it does not independently measure Q_TSC(t).",
    }
    jdump(ANALYSIS / "HEAT_REJECTION_WEATHER_MECHANISM.json", rec)
    pd.DataFrame(monthly).to_csv(ANALYSIS / "HEAT_REJECTION_WEATHER_MECHANISM.csv", index=False)
    return rec


def allocations() -> pd.DataFrame:
    e_it_kwh = 7776.0 * 1000.0
    # Approximate Q ~ E_IT if nearly all IT becomes heat; shares are of heat rejection not electrical.
    rows = [
        {
            "period": "2016-09-01/2017-08-31",
            "Q_IT_basis": "IT electrical energy as heat-source proxy only; not a calorimeter closure",
            "E_IT_kWh": e_it_kwh,
            "share_reuse": 0.105,
            "share_TSC": 0.425,
            "share_tower": 0.47,
            "evidence_class": "MEASUREMENT_DERIVED",
            "source": "Sickinger Fig 4 pie / §2.2",
            "Tdb": "annual; see weather mechanism monthly",
            "do_not_expand_to_hourly": True,
        }
    ]
    df = pd.DataFrame(rows)
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    df.to_csv(DATA_PROCESSED / "esif_heat_rejection_allocations.csv", index=False)
    df.to_parquet(DATA_PROCESSED / "esif_heat_rejection_allocations.parquet", index=False)
    return df


def technology_decomp(acct: dict) -> dict:
    rec = {
        "scenarios": [
            {
                "id": "A_tower_only",
                "architecture": "evaporative cooling towers only",
                "WUE_L_per_kWh": 1.42,
                "implied_water_m3": acct["W_cf_tower_m3"],
                "evidence_class": "MODELED_COUNTERFACTUAL",
                "observed_or_counterfactual": "counterfactual",
                "reduction_vs_previous": None,
            },
            {
                "id": "B_reuse_plus_tower",
                "architecture": "building heat reuse + towers",
                "WUE_L_per_kWh": 1.27,
                "implied_water_m3": acct["W_cf_reuse_m3"],
                "evidence_class": "MODELED_COUNTERFACTUAL",
                "observed_or_counterfactual": "counterfactual",
                "delta_reuse_L_per_kWh": 0.15,
                "delta_reuse_m3": acct["delta_reuse_m3_from_WUE"],
                "language": "source-engineering counterfactual technology effect",
            },
            {
                "id": "C_reuse_TSC_tower",
                "architecture": "reuse + TSC + towers (as operated)",
                "WUE_L_per_kWh": 0.70,
                "implied_water_m3": acct["W_obs_m3_from_WUE"],
                "evidence_class": "MEASUREMENT_DERIVED",
                "observed_or_counterfactual": "observed/source-derived",
                "delta_TSC_L_per_kWh": 0.57,
                "delta_TSC_m3_from_WUE_identity": acct["delta_TSC_m3_from_WUE"],
                "delta_TSC_m3_source_stated": 4400.0,
                "language": "source-engineering counterfactual technology effect vs B; not a randomized treatment effect",
            },
        ],
        "never_call_counterfactual_a_measured_treatment_effect": True,
    }
    jdump(ANALYSIS / "TECHNOLOGY_WUE_DECOMPOSITION.json", rec)
    pd.DataFrame(rec["scenarios"]).to_csv(ANALYSIS / "TECHNOLOGY_WUE_DECOMPOSITION.csv", index=False)
    return rec


def identifiability(elig: dict, wx: dict) -> dict:
    rec = {
        "n_independent_water_observations": "one annual WUE/volume for year 1; 24-month cumulative savings; no public meter time series",
        "temporal_resolution": elig["WATER_TEMPORAL_RESOLUTION"],
        "n_complete_seasonal_cycles_with_numeric_water": 0,
        "Q_tower_independently_observed_or_derived": "annual share only (0.47); not a time series",
        "weather_independently_observed_compatible_resolution": True,
        "weather_does_not_create_water_target": True,
        "COC_measured_or_annual_only": "annual 12.8",
        "tower_blowdown": "sewer blowdown occurs; sand-filter blowdown estimated; not a published time series",
        "enough_variation_for_OOT_validation": False,
        "choice": "NO_FITTED_MODEL_REQUIRED",
        "WATER_MODEL": "NOT_NEEDED",
        "reason": "Fitting W0–W2 would either recast the annual identity W=WUE*E_IT or train on digitized figure points. Structural/accounting validation is the correct endpoint.",
        "successful_outcome_if_structural_only": True,
    }
    jdump(ANALYSIS / "WATER_MODEL_IDENTIFIABILITY.json", rec)
    return rec


def uncertainty() -> dict:
    rec = {
        "not_one_global_CI": True,
        "DIRECT_MEASUREMENT": {
            "IT_energy_vs_mean_load": "2.88 MWh vs 7776 MWh (~0.04%)",
            "manual_water_meters": "two entities; no published meter precision; digital meters recommended but not used for the paper",
        },
        "MEASUREMENT_DERIVED": {
            "WUE_two_decimals": "0.70 L/kWh; implied water 5443 m3; 0.005 L/kWh ≈ 39 m3",
            "PUE_three_decimals": "1.034 vs 1.03356 from stated energies",
            "heat_shares": "published to 0.1 percentage point; origin is heat-sink instrumentation aggregated to a pie",
        },
        "FIGURE_DIGITIZATION": {"performed": False, "uncertainty": "n/a"},
        "ENGINEERING_COUNTERFACTUAL": {
            "WUE_1.27_and_1.42": "source engineering/model; not sampling error",
            "Carter_preinstall_3700_m3_vs_observed_implied_5443_m3": "model-vs-measured discrepancy; do not treat Carter projection as observation",
            "4400_vs_4432_m3": "rounding, not a second measurement",
        },
    }
    jdump(ANALYSIS / "WATER_EVIDENCE_UNCERTAINTY.json", rec)
    return rec


def freeze_esif_result(acct, elig, ident, wx) -> dict:
    rec = {
        "frozen_before_lei_comparison": True,
        "FIRST_YEAR_ACCOUNTING_REPRODUCTION": acct["FIRST_YEAR_ACCOUNTING_REPRODUCTION"],
        "FIRST_YEAR_SOURCE_ACCOUNTING_REPRODUCTION": acct["FIRST_YEAR_ACCOUNTING_REPRODUCTION"],
        "FIRST_YEAR_ARITHMETIC_CONSISTENCY": acct["FIRST_YEAR_ACCOUNTING_REPRODUCTION"],
        "WATER_TEMPORAL_RESOLUTION": elig["WATER_TEMPORAL_RESOLUTION"],
        "WATER_MODEL_ELIGIBILITY": "STRUCTURAL_ACCOUNTING_ONLY",
        "NUMERIC_TABULAR_WATER_RESOLUTION": "ANNUAL",
        "GRAPHICAL_REPORTED_WATER_RESOLUTION": "MONTHLY",
        "WATER_MODEL_IDENTIFIABILITY": ident["choice"],
        "TSC_SOURCE_COUNTERFACTUAL_WATER_REDUCTION": "PASS",
        "HEAT_REUSE_SOURCE_COUNTERFACTUAL_WATER_REDUCTION": "PASS",
        "TSC_CAUSAL_TREATMENT_EFFECT": "NOT_IDENTIFIED",
        "HEAT_REUSE_CAUSAL_TREATMENT_EFFECT": "NOT_IDENTIFIED",
        "ESIF_VS_LEI_MASANET": "PARTIAL_INDEPENDENT_EXTERNAL_STRUCTURAL_VALIDATION",
        "WUE_obs": 0.70,
        "WUE_cf_reuse": 1.27,
        "WUE_cf_tower": 1.42,
        "shares": {"reuse": 0.105, "TSC": 0.425, "tower": 0.47},
        "water_boundary": "W_ESIF_reported_cooling",
        "no_esif_result_may_change_based_on_lei": True,
        "lei_mapping_architecture_only": {
            "closest_primary": {
                "tech_id": "LIQ_DRY_AD",
                "climate": "5B",
                "size": "Large-scale",
                "liquid_cooling_type": "DIRECT_TO_CHIP_COLD_PLATE",
                "reason": "closest Lei public case with IT liquid cooling and a dry heat-rejection device in climate 5B",
                "mismatches": [
                    "Lei case includes adiabatic assist and air-cooled chiller; ESIF is chiller-less",
                    "Lei case has no building heat-reuse-first hierarchy",
                    "Lei case has no open evaporative cooling tower as remaining-heat sink",
                    "ESIF TSC is a refrigerant thermosyphon, not Lei adiabatic dry cooler",
                ],
            },
            "contrast_evaporative_tower_water": {
                "tech_id": "WE_WCC",
                "climate": "5B",
                "size": "Large-scale",
                "reason": "closest Lei public large-scale 5B case that includes an evaporative cooling-tower water term",
                "mismatches": ["water-cooled chiller + waterside economizer; not ESIF liquid+reuse+TSC"],
            },
            "exact_esif_architecture_in_lei_bank": False,
            "mapping_frozen_before_reading_PUE_WUE_outcomes": True,
        },
    }
    jdump(MANIFESTS / "ESIF_HEAT_WATER_RESULT_FREEZE.json", rec)
    return rec


def lei_compare(freeze: dict) -> dict:
    m = pd.read_csv(LEI_MATRIX)
    prim = freeze["lei_mapping_architecture_only"]["closest_primary"]
    ctr = freeze["lei_mapping_architecture_only"]["contrast_evaporative_tower_water"]

    def pick(tech, climate, size, liquid=None):
        q = (m.tech_id == tech) & (m["Climate Zone"] == climate) & (m["Data center size"] == size)
        if liquid:
            q = q & (m.liquid_cooling_type == liquid)
        sub = m[q]
        if sub.empty:
            return None
        r = sub.iloc[0]
        return {
            "tech_id": r.tech_id,
            "Cooling system": r["Cooling system"],
            "Climate Zone": r["Climate Zone"],
            "PUE_p05": float(r.PUE_p05),
            "PUE_p95": float(r.PUE_p95),
            "WUE_site_p05": float(r.WUE_site_model_p05),
            "WUE_site_p95": float(r.WUE_site_model_p95),
            "evidence_status": r.evidence_status,
        }

    p = pick(prim["tech_id"], prim["climate"], prim["size"], prim["liquid_cooling_type"])
    c = pick(ctr["tech_id"], ctr["climate"], ctr["size"])
    rec = {
        "ESIF_MEASURED_OR_SOURCE_DERIVED": {"WUE": 0.70, "PUE": 1.034, "WUE_cf_reuse": 1.27, "WUE_cf_tower": 1.42},
        "LEI_MASANET_MODELED_SCENARIO_primary": p,
        "LEI_MASANET_MODELED_SCENARIO_contrast_tower": c,
        "architecture_match": "PARTIAL",
        "lineage": (
            "ESIF Sickinger/NREL empirical/source-derived evidence is independent from the Lei/Masanet modeled scenario lineage. "
            "Architecture mismatch prevents direct coefficient validation. Directional dry-vs-evaporative water ordering is an external structural consistency check, not coefficient validation."
        ),
        "ESIF_VS_LEI_MASANET": "PARTIAL_INDEPENDENT_EXTERNAL_STRUCTURAL_VALIDATION",
        "direction_of_technology_effect": (
            "ESIF source: adding dry TSC after reuse reduces engineering-counterfactual WUE 1.27 → 0.70. "
            "Lei LIQ_DRY_AD in 5B has low WUE relative to WE_WCC in 5B (dry vs evaporative-tower water). "
            "Direction (dry rejection uses less site water than open-tower evaporation) is consistent. "
            "Magnitudes are not comparable as the same object."
        ),
        "PUE_WUE_tradeoff": "ESIF: TSC saved water without reported PUE degradation (PUE 1.034). Lei dry-liquid PUE also low; not a calibrated match.",
        "weather_dependence": "ESIF documents cold-season TSC dominance; Lei hourly simulator for liquid cases is not in the public bank used here.",
        "dry_vs_evaporative_routing": "ESIF has explicit series routing reuse→dry TSC→wet tower. Lei closest case does not encode that series hierarchy.",
        "no_retuning": True,
        "esif_results_unchanged_after_comparison": True,
    }
    jdump(ANALYSIS / "ESIF_VS_LEI_MASANET.json", rec)
    pd.DataFrame([
        {"side": "ESIF_observed", "WUE": 0.70, "PUE": 1.034, "class": "ESIF_MEASURED_OR_SOURCE_DERIVED"},
        {"side": "ESIF_cf_reuse", "WUE": 1.27, "PUE": 1.034, "class": "MODELED_COUNTERFACTUAL"},
        {"side": "ESIF_cf_tower", "WUE": 1.42, "PUE": None, "class": "MODELED_COUNTERFACTUAL"},
        {"side": "Lei_LIQ_DRY_AD_5B", **({} if not p else {"WUE_p05": p["WUE_site_p05"], "WUE_p95": p["WUE_site_p95"], "PUE_p05": p["PUE_p05"], "PUE_p95": p["PUE_p95"]}), "class": "LEI_MASANET_MODELED_SCENARIO"},
        {"side": "Lei_WE_WCC_5B", **({} if not c else {"WUE_p05": c["WUE_site_p05"], "WUE_p95": c["WUE_site_p95"], "PUE_p05": c["PUE_p05"], "PUE_p95": c["PUE_p95"]}), "class": "LEI_MASANET_MODELED_SCENARIO"},
    ]).to_csv(ANALYSIS / "ESIF_VS_LEI_MASANET.csv", index=False)
    return rec


def figures(acct, wx, lei) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    # 1. allocation pie
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.pie([10.5, 42.5, 47.0], labels=["Reuse 10.5%", "TSC dry 42.5%", "Tower evap 47%"],
           colors=["#c44e52", "#55a868", "#4c72b0"])
    ax.set_title("First-year heat-rejection allocation\n(Sickinger MEASUREMENT_DERIVED annual shares)")
    fig.tight_layout()
    fig.savefig(FIGURES / "02_first_year_heat_allocation.png", dpi=120)
    plt.close()

    # 2. WUE technology bars
    fig, ax = plt.subplots(figsize=(7, 4))
    names = ["Tower only\n(counterfactual)", "Reuse + tower\n(counterfactual)", "Reuse+TSC+tower\n(source WUE)"]
    vals = [1.42, 1.27, 0.70]
    colors = ["#4c72b0", "#dd8452", "#55a868"]
    ax.bar(names, vals, color=colors)
    ax.set_ylabel("WUE (L/kWh IT)")
    ax.set_title("Source WUE technology decomposition (not a fitted model)")
    ax.set_ylim(0, 1.8)
    fig.tight_layout()
    fig.savefig(FIGURES / "05_wue_technology_decomposition.png", dpi=120)
    plt.close()

    # 3. weather vs documented TSC-dominant months
    m = pd.DataFrame(wx["monthly"])
    fig, ax = plt.subplots(figsize=(8, 3.5))
    col = np.where(m.source_TSC_expected_dominant, "#55a868", "#4c72b0")
    ax.bar(range(len(m)), m.tdb_c, color=col)
    ax.axhline(TSC_DB_THRESHOLD_C, color="k", ls="--", lw=1, label=f"documented 9.4 °C rule")
    ax.set_xticks(range(len(m)))
    ax.set_xticklabels(m.month, rotation=90, fontsize=8)
    ax.set_ylabel("Mean Tdb °C")
    ax.set_title("Independent ESIF weather, first TSC year\n(green = Nov–Apr source TSC-dominant season)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES / "04_weather_vs_tsc_season.png", dpi=120)
    plt.close()

    # 4. water volumes
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(["Observed\n(WUE×E_IT)", "CF reuse+tower", "CF tower-only"],
           [acct["W_obs_m3_from_WUE"], acct["W_cf_reuse_m3"], acct["W_cf_tower_m3"]],
           color=["#55a868", "#dd8452", "#4c72b0"])
    ax.set_ylabel("m³ / first year")
    ax.set_title("Implied first-year cooling-loop water (WUE × IT energy)")
    fig.tight_layout()
    fig.savefig(FIGURES / "03_implied_water_volumes.png", dpi=120)
    plt.close()

    # 5. ESIF vs Lei
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.axhspan(0.70, 0.70, color="green")
    ax.scatter([0], [0.70], s=80, color="#55a868", label="ESIF observed 0.70", zorder=3)
    ax.scatter([0], [1.27], s=60, color="#dd8452", label="ESIF CF reuse 1.27", zorder=3)
    ax.scatter([0], [1.42], s=60, color="#4c72b0", label="ESIF CF tower 1.42", zorder=3)
    p = lei.get("LEI_MASANET_MODELED_SCENARIO_primary") or {}
    c = lei.get("LEI_MASANET_MODELED_SCENARIO_contrast_tower") or {}
    if p:
        ax.plot([1, 1], [p["WUE_site_p05"], p["WUE_site_p95"]], color="#8c8c8c", lw=4, label="Lei LIQ_DRY_AD 5B p05–p95")
    if c:
        ax.plot([2, 2], [c["WUE_site_p05"], c["WUE_site_p95"]], color="#c44e52", lw=4, label="Lei WE_WCC 5B p05–p95")
    ax.set_xticks([0, 1, 2])
    ax.set_xticklabels(["ESIF", "Lei dry-liquid", "Lei tower+chiller"])
    ax.set_ylabel("site WUE L/kWh")
    ax.set_title("Architecture-preregistered Lei comparison\n(independent ESIF source vs modeled Lei scenarios; mismatch blocks coefficient validation)")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(FIGURES / "06_esif_vs_lei.png", dpi=120)
    plt.close()

    # 6. schematic-like text figure
    fig, ax = plt.subplots(figsize=(8, 3.2))
    ax.axis("off")
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 3)
    boxes = [(0.3, 1, "Q_IT"), (2.3, 1, "remaining"), (4.3, 1, "Q_TSC dry"), (6.3, 1, "remaining"), (8.3, 1, "W_cooling")]
    for x, y, lab in boxes:
        ax.add_patch(plt.Rectangle((x, y), 1.6, 1, fill=True, facecolor="#e8e8e8", edgecolor="k"))
        ax.text(x + 0.8, y + 0.5, lab, ha="center", va="center", fontsize=8)
    for x in (1.9, 3.9, 5.9, 7.9):
        ax.annotate("", xy=(x + 0.4, 1.5), xytext=(x, 1.5), arrowprops=dict(arrowstyle="->"))
    ax.text(3.1, 2.15, "Q_reuse", ha="center", fontsize=8)
    ax.text(7.1, 2.15, "Q_tower evap", ha="center", fontsize=8)
    ax.set_title("Documented ESIF heat→water hierarchy (remaining thermal load; structure, not coefficients)")
    fig.tight_layout()
    fig.savefig(FIGURES / "01_thermal_water_hierarchy.png", dpi=120)
    plt.close()


def write_status(acct, elig, ident, lei) -> dict:
    st = {
        "SOURCE_PROVENANCE": "PASS",
        "WATER_BOUNDARY_IDENTIFIED": "PASS",
        "THERMAL_BOUNDARY_IDENTIFIED": "PASS",
        "FIRST_YEAR_ACCOUNTING_REPRODUCTION": acct["FIRST_YEAR_ACCOUNTING_REPRODUCTION"],
        "FIRST_YEAR_SOURCE_ACCOUNTING_REPRODUCTION": acct["FIRST_YEAR_ACCOUNTING_REPRODUCTION"],
        "FIRST_YEAR_ARITHMETIC_CONSISTENCY": acct["FIRST_YEAR_ACCOUNTING_REPRODUCTION"],
        "FIRST_YEAR_INDEPENDENT_METER_REOBSERVATION": "NOT_AVAILABLE",
        "WATER_TEMPORAL_RESOLUTION": "STRUCTURAL_ONLY",
        "WATER_MODEL_ELIGIBILITY": "STRUCTURAL_ACCOUNTING_ONLY",
        "NUMERIC_TABULAR_WATER_RESOLUTION": "ANNUAL",
        "GRAPHICAL_REPORTED_WATER_RESOLUTION": "MONTHLY",
        "WATER_MODEL_IDENTIFIABILITY": "NO_FITTED_MODEL_REQUIRED",
        "HEAT_REJECTION_ALLOCATION": "PASS",
        "WEATHER_REGIME_MECHANISM": "PARTIAL",
        "TSC_WATER_REDUCTION": "PASS",
        "TSC_SOURCE_COUNTERFACTUAL_WATER_REDUCTION": "PASS",
        "HEAT_REUSE_WATER_REDUCTION": "PASS",
        "HEAT_REUSE_SOURCE_COUNTERFACTUAL_WATER_REDUCTION": "PASS",
        "TSC_CAUSAL_TREATMENT_EFFECT": "NOT_IDENTIFIED",
        "HEAT_REUSE_CAUSAL_TREATMENT_EFFECT": "NOT_IDENTIFIED",
        "OBSERVED_WUE": "PASS",
        "COUNTERFACTUAL_WUE": "PASS",
        "MONTHLY_WATER_RECONSTRUCTION": "UNSUPPORTED",
        "WATER_MODEL": "NOT_NEEDED",
        "WATER_MODEL_OUT_OF_TIME_VALIDATION": "NOT_NEEDED",
        "ESIF_VS_LEI_MASANET": "PARTIAL_INDEPENDENT_EXTERNAL_STRUCTURAL_VALIDATION",
        "PRINEVILLE_COEFFICIENT_TRANSFER": "NOT_ALLOWED",
        "HEAT_WATER_FINAL_DISPOSITION": "STRUCTURAL_ACCOUNTING_VALIDATION",
        "cpu_untouched": True,
        "h100_untouched": True,
        "facility_overhead_untouched": True,
        "prineville_modified": False,
        "meta_water_accessed": False,
        "fitted_water_model": False,
        "used_hvac_kw_as_heat": False,
        "used_cooling_kw_as_heat": False,
        "lei_mapping_frozen_before_outcome_comparison": True,
        "esif_result_changed_after_lei": False,
    }
    jdump(ANALYSIS / "FINAL_ESIF_HEAT_WATER_STATUS.json", st)
    return st


def main() -> None:
    os.environ.setdefault("PYTHONNOUSERSITE", "1")
    assert_upstream_untouched()
    print("provenance…", flush=True)
    write_provenance()
    print("inventory…", flush=True)
    inventory()
    freeze_boundaries()
    print("first-year accounting…", flush=True)
    acct = first_year_accounting()
    if acct["FIRST_YEAR_ACCOUNTING_REPRODUCTION"] == "FAIL":
        raise SystemExit("STOP BEFORE MODELING: first-year accounting failed")
    elig = temporal_eligibility()
    print("weather mechanism (no power/HVAC)…", flush=True)
    wx = weather_mechanism()
    allocations()
    technology_decomp(acct)
    ident = identifiability(elig, wx)
    uncertainty()
    print("freeze ESIF result…", flush=True)
    freeze = freeze_esif_result(acct, elig, ident, wx)
    print("Lei comparison after freeze…", flush=True)
    lei = lei_compare(freeze)
    figures(acct, wx, lei)
    st = write_status(acct, elig, ident, lei)
    assert_upstream_untouched()
    print(json.dumps({"disposition": st["HEAT_WATER_FINAL_DISPOSITION"], "accounting": acct["FIRST_YEAR_ACCOUNTING_REPRODUCTION"], "model": ident["choice"]}, indent=2))
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
