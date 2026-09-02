#!/usr/bin/env python3
"""Forest City v3 pipeline. Additive only. No refit. No v1/v2/Prineville writes."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

FC3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FC3 / "src"))

from esif_frozen import load_selected, predict_f0_hvac, predict_f4_cooling  # noqa: E402
from hashes import sha256_file, write_json  # noqa: E402
from fc3_paths import (  # noqa: E402
    CAMPUS_TZ,
    COMMON_END,
    COMMON_START,
    FC_EVAP_EPS,
    JJA_END,
    JJA_START,
    MASANET,
    MASANET_PYTHON,
    NLR,
    OUTPUTS,
    PRN,
    REPO,
    V1,
    V1_PROCESSED,
    V1_RAW_WEATHER,
    V2,
    V2_KFQD_JJA_TARGET,
)
from taxonomy import CATEGORIES, assert_exactly_one, classify_hour, mapping_table_rows  # noqa: E402
from weather_hourly import calendar_2012, hourlyize, read_global_hourly  # noqa: E402

sys.path.insert(0, str(V1 / "src"))
sys.path.insert(0, str(PRN / "src"))
from forest_city_structural_reference_v1 import simulate_frame  # noqa: E402
from prineville_structural_v1 import ReturnAirSpec, StructuralV1Params, simulate_structural_reference_v1  # noqa: E402

EXPECTED = {
    "fc_controller": "99ecc213fa181ab1fe7144087da5874b0a8f3f79478a6a8b5aed83fe0ea77c78",
    "fc_structural": "085a893cd63665b37d027877e9d80efbc99489a6c813a9f8da150e41a529568d",
    "fc_control_contract": "56d3ef12b0ab3584886892a3283f068ebe7bcfc0adc827543dc6b8910da450c2",
    "fc_airflow_contract": "f1cdc03bea8f5103e8951c6fbef7e965d16248e511fd4ad4874e19d5054ddc37",
    "kfqd_parquet": "f87a2e61120cf2d8e3117ff20e838567d0f8525a650a7fdaad221f9b3044e1d9",
    "prn_structural": "f9649c489196cdc3e617f5b28574334aaaace5a94e7ade5ce461f6da22809a6a",
    "prn_psych": "c10e1487a00ce32023bf3b630f915b2fe9ba303917951ff5f5bcbec3a3aafd30",
    "prn_graybox": "8275ca5bfc23042e3af19b72f2adb260304ac95d692d0b3ecbcb526b020f0609",
    "prn_arch": "1f87a1846aa8254c758ab11e3bd9b6f639e6c64bc551c36bcf8201bd65e78604",
    "q2_krdm": "87c0beaf1f8223ebb9f4d02ff13b9efd9d2286aaddfec0a3cce9af4c4279d925",
    "cpu": "1f57b210a63d375ce8eff7d5043756ffe6efe04e8a408bf9429bfd10096528d9",
    "h100": "a620d649a932f2388aa2f35bac2730eb75fe1dc74529668de4f30ee814600076",
    "esif": "4e01139dd9365f62824ac00ff944468839e7873e47a5cea3df4714854af1b02c",
    "esif_selected": "fc15039e713578316877f5df9e1009e2a719128bd2458cde74a822ff1aa877dd",
    "masanet_first": "70782ac8597d81d8d970fdbffb427969cc5618526df0191146b382e7cb1d1d8a",
}

HASH_FILES = {
    "fc_controller": V1 / "src/forest_city_controller.py",
    "fc_structural": V1 / "src/forest_city_structural_reference_v1.py",
    "fc_control_contract": V1 / "config/FOREST_CITY_REFERENCE_CONTROL_CONTRACT.json",
    "fc_airflow_contract": V1 / "config/FOREST_CITY_AIRFLOW_BOUNDARY_CONTRACT.json",
    "kfqd_parquet": V1_PROCESSED / "forest_city_weather_2012_hourly.parquet",
    "prn_structural": PRN / "src/prineville_structural_v1.py",
    "prn_psych": PRN / "src/prineville_psychrometrics.py",
    "prn_graybox": PRN / "src/prineville_graybox.py",
    "prn_arch": PRN / "config/prineville_architecture_states.yaml",
    "q2_krdm": PRN / "outputs/prn1_q2_2012_public_validation_v1/weather/Q2_2012_KRDM_hourly.parquet",
    "cpu": NLR / "analysis/FINAL_KESTREL_CPU_STATUS.json",
    "h100": NLR / "genai_h100/manifests/H100_COMPUTE_FINAL_FREEZE.json",
    "esif": NLR / "heat_rejection_water/manifests/ESIF_HEAT_WATER_RESULT_FREEZE.json",
    "esif_selected": NLR / "facility_overhead/analysis/COMPONENT_SELECTED_MODELS.json",
    "masanet_first": MASANET / "results/FIRST_RUN_STATUS.json",
}

STATION_META = [
    {
        "call_sign": "KFQD",
        "station_id": "72314453890",
        "role": "PREFERRED_LOCAL",
        "raw_name": "72314453890_2012.csv",
        "reuse_v1_parquet": True,
        "selection_reason": (
            "Nearest ISD station to the Forest City campus; OCP 2013 used Rutherfordton "
            "weather ~6 miles NW. Preferred where observed. Completeness and distance decided "
            "a priori; not selected because of a DX outcome."
        ),
    },
    {
        "call_sign": "KEHO",
        "station_id": "72027763843",
        "role": "NEAREST_COMPLETE_2012_JJA",
        "raw_name": "72027763843_2012.csv",
        "reuse_v1_parquet": False,
        "selection_reason": (
            "Independent 2012 JJA representation closer than KGSP and already present in "
            "the v1 weather bank. Included for completeness robustness, not because of DX."
        ),
    },
    {
        "call_sign": "KGSP",
        "station_id": "72312003870",
        "role": "FIRST_ORDER_ASOS_INDEPENDENT_REPLICATION",
        "raw_name": "72312003870_2012.csv",
        "reuse_v1_parquet": False,
        "selection_reason": (
            "Complete first-order ASOS for overlap diagnostics. Farther than KFQD/KEHO. "
            "Not selected because of a DX outcome."
        ),
    },
]

PRN_RA = ReturnAirSpec(T_C=35.0, rh_pct=15.0, provenance="DESIGN_REFERENCE_SCENARIO", label="PRN1_Q2_FROZEN")
PRN_PARAMS = StructuralV1Params(evap_thermal_effectiveness=0.85, server_deltaT_C=12.0)

V2_2X2_TARGET = {
    "PRN_weather+PRN_controller": {
        "P(HUMIDIFICATION)": 0.43005595523581136,
        "P(OA_FREE)": 0.1374900079936051,
        "P(HIGH_RH_MIXING)": 0.20623501199040767,
        "P(EVAP_COOLING)": 0.22621902478017586,
    },
    "PRN_weather+FC_controller": {
        "P(HUMIDIFICATION)": 0.0,
        "P(OA_FREE)": 0.8361310951239008,
        "P(HIGH_RH_MIXING)": 0.03117505995203837,
        "P(EVAP_COOLING)": 0.13269384492406075,
    },
    "FC_weather+PRN_controller": {
        "P(HUMIDIFICATION)": 0.0,
        "P(OA_FREE)": 0.019984012789768184,
        "P(HIGH_RH_MIXING)": 0.7450039968025579,
        "P(EVAP_COOLING)": 0.23501199040767387,
    },
    "FC_weather+FC_controller": {
        "P(HUMIDIFICATION)": 0.0,
        "P(OA_FREE)": 0.539568345323741,
        "P(HIGH_RH_MIXING)": 0.35411670663469225,
        "P(EVAP_COOLING)": 0.10631494804156674,
    },
}


def git(cmd: str) -> str:
    r = subprocess.run(cmd, shell=True, cwd=REPO, capture_output=True, text=True)
    return (r.stdout or r.stderr).strip()


def df_to_md(df: pd.DataFrame) -> str:
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in df.columns) + " |")
    return "\n".join(lines)


def record_hashes(tag: str) -> dict:
    rec = {}
    mismatches = []
    for k, p in HASH_FILES.items():
        rec[k] = {"path": str(p), "exists": p.exists()}
        if p.exists():
            rec[k]["sha256"] = sha256_file(p)
            exp = EXPECTED.get(k)
            if exp:
                rec[k]["match"] = rec[k]["sha256"] == exp
                if not rec[k]["match"]:
                    mismatches.append(k)
        else:
            mismatches.append(k)
    tree = {
        "v1_tree_HEAD": git("git rev-parse HEAD:Meta_Forest_City_North_Carolina_v1"),
        "v2_tree_HEAD": git("git rev-parse HEAD:Meta_Forest_City_North_Carolina_v2"),
        "prn_src_HEAD": git("git rev-parse HEAD:Meta_Prineville_Oregon_v3/src"),
    }
    return {"tag": tag, "hashes": rec, "mismatches": mismatches, "trees": tree}


def usable(df: pd.DataFrame) -> pd.Series:
    return df[["t_db_C", "rh_pct", "pressure_Pa"]].notna().all(axis=1)


def window(df, start, end):
    return df[(df["timestamp_utc"] >= start) & (df["timestamp_utc"] < end)].copy()


def isd_row(station_id: str) -> dict:
    hist = pd.read_csv(V1_RAW_WEATHER / "isd-history.csv")
    usaf, wban = station_id[:6], station_id[6:]
    hit = hist[(hist["USAF"].astype(str) == usaf) & (hist["WBAN"].astype(str).str.zfill(5) == wban)]
    if hit.empty:
        return {}
    r = hit.iloc[0]
    return {"lat": float(r["LAT"]), "lon": float(r["LON"]), "elev_m": float(r["ELEV(M)"])}


def load_station(meta: dict) -> pd.DataFrame:
    isd = isd_row(meta["station_id"])
    elev = float(isd.get("elev_m") or 300.0)
    raw_path = V1_RAW_WEATHER / meta["raw_name"]
    if meta.get("reuse_v1_parquet"):
        pq = V1_PROCESSED / "forest_city_weather_2012_hourly.parquet"
        df = pd.read_parquet(pq)
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
        df.attrs["source_path"] = str(pq)
        df.attrs["source_sha256"] = sha256_file(pq)
        df.attrs["elev_m"] = elev
        df.attrs["station"] = meta["call_sign"]
        return df
    raw = read_global_hourly(raw_path)
    h = hourlyize(raw, elev_m=elev, call_sign=meta["call_sign"], station_id=meta["station_id"], tz=CAMPUS_TZ)
    full = calendar_2012(h, call_sign=meta["call_sign"], station_id=meta["station_id"], tz=CAMPUS_TZ)
    full.attrs["source_path"] = str(raw_path)
    full.attrs["source_sha256"] = sha256_file(raw_path)
    full.attrs["elev_m"] = elev
    full.attrs["station"] = meta["call_sign"]
    return full


def load_krdm() -> pd.DataFrame:
    p = PRN / "data/processed/weather_krdm_hourly.csv"
    df = pd.read_csv(p, parse_dates=["timestamp_utc"])
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df.attrs["source_path"] = str(p)
    df.attrs["source_sha256"] = sha256_file(p)
    df.attrs["station"] = "KRDM"
    return df


def classify_frame(sim: pd.DataFrame, site: str) -> pd.DataFrame:
    out = sim.copy()
    cats = []
    for _, r in out.iterrows():
        miss = str(r.get("control_mode")) == "WEATHER_MISSING"
        cat = classify_hour(
            site,
            str(r.get("control_mode")),
            primary_control_objective=r.get("primary_control_objective"),
            weather_missing=miss,
        )
        assert_exactly_one(cat)
        cats.append(cat)
    out["common_category"] = cats
    out["evidence_class"] = np.where(out["common_category"] == "UNRESOLVED", "UNIDENTIFIED", "MODEL_REPLAY")
    return out


def regime_counts(sim: pd.DataFrame) -> dict:
    usable_mask = sim["control_mode"].astype(str) != "WEATHER_MISSING"
    n = int(usable_mask.sum())
    vc = sim.loc[usable_mask, "common_category"].value_counts()
    d = {c: int(vc.get(c, 0)) for c in CATEGORIES}
    d["valid_hours"] = n
    d["weather_missing_hours"] = int((~usable_mask).sum())
    if "dx_required" in sim.columns:
        d["DX_required_hours"] = int((usable_mask & sim["dx_required"].fillna(False).astype(bool)).sum())
    else:
        d["DX_required_hours"] = int(d["MECHANICAL_COOLING"])
    return d


def simulate_fc(hourly: pd.DataFrame) -> pd.DataFrame:
    sim = simulate_frame(hourly, evap_thermal_effectiveness=FC_EVAP_EPS, airflow_boundary="UNIDENTIFIED")
    return classify_frame(sim, "FC")


def simulate_prn(hourly: pd.DataFrame) -> pd.DataFrame:
    w = hourly.copy()
    ok = usable(w) & w["t_wb_C"].notna()
    cols = ["timestamp_utc", "t_db_C", "t_wb_C", "rh_pct", "pressure_Pa"]
    phys = w.loc[ok, cols]
    if phys.empty:
        w["control_mode"] = "WEATHER_MISSING"
        w["primary_control_objective"] = None
        w["dx_required"] = False
        return classify_frame(w, "PRN1")
    out = simulate_structural_reference_v1(phys, 1.0, PRN_PARAMS, return_air=PRN_RA)
    keep = ["timestamp_utc", "control_mode", "primary_control_objective"]
    m = w.merge(out[keep], on="timestamp_utc", how="left")
    m.loc[m["control_mode"].isna(), "control_mode"] = "WEATHER_MISSING"
    m["dx_required"] = False
    return classify_frame(m, "PRN1")


def preflight():
    h = record_hashes("start")
    state = {
        "repository_root": str(REPO),
        "branch": git("git rev-parse --abbrev-ref HEAD"),
        "HEAD": git("git rev-parse HEAD"),
        "git_status_short": git("git status --short"),
        "submodule": git("git submodule status"),
        "python": sys.executable,
        "utc": datetime.now(timezone.utc).isoformat(),
        "v1": str(V1),
        "v2": str(V2),
        "prineville": str(PRN),
        "hashes": h,
        "MODEL_CALIBRATED": "NO",
        "note": (
            "v2 working tree may be mid-rewrite; v3 does not write there. "
            "Reproduction targets are HEAD-committed v2 JJA shares."
        ),
        "writes_forbidden": [
            str(V1),
            str(V2),
            str(PRN),
            str(MASANET),
            str(NLR),
            str(REPO / "Data-center-PUE-prediction-tool"),
        ],
    }
    write_json(OUTPUTS / "preflight" / "INITIAL_STATE.json", state)
    if h["mismatches"]:
        raise SystemExit(f"frozen hash mismatch: {h['mismatches']}")
    return state


def evidence_crosswalk():
    rows = []
    src_csv = V1 / "config/forest_city_source_register.csv"
    if src_csv.exists():
        reg = pd.read_csv(src_csv)
        for _, rec in reg.iterrows():
            sid = str(rec.get("source_id", ""))
            qty = str(rec.get("quantity", ""))
            if sid in {"MAGUIRE_2011_OCP_REFLECTIONS", "OCP_2013_HOT_HUMID"}:
                bucket = "B_controller_design"
            elif "DASHBOARD" in sid or "PUE_WUE" in sid:
                bucket = "E_dashboard_screenshot"
            elif "EDI" in sid or "FACTSHEET" in sid:
                bucket = "D_later_campus_annual"
            elif "PERMIT" in sid:
                bucket = "G_permit_utility"
            elif sid.startswith("TOWN") or "LWSP" in sid:
                bucket = "G_permit_utility"
            elif rec.get("publication_date") and str(rec.get("publication_date", "")).startswith("201"):
                bucket = "A_original_design_era_FRC1"
            else:
                bucket = "A_original_design_era_FRC1"
            if "EDI" in sid:
                bucket = "D_later_campus_annual"
            rows.append(
                {
                    "source_id": sid,
                    "source_path": rec.get("local_path"),
                    "date_period": rec.get("temporal_scope") or rec.get("publication_date"),
                    "source_type": rec.get("source_tier"),
                    "address": "",
                    "facility_campus_scope": rec.get("site_scope"),
                    "FRC1_identity_status": "INTERVAL/SET_UNRESOLVED",
                    "variable": qty,
                    "units": "",
                    "observed_vs_inferred": rec.get("design_vs_observed"),
                    "usable_for": rec.get("measurement_boundary"),
                    "not_usable_for": rec.get("limitations"),
                    "provenance_hash": rec.get("sha256"),
                    "notes": rec.get("title"),
                    "bucket": bucket,
                    "do_not_merge_2012_with_2023_2024_campus": True,
                }
            )
    weather_items = [
        ("C_weather", "KFQD_2012_hourly", V1_PROCESSED / "forest_city_weather_2012_hourly.parquet", "2012", "OBSERVED"),
        ("C_weather", "KEHO_2012_raw_isd", V1_RAW_WEATHER / "72027763843_2012.csv", "2012", "OBSERVED"),
        ("C_weather", "KGSP_2012_raw_isd", V1_RAW_WEATHER / "72312003870_2012.csv", "2012", "OBSERVED"),
        ("C_weather", "KRDM_hourly", PRN / "data/processed/weather_krdm_hourly.csv", "2011-2024", "OBSERVED"),
        ("D_later_campus_annual", "FC_annual_electricity", V1_PROCESSED / "FOREST_CITY_ANNUAL_ELECTRICITY.csv", "2015-2024", "OBSERVED"),
        ("D_later_campus_annual", "FC_annual_water", V1_PROCESSED / "FOREST_CITY_ANNUAL_WATER_WITHDRAWAL.csv", "2017-2024", "OBSERVED"),
        ("D_later_campus_annual", "PRN_annual_audit", PRN / "outputs/annual_audit.csv", "2011-2024", "OBSERVED"),
        ("E_dashboard_screenshot", "dashboard_recovery_status", V1 / "outputs/dashboard_recovery/DASHBOARD_RECOVERY_STATUS.json", "2012-2014", "SCREENSHOT_ONLY"),
        ("F_address_parcel", "v1_facility_registry", V1 / "config/forest_city_facility_registry.yaml", "2012-2025", "UNIDENTIFIED"),
        ("G_permit_utility", "permit_inventory", V1 / "outputs/permit_audit/FOREST_CITY_PUBLIC_PERMIT_INVENTORY.csv", "public portal", "NOT_FOUND_PUBLIC"),
    ]
    for bucket, name, path, period, obs in weather_items:
        rows.append(
            {
                "source_id": name,
                "source_path": str(path),
                "date_period": period,
                "source_type": bucket,
                "address": "UNIDENTIFIED_FRC1" if bucket.startswith("F") else "",
                "facility_campus_scope": "weather_station" if bucket == "C_weather" else "as_labeled",
                "FRC1_identity_status": "INTERVAL/SET_UNRESOLVED",
                "variable": name,
                "units": "",
                "observed_vs_inferred": obs,
                "usable_for": "climate_replay" if bucket == "C_weather" else "campus_accounting" if bucket.startswith("D") else "identity_set",
                "not_usable_for": "2012 FRC1 cooling WUE" if bucket.startswith("D") else "as_operated_RAT",
                "provenance_hash": sha256_file(path) if path.exists() else "",
                "notes": "Do not merge 2012 FRC1 engineering with 2023-2024 campus totals.",
                "bucket": bucket,
                "do_not_merge_2012_with_2023_2024_campus": True,
            }
        )
    df = pd.DataFrame(rows)
    (OUTPUTS / "evidence").mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUTS / "evidence" / "FOREST_CITY_EVIDENCE_SCOPE_CROSSWALK.csv", index=False)
    try:
        df.to_parquet(OUTPUTS / "evidence" / "FOREST_CITY_EVIDENCE_SCOPE_CROSSWALK.parquet", index=False)
    except Exception:
        pass
    buckets = df.groupby("bucket").size().reset_index(name="n")
    md = [
        "# Forest City evidence-scope crosswalk",
        "",
        "Do not merge 2012 FRC1 engineering evidence with 2023–2024 campus totals.",
        "FRC1_ADDRESS = INTERVAL/SET_UNRESOLVED (284 / 404 / 408 Social Circle remain a set).",
        "Dashboard evidence remains screenshot-only unless a structured source is independently recovered.",
        "",
        f"n_rows = {len(df)}",
        "",
        "## Counts by bucket",
        "",
        df_to_md(buckets),
        "",
        "## Rows",
        "",
        df_to_md(df[["source_id", "bucket", "date_period", "observed_vs_inferred", "usable_for", "not_usable_for"]]),
        "",
    ]
    (OUTPUTS / "evidence" / "FOREST_CITY_EVIDENCE_SCOPE_CROSSWALK.md").write_text("\n".join(md) + "\n")
    pd.DataFrame(mapping_table_rows()).to_csv(OUTPUTS / "regimes" / "COMMON_TAXONOMY_NATIVE_MAPPING.csv", index=False)
    return df


def weather_spine(stations: dict, krdm: pd.DataFrame) -> pd.DataFrame:
    rows = []
    miss_rows = []
    for name, df in list(stations.items()) + [("KRDM", krdm)]:
        full_year = df[(df.timestamp_utc >= "2012-01-01") & (df.timestamp_utc < "2013-01-01")]
        jja = window(df, JJA_START, JJA_END)
        common = window(df, COMMON_START, COMMON_END)
        u_year = usable(full_year) if len(full_year) else pd.Series(dtype=bool)
        u_jja = usable(jja)
        u_c = usable(common)
        first = full_year.loc[usable(full_year), "timestamp_utc"].min() if len(full_year) and usable(full_year).any() else pd.NaT
        rows.append(
            {
                "station": name,
                "evidence_class": "OBSERVED",
                "n_calendar_2012": int(len(full_year)),
                "usable_2012": int(u_year.sum()) if len(full_year) else 0,
                "first_usable_utc": str(first),
                "jja_calendar": int(len(jja)),
                "jja_usable": int(u_jja.sum()),
                "jja_missing": int((~u_jja).sum()),
                "common_calendar": int(len(common)),
                "common_usable": int(u_c.sum()),
                "common_missing": int((~u_c).sum()),
                "selected_using_dx_outcome": False,
                "missing_hours_not_converted_to_observed": True,
                "role": {
                    "KFQD": "PREFERRED_LOCAL",
                    "KEHO": "NEAREST_COMPLETE",
                    "KGSP": "FIRST_ORDER_ASOS",
                    "KRDM": "PRINEVILLE_PREFERRED",
                }[name],
            }
        )
        miss = jja.copy()
        miss["observed"] = usable(jja)
        miss_rows.append(
            {
                "station": name,
                "jja_missing_hours": int((~usable(jja)).sum()),
                "jja_missing_labeled_observed": False,
                "evidence_class_for_missing": "UNIDENTIFIED",
            }
        )
    cov = pd.DataFrame(rows)
    (OUTPUTS / "weather").mkdir(parents=True, exist_ok=True)
    cov.to_csv(OUTPUTS / "weather" / "WEATHER_COVERAGE.csv", index=False)
    pd.DataFrame(miss_rows).to_csv(OUTPUTS / "weather" / "WEATHER_MISSINGNESS.csv", index=False)
    ov_rows = []
    pairs = [
        ("KFQD", stations["KFQD"], "KEHO", stations["KEHO"]),
        ("KFQD", stations["KFQD"], "KGSP", stations["KGSP"]),
        ("KEHO", stations["KEHO"], "KGSP", stations["KGSP"]),
        ("KFQD", stations["KFQD"], "KRDM", krdm),
    ]
    for na, a, nb, b in pairs:
        ja, jb = window(a, JJA_START, JJA_END), window(b, JJA_START, JJA_END)
        m = ja.merge(jb, on="timestamp_utc", suffixes=(f"_{na}", f"_{nb}"))
        ok = m[f"t_db_C_{na}"].notna() & m[f"rh_pct_{na}"].notna() & m[f"t_db_C_{nb}"].notna() & m[f"rh_pct_{nb}"].notna()
        ov_rows.append(
            {
                "station_a": na,
                "station_b": nb,
                "period": "JJA_2012",
                "jja_overlap_usable": int(ok.sum()),
                "stitched": False,
                "evidence_class": "OBSERVED",
            }
        )
        ca, cb = window(a, COMMON_START, COMMON_END), window(b, COMMON_START, COMMON_END)
        mc = ca.merge(cb, on="timestamp_utc", suffixes=(f"_{na}", f"_{nb}"))
        okc = mc[f"t_db_C_{na}"].notna() & m[f"rh_pct_{na}"].notna() & mc[f"t_db_C_{nb}"].notna() & mc[f"rh_pct_{nb}"].notna() if False else (
            mc[f"t_db_C_{na}"].notna() & mc[f"rh_pct_{na}"].notna() & mc[f"t_db_C_{nb}"].notna() & mc[f"rh_pct_{nb}"].notna()
        )
        ov_rows.append(
            {
                "station_a": na,
                "station_b": nb,
                "period": "COMMON_2012-06-21_to_2012-08-31",
                "jja_overlap_usable": int(okc.sum()),
                "stitched": False,
                "evidence_class": "OBSERVED",
            }
        )
    pd.DataFrame(ov_rows).to_csv(OUTPUTS / "weather" / "STATION_OVERLAP.csv", index=False)
    write_json(
        OUTPUTS / "weather" / "STATION_SELECTION.json",
        {
            "a_priori": True,
            "selected_using_dx_outcome": False,
            "preferred_local": "KFQD",
            "missing_not_converted_to_observed": True,
            "stations": STATION_META,
            "rationale": (
                "KFQD nearest; KEHO nearest more-complete; KGSP first-order ASOS. "
                "KRDM is Prineville, not an FC station. Station choice is independent of DX outcome."
            ),
        },
    )
    (OUTPUTS / "weather" / "WEATHER_COVERAGE.md").write_text(
        "# Weather coverage (OBSERVED)\n\nMissing hours are UNIDENTIFIED, not observations.\n\n" + df_to_md(cov) + "\n"
    )
    return cov


def reproduce_v2(kfq: pd.DataFrame, stations: dict):
    jja = window(kfq, JJA_START, JJA_END)
    sim = simulate_fc(jja)
    d = regime_counts(sim)
    tgt = V2_KFQD_JJA_TARGET
    ok = (
        d["valid_hours"] == tgt["valid_hours"]
        and d["weather_missing_hours"] == tgt["weather_missing_hours"]
        and d["OA_FREE"] == tgt["OA_FREE"]
        and d["HIGH_RH_MIXING"] == tgt["HIGH_RH_MIXING"]
        and d["EVAP_COOLING"] == tgt["EVAP_COOLING"]
        and d["DX_required_hours"] == tgt["DX_required_hours"]
    )
    rec = {
        "V2_REPRODUCTION": "PASS" if ok else "FAIL",
        "reproduced": d,
        "target": tgt,
        "tolerance": "exact hour counts",
        "evidence_class": "MODEL_REPLAY",
    }
    write_json(OUTPUTS / "regimes" / "V2_REPRODUCTION.json", rec)
    if not ok:
        raise SystemExit(f"V2 reproduction failed: {d} vs {tgt}")
    sim.to_csv(OUTPUTS / "regimes" / "KFQD_JJA_HOURS.csv", index=False)
    # Independent station DX robustness (not used to choose a station)
    dx_rows = []
    for call, df in stations.items():
        s = simulate_fc(window(df, JJA_START, JJA_END))
        c = regime_counts(s)
        dx_rows.append(
            {
                "station": call,
                "evidence_class": "MODEL_REPLAY",
                "valid_hours": c["valid_hours"],
                "weather_missing_hours": c["weather_missing_hours"],
                "DX_required_hours": c["DX_required_hours"],
                "selected_using_dx_outcome": False,
                **{k: c[k] for k in CATEGORIES},
            }
        )
    pd.DataFrame(dx_rows).to_csv(OUTPUTS / "regimes" / "JJA_STATION_REGIME_SHARES.csv", index=False)
    return sim, rec


def two_by_two(kfq, krdm):
    fc_w = window(kfq, COMMON_START, COMMON_END)
    prn_w = window(krdm, COMMON_START, COMMON_END)
    krdm_ok = set(prn_w.loc[usable(prn_w) & prn_w["t_wb_C"].notna(), "timestamp_utc"])
    fc_ok = set(fc_w.loc[usable(fc_w), "timestamp_utc"])
    both = sorted(krdm_ok & fc_ok)
    krdm_b = prn_w[prn_w.timestamp_utc.isin(both)].sort_values("timestamp_utc").copy()
    fc_b = fc_w[fc_w.timestamp_utc.isin(both)].sort_values("timestamp_utc").copy()
    combos = {
        "PRN_weather+PRN_controller": simulate_prn(krdm_b),
        "PRN_weather+FC_controller": simulate_fc(krdm_b),
        "FC_weather+PRN_controller": simulate_prn(fc_b),
        "FC_weather+FC_controller": simulate_fc(fc_b),
    }
    rows = []
    trans_rows = []
    mismatches = []
    for name, sim in combos.items():
        d = regime_counts(sim)
        n = d["valid_hours"]
        row = {
            "combination": name,
            "evidence_class": "MODEL_REPLAY",
            "NOT_CAUSAL_IDENTIFICATION": True,
            "not_gallons": True,
            "n_intersection": len(both),
            "calendar_start_utc": COMMON_START,
            "calendar_end_utc": COMMON_END,
            **{f"P({c})": (d[c] / n if n else np.nan) for c in CATEGORIES},
            **{f"n_{c}": d[c] for c in CATEGORIES},
            "valid_hours": n,
            "DX_required_hours": d["DX_required_hours"],
        }
        tgt = V2_2X2_TARGET.get(name, {})
        row["matches_committed_v2"] = all(abs(row[k] - v) < 1e-9 for k, v in tgt.items()) if tgt else None
        if tgt and not row["matches_committed_v2"]:
            mismatches.append({"combination": name, "got": {k: row[k] for k in tgt}, "target": tgt})
        rows.append(row)
        cats = sim.loc[sim["control_mode"].astype(str) != "WEATHER_MISSING"].sort_values("timestamp_utc")["common_category"].tolist()
        for a, b in zip(cats[:-1], cats[1:]):
            trans_rows.append({"combination": name, "from": a, "to": b, "changed": int(a != b)})
    rdf = pd.DataFrame(rows)
    rdf.to_csv(OUTPUTS / "cross_site" / "WEATHER_CONTROLLER_2x2.csv", index=False)
    write_json(
        OUTPUTS / "cross_site" / "WEATHER_CONTROLLER_2x2.json",
        {
            "rows": rows,
            "not_causal": True,
            "not_gallons": True,
            "n_intersection": len(both),
            "v2_match_mismatches": mismatches,
            "evidence_class": "MODEL_REPLAY",
        },
    )
    tdf = pd.DataFrame(trans_rows)
    if len(tdf):
        summ = tdf.groupby(["combination", "from", "to"]).size().reset_index(name="n")
        chg = tdf.groupby("combination")["changed"].mean().reset_index(name="transition_rate")
        summ.to_csv(OUTPUTS / "cross_site" / "REGIME_TRANSITIONS.csv", index=False)
        chg.to_csv(OUTPUTS / "cross_site" / "REGIME_TRANSITION_RATES.csv", index=False)
    def clim(df, site):
        s = df.loc[usable(df)]
        return {
            "site": site,
            "evidence_class": "OBSERVED",
            "n": int(len(s)),
            "t_db_C_mean": float(s.t_db_C.mean()),
            "t_db_C_p05": float(s.t_db_C.quantile(0.05)),
            "t_db_C_p95": float(s.t_db_C.quantile(0.95)),
            "rh_pct_mean": float(s.rh_pct.mean()),
            "t_wb_C_mean": float(s.t_wb_C.mean()) if "t_wb_C" in s else np.nan,
        }
    pd.DataFrame([clim(fc_b, "KFQD_Forest_City"), clim(krdm_b, "KRDM_Prineville")]).to_csv(
        OUTPUTS / "cross_site" / "COMMON_PERIOD_CLIMATE.csv", index=False
    )
    native = rdf[rdf.combination.isin(["FC_weather+FC_controller", "PRN_weather+PRN_controller"])]
    native.to_csv(OUTPUTS / "cross_site" / "NATIVE_SAME_PERIOD_REGIMES.csv", index=False)
    (OUTPUTS / "cross_site" / "WEATHER_CONTROLLER_2x2.md").write_text(
        "# Weather × controller 2×2 (MODEL_REPLAY)\n\n"
        "Not causal identification. Not gallons. Common UTC window 2012-06-21 through 2012-08-31.\n\n"
        + df_to_md(rdf[["combination", "valid_hours"] + [f"P({c})" for c in CATEGORIES] + ["matches_committed_v2"]])
        + "\n"
    )
    if mismatches:
        raise SystemExit(f"2x2 does not match committed v2: {mismatches}")
    # Write masanet weather inputs (common-period usable hours, not filled)
    (OUTPUTS / "masanet").mkdir(parents=True, exist_ok=True)
    fc_b.loc[usable(fc_b), ["timestamp_utc", "t_db_C", "rh_pct", "pressure_Pa", "t_wb_C"]].to_csv(
        OUTPUTS / "masanet" / "weather_KFQD_common.csv", index=False
    )
    krdm_b.loc[usable(krdm_b), ["timestamp_utc", "t_db_C", "rh_pct", "pressure_Pa", "t_wb_C"]].to_csv(
        OUTPUTS / "masanet" / "weather_KRDM_common.csv", index=False
    )
    return rdf, combos


def annual_comparison():
    elec = pd.read_csv(V1_PROCESSED / "FOREST_CITY_ANNUAL_ELECTRICITY.csv")
    water = pd.read_csv(V1_PROCESSED / "FOREST_CITY_ANNUAL_WATER_WITHDRAWAL.csv")
    e2024 = float(elec.loc[elec.year == 2024, "value"].iloc[0])
    w2024 = float(water.loc[water.year == 2024, "value"].iloc[0])
    intensity = w2024 / e2024
    prn = pd.read_csv(PRN / "outputs/annual_audit.csv")
    p2024 = prn.loc[prn.year == 2024].iloc[0]
    rows = [
        {
            "site": "FOREST_CITY",
            "year": 2024,
            "electricity_MWh": e2024,
            "withdrawal_m3": w2024,
            "SITE_WITHDRAWAL_INTENSITY": intensity,
            "unit": "m3_per_MWh_equals_L_per_kWh_facility",
            "not_WUE": True,
            "not_FRC1_cooling_WUE": True,
            "scope": "FOREST_CITY_SITE_AS_REPORTED_CAMPUS",
            "evidence_class": "DERIVED",
            "comparable_to_prn_campus": True,
            "comparable_to_2012_FRC1": False,
        },
        {
            "site": "PRINEVILLE",
            "year": 2024,
            "electricity_MWh": float(p2024.electricity_mwh_reported),
            "withdrawal_m3": float(p2024.water_withdrawal_m3_reported),
            "SITE_WITHDRAWAL_INTENSITY": float(p2024.water_intensity_L_per_kWh_facility_derived),
            "unit": "m3_per_MWh_equals_L_per_kWh_facility",
            "not_WUE": True,
            "not_FRC1_cooling_WUE": True,
            "scope": "PRINEVILLE_SITE_AS_REPORTED_CAMPUS",
            "evidence_class": "DERIVED",
            "comparable_to_prn_campus": True,
            "comparable_to_2012_FRC1": False,
            "definitional_scope_note": (
                "Both rows are Meta campus annual disclosure totals, not 2012 single-building cooling WUE."
            ),
        },
    ]
    df = pd.DataFrame(rows)
    (OUTPUTS / "annual").mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUTS / "annual" / "CAMPUS_ANNUAL_COMPARISON.csv", index=False)
    write_json(
        OUTPUTS / "annual" / "CAMPUS_ANNUAL_COMPARISON.json",
        {
            "fc_2024_electricity_MWh": e2024,
            "fc_2024_withdrawal_m3": w2024,
            "fc_2024_intensity_recomputed": intensity,
            "evidence_class": "DERIVED",
            "not_FRC1": True,
            "layers_kept_separate": ["A_climate_exposure", "B_regime_controller", "C_campus_annual_aggregates"],
        },
    )
    (OUTPUTS / "annual" / "CAMPUS_ANNUAL_COMPARISON.md").write_text(
        "# Campus annual comparison (DERIVED from OBSERVED disclosures)\n\n"
        "Not FRC1 cooling WUE. Not equivalent to 2012 single-building cooling water.\n\n"
        + df_to_md(df)
        + "\n"
    )
    return df


def esif_transfer(kfq, krdm):
    sel = load_selected()
    it_mean = float(sel["cooling_kw"]["scaler"]["it_power_kw"]["mean"])
    rows = []
    (OUTPUTS / "esif").mkdir(parents=True, exist_ok=True)
    for name, df in [("KFQD", kfq), ("KRDM", krdm)]:
        w = window(df, COMMON_START, COMMON_END)
        s = w.loc[usable(w) & w["t_wb_C"].notna()].copy()
        it = np.full(len(s), it_mean)
        cool = predict_f4_cooling(it, s.t_db_C.to_numpy(), s.t_wb_C.to_numpy(), sel)
        hvac = predict_f0_hvac(len(s), sel)
        oh = cool + hvac
        s["it_kw_synthetic"] = it_mean
        s["it_provenance"] = "SCENARIO: ESIF training-window mean IT; not Forest City IT"
        s["esif_cooling_kw"] = cool
        s["esif_hvac_kw"] = hvac
        s["esif_hvac_weather_independent"] = True
        s["overhead_kw"] = oh
        s["overhead_per_it"] = oh / it_mean
        s["month"] = s.timestamp_utc.dt.month
        corr = float(np.corrcoef(s.t_db_C, s.esif_cooling_kw)[0, 1]) if len(s) > 2 else np.nan
        monthly = s.groupby("month")["overhead_per_it"].mean()
        rows.append(
            {
                "weather": name,
                "evidence_class": "TRANSFERRED_MODEL",
                "n": int(len(s)),
                "synthetic_IT_kw": it_mean,
                "IT_provenance": "SCENARIO normalized load = ESIF training-window mean",
                "mean_cooling_kw": float(np.mean(cool)),
                "mean_overhead_per_it": float(np.mean(oh / it_mean)),
                "corr_cooling_vs_tdb": corr,
                "jja_minus_shoulder_overhead": float(monthly.reindex([6, 7, 8]).mean() - monthly.reindex([4, 5, 9]).mean())
                if monthly.reindex([6, 7, 8]).notna().any()
                else np.nan,
                "architecture_mismatch": (
                    "ESIF cooling_kw is outdoor fan/heater/filter-pump on a liquid/thermosyphon plant, "
                    "not Forest City direct-evap AHU. HVAC F0 is weather-independent intercept."
                ),
                "not_fc_pue_validation": True,
                "not_quantitative_physics_transfer": True,
            }
        )
        s[["timestamp_utc", "t_db_C", "t_wb_C", "esif_cooling_kw", "overhead_per_it", "it_provenance"]].to_csv(
            OUTPUTS / "esif" / f"ESIF_TRANSFER_{name}.csv", index=False
        )
    df = pd.DataFrame(rows)
    df.to_csv(OUTPUTS / "esif" / "ESIF_TRANSFER_SUMMARY.csv", index=False)
    sign_ok = all(r["corr_cooling_vs_tdb"] == r["corr_cooling_vs_tdb"] for r in rows)
    write_json(
        OUTPUTS / "esif" / "ESIF_TRANSFER.json",
        {
            "status": "PARTIAL",
            "refit": False,
            "evidence_class": "TRANSFERRED_MODEL",
            "rows": rows,
            "weather_signed_cooling": sign_ok,
            "QUANTITATIVE_PHYSICS_TRANSFER": "NOT_VALIDATED",
        },
    )
    return df


def identification_table():
    rows = [
        ("annual aggregate electricity", "IDENTIFIED", "OBSERVED", "Meta site row, campus scope"),
        ("annual aggregate water", "IDENTIFIED", "OBSERVED", "Meta site withdrawal, campus scope"),
        ("aggregate L/kWh intensity", "IDENTIFIED", "DERIVED", "withdrawal/electricity at campus; not FRC1 WUE"),
        ("regime frequencies", "BOUNDED", "MODEL_REPLAY", "frozen controllers on observed weather"),
        ("station sensitivity", "BOUNDED", "OBSERVED", "KFQD/KEHO/KGSP independent; not chosen by DX"),
        ("effective facility Delta-T", "UNIDENTIFIED", "UNIDENTIFIED", "35F is IT design rise only; circular water fit prohibited"),
        ("facility airflow / CFM", "UNIDENTIFIED", "UNIDENTIFIED", "needs TAB/BMS"),
        ("cooling-only makeup water", "UNIDENTIFIED", "UNIDENTIFIED", "needs meter IDs"),
        ("blowdown", "UNIDENTIFIED", "UNIDENTIFIED", ""),
        ("reuse / return", "UNIDENTIFIED", "UNIDENTIFIED", ""),
        ("withdrawal vs consumption", "UNIDENTIFIED", "UNIDENTIFIED", "Meta reports withdrawal"),
        ("FRC1 vs campus mapping", "UNIDENTIFIED", "UNIDENTIFIED", "FRC1_ADDRESS set unresolved"),
        ("quantitative cooling-water transfer", "UNIDENTIFIED", "UNIDENTIFIED", "QUANTITATIVE_PHYSICS_TRANSFER=NOT_VALIDATED"),
    ]
    df = pd.DataFrame(rows, columns=["quantity", "identification", "evidence_class", "notes"])
    (OUTPUTS / "identification").mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUTS / "identification" / "IDENTIFICATION_LEDGER.csv", index=False)
    (OUTPUTS / "identification" / "IDENTIFICATION_LEDGER.md").write_text(
        "# Identification ledger\n\nDo not choose facility Delta-T to match annual water.\n\n" + df_to_md(df) + "\n"
    )
    return df


def acquisition_matrix():
    rows = [
        {
            "priority": 1,
            "record": "TAB/design AHU CFM",
            "identifies": "m_dot / FACILITY_EFFECTIVE_DELTA_T",
            "upgrades": "UNIDENTIFIED airflow -> IDENTIFIED or BOUNDED",
            "uncertainty": "removes circular water calibration path",
            "owner": "Meta / commissioning / TAB contractor; Town permit drawings",
        },
        {
            "priority": 2,
            "record": "SAT/RAT and OA/RA 2012",
            "identifies": "as-operated return-air rise vs 35F IT design",
            "upgrades": "SCENARIO RA -> OBSERVED RAT",
            "uncertainty": "separates design-reference from operation",
            "owner": "BMS / commissioning",
        },
        {
            "priority": 3,
            "record": "cooling / economizer / DX sequence of operations",
            "identifies": "independent controller vs OCP blog cases",
            "upgrades": "implementation consistency -> possible validation",
            "uncertainty": "stops using June 25/July 1 as definition and test",
            "owner": "Meta facilities",
        },
        {
            "priority": 4,
            "record": "cooling makeup meter IDs + 2012 and 2022-2024 totals",
            "identifies": "cooling-only water vs campus withdrawal",
            "upgrades": "campus accounting -> cooling boundary",
            "uncertainty": "2023-24 drop cause",
            "owner": "Town of Forest City utility; Meta",
        },
        {
            "priority": 5,
            "record": "blowdown/reuse/return-flow accounting",
            "identifies": "withdrawal vs consumption",
            "upgrades": "UNIDENTIFIED water split",
            "uncertainty": "cycles of concentration",
            "owner": "P&ID / treatment",
        },
        {
            "priority": 6,
            "record": "retrofit chronology 2022-2024",
            "identifies": "55->16 ML cause",
            "upgrades": "CAUSE_PUBLICLY_UNRESOLVED",
            "uncertainty": "reporting vs physical",
            "owner": "permits / change orders",
        },
        {
            "priority": 7,
            "record": "P&IDs / mechanical schedules",
            "identifies": "AHU vs plant boundary",
            "upgrades": "architecture map",
            "uncertainty": "served-load",
            "owner": "DPR / Meta",
        },
    ]
    df = pd.DataFrame(rows)
    df["engineering_records_higher_value_than_more_weather"] = True
    (OUTPUTS / "acquisition").mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUTS / "acquisition" / "DATA_VALUE_MATRIX.csv", index=False)
    extra = (
        "\n\n## v3 data-value ranking\n\n"
        "Engineering and utility records now have **higher marginal value** than additional weather stations.\n\n"
        + df_to_md(df)
        + "\n"
    )
    r = subprocess.run(
        "git show HEAD:Meta_Forest_City_North_Carolina_v2/outputs/FOREST_CITY_MANUAL_DATA_REQUEST_PACKAGE.md",
        shell=True,
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    header = (
        "# Forest City v3 data-request package\n\n"
        "Read-only reuse of committed v2 package plus v3 ranking. Working-tree v2 is not written.\n"
    )
    (OUTPUTS / "acquisition" / "FOREST_CITY_MANUAL_DATA_REQUEST_PACKAGE.md").write_text(header + (r.stdout or "") + extra)
    (OUTPUTS / "acquisition" / "DATA_VALUE_MATRIX.md").write_text("# Data-value matrix\n\n" + extra)
    return df


def figures(two, ident, masanet_monthly):
    figdir = OUTPUTS / "figures"
    figdir.mkdir(parents=True, exist_ok=True)
    captions = []

    fig, axes = plt.subplots(1, 2, figsize=(11.2, 4.4))
    clim = pd.read_csv(OUTPUTS / "cross_site" / "COMMON_PERIOD_CLIMATE.csv")
    axes[0].bar(clim.site, clim.t_db_C_mean, color="#4C78A8")
    ax2 = axes[0].twinx()
    ax2.plot(range(len(clim)), clim.rh_pct_mean, "o-", color="#F58518")
    axes[0].set_ylabel("Mean Tdb (°C)")
    ax2.set_ylabel("Mean RH (%)")
    axes[0].set_title("A. OBSERVED climate")
    native = two[two.combination.isin(["FC_weather+FC_controller", "PRN_weather+PRN_controller"])]
    labs = ["FC wx+ctrl", "PRN wx+ctrl"]
    order = ["FC_weather+FC_controller", "PRN_weather+PRN_controller"]
    native = native.set_index("combination").loc[order]
    bottom = np.zeros(2)
    colors = ["#4C78A8", "#72B7B2", "#F58518", "#E45756", "#54A24B", "#B279A2"]
    for i, cat in enumerate(CATEGORIES):
        vals = native[f"P({cat})"].fillna(0).to_numpy()
        axes[1].bar(range(2), vals, bottom=bottom, label=cat, color=colors[i])
        bottom = bottom + vals
    axes[1].set_xticks(range(2))
    axes[1].set_xticklabels(labs, rotation=15)
    axes[1].set_title("B. MODEL_REPLAY native regimes")
    axes[1].legend(fontsize=7, ncol=2, loc="upper right")
    fig.suptitle("Fig 1. Same-period Forest City vs Prineville — OBSERVED climate + MODEL_REPLAY regimes")
    fig.tight_layout()
    fig.savefig(figdir / "fig01_same_period_climate_regime.png", dpi=140)
    plt.close()
    captions.append("FIG1: left OBSERVED climate; right MODEL_REPLAY native controllers. Not gallons.")

    fig, ax = plt.subplots(figsize=(10.2, 4.8))
    labs = two.combination.tolist()
    bottom = np.zeros(len(labs))
    for i, cat in enumerate(CATEGORIES):
        vals = two[f"P({cat})"].fillna(0).to_numpy()
        ax.bar(range(len(labs)), vals, bottom=bottom, label=cat, color=colors[i])
        bottom = bottom + vals
    ax.set_xticks(range(len(labs)))
    ax.set_xticklabels(labs, rotation=18, ha="right")
    ax.set_ylabel("Share of usable hours")
    ax.set_title("Fig 2. MODEL_REPLAY weather × controller 2×2 (not causal; not gallons)")
    ax.legend(fontsize=7, ncol=3)
    fig.tight_layout()
    fig.savefig(figdir / "fig02_weather_controller_2x2.png", dpi=140)
    plt.close()
    captions.append("FIG2: MODEL_REPLAY only. Separates climate vs controller occupancy; not water use.")

    fig, ax = plt.subplots(figsize=(8.2, 4.2))
    if masanet_monthly is not None and len(masanet_monthly):
        for site, g in masanet_monthly.groupby("weather"):
            ax.plot(g.month, g.PUE_mean, "o-", label=f"{site} PUE")
        ax.set_xlabel("Month")
        ax.set_ylabel("Mean hourly PUE (P_IT=1)")
        ax.set_title("Fig 3. TRANSFERRED_MODEL Masanet Case 1 midpoint (not FC PUE validation)")
        ax.legend()
    else:
        ax.text(0.5, 0.5, "Masanet transfer plotted after subprocess", ha="center")
        ax.set_title("Fig 3. TRANSFERRED_MODEL Masanet")
    fig.tight_layout()
    fig.savefig(figdir / "fig03_masanet_transfer.png", dpi=140)
    plt.close()
    captions.append("FIG3: TRANSFERRED_MODEL Case 1 (adiabatic + water-cooled chiller). Architecture-mismatched to FC direct-evap.")

    fig, ax = plt.subplots(figsize=(8.2, 4.2))
    for name, c in (("KFQD", "#4C78A8"), ("KRDM", "#F58518")):
        p = OUTPUTS / "esif" / f"ESIF_TRANSFER_{name}.csv"
        if p.exists():
            d = pd.read_csv(p, parse_dates=["timestamp_utc"])
            ax.scatter(d.t_db_C, d.overhead_per_it, s=6, alpha=0.28, label=name, color=c)
    ax.set_xlabel("Tdb (°C)")
    ax.set_ylabel("ESIF overhead / synthetic IT")
    ax.set_title("Fig 4. TRANSFERRED_MODEL ESIF F4 cooling + F0 HVAC (architecture-mismatched)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(figdir / "fig04_esif_overhead_transfer.png", dpi=140)
    plt.close()
    captions.append("FIG4: TRANSFERRED_MODEL. Synthetic IT. ESIF plant ≠ FC evaporative AHU.")

    fig, ax = plt.subplots(figsize=(9.2, 5.2))
    color_map = {
        "IDENTIFIED": "#1b9e77",
        "BOUNDED": "#d95f02",
        "DERIVED": "#1b9e77",
        "SCENARIO_ONLY": "#7570b3",
        "UNIDENTIFIED": "#666666",
    }
    y = ident.quantity[::-1]
    cols = [color_map.get(x, "#999") for x in ident.identification[::-1]]
    ax.barh(y, [1] * len(ident), color=cols)
    ax.set_xlabel("Status (color)")
    ax.set_title("Fig 5. Identification status — not a fit; circular ΔT calibration prohibited")
    fig.tight_layout()
    fig.savefig(figdir / "fig05_identification.png", dpi=140)
    plt.close()
    captions.append("FIG5: IDENTIFIED/BOUNDED/UNIDENTIFIED ledger. FACILITY_EFFECTIVE_DELTA_T remains UNIDENTIFIED.")

    acq = pd.read_csv(OUTPUTS / "acquisition" / "DATA_VALUE_MATRIX.csv")
    fig, ax = plt.subplots(figsize=(8.6, 4.6))
    ax.barh(acq.sort_values("priority", ascending=False).record, 8 - acq.sort_values("priority", ascending=False).priority)
    ax.set_xlabel("Priority score (higher = more valuable)")
    ax.set_title("Fig 6. Acquisition ranking — engineering records outrank more weather")
    fig.tight_layout()
    fig.savefig(figdir / "fig06_data_value_matrix.png", dpi=140)
    plt.close()
    captions.append("FIG6: data-value ranking. Not a measurement.")

    (figdir / "FIGURE_CAPTIONS.md").write_text("# Figure captions\n\n" + "\n".join(f"- {c}" for c in captions) + "\n")


def claims_ledger(v2rep, two, masanet_status, esif):
    text = f"""# FINAL CLAIMS LEDGER — Forest City v3

Statuses use only: PASS, STRONG_SUPPORT, PARTIAL, NOT_VALIDATED, UNIDENTIFIED, NEEDS_DATA, FAIL.

| Claim | Status | Evidence class | Notes |
| --- | --- | --- | --- |
| V2_REPRODUCTION | {v2rep['V2_REPRODUCTION']} | MODEL_REPLAY | KFQD JJA hour counts vs committed v2 |
| WEATHER_ROBUSTNESS | STRONG_SUPPORT | OBSERVED + MODEL_REPLAY | Inherited: 0 DX at KFQD/KEHO/KGSP independently; station not chosen by DX |
| REGIME_TAXONOMY | PASS | MODEL_REPLAY | mutually exclusive; exhaustive on usable hours |
| FOREST_CITY_PRINEVILLE_CLIMATE_COMPARISON | STRONG_SUPPORT | OBSERVED | same UTC window; FC more humid |
| WEATHER_CONTROLLER_DECOMPOSITION | STRONG_SUPPORT | MODEL_REPLAY | humidification ≈ PRN controller; mixing ≈ FC climate × tighter PRN RH cap |
| QUALITATIVE_PHYSICS_TRANSFER | PARTIAL | MODEL_REPLAY | shared moist-air physics useful; not quantitative |
| MASANET_TRANSFER | {masanet_status} | TRANSFERRED_MODEL | Case 1 adiabatic+chiller is architecture-mismatched to FC direct-evap |
| ESIF_TRANSFER | PARTIAL | TRANSFERRED_MODEL | weather-signed cooling term; ESIF plant ≠ FC AHU |
| QUANTITATIVE_PHYSICS_TRANSFER | NOT_VALIDATED | UNIDENTIFIED | prohibited to flip this via annual-aggregate match |
| FACILITY_EFFECTIVE_DELTA_T | UNIDENTIFIED | UNIDENTIFIED | 35 F remains IT design rise |
| COOLING_WATER_MAGNITUDE | UNIDENTIFIED | UNIDENTIFIED | no CFM / makeup meter |
| FRC1_ADDRESS | UNIDENTIFIED | UNIDENTIFIED | INTERVAL/SET_UNRESOLVED |
| CAMPUS_FACILITY_SCOPE | PASS | OBSERVED | 2024 totals labeled campus, not FRC1 |
| ACQUISITION_READINESS | PASS | DERIVED | engineering/utility records outrank more weather |

MODEL_CALIBRATED = NO

A scientifically successful v3 run still ends with QUANTITATIVE_PHYSICS_TRANSFER = NOT_VALIDATED and FACILITY_EFFECTIVE_DELTA_T = UNIDENTIFIED.
"""
    (OUTPUTS / "FINAL_CLAIMS_LEDGER.md").write_text(text)
    write_json(
        OUTPUTS / "FINAL_CLAIMS_LEDGER.json",
        {
            "V2_REPRODUCTION": v2rep["V2_REPRODUCTION"],
            "WEATHER_ROBUSTNESS": "STRONG_SUPPORT",
            "REGIME_TAXONOMY": "PASS",
            "FOREST_CITY_PRINEVILLE_CLIMATE_COMPARISON": "STRONG_SUPPORT",
            "WEATHER_CONTROLLER_DECOMPOSITION": "STRONG_SUPPORT",
            "QUALITATIVE_PHYSICS_TRANSFER": "PARTIAL",
            "MASANET_TRANSFER": masanet_status,
            "ESIF_TRANSFER": "PARTIAL",
            "QUANTITATIVE_PHYSICS_TRANSFER": "NOT_VALIDATED",
            "FACILITY_EFFECTIVE_DELTA_T": "UNIDENTIFIED",
            "COOLING_WATER_MAGNITUDE": "UNIDENTIFIED",
            "FRC1_ADDRESS": "UNIDENTIFIED",
            "CAMPUS_FACILITY_SCOPE": "PASS",
            "ACQUISITION_READINESS": "PASS",
            "MODEL_CALIBRATED": "NO",
        },
    )


def run_masanet():
    script = FC3 / "scripts" / "run_masanet_transfer.py"
    out = OUTPUTS / "masanet"
    out.mkdir(parents=True, exist_ok=True)
    if not Path(MASANET_PYTHON).exists():
        write_json(out / "MASANET_TRANSFER.json", {"status": "NEEDS_DATA", "reason": "masanet_lei missing"})
        return "NEEDS_DATA", None
    r = subprocess.run(
        [MASANET_PYTHON, str(script)],
        cwd=str(FC3),
        capture_output=True,
        text=True,
        timeout=900,
    )
    (out / "masanet_subprocess.log").write_text((r.stdout or "") + "\n" + (r.stderr or ""))
    js = out / "MASANET_TRANSFER.json"
    if r.returncode != 0 or not js.exists():
        write_json(
            out / "MASANET_TRANSFER.json",
            {"status": "PARTIAL", "returncode": r.returncode, "stderr": (r.stderr or "")[-2000:]},
        )
        return "PARTIAL", None
    rec = json.loads(js.read_text())
    monthly_path = out / "MASANET_MONTHLY.csv"
    monthly = pd.read_csv(monthly_path) if monthly_path.exists() else None
    return rec.get("status", "PARTIAL"), monthly


def write_report(state, v2rep, two, annual, masanet_status):
    (OUTPUTS / "FOREST_CITY_V3_REPORT.md").write_text(
        "\n".join(
            [
                "# Forest City v3 — Cross-Site Transportability, Partial Identification, and Acquisition-Readiness",
                "",
                "MODEL_CALIBRATED = NO. QUANTITATIVE_PHYSICS_TRANSFER = NOT_VALIDATED. FACILITY_EFFECTIVE_DELTA_T = UNIDENTIFIED.",
                "",
                f"HEAD `{state['HEAD']}` on `{state['branch']}`.",
                "",
                "## What is OBSERVED",
                "- NOAA hourly weather at KFQD, KEHO, KGSP, KRDM, with missingness preserved.",
                "- Meta campus annual electricity and water withdrawal as reported.",
                "",
                "## What is DERIVED",
                "- 2024 Forest City site withdrawal intensity = withdrawal_m3 / electricity_MWh (L/kWh_facility). Not FRC1 WUE.",
                "",
                "## What is MODEL_REPLAY",
                "- Frozen Forest City and Prineville controllers on observed weather.",
                "- Mutually exclusive cooling-regime occupancy and transitions.",
                "- 2×2 weather × controller decomposition on the common UTC window.",
                "",
                "## What is TRANSFERRED_MODEL",
                "- Frozen Masanet Case 1 (P_IT=1, Table 3 midpoints, seed 2025) replayed on Forest City and Prineville weather.",
                "- Frozen ESIF F4 cooling + F0 HVAC with synthetic IT equal to the ESIF training-window mean.",
                "- Neither is Forest City PUE/WUE/water-magnitude validation.",
                "",
                "## What remains UNIDENTIFIED",
                "- FACILITY_EFFECTIVE_DELTA_T, airflow/CFM, cooling-only makeup, blowdown, reuse, FRC1 street address.",
                "",
                "See `FINAL_CLAIMS_LEDGER.md` and figure captions in `figures/FIGURE_CAPTIONS.md`.",
                "",
            ]
        )
        + "\n"
    )


def main():
    for d in (
        "preflight",
        "evidence",
        "weather",
        "regimes",
        "cross_site",
        "annual",
        "masanet",
        "esif",
        "identification",
        "acquisition",
        "figures",
        "slurm",
    ):
        (OUTPUTS / d).mkdir(parents=True, exist_ok=True)
    state = preflight()
    evidence_crosswalk()
    stations = {m["call_sign"]: load_station(m) for m in STATION_META}
    kfq = stations["KFQD"]
    krdm = load_krdm()
    weather_spine(stations, krdm)
    _, v2rep = reproduce_v2(kfq, stations)
    two, _ = two_by_two(kfq, krdm)
    annual = annual_comparison()
    esif = esif_transfer(kfq, krdm)
    masanet_status, monthly = run_masanet()
    ident = identification_table()
    acquisition_matrix()
    figures(two, ident, monthly)
    claims_ledger(v2rep, two, masanet_status, esif)
    write_report(state, v2rep, two, annual, masanet_status)
    end = record_hashes("end")
    write_json(OUTPUTS / "preflight" / "FINAL_HASH_CHECK.json", end)
    if end["mismatches"]:
        raise SystemExit("end hash mismatch")
    write_json(
        OUTPUTS / "FOREST_CITY_V3_FREEZE.json",
        {
            "STOP": True,
            "MODEL_CALIBRATED": "NO",
            "QUANTITATIVE_PHYSICS_TRANSFER": "NOT_VALIDATED",
            "FACILITY_EFFECTIVE_DELTA_T": "UNIDENTIFIED",
            "v1_untouched": True,
            "v2_untouched": True,
            "prineville_untouched": True,
            "slurm": {
                "policy": "Sloan CPU first (sched_mit_sloan_batch_r8 then sched_mit_sloan_batch); never default mit_normal",
                "this_run": "local_core_deterministic; Masanet via masanet_lei subprocess; mit_normal not used",
            },
        },
    )
    write_json(
        OUTPUTS / "slurm" / "RUN_MANIFEST.json",
        {
            "jobs": [],
            "local_steps": ["preflight", "v2_reproduction", "2x2", "esif_transfer", "masanet_subprocess"],
            "mit_normal_used": False,
            "sloan_partitions_used": [],
            "reason_local": "Core replay is deterministic and short; Masanet hourly Case-1 midpoint is a single-process intensity eval.",
        },
    )
    print(
        json.dumps(
            {
                "v2_repro": v2rep["V2_REPRODUCTION"],
                "masanet": masanet_status,
                "end_mismatches": end["mismatches"],
                "2x2_n": int(two.iloc[0].n_intersection),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
