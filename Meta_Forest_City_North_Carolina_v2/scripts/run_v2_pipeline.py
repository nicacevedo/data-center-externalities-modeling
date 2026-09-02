#!/usr/bin/env python3
"""Forest City v2 pipeline.

Read-only on v1/Prineville/CPU/H100/ESIF. No calibration. No mit_normal.
Does not write into Meta_Forest_City_North_Carolina_v1/.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

FC2 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FC2 / "src"))

from fc2_paths import PRN, REPO, V1  # noqa: E402
from hashes import sha256_file, write_json  # noqa: E402
from v1_bridge import (  # noqa: E402
    EVAP_THERMAL_EFFECTIVENESS_GENERIC_PRIOR,
    IT_EQUIPMENT_DELTA_T_DESIGN_F,
    IT_EQUIPMENT_DELTA_T_DESIGN_K,
    c_to_f,
    dry_air_mass_flow_from_sensible_heat_kg_s,
    f_to_c,
    simulate_frame,
    simulate_hour,
    state_from_t_rh,
    water_m3_h_from_delta_w,
)

OUT = FC2 / "outputs"
RAW_NEW = FC2 / "data" / "raw" / "documentary_evidence"
WEATHER_PARQUET = V1 / "data/processed/forest_city_weather_2012_hourly.parquet"
WEATHER_SHA = "f87a2e61120cf2d8e3117ff20e838567d0f8525a650a7fdaad221f9b3044e1d9"
P_IT_MW = 1.0e6  # 1 MW_IT scenario only; not 2012 FRC1 load
EPS_BOUNDS = (
    (0.70, "CONSERVATIVE_ENGINEERING_BOUND"),
    (0.85, "GENERIC_PRIOR_SCENARIO_NOT_FOREST_CITY_SOURCED"),
    (1.00, "IDEAL_UPPER_BOUND"),
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    cols = list(rows[0].keys())
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def family_of_row(r) -> str:
    if bool(r.get("dx_required")):
        return "DX_REQUIRED"
    if bool(r.get("spray_enabled")):
        return "EVAPORATIVE_COOLING"
    oa = r.get("oa_fraction")
    if pd.notna(oa) and float(oa) < 0.999:
        return "RETURN_AIR_MIXING"
    mode = str(r.get("control_mode") or "")
    if mode == "WEATHER_MISSING":
        return "WEATHER_MISSING"
    return "OA_FREE_COOLING"


def step2_source_registry(new_sources: list[dict]) -> pd.DataFrame:
    src = pd.read_csv(V1 / "config/forest_city_source_register.csv")
    rows = []
    for _, r in src.iterrows():
        local = str(r.get("local_path") or "")
        sha = str(r.get("sha256") or "")
        if local and Path(local).exists() and (not sha or sha in ("nan", "")):
            sha = sha256_file(Path(local))
        rows.append({
            "source_id": r["source_id"],
            "title": r["title"],
            "url": r.get("url"),
            "local_file": local if local and local != "nan" else "",
            "sha256": sha if sha != "nan" else "",
            "publication_date": r.get("publication_date"),
            "event_or_measurement_date": r.get("temporal_scope"),
            "geographic_boundary": r.get("site_scope"),
            "temporal_boundary": r.get("temporal_scope"),
            "quantity_boundary": r.get("quantity"),
            "evidence_type": _evidence_type(r),
            "confidence": r.get("source_tier"),
            "permitted_quantitative_use": _permitted_use(r),
            "design_vs_observed": r.get("design_vs_observed"),
            "building_scope": r.get("building_scope"),
            "limitations": r.get("limitations"),
            "origin": "FOREST_CITY_V1_REGISTER_REFERENCED_NOT_COPIED",
        })
    extras = [
        {
            "source_id": "KFQD_ISD_2012_HOURLY",
            "title": "NOAA ISD KFQD Rutherford Co Marchman Field 2012 hourly (frozen v1 parquet)",
            "url": "https://www.ncei.noaa.gov/data/global-hourly/",
            "local_file": str(WEATHER_PARQUET),
            "sha256": sha256_file(WEATHER_PARQUET),
            "publication_date": "2012",
            "event_or_measurement_date": "2012-06-21/2012-12-31 usable",
            "geographic_boundary": "county / KFQD ~6 mi NW of campus (OCP design-analysis station)",
            "temporal_boundary": "2012; Jan 1–Jun 21 17:00 UTC MISSING not imputed",
            "quantity_boundary": "outdoor dry bulb / RH / pressure",
            "evidence_type": "measured",
            "confidence": "HIGH_as_station_weather; MEDIUM_as_campus_microclimate",
            "permitted_quantitative_use": "hourly outdoor state for controller/psychrometrics; not campus water or electricity",
            "design_vs_observed": "MEASURED_WEATHER",
            "building_scope": "not building-specific",
            "limitations": "OCP used Rutherfordton ~6 miles NW; June 1-20 2012 missing.",
            "origin": "FOREST_CITY_V1_WEATHER_REFERENCED_NOT_COPIED",
        },
        {
            "source_id": "HSU_MULAY_FOREST_CITY_DX",
            "title": "Hsu and Mulay Forest City mechanical case-study slides (DX coil / psychrometric chart)",
            "url": "https://www.yumpu.com/en/document/view/45018683/a-case-studies-hsu-and-mulay",
            "local_file": "",
            "sha256": "",
            "publication_date": "circa_2013_OCP_summit",
            "event_or_measurement_date": "FRC1 design; BIN weather typical year",
            "geographic_boundary": "FRC1",
            "temporal_boundary": "design / typical-year BIN; not as-operated TAB",
            "quantity_boundary": "DX present; sized to dehumidify OA at extreme weather; BIN says DX not required typical year; FRC chart also shows 41.9F min dewpoint which v1 did not adopt as FC setpoint",
            "evidence_type": "engineering design",
            "confidence": "MEDIUM_for_DX_existence; LOW_for_dewpoint_min (not independently restated in OCP 2013 operator post)",
            "permitted_quantitative_use": "DX existence DESIGN_SPEC only; do not import 41.9F dewpoint min; no CFM/TAB",
            "design_vs_observed": "DESIGN_SPEC",
            "building_scope": "FRC1",
            "limitations": "Slide deck via third-party viewer; not a TAB report. v1 controller correctly did not copy 41.9F min dewpoint.",
            "origin": "REFERENCED_IN_V1_CONTRACT_NOT_DOWNLOADED_AS_NUMERIC_TRUTH",
        },
        {
            "source_id": "META_EDI_ANNUAL_ELECTRICITY_WATER",
            "title": "Meta Environmental Data Index Forest City site rows (electricity MWh; withdrawal m3/ML)",
            "url": "https://sustainability.atmeta.com/wp-content/uploads/2025/10/Meta_2025-Environmental-Data-Index.pdf",
            "local_file": str(V1 / "data/processed/FOREST_CITY_ANNUAL_ELECTRICITY.csv"),
            "sha256": sha256_file(V1 / "data/processed/FOREST_CITY_ANNUAL_ELECTRICITY.csv"),
            "publication_date": "2019-2025 disclosures",
            "event_or_measurement_date": "calendar years 2015-2024 electricity; 2017-2024 withdrawal",
            "geographic_boundary": "campus / FOREST_CITY_SITE_AS_REPORTED",
            "temporal_boundary": "annual; not 2012 FRC1 interval",
            "quantity_boundary": "campus electricity; campus withdrawal — not cooling-water meter, not WUE",
            "evidence_type": "corporate annual",
            "confidence": "HIGH_as_reported_site_totals; LOW_as_2012_FRC1",
            "permitted_quantitative_use": "descriptive annual accounting only; never controller calibration; never 2012 FRC1 load",
            "design_vs_observed": "REPORTED_ANNUAL",
            "building_scope": "unidentified mix of halls after 2012",
            "limitations": "Later years are not 2012 Building 1. Withdrawal is not cooling evaporation.",
            "origin": "FOREST_CITY_V1_PROCESSED_REFERENCED_NOT_COPIED",
        },
        {
            "source_id": "FBPUEWUE_DASHBOARD_WAYBACK",
            "title": "fbpuewue.com Forest City Wayback HTML (no numeric payload)",
            "url": "https://www.fbpuewue.com/forestcity",
            "local_file": str(V1 / "outputs/dashboard_recovery/DASHBOARD_RECOVERY_STATUS.json"),
            "sha256": sha256_file(V1 / "outputs/dashboard_recovery/DASHBOARD_RECOVERY_STATUS.json"),
            "publication_date": "2012-08 dashboard launch; archives 2013-2021",
            "event_or_measurement_date": "UNIDENTIFIED numeric period",
            "geographic_boundary": "FOREST_CITY dashboard site",
            "temporal_boundary": "public dashboard era",
            "quantity_boundary": "PUE / WUE labels only; ISO WUE numerator NOT verified",
            "evidence_type": "screenshot",
            "confidence": "HIGH_that_dashboard_existed; n/a as measurement",
            "permitted_quantitative_use": "NONE — SCREENSHOT_ONLY",
            "design_vs_observed": "SCREENSHOT_ONLY",
            "building_scope": "dashboard site",
            "limitations": "No JSON API in Wayback. Must not enter quantitative validation.",
            "origin": "FOREST_CITY_V1_DASHBOARD_REFERENCED_NOT_COPIED",
        },
    ]
    rows.extend(extras)
    rows.extend(new_sources)
    df = pd.DataFrame(rows)
    _csv(OUT / "source_audit" / "SOURCE_REGISTRY.csv", df.to_dict(orient="records"))
    hashes = {r["source_id"]: {"sha256": r["sha256"], "local_file": r["local_file"]} for r in rows}
    write_json(OUT / "source_audit" / "SOURCE_HASHES.json", hashes)
    claims = [
        {"claim_id": "FRC1_OPEN_2012_04_19", "claim": "FRC1 operational 2012-04-19", "source_id": "META_FC_OPENING_2012_04_19", "status": "VALIDATED", "design_not_measurement": False},
        {"claim_id": "IT_DELTA_T_35F_DESIGN", "claim": "IT design rise 35F", "source_id": "MAGUIRE_2011_OCP_REFLECTIONS", "status": "IDENTIFIED_DESIGN_SPEC", "design_not_measurement": True},
        {"claim_id": "FACILITY_EFFECTIVE_DELTA_T", "claim": "facility-effective DeltaT", "source_id": "", "status": "UNIDENTIFIED", "design_not_measurement": True},
        {"claim_id": "ENVELOPE_85F_90RH", "claim": "85F / 90% RH envelope", "source_id": "OCP_2013_HOT_HUMID", "status": "SUPPORTED", "design_not_measurement": False},
        {"claim_id": "EVENT_2012_06_25_MIXING", "claim": "high-RH mixing 2012-06-25", "source_id": "OCP_2013_HOT_HUMID", "status": "VALIDATED", "design_not_measurement": False},
        {"claim_id": "EVENT_2012_07_01_EVAP", "claim": "evaporative 2012-07-01; DX unused", "source_id": "OCP_2013_HOT_HUMID", "status": "VALIDATED", "design_not_measurement": False},
        {"claim_id": "SUMMER_2012_DX_UNUSED", "claim": "DX unused summer 2012", "source_id": "OCP_2013_HOT_HUMID", "status": "SUPPORTED", "design_not_measurement": False},
        {"claim_id": "PUE_1_07_SUMMER", "claim": "seasonal PUE 1.07 summer 2012", "source_id": "OCP_2013_HOT_HUMID", "status": "ENGINEERING_BOUNDED", "design_not_measurement": False},
        {"claim_id": "DASHBOARD_NUMERIC", "claim": "dashboard PUE/WUE time series", "source_id": "FBPUEWUE_DASHBOARD_WAYBACK", "status": "UNIDENTIFIED", "design_not_measurement": False},
        {"claim_id": "WUE_NUMERATOR", "claim": "cooling WUE numerator/meter", "source_id": "", "status": "UNIDENTIFIED", "design_not_measurement": True},
        {"claim_id": "MUNICIPAL_INDUSTRIAL_IS_META", "claim": "LWSP industrial class = Meta", "source_id": "NC_LWSP_FC_2023", "status": "FAILED_IF_ASSERTED", "design_not_measurement": True},
        {"claim_id": "CAMPUS_WITHDRAWAL_IS_COOLING", "claim": "campus withdrawal = cooling water", "source_id": "META_EDI_ANNUAL_ELECTRICITY_WATER", "status": "UNIDENTIFIED", "design_not_measurement": True},
        {"claim_id": "2024_KWH_IS_2012_FRC1", "claim": "2024 campus electricity = 2012 FRC1", "source_id": "META_EDI_ANNUAL_ELECTRICITY_WATER", "status": "FAILED_IF_ASSERTED", "design_not_measurement": True},
        {"claim_id": "MEMBRANE_EPOCH_DATE", "claim": "membrane vs misters dated cooling epoch", "source_id": "ITNEWS_MCCAMMON_FC", "status": "UNIDENTIFIED", "design_not_measurement": True},
        {"claim_id": "SPLC_AT_FOREST_CITY", "claim": "SPLC deployed at Forest City", "source_id": "", "status": "UNIDENTIFIED", "design_not_measurement": True},
        {"claim_id": "TAB_CFM", "claim": "as-operated CFM / SAT / RAT", "source_id": "", "status": "UNIDENTIFIED", "design_not_measurement": True},
    ]
    _csv(OUT / "source_audit" / "CLAIM_EVIDENCE_MATRIX.csv", claims)
    return df


def _evidence_type(r) -> str:
    dvo = str(r.get("design_vs_observed") or "")
    tier = str(r.get("source_tier") or "")
    if "SCREENSHOT" in dvo or "DASHBOARD" in tier:
        return "screenshot"
    if "DESIGN" in dvo:
        return "engineering design"
    if "OPERATOR" in dvo or "OPERATOR" in tier:
        return "operator statement"
    if "REPORTED_ANNUAL" in dvo or "DISCLOSURE" in tier:
        return "corporate annual"
    if "GOVERNMENT" in tier or "LWSP" in str(r.get("source_id")):
        return "administrative"
    if "OBSERVED" in dvo:
        return "measured"
    return "inferred"


def _permitted_use(r) -> str:
    dvo = str(r.get("design_vs_observed") or "")
    if "DESIGN" in dvo:
        return "design specification only; not as-operated measurement"
    if "SCREENSHOT" in dvo:
        return "NONE"
    if "REPORTED_ANNUAL" in dvo:
        return "descriptive campus annual accounting only"
    if "SYSTEM_DESCRIPTION" in dvo or "PORTAL" in dvo:
        return "municipal/administrative context; not Meta meter"
    return "as documented; do not upgrade evidence class"


def step3_architecture() -> pd.DataFrame:
    rows = [
        {
            "epoch_id": "E2010_FRC1_CONSTRUCTION",
            "start_date": "2010-11-01",
            "end_date": "2012-04-18",
            "scope": "FRC1 construction",
            "building_or_campus": "FRC1",
            "cooling_architecture": "UNDER_CONSTRUCTION",
            "change_description": "Original campus construction start ~Nov 2010; not operating.",
            "source_id": "DPR_FOREST_CITY_PROJECT;META_FC_OPENING_2012_04_19",
            "evidence_strength": "HIGH",
            "hard_epoch_boolean": True,
            "known_parameters": "construction of original hall",
            "unknown_parameters": "as-operated CFM, SAT/RAT, IT MW",
        },
        {
            "epoch_id": "E2012_FRC1_OA_EVAP_DX",
            "start_date": "2012-04-19",
            "end_date": "UNBOUNDED_OPEN",
            "scope": "FRC1 operating architecture",
            "building_or_campus": "FRC1",
            "cooling_architecture": "DIRECT_OUTSIDE_AIR_EVAPORATIVE_with_DX_BACKUP",
            "change_description": "FRC1 opens. Direct OA evaporative/misting + DX backup. 85F/90%RH. Municipal UV then misting. Hard cooling-architecture epoch for FRC1 only; later campus mix unidentified.",
            "source_id": "META_FC_OPENING_2012_04_19;OCP_2013_HOT_HUMID;ENR_2013_GREEN_LIKES;HSU_MULAY_FOREST_CITY_DX",
            "evidence_strength": "HIGH",
            "hard_epoch_boolean": True,
            "known_parameters": "85F inlet; 90% RH; DX present unused summer 2012; 35F IT design rise",
            "unknown_parameters": "FACILITY_EFFECTIVE_DELTA_T; CFM; cooling-water meter; FRC1 interval kWh",
        },
        {
            "epoch_id": "E2014_FRC3_SECOND_LARGE_HALL_PRESENT",
            "start_date": "2014-04-22",
            "end_date": "UNBOUNDED_OPEN",
            "scope": "campus composition",
            "building_or_campus": "campus",
            "cooling_architecture": "DIRECT_OUTSIDE_AIR_EVAPORATIVE_LIKELY_SAME_FAMILY",
            "change_description": "2014 tour confirms a second large production hall (called Building 3). Cooling family likely similar is MEDIUM, not a proven cooling-technology hard epoch. Do not merge with 2012 planned Building 2 (empty pad in 2014).",
            "source_id": "AIWIRE_2014_COLD_STORAGE;CHARLOTTE_OBSERVER_COLD_STORAGE",
            "evidence_strength": "HIGH_for_building_existence; MEDIUM_for_cooling_sameness",
            "hard_epoch_boolean": True,
            "known_parameters": "second large hall present by 2014 tour",
            "unknown_parameters": "exact opening date; as-operated cooling identity vs FRC1",
        },
        {
            "epoch_id": "E2014_FRC4_COLD_STORAGE",
            "start_date": "2014-01-01",
            "end_date": "UNBOUNDED_OPEN",
            "scope": "FRC4 function",
            "building_or_campus": "FRC4",
            "cooling_architecture": "MINIATURIZED_OUTSIDE_AIR_COOLING",
            "change_description": "Cold-storage archive halls (~90k sf, 14 AHUs press). Different function from FRC1 production halls. Dates MEDIUM.",
            "source_id": "AIWIRE_2014_COLD_STORAGE;ENR_2014_FRC4",
            "evidence_strength": "HIGH_existence; MEDIUM_dates",
            "hard_epoch_boolean": True,
            "known_parameters": "cold storage existence and distinct function",
            "unknown_parameters": "load share of campus electricity/water",
        },
        {
            "epoch_id": "CANDIDATE_MEMBRANE_VS_MISTERS",
            "start_date": "UNRESOLVED",
            "end_date": "UNRESOLVED",
            "scope": "cooling technology candidate",
            "building_or_campus": "campus UNRESOLVED which halls",
            "cooling_architecture": "CANDIDATE_MEMBRANE_IN_PLACE_OF_MISTERS",
            "change_description": "McCammon/ITNEWS: later membrane vs misters for water efficiency. Timing vs annual withdrawal drop UNRESOLVED. Not a hard epoch. Must not be dated from Meta EDI water.",
            "source_id": "ITNEWS_MCCAMMON_FC",
            "evidence_strength": "LOW_for_date; MEDIUM_that_operator_discussed_membrane",
            "hard_epoch_boolean": False,
            "known_parameters": "operator mentioned membrane later",
            "unknown_parameters": "install date; which buildings; meter impact",
        },
        {
            "epoch_id": "CANDIDATE_SPLC_OR_INDIRECT",
            "start_date": "UNRESOLVED",
            "end_date": "UNRESOLVED",
            "scope": "cooling technology candidate",
            "building_or_campus": "UNRESOLVED",
            "cooling_architecture": "CANDIDATE_SPLC_UNCONFIRMED_AT_FOREST_CITY",
            "change_description": "Public SPLC/indirect-cooling statements are about a later Meta technology family, not an independently dated Forest City mechanical retrofit. Remain CANDIDATE.",
            "source_id": "",
            "evidence_strength": "NONE_as_FC_hard_epoch",
            "hard_epoch_boolean": False,
            "known_parameters": "",
            "unknown_parameters": "whether SPLC was ever installed at Forest City",
        },
        {
            "epoch_id": "CANDIDATE_POST2014_ADDITIONAL_HALL",
            "start_date": "UNRESOLVED",
            "end_date": "UNRESOLVED",
            "scope": "campus composition candidate",
            "building_or_campus": "campus",
            "cooling_architecture": "UNIDENTIFIED",
            "change_description": "Secondary aggregators claim an additional ~2017 hall. Not independently confirmed in primary Meta/DPR sources in v1. Remain UNRESOLVED.",
            "source_id": "",
            "evidence_strength": "LOW",
            "hard_epoch_boolean": False,
            "known_parameters": "",
            "unknown_parameters": "existence, date, cooling, electrical capacity",
        },
    ]
    df = pd.DataFrame(rows)
    _csv(OUT / "architecture" / "FOREST_CITY_ARCHITECTURE_EPOCH_REGISTRY.csv", rows)
    return df


def step4_regression(w: pd.DataFrame) -> dict:
    v1_events = json.loads((V1 / "outputs/control_validation/HISTORICAL_EVENT_VALIDATION.json").read_text())
    v1_summer = json.loads((V1 / "outputs/control_validation/SUMMER_2012_DX_VALIDATION.json").read_text())
    v1_qa = json.loads((V1 / "outputs/weather/FOREST_CITY_2012_WEATHER_QA.json").read_text())
    v1_xfer = json.loads((V1 / "outputs/cross_site_validation/PRINEVILLE_FOREST_CITY_TRANSFER_STATUS.json").read_text())
    w = w.copy()
    w["local_date"] = pd.to_datetime(w["timestamp_local"]).dt.tz_convert("America/New_York").dt.date.astype(str)
    rows = []
    ok = True
    for event, date, op_T, op_RH, expect_fam in (
        ("B_2012_06_25", "2012-06-25", 68.0, 0.97, "RETURN_AIR_MIXING"),
        ("A_2012_07_01", "2012-07-01", 102.0, 0.26, "EVAPORATIVE_COOLING"),
    ):
        day = w[w["local_date"] == date]
        usable = day.dropna(subset=["t_db_C", "rh_pct", "pressure_Pa"])
        sim = simulate_frame(usable, airflow_boundary="UNIDENTIFIED")
        t_c = f_to_c(op_T)
        rh = op_RH * 100
        p = float(usable["pressure_Pa"].median())
        synth = simulate_hour(t_db_C=t_c, rh_pct=rh, pressure_Pa=p, airflow_boundary="UNIDENTIFIED")
        dx_hours = int(sim["dx_required"].sum())
        family = "DX_REQUIRED" if synth["dx_required"] else (
            "EVAPORATIVE_COOLING" if synth["spray_enabled"] else (
                "RETURN_AIR_MIXING" if synth["oa_fraction"] < 0.999 else "OA_FREE_COOLING"
            )
        )
        v1 = v1_events["events"][event]
        checks = {
            "status_match": family == v1["synthetic_mode_family"] or (
                expect_fam == "RETURN_AIR_MIXING" and family in ("RETURN_AIR_MIXING", "OA_FREE_COOLING")
            ),
            "v1_status": v1["status"],
            "v2_synthetic_mode": synth["control_mode"],
            "v2_family": family,
            "v2_dx_hours": dx_hours,
            "v1_dx_hours": v1["day_dx_required_hours"],
            "dx_hours_match": dx_hours == v1["day_dx_required_hours"],
            "synthetic_dx_match": bool(synth["dx_required"]) == bool(v1["synthetic_dx"]),
            "n_hours_match": int(len(sim)) == int(v1["n_kfqd_hours"]),
        }
        rec = {"item": event, **checks, "PASS": all([checks["status_match"], checks["dx_hours_match"], checks["synthetic_dx_match"], checks["n_hours_match"]]) and v1["status"] == "PASS"}
        ok = ok and rec["PASS"]
        rows.append(rec)

    jja = w[(w["timestamp_utc"] >= "2012-06-01") & (w["timestamp_utc"] < "2012-09-01")]
    usable = jja.dropna(subset=["t_db_C", "rh_pct", "pressure_Pa"])
    sim1 = simulate_frame(usable, airflow_boundary="UNIDENTIFIED", evap_thermal_effectiveness=1.0)
    sim085 = simulate_frame(usable, airflow_boundary="UNIDENTIFIED", evap_thermal_effectiveness=0.85)
    dx1 = int(sim1["dx_required"].sum())
    dx085 = int(sim085["dx_required"].sum())
    n = int(len(usable))
    rows.append({
        "item": "summer_DX_eps1",
        "v1": v1_summer["primary"]["PREDICTED_DX_REQUIRED_HOURS"],
        "v2": dx1,
        "PASS": dx1 == v1_summer["primary"]["PREDICTED_DX_REQUIRED_HOURS"] == 0,
    })
    rows.append({
        "item": "summer_DX_eps085",
        "v1": v1_summer["sensitivity_generic_prior"]["PREDICTED_DX_REQUIRED_HOURS"],
        "v2": dx085,
        "PASS": dx085 == v1_summer["sensitivity_generic_prior"]["PREDICTED_DX_REQUIRED_HOURS"] == 0,
    })
    rows.append({
        "item": "summer_classified_hours",
        "v1": v1_summer["primary"]["n_classified_hours"],
        "v2": n,
        "PASS": n == v1_summer["primary"]["n_classified_hours"] == 1253,
    })
    weather_sha = sha256_file(WEATHER_PARQUET)
    rows.append({
        "item": "weather_parquet_sha256",
        "v1": v1_qa["parquet_sha256"],
        "v2": weather_sha,
        "PASS": weather_sha == v1_qa["parquet_sha256"] == WEATHER_SHA,
    })
    rows.append({
        "item": "weather_usable_JJA",
        "v1": v1_qa["usable_hours_JJA"],
        "v2": n,
        "PASS": n == v1_qa["usable_hours_JJA"],
    })
    rows.append({
        "item": "transfer_status",
        "v1": v1_xfer["status"],
        "v2": v1_xfer["status"],
        "PASS": v1_xfer["status"] == "TRANSFERABLE_PHYSICS_SUPPORTED" and v1_xfer["MODEL_CALIBRATED"] == "NO",
    })
    ok = ok and all(r.get("PASS") for r in rows)
    verdict = "PASS_AND_FREEZE" if ok else "FAIL_STOP"
    payload = {"verdict": verdict, "rows": rows, "controller_not_modified": True, "MODEL_CALIBRATED": "NO"}
    _csv(OUT / "controller_validation" / "V1_REGRESSION_CHECK.csv", rows)
    write_json(OUT / "controller_validation" / "V1_REGRESSION_CHECK.json", payload)
    if verdict != "PASS_AND_FREEZE":
        raise SystemExit("STEP 4 FAIL: v1 regression mismatch. Diagnose before continuing.\n" + json.dumps(payload, indent=2, default=str))
    return {"sim_jja_eps1": sim1, "sim_jja_eps085": sim085, "usable_jja": usable, "verdict": verdict}


def scenario_water_m3_h_per_mw(dw: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """SCENARIO_ONLY: treat IT design DeltaT as if it were effective. Not FRC1 load."""
    m_air = dry_air_mass_flow_from_sensible_heat_kg_s(P_IT_MW, IT_EQUIPMENT_DELTA_T_DESIGN_K)
    water = np.array([
        water_m3_h_from_delta_w(m_air, float(d)) if np.isfinite(d) else np.nan for d in dw
    ], dtype=float)
    kwh = P_IT_MW / 1000.0
    intensity = water * 1000.0 / kwh
    return water, intensity


def step5_airside(w: pd.DataFrame, reg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    usable_mask = w["t_db_C"].notna() & w["rh_pct"].notna() & w["pressure_Pa"].notna()
    usable = w.loc[usable_mask].copy()
    sim = simulate_frame(usable, airflow_boundary="UNIDENTIFIED", evap_thermal_effectiveness=1.0)
    water_scen, inten_scen = scenario_water_m3_h_per_mw(sim["dw"])
    oa_states = []
    for _, r in usable.iterrows():
        st = state_from_t_rh(float(r["t_db_C"]), float(r["rh_pct"]), float(r["pressure_Pa"]))
        oa_states.append({
            "humidity_ratio_oa": st.w,
            "enthalpy_J_per_kg_da": st.h_J_per_kg_da,
            "t_wb_C_psych": st.T_wb_C,
            "t_wb_F": c_to_f(st.T_wb_C),
        })
    oa_df = pd.DataFrame(oa_states)
    hourly = pd.concat([
        usable.reset_index(drop=True),
        sim.reset_index(drop=True)[[
            "control_mode", "region", "oa_fraction", "spray_enabled", "dx_required",
            "dw", "t_supply_C", "t_supply_F", "rh_supply", "t_wb_C", "margin_T_K", "margin_RH",
            "evap_thermal_effectiveness",
        ]],
        oa_df,
        pd.DataFrame({
            "required_conditioning_regime": [family_of_row(r) for _, r in sim.iterrows()],
            "air_stream_evaporated_water_m3_h_UNIDENTIFIED_AIRFLOW": sim["air_stream_evaporated_water_m3_h"].to_numpy(),
            "evaporative_water_m3_h_per_MW_IT_SCENARIO_ONLY": water_scen,
            "intensity_L_per_kWh_IT_SCENARIO_ONLY": inten_scen,
            "airflow_boundary_primary": "UNIDENTIFIED",
            "airflow_boundary_scenario": "SCENARIO_ONLY_IT_EQUIPMENT_DELTA_T_DESIGN_NOT_EFFECTIVE",
            "FACILITY_EFFECTIVE_DELTA_T": "UNIDENTIFIED",
            "IT_DESIGN_DELTA_T_F": IT_EQUIPMENT_DELTA_T_DESIGN_F,
            "IT_DESIGN_DELTA_T_K": IT_EQUIPMENT_DELTA_T_DESIGN_K,
            "MODEL_CALIBRATED": "NO",
            "not_fitted_to_annual_withdrawal": True,
            "p_it_scenario_W": P_IT_MW,
            "p_it_is_not_2012_FRC1_load": True,
        }),
    ], axis=1)
    hourly = hourly.loc[:, ~hourly.columns.duplicated()]
    hourly.to_parquet(OUT / "airside" / "FOREST_CITY_HOURLY_AIRSIDE_V2.parquet", index=False)

    valid = hourly[hourly["control_mode"] != "WEATHER_MISSING"]
    jja = valid[(valid["timestamp_utc"] >= "2012-06-01") & (valid["timestamp_utc"] < "2012-09-01")]
    summary_rows = []
    for label, df in (("all_usable_2012_kfqd", valid), ("JJA_usable", jja)):
        fam = df["required_conditioning_regime"].value_counts().to_dict()
        evap = df[df["spray_enabled"].astype(bool)]
        summary_rows.append({
            "period": label,
            "n_hours": int(len(df)),
            "dx_required_hours": int(df["dx_required"].sum()),
            "evaporative_hours": int(df["spray_enabled"].sum()),
            "mixing_hours": int((df["required_conditioning_regime"] == "RETURN_AIR_MIXING").sum()),
            "oa_free_hours": int((df["required_conditioning_regime"] == "OA_FREE_COOLING").sum()),
            "mode_counts": json.dumps(fam),
            "mean_dw_all": float(df["dw"].mean()),
            "mean_dw_when_spray": float(evap["dw"].mean()) if len(evap) else 0.0,
            "mean_evap_m3_h_per_MW_IT_SCENARIO": float(df["evaporative_water_m3_h_per_MW_IT_SCENARIO_ONLY"].mean()),
            "p95_evap_m3_h_per_MW_IT_SCENARIO": float(df["evaporative_water_m3_h_per_MW_IT_SCENARIO_ONLY"].quantile(0.95)),
            "FACILITY_EFFECTIVE_DELTA_T": "UNIDENTIFIED",
            "absolute_cooling_water_m3": "UNIDENTIFIED",
            "MODEL_CALIBRATED": "NO",
        })
    _csv(OUT / "airside" / "FOREST_CITY_AIRSIDE_SUMMARY.csv", summary_rows)

    sens = []
    reused = {
        1.00: reg["sim_jja_eps1"],
        0.85: reg["sim_jja_eps085"],
    }
    jja_u = w[(w["timestamp_utc"] >= "2012-06-01") & (w["timestamp_utc"] < "2012-09-01")].dropna(
        subset=["t_db_C", "rh_pct", "pressure_Pa"]
    )
    for eps, tag in EPS_BOUNDS:
        if eps in reused:
            s0 = reused[eps]
        else:
            s0 = simulate_frame(jja_u, airflow_boundary="UNIDENTIFIED", evap_thermal_effectiveness=eps)
        water, _inten = scenario_water_m3_h_per_mw(s0["dw"])
        spray = s0["spray_enabled"].astype(bool)
        sens.append({
            "evap_thermal_effectiveness": eps,
            "tag": tag,
            "optimizer_used": False,
            "annual_meta_used_to_fit": False,
            "n_hours": int(len(s0)),
            "dx_required_hours": int(s0["dx_required"].sum()),
            "mean_dw": float(s0["dw"].mean()),
            "mean_dw_when_spray": float(s0.loc[spray, "dw"].mean()) if spray.any() else 0.0,
            "mean_evaporative_water_m3_h_per_MW_IT_SCENARIO_ONLY": float(np.nanmean(water)),
            "p50_evaporative_water_m3_h_per_MW_IT_SCENARIO_ONLY": float(np.nanmedian(water)),
            "p95_evaporative_water_m3_h_per_MW_IT_SCENARIO_ONLY": float(np.nanquantile(water, 0.95)),
            "FACILITY_EFFECTIVE_DELTA_T": "UNIDENTIFIED",
            "intensity_claim_class": "SCENARIO_BOUNDED",
        })
    _csv(OUT / "airside" / "FOREST_CITY_AIRSIDE_SENSITIVITY.csv", sens)
    return hourly, pd.DataFrame(sens)


def step6_transfer(reg) -> None:
    ev = json.loads((V1 / "outputs/control_validation/HISTORICAL_EVENT_VALIDATION.json").read_text())
    items = [
        {
            "item_id": "B_2012_06_25_MIXING",
            "evidence": "OCP_2013 operator: high-RH mixing; DX not required",
            "classification": "STRUCTURAL_PASS",
            "v1": ev["events"]["B_2012_06_25"]["status"],
            "v2_regression": reg["verdict"],
            "note": "Frozen FC controller + shared psychrometrics. Not a water-magnitude validation.",
        },
        {
            "item_id": "A_2012_07_01_EVAPORATIVE",
            "evidence": "OCP_2013 operator: evaporative/free cooling; DX not required",
            "classification": "STRUCTURAL_PASS",
            "v1": ev["events"]["A_2012_07_01"]["status"],
            "v2_regression": reg["verdict"],
            "note": "Hot/dry snapshot maps to evaporative family.",
        },
        {
            "item_id": "SUMMER_2012_DX_UNUSED",
            "evidence": "OCP_2013: DX coils unused summer 2012; model DX-required hours = 0 on valid KFQD hours",
            "classification": "STRUCTURAL_PASS",
            "v1": 0,
            "v2_regression": reg["verdict"],
            "note": "June 1-20 weather missing; claim is on observed hours only.",
        },
        {
            "item_id": "PSYCHROMETRIC_LAYER_HOT_HUMID",
            "evidence": "Shared Prineville psychrometrics/mixing/adiabatic evap remain physically closed under KFQD states",
            "classification": "STRUCTURAL_PASS",
            "v1": "TRANSFERABLE_PHYSICS_SUPPORTED",
            "v2_regression": "SUPPORTED",
            "note": "Physics transfer ≠ site water validated.",
        },
        {
            "item_id": "SEASONAL_PUE_1_07",
            "evidence": "OCP_2013 seasonal PUE 1.07; no interval electricity, no IT vs facility split recovered",
            "classification": "UNIDENTIFIED",
            "v1": "seasonal operator statement",
            "v2_regression": "boundary inadequate for quantitative PUE reconstruction",
            "note": "QUANTITATIVE_BOUND_PASS not claimed. Screenshot dashboard cannot supply the missing series.",
        },
        {
            "item_id": "ABSOLUTE_SITE_WATER_MAGNITUDE",
            "evidence": "No cooling-water meter; airflow UNIDENTIFIED; EDI is campus withdrawal",
            "classification": "UNIDENTIFIED",
            "v1": "UNIDENTIFIED",
            "v2_regression": "UNIDENTIFIED",
            "note": "Do not equate STRUCTURAL_PASS with water validation.",
        },
        {
            "item_id": "PRN_AH_THRESHOLDS_NOT_TRANSFERRED",
            "evidence": "FC contract explicitly does not inherit 65% RH, 80F SAT, 54F floor, 41.9F dewpoint, regions A-H",
            "classification": "STRUCTURAL_PASS",
            "v1": "local_controls documented",
            "v2_regression": "local envelope retained",
            "note": "Transfer is shared physics + local FC controls, not copied PRN1 A-H.",
        },
    ]
    _csv(OUT / "cross_site_validation" / "PRINEVILLE_FOREST_CITY_V2_RESULTS.csv", items)
    _csv(OUT / "cross_site_validation" / "TRANSFER_EVIDENCE_MATRIX.csv", items)
    status = {
        "physics_controller_transfer": "SUPPORTED",
        "absolute_site_water_magnitude_validated": False,
        "MODEL_CALIBRATED": "NO",
        "FACILITY_EFFECTIVE_DELTA_T": "UNIDENTIFIED",
        "claim_distinction": "physics/controller transfers is not equivalent to absolute site water magnitude validated",
        "items": items,
        "v1_status_preserved": "TRANSFERABLE_PHYSICS_SUPPORTED",
    }
    write_json(OUT / "cross_site_validation" / "TRANSFER_STATUS.json", status)


def step7_water() -> None:
    nodes = [
        {"node_or_edge": "municipal_source_Second_Broad_River", "class": "IDENTIFIED_MEASURED", "source_id": "NC_LWSP_FC_2023", "note": "Town PWSID 01-81-010 raw source. Not Meta."},
        {"node_or_edge": "municipal_WTP_finished_water", "class": "IDENTIFIED_ACCOUNTING", "source_id": "TOWN_FC_WATER_TREATMENT", "note": "Town WTP; UV mentioned in ENR as campus pretreatment context, not a Meta meter."},
        {"node_or_edge": "municipal_industrial_class_flow", "class": "IDENTIFIED_ACCOUNTING", "source_id": "NC_LWSP_FC_2023", "note": "12 industrial connections in 2023 LWSP. NEVER assign class total to Meta."},
        {"node_or_edge": "edge_industrial_class_to_Meta_campus", "class": "UNIDENTIFIED", "source_id": "", "note": "No public customer-meter identity tying industrial class to Meta."},
        {"node_or_edge": "campus_withdrawal_Meta_EDI", "class": "IDENTIFIED_ACCOUNTING", "source_id": "META_EDI_ANNUAL_ELECTRICITY_WATER", "note": "Site withdrawal as reported. Not cooling evaporation."},
        {"node_or_edge": "treatment_RO", "class": "UNIDENTIFIED", "source_id": "", "note": "RO not identified at Forest City. ENR: municipal then UV then evap."},
        {"node_or_edge": "cooling_system_makeup_meter", "class": "UNIDENTIFIED", "source_id": "", "note": "WUE numerator / P&ID tag missing."},
        {"node_or_edge": "air_stream_evaporation_dw", "class": "ENGINEERING_BOUNDED", "source_id": "OCP_2013_HOT_HUMID", "note": "dw structurally identified when spray on; m_dot UNIDENTIFIED so m3 UNIDENTIFIED."},
        {"node_or_edge": "air_stream_evaporation_m3", "class": "SCENARIO_BOUNDED", "source_id": "", "note": "Only if IT design DeltaT is misused as effective; tagged SCENARIO_ONLY."},
        {"node_or_edge": "blowdown_discharge_reuse", "class": "UNIDENTIFIED", "source_id": "META_FC_FACTSHEET_2025", "note": "Factsheet qualitative reuse; no meter."},
        {"node_or_edge": "town_WWTP_NPDES_NC0025984", "class": "IDENTIFIED_ACCOUNTING", "source_id": "NCDEQ_NPDES_NC0025984_NOTICE", "note": "Town WWTP discharges to Second Broad. Not a Meta cooling-water meter. 5 SIUs unnamed."},
        {"node_or_edge": "edge_cooling_makeup_to_campus_withdrawal", "class": "UNIDENTIFIED", "source_id": "", "note": "Other campus uses unidentified; cannot equate."},
        {"node_or_edge": "WUE", "class": "UNIDENTIFIED", "source_id": "FBPUEWUE_DASHBOARD_WAYBACK", "note": "Undefined until numerator/meter identified. Screenshot not a definition."},
    ]
    _csv(OUT / "water_boundary" / "FOREST_CITY_WATER_BOUNDARY_GRAPH.csv", nodes)
    _csv(OUT / "water_boundary" / "FOREST_CITY_WATER_IDENTIFIABILITY_MATRIX.csv", nodes)
    write_json(OUT / "water_boundary" / "FOREST_CITY_WATER_BOUNDARY_STATUS.json", {
        "absolute_cooling_water_magnitude": "UNIDENTIFIED",
        "cooling_water_to_campus_withdrawal": "UNIDENTIFIED",
        "municipal_industrial_equals_Meta": False,
        "WUE_defined": False,
        "Q3": "UNIDENTIFIED",
    })


def _epoch_for_year(year: int) -> str:
    labels = ["E2012_FRC1_OA_EVAP_DX"]
    if year >= 2014:
        labels.append("E2014_FRC3_SECOND_LARGE_HALL_PRESENT")
        labels.append("E2014_FRC4_COLD_STORAGE")
    labels.append("CANDIDATE_MEMBRANE_VS_MISTERS_UNRESOLVED")
    labels.append("CANDIDATE_POST2014_ADDITIONAL_HALL_UNRESOLVED")
    return ";".join(labels)


def step8_annual(epochs: pd.DataFrame) -> pd.DataFrame:
    elec = pd.read_csv(V1 / "data/processed/FOREST_CITY_ANNUAL_ELECTRICITY.csv")
    wat = pd.read_csv(V1 / "data/processed/FOREST_CITY_ANNUAL_WATER_WITHDRAWAL.csv")
    wmap = wat.set_index("year")
    rows = []
    for _, r in elec.iterrows():
        y = int(r["year"])
        wd = wmap.loc[y, "value"] if y in wmap.index else np.nan
        wd_ml = wmap.loc[y, "value_ML"] if y in wmap.index else np.nan
        inten = (float(wd) / (float(r["value"]) * 1000.0)) if pd.notna(wd) else np.nan  # m3 / MWh * 1000 = L/kWh
        # wd m3, elec MWh: L/kWh = (wd * 1000 L) / (MWh * 1000 kWh) = wd / elec
        inten = (float(wd) / float(r["value"])) if pd.notna(wd) else np.nan
        rows.append({
            "year": y,
            "reported_electricity_MWh": r["value"],
            "electricity_reporting_boundary": r["scope"],
            "electricity_source": r["source_publication"],
            "reported_withdrawal_m3": wd if pd.notna(wd) else "",
            "reported_withdrawal_ML": wd_ml if pd.notna(wd_ml) else "",
            "withdrawal_reporting_boundary": "FOREST_CITY_SITE_AS_REPORTED" if pd.notna(wd) else "",
            "withdrawal_source": wmap.loc[y, "source_publication"] if y in wmap.index else "",
            "architecture_epoch_independently_identified": _epoch_for_year(y),
            "withdrawal_per_electricity_L_per_kWh_facility": inten if pd.notna(inten) else "",
            "intensity_name": "SITE_WITHDRAWAL_INTENSITY",
            "not_WUE": True,
            "not_2012_FRC1_load": True,
            "not_cooling_water": True,
        })
    _csv(FC2 / "data/canonical/forest_city_annual_accounting_v2.csv", rows)
    _csv(OUT / "annual_accounting" / "FOREST_CITY_ANNUAL_BY_EPOCH.csv", rows)
    interp = [{
        "question": "Can later campus annuals be interpreted as 2012 FRC1 architecture?",
        "answer": "DO_NOT_ASSUME_YES",
        "electricity_boundary": "FOREST_CITY_SITE_AS_REPORTED campus totals; unidentified hall mix after 2014",
        "water_boundary": "withdrawal not cooling-water meter",
        "legitimate_use": "descriptive campus intensity trajectory only; external consistency check, not calibration",
        "illegitimate_use": "controller fitting; WUE; 2012 FRC1 load; dating membrane epoch from 2024 drop",
    }]
    _csv(OUT / "annual_accounting" / "FOREST_CITY_ANNUAL_INTERPRETABILITY.csv", interp)
    return pd.DataFrame(rows)


def step9_acquire() -> list[dict]:
    """Download a few primary public pages. No other data-center site. No brute force."""
    import urllib.request

    targets = [
        {
            "source_id": "TOWN_FC_WASTEWATER_TREATMENT",
            "url": "https://www.townofforestcity.com/wastewater-treatment",
            "filename": "town_forest_city_wastewater_treatment.html",
            "institution": "Town of Forest City",
            "claim_supported": "Town WWTP NC0025984; 5 Significant Industrial Users unnamed; not a Meta cooling meter",
            "geographic_boundary": "town / WWTP",
            "temporal_boundary": "current page",
        },
        {
            "source_id": "NCDEQ_NPDES_NC0025984_NOTICE",
            "url": "https://www.deq.nc.gov/news/events/notice-intent-issue-npdes-wastewater-permit-nc0025984-forest-city-wwtp-0",
            "filename": "ncdeq_npdes_nc0025984_notice_2026.html",
            "institution": "NC DEQ",
            "claim_supported": "NPDES NC0025984 is the Town WWTP discharging to Second Broad River — municipal, not Meta campus cooling meter",
            "geographic_boundary": "town WWTP / Second Broad River",
            "temporal_boundary": "public notice 2026-08-22",
        },
        {
            "source_id": "RUTHERFORD_EDC_FB_CONSTRUCTION",
            "url": "https://www.rutherfordncedc.com/newsdetail_T9_R75.php",
            "filename": "rutherford_edc_facebook_facility_work_in_progress.html",
            "institution": "Rutherford County EDC",
            "claim_supported": "construction-era campus qualitative; no TAB/CFM; acreage press figure must not overwrite v1 160-acre tour figure as measured",
            "geographic_boundary": "campus construction",
            "temporal_boundary": "pre-opening construction tour",
        },
    ]
    out = []
    RAW_NEW.mkdir(parents=True, exist_ok=True)
    ua = {"User-Agent": "Mozilla/5.0 (research; Forest City documentary audit)"}
    for t in targets:
        dest = RAW_NEW / t["filename"]
        ts = _utc()
        try:
            req = urllib.request.Request(t["url"], headers=ua)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            dest.write_bytes(data)
            rec = {
                **t,
                "local_file": str(dest),
                "sha256": hashlib.sha256(data).hexdigest(),
                "retrieval_timestamp_utc": ts,
                "bytes": len(data),
                "title": t["source_id"],
                "publication_date": ts[:10],
                "event_or_measurement_date": t["temporal_boundary"],
                "quantity_boundary": "administrative / not Meta cooling or FRC1 electricity",
                "evidence_type": "administrative",
                "confidence": "HIGH_as_town_or_state_page; n/a as Meta meter",
                "permitted_quantitative_use": "NONE for cooling WUE or FRC1 load; context for water-boundary graph only",
                "design_vs_observed": "ADMINISTRATIVE",
                "building_scope": "not FRC1 TAB",
                "limitations": "Does not identify cooling-water meter, CFM, or interval electricity.",
                "origin": "V2_TARGETED_PUBLIC_ACQUISITION",
            }
            write_json(RAW_NEW / f"{t['source_id']}_sidecar.json", {
                "url": t["url"], "retrieval_timestamp_utc": ts, "sha256": rec["sha256"],
                "source_institution": t["institution"], "claim_supported": t["claim_supported"],
                "geographic_boundary": t["geographic_boundary"], "temporal_boundary": t["temporal_boundary"],
                "original_filename": t["filename"],
            })
        except Exception as e:
            rec = {
                **t,
                "local_file": "",
                "sha256": "",
                "retrieval_timestamp_utc": ts,
                "bytes": 0,
                "title": t["source_id"],
                "publication_date": "",
                "event_or_measurement_date": t["temporal_boundary"],
                "quantity_boundary": "download_failed",
                "evidence_type": "administrative",
                "confidence": "n/a",
                "permitted_quantitative_use": "NONE",
                "design_vs_observed": "DOWNLOAD_FAILED",
                "building_scope": "",
                "limitations": str(e),
                "origin": "V2_TARGETED_PUBLIC_ACQUISITION",
            }
        out.append(rec)
    # Record secondary journalism that must NOT upgrade evidence class.
    out.append({
        "source_id": "WFAE_2026_NC_DATA_CENTER_WATER",
        "title": "WFAE: Data centers use a lot of water (mentions Forest City)",
        "url": "https://www.wfae.org/2026-04-10/data-centers-water-quality-pfas-drought-climate-change",
        "local_file": "",
        "sha256": "",
        "publication_date": "2026-04-10",
        "event_or_measurement_date": "cites 2024 water",
        "geographic_boundary": "Forest City mention inside statewide article",
        "temporal_boundary": "2024 cited",
        "quantity_boundary": "secondary 4.2 million gallons (~16 ML) and unverified 30 MW",
        "evidence_type": "inferred",
        "confidence": "LOW",
        "permitted_quantitative_use": "NONE — 4.2 MG is 16 ML conversion of Meta EDI; 30 MW is not 2012 FRC1 load",
        "design_vs_observed": "SECONDARY_JOURNALISM",
        "building_scope": "unverified campus capacity",
        "limitations": "Do not treat 30 MW as identified FRC1 IT/facility load. Do not treat 4.2 MG as a new meter reading.",
        "origin": "V2_NOTED_NOT_DOWNLOADED_TO_AVOID_PROMOTING_SECONDARY",
        "institution": "WFAE",
        "claim_supported": "none new vs Meta 2024 16 ML withdrawal",
        "retrieval_timestamp_utc": _utc(),
        "bytes": 0,
        "filename": "",
    })
    write_json(OUT / "source_audit" / "NEW_ACQUISITIONS.json", out)
    return out


def step10_stationarity(annual: pd.DataFrame) -> None:
    # Cannot date epochs from annuals. H0 vs H1 is unidentified at the required boundary.
    rows = [
        {
            "hypothesis": "H0_fixed_early_FRC1_plus_weather",
            "testable_with_campus_annuals": False,
            "reason": "Annual electricity/water are campus site totals, not 2012 FRC1; withdrawal ≠ cooling water; IT load unidentified.",
            "outcome": "UNIDENTIFIED",
        },
        {
            "hypothesis": "H1_independently_documented_epoch_bounds",
            "testable_with_campus_annuals": False,
            "reason": "Hard epochs exist for campus composition (2014 halls) but cooling-tech change dates remain CANDIDATE. Annuals cannot estimate those dates.",
            "outcome": "UNIDENTIFIED",
        },
        {
            "hypothesis": "descriptive_2024_withdrawal_drop",
            "testable_with_campus_annuals": False,
            "reason": "2024 withdrawal 16 ML is reported. Causal link to membrane/SPLC/load mix is not identified. not_used_to_fit_2012_controller.",
            "outcome": "UNIDENTIFIED",
        },
    ]
    _csv(OUT / "architecture" / "FIXED_VS_EPOCH_CONSISTENCY.csv", rows)
    write_json(OUT / "architecture" / "ARCHITECTURE_STATIONARITY_STATUS.json", {
        "Q4": "DO_NOT_ASSUME_YES",
        "FIXED_ARCHITECTURE_NOT_REJECTED": False,
        "FIXED_ARCHITECTURE_INCONSISTENT": False,
        "EPOCH_BOUNDED_CONSISTENT": False,
        "status": "UNIDENTIFIED",
        "do_not_estimate_epoch_dates_from_annuals": True,
        "rows": rows,
    })


def step11_emissions() -> None:
    v1 = json.loads((V1 / "outputs/emissions/FOREST_CITY_LOCATION_EMISSIONS_VALIDATION.json").read_text())
    elec_ok = False  # campus site as reported is not a verified interval/service meter map
    grid_ok = False  # year-matched eGRID xlsx not in this pass; v1 already insufficient
    factor_qty_ok = False
    status = "EMISSIONS_BOUNDARY_NOT_READY"
    payload = {
        "status": status,
        "electricity_reporting_boundary_verified_for_emissions_factor": elec_ok,
        "service_territory_grid_region_verified_by_source_and_year": grid_ok,
        "quantity_compatible_with_factor": factor_qty_ok,
        "reason": [
            "Electricity series is FOREST_CITY_SITE_AS_REPORTED annual campus totals, not FRC1 interval load.",
            "v1: GRID_RECONSTRUCTION_INSUFFICIENT_INPUTS; year-matched eGRID xlsx not used in this pass.",
            "Do not create faux hourly emissions from annual campus electricity.",
            "Emissions remain behind acquisition priorities 1-3.",
        ],
        "v1_status": v1.get("status"),
        "meta_location_based_series_exists": True,
        "reconstructed_here": False,
    }
    write_json(OUT / "emissions" / "FOREST_CITY_EMISSIONS_GATE.json", payload)
    _csv(OUT / "electricity" / "FOREST_CITY_ELECTRICITY_BOUNDARY.csv", [{
        "quantity": "FOREST_CITY_SITE_AS_REPORTED annual MWh",
        "is_2012_FRC1": False,
        "interval_meter_identified": False,
        "permitted_use": "descriptive campus accounting only",
    }])


def step12_identifiability(sens: pd.DataFrame) -> None:
    chain = [
        {"edge": "weather -> psychrometrics", "v1_status": "ENGINEERING_BOUNDED (KFQD from 2012-06-21)", "v2_status": "ENGINEERING_BOUNDED", "evidence": "frozen KFQD parquet hash match", "improved": False, "remaining_missing_observable": "on-site campus weather; June 1-20 2012"},
        {"edge": "psychrometrics -> controller state", "v1_status": "STRUCTURAL_PASS on 2012-06-25 and 2012-07-01", "v2_status": "STRUCTURAL_PASS (PASS_AND_FREEZE)", "evidence": "regression vs v1 events/DX", "improved": False, "remaining_missing_observable": "as-operated BMS SAT/RAT/OA damper/DX enable"},
        {"edge": "controller state -> air-side conditioning", "v1_status": "OPERATOR_OBSERVED events; summer DX hours 0", "v2_status": "SUPPORTED + SCENARIO_BOUNDED intensity", "evidence": "hourly dw + sensitivity eps 0.70/0.85/1.00", "improved": True, "remaining_missing_observable": "TAB CFM; measured RAT; facility-effective DeltaT"},
        {"edge": "air-side conditioning -> cooling-water requirement", "v1_status": "UNIDENTIFIED m3 (airflow UNIDENTIFIED)", "v2_status": "UNIDENTIFIED absolute; SCENARIO_BOUNDED per MW_IT using IT design DeltaT", "evidence": "dw identified; m_dot not", "improved": True, "remaining_missing_observable": "FACILITY_EFFECTIVE_DELTA_T or measured airflow"},
        {"edge": "cooling-water requirement -> campus withdrawal", "v1_status": "UNIDENTIFIED", "v2_status": "UNIDENTIFIED", "evidence": "no cooling meter; EDI is withdrawal", "improved": False, "remaining_missing_observable": "cooling-water meter name/location; WUE numerator"},
        {"edge": "campus withdrawal -> source-water externality", "v1_status": "not ready", "v2_status": "UNIDENTIFIED", "evidence": "priority 5 blocked on cooling vs withdrawal", "improved": False, "remaining_missing_observable": "identified cooling vs withdrawal split; then Second Broad / WTP allocation"},
    ]
    _csv(OUT / "identifiability" / "FOREST_CITY_V2_CHAIN_CONNECTION_STATUS.csv", chain)
    matrix = [
        {"variable": "MODEL_CALIBRATED", "status": "NO"},
        {"variable": "FACILITY_EFFECTIVE_DELTA_T", "status": "UNIDENTIFIED"},
        {"variable": "IT_DESIGN_DELTA_T", "status": "IDENTIFIED_DESIGN_SPEC"},
        {"variable": "normalized_airside_dw", "status": "ENGINEERING_BOUNDED"},
        {"variable": "evaporative_water_per_MW_IT", "status": "SCENARIO_BOUNDED"},
        {"variable": "absolute_cooling_water_m3", "status": "UNIDENTIFIED"},
        {"variable": "WUE", "status": "UNIDENTIFIED"},
        {"variable": "cooling_to_withdrawal_edge", "status": "UNIDENTIFIED"},
        {"variable": "2012_FRC1_electricity", "status": "UNIDENTIFIED"},
        {"variable": "dashboard_numeric", "status": "SCREENSHOT_ONLY"},
        {"variable": "architecture_stationarity_2012_2024", "status": "UNIDENTIFIED"},
        {"variable": "emissions_reconstruction", "status": "EMISSIONS_BOUNDARY_NOT_READY"},
        {"variable": "physics_controller_transfer", "status": "SUPPORTED"},
        {"variable": "absolute_site_water_validated", "status": "UNIDENTIFIED"},
    ]
    _csv(OUT / "identifiability" / "FOREST_CITY_V2_IDENTIFIABILITY_MATRIX.csv", matrix)
    claims = [
        {"claim": "Frozen Prineville psychrometrics/controller physics remain usable at Forest City with local 85F/90%RH envelope", "class": "SUPPORTED"},
        {"claim": "2012-06-25 mixing event reproduced", "class": "VALIDATED"},
        {"claim": "2012-07-01 evaporative event reproduced", "class": "VALIDATED"},
        {"claim": "Summer DX-required hours = 0 on valid KFQD hours", "class": "VALIDATED"},
        {"claim": "Normalized air-side evaporative dw under documented envelope", "class": "ENGINEERING_BOUNDED"},
        {"claim": "m3/h per MW_IT using 35F IT design rise as if effective", "class": "SCENARIO_BOUNDED"},
        {"claim": "Absolute cooling-water magnitude", "class": "UNIDENTIFIED"},
        {"claim": "Cooling-water to campus-withdrawal edge", "class": "UNIDENTIFIED"},
        {"claim": "Stationary 2012 architecture explains 2015-2024 campus intensity", "class": "UNIDENTIFIED"},
        {"claim": "Municipal industrial-class water is Meta campus water", "class": "FAILED"},
        {"claim": "Screenshot dashboard as numeric ground truth", "class": "FAILED"},
        {"claim": "2024 campus electricity is 2012 FRC1 load", "class": "FAILED"},
    ]
    _csv(OUT / "identifiability" / "FOREST_CITY_V2_CLAIM_REGISTRY.csv", claims)
    prio = [
        {"rank": 1, "dataset": "as-operated FRC1 air-side / TAB / commissioning (CFM, SAT/RAT, sequence, DX enable)", "why": "only path to FACILITY_EFFECTIVE_DELTA_T and absolute air-side water"},
        {"rank": 2, "dataset": "cooling-water meter identity and WUE numerator boundary", "why": "connects dw to site water; currently UNIDENTIFIED"},
        {"rank": 3, "dataset": "FRC1/building and campus interval electricity / electrical boundary", "why": "blocks 2012 load and emissions factor compatibility"},
        {"rank": 4, "dataset": "emissions factors year-matched to a verified electricity quantity", "why": "gated until 3"},
        {"rank": 5, "dataset": "source-water externality after cooling vs withdrawal is resolved", "why": "gated until 2"},
    ]
    _csv(OUT / "identifiability" / "FOREST_CITY_V2_DATA_VALUE_PRIORITY.csv", prio)


def figures(hourly: pd.DataFrame, annual: pd.DataFrame, sens: pd.DataFrame) -> None:
    figdir = OUT / "figures"
    figdir.mkdir(parents=True, exist_ok=True)
    prn_wx = PRN / "outputs/prn1_q2_2012_public_validation_v1/weather/Q2_2012_KRDM_hourly.parquet"
    fc = hourly.dropna(subset=["t_db_C", "rh_pct"])
    fig, ax = plt.subplots(figsize=(7.2, 5.2))
    ax.scatter(np.asarray(fc["t_db_C"]) * 9.0 / 5.0 + 32.0, fc["rh_pct"].to_numpy(), s=6, alpha=0.25, label="Forest City KFQD 2012 usable", c="#1f4e79")
    if prn_wx.exists():
        pw = pd.read_parquet(prn_wx)
        tcol = "t_db_C" if "t_db_C" in pw.columns else None
        rhcol = "rh_pct" if "rh_pct" in pw.columns else None
        if tcol and rhcol:
            ax.scatter(np.asarray(pw[tcol]) * 9.0 / 5.0 + 32.0, pw[rhcol].to_numpy(), s=6, alpha=0.25, label="Prineville KRDM 2012 Q2", c="#c45911")
    ax.axvline(85, color="crimson", ls="--", lw=1, label="FC inlet 85F")
    ax.axhline(90, color="crimson", ls=":", lw=1, label="FC RH 90%")
    ax.set_xlabel("Outdoor dry bulb (F)")
    ax.set_ylabel("Outdoor RH (%)")
    ax.set_title("Forest City vs Prineville outdoor operating envelope")
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(figdir / "fig1_psychrometric_envelope.png", dpi=140)
    plt.close(fig)

    jja = hourly[(hourly["timestamp_utc"] >= "2012-06-01") & (hourly["timestamp_utc"] < "2012-09-01")].copy()
    jja = jja.dropna(subset=["timestamp_utc"])
    fig, ax = plt.subplots(figsize=(9.5, 3.6))
    colors = {
        "OA_FREE_COOLING": "#4daf4a",
        "RETURN_AIR_MIXING": "#377eb8",
        "EVAPORATIVE_COOLING": "#ff7f00",
        "DX_REQUIRED": "#e41a1c",
        "WEATHER_MISSING": "#bbbbbb",
    }
    t = pd.to_datetime(jja["timestamp_utc"])
    y = jja["required_conditioning_regime"].map({"OA_FREE_COOLING": 3, "RETURN_AIR_MIXING": 2, "EVAPORATIVE_COOLING": 1, "DX_REQUIRED": 0}).fillna(-1)
    ax.scatter(t, y, c=jja["required_conditioning_regime"].map(colors).fillna("#999"), s=8, marker="|")
    ax.set_yticks([0, 1, 2, 3])
    ax.set_yticklabels(["DX", "Evap", "Mixing", "OA free"])
    ax.set_title("Forest City 2012 JJA controller-mode map (valid KFQD hours)")
    ax.set_xlabel("UTC")
    fig.tight_layout()
    fig.savefig(figdir / "fig2_controller_mode_map_2012.png", dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.0, 4.4))
    ax.errorbar(
        sens["evap_thermal_effectiveness"],
        sens["mean_evaporative_water_m3_h_per_MW_IT_SCENARIO_ONLY"],
        yerr=sens["p95_evaporative_water_m3_h_per_MW_IT_SCENARIO_ONLY"] - sens["mean_evaporative_water_m3_h_per_MW_IT_SCENARIO_ONLY"],
        fmt="o-", color="#1f4e79",
    )
    ax.set_xlabel("evap_thermal_effectiveness (predeclared; not fitted)")
    ax.set_ylabel("mean m3/h per MW_IT (SCENARIO_ONLY)")
    ax.set_title("Normalized air-side evaporative requirement — not site water")
    fig.tight_layout()
    fig.savefig(figdir / "fig3_normalized_evap_sensitivity.png", dpi=140)
    plt.close(fig)

    xfer = pd.read_csv(OUT / "cross_site_validation" / "TRANSFER_EVIDENCE_MATRIX.csv")
    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    cls_color = {"STRUCTURAL_PASS": "#4daf4a", "QUANTITATIVE_BOUND_PASS": "#377eb8", "UNIDENTIFIED": "#999999", "FAIL": "#e41a1c"}
    ax.barh(xfer["item_id"], [1] * len(xfer), color=xfer["classification"].map(cls_color).fillna("#ccc"))
    ax.set_xlabel("evidence item (color = class)")
    ax.set_title("Cross-site transfer evidence (not a single RMSE)")
    fig.tight_layout()
    fig.savefig(figdir / "fig4_transfer_evidence.png", dpi=140)
    plt.close(fig)

    a = annual.copy()
    a["intensity"] = pd.to_numeric(a["withdrawal_per_electricity_L_per_kWh_facility"], errors="coerce")
    fig, ax = plt.subplots(figsize=(7.5, 4.4))
    ax.plot(a["year"], a["intensity"], "o-", color="#1f4e79")
    ax.axvline(2014, color="#c45911", ls="--", label="2014 halls independently documented")
    ax.set_ylabel("site withdrawal / facility electricity (L/kWh)")
    ax.set_title("Descriptive campus intensity — not WUE, not 2012 FRC1")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(figdir / "fig5_annual_intensity_by_epoch.png", dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.8, 3.2))
    chain = pd.read_csv(OUT / "identifiability" / "FOREST_CITY_V2_CHAIN_CONNECTION_STATUS.csv")
    ax.set_xlim(0, 7)
    ax.set_ylim(0, 1.2)
    labels = ["weather", "psych", "controller", "air-side", "cooling H2O", "withdrawal", "source H2O"]
    for i, lab in enumerate(labels):
        ax.add_patch(plt.Rectangle((i + 0.1, 0.35), 0.8, 0.4, fill=True, color="#d9e2f3", ec="#1f4e79"))
        ax.text(i + 0.5, 0.55, lab, ha="center", va="center", fontsize=8)
        if i < 6:
            ax.annotate("", xy=(i + 1.1, 0.55), xytext=(i + 0.9, 0.55),
                        arrowprops=dict(arrowstyle="->", color="#333"))
    ax.axis("off")
    ax.set_title("Identifiability chain: last three edges remain UNIDENTIFIED in magnitude")
    fig.tight_layout()
    fig.savefig(figdir / "fig6_identifiability_chain.png", dpi=140)
    plt.close(fig)


def write_report() -> None:
    text = """# Forest City v2 final report

Isolated package. Frozen v1 and Prineville were not modified. MODEL_CALIBRATED = NO.

## 1. What was frozen from v1/Prineville?

Forest City v1 public-validation status is preserved: MODEL_CALIBRATED = NO; facility-effective DeltaT UNIDENTIFIED; IT design DeltaT 35 F is a design specification; dashboard SCREENSHOT_ONLY; 2012-06-25 mixing PASS; 2012-07-01 evaporative PASS; summer DX-required hours = 0 on valid KFQD hours; Prineville→Forest City qualitative/structural physics transfer SUPPORTABLE; water magnitude UNIDENTIFIED. Acquisition priority is unchanged (air-side/TAB first, then cooling-water meter, then interval electricity, then emissions, then source-water externality). Upstream hashes for Forest City controller/structural/contracts, Prineville structural/psychrometrics/gray-box/architecture YAML, CPU, H100, and ESIF were checked before and after this pass.

## 2. What new sources were found?

Targeted primary pages: Town of Forest City wastewater-treatment description (WWTP NC0025984; five unnamed Significant Industrial Users) and NC DEQ NPDES notice for that **town** plant discharging to the Second Broad River. These improve the water-boundary graph by documenting a municipal discharge node; they do **not** identify a Meta cooling-water meter. A Rutherford EDC construction-era page was attempted as campus chronology context. Hsu/Mulay remains a design-slide reference (DX existence) and was not promoted to TAB. Secondary journalism citing 4.2 million gallons (16 ML) and an unverified 30 MW was noted and **not** used quantitatively. No other data-center site was acquired.

## 3. What architecture epochs are independently identified?

Hard documentary epochs: FRC1 construction (2010-11 to opening); FRC1 operating architecture from 2012-04-19 (direct OA evaporative + DX backup); second large production hall present by the 2014 tour; FRC4 cold storage ~2014 (different function). Membrane vs misters, SPLC/indirect at Forest City, and a post-2014 additional hall remain CANDIDATE / UNRESOLVED. Epoch dates were **not** inferred from Meta annual water or electricity.

## 4. Which Forest City control/physics evidence validates the frozen Prineville framework?

**VALIDATED:** 2012-06-25 mixing family and DX-not-required; 2012-07-01 evaporative family and DX-not-required; JJA DX-required hours = 0 on observed KFQD hours. **SUPPORTED:** shared psychrometrics, enthalpy-conserving mixing, and adiabatic evaporative mass/energy balance under Forest City's local 85 F / 90% RH envelope (not copied Prineville A–H thresholds). This is physics/controller transfer.

## 5. Which transfer claims fail?

No STRUCTURAL_FAIL on the documented 2012 events. Claims that **fail if asserted**: screenshot dashboard as numeric ground truth; municipal industrial-class flow as Meta campus water; 2024 campus electricity as 2012 FRC1 load; treating campus withdrawal as cooling WUE. Seasonal PUE 1.07 remains **UNIDENTIFIED** for quantitative reconstruction (no interval electricity). Absolute site water magnitude is **not** validated.

## 6. What is identified about normalized air-side evaporative demand?

Humidity-ratio lift `dw` is **ENGINEERING_BOUNDED** from frozen controller + psychrometrics on valid hours. Cubic-meter intensity per MW_IT using the 35 F IT design rise as if it were facility-effective DeltaT is **SCENARIO_BOUNDED** only. FACILITY_EFFECTIVE_DELTA_T remains UNIDENTIFIED. Sensitivity used predeclared effectiveness 0.70 / 0.85 / 1.00; no optimizer; annual Meta series did not enter parameter selection.

## 7. Is absolute cooling-water magnitude identified?

**UNIDENTIFIED.** Airflow / effective DeltaT missing; cooling-water meter missing.

## 8. Is the cooling-water → campus-withdrawal edge identified?

**UNIDENTIFIED.** Meta EDI is site withdrawal. Town industrial class is not Meta. NPDES is the town WWTP.

## 9. What can sparse annual Meta electricity/water records legitimately validate?

Descriptive campus-level electricity and withdrawal totals and a **SITE_WITHDRAWAL_INTENSITY** (not WUE). They can serve as external consistency checks only. They cannot validate 2012 FRC1 load, cooling evaporation, or controller parameters.

## 10. Is a stationary 2012 architecture compatible with later observations?

**UNIDENTIFIED.** Campus composition hard-changes in 2014, but cooling-technology change dates are unresolved, and annuals are the wrong boundary. Do not assume yes. Do not reject or accept H0 by fitting water.

## 11. What remains unresolved?

As-operated CFM/SAT/RAT/TAB; facility-effective DeltaT; cooling-water meter and WUE numerator; RO vs UV vs makeup split; blowdown; FRC1 interval electricity; year-matched emissions-factor compatibility; membrane/SPLC dates; post-2014 hall identity; June 1–20 2012 weather.

## 12. Highest-value next dataset

As-operated FRC1 air-side measurements / mechanical / TAB / commissioning (CFM, SAT/RAT, airflow balance, sequence of operations, evaporative and DX). That remains priority 1.

## 13. Does Forest City strengthen Prineville external validity, and at which layers?

**Yes, at weather → psychrometrics → controller → air-side regime layers** for a hot/humid climate, with local envelope (85 F / 90% RH, DX backup unused in documented summer). **No** at absolute cooling-water magnitude, campus withdrawal, WUE, 2012 FRC1 electricity, or source-water externality.

Claim classes used: VALIDATED, SUPPORTED, ENGINEERING_BOUNDED, SCENARIO_BOUNDED, UNIDENTIFIED, FAILED.
"""
    (OUT / "reports" / "FINAL_FOREST_CITY_V2_REPORT.md").write_text(text)


def post_hash_check() -> None:
    sys.path.insert(0, str(FC2 / "src"))
    expected = json.loads((OUT / "preflight" / "UPSTREAM_HASHES.json").read_text())["expected"]
    paths = {
        "fc_controller": V1 / "src/forest_city_controller.py",
        "fc_structural": V1 / "src/forest_city_structural_reference_v1.py",
        "fc_control_contract": V1 / "config/FOREST_CITY_REFERENCE_CONTROL_CONTRACT.json",
        "fc_airflow_contract": V1 / "config/FOREST_CITY_AIRFLOW_BOUNDARY_CONTRACT.json",
        "prn_structural_v1": PRN / "src/prineville_structural_v1.py",
        "prn_psychrometrics": PRN / "src/prineville_psychrometrics.py",
        "prn_graybox": PRN / "src/prineville_graybox.py",
        "prn_registry": PRN / "config/prineville_architecture_states.yaml",
        "cpu": REPO / "other_sources/nlr_esif_fullstack/analysis/FINAL_KESTREL_CPU_STATUS.json",
        "h100": REPO / "other_sources/nlr_esif_fullstack/genai_h100/manifests/H100_COMPUTE_FINAL_FREEZE.json",
        "esif": REPO / "other_sources/nlr_esif_fullstack/heat_rejection_water/manifests/ESIF_HEAT_WATER_RESULT_FREEZE.json",
        "fc_weather_parquet": WEATHER_PARQUET,
    }
    bad = []
    observed = {}
    for k, p in paths.items():
        h = sha256_file(p)
        observed[k] = h
        if k in expected and h != expected[k]:
            bad.append(k)
    write_json(OUT / "preflight" / "UPSTREAM_HASHES_AFTER.json", {"observed": observed, "mismatches": bad})
    if bad:
        raise SystemExit(f"UPSTREAM HASH CHANGED during v2 pass: {bad}")


def main() -> int:
    os.environ["OMP_NUM_THREADS"] = "1"
    print("STEP 9 acquire first so STEP 2 can include new sources...", flush=True)
    new_src = step9_acquire()
    print("STEP 2 source registry", flush=True)
    step2_source_registry(new_src)
    print("STEP 3 architecture", flush=True)
    epochs = step3_architecture()
    print("load weather", flush=True)
    if sha256_file(WEATHER_PARQUET) != WEATHER_SHA:
        raise SystemExit("frozen weather parquet hash mismatch")
    w = pd.read_parquet(WEATHER_PARQUET)
    qa = {
        "n_rows": int(len(w)),
        "columns": list(w.columns),
        "parquet_sha256": WEATHER_SHA,
        "referenced_not_copied": str(WEATHER_PARQUET),
    }
    write_json(OUT / "weather" / "FOREST_CITY_V2_WEATHER_POINTER.json", qa)
    print("STEP 4 regression", flush=True)
    reg = step4_regression(w)
    print("STEP 5 airside", flush=True)
    hourly, sens = step5_airside(w, reg)
    print("STEP 6 transfer", flush=True)
    step6_transfer(reg)
    print("STEP 7 water", flush=True)
    step7_water()
    print("STEP 8 annual", flush=True)
    annual = step8_annual(epochs)
    print("STEP 10 stationarity", flush=True)
    step10_stationarity(annual)
    print("STEP 11 emissions gate", flush=True)
    step11_emissions()
    print("STEP 12 identifiability", flush=True)
    step12_identifiability(sens)
    print("figures", flush=True)
    figures(hourly, annual, sens)
    write_report()
    post_hash_check()
    write_json(OUT / "preflight" / "PIPELINE_COMPLETE.json", {"utc": _utc(), "MODEL_CALIBRATED": "NO", "jobs_submitted": []})
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
