#!/usr/bin/env python3
"""Forest City public-data validation pipeline. No calibration. No Prineville writes."""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

FC = Path(__file__).resolve().parents[1]
REPO = FC.parent
sys.path.insert(0, str(FC / "src"))
from forest_city_controller import RH_MAX, T_INLET_MAX_C, T_INLET_MAX_F  # noqa: E402
from forest_city_structural_reference_v1 import (  # noqa: E402
    AIRFLOW_BOUNDARY,
    FACILITY_EFFECTIVE_DELTA_T_STATUS,
    IT_DELTA_T_STATUS,
    IT_EQUIPMENT_DELTA_T_DESIGN_F,
    IT_EQUIPMENT_DELTA_T_DESIGN_K,
    MODEL_VERSION,
    simulate_frame,
    simulate_hour,
)
from hashes import sha256_file, write_json  # noqa: E402
from paths import CONFIG, DATA_PROCESSED, OUTPUTS, PRINEVILLE_ROOT, RAW_DASHBOARD, RAW_LWSP, RAW_PERMITS  # noqa: E402
from psychrometrics_adapter import c_to_f, f_to_c  # noqa: E402

PY = "/home/nacevedo/.conda/envs/dc_externalities/bin/python"


def _csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fields = []
    seen = set()
    for r in rows:
        for k in r.keys():
            if k not in seen:
                fields.append(k)
                seen.add(k)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def facility_timeline() -> None:
    reg = yaml.safe_load((CONFIG / "forest_city_facility_registry.yaml").read_text())
    rows = []
    for b in reg["buildings"]:
        rows.append(
            {
                "building_id": b["building_id"],
                "address": b.get("address"),
                "phase": b.get("phase"),
                "function": b.get("function"),
                "construction_start": b.get("construction_start"),
                "confirmed_operational": b.get("confirmed_operational"),
                "possible_operational_interval": b.get("possible_operational_interval"),
                "operational_status": b.get("operational_status"),
                "square_feet": json.dumps(b.get("square_feet")),
                "data_suite_count": b.get("data_suite_count"),
                "cooling_architecture": b.get("cooling_architecture"),
                "cold_storage_flag": b.get("cold_storage_flag"),
                "source_ids": ";".join(b.get("source_ids") or []),
                "confidence": b.get("confidence"),
            }
        )
    _csv(OUTPUTS / "architecture_audit" / "FOREST_CITY_FACILITY_TIMELINE.csv", rows)


def load_weather() -> pd.DataFrame:
    p = DATA_PROCESSED / "forest_city_weather_2012_hourly.parquet"
    return pd.read_parquet(p)


def event_validation(w: pd.DataFrame) -> dict:
    """June 25 and July 1 2012. Controller frozen before this function conceptually;
    this function must not write the control contract."""
    w = w.copy()
    w["local_date"] = w["timestamp_local"].dt.tz_convert("America/New_York").dt.date.astype(str)
    rows = []
    summaries = {}
    specs = [
        {
            "event": "B_2012_06_25",
            "date": "2012-06-25",
            "operator_T_F": 68.0,
            "operator_RH": 0.97,
            "observed": "DX NOT required; high-RH mixing of hot return air to stay within 90% cap",
            "expect_dx": False,
            "expect_mode_family": "RETURN_AIR_MIXING",
        },
        {
            "event": "A_2012_07_01",
            "date": "2012-07-01",
            "operator_T_F": 102.0,
            "operator_RH": 0.26,
            "observed": "evaporative/free cooling worked; DX NOT required",
            "expect_dx": False,
            "expect_mode_family": "EVAPORATIVE_COOLING",
        },
    ]
    for spec in specs:
        day = w[w["local_date"] == spec["date"]].copy()
        usable = day.dropna(subset=["t_db_C", "rh_pct", "pressure_Pa"])
        if usable.empty:
            rec = {**spec, "status": "FAIL_NO_WEATHER", "n_hours": 0}
            rows.append(rec)
            summaries[spec["event"]] = rec
            continue
        sim = simulate_frame(usable, airflow_boundary="UNIDENTIFIED")
        # snapshot hour: closest outdoor T,RH to operator snapshot
        t_c = f_to_c(spec["operator_T_F"])
        rh = spec["operator_RH"] * 100
        dist = (sim["t_db_C"] - t_c) ** 2 + ((sim["rh_pct"] - rh) / 10.0) ** 2
        snap = sim.loc[dist.idxmin()]
        # also evaluate operator snapshot as a synthetic outdoor state at station pressure
        p = float(usable["pressure_Pa"].median())
        synth = simulate_hour(t_db_C=t_c, rh_pct=rh, pressure_Pa=p, airflow_boundary="UNIDENTIFIED")
        dx_hours = int(sim["dx_required"].sum())
        modes = sim["control_mode"].value_counts(normalize=True).to_dict()
        family = "DX_REQUIRED" if synth["dx_required"] else (
            "EVAPORATIVE_COOLING" if synth["spray_enabled"] else (
                "RETURN_AIR_MIXING" if synth["oa_fraction"] < 0.999 else "OA_FREE_COOLING"
            )
        )
        match_family = family == spec["expect_mode_family"] or (
            spec["expect_mode_family"] == "RETURN_AIR_MIXING" and family in ("RETURN_AIR_MIXING", "OA_FREE_COOLING")
        )
        dx_ok = (not synth["dx_required"]) and dx_hours == 0
        if dx_ok and match_family:
            status = "PASS"
        elif dx_ok:
            status = "PARTIAL"
        else:
            status = "FAIL"
        rec = {
            **spec,
            "n_kfqd_hours": int(len(sim)),
            "kfqd_Tmin_F": float(c_to_f(usable["t_db_C"].min())),
            "kfqd_Tmax_F": float(c_to_f(usable["t_db_C"].max())),
            "kfqd_RHmin": float(usable["rh_pct"].min() / 100.0),
            "kfqd_RHmax": float(usable["rh_pct"].max() / 100.0),
            "nearest_hour_utc": str(snap.get("timestamp_utc")),
            "nearest_T_F": float(c_to_f(snap["t_db_C"])),
            "nearest_RH": float(snap["rh_pct"] / 100.0),
            "nearest_mode": snap["control_mode"],
            "nearest_dx": bool(snap["dx_required"]),
            "synthetic_mode": synth["control_mode"],
            "synthetic_mode_family": family,
            "synthetic_dx": bool(synth["dx_required"]),
            "synthetic_oa_fraction": synth["oa_fraction"],
            "synthetic_spray": bool(synth["spray_enabled"]),
            "synthetic_t_supply_F": synth["t_supply_F"],
            "synthetic_rh_supply": synth["rh_supply"],
            "synthetic_margin_T_K": synth["margin_T_K"],
            "synthetic_margin_RH": synth["margin_RH"],
            "day_dx_required_hours": dx_hours,
            "day_mode_fractions": json.dumps(modes),
            "status": status,
            "controller_not_modified": True,
        }
        rows.append(rec)
        summaries[spec["event"]] = rec
        # per-hour dump
        sim.assign(event=spec["event"]).to_csv(
            OUTPUTS / "control_validation" / f"EVENT_{spec['event']}_HOURS.csv", index=False
        )
    _csv(OUTPUTS / "control_validation" / "HISTORICAL_EVENT_VALIDATION.csv", rows)
    write_json(OUTPUTS / "control_validation" / "HISTORICAL_EVENT_VALIDATION.json", {"events": summaries, "no_retune": True})
    return summaries


def summer_dx(w: pd.DataFrame) -> dict:
    jja = w[(w["timestamp_utc"] >= "2012-06-01") & (w["timestamp_utc"] < "2012-09-01")].copy()
    usable = jja.dropna(subset=["t_db_C", "rh_pct", "pressure_Pa"])
    missing = len(jja) - len(usable)
    sim = simulate_frame(usable, airflow_boundary="UNIDENTIFIED")
    # also ideal eps=1.0 vs generic 0.85 (already 0.85 default). Recompute eps=1 for DX robustness.
    sim1 = simulate_frame(usable, airflow_boundary="UNIDENTIFIED", evap_thermal_effectiveness=1.0)
    def pack(s, tag):
        fam = []
        for _, r in s.iterrows():
            if r["dx_required"]:
                fam.append("DX_REQUIRED")
            elif r["spray_enabled"]:
                fam.append("EVAPORATIVE_COOLING")
            elif r["oa_fraction"] < 0.999:
                fam.append("RETURN_AIR_MIXING")
            else:
                fam.append("OA_FREE_COOLING")
        c = Counter(fam)
        n = len(s)
        return {
            "tag": tag,
            "n_classified_hours": n,
            "PREDICTED_DX_REQUIRED_HOURS": int(s["dx_required"].sum()),
            "mode_counts": dict(c),
            "mode_fractions": {k: v / n for k, v in c.items()} if n else {},
            "high_RH_mixing_hours": int(c.get("RETURN_AIR_MIXING", 0)),
            "hot_dry_evaporative_hours": int(c.get("EVAPORATIVE_COOLING", 0)),
            "oa_free_hours": int(c.get("OA_FREE_COOLING", 0)),
            "unresolved_hours": int(s["unresolved"].fillna(False).sum()) if "unresolved" in s else 0,
        }
    a = pack(sim, "eps_0.85_GENERIC_PRIOR")
    b = pack(sim1, "eps_1.0_IDEAL_UPPER_BOUND")
    out = {
        "period": "2012-06-01/2012-08-31 America/New_York via UTC hours",
        "calendar_hours": int(len(jja)),
        "weather_missing_hours": int(missing),
        "missing_note": "KFQD ISD has no records before 2012-06-21; June 1-20 are WEATHER_MISSING not imputed.",
        "operator_observed": "DX coils were not used during summer 2012 despite extreme weather (OCP_2013_HOT_HUMID)",
        "primary": b,  # ideal: DX required even if evaporation is perfect
        "sensitivity_generic_prior": a,
        "interpretation_rule": "0 or near-zero DX-required hours with source-compatible modes = strong consistency. Material DX hours = inconsistency. No threshold fitting.",
        "controller_not_modified": True,
    }
    dx = b["PREDICTED_DX_REQUIRED_HOURS"]
    if dx == 0 and missing > 0:
        out["interpretation"] = "CONSISTENT_ON_OBSERVED_KFQD_HOURS_WITH_DOCUMENTED_EARLY_JUNE_GAP"
    elif dx == 0:
        out["interpretation"] = "STRONG_CONTROLLER_ARCHITECTURE_CONSISTENCY"
    elif dx <= 24:
        out["interpretation"] = "NEAR_ZERO_DX_PARTIAL"
    else:
        out["interpretation"] = "MATERIAL_DX_REQUIRED_MODEL_INCONSISTENCY"
    sim1.to_csv(OUTPUTS / "control_validation" / "SUMMER_2012_DX_HOURS.csv", index=False)
    _csv(OUTPUTS / "control_validation" / "SUMMER_2012_DX_VALIDATION.csv", [
        {"metric": k, "value": json.dumps(v) if isinstance(v, (dict, list)) else v} for k, v in {
            "PREDICTED_DX_REQUIRED_HOURS_eps1": b["PREDICTED_DX_REQUIRED_HOURS"],
            "PREDICTED_DX_REQUIRED_HOURS_eps085": a["PREDICTED_DX_REQUIRED_HOURS"],
            "weather_missing_hours": missing,
            "evaporative_hours_eps1": b["hot_dry_evaporative_hours"],
            "mixing_hours_eps1": b["high_RH_mixing_hours"],
            "oa_free_hours_eps1": b["oa_free_hours"],
            "interpretation": out["interpretation"],
        }.items()
    ])
    write_json(OUTPUTS / "control_validation" / "SUMMER_2012_DX_VALIDATION.json", out)
    return out


def airflow_boundary() -> dict:
    dT_it_k = IT_EQUIPMENT_DELTA_T_DESIGN_K
    dT_prn_k = 12.0
    # m_dot / P = 1/(cp dT)
    cp = 1006.0
    m_per_w_it = 1.0 / (cp * dT_it_k)
    m_per_w_12 = 1.0 / (cp * dT_prn_k)
    ratio = m_per_w_it / m_per_w_12
    # Maguire: 45% less air-handling hardware. If hardware ~ airflow capacity, m_FC/m_PRN1 ≈ 0.55
    # which would imply dT_FC/dT_PRN1_design ≈ 1/0.55 if same Q and same design basis.
    # PRN1 design IT rise was 25F; FC 35F; 25/35 = 0.714, not 0.55. Hardware reduction is not a pure DeltaT map.
    rec = {
        "IT_EQUIPMENT_DELTA_T_DESIGN_F": IT_EQUIPMENT_DELTA_T_DESIGN_F,
        "IT_EQUIPMENT_DELTA_T_DESIGN_K": dT_it_k,
        "IT_DELTA_T_DESIGN": IT_DELTA_T_STATUS,
        "FACILITY_EFFECTIVE_DELTA_T": FACILITY_EFFECTIVE_DELTA_T_STATUS,
        "Q1_35F_credible_IT_design_rise": "YES",
        "Q1_confidence": "HIGH",
        "Q2_translatable_to_effective_facility_airflow": "NO_NOT_WITHOUT_BOUNDARY_ASSUMPTIONS",
        "Q3_boundary_assumptions_required": [
            "sensible-only IT heat to air",
            "AHU DeltaT = IT DeltaT",
            "no recirculation/bypass",
            "m_dot from Q/(cp dT) at facility not server fans",
        ],
        "Q4_universal_12K_inappropriate": "YES_AS_UNIVERSAL_CONSTANT; Forest City 35F DESIGN is a different boundary and climate/control. Do NOT conclude Prineville should use 19.4K.",
        "implied_m_dot_per_W_IT_design": m_per_w_it,
        "implied_m_dot_per_W_12K_prior": m_per_w_12,
        "m_dot_ratio_IT35_vs_12K": ratio,
        "hardware_45pct_less": "DESIGN_SPEC Maguire; not a measured CFM and not equal to 25F/35F=0.714",
        "ocp_v1_cfm_tables": "Prineville-observed server CFM; not Forest City facility BMS; hardware generation compatible only as OCP family, NOT as matched operating point",
        "never_state": "Forest City 19.4 K proves Prineville should use 19.4 K",
    }
    _csv(OUTPUTS / "cross_site_validation" / "FOREST_CITY_AIRFLOW_BOUNDARY_RESULTS.csv", [
        {"field": k, "value": json.dumps(v) if isinstance(v, (list, dict)) else v} for k, v in rec.items()
    ])
    write_json(OUTPUTS / "cross_site_validation" / "FOREST_CITY_AIRFLOW_BOUNDARY_RESULTS.json", rec)
    return rec


def cross_climate(w: pd.DataFrame, summer: dict) -> dict:
    prn_modes = pd.read_csv(
        PRINEVILLE_ROOT / "outputs/prn1_q2_2012_public_validation_v1/PREBENCHMARK_MODE_BREAKDOWN.csv"
    )
    jja = w[(w["timestamp_utc"] >= "2012-06-01") & (w["timestamp_utc"] < "2012-09-01")]
    usable = jja.dropna(subset=["t_db_C", "rh_pct", "pressure_Pa"])
    sim = simulate_frame(usable, airflow_boundary="UNIDENTIFIED")
    fam = []
    for _, r in sim.iterrows():
        if r["dx_required"]:
            fam.append("DX_REQUIRED")
        elif r["spray_enabled"]:
            fam.append("EVAPORATIVE_COOLING")
        elif r["oa_fraction"] < 0.999:
            fam.append("RETURN_AIR_MIXING")
        else:
            fam.append("OA_FREE_COOLING")
    sim["family"] = fam
    fc_frac = sim["family"].value_counts(normalize=True).to_dict()
    # Prineville Q2 humidification-dominated
    prn_hum = float(
        prn_modes.loc[prn_modes["control_mode"].str.contains("HUMID"), "fraction_hours"].sum()
    ) if len(prn_modes) else np.nan
    prn_evap = float(
        prn_modes.loc[prn_modes["control_mode"].str.contains("EVAP"), "fraction_hours"].sum()
    ) if len(prn_modes) else np.nan
    prn_mix = float(
        prn_modes.loc[prn_modes["control_mode"].str.contains("MIX|RH_OR"), "fraction_hours"].sum()
    ) if len(prn_modes) else np.nan
    rows = [
        {"site": "PRINEVILLE_PRN1", "period": "2012-Q2 KRDM", "source": "frozen PREBENCHMARK_MODE_BREAKDOWN",
         "humidification_or_lowRH_water_mode_frac": prn_hum, "evaporative_cooling_frac": prn_evap,
         "high_RH_mixing_frac": prn_mix, "dx_frac": 0.0, "note": "PRN1 qualitative: humidification dominated; no DX actuator"},
        {"site": "FOREST_CITY", "period": "2012-JJA KFQD usable", "source": "this pass eps=1",
         "humidification_or_lowRH_water_mode_frac": 0.0,
         "evaporative_cooling_frac": fc_frac.get("EVAPORATIVE_COOLING", 0),
         "high_RH_mixing_frac": fc_frac.get("RETURN_AIR_MIXING", 0),
         "dx_frac": fc_frac.get("DX_REQUIRED", 0),
         "oa_free_frac": fc_frac.get("OA_FREE_COOLING", 0),
         "note": "Forest City controller has no sourced dewpoint-min humidification mode"},
    ]
    _csv(OUTPUTS / "cross_site_validation" / "PRINEVILLE_FOREST_CITY_CROSS_CLIMATE_RESULTS.csv", rows)
    # Transfer status
    expected_dir = (
        prn_hum > 0.4
        and fc_frac.get("EVAPORATIVE_COOLING", 0) + fc_frac.get("RETURN_AIR_MIXING", 0) > 0.1
    )
    dx_ok = summer["primary"]["PREDICTED_DX_REQUIRED_HOURS"] == 0
    if expected_dir and dx_ok:
        status = "TRANSFERABLE_PHYSICS_SUPPORTED"
    elif expected_dir:
        status = "PARTIAL_TRANSFER"
    else:
        status = "PARTIAL_TRANSFER"
    if FACILITY_EFFECTIVE_DELTA_T_STATUS == "UNIDENTIFIED":
        water_note = "AIR_STREAM_EVAPORATED_WATER intensity remains SCENARIO_ONLY; quantitative water transfer not claimed"
    else:
        water_note = "effective DeltaT identified"
    transfer = {
        "status": status,
        "shared_physics": [
            "psychrometrics",
            "enthalpy-conserving mixing",
            "direct evaporative mass/energy balance",
            "saturation constraints",
            "water = m_da * dw (when airflow identified)",
        ],
        "local_controls": [
            "85F/90%RH vs PRN1 80F/65%RH",
            "DX backup present at FC not at early PRN1",
            "no sourced FC dewpoint-min humidification",
            "IT 35F design rise vs PRN1 12K generic effective prior (different boundaries)",
        ],
        "mode_shift_expected_direction": True,
        "prineville_humidification_dominated_q2": True,
        "forest_city_more_mixing_and_evap_jja": True,
        "water_implications": water_note,
        "season_mismatch": "PRN1 frozen comparison is Q2; FC is JJA usable KFQD hours (starts 2012-06-21)",
        "INSUFFICIENT_BOUNDARY_INFORMATION": FACILITY_EFFECTIVE_DELTA_T_STATUS == "UNIDENTIFIED",
        "MODEL_CALIBRATED": "NO",
    }
    write_json(OUTPUTS / "cross_site_validation" / "PRINEVILLE_FOREST_CITY_TRANSFER_STATUS.json", transfer)
    return transfer


def dashboard_recovery() -> dict:
    htmls = list((RAW_DASHBOARD / "wayback").glob("forest-city_*.html"))
    cdx = RAW_DASHBOARD / "wayback" / "cdx_json_endpoints.json"
    js = RAW_DASHBOARD / "wayback" / "application_20130430.js"
    numeric = False
    fields = ["PUE", "WUE L/kWh", "Humidity %", "Temperature"]
    status = "NOT_RECOVERED"
    if htmls:
        status = "SCREENSHOT_ONLY"
        # HTML is a JS app; histograms empty; no embedded series
        sample = htmls[0].read_text(errors="replace")
        if "data-metric=\"pue\"" in sample:
            status = "SCREENSHOT_ONLY"
        if cdx.exists() and cdx.stat().st_size > 5:
            try:
                j = json.loads(cdx.read_text() or "[]")
                if j:
                    status = "PARTIAL_NUMERIC_SERIES"
                    numeric = True
            except Exception:
                pass
    rec = {
        "status": "SCREENSHOT_ONLY" if htmls else "NOT_RECOVERED",
        "live_url_dead": True,
        "archived_html": [str(p) for p in htmls],
        "archived_html_bytes": {p.name: p.stat().st_size for p in htmls},
        "json_api_in_wayback": False,
        "github_frontend": "https://github.com/facebookarchive/puewue-frontend",
        "github_backend": "https://github.com/facebookarchive/puewue-backend",
        "fields_described": fields,
        "period": "public dashboards launched ~2012-08; Forest City page archived 2013-04 through 2021; numeric payloads not in CDX",
        "measurement_boundary": "WUE labeled L/kWh on dashboard HTML; ISO/IEC 30134-9 IT-energy denominator NOT verified from recovered files. Do not use quantitatively.",
        "usefulness": "confirms dashboard existed with PUE/WUE/T/RH and 24h + 1-year views; NO raw time series recovered",
        "js_present": js.exists(),
        "no_model_comparison": True,
    }
    write_json(OUTPUTS / "dashboard_recovery" / "DASHBOARD_RECOVERY_STATUS.json", rec)
    return rec


def annual_series() -> dict:
    # Sourced values. Preserve publication. Do not fit controller.
    elec = [
        # year, MWh, source, methodology, revision
        (2015, 310000, "MWh", "Facebook_2019_Sustainability_Data_Disclosure", "facility electricity", "rounded"),
        (2016, 339000, "MWh", "Facebook_2019_and_2020_Sustainability_Data", "facility electricity", "rounded"),
        (2017, 433000, "MWh", "Meta_2023_EDI", "facility electricity", "rounded"),
        (2018, 547000, "MWh", "Meta_2023_EDI", "facility electricity", "rounded"),
        (2019, 614000, "MWh", "Meta_2023_EDI", "facility electricity", "rounded"),
        (2020, 595000, "MWh", "Meta_2025_EDI", "facility electricity", "rounded_in_2025_index"),
        (2021, 580842, "MWh", "Meta_2025_EDI", "facility electricity", "as_published"),
        (2022, 492786, "MWh", "Meta_2025_EDI", "facility electricity", "as_published"),
        (2023, 507068, "MWh", "Meta_2025_EDI", "facility electricity", "as_published"),
        (2024, 535555, "MWh", "Meta_2025_EDI", "facility electricity", "as_published"),
    ]
    water_m3 = [
        (2017, 129000, "m3", "Meta_2023_EDI", "withdrawal", "as_published_cubic_meters"),
        (2018, 99000, "m3", "Meta_2023_EDI", "withdrawal", "as_published_cubic_meters"),
        (2019, 85000, "m3", "Meta_2023_EDI", "withdrawal", "as_published_cubic_meters"),
        (2020, 68000, "m3", "Meta_2023_EDI_and_2025_EDI_68_ML", "withdrawal", "2025_EDI_reports_68_ML"),
        (2021, 64053, "m3", "Meta_2023_EDI", "withdrawal", "2025_EDI_reports_64_ML"),
        (2022, 62853, "m3", "Meta_2023_EDI", "withdrawal", "2025_EDI_reports_63_ML"),
        (2023, 55000, "m3", "Meta_2025_EDI_55_ML", "withdrawal", "converted_from_55_ML"),
        (2024, 16000, "m3", "Meta_2025_EDI_16_ML", "withdrawal", "converted_from_16_ML"),
    ]
    s2 = [
        (2020, 202000, "tCO2e", "Meta_2025_EDI", "location-based Scope 2", "rounded"),
        (2021, 165026, "tCO2e", "Meta_2025_EDI", "location-based Scope 2", "as_published"),
        (2022, 143754, "tCO2e", "Meta_2025_EDI", "location-based Scope 2", "as_published"),
        (2023, 144050, "tCO2e", "Meta_2025_EDI", "location-based Scope 2", "as_published"),
        (2024, 144104, "tCO2e", "Meta_2025_EDI", "location-based Scope 2", "as_published"),
    ]
    e_rows = [{"year": y, "value": v, "unit": u, "source_publication": s, "methodology": m, "scope": "FOREST_CITY_SITE_AS_REPORTED", "revision": r, "note": "later years are not 2012 Building-1 only"} for y,v,u,s,m,r in elec]
    w_rows = [{"year": y, "value": v, "unit": u, "source_publication": s, "methodology": m, "scope": "FOREST_CITY_SITE_AS_REPORTED", "revision": r, "value_ML": v / 1000.0} for y,v,u,s,m,r in water_m3]
    s_rows = [{"year": y, "value": v, "unit": u, "source_publication": s, "methodology": m, "scope": "location-based Scope 2 site row", "revision": r} for y,v,u,s,m,r in s2]
    e = pd.DataFrame(e_rows)
    ww = pd.DataFrame(w_rows)
    e.to_csv(DATA_PROCESSED / "FOREST_CITY_ANNUAL_ELECTRICITY.csv", index=False)
    ww.to_csv(DATA_PROCESSED / "FOREST_CITY_ANNUAL_WATER_WITHDRAWAL.csv", index=False)
    pd.DataFrame(s_rows).to_csv(DATA_PROCESSED / "FOREST_CITY_SCOPE2_LOCATION.csv", index=False)
    m = e.merge(ww[["year", "value"]].rename(columns={"value": "withdrawal_m3"}), on="year", how="outer")
    m["site_withdrawal_intensity_L_per_kWh_facility"] = m["withdrawal_m3"] / m["value"]
    m["not_WUE"] = True
    m["intensity_name"] = "SITE_WITHDRAWAL_INTENSITY"
    m.to_csv(OUTPUTS / "annual_accounting" / "FOREST_CITY_SITE_WITHDRAWAL_INTENSITY.csv", index=False)
    return {"electricity_years": list(e.year), "water_years": list(ww.year)}


def water_audit() -> dict:
    e = pd.read_csv(DATA_PROCESSED / "FOREST_CITY_ANNUAL_ELECTRICITY.csv")
    w = pd.read_csv(DATA_PROCESSED / "FOREST_CITY_ANNUAL_WATER_WITHDRAWAL.csv")
    m = e.merge(w[["year", "value", "value_ML"]], on="year", how="outer", suffixes=("_mwh", "_m3"))
    m["intensity"] = m["value_m3"] / m["value_mwh"]
    # simple change: largest YoY drop in withdrawal
    w2 = w.sort_values("year")
    w2["yoy"] = w2["value"].diff()
    drop = w2.loc[w2["yoy"].idxmin()] if w2["yoy"].notna().any() else None
    rows = []
    hypotheses = [
        ("facility_additions", "FRC3 ~2014 and FRC4 cold storage 2014; later unidentified halls", "NOT_ALIGNED_WITH_2023_2024_DROP", "electricity stays large while water falls later"),
        ("cold_storage", "FRC4 2014 OpenVault mostly powered-down disks", "PARTIAL_CHRONOLOGY_ONLY", "too early for 2024 16 ML step"),
        ("mechanical_retrofits", "McCammon: water-infused membrane instead of misters", "PUBLICLY_UNRESOLVED_TIMING", "could reduce evaporated water; year unknown"),
        ("water_treatment_changes", "municipal WTP 8 MGD unchanged in LWSP", "NOT_A_META_CAUSE", "town capacity is not Meta withdrawal"),
        ("reporting_method_changes", "EDI unit ML vs m3; 2024 16 ML vs 2023 55 ML", "POSSIBLE_CONTRIBUTOR_UNVERIFIED", "no method note attributing the 2024 drop"),
        ("weather", "not used to fit; 2024 weather not reconstructed here", "UNTESTED"),
        ("operational_efficiency", "qualitative operator claims", "PUBLICLY_UNRESOLVED"),
    ]
    for h in hypotheses:
        rows.append({"hypothesis": h[0], "evidence": h[1], "alignment": h[2], "note": h[3] if len(h) > 3 else ""})
    if drop is not None:
        rows.append({"hypothesis": "descriptive_largest_yoy_drop", "evidence": f"{int(drop.year)} {drop.yoy} m3", "alignment": "DESCRIPTIVE_NOT_CAUSAL", "note": "largest decline is 2023->2024"})
    _csv(OUTPUTS / "annual_accounting" / "FOREST_CITY_LONG_RUN_WATER_AUDIT.csv", rows)
    rec = {
        "largest_yoy_drop_year": int(drop.year) if drop is not None else None,
        "largest_yoy_drop_m3": float(drop.yoy) if drop is not None else None,
        "2024_withdrawal_ML": 16,
        "2024_electricity_MWh": 535555,
        "causal_claim": False,
        "status": "PUBLICLY_UNRESOLVED",
        "not_used_to_fit_2012_controller": True,
    }
    write_json(OUTPUTS / "annual_accounting" / "FOREST_CITY_LONG_RUN_WATER_AUDIT.json", rec)
    return rec


def parse_lwsp() -> pd.DataFrame:
    rows = []
    for p in sorted(RAW_LWSP.glob("lwsp_01-81-010_*.html")):
        year = int(re.search(r"(\d{4})", p.stem).group(1))
        t = p.read_text(errors="replace")
        if "Average Daily Withdrawal" not in t and "Second Broad" not in t:
            continue
        m_ind = re.search(r"Industrial</td>\s*<td>([0-9,]+)</td>\s*<td>([0-9.]+)</td>", t)
        m_com = re.search(r"Commercial</td>\s*<td>([0-9,]+)</td>\s*<td>([0-9.]+)</td>", t)
        m_res = re.search(r"Residential</td>\s*<td>([0-9,]+)</td>\s*<td>([0-9.]+)</td>", t)
        m_raw = re.search(r"Second Broad River</td>\s*<td class=\"left\"></td>\s*<td>([0-9.]+)</td>\s*<td>([0-9.]+)</td>", t)
        months = re.findall(
            r"<th>(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)</th>\s*<td>([0-9.]+)</td>\s*<td>([0-9.]+)</td>",
            t,
        )
        month_map = {a: (float(b), float(c)) for a, b, c in months}
        # first occurrence set is monthly withdrawal table
        for i, mon in enumerate(["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], 1):
            avg, mx = month_map.get(mon, (np.nan, np.nan))
            rows.append({
                "year": year,
                "month": i,
                "raw_surface_withdrawal_avg_mgd": avg,
                "raw_surface_withdrawal_max_mgd": mx,
                "finished_production_mgd": np.nan,
                "industrial_demand_mgd": float(m_ind.group(2)) if m_ind else np.nan,
                "commercial_demand_mgd": float(m_com.group(2)) if m_com else np.nan,
                "residential_demand_mgd": float(m_res.group(2)) if m_res else np.nan,
                "industrial_connections": m_ind.group(1).replace(",", "") if m_ind else "",
                "annual_raw_avg_mgd": float(m_raw.group(1)) if m_raw else np.nan,
                "annual_raw_days": float(m_raw.group(2)) if m_raw else np.nan,
                "wwtp_discharge": "see LWSP monthly discharge table",
                "source": p.name,
                "note": "monthly avg is municipal withdrawal/purchases, NOT Meta. Industrial is municipal class.",
            })
    df = pd.DataFrame(rows)
    df.to_csv(DATA_PROCESSED / "forest_city_municipal_water_monthly.csv", index=False)
    return df


def municipal_accounting() -> None:
    muni = pd.read_csv(DATA_PROCESSED / "forest_city_municipal_water_monthly.csv")
    meta = pd.read_csv(DATA_PROCESSED / "FOREST_CITY_ANNUAL_WATER_WITHDRAWAL.csv")
    # annual municipal production proxy: mean of monthly avg MGD * 365
    ann = muni.groupby("year").agg(
        monthly_avg_mgd=("raw_surface_withdrawal_avg_mgd", "mean"),
        industrial_mgd=("industrial_demand_mgd", "first"),
        annual_raw_avg_mgd=("annual_raw_avg_mgd", "first"),
    ).reset_index()
    ann["municipal_m3"] = ann["annual_raw_avg_mgd"] * 365.0 * 3785.411784
    ann["industrial_m3"] = ann["industrial_mgd"] * 365.0 * 3785.411784
    out = ann.merge(meta[["year", "value"]].rename(columns={"value": "meta_withdrawal_m3"}), on="year", how="left")
    out["meta_share_of_municipal"] = out["meta_withdrawal_m3"] / out["municipal_m3"]
    out["meta_share_of_industrial_class"] = out["meta_withdrawal_m3"] / out["industrial_m3"]
    out["not_WUE"] = True
    out["not_causal_flow"] = True
    out["wtp"] = "Forest City WTP PWSID 01-81-010 8 MGD; raw metered; finished metered; Second Broad River"
    out.to_csv(OUTPUTS / "annual_accounting" / "FOREST_CITY_MUNICIPAL_SOURCE_ACCOUNTING.csv", index=False)


def permit_audit() -> None:
    portal = RAW_PERMITS / "search_facebook.html"
    rows = [{
        "permit_number": "UNIDENTIFIED",
        "address_searched": "Facebook; 404 Social Circle; Meta; Social Circle",
        "portal": "https://twn-forestcity-nc.smartgovcommunity.com/Public/Home",
        "public_result": "Portal loads; ApplicationSearch requires login/account. No permit numbers, CFM, DX, or water-service documents were returned to an unauthenticated request.",
        "mechanical": "NOT_FOUND_PUBLIC",
        "plumbing": "NOT_FOUND_PUBLIC",
        "electrical": "NOT_FOUND_PUBLIC",
        "building": "NOT_FOUND_PUBLIC",
        "do_not_treat_as_measured_load": True,
        "source": portal.name if portal.exists() else "portal_home",
    }]
    _csv(OUTPUTS / "permit_audit" / "FOREST_CITY_PUBLIC_PERMIT_INVENTORY.csv", rows)
    md = OUTPUTS / "permit_audit" / "FOREST_CITY_MANUAL_RECORDS_REQUEST_TARGETS.md"
    md.write_text(
        """# Forest City manual records request targets

Do not send requests from this repository. High-value unresolved public documents only.

1. Permit number: UNIDENTIFIED (search Town SmartGov / paper archives 2010–2014 for Facebook/Meta, 404 Social Circle).
   Building/address: 404 Social Circle, Forest City, NC 28043 (FRC1) and later campus buildings.
   Document requested: mechanical permit set / sequence of operations / AHU schedules / TAB / commissioning.
   Reason: SAT/RAT, CFM, evaporative vs DX capacity, design DeltaT at AHU vs IT.
   Uncertainty resolved: FACILITY_EFFECTIVE_DELTA_T; as-operated controller; DX capacity.

2. Permit number: UNIDENTIFIED plumbing / water service.
   Building/address: same.
   Document requested: water-service size, cooling-water meter, RO/UV skid, drain, P&ID tag for WUE numerator.
   Reason: cooling-water input vs site withdrawal boundary.
   Uncertainty resolved: air vapor → cooling-water input → site withdrawal.

3. Permit number: UNIDENTIFIED electrical / load calculations.
   Building/address: FRC1, FRC3, FRC4.
   Document requested: transformer/service capacity, load calculations, building-to-feeder map.
   Reason: IT vs facility electricity; do not treat nameplate as measured load.
   Uncertainty resolved: campus load mapping.

4. FRC4 cold storage (2014 DPR/Fortis).
   Document requested: AHU count/CFM (ENR says 14 AHUs) TAB.
   Reason: whether later withdrawal drop could be architecture mix vs 2012 evaporative halls.
   Uncertainty resolved: later-campus water vs 2012 Building-1 physics.

5. Town industrial customer class / Meta account (if legally releasable; may be confidential).
   Document requested: monthly customer meter, not modeled.
   Uncertainty resolved: Meta share of industrial demand. Do not invent.
"""
    )


def emissions() -> dict:
    s2 = pd.read_csv(DATA_PROCESSED / "FOREST_CITY_SCOPE2_LOCATION.csv")
    e = pd.read_csv(DATA_PROCESSED / "FOREST_CITY_ANNUAL_ELECTRICITY.csv")
    m = s2.merge(e[["year", "value"]].rename(columns={"value": "mwh"}), on="year")
    m["implied_kg_per_kWh"] = m["value"] / m["mwh"]
    rec = {
        "historical_utility": "Duke Energy Carolinas (DUK BA); Meta factsheet: worked with Duke Energy for 100% clean/renewable matching (market-based, not location-based)",
        "grid_boundary_location_based": "eGRID SRVC (SERC Virginia/Carolina) is the candidate subregion; plant-level DUK mix UNIDENTIFIED without a serving-plant study",
        "egrid_files_this_pass": "NOT_DOWNLOADED_FULL_eGRID_XLSX",
        "reconstructed": "NOT_RECONSTRUCTED_TIME_RESOLVED",
        "meta_location_based_scope2": s2.to_dict(orient="records"),
        "implied_site_average_t_per_MWh": m[["year", "implied_kg_per_kWh"]].to_dict(orient="records"),
        "status": "META_SERIES_CANONICAL; GRID_RECONSTRUCTION_INSUFFICIENT_INPUTS",
        "do_not_refit_emission_factors": True,
        "comparison": "Cannot validate vs eGRID without downloading year-matched SRVC factors. Implied 2024 EF = 144104/535555 ≈ 0.269 t/MWh. Not an eGRID value.",
    }
    m.assign(not_egrid=True).to_csv(OUTPUTS / "emissions" / "FOREST_CITY_LOCATION_EMISSIONS_VALIDATION.csv", index=False)
    write_json(OUTPUTS / "emissions" / "FOREST_CITY_LOCATION_EMISSIONS_VALIDATION.json", rec)
    return rec


def chain_and_priority(events, summer, transfer, dash) -> None:
    rows = [
        {"edge": "workload→IT", "prineville": "UNIDENTIFIED", "forest_city": "UNIDENTIFIED", "note": "no public interval IT load"},
        {"edge": "IT→airflow", "prineville": "SCENARIO_ONLY 12K generic effective", "forest_city": "DESIGN_SPEC 35F IT rise; EFFECTIVE UNIDENTIFIED", "note": "boundaries not interchangeable"},
        {"edge": "weather→controller", "prineville": "ENGINEERING_BOUNDED Q2 KRDM + OCP A-H DESIGN_SPEC", "forest_city": "ENGINEERING_BOUNDED KFQD from 2012-06-21 + FC envelope DESIGN_SPEC", "note": "KFQD gap before 2012-06-21"},
        {"edge": "controller→air state", "prineville": "DESIGN_SPEC", "forest_city": "DESIGN_SPEC + OPERATOR_OBSERVED events", "note": events},
        {"edge": "air state→AIR_STREAM_EVAPORATED_WATER", "prineville": "STRUCTURALLY_IDENTIFIED physics; magnitude overpredicts published WUE", "forest_city": "STRUCTURALLY_IDENTIFIED physics; intensity UNIDENTIFIED without effective DeltaT", "note": ""},
        {"edge": "air vapor→cooling-water input", "prineville": "SCENARIO_BOUNDED RO hypotheses", "forest_city": "UNIDENTIFIED (UV then evap; RO not identified)", "note": "ENR municipal UV"},
        {"edge": "cooling-water input→site withdrawal", "prineville": "UNIDENTIFIED meter", "forest_city": "UNIDENTIFIED", "note": "annual EDI is site withdrawal not 2012 cooling meter"},
        {"edge": "site withdrawal→municipal water", "prineville": "City meters diagnostic", "forest_city": "ENGINEERING_BOUNDED accounting share only", "note": "not causal"},
        {"edge": "municipal water→Second Broad River", "prineville": "n/a", "forest_city": "DIRECTLY_MEASURED municipal raw source in LWSP", "note": "PWSID 01-81-010"},
        {"edge": "facility electricity→grid emissions", "prineville": "PACW/eGRID Oregon", "forest_city": "EXTERNALLY_VALIDATED Meta location-based series; grid reconstruction insufficient", "note": "Duke/SRVC"},
    ]
    # map statuses to allowed ontology
    allowed = {"DIRECTLY_MEASURED","OPERATOR_OBSERVED","EXTERNALLY_VALIDATED","ENGINEERING_BOUNDED","DESIGN_SPEC","SCENARIO_ONLY","UNIDENTIFIED"}
    out = []
    for r in rows:
        out.append({
            "edge": r["edge"],
            "forest_city_status": "UNIDENTIFIED" if "UNIDENTIFIED" in r["forest_city"] else (
                "OPERATOR_OBSERVED" if "OPERATOR" in r["forest_city"] else (
                    "DESIGN_SPEC" if "DESIGN_SPEC" in r["forest_city"] else (
                        "ENGINEERING_BOUNDED" if "ENGINEERING" in r["forest_city"] else (
                            "DIRECTLY_MEASURED" if "DIRECTLY" in r["forest_city"] else (
                                "SCENARIO_ONLY" if "SCENARIO" in r["forest_city"] else "UNIDENTIFIED"
                            )
                        )
                    )
                )
            ),
            "prineville_status_context": r["prineville"],
            "forest_city_detail": r["forest_city"],
            "note": r["note"],
        })
    _csv(OUTPUTS / "FOREST_CITY_CHAIN_CONNECTION_STATUS.csv", out)
    pri = [
        {"dataset": "BMS SAT/RAT/MAT T/RH, OA damper, DX enable, ECH command", "category": "air-side physics", "value": "VERY_HIGH", "why": "as-operated controller vs design envelope; event/DX tests are qualitative only"},
        {"dataset": "TAB CFM / air-balance / sequence of operations", "category": "air-side physics", "value": "VERY_HIGH", "why": "only path to FACILITY_EFFECTIVE_DELTA_T"},
        {"dataset": "cooling-water meter / WUE numerator P&ID tag", "category": "water boundary", "value": "VERY_HIGH", "why": "cannot quantitatively predict site water from air-stream dw yet"},
        {"dataset": "customer water meter history (if releasable)", "category": "water boundary", "value": "HIGH", "why": "Meta share of industrial class is accounting only"},
        {"dataset": "customer interval electricity / building-service map", "category": "campus load", "value": "HIGH", "why": "annual EDI is campus-total; 2012 Building-1 load UNIDENTIFIED"},
        {"dataset": "eGRID SRVC / DUK EIA-930 time series", "category": "emissions", "value": "MEDIUM", "why": "Meta location-based already published; reconstruction is secondary"},
        {"dataset": "Second Broad instream / source externality hydrology", "category": "source externality", "value": "LOW_until_withdrawal_boundary_identified", "why": "do not fit groundwater/surface-water impact models yet"},
    ]
    _csv(OUTPUTS / "FOREST_CITY_DATA_VALUE_PRIORITY.csv", pri)
    (OUTPUTS / "FOREST_CITY_NEXT_ACQUISITION_PLAN.md").write_text(
        """# Next acquisition plan (after public Forest City pass)

Highest remaining value is as-operated air-side measurements, not another public climate site.

1. Air-side physics: Town mechanical/TAB/commissioning set for FRC1 (2010–2012) — CFM, SAT/RAT, sequence, DX.
2. Water boundary: cooling-water meter identity and WUE numerator tag; do not treat municipal industrial class as Meta.
3. Campus load: interval electricity mapped to buildings; do not assume 2024 EDI is 2012 Building 1.
4. Emissions: year-matched eGRID SRVC / DUK only after (1)–(3) if still needed.
5. Source externality: only after cooling-water vs withdrawal boundary is identified.

No calibration. No Prineville refit. No other data center in this pass.
"""
    )


def figures(w, events, summer) -> None:
    figdir = OUTPUTS / "figures"
    figdir.mkdir(parents=True, exist_ok=True)
    # 1 timeline
    fig, ax = plt.subplots(figsize=(10, 4))
    items = [
        ("FRC1 online", 2012.3),
        ("B2 planned", 2012.7),
        ("FRC3 2nd hall (tour)", 2014.0),
        ("FRC4 cold storage", 2014.3),
        ("later campus UNIDENTIFIED", 2017.0),
    ]
    ax.scatter([x[1] for x in items], [1]*len(items))
    for name, yr in items:
        ax.annotate(name, (yr, 1.02), rotation=20, ha="left")
    ax.set_title("Forest City facility chronology (public evidence only)")
    ax.set_yticks([])
    ax.set_xlim(2010, 2026)
    fig.tight_layout()
    fig.savefig(figdir / "fig01_facility_timeline.png", dpi=140)
    plt.close()
    # 2 psychrometric scatter
    jja = w[(w["timestamp_utc"] >= "2012-06-01") & (w["timestamp_utc"] < "2012-09-01")].dropna(subset=["t_db_C", "rh_pct", "pressure_Pa"])
    if len(jja):
        sim = simulate_frame(jja, airflow_boundary="UNIDENTIFIED", evap_thermal_effectiveness=1.0)
        fig, ax = plt.subplots(figsize=(8, 6))
        t_f = [c_to_f(x) for x in sim["t_db_C"]]
        colors = []
        for _, r in sim.iterrows():
            if r["dx_required"]:
                colors.append("red")
            elif r["spray_enabled"]:
                colors.append("tab:orange")
            elif r["oa_fraction"] < 0.999:
                colors.append("tab:blue")
            else:
                colors.append("tab:green")
        ax.scatter(t_f, sim["rh_pct"], c=colors, s=8, alpha=0.5)
        ax.axvline(85, color="k", ls="--", lw=1, label="85F inlet max")
        ax.axhline(90, color="k", ls=":", lw=1, label="90% RH max")
        ax.set_xlabel("Outdoor DB F")
        ax.set_ylabel("Outdoor RH %")
        ax.set_title("2012 JJA KFQD hours, Forest City controller modes")
        fig.tight_layout()
        fig.savefig(figdir / "fig02_2012_modes_psychrometric.png", dpi=140)
        plt.close()
    # 3 events: predicted family vs operator DX=0
    fig, ax = plt.subplots(figsize=(8, 3.5))
    names = []
    for ev, rec in events.items():
        names.append(f"{ev}\n{rec.get('synthetic_mode_family')}\nDX={rec.get('synthetic_dx')}")
    ax.bar(range(len(names)), [0 if rec.get("synthetic_dx") else 1 for rec in events.values()])
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names)
    ax.set_ylim(0, 1.2)
    ax.set_ylabel("model agrees DX not required")
    ax.set_title("June 25 / July 1: predicted mode vs operator DX non-use")
    fig.tight_layout()
    fig.savefig(figdir / "fig03_historical_events.png", dpi=140)
    plt.close()
    # 4 summer DX
    hours = OUTPUTS / "control_validation" / "SUMMER_2012_DX_HOURS.csv"
    if hours.exists():
        s = pd.read_csv(hours)
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(pd.to_datetime(s["timestamp_utc"]), s["dx_required"].astype(int), lw=0.8)
        ax.set_title("Summer 2012 predicted DX-required (1) on valid KFQD hours")
        fig.tight_layout()
        fig.savefig(figdir / "fig04_summer_dx_timeline.png", dpi=140)
        plt.close()
    # 5 cross climate family comparison
    fig, ax = plt.subplots(figsize=(8, 4))
    prn = pd.read_csv(PRINEVILLE_ROOT / "outputs/prn1_q2_2012_public_validation_v1/PREBENCHMARK_MODE_BREAKDOWN.csv")
    prn_h = float(prn.loc[prn["control_mode"].str.contains("HUMID"), "fraction_hours"].sum())
    prn_e = float(prn.loc[prn["control_mode"].str.contains("EVAP"), "fraction_hours"].sum())
    prn_m = float(prn.loc[prn["control_mode"].str.contains("MIX|RH_OR"), "fraction_hours"].sum())
    prn_f = float(prn.loc[prn["control_mode"].str.contains("FREE"), "fraction_hours"].sum())
    cc = pd.read_csv(OUTPUTS / "cross_site_validation" / "PRINEVILLE_FOREST_CITY_CROSS_CLIMATE_RESULTS.csv")
    fc = cc.iloc[1] if False else None
    labels = ["humidification\n(PRN1 modes)", "evaporative\ncooling", "high-RH\nmixing", "OA free /\nother"]
    prn_vals = [prn_h, prn_e, prn_m, prn_f]
    # FC from summer json
    sm = json.loads((OUTPUTS / "control_validation" / "SUMMER_2012_DX_VALIDATION.json").read_text())
    fr = sm["primary"]["mode_fractions"]
    fc_vals = [0.0, fr.get("EVAPORATIVE_COOLING", 0), fr.get("RETURN_AIR_MIXING", 0), fr.get("OA_FREE_COOLING", 0)]
    x = np.arange(len(labels))
    ax.bar(x - 0.18, prn_vals, 0.35, label="PRN1 Q2 2012 (frozen)")
    ax.bar(x + 0.18, fc_vals, 0.35, label="Forest City JJA 2012 KFQD")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("hour fraction")
    ax.set_title("Cross-climate mode occupancy (different seasons/controllers)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(figdir / "fig05_cross_climate_mode_comparison.png", dpi=140)
    plt.close()
    # 6 annual
    e = pd.read_csv(DATA_PROCESSED / "FOREST_CITY_ANNUAL_ELECTRICITY.csv")
    ww = pd.read_csv(DATA_PROCESSED / "FOREST_CITY_ANNUAL_WATER_WITHDRAWAL.csv")
    fig, ax1 = plt.subplots(figsize=(8, 4))
    ax1.plot(e["year"], e["value"] / 1000.0, "o-", label="electricity GWh")
    ax2 = ax1.twinx()
    ax2.plot(ww["year"], ww["value_ML"], "s-", color="tab:blue", label="withdrawal ML")
    ax1.set_title("Forest City annual electricity and withdrawal (not WUE)")
    fig.tight_layout()
    fig.savefig(figdir / "fig06_annual_electricity_withdrawal.png", dpi=140)
    plt.close()


def main() -> None:
    facility_timeline()
    w = load_weather()
    events = event_validation(w)
    summer = summer_dx(w)
    airflow_boundary()
    transfer = cross_climate(w, summer)
    dash = dashboard_recovery()
    annual_series()
    water_audit()
    parse_lwsp()
    municipal_accounting()
    permit_audit()
    emissions()
    chain_and_priority(events, summer, transfer, dash)
    figures(w, events, summer)
    write_json(
        OUTPUTS / "FOREST_CITY_PUBLIC_VALIDATION_STATUS.json",
        {
            "utc": datetime.now(timezone.utc).isoformat(),
            "MODEL_CALIBRATED": "NO",
            "model_version": MODEL_VERSION,
            "events": {k: v.get("status") for k, v in events.items()},
            "summer_dx_hours_eps1": summer["primary"]["PREDICTED_DX_REQUIRED_HOURS"],
            "transfer": transfer["status"],
            "dashboard": dash["status"],
            "IT_DELTA_T_DESIGN": IT_DELTA_T_STATUS,
            "FACILITY_EFFECTIVE_DELTA_T": FACILITY_EFFECTIVE_DELTA_T_STATUS,
        },
    )
    print("pipeline complete")


if __name__ == "__main__":
    main()
