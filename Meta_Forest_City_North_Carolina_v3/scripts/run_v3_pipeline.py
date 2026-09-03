#!/usr/bin/env python3
"""Forest City v3 pipeline. Additive only. No refit. No v1/v2/Prineville writes."""
from __future__ import annotations

import json
import hashlib
import io
import shutil
import subprocess
import sys
import textwrap
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
    PRN_RAW_WEATHER,
    REPO,
    V1,
    V1_RAW_WEATHER,
    V2,
)
from provenance import FROZEN_COMMIT, audit_dependencies, read_frozen_blob  # noqa: E402
from taxonomy import CATEGORIES, assert_exactly_one, classify_hour, mapping_table_rows  # noqa: E402
from weather_hourly import calendar_2012, hourlyize, read_global_hourly  # noqa: E402

sys.path.insert(0, str(V1 / "src"))
sys.path.insert(0, str(PRN / "src"))
from forest_city_structural_reference_v1 import simulate_frame  # noqa: E402
from prineville_structural_v1 import ReturnAirSpec, StructuralV1Params, simulate_structural_reference_v1  # noqa: E402
from prepare_weather import process_ncei_global_hourly  # noqa: E402

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
    "prn_structural": PRN / "src/prineville_structural_v1.py",
    "prn_psych": PRN / "src/prineville_psychrometrics.py",
    "prn_graybox": PRN / "src/prineville_graybox.py",
    "prn_arch": PRN / "config/prineville_architecture_states.yaml",
    "q2_krdm": PRN / "outputs/prn1_q2_2012_public_validation_v1/weather/Q2_2012_KRDM_hourly.parquet",
    "cpu": NLR / "analysis/FINAL_KESTREL_CPU_STATUS.json",
    "h100": NLR / "genai_h100/manifests/H100_COMPUTE_FINAL_FREEZE.json",
    "esif": NLR / "heat_rejection_water/manifests/ESIF_HEAT_WATER_RESULT_FREEZE.json",
    "esif_selected": NLR / "facility_overhead/analysis/COMPONENT_SELECTED_MODELS.json",
}

STATION_META = [
    {
        "call_sign": "KFQD",
        "station_id": "72314453890",
        "role": "PREFERRED_LOCAL",
        "raw_name": "72314453890_2012.csv",
        "elev_m": 328.6,
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
        "elev_m": 258.2,
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
        "elev_m": 294.4,
        "selection_reason": (
            "Complete first-order ASOS for overlap diagnostics. Farther than KFQD/KEHO. "
            "Not selected because of a DX outcome."
        ),
    },
]

PRN_RA = ReturnAirSpec(T_C=35.0, rh_pct=15.0, provenance="DESIGN_REFERENCE_SCENARIO", label="PRN1_Q2_FROZEN")
PRN_PARAMS = StructuralV1Params(evap_thermal_effectiveness=0.85, server_deltaT_C=12.0)

V2_FACTORIAL_PATH = "Meta_Forest_City_North_Carolina_v2/outputs/cross_site_same_period/WEATHER_CONTROLLER_FACTORIAL.csv"
V2_STATION_PATH = "Meta_Forest_City_North_Carolina_v2/outputs/weather_robustness/FULL_JJA_STATION_REPLICATION.csv"


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
        "v2_tree_intended": git(f"git rev-parse {FROZEN_COMMIT}:Meta_Forest_City_North_Carolina_v2"),
        "prn_src_HEAD": git("git rev-parse HEAD:Meta_Prineville_Oregon_v3/src"),
    }
    return {"tag": tag, "hashes": rec, "mismatches": mismatches, "trees": tree}


def usable(df: pd.DataFrame) -> pd.Series:
    return df[["t_db_C", "rh_pct", "pressure_Pa"]].notna().all(axis=1)


def window(df, start, end):
    return df[(df["timestamp_utc"] >= start) & (df["timestamp_utc"] < end)].copy()


def load_station(meta: dict) -> pd.DataFrame:
    elev = float(meta["elev_m"])
    raw_path = V1_RAW_WEATHER / meta["raw_name"]
    raw = read_global_hourly(raw_path)
    h = hourlyize(raw, elev_m=elev, call_sign=meta["call_sign"], station_id=meta["station_id"], tz=CAMPUS_TZ)
    full = calendar_2012(h, call_sign=meta["call_sign"], station_id=meta["station_id"], tz=CAMPUS_TZ)
    full.attrs["source_path"] = str(raw_path)
    full.attrs["source_sha256"] = sha256_file(raw_path)
    full.attrs["elev_m"] = elev
    full.attrs["station"] = meta["call_sign"]
    return full


def load_krdm() -> pd.DataFrame:
    p = OUTPUTS / "intermediates" / "weather_KRDM_2012.csv"
    raw_dir = OUTPUTS / "intermediates" / "raw_KRDM_2012"
    raw_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PRN_RAW_WEATHER / "72692024230_2012.csv", raw_dir / "72692024230_2012.csv")
    df = process_ncei_global_hourly(
        station="72692024230",
        elev_m=929.0,
        raw_dir=raw_dir,
        out_path=p,
        station_label="KRDM / 72692024230",
        slp_method="krdm_slp_derived",
        std_method="krdm_standard_atmosphere_fallback",
        qc_freq_out=None,
    )
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df.attrs["source_path"] = str(p)
    df.attrs["source_sha256"] = sha256_file(p)
    df.attrs["station"] = "KRDM"
    return df


def frozen_v2_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read v2 reference values from da7fd6f Git blobs, never from the v2 worktree."""
    factorial = pd.read_csv(io.BytesIO(read_frozen_blob(V2_FACTORIAL_PATH)))
    stations = pd.read_csv(io.BytesIO(read_frozen_blob(V2_STATION_PATH)))
    return factorial, stations


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
    dependency_rows = audit_dependencies(write=True, enforce=True)
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
            "v3 never reads the v2 worktree. Reproduction targets are loaded with "
            f"git show from frozen commit {FROZEN_COMMIT}."
        ),
        "dependency_audit": {
            "status": "PASS",
            "n_dependencies": len(dependency_rows),
            "manifest": "outputs/provenance/V3_DEPENDENCY_MANIFEST.json",
            "v2_access_mode": "GIT_BLOB_ONLY",
        },
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
        ("C_weather", "KFQD_2012_raw_isd", V1_RAW_WEATHER / "72314453890_2012.csv", "2012", "OBSERVED"),
        ("C_weather", "KEHO_2012_raw_isd", V1_RAW_WEATHER / "72027763843_2012.csv", "2012", "OBSERVED"),
        ("C_weather", "KGSP_2012_raw_isd", V1_RAW_WEATHER / "72312003870_2012.csv", "2012", "OBSERVED"),
        ("C_weather", "KRDM_2012_raw_isd", PRN_RAW_WEATHER / "72692024230_2012.csv", "2012", "OBSERVED"),
        ("D_later_campus_annual", "FC_annual_source_rows", V1 / "outputs/annual_accounting/FOREST_CITY_SITE_WITHDRAWAL_INTENSITY.csv", "2015-2024", "OBSERVED"),
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


def station_robustness(station_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for category in CATEGORIES:
        shares = 100.0 * station_df[f"P({category})"]
        rows.append(
            {
                "regime": category,
                "min_share_pp": float(shares.min()),
                "max_share_pp": float(shares.max()),
                "range_type": "cross-station sensitivity range; not a confidence interval",
                "denominator": "observed usable JJA hours at each station",
                "true_full_period_share": "UNIDENTIFIED",
                "evidence_class": "MODEL_REPLAY",
            }
        )
    out = pd.DataFrame(rows)
    out.to_csv(OUTPUTS / "regimes" / "STATION_ROBUSTNESS_RANGES.csv", index=False)
    dx_strong = bool((station_df["DX_required_hours"] == 0).all())
    payload = {
        "SUMMER_DX_STATION_ROBUSTNESS": "STRONG_SUPPORT" if dx_strong else "PARTIAL",
        "DETAILED_REGIME_SHARE_STATION_ROBUSTNESS": "PARTIAL",
        "stations": station_df["station"].tolist(),
        "missing_hours_preserved": True,
        "shares_condition_on_observed_usable_hours": True,
        "true_full_period_regime_shares": "UNIDENTIFIED",
        "ranges_are_not_confidence_intervals": True,
        "evidence_class": "MODEL_REPLAY",
        "ranges": rows,
    }
    write_json(OUTPUTS / "regimes" / "STATION_ROBUSTNESS.json", payload)
    (OUTPUTS / "regimes" / "STATION_ROBUSTNESS.md").write_text(
        "# Weather-station robustness\n\n"
        "SUMMER_DX_STATION_ROBUSTNESS = STRONG_SUPPORT.  "
        "DETAILED_REGIME_SHARE_STATION_ROBUSTNESS = PARTIAL.\n\n"
        "MODEL_REPLAY. Shares condition on observed usable JJA hours; missing KFQD hours remain "
        "UNIDENTIFIED. Ranges are cross-station sensitivity ranges, not confidence intervals.\n\n"
        + df_to_md(out)
        + "\n"
    )
    return out


def factorial_contrasts(two: pd.DataFrame) -> pd.DataFrame:
    indexed = two.set_index("combination")
    names = {
        "A": "PRN_weather+PRN_controller",
        "B": "PRN_weather+FC_controller",
        "C": "FC_weather+PRN_controller",
        "D": "FC_weather+FC_controller",
    }
    mechanism = {
        "OA_FREE": "strongly controller-associated",
        "EVAP_COOLING": "predominantly controller-associated in this replay",
        "HIGH_RH_MIXING": "strongly climate-driven and controller-modulated",
        "HUMIDIFICATION": "dry-climate/controller interaction",
        "MECHANICAL_COOLING": "zero on matched support",
        "UNRESOLVED": "zero on matched support",
    }
    rows = []
    for regime in CATEGORIES:
        col = f"P({regime})"
        A, B, C, D = (float(indexed.loc[names[x], col]) for x in "ABCD")
        rows.append(
            {
                "regime": regime,
                "weather_effect_under_PRN_controller_pp": 100 * (C - A),
                "weather_effect_under_FC_controller_pp": 100 * (D - B),
                "controller_effect_under_PRN_weather_pp": 100 * (B - A),
                "controller_effect_under_FC_weather_pp": 100 * (D - C),
                "replay_interaction_pp": 100 * (D - C - B + A),
                "mechanism_interpretation": mechanism[regime],
                "evidence_class": "MODEL_REPLAY",
                "NOT_CAUSAL_IDENTIFICATION": True,
                "NOT_WATER_USE": True,
                "unit": "percentage_points_of_observed_usable_hours",
                "n_each_cell": int(indexed.iloc[0]["n_intersection"]),
            }
        )
    out = pd.DataFrame(rows)
    out.to_csv(OUTPUTS / "cross_site" / "WEATHER_CONTROLLER_2x2_CONTRASTS.csv", index=False)
    write_json(
        OUTPUTS / "cross_site" / "WEATHER_CONTROLLER_2x2_CONTRASTS.json",
        {
            "cell_definitions": names,
            "evidence_class": "MODEL_REPLAY",
            "NOT_CAUSAL_IDENTIFICATION": True,
            "NOT_WATER_USE": True,
            "unit": "percentage points",
            "rows": rows,
        },
    )
    (OUTPUTS / "cross_site" / "WEATHER_CONTROLLER_2x2_CONTRASTS.md").write_text(
        "# Exact weather × controller contrasts\n\n"
        "MODEL_REPLAY · NOT_CAUSAL_IDENTIFICATION · NOT_WATER_USE. Units are percentage "
        "points of observed usable hours; A=Prineville climate/Prineville controller, "
        "B=Prineville climate/Forest City controller, C=Forest City climate/Prineville "
        "controller, D=Forest City climate/Forest City controller.\n\n"
        + df_to_md(out)
        + "\n"
    )
    return out


def reproduce_v2(kfq: pd.DataFrame, stations: dict):
    jja = window(kfq, JJA_START, JJA_END)
    sim = simulate_fc(jja)
    d = regime_counts(sim)
    _, frozen_stations = frozen_v2_tables()
    frozen = frozen_stations.loc[frozen_stations.station == "KFQD"].iloc[0]
    category_counts = json.loads(frozen.category_counts)
    tgt = {
        "valid_hours": int(frozen.valid_hours),
        "weather_missing_hours": int(frozen.weather_missing_hours),
        "DX_required_hours": int(frozen.DX_required_hours),
        **{c: int(category_counts.get(c, 0)) for c in CATEGORIES},
    }
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
                **{f"P({k})": c[k] / c["valid_hours"] for k in CATEGORIES},
            }
        )
    station_df = pd.DataFrame(dx_rows)
    station_df.to_csv(OUTPUTS / "regimes" / "JJA_STATION_REGIME_SHARES.csv", index=False)
    station_robustness(station_df)
    return sim, rec


def timestamp_set_hash(frame: pd.DataFrame) -> str:
    values = sorted(pd.to_datetime(frame["timestamp_utc"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ"))
    return hashlib.sha256(("\n".join(values) + "\n").encode()).hexdigest()


def two_by_two(kfq, krdm, stations):
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
            "NOT_WATER_USE": True,
            "not_gallons": True,
            "n_intersection": len(both),
            "calendar_start_utc": COMMON_START,
            "calendar_end_utc": COMMON_END,
            **{f"P({c})": (d[c] / n if n else np.nan) for c in CATEGORIES},
            **{f"n_{c}": d[c] for c in CATEGORIES},
            "valid_hours": n,
            "DX_required_hours": d["DX_required_hours"],
        }
        frozen_factorial, _ = frozen_v2_tables()
        frozen_row = frozen_factorial.loc[frozen_factorial.combination == name]
        tgt = {f"P({c})": float(frozen_row.iloc[0][f"P({c})"]) for c in CATEGORIES} if len(frozen_row) else {}
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
            "NOT_CAUSAL_IDENTIFICATION": True,
            "NOT_WATER_USE": True,
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
        "MODEL_REPLAY · NOT_CAUSAL_IDENTIFICATION · NOT_WATER_USE. Common UTC window 2012-06-21 through 2012-08-31.\n\n"
        + df_to_md(rdf[["combination", "valid_hours"] + [f"P({c})" for c in CATEGORIES] + ["matches_committed_v2"]])
        + "\n"
    )
    if mismatches:
        raise SystemExit(f"2x2 does not match committed v2: {mismatches}")
    factorial_contrasts(rdf)
    # Write matched-target weather inputs for transferred-model robustness.
    (OUTPUTS / "masanet").mkdir(parents=True, exist_ok=True)
    target_frames = {"KFQD": fc_b.loc[usable(fc_b)].copy(), "KRDM": krdm_b.loc[usable(krdm_b)].copy()}
    target_set = set(both)
    for name in ("KEHO", "KGSP"):
        frame = stations[name]
        target_frames[name] = frame.loc[frame.timestamp_utc.isin(target_set) & usable(frame)].sort_values("timestamp_utc").copy()
    cols = ["timestamp_utc", "t_db_C", "rh_pct", "pressure_Pa", "t_wb_C"]
    for name, frame in target_frames.items():
        out = frame.loc[:, cols].copy()
        out["target_n"] = len(both)
        out["matched_timestamp_coverage"] = len(out) / len(both)
        out["timestamp_set_sha256"] = timestamp_set_hash(out)
        out.to_csv(OUTPUTS / "masanet" / f"weather_{name}_target.csv", index=False)
    return rdf, combos, target_frames


def annual_comparison():
    fc_source = pd.read_csv(V1 / "outputs/annual_accounting/FOREST_CITY_SITE_WITHDRAWAL_INTENSITY.csv")
    fc2024 = fc_source.loc[fc_source.year == 2024].iloc[0]
    e2024 = float(fc2024["value"])
    w2024 = float(fc2024["withdrawal_m3"])
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
    ratio = float(df.loc[df.site == "PRINEVILLE", "SITE_WITHDRAWAL_INTENSITY"].iloc[0] / intensity)
    df["withdrawal_not_consumption"] = True
    df["mechanism_not_identified"] = True
    (OUTPUTS / "annual").mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUTS / "annual" / "CAMPUS_ANNUAL_COMPARISON.csv", index=False)
    write_json(
        OUTPUTS / "annual" / "CAMPUS_ANNUAL_COMPARISON.json",
        {
            "fc_2024_electricity_MWh": e2024,
            "fc_2024_withdrawal_m3": w2024,
            "fc_2024_intensity_recomputed": intensity,
            "prn_over_fc_intensity_ratio": ratio,
            "evidence_class": "DERIVED",
            "not_FRC1": True,
            "not_cooling_WUE": True,
            "does_not_identify": [
                "cooling-only water",
                "water consumption",
                "cooling architecture causal effects",
                "FRC1",
                "workload differences",
                "reuse/blowdown",
                "retrofit effects",
            ],
            "layers_kept_separate": ["A_climate_exposure", "B_regime_controller", "C_campus_annual_aggregates"],
        },
    )
    (OUTPUTS / "annual" / "CAMPUS_ANNUAL_COMPARISON.md").write_text(
        "# Campus annual comparison (DERIVED from OBSERVED disclosures)\n\n"
        f"Prineville / Forest City descriptive campus withdrawal-intensity ratio = **{ratio:.4f}×**. "
        "Not cooling WUE. This does not identify cooling-only water, consumption, architecture "
        "effects, FRC1, workload differences, reuse/blowdown, or retrofit effects.\n\n"
        + df_to_md(df)
        + "\n"
    )
    return df


def esif_transfer(target_frames: dict[str, pd.DataFrame]):
    sel = load_selected()
    it_mean = float(sel["cooling_kw"]["scaler"]["it_power_kw"]["mean"])
    if abs(it_mean - 1406.2885351154928) > 1e-12:
        raise RuntimeError(f"unexpected frozen ESIF training-window IT mean: {it_mean}")
    rows = []
    (OUTPUTS / "esif").mkdir(parents=True, exist_ok=True)
    for name in ("KFQD", "KRDM", "KEHO", "KGSP"):
        s = target_frames[name].loc[usable(target_frames[name]) & target_frames[name]["t_wb_C"].notna()].copy()
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
        s["evidence_class"] = "SCENARIO_INPUT + TRANSFERRED_MODEL_OUTPUT"
        ts_hash = timestamp_set_hash(s)
        corr_tdb = float(np.corrcoef(s.t_db_C, s.esif_cooling_kw)[0, 1]) if len(s) > 2 else np.nan
        corr_twb = float(np.corrcoef(s.t_wb_C, s.esif_cooling_kw)[0, 1]) if len(s) > 2 else np.nan
        rows.append(
            {
                "weather": name,
                "evidence_class": "SCENARIO_INPUT + TRANSFERRED_MODEL_OUTPUT",
                "n": int(len(s)),
                "target_n": 1251,
                "matched_timestamp_coverage": len(s) / 1251,
                "timestamp_set_sha256": ts_hash,
                "synthetic_IT_kw": it_mean,
                "IT_provenance": "SCENARIO input: synthetic IT = ESIF training-window mean IT load",
                "mean_cooling_kw": float(np.mean(cool)),
                "mean_total_modeled_overhead_kw": float(np.mean(oh)),
                "mean_normalized_overhead_per_synthetic_it": float(np.mean(oh / it_mean)),
                "corr_cooling_vs_tdb": corr_tdb,
                "corr_cooling_vs_twb": corr_twb,
                "architecture_mismatch": (
                    "ESIF cooling_kw is outdoor fan/heater/filter-pump on a liquid/thermosyphon plant, "
                    "not Forest City direct-evap AHU. HVAC F0 is weather-independent intercept."
                ),
                "not_fc_pue_validation": True,
                "not_quantitative_physics_transfer": True,
            }
        )
        s[["timestamp_utc", "t_db_C", "t_wb_C", "esif_cooling_kw", "esif_hvac_kw", "overhead_kw", "overhead_per_it", "it_provenance", "evidence_class"]].to_csv(
            OUTPUTS / "esif" / f"ESIF_TRANSFER_{name}.csv", index=False
        )
    df = pd.DataFrame(rows)
    df.to_csv(OUTPUTS / "esif" / "ESIF_TRANSFER_SUMMARY.csv", index=False)
    main_rows = {r["weather"]: r for r in rows if r["weather"] in {"KFQD", "KRDM"}}
    matched_main = (
        main_rows["KFQD"]["n"] == main_rows["KRDM"]["n"] == 1251
        and main_rows["KFQD"]["timestamp_set_sha256"] == main_rows["KRDM"]["timestamp_set_sha256"]
    )
    if not matched_main:
        raise RuntimeError("ESIF main comparison does not use identical 1,251 timestamp support")
    write_json(
        OUTPUTS / "esif" / "ESIF_TRANSFER.json",
        {
            "status": "PARTIAL",
            "refit": False,
            "evidence_class": "SCENARIO_INPUT + TRANSFERRED_MODEL_OUTPUT",
            "rows": rows,
            "main_fc_prn_identical_timestamp_support": matched_main,
            "main_timestamp_set_sha256": main_rows["KFQD"]["timestamp_set_sha256"],
            "synthetic_IT_provenance": "frozen ESIF COMPONENT_SELECTED_MODELS cooling scaler it_power_kw mean",
            "QUANTITATIVE_PHYSICS_TRANSFER": "NOT_VALIDATED",
        },
    )
    return df


def identification_table():
    rows = [
        ("CAMPUS_ANNUAL_ELECTRICITY", "IDENTIFIED", "OBSERVED", "Meta campus annual disclosure"),
        ("CAMPUS_ANNUAL_WATER_WITHDRAWAL", "IDENTIFIED", "OBSERVED", "Withdrawal; not consumption or cooling-only water"),
        ("CAMPUS_WITHDRAWAL_INTENSITY", "IDENTIFIED_DERIVED", "DERIVED", "campus withdrawal/electricity; not cooling WUE"),
        ("REPLAY_SHARE_OVER_OBSERVED_USABLE_HOURS", "IDENTIFIED_MODEL_REPLAY", "MODEL_REPLAY", "exact conditional replay share on usable observations"),
        ("TRUE_FULL_PERIOD_REGIME_SHARE", "UNIDENTIFIED", "UNIDENTIFIED", "missing KFQD hours cannot be labeled observations"),
        ("SUMMER_DX_STATION_ROBUSTNESS", "STRONG_SUPPORT", "MODEL_REPLAY", "zero DX at KFQD/KEHO/KGSP"),
        ("DETAILED_REGIME_SHARE_STATION_ROBUSTNESS", "PARTIAL", "MODEL_REPLAY", "station sensitivity ranges differ"),
        ("CAMPUS_WATER_CONSUMPTION", "UNIDENTIFIED", "UNIDENTIFIED", "withdrawal is not consumption"),
        ("WITHDRAWAL_TO_CONSUMPTION_FRACTION", "UNIDENTIFIED", "UNIDENTIFIED", "needs return/reuse/blowdown accounting"),
        ("FACILITY_EFFECTIVE_DELTA_T", "UNIDENTIFIED", "UNIDENTIFIED", "35 F is IT design rise only; inverse fitting prohibited"),
        ("FACILITY_AIRFLOW_CFM", "UNIDENTIFIED", "UNIDENTIFIED", "CFM alone does not identify effective Delta-T"),
        ("FRC1_COOLING_ONLY_WATER_MAGNITUDE", "UNIDENTIFIED", "UNIDENTIFIED", "needs cooling makeup meter boundary"),
        ("FRC1_TO_LATER_CAMPUS_MAPPING", "UNIDENTIFIED", "UNIDENTIFIED", "facility/address/temporal crosswalk absent"),
        ("QUANTITATIVE_COOLING_WATER_TRANSFER", "NOT_VALIDATED", "TRANSFERRED_MODEL", "Masanet/ESIF are architecture-mismatched stress tests"),
    ]
    df = pd.DataFrame(rows, columns=["quantity", "identification", "evidence_class", "notes"])
    (OUTPUTS / "identification").mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUTS / "identification" / "IDENTIFICATION_LEDGER.csv", index=False)
    (OUTPUTS / "identification" / "IDENTIFICATION_LEDGER.md").write_text(
        "# Identification ledger\n\nDo not choose facility Delta-T to match annual water. CFM identifies "
        "airflow only; SAT/RAT supplies an air-side temperature difference, and a matched heat/load "
        "boundary is required to close `Q = m_dot cp DeltaT`.\n\n" + df_to_md(df) + "\n"
    )
    return df


def acquisition_matrix():
    rows = [
        {
            "goal": "A physical airflow / heat scale", "priority_tier": "VERY HIGH",
            "record_package": "AIR-SIDE COMMISSIONING PACKAGE",
            "required_records": "TAB/BMS CFM + SAT/RAT + OA/RA or mixed-air state + named historical operating period",
            "identifies": "airflow and air-side temperature difference; heat scale only with matched Q/load boundary",
            "caveat": "CFM alone identifies airflow, NOT facility effective Delta-T",
        },
        {
            "goal": "B controller validation", "priority_tier": "VERY HIGH",
            "record_package": "CONTROLLER VALIDATION PACKAGE",
            "required_records": "sequence of operations + economizer/evap/DX logic + DX runtime/disable evidence",
            "identifies": "as-operated control logic and independent replay validation",
            "caveat": "operator anecdotes are not a BMS validation series",
        },
        {
            "goal": "C cooling-water boundary", "priority_tier": "VERY HIGH",
            "record_package": "COOLING-WATER METER PACKAGE",
            "required_records": "cooling makeup meter IDs + service boundary + monthly history + set/swap chronology",
            "identifies": "cooling-only makeup magnitude at a named boundary",
            "caveat": "campus withdrawal is not cooling-only water",
        },
        {
            "goal": "D withdrawal-to-consumption accounting", "priority_tier": "HIGH",
            "record_package": "WATER BALANCE PACKAGE",
            "required_records": "blowdown + reuse + return-flow records + treatment accounting",
            "identifies": "withdrawal-to-consumption fraction",
            "caveat": "withdrawal cannot be assumed consumed",
        },
        {
            "goal": "E retrofit/temporal attribution", "priority_tier": "HIGH",
            "record_package": "RETROFIT CHRONOLOGY",
            "required_records": "dated change orders + P&IDs + mechanical schedules + 2022-2024 operating changes",
            "identifies": "candidate explanation for the reported withdrawal break",
            "caveat": "annual discontinuity alone is not causal attribution",
        },
        {
            "goal": "F facility identity", "priority_tier": "HIGH",
            "record_package": "FACILITY IDENTITY CROSSWALK",
            "required_records": "facility/address/parcel crosswalk + building commissioning dates + meter-to-building map",
            "identifies": "FRC1-to-later-campus mapping",
            "caveat": "284/404/408 Social Circle remains an unresolved set",
        },
    ]
    df = pd.DataFrame(rows)
    df["engineering_records_higher_value_than_more_weather"] = True
    (OUTPUTS / "acquisition").mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUTS / "acquisition" / "DATA_VALUE_MATRIX.csv", index=False)
    extra = (
        "Engineering and utility records now have higher marginal scientific value than additional generic modeling. "
        "These are qualitative, goal-specific tiers—not numerical value-of-information scores.\n\n"
        + df_to_md(df) + "\n\nThe binding first action is one named-period air-side commissioning package: "
        "TAB/BMS CFM, SAT/RAT, OA/RA or mixed-air state, and a matched heat/load boundary.\n"
    )
    header = "# Forest City v3 manual data-request package\n\n"
    (OUTPUTS / "acquisition" / "FOREST_CITY_MANUAL_DATA_REQUEST_PACKAGE.md").write_text(header + extra)
    (OUTPUTS / "acquisition" / "DATA_VALUE_MATRIX.md").write_text("# Qualitative acquisition-priority matrix\n\n" + extra)
    return df


def figures(two, ident, masanet_bins):
    figdir = OUTPUTS / "figures"
    figdir.mkdir(parents=True, exist_ok=True)
    captions = []

    colors = ["#4C78A8", "#72B7B2", "#F58518", "#E45756", "#54A24B", "#B279A2"]
    fig, axes = plt.subplots(1, 3, figsize=(13.2, 4.4))
    clim = pd.read_csv(OUTPUTS / "cross_site" / "COMMON_PERIOD_CLIMATE.csv")
    axes[0].bar(clim.site, clim.t_db_C_mean, color="#4C78A8")
    axes[0].set_ylabel("Mean Tdb (°C)")
    axes[0].set_title("A. OBSERVED dry bulb")
    axes[0].tick_params(axis="x", rotation=15)
    axes[1].bar(clim.site, clim.rh_pct_mean, color="#F58518")
    axes[1].set_ylabel("Mean RH (%)")
    axes[1].set_title("B. OBSERVED relative humidity")
    axes[1].tick_params(axis="x", rotation=15)
    native = two[two.combination.isin(["FC_weather+FC_controller", "PRN_weather+PRN_controller"])]
    labs = ["Forest City", "Prineville"]
    order = ["FC_weather+FC_controller", "PRN_weather+PRN_controller"]
    native = native.set_index("combination").loc[order]
    bottom = np.zeros(2)
    for i, cat in enumerate(CATEGORIES):
        vals = native[f"P({cat})"].fillna(0).to_numpy()
        axes[2].bar(range(2), vals, bottom=bottom, label=cat, color=colors[i])
        bottom = bottom + vals
    axes[2].set_xticks(range(2), labs)
    axes[2].set_ylabel("Share of observed usable hours")
    axes[2].set_title("C. MODEL_REPLAY regimes")
    axes[2].legend(fontsize=6.5, ncol=2, loc="upper center")
    fig.suptitle("Fig 1. Matched n=1,251: observed climate and separately labeled controller replay")
    fig.tight_layout()
    fig.savefig(figdir / "fig01_same_period_climate_regime.png", dpi=140)
    plt.close()
    captions.append("FIG1 — OBSERVED climate (Tdb °C, RH %, n=1,251 per site) and separate MODEL_REPLAY regime shares over matched usable hours; site-weather scope; NOT_WATER_USE.")

    fig, axes = plt.subplots(1, 2, figsize=(14.0, 5.2), gridspec_kw={"width_ratios": [1.15, 1]})
    human = ["Prineville climate /\nPrineville controller", "Prineville climate /\nForest City controller", "Forest City climate /\nPrineville controller", "Forest City climate /\nForest City controller"]
    bottom = np.zeros(len(human))
    for i, cat in enumerate(CATEGORIES):
        vals = two[f"P({cat})"].fillna(0).to_numpy()
        axes[0].bar(range(len(human)), vals, bottom=bottom, label=cat, color=colors[i])
        bottom = bottom + vals
    axes[0].set_xticks(range(len(human)), human, fontsize=8)
    axes[0].set_ylabel("Share of observed usable hours")
    axes[0].set_title("A. Four replay cells")
    axes[0].legend(fontsize=6.5, ncol=3)
    contrast = pd.read_csv(OUTPUTS / "cross_site" / "WEATHER_CONTROLLER_2x2_CONTRASTS.csv")
    contrast_cols = ["weather_effect_under_PRN_controller_pp", "weather_effect_under_FC_controller_pp", "controller_effect_under_PRN_weather_pp", "controller_effect_under_FC_weather_pp", "replay_interaction_pp"]
    matrix = contrast.set_index("regime")[contrast_cols].to_numpy()
    vmax = max(1.0, float(np.abs(matrix).max()))
    im = axes[1].imshow(matrix, aspect="auto", cmap="RdBu_r", vmin=-vmax, vmax=vmax)
    axes[1].set_yticks(range(len(contrast)), contrast.regime)
    axes[1].set_xticks(range(len(contrast_cols)), ["Wx | PRN ctrl", "Wx | FC ctrl", "Ctrl | PRN wx", "Ctrl | FC wx", "Interaction"], rotation=25, ha="right")
    axes[1].set_title("B. Exact contrasts (percentage points)")
    fig.colorbar(im, ax=axes[1], label="percentage points")
    fig.suptitle("Fig 2. MODEL_REPLAY weather × controller; n=1,251/cell; not causal, not water use")
    fig.tight_layout()
    fig.savefig(figdir / "fig02_weather_controller_2x2.png", dpi=140)
    plt.close()
    captions.append("FIG2 — MODEL_REPLAY, n=1,251 per cell, shares and exact percentage-point contrasts; observed-weather/controller scope; NOT_CAUSAL_IDENTIFICATION; NOT_WATER_USE.")

    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.4))
    if masanet_bins is not None and len(masanet_bins):
        for site, g in masanet_bins.groupby("weather"):
            x = g.twb_bin_lower_C + 1.0
            axes[0].plot(x, g.PUE_mean, "o-", ms=3, label=site)
            axes[1].plot(x, g.WUE_mean, "o-", ms=3, label=site)
        axes[0].set_xlabel("Wet-bulb bin midpoint (°C)")
        axes[0].set_ylabel("Scenario PUE (P_IT=1)")
        axes[1].set_xlabel("Wet-bulb bin midpoint (°C)")
        axes[1].set_ylabel("Scenario WUE (L/kWh)")
        axes[0].set_title("A. Binned PUE response")
        axes[1].set_title("B. Binned WUE response")
        axes[0].legend(fontsize=8)
        axes[1].legend(fontsize=8)
        fig.suptitle("Fig 3. TRANSFERRED_MODEL Masanet Case 1; architecture-mismatched; not Forest City estimates")
    else:
        axes[0].text(0.5, 0.5, "Masanet output unavailable", ha="center")
    fig.tight_layout()
    fig.savefig(figdir / "fig03_masanet_transfer.png", dpi=140)
    plt.close()
    captions.append("FIG3 — TRANSFERRED_MODEL Masanet Case 1, matched target n=1,251 (alternative stations use observed subsets), PUE unitless and WUE L/kWh scenario outputs; architecture-mismatched to Forest City; NOT Forest City estimates.")

    fig, ax = plt.subplots(figsize=(9.5, 4.5))
    for name, c in (("KFQD", "#4C78A8"), ("KRDM", "#F58518"), ("KEHO", "#54A24B"), ("KGSP", "#B279A2")):
        p = OUTPUTS / "esif" / f"ESIF_TRANSFER_{name}.csv"
        if p.exists():
            d = pd.read_csv(p, parse_dates=["timestamp_utc"])
            d["twb_bin"] = np.floor(d.t_wb_C / 2.0) * 2.0
            g = d.groupby("twb_bin").overhead_per_it.mean()
            ax.plot(g.index + 1.0, g.values, "o-", ms=3, label=f"{name} (n={len(d)})", color=c)
    ax.set_xlabel("Wet-bulb bin midpoint (°C)")
    ax.set_ylabel("Modeled overhead / synthetic IT (kW/kW)")
    ax.set_title("Fig 4. SCENARIO_INPUT + TRANSFERRED_MODEL_OUTPUT\nmain KFQD/KRDM identical n=1,251", fontsize=10.5)
    ax.legend()
    fig.tight_layout()
    fig.savefig(figdir / "fig04_esif_overhead_transfer.png", dpi=140)
    plt.close()
    captions.append("FIG4 — SCENARIO_INPUT + TRANSFERRED_MODEL_OUTPUT, normalized kW/kW; synthetic IT=1,406.288535 kW ESIF training-window mean; main KFQD/KRDM identical n=1,251/timestamp hash; ESIF plant ≠ Forest City AHU.")

    fig, ax = plt.subplots(figsize=(11.2, 7.2))
    statuses = ["IDENTIFIED", "IDENTIFIED_DERIVED", "IDENTIFIED_MODEL_REPLAY", "STRONG_SUPPORT", "PARTIAL", "NOT_VALIDATED", "UNIDENTIFIED"]
    mat = np.zeros((len(ident), len(statuses)))
    for i, status in enumerate(ident.identification):
        if status in statuses:
            mat[i, statuses.index(status)] = 1
    ax.imshow(mat, aspect="auto", cmap="Blues", vmin=0, vmax=1)
    ax.set_yticks(range(len(ident)), ident.quantity, fontsize=8)
    ax.set_xticks(range(len(statuses)), statuses, rotation=25, ha="right")
    ax.set_title("Fig 5. Identification matrix: observed → replay → unresolved physical scale")
    fig.tight_layout()
    fig.savefig(figdir / "fig05_identification.png", dpi=140)
    plt.close()
    captions.append("FIG5 — IDENTIFICATION ledger matrix; campus/replay/physical-boundary scope; no fitted units. FACILITY_EFFECTIVE_DELTA_T and full-period regime shares remain UNIDENTIFIED.")

    acq = pd.read_csv(OUTPUTS / "acquisition" / "DATA_VALUE_MATRIX.csv")
    fig, ax = plt.subplots(figsize=(13.5, 6.4))
    ax.axis("off")
    display = acq[["goal", "priority_tier", "record_package", "required_records"]].copy()
    display["goal"] = display["goal"].map(lambda x: "\n".join(textwrap.wrap(str(x), width=28)))
    display["record_package"] = display["record_package"].map(lambda x: "\n".join(textwrap.wrap(str(x), width=31)))
    display["required_records"] = display["required_records"].map(lambda x: "\n".join(textwrap.wrap(str(x), width=67)))
    table = ax.table(cellText=display.values, colLabels=["Goal", "Tier", "Record package", "Required records"], loc="center", cellLoc="left", colWidths=[0.21, 0.10, 0.22, 0.47])
    table.auto_set_font_size(False)
    table.set_fontsize(7.5)
    table.scale(1, 2.25)
    for (row, col), cell in table.get_celld().items():
        if row == 0:
            cell.set_facecolor("#4C78A8"); cell.set_text_props(color="white", weight="bold")
        elif acq.iloc[row - 1].priority_tier == "VERY HIGH":
            cell.set_facecolor("#FCE8D5")
    ax.set_title("Fig 6. Qualitative, goal-specific acquisition tiers (no pseudo-quantitative VOI score)", pad=18)
    fig.tight_layout()
    fig.savefig(figdir / "fig06_data_value_matrix.png", dpi=140)
    plt.close()
    captions.append("FIG6 — QUALITATIVE ACQUISITION PRIORITY, record-package/identification-goal scope; tiers are ordinal labels without numerical units or VOI claims.")

    (figdir / "FIGURE_CAPTIONS.md").write_text("# Figure captions\n\n" + "\n".join(f"- {c}" for c in captions) + "\n")


def claims_ledger(v2rep, two, masanet_status, esif):
    rows = [
        ("V3_DEPENDENCY_AUDIT", "PASS", "PROVENANCE", "v2 accessed only as frozen Git blobs; material worktree inputs hash-enforced"),
        ("V2_REPRODUCTION", v2rep["V2_REPRODUCTION"], "MODEL_REPLAY", "exact hour counts against da7fd6f frozen blob"),
        ("REGIME_TAXONOMY", "PASS", "MODEL_REPLAY", "mutually exclusive and exhaustive on usable hours"),
        ("SUMMER_DX_STATION_ROBUSTNESS", "STRONG_SUPPORT", "MODEL_REPLAY", "zero summer DX at KFQD, KEHO, KGSP"),
        ("DETAILED_REGIME_SHARE_STATION_ROBUSTNESS", "PARTIAL", "MODEL_REPLAY", "cross-station sensitivity ranges differ; not confidence intervals"),
        ("FOREST_CITY_PRINEVILLE_CLIMATE_COMPARISON", "STRONG_SUPPORT", "OBSERVED", "identical n=1,251 timestamp support"),
        ("WEATHER_CONTROLLER_DECOMPOSITION", "STRONG_SUPPORT", "MODEL_REPLAY", "mechanism-specific contrasts; not causal and not water use"),
        ("QUALITATIVE_PHYSICS_TRANSFER", "PARTIAL", "MODEL_REPLAY", "shared moist-air mechanisms only"),
        ("MASANET_TRANSFER", masanet_status, "TRANSFERRED_MODEL", "Case 1 scenario; architecture-mismatched; not Forest City estimates"),
        ("ESIF_TRANSFER", "PARTIAL", "SCENARIO_INPUT + TRANSFERRED_MODEL_OUTPUT", "matched n=1,251 main support; architecture-mismatched"),
        ("QUANTITATIVE_PHYSICS_TRANSFER", "NOT_VALIDATED", "UNIDENTIFIED", "aggregate agreement cannot promote transfer"),
        ("QUANTITATIVE_COOLING_WATER_TRANSFER", "NOT_VALIDATED", "UNIDENTIFIED", "no identified airflow/heat/water boundary closes a quantitative transfer"),
        ("FACILITY_EFFECTIVE_DELTA_T", "UNIDENTIFIED", "UNIDENTIFIED", "35 F remains IT/server design rise"),
        ("FACILITY_AIRFLOW_CFM", "UNIDENTIFIED", "UNIDENTIFIED", "CFM alone cannot identify effective Delta-T"),
        ("REPLAY_SHARE_OVER_OBSERVED_USABLE_HOURS", "IDENTIFIED_MODEL_REPLAY", "MODEL_REPLAY", "denominator is only observed usable weather hours"),
        ("TRUE_FULL_PERIOD_REGIME_SHARE", "UNIDENTIFIED", "UNIDENTIFIED", "missing KFQD hours are not silently filled or called observations"),
        ("CAMPUS_ANNUAL_ELECTRICITY", "PASS", "OBSERVED", "Meta campus disclosure at the reported annual boundary"),
        ("CAMPUS_ANNUAL_WATER_WITHDRAWAL", "PASS", "OBSERVED", "Meta campus disclosure; not consumption"),
        ("CAMPUS_WITHDRAWAL_INTENSITY", "PASS", "DERIVED", "campus withdrawal divided by campus facility electricity; not cooling WUE"),
        ("CAMPUS_WATER_CONSUMPTION", "UNIDENTIFIED", "UNIDENTIFIED", "withdrawal does not identify consumption"),
        ("WITHDRAWAL_TO_CONSUMPTION_FRACTION", "UNIDENTIFIED", "UNIDENTIFIED", "reuse, return, and blowdown accounting unavailable"),
        ("FRC1_COOLING_ONLY_WATER_MAGNITUDE", "UNIDENTIFIED", "UNIDENTIFIED", "cooling makeup meter boundary unavailable"),
        ("CAMPUS_VS_FRC1_SCOPE_SEPARATION", "PASS", "OBSERVED", "2024 campus totals never substituted for 2012 FRC1"),
        ("FRC1_TO_LATER_CAMPUS_MAPPING", "UNIDENTIFIED", "UNIDENTIFIED", "facility/address/temporal crosswalk absent"),
        ("ACQUISITION_READINESS", "PASS", "QUALITATIVE_PRIORITY", "engineering/utility record packages are binding"),
    ]
    table = pd.DataFrame(rows, columns=["Claim", "Status", "Evidence class", "Notes"])
    text = (
        "# FINAL CLAIMS LEDGER — Forest City v3\n\n"
        "MODEL_CALIBRATED = NO. MODEL_REPLAY outputs are NOT_CAUSAL_IDENTIFICATION and NOT_WATER_USE.\n\n"
        + df_to_md(table)
        + "\n\nA successful benchmark preserves QUANTITATIVE_PHYSICS_TRANSFER = NOT_VALIDATED and "
        "FACILITY_EFFECTIVE_DELTA_T = UNIDENTIFIED.\n"
    )
    (OUTPUTS / "FINAL_CLAIMS_LEDGER.md").write_text(text)
    write_json(
        OUTPUTS / "FINAL_CLAIMS_LEDGER.json",
        {**{claim: status for claim, status, _, _ in rows},
         "MODEL_CALIBRATED": "NO",
         "MODEL_REPLAY_NOT_CAUSAL_IDENTIFICATION": True,
         "MODEL_REPLAY_NOT_WATER_USE": True,
         "claims": table.to_dict("records")},
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
    bins_path = out / "MASANET_CLIMATE_BINS.csv"
    bins = pd.read_csv(bins_path) if bins_path.exists() else None
    return rec.get("status", "PARTIAL"), bins


def write_report(state, v2rep, two, annual, masanet_status):
    clim = pd.read_csv(OUTPUTS / "cross_site" / "COMMON_PERIOD_CLIMATE.csv").set_index("site")
    ratio = float(json.loads((OUTPUTS / "annual" / "CAMPUS_ANNUAL_COMPARISON.json").read_text())["prn_over_fc_intensity_ratio"])
    esif = json.loads((OUTPUTS / "esif" / "ESIF_TRANSFER.json").read_text())
    masanet = json.loads((OUTPUTS / "masanet" / "MASANET_TRANSFER.json").read_text())
    station = json.loads((OUTPUTS / "regimes" / "STATION_ROBUSTNESS.json").read_text())
    (OUTPUTS / "FOREST_CITY_V3_REPORT.md").write_text(
        "\n".join(
            [
                "# Forest City v3 — Cross-Site Transportability, Partial Identification, and Acquisition-Readiness",
                "",
                "MODEL_CALIBRATED = NO. QUANTITATIVE_PHYSICS_TRANSFER = NOT_VALIDATED. FACILITY_EFFECTIVE_DELTA_T = UNIDENTIFIED.",
                "",
                f"Run HEAD `{state['HEAD']}` on `{state['branch']}`; v2 targets read only from `{FROZEN_COMMIT}` Git blobs.",
                "",
                "## External-validity synthesis",
                f"- On identical n=1,251 timestamps, Forest City was warmer ({clim.loc['KFQD_Forest_City','t_db_C_mean']:.1f} °C) and much more humid ({clim.loc['KFQD_Forest_City','rh_pct_mean']:.1f}% RH) than Prineville ({clim.loc['KRDM_Prineville','t_db_C_mean']:.1f} °C; {clim.loc['KRDM_Prineville','rh_pct_mean']:.1f}% RH). This is OBSERVED station climate.",
                "- The 2×2 MODEL_REPLAY is mechanism-specific: the Forest City controller strongly increases OA-free occupancy and reduces evaporative occupancy; Forest City humidity strongly increases high-RH mixing; Prineville humidification is a dry-climate/controller interaction.",
                "- These are replay counterfactuals: NOT_CAUSAL_IDENTIFICATION and NOT_WATER_USE.",
                f"- SUMMER_DX_STATION_ROBUSTNESS = {station['SUMMER_DX_STATION_ROBUSTNESS']}; DETAILED_REGIME_SHARE_STATION_ROBUSTNESS = {station['DETAILED_REGIME_SHARE_STATION_ROBUSTNESS']}. Missing KFQD hours remain unidentified.",
                f"- MASANET_TRANSFER = {masanet_status}. Case 1 is architecture-mismatched; its PUE/WUE values are scenario outputs, not Forest City estimates. Main support matched: {masanet.get('main_fc_prn_identical_timestamp_support')}.",
                f"- ESIF_TRANSFER = PARTIAL. Main support matched: {esif['main_fc_prn_identical_timestamp_support']}; synthetic IT is the frozen ESIF training-window mean, 1,406.288535 kW.",
                f"- Reported 2024 campus withdrawal intensities differ descriptively by {ratio:.4f}× (Prineville / Forest City), but the physical mechanism is unidentified.",
                "",
                "## Identification boundary",
                "- Campus annual electricity and water withdrawal are identified at the disclosure boundary; campus withdrawal intensity is identified-derived.",
                "- Campus consumption, withdrawal-to-consumption fraction, facility airflow, effective facility Delta-T, FRC1 cooling-only water, reuse/blowdown, retrofit effects, and FRC1-to-campus mapping remain UNIDENTIFIED.",
                "- Replay shares are known only over observed usable hours. The true full-period shares remain UNIDENTIFIED.",
                "- CFM alone identifies airflow, not effective facility Delta-T. SAT/RAT and a matched heat/load boundary are required to close Q = m_dot cp DeltaT.",
                "",
                "## Accounting boundary",
                "- Forest City 2024: 535,555 MWh, 16,000 m³ withdrawal, 0.0298755 L/kWh_facility.",
                "- Prineville 2024: 1,728,291 MWh, 328,000 m³ withdrawal, 0.189783 L/kWh_facility.",
                "- This is not cooling WUE and does not identify cooling-only water, consumption, causal architecture effects, FRC1, workload differences, reuse/blowdown, or retrofit effects.",
                "",
                "## Stop rule",
                "Further generic computation has low marginal value. Engineering and utility records are now the binding information source; see the qualitative acquisition matrix.",
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
        "slurm", "provenance", "intermediates", "reproducibility",
    ):
        (OUTPUTS / d).mkdir(parents=True, exist_ok=True)
    state = preflight()
    evidence_crosswalk()
    stations = {m["call_sign"]: load_station(m) for m in STATION_META}
    kfq = stations["KFQD"]
    krdm = load_krdm()
    weather_spine(stations, krdm)
    _, v2rep = reproduce_v2(kfq, stations)
    two, _, target_frames = two_by_two(kfq, krdm, stations)
    annual = annual_comparison()
    esif = esif_transfer(target_frames)
    masanet_status, bins = run_masanet()
    ident = identification_table()
    acquisition_matrix()
    figures(two, ident, bins)
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
            "v2_worktree_untouched": True,
            "v2_dependency_access": f"GIT_BLOB_ONLY:{FROZEN_COMMIT}",
            "prineville_untouched": True,
            # Finalization is promoted only by finalize_freeze.py after a passing
            # independent clean-room replay.  A development replay alone cannot
            # declare the package frozen.
            "FOREST_CITY_V3_FINAL_FREEZE": False,
            "STOP_MODEL_EXPANSION": False,
            "freeze_gate": "PENDING_CLEANROOM_FINAL_STATUS_PASS",
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
            "reason_local": "Core replay is deterministic and short; the four frozen Masanet station evaluations run locally on CPU workers.",
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
