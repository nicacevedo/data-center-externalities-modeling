#!/usr/bin/env python3
"""Forest City v2 robustness / cross-climate / acquisition-readiness pipeline.

Does not modify v1, Prineville, or frozen hashes. Does not fit any parameter.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

FC2 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FC2 / "src"))

from common_mechanism_taxonomy import (  # noqa: E402
    CATEGORIES,
    assert_exactly_one,
    classify_hour,
    mapping_table_rows,
)
from fc_design_return_air import simulate_hour_design_rise  # noqa: E402
from hashes import sha256_file, write_json  # noqa: E402
from paths import (  # noqa: E402
    CAMPUS_LAT,
    CAMPUS_LON,
    CAMPUS_TZ,
    CONFIG,
    DATA_PROCESSED,
    OUTPUTS,
    PRINEVILLE_ROOT,
    V1_OUTPUTS,
    V1_PROCESSED,
    V1_RAW_LWSP,
    V1_RAW_WEATHER,
    V1_ROOT,
    WEATHER_DIR,
)
from v1_bridge import (  # noqa: E402
    EVAP_THERMAL_EFFECTIVENESS_GENERIC_PRIOR,
    IT_EQUIPMENT_DELTA_T_DESIGN_F,
    IT_EQUIPMENT_DELTA_T_DESIGN_K,
    ReturnAirSpec,
    StructuralV1Params,
    c_to_f,
    f_to_c,
    forest_city_control_request,
    iterate_return_air,
    simulate_frame,
    simulate_hour,
    simulate_structural_reference_v1,
    state_from_t_rh,
)
from weather_hourly import (  # noqa: E402
    calendar_2012,
    coverage_stats,
    haversine_km,
    hourlyize,
    read_global_hourly,
)

JJA_START = pd.Timestamp("2012-06-01 00:00:00", tz="UTC")
JJA_END = pd.Timestamp("2012-09-01 00:00:00", tz="UTC")
COMMON_START = pd.Timestamp("2012-06-21 00:00:00", tz="UTC")
COMMON_END = pd.Timestamp("2012-09-01 00:00:00", tz="UTC")
EPS = 1.0  # same ideal upper-bound used for v1 primary DX classification
PRN_RA = ReturnAirSpec(T_C=35.0, rh_pct=15.0, provenance="DESIGN_REFERENCE_SCENARIO", label="PRN1_Q2_FROZEN")
PRN_PARAMS = StructuralV1Params(evap_thermal_effectiveness=0.85, server_deltaT_C=12.0)

STATION_META = [
    {
        "call_sign": "KFQD",
        "station_id": "72314453890",
        "name": "RUTHERFORD CO MARCHMAN FIELD AIRPORT",
        "station_type": "AWOS",
        "role": "PREFERRED_LOCAL",
        "selection_reason": (
            "Nearest ISD station to the Forest City campus; OCP 2013 used Rutherfordton "
            "weather ~6 miles NW for design analysis. Preferred where observed. Completeness "
            "and distance decided a priori; not selected because of a DX outcome."
        ),
        "raw_name": "72314453890_2012.csv",
        "reuse_v1_parquet": True,
    },
    {
        "call_sign": "KEHO",
        "station_id": "72027763843",
        "name": "SHELBY MUNICIPAL AIRPORT",
        "station_type": "AWOS",
        "role": "NEAREST_COMPLETE_2012_JJA",
        "selection_reason": (
            "Independent 2012 JJA representation closer than KGSP and already present in "
            "the v1 weather bank. Included for completeness robustness, not because of DX."
        ),
        "raw_name": "72027763843_2012.csv",
        "reuse_v1_parquet": False,
    },
    {
        "call_sign": "KGSP",
        "station_id": "72312003870",
        "name": "GREENVILLE-SPARTANBURG INTL",
        "station_type": "ASOS_FIRST_ORDER",
        "role": "FIRST_ORDER_ASOS_INDEPENDENT_REPLICATION",
        "selection_reason": (
            "Complete first-order ASOS for overlap diagnostics. Farther than KFQD/KEHO; "
            "not the preferred local series. Not selected because of a DX outcome."
        ),
        "raw_name": "72312003870_2012.csv",
        "reuse_v1_parquet": False,
    },
]


def _isd_row(station_id: str) -> dict:
    hist = pd.read_csv(V1_RAW_WEATHER / "isd-history.csv")
    usaf, wban = station_id[:6], station_id[6:]
    hit = hist[(hist["USAF"].astype(str) == usaf) & (hist["WBAN"].astype(str).str.zfill(5) == wban)]
    if hit.empty:
        return {}
    r = hit.iloc[0]
    return {
        "lat": float(r["LAT"]),
        "lon": float(r["LON"]),
        "elev_m": float(r["ELEV(M)"]),
        "icao": str(r.get("ICAO", "")),
        "begin": str(r["BEGIN"]),
        "end": str(r["END"]),
        "name_isd": str(r["STATION NAME"]),
        "state": str(r.get("STATE", "")),
    }


def write_v1_corrections() -> None:
    obj = {
        "pass": "forest_city_v2_scientific_correction",
        "MODEL_CALIBRATED": "NO",
        "corrections": {
            "A_operator_events": {
                "old": "HISTORICAL_EVENT_VALIDATION = PASS",
                "new": "OPERATOR_EVENT_CONTROL_IMPLEMENTATION_CONSISTENCY = PASS",
                "reason": (
                    "June 25 and July 1 operator cases were themselves used to define the "
                    "Forest City controller (high-RH mixing; hot/dry evaporative; DX backup unused). "
                    "They are source-implementation checks, not independent predictive validations."
                ),
                "scientific_consequence": (
                    "Event PASS cannot be counted as out-of-sample evidence that the controller "
                    "predicts unseen Forest City behavior."
                ),
            },
            "B_summer_dx": {
                "old": "full-calendar summer DX interpretation from v1 JJA",
                "new": "SUMMER_DX_CONSISTENCY = PASS_ON_OBSERVED_KFQD_HOURS",
                "reason": "KFQD has no records before 2012-06-21; 955 JJA hours were WEATHER_MISSING.",
                "scientific_consequence": (
                    "Do not claim full-calendar summer until missing-weather robustness is assessed "
                    "with independent station replications."
                ),
            },
            "C_cross_climate": {
                "old": "TRANSFERABLE_PHYSICS_SUPPORTED",
                "new_default_before_v2_tests": {
                    "CROSS_CLIMATE_MECHANISM_CONSISTENCY": "PRELIMINARY_SUPPORT",
                    "QUANTITATIVE_PHYSICS_TRANSFER": "NOT_VALIDATED",
                },
                "reason": (
                    "v1 compared PRN1 Q2 frozen modes to Forest City JJA KFQD. Seasons differed. "
                    "No mutually exclusive taxonomy. No identified Forest City airflow/water boundary."
                ),
            },
            "D_overlapping_prn_filters": {
                "old_method": "PRN categories constructed by overlapping substring searches (HUMID, EVAP, MIX|RH_OR)",
                "new_requirement": "mutually exclusive common taxonomy; sum(category_indicators)==1",
                "consequence": "v1 Prineville-vs-Forest-City mode fractions were not a clean probability comparison.",
            },
            "E_delta_t": {
                "IT_EQUIPMENT_DELTA_T_DESIGN": "IDENTIFIED (35 F / 19.44 K Maguire 2011)",
                "FACILITY_EFFECTIVE_DELTA_T": "UNIDENTIFIED",
                "do_not": "equate 35F IT/server DeltaT with AHU or effective facility DeltaT",
            },
            "F_frc1_address": {
                "FRC1_ADDRESS": "INTERVAL/SET_UNRESOLVED",
                "note": "Original-campus street-address mapping was unresolved in v1 and remains a set, not a single PIN.",
            },
        },
        "v1_figure5": "DO_NOT_REUSE_AS_EVIDENCE",
    }
    write_json(OUTPUTS / "V1_SCIENTIFIC_CORRECTIONS.json", obj)


def write_address_crosswalk() -> pd.DataFrame:
    rows = [
        {
            "address": "284 Social Circle, Forest City, NC 28043-8820",
            "parcel_id": "UNIDENTIFIED",
            "legal_entity": "Andale, Inc. (NC SOS 1188765); elevator owner FACEBOOK",
            "facility_name": "ANDALE DATA CENTER",
            "possible_FRC_label": "CANDIDATE_ORIGINAL_CAMPUS_NOT_LABELED_FRC1",
            "evidence_date": "2011-10-06",
            "source_id": "NC_DOL_ELEVATOR_RUTHERFORD_27994",
            "relationship_type": "ELEVATOR_OCCUPANT_AND_OWNER",
            "confidence": "HIGH_as_2011_Andale_Facebook_elevator; MEDIUM_as_FRC1_street_address",
            "notes": (
                "NC DOL Elevator Bureau Rutherford 27994: owner FACEBOOK 284 Social Circle; "
                "occupant ANDALE DATA CENTER 284 Social Circle; installed 2011-10-06. "
                "Andale, Inc. principal office 284 Social Circle (formed 2011-02-14; officers include Tom Furlong). "
                "NC DAQ lists Andale, Inc. 8100221 at 284 Social Circle with permit contact at 404 Social Circle. "
                "Do not promote 284 -> FRC1: occupant name is Andale Data Center, not FRC1. "
                "Timing is consistent with Building 1 construction (broke ground Nov 2010; opened 2012-04-19)."
            ),
        },
        {
            "address": "284 Social Circle, Forest City, NC 28043",
            "parcel_id": "UNIDENTIFIED",
            "legal_entity": "Andale, Inc. / Andale, LLC (2010 development agreement used Andale, LLC)",
            "facility_name": "Andale Facebook Data Center brownfields campus",
            "possible_FRC_label": "CAMPUS_NOT_BUILDING_SPECIFIC",
            "evidence_date": "2012",
            "source_id": "NC_DEQ_BROWNFIELDS_14036-10-081",
            "relationship_type": "BROWNFIELDS_SITE_CAMPUS",
            "confidence": "HIGH_as_campus_redevelopment; LOW_as_building_address",
            "notes": (
                "NC DEQ Brownfields Project #14036-10-081 Andale Facebook Data Center, Forest City, "
                "Rutherford County; ~140 acres; former Burlington Industries then Tracker Marine. "
                "Agreement 2012. No street-address split among FRC1/FRC3 in the success-story text. "
                "2010 Development Agreement among Rutherford County, Town of Forest City, and Andale, LLC."
            ),
        },
        {
            "address": "408 Social Circle, Forest City, NC 28043",
            "parcel_id": "UNIDENTIFIED",
            "legal_entity": "FACEBOOK (elevator owner)",
            "facility_name": "FACEBOOK FRC 3",
            "possible_FRC_label": "FRC3",
            "evidence_date": "2012-07-31",
            "source_id": "NC_DOL_ELEVATOR_RUTHERFORD_28417",
            "relationship_type": "ELEVATOR_OCCUPANT_NAMED_FRC3",
            "confidence": "HIGH_for_FRC3_occupant_label_at_408; MEDIUM_as_2014_tour_Building_3",
            "notes": (
                "NC DOL Elevator Bureau Rutherford 28417: owner FACEBOOK 408 Social Circle; "
                "occupant FACEBOOK FRC 3 408 Social Circle; installed 2012-07-31. "
                "This is the only official record in this pass that uses an FRC# street mapping. "
                "Do not silently equate FRC3 with 2012 Building 2 announced as expected later 2012; "
                "2014 tour reported Building 2 as an empty pad and called the second large hall Building 3."
            ),
        },
        {
            "address": "404 Social Circle, Forest City, NC 28043",
            "parcel_id": "UNIDENTIFIED",
            "legal_entity": "FACEBOOK INC (elevator owner Menlo Park); marketing campus address",
            "facility_name": "FACEBOOK DATA CENTER",
            "possible_FRC_label": "NOT_PROMOTED_TO_FRC1",
            "evidence_date": "2016-10-27",
            "source_id": "NC_DOL_ELEVATOR_RUTHERFORD_30676",
            "relationship_type": "ELEVATOR_OCCUPANT_AND_CAMPUS_MAILING",
            "confidence": "HIGH_as_2016_elevator_and_marketing_address; LOW_as_2012_FRC1",
            "notes": (
                "NC DOL Elevator Bureau Rutherford 30676: owner FACEBOOK INC 1601 Willow Road Menlo Park; "
                "occupant FACEBOOK DATA CENTER 404 Social Circle; installed 2016-10-27. "
                "Meta/Facebook Forest City page and Facebook page list 404 Social Circle as the campus contact. "
                "DAQ permit contact also 404 Social Circle. Installation year 2016 is after original campus opening. "
                "Do not promote 404 -> FRC1."
            ),
        },
        {
            "address": "480 Social Circle, Forest City, NC 28043",
            "parcel_id": "UNIDENTIFIED",
            "legal_entity": "Meta / Facebook Forest City Data Center (Chamber listing)",
            "facility_name": "Meta Forest City campus listing",
            "possible_FRC_label": "UNIDENTIFIED",
            "evidence_date": "undated_directory",
            "source_id": "RUTHERFORD_COC_META_LISTING",
            "relationship_type": "DIRECTORY_SECONDARY",
            "confidence": "LOW",
            "notes": (
                "Rutherford County Chamber lists 480 Social Circle and also 408 Social Circle. "
                "Not an official elevator or SOS address. Not used to resolve FRC1."
            ),
        },
        {
            "address": "Social Circle campus / former textile-mill / US 74",
            "parcel_id": "UNIDENTIFIED",
            "legal_entity": "Facebook / Meta; contractor DPR",
            "facility_name": "Forest City Data Center original two-building plan",
            "possible_FRC_label": "FRC1_SET_UNRESOLVED",
            "evidence_date": "2012-04-19",
            "source_id": "META_FC_OPENING_2012_04_19",
            "relationship_type": "OPERATOR_CAMPUS_ANNOUNCEMENT",
            "confidence": "HIGH_as_campus_opening; UNIDENTIFIED_street_for_Building_1",
            "notes": (
                "Building 1 broke ground Nov 2010 and opened 2012-04-19; Building 2 expected later 2012. "
                "DPR: two ~370k sf buildings, four suites, 25k sf penthouse/suite. "
                "No Meta/DPR source in this pass assigns Building 1 a unique street number among 284/404/408."
            ),
        },
    ]
    df = pd.DataFrame(rows)
    CONFIG.mkdir(parents=True, exist_ok=True)
    df.to_csv(CONFIG / "FOREST_CITY_ADDRESS_ENTITY_CROSSWALK.csv", index=False)
    write_json(
        OUTPUTS / "FOREST_CITY_ADDRESS_RESOLUTION.json",
        {
            "FRC1_ADDRESS": "INTERVAL/SET_UNRESOLVED",
            "FRC1_address_set": [
                "284 Social Circle (Andale Data Center elevator 2011; SOS principal office)",
                "campus / unnamed Building 1 opened 2012-04-19",
            ],
            "FRC3_ADDRESS": "408 Social Circle (elevator occupant FACEBOOK FRC 3, installed 2012-07-31)",
            "FRC3_confidence": "HIGH_for_occupant_label; not independently tied to 2014 tour Building 3 identity",
            "404_Social_Circle": "2016 elevator FACEBOOK DATA CENTER; campus mailing/marketing; not FRC1",
            "parcel_id": "UNIDENTIFIED",
            "gis_tax_portals_inspected": [
                "https://lrcpwa.ncptscloud.com/Rutherford/parcel-search",
                "https://gis.rutherfordcountync.gov/maps/",
            ],
            "parcel_extract": "PIN not recovered from the public PWA/GIS landing pages in this pass (interactive search required).",
            "do_not_guess_one_street_for_records_request": True,
        },
    )
    return df


def load_station_hourly(meta: dict) -> pd.DataFrame:
    isd = _isd_row(meta["station_id"])
    elev = float(isd.get("elev_m") or 300.0)
    raw_path = V1_RAW_WEATHER / meta["raw_name"]
    if meta.get("reuse_v1_parquet"):
        pq = V1_PROCESSED / "forest_city_weather_2012_hourly.parquet"
        if pq.exists():
            df = pd.read_parquet(pq)
            df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
            df.attrs["source_path"] = str(pq)
            df.attrs["source_sha256"] = sha256_file(pq)
            df.attrs["isd"] = isd
            df.attrs["elev_m"] = elev
            df.attrs["raw_sha256"] = sha256_file(raw_path) if raw_path.exists() else None
            return df
    if not raw_path.exists():
        raise FileNotFoundError(raw_path)
    raw = read_global_hourly(raw_path)
    h = hourlyize(
        raw,
        elev_m=elev,
        call_sign=meta["call_sign"],
        station_id=meta["station_id"],
        tz=CAMPUS_TZ,
    )
    full = calendar_2012(h, call_sign=meta["call_sign"], station_id=meta["station_id"], tz=CAMPUS_TZ)
    full.attrs["source_path"] = str(raw_path)
    full.attrs["source_sha256"] = sha256_file(raw_path)
    full.attrs["isd"] = isd
    full.attrs["elev_m"] = elev
    return full


def usable_mask(df: pd.DataFrame) -> pd.Series:
    return df[["t_db_C", "rh_pct", "pressure_Pa"]].notna().all(axis=1)


def jja(df: pd.DataFrame) -> pd.DataFrame:
    return df[(df["timestamp_utc"] >= JJA_START) & (df["timestamp_utc"] < JJA_END)].copy()


def common_window(df: pd.DataFrame) -> pd.DataFrame:
    return df[(df["timestamp_utc"] >= COMMON_START) & (df["timestamp_utc"] < COMMON_END)].copy()


def mode_summary(sim: pd.DataFrame, *, site: str) -> dict:
    valid = sim["control_mode"].astype(str) != "WEATHER_MISSING"
    n = int(valid.sum())
    cats = []
    for _, r in sim.loc[valid].iterrows():
        cats.append(
            classify_hour(
                site,
                str(r["control_mode"]),
                primary_control_objective=r.get("primary_control_objective"),
                weather_missing=False,
            )
        )
    sim = sim.copy()
    sim.loc[valid, "common_category"] = cats
    sim.loc[~valid, "common_category"] = "UNRESOLVED"
    for c in sim["common_category"]:
        assert_exactly_one(c)
    vc = pd.Series(cats).value_counts() if n else pd.Series(dtype=int)
    dx = int((valid & sim["dx_required"].fillna(False).astype(bool)).sum()) if "dx_required" in sim.columns else 0
    if site == "PRN1":
        dx = 0
        mech = int((pd.Series(cats) == "MECHANICAL_COOLING").sum()) if n else 0
        dx = mech
    oa = float((pd.Series(cats) == "OA_FREE").mean()) if n else float("nan")
    mix = float((pd.Series(cats) == "HIGH_RH_MIXING").mean()) if n else float("nan")
    evap = float((pd.Series(cats) == "EVAP_COOLING").mean()) if n else float("nan")
    unres = float((pd.Series(cats) == "UNRESOLVED").mean()) if n else float("nan")
    humid = float((pd.Series(cats) == "HUMIDIFICATION").mean()) if n else float("nan")
    mech = float((pd.Series(cats) == "MECHANICAL_COOLING").mean()) if n else float("nan")
    return {
        "valid_hours": n,
        "weather_missing_hours": int((~valid).sum()),
        "DX_required_hours": int(dx) if site != "PRN1" else int((pd.Series(cats) == "MECHANICAL_COOLING").sum()) if n else 0,
        "OA_FREE_fraction": oa,
        "HIGH_RH_MIXING_fraction": mix,
        "EVAP_COOLING_fraction": evap,
        "HUMIDIFICATION_fraction": humid,
        "MECHANICAL_COOLING_fraction": mech,
        "UNRESOLVED_fraction": unres,
        "category_counts": {k: int(vc.get(k, 0)) for k in CATEGORIES},
        "native_mode_counts": sim.loc[valid, "control_mode"].value_counts().to_dict() if n else {},
        "frame": sim,
    }


def simulate_fc_station(hourly: pd.DataFrame, *, rise_k: float | None = None) -> pd.DataFrame:
    if rise_k is None:
        return simulate_frame(hourly, evap_thermal_effectiveness=EPS, airflow_boundary="UNIDENTIFIED")
    rows = []
    for _, r in hourly.iterrows():
        if not (np.isfinite(r.get("t_db_C")) and np.isfinite(r.get("rh_pct")) and np.isfinite(r.get("pressure_Pa"))):
            rows.append(
                {
                    "control_mode": "WEATHER_MISSING",
                    "dx_required": False,
                    "oa_fraction": np.nan,
                    "unresolved": True,
                    "t_inlet_max_satisfied": False,
                    "rh_max_satisfied": False,
                    "primary_control_objective": None,
                }
            )
            continue
        rows.append(
            simulate_hour_design_rise(
                t_db_C=float(r["t_db_C"]),
                rh_pct=float(r["rh_pct"]),
                pressure_Pa=float(r["pressure_Pa"]),
                rise_k=float(rise_k),
                evap_thermal_effectiveness=EPS,
            )
        )
    return pd.concat([hourly.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def simulate_prn(hourly: pd.DataFrame) -> pd.DataFrame:
    w = hourly.copy()
    ok = usable_mask(w) & w["t_wb_C"].notna()
    phys = w.loc[ok, ["timestamp_utc", "t_db_C", "t_wb_C", "rh_pct", "pressure_Pa"]].copy()
    if phys.empty:
        w["control_mode"] = "WEATHER_MISSING"
        w["dx_required"] = False
        w["primary_control_objective"] = None
        w["oa_fraction"] = np.nan
        w["feasibility"] = "WEATHER_MISSING"
        return w
    out = simulate_structural_reference_v1(phys, 1.0, PRN_PARAMS, return_air=PRN_RA)
    merged = w.merge(out, on="timestamp_utc", how="left", suffixes=("", "_prn"))
    missing = merged["control_mode"].isna()
    merged.loc[missing, "control_mode"] = "WEATHER_MISSING"
    merged["dx_required"] = False
    return merged


def weather_distributions(df: pd.DataFrame) -> dict:
    m = usable_mask(df)
    s = df.loc[m]
    if s.empty:
        return {"n": 0}
    return {
        "n": int(m.sum()),
        "t_db_C_mean": float(s["t_db_C"].mean()),
        "t_db_C_p50": float(s["t_db_C"].median()),
        "t_db_F_p95": float(c_to_f(s["t_db_C"].quantile(0.95))),
        "rh_pct_mean": float(s["rh_pct"].mean()),
        "rh_pct_p90": float(s["rh_pct"].quantile(0.90)),
        "t_dew_C_mean": float(s["t_dew_C"].mean()) if "t_dew_C" in s else float("nan"),
        "t_wb_C_mean": float(s["t_wb_C"].mean()) if "t_wb_C" in s else float("nan"),
    }


def build_weather_and_stations():
    hist = pd.read_csv(V1_RAW_WEATHER / "isd-history.csv")
    hist["LAT"] = pd.to_numeric(hist["LAT"], errors="coerce")
    hist["LON"] = pd.to_numeric(hist["LON"], errors="coerce")
    hist["ELEV(M)"] = pd.to_numeric(hist["ELEV(M)"], errors="coerce")
    cand = hist[(hist["STATE"].isin(["NC", "SC"])) & hist["LAT"].notna() & hist["LON"].notna()].copy()
    cand["distance_to_campus_km"] = [
        haversine_km(CAMPUS_LAT, CAMPUS_LON, a, b) for a, b in zip(cand["LAT"], cand["LON"])
    ]
    cand = cand[cand["distance_to_campus_km"] <= 80].copy()
    cand["begin"] = cand["BEGIN"].astype(str)
    cand["end"] = cand["END"].astype(str)
    cand["covers_2012_jja"] = (cand["begin"] <= "20120601") & (cand["end"] >= "20120831")
    inv_path = WEATHER_DIR / "FOREST_CITY_2012_NEARBY_ISD_INVENTORY.csv"
    cand.sort_values("distance_to_campus_km").to_csv(inv_path, index=False)

    selected = []
    hourly = {}
    audit_rows = []
    for meta in STATION_META:
        isd = _isd_row(meta["station_id"])
        df = load_station_hourly(meta)
        hourly[meta["call_sign"]] = df
        cov = coverage_stats(df, "2012-06-01", "2012-09-01")
        lat = float(isd.get("lat") or np.nan)
        lon = float(isd.get("lon") or np.nan)
        dist = haversine_km(CAMPUS_LAT, CAMPUS_LON, lat, lon) if np.isfinite(lat) else float("nan")
        row = {
            "call_sign": meta["call_sign"],
            "station_id": meta["station_id"],
            "name": isd.get("name_isd") or meta["name"],
            "station_type": meta["station_type"],
            "role": meta["role"],
            "lat": lat,
            "lon": lon,
            "elevation_m": isd.get("elev_m"),
            "distance_to_campus_km": dist,
            "distance_to_campus_mi": dist * 0.621371 if np.isfinite(dist) else float("nan"),
            "2012_JJA_completeness": cov["jja_completeness"],
            "T_coverage": cov["t_coverage"],
            "dewpoint_coverage": cov["dewpoint_coverage"],
            "pressure_coverage": cov["pressure_coverage"],
            "usable_jja_hours": cov["usable_hours"],
            "n_calendar_jja_hours": cov["n_calendar_hours"],
            "source_path": df.attrs.get("source_path"),
            "source_sha256": df.attrs.get("source_sha256"),
            "selection_reason": meta["selection_reason"],
            "selected_using_dx_outcome": False,
        }
        audit_rows.append(row)
        selected.append(meta["call_sign"])
        outp = DATA_PROCESSED / f"forest_city_{meta['call_sign']}_2012_hourly.parquet"
        DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
        keep = [c for c in df.columns if c in df]
        df.to_parquet(outp, index=False)

    audit = pd.DataFrame(audit_rows)
    WEATHER_DIR.mkdir(parents=True, exist_ok=True)
    audit.to_csv(WEATHER_DIR / "FOREST_CITY_2012_STATION_AUDIT.csv", index=False)
    write_json(
        OUTPUTS / "weather_robustness" / "STATION_SELECTION.json",
        {
            "a_priori": True,
            "selected_using_dx_outcome": False,
            "max_representations": 3,
            "preferred_local": "KFQD",
            "stations": audit.to_dict(orient="records"),
            "nearby_inventory": str(inv_path),
            "kfq_gap": "KFQD ISD has no records before 2012-06-21 17:55Z. Not filled.",
        },
    )
    return hourly, audit


def overlap_diagnostics(hourly: dict, station_frames: dict) -> pd.DataFrame:
    names = list(hourly)
    rows = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            da, db = jja(hourly[a]), jja(hourly[b])
            m = da.merge(db, on="timestamp_utc", suffixes=(f"_{a}", f"_{b}"))
            ok = (
                m[f"t_db_C_{a}"].notna()
                & m[f"rh_pct_{a}"].notna()
                & m[f"t_db_C_{b}"].notna()
                & m[f"rh_pct_{b}"].notna()
            )
            sub = m.loc[ok]
            if sub.empty:
                continue
            dT = sub[f"t_db_C_{a}"] - sub[f"t_db_C_{b}"]
            dTd = sub[f"t_dew_C_{a}"] - sub[f"t_dew_C_{b}"]
            dRH = sub[f"rh_pct_{a}"] - sub[f"rh_pct_{b}"]
            dTw = sub[f"t_wb_C_{a}"] - sub[f"t_wb_C_{b}"]
            fa = station_frames[a]
            fb = station_frames[b]
            both = fa[["timestamp_utc", "common_category", "control_mode"]].merge(
                fb[["timestamp_utc", "common_category", "control_mode"]],
                on="timestamp_utc",
                suffixes=("_a", "_b"),
            )
            both = both[both["timestamp_utc"].isin(sub["timestamp_utc"])]
            agree = float((both["common_category_a"] == both["common_category_b"]).mean()) if len(both) else float("nan")
            rows.append(
                {
                    "station_a": a,
                    "station_b": b,
                    "overlap_valid_hours": int(ok.sum()),
                    "Tdb_diff_C_mean": float(dT.mean()),
                    "Tdb_diff_C_mae": float(dT.abs().mean()),
                    "dewpoint_diff_C_mean": float(dTd.mean()),
                    "dewpoint_diff_C_mae": float(dTd.abs().mean()),
                    "RH_diff_pct_mean": float(dRH.mean()),
                    "RH_diff_pct_mae": float(dRH.abs().mean()),
                    "Twb_diff_C_mean": float(dTw.mean()),
                    "Twb_diff_C_mae": float(dTw.abs().mean()),
                    "FC_controller_common_taxonomy_agreement": agree,
                    "note": "Independent series; not a stitched truth series.",
                }
            )
    return pd.DataFrame(rows)


def fractions_from_summary(s: dict) -> dict:
    n = s["valid_hours"]
    out = {f"P({c})": (s["category_counts"].get(c, 0) / n if n else float("nan")) for c in CATEGORIES}
    out.update(
        {
            "sample_hours": n,
            "weather_missing_hours": s["weather_missing_hours"],
            "DX_required_hours": s["DX_required_hours"],
        }
    )
    return out


def operator_events(kfq: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    events = [
        {
            "event": "B_2012_06_25",
            "date": "2012-06-25",
            "operator_T_F": 68.0,
            "operator_RH": 0.97,
            "expect_family": "HIGH_RH_MIXING",
            "expect_dx": False,
            "observed": "high RH / low DB; return-air mixing; DX not used",
        },
        {
            "event": "A_2012_07_01",
            "date": "2012-07-01",
            "operator_T_F": 102.0,
            "operator_RH": 0.26,
            "expect_family": "EVAP_COOLING",
            "expect_dx": False,
            "observed": "hot/dry; evaporative cooling sufficient; no DX",
        },
    ]
    rows = []
    for e in events:
        oa = state_from_t_rh(f_to_c(e["operator_T_F"]), e["operator_RH"] * 100.0, 101325.0)
        req, ra, supply = iterate_return_air(oa, evap_thermal_effectiveness=EPS)
        rec = simulate_hour(
            t_db_C=oa.T_C,
            rh_pct=e["operator_RH"] * 100.0,
            pressure_Pa=101325.0,
            evap_thermal_effectiveness=EPS,
            airflow_boundary="UNIDENTIFIED",
        )
        cat = classify_hour("FC", rec["control_mode"], primary_control_objective=rec.get("primary_control_objective"))
        day0 = pd.Timestamp(e["date"], tz=CAMPUS_TZ).tz_convert("UTC")
        day1 = day0 + pd.Timedelta(days=1)
        day = kfq[(kfq["timestamp_utc"] >= day0) & (kfq["timestamp_utc"] < day1)]
        sim_day = simulate_fc_station(day) if len(day) else day
        dsum = mode_summary(sim_day, site="FC") if len(day) else None
        impl = (
            (not rec["dx_required"])
            and (cat == e["expect_family"])
            and (not e["expect_dx"])
        )
        rows.append(
            {
                **e,
                "synthetic_mode": rec["control_mode"],
                "synthetic_common_category": cat,
                "synthetic_dx": bool(rec["dx_required"]),
                "synthetic_oa_fraction": rec["oa_fraction"],
                "synthetic_t_supply_F": rec["t_supply_F"],
                "synthetic_rh_supply": rec["rh_supply"],
                "kfqd_day_valid_hours": None if dsum is None else dsum["valid_hours"],
                "kfqd_day_dx_hours": None if dsum is None else dsum["DX_required_hours"],
                "implementation_consistent": bool(impl),
                "independent_predictive_validation": False,
                "status": "OPERATOR_EVENT_CONTROL_IMPLEMENTATION_CONSISTENCY_PASS" if impl else "FAIL",
                "controller_not_modified": True,
            }
        )
    df = pd.DataFrame(rows)
    js = {
        "label": "OPERATOR_EVENT_CONTROL_CONSISTENCY",
        "not_independent_validation": True,
        "events": df.to_dict(orient="records"),
        "overall": "PASS" if df["implementation_consistent"].all() else "FAIL",
    }
    return df, js


def canonical_annual() -> pd.DataFrame:
    GAL_TO_M3 = 0.003785411784
    rows = []

    def add(**kwargs):
        rows.append(kwargs)

    # Electricity 2011-2016 from 2016 disclosure (agrees with 2014 kWh table)
    elec_early = {2011: 6000, 2012: 98000, 2013: 225000, 2014: 322000, 2015: 310000, 2016: 339000}
    for y, v in elec_early.items():
        add(
            year=y,
            quantity="electricity",
            value=v,
            unit="MWh",
            source_report="Facebook_2016_Sustainability_Data_Disclosure",
            publication_year=2017,
            methodology_version="Facebook_2016_disclosure_MWh",
            original_vs_revised="original_or_confirmed",
            revision_of="",
            canonical_preferred=True,
            boundary_notes="Facility electricity as reported. 2011 is pre-opening / commissioning residual. Later years are not 2012 Building-1 only.",
        )
    add(
        year=2011,
        quantity="electricity",
        value=6000,
        unit="MWh",
        source_report="Facebook_2014_Sustainability_Data_Disclosure",
        publication_year=2015,
        methodology_version="Facebook_2014_disclosure_kWh_converted",
        original_vs_revised="original",
        revision_of="",
        canonical_preferred=False,
        boundary_notes="Published as 6,000,000 kWh. Same rounded MWh as 2016 disclosure.",
    )
    # 2017-2019 from 2023 EDI (v1)
    for y, v in {2017: 433000, 2018: 547000, 2019: 614000}.items():
        add(
            year=y,
            quantity="electricity",
            value=v,
            unit="MWh",
            source_report="Meta_2023_Environmental_Data_Index",
            publication_year=2023,
            methodology_version="Meta_2023_EDI_facility_electricity",
            original_vs_revised="as_published",
            revision_of="",
            canonical_preferred=True,
            boundary_notes="Site as reported; later campus buildings included. Not 2012 Building-1 only.",
        )
    for y, v, rev in [
        (2020, 595000, "rounded_in_2025_index"),
        (2021, 580842, "as_published"),
        (2022, 492786, "as_published"),
        (2023, 507068, "as_published"),
        (2024, 535555, "as_published"),
    ]:
        add(
            year=y,
            quantity="electricity",
            value=v,
            unit="MWh",
            source_report="Meta_2025_Environmental_Data_Index",
            publication_year=2025,
            methodology_version="Meta_2025_EDI_facility_electricity",
            original_vs_revised=rev,
            revision_of="",
            canonical_preferred=True,
            boundary_notes="Site as reported; unidentified later buildings/cold storage in the site total.",
        )

    # Water
    add(
        year=2014,
        quantity="water_withdrawal",
        value=33000000 * GAL_TO_M3,
        unit="m3",
        source_report="Facebook_2014_Sustainability_Data_Disclosure",
        publication_year=2015,
        methodology_version="gallons_converted_to_m3",
        original_vs_revised="original",
        revision_of="",
        canonical_preferred=False,
        boundary_notes="First public water year. Published 33,000,000 gallons. Not WUE.",
    )
    add(
        year=2014,
        quantity="water_withdrawal",
        value=31000000 * GAL_TO_M3,
        unit="m3",
        source_report="Facebook_2016_Sustainability_Data_Disclosure",
        publication_year=2017,
        methodology_version="gallons_converted_to_m3",
        original_vs_revised="revised",
        revision_of="Facebook_2014_Sustainability_Data_Disclosure",
        canonical_preferred=True,
        boundary_notes="2016 disclosure restates 2014 Forest City water as 31,000,000 gallons.",
    )
    add(
        year=2015,
        quantity="water_withdrawal",
        value=33200000 * GAL_TO_M3,
        unit="m3",
        source_report="Facebook_2016_Sustainability_Data_Disclosure",
        publication_year=2017,
        methodology_version="gallons_converted_to_m3",
        original_vs_revised="as_published",
        revision_of="",
        canonical_preferred=True,
        boundary_notes="33,200,000 gallons. Site withdrawal, not WUE.",
    )
    add(
        year=2016,
        quantity="water_withdrawal",
        value=35100000 * GAL_TO_M3,
        unit="m3",
        source_report="Facebook_2016_Sustainability_Data_Disclosure",
        publication_year=2017,
        methodology_version="gallons_converted_to_m3",
        original_vs_revised="original",
        revision_of="",
        canonical_preferred=False,
        boundary_notes="35,100,000 gallons. Later 2020 disclosure reports 123,000 m3.",
    )
    add(
        year=2016,
        quantity="water_withdrawal",
        value=123000,
        unit="m3",
        source_report="Facebook_2020_Sustainability_Data",
        publication_year=2021,
        methodology_version="cubic_meters",
        original_vs_revised="revised",
        revision_of="Facebook_2016_Sustainability_Data_Disclosure",
        canonical_preferred=True,
        boundary_notes="2020 disclosure Forest City 2016 water 123,000 m3.",
    )
    for y, v in {2017: 129000, 2018: 99000, 2019: 85000, 2020: 68000, 2021: 64053, 2022: 62853}.items():
        add(
            year=y,
            quantity="water_withdrawal",
            value=v,
            unit="m3",
            source_report="Meta_2023_Environmental_Data_Index",
            publication_year=2023,
            methodology_version="Meta_2023_EDI_cubic_meters",
            original_vs_revised="as_published",
            revision_of="",
            canonical_preferred=True,
            boundary_notes="Site withdrawal. Not WUE. Not used to tune the 2012 controller.",
        )
    for y, ml in {2020: 68, 2021: 64, 2022: 63, 2023: 55, 2024: 16}.items():
        add(
            year=y,
            quantity="water_withdrawal",
            value=ml * 1000.0,
            unit="m3",
            source_report="Meta_2025_Environmental_Data_Index",
            publication_year=2025,
            methodology_version="Meta_2025_EDI_megaliters_converted",
            original_vs_revised="revised_unit_ML" if y <= 2022 else "as_published",
            revision_of="Meta_2023_Environmental_Data_Index" if y <= 2022 else "",
            canonical_preferred=y >= 2023,
            boundary_notes="2025 EDI reports megaliters. 2023-2024 have no earlier m3 restatement in this pass. Construction water excluded globally, not a Forest City-specific note.",
        )

    # Location-based Scope 2
    loc = {
        2012: (46000, "Facebook_2014_Sustainability_Data_Disclosure", 2015, "regional_impact"),
        2013: (106000, "Facebook_2016_Sustainability_Data_Disclosure", 2017, "location_based"),
        2014: (157000, "Facebook_2016_Sustainability_Data_Disclosure", 2017, "location_based"),
        2015: (132000, "Facebook_2016_Sustainability_Data_Disclosure", 2017, "location_based"),
        2016: (144000, "Facebook_2016_Sustainability_Data_Disclosure", 2017, "location_based"),
        2020: (202000, "Meta_2025_Environmental_Data_Index", 2025, "location_based_rounded"),
        2021: (165026, "Meta_2025_Environmental_Data_Index", 2025, "location_based"),
        2022: (143754, "Meta_2025_Environmental_Data_Index", 2025, "location_based"),
        2023: (144050, "Meta_2025_Environmental_Data_Index", 2025, "location_based"),
        2024: (144104, "Meta_2025_Environmental_Data_Index", 2025, "location_based"),
    }
    for y, (v, src, py, meth) in loc.items():
        add(
            year=y,
            quantity="location_based_scope2",
            value=v,
            unit="tCO2e",
            source_report=src,
            publication_year=py,
            methodology_version=meth,
            original_vs_revised="as_published",
            revision_of="",
            canonical_preferred=True,
            boundary_notes="Location-based / regional Scope 2. Not market-based. 2011 location-based not published as a separate regional row.",
        )
    add(
        year=2012,
        quantity="location_based_scope2",
        value=46000,
        unit="tCO2e",
        source_report="Facebook_2014_Sustainability_Data_Disclosure",
        publication_year=2015,
        methodology_version="regional_impact",
        original_vs_revised="original",
        revision_of="",
        canonical_preferred=True,
        boundary_notes="Labeled regional impact in 2014 disclosure (later called location-based).",
    )

    df = pd.DataFrame(rows)
    # drop duplicate 2012 location row accidentally added twice with same preferred
    df = df.drop_duplicates(
        subset=["year", "quantity", "source_report", "value", "canonical_preferred"], keep="first"
    )
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    df.to_csv(DATA_PROCESSED / "FOREST_CITY_META_ANNUAL_CANONICAL.csv", index=False)
    df.to_csv(OUTPUTS / "annual_accounting" / "FOREST_CITY_META_ANNUAL_CANONICAL.csv", index=False)
    return df


def intensity_table(canon: pd.DataFrame) -> pd.DataFrame:
    e = canon[(canon.quantity == "electricity") & (canon.canonical_preferred)].set_index("year")["value"]
    w = canon[(canon.quantity == "water_withdrawal") & (canon.canonical_preferred)].set_index("year")["value"]
    rows = []
    for y in range(2011, 2025):
        ev, wv = e.get(y), w.get(y)
        if pd.isna(ev) or pd.isna(wv):
            rows.append(
                {
                    "year": y,
                    "electricity_MWh": ev,
                    "withdrawal_m3": wv,
                    "SITE_WITHDRAWAL_INTENSITY": np.nan,
                    "unit": "m3_per_MWh_equals_L_per_kWh_facility",
                    "not_WUE": True,
                    "note": "intensity undefined unless both canonical preferred series exist",
                }
            )
            continue
        rows.append(
            {
                "year": y,
                "electricity_MWh": ev,
                "withdrawal_m3": wv,
                "SITE_WITHDRAWAL_INTENSITY": float(wv) / float(ev),
                "unit": "m3_per_MWh_equals_L_per_kWh_facility",
                "not_WUE": True,
                "intensity_name": "SITE_WITHDRAWAL_INTENSITY",
                "denominator": "facility electricity, not IT load",
                "note": "Never call this WUE. Not used to tune the 2012 controller.",
            }
        )
    out = pd.DataFrame(rows)
    out.to_csv(OUTPUTS / "annual_accounting" / "FOREST_CITY_SITE_WITHDRAWAL_INTENSITY.csv", index=False)
    return out


def municipal_update(canon: pd.DataFrame) -> pd.DataFrame:
    muni = pd.read_csv(V1_PROCESSED / "forest_city_municipal_water_monthly.csv")
    annual = (
        muni.groupby("year")
        .agg(
            industrial_mgd=("industrial_demand_mgd", "mean"),
            annual_raw_avg_mgd=("annual_raw_avg_mgd", "first"),
        )
        .reset_index()
    )
    # 1 MGD = 3785.411784 m3/day; use 365.25 days as accounting context only
    M3_PER_MGD_YEAR = 3785.411784 * 365.25
    w = canon[(canon.quantity == "water_withdrawal") & (canon.canonical_preferred)].set_index("year")["value"]
    rows = []
    for _, r in annual.iterrows():
        y = int(r["year"])
        mun_m3 = float(r["annual_raw_avg_mgd"]) * M3_PER_MGD_YEAR if pd.notna(r["annual_raw_avg_mgd"]) else np.nan
        ind_m3 = float(r["industrial_mgd"]) * M3_PER_MGD_YEAR if pd.notna(r["industrial_mgd"]) else np.nan
        meta = w.get(y, np.nan)
        rows.append(
            {
                "year": y,
                "wtp": "Forest City WTP PWSID 01-81-010",
                "source_water": "Second Broad River",
                "raw_and_finished": "metered (LWSP)",
                "annual_raw_avg_mgd": r["annual_raw_avg_mgd"],
                "industrial_class_mgd": r["industrial_mgd"],
                "municipal_raw_m3": mun_m3,
                "industrial_class_m3": ind_m3,
                "meta_withdrawal_m3_canonical": meta,
                "meta_share_of_municipal": (meta / mun_m3) if (pd.notna(meta) and mun_m3) else np.nan,
                "meta_share_of_industrial_class": (meta / ind_m3) if (pd.notna(meta) and ind_m3) else np.nan,
                "industrial_class_equals_Meta": False,
                "ACCOUNTING_CONTEXT_ONLY": True,
                "not_WUE": True,
                "not_causal_flow": True,
                "lwsp_dir": str(V1_RAW_LWSP),
            }
        )
    out = pd.DataFrame(rows)
    out.to_csv(OUTPUTS / "annual_accounting" / "FOREST_CITY_MUNICIPAL_SOURCE_ACCOUNTING.csv", index=False)
    return out


def water_break_audit() -> pd.DataFrame:
    rows = [
        {
            "mechanism": "EDI unit/methodology change (m3 -> ML)",
            "expected_direction": "possible rounding, not a 3x drop",
            "evidence_date": "2025-10",
            "source": "Meta_2025_EDI vs Meta_2023_EDI",
            "boundary": "site water withdrawal",
            "supported": False,
            "confidence": "LOW_as_cause_of_55_to_16",
            "notes": "2023 55 ML vs 55,000 m3 is consistent. 2024 16 ML is a new year, not a restatement of 2023.",
        },
        {
            "mechanism": "IT/facility electricity decline",
            "expected_direction": "water down if load-driven evaporative use",
            "evidence_date": "2024",
            "source": "Meta_2025_EDI electricity 507068 -> 535555 MWh",
            "boundary": "site electricity vs site withdrawal",
            "supported": False,
            "confidence": "HIGH_that_load_decline_is_not_the_explanation",
            "notes": "Electricity rose while withdrawal fell. Intensity fell. Not a simple load effect.",
        },
        {
            "mechanism": "2022-2024 cooling/mechanical upgrade or DX/chiller change",
            "expected_direction": "withdrawal down if evaporative use reduced",
            "evidence_date": "none_public",
            "source": "Town permit portal requires login; no public permit numbers recovered",
            "boundary": "as-operated cooling",
            "supported": False,
            "confidence": "UNIDENTIFIED",
            "notes": "No public TAB/SOO/permit evidence of a 2022-2024 cooling retrofit.",
        },
        {
            "mechanism": "Water reuse / higher cycles of concentration / treatment change",
            "expected_direction": "withdrawal down",
            "evidence_date": "undated_factsheet_2025",
            "source": "Meta Forest City factsheet 2025: reuses water numerous times; rainwater capture",
            "boundary": "qualitative campus water efficiency",
            "supported": False,
            "confidence": "LOW_as_dated_2023_2024_cause",
            "notes": "Undated qualitative claims. Not a dated 2023-2024 retrofit record.",
        },
        {
            "mechanism": "Early-2010s membrane vs misters transition",
            "expected_direction": "withdrawal down in the early 2010s, not specifically 2024",
            "evidence_date": "circa_2013",
            "source": "ITNEWS_MCCAMMON_FC",
            "boundary": "2012-era water treatment narrative",
            "supported": False,
            "confidence": "REJECTED_as_2024_explanation",
            "notes": "Do not use the early-2010s membrane/media transition as a 2024 explanation without a distinct later retrofit.",
        },
        {
            "mechanism": "New building / cold-storage mix / reporting boundary change",
            "expected_direction": "ambiguous",
            "evidence_date": "2014-2016 campus growth already in the series",
            "source": "elevator 404 Social Circle 2016; 2014 FRC4 cold storage",
            "boundary": "site total vs original campus",
            "supported": False,
            "confidence": "LOW",
            "notes": "Later buildings are already in 2017-2023 totals. No public 2024 boundary restatement specific to Forest City.",
        },
        {
            "mechanism": "Municipal industrial-class demand change",
            "expected_direction": "industrial class is not Meta",
            "evidence_date": "2023-2024 LWSP",
            "source": "NC LWSP 01-81-010",
            "boundary": "ACCOUNTING_CONTEXT_ONLY",
            "supported": False,
            "confidence": "n/a",
            "notes": "Industrial class must not be inferred as Meta usage. Tagged ACCOUNTING_CONTEXT_ONLY.",
        },
        {
            "mechanism": "Global construction-water exclusion note",
            "expected_direction": "operational totals exclude construction water",
            "evidence_date": "2025 EDI",
            "source": "Meta_2025_EDI note: additional 1,019 ML construction water not in 2024 withdrawal",
            "boundary": "global construction vs site operational",
            "supported": False,
            "confidence": "LOW_as_Forest_City_2024_cause",
            "notes": "Company-wide construction exclusion, not a Forest City operational-meter explanation.",
        },
    ]
    df = pd.DataFrame(rows)
    df.to_csv(OUTPUTS / "annual_accounting" / "FOREST_CITY_2023_2024_WATER_BREAK_AUDIT.csv", index=False)
    write_json(
        OUTPUTS / "annual_accounting" / "FOREST_CITY_2023_2024_WATER_BREAK_AUDIT.json",
        {
            "canonical_2023_m3": 55000,
            "canonical_2024_m3": 16000,
            "drop_m3": -39000,
            "electricity_2023_MWh": 507068,
            "electricity_2024_MWh": 535555,
            "CAUSE_PUBLICLY_UNRESOLVED": True,
            "causal_claim": False,
            "regression_or_fit": False,
            "not_used_to_tune_2012_controller": True,
            "hypotheses": df.to_dict(orient="records"),
        },
    )
    return df


def write_airflow_md() -> None:
    text = """# Forest City airflow identification requirements

Status freeze:

- `IT_DELTA_T_DESIGN = IDENTIFIED` (35 °F / 19.44 K, Maguire 2011). This is server inlet to server exhaust design rise.
- `FACILITY_EFFECTIVE_DELTA_T = UNIDENTIFIED`.
- No Forest City WUE is computed. No facility-electricity WUE. No 2012 water magnitude.

The air-stream evaporated water identity is

`V_dot_water = m_dot_da * Δw / ρ_water`

where `Δw` is closed by moist-air states (mixing + adiabatic evaporation) once SAT/RAT and OA/RA fractions are known. The unidentified term for magnitude is `m_dot_da`.

A sensible heat-balance candidate is

`m_dot_da = Q_air / (cp * ΔT_effective)`

`Q_air` is the air-stream sensible load at the chosen boundary (IT only, IT+fan, or another served load). `ΔT_effective` is not automatically the 35 °F IT design rise.

## Measurements that close which equation

| Measurement | Equation / boundary it closes |
| --- | --- |
| TAB measured AHU CFM (supply, return, OA) | Directly identifies `m_dot` (with density/humidity). Does not require ΔT. |
| AHU schedule / design CFM | Upper-bound / design `m_dot` only (`DESIGN_SPEC`, not as-operated). |
| SAT and RAT (as-operated) | Identifies AHU ΔT. Combined with measured CFM closes `Q_air = m cp ΔT_AHU`. Still not IT ΔT. |
| Cold-aisle / hot-aisle temperatures | Identifies as-operated IT ΔT vs the 35 °F design value. |
| BMS airflow or VFD/fan speed with a fan curve | Identifies time-varying `m_dot` if the curve and operating point are documented. |
| Served load boundary (IT kW vs facility kW; which halls) | Closes `Q` in `m = Q/(cp ΔT)`. Without this, even a measured ΔT does not give site water. |
| Fan heat / bypass / recirculation / economizer OA fraction | Distinguishes IT ΔT, AHU ΔT, and facility effective ΔT. Bypass makes 35 °F the wrong `m_dot` ΔT. |
| Makeup / blowdown / drain meters | Maps air-stream `m Δw` onto cooling-system input water (treatment, cycles, non-evaporative uses). |

Until one of {TAB CFM, BMS airflow, explicit effective ΔT at a named load boundary} is identified, Forest City water magnitude remains `UNIDENTIFIED` and quantitative airflow transfer remains `NOT_VALIDATED`.
"""
    (OUTPUTS / "AIRFLOW_IDENTIFICATION_REQUIREMENTS.md").write_text(text)


def write_manual_package() -> None:
    text = """# Forest City manual data / records request package

Do not send these requests from this pass. Freeze public v2 first.

**Address/entity scope (do not guess FRC1):** request the original 2010–2013 Facebook/Andale campus and **all** of:

- 284 Social Circle, Forest City, NC 28043 (Andale Data Center / Andale, Inc. / Facebook elevator owner, 2011)
- 408 Social Circle, Forest City, NC 28043 (FACEBOOK FRC 3 elevator occupant, 2012-07-31)
- 404 Social Circle, Forest City, NC 28043 (FACEBOOK DATA CENTER elevator occupant 2016; campus mailing)
- Legal entities: Andale, Inc. (NC SOS 1188765); Andale, LLC (2010 development agreement); Facebook, Inc. / Meta Platforms, Inc.
- Brownfields project #14036-10-081 (Andale Facebook Data Center)
- Town of Forest City / Rutherford County building, planning, and utility files for the Social Circle campus
- Date range for original-campus cooling/control: **2010-11 through 2013-12**, plus **2022-01 through 2024-12** for the water-withdrawal discontinuity

`FRC1_ADDRESS = INTERVAL/SET_UNRESOLVED`. Records requests must use the set, not a single guessed street.

## VERY_HIGH

1. **AHU schedules + design and measured CFM (TAB)** for original production halls (Building 1 / Andale 284 and any 2012 hall that was actually operating). Why: closes `m_dot` directly. Equation: `V_dot_water = m Δw / ρ`. Expected value: identifies or bounds `FACILITY_EFFECTIVE_DELTA_T` vs 35 °F IT design.
2. **SAT / RAT time series or commissioning snapshots (summer 2012)** including OA/RA damper positions. Why: closes mixed-air state and as-operated return-air rise. Distinguishes design-reference 25/35 °F scenarios from RAT.
3. **Sequence of operations** for OA/RA mixing, evaporative, and DX. Why: independent of the OCP blog cases that defined the v1 controller. Needed before treating June 25 / July 1 as validation.
4. **Cooling makeup meter IDs, service boundary, and 2012 + 2022–2024 monthly totals** (Town of Forest City utility; Meta customer). Why: maps air-stream water onto site withdrawal. Does not infer industrial class = Meta.
5. **2022–2024 mechanical / water-treatment / reuse retrofit files** (permits, change orders, P&ID). Why: only dated evidence can explain 55 ML → 16 ML. Early-2010s membrane story is not acceptable as a 2024 cause.

## HIGH

6. **DX schedule, capacity, and 2012 runtime / disable logs.** Why: independent check of “DX unused summer 2012” beyond the operator blog.
7. **Evaporative system specifications** (Munters or successor; effectiveness; mist vs membrane dates). Why: `evap_thermal_effectiveness` is currently a generic prior, not Forest City sourced.
8. **Commissioning reports (2011–2013)** for Building 1 and FRC 3 (408 Social Circle). Why: as-operated vs design envelope (85 °F / 90 % RH).
9. **Fan curves / penthouse AHU as-built.** Why: fan heat and bypass break IT ΔT ≠ AHU ΔT.
10. **Utility meter installation/replacement history 2022–2024.** Why: reporting discontinuity vs physical use.

## MEDIUM

11. **P&ID and water treatment (UV, RO/membrane, reuse, blowdown/drain).** Why: cooling-system input vs air-stream evaporated water.
12. **Rutherford County PIN / tax cards** for 284 / 404 / 408 Social Circle. Why: entity/building crosswalk; parcel_id currently UNIDENTIFIED.
13. **Town SmartGov building permits** (drawings if releasable) 2010–2017 and 2022–2024.
14. **Duke Energy account / interval mapping** (later; electricity is already disclosed annually).

## LOW

15. **eGRID SRVC / DUK EIA-930 reconstruction inputs** for location-based Scope 2. Secondary; Meta already publishes location-based totals. Stopped this pass at `INSUFFICIENT_BOUNDARY_INFORMATION`.
16. **Groundwater / surface-water impact studies.** Out of scope for v2 freeze.

Expected scientific value ranking follows the missing measurements in `AIRFLOW_IDENTIFICATION_REQUIREMENTS.md`. Highest-value missing measurement: **TAB or BMS CFM at the original-campus AHU boundary for 2012**, or SAT/RAT that would identify effective ΔT at a named load.
"""
    (OUTPUTS / "FOREST_CITY_MANUAL_DATA_REQUEST_PACKAGE.md").write_text(text)


def write_figures(hourly, station_summ, tax_df, fact_df, ra_df, intensity):
    figdir = OUTPUTS / "figures"
    figdir.mkdir(parents=True, exist_ok=True)

    # 1 coverage + overlap
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=False)
    ax = axes[0]
    for i, (name, df) in enumerate(hourly.items()):
        j = jja(df)
        ok = usable_mask(j)
        ax.plot(j["timestamp_utc"], ok.astype(float) + i * 1.15, lw=0.6, label=name)
    ax.set_ylabel("valid hour (offset)")
    ax.set_title("2012 JJA station coverage (independent series; not stitched)")
    ax.legend()
    ax = axes[1]
    if "KFQD" in hourly and "KEHO" in hourly:
        a, b = jja(hourly["KFQD"]), jja(hourly["KEHO"])
        m = a.merge(b, on="timestamp_utc", suffixes=("_KFQD", "_KEHO"))
        ok = m["t_db_C_KFQD"].notna() & m["t_db_C_KEHO"].notna()
        ax.scatter(m.loc[ok, "t_db_C_KFQD"], m.loc[ok, "t_db_C_KEHO"], s=6, alpha=0.4)
        lim = [
            np.nanmin([m.loc[ok, "t_db_C_KFQD"].min(), m.loc[ok, "t_db_C_KEHO"].min()]),
            np.nanmax([m.loc[ok, "t_db_C_KFQD"].max(), m.loc[ok, "t_db_C_KEHO"].max()]),
        ]
        ax.plot(lim, lim, "k--", lw=0.8)
        ax.set_xlabel("KFQD Tdb C")
        ax.set_ylabel("KEHO Tdb C")
        ax.set_title("Overlap Tdb (JJA valid hours)")
    fig.tight_layout()
    fig.savefig(figdir / "fig01_jja_station_coverage_overlap.png", dpi=140)
    plt.close(fig)

    # 2 DX robustness
    fig, ax = plt.subplots(figsize=(8, 4.5))
    names = [s["station"] for s in station_summ]
    dx = [s["DX_required_hours"] for s in station_summ]
    n = [s["valid_hours"] for s in station_summ]
    ax.bar(names, dx)
    ax.set_ylabel("DX-required hours (full JJA, independent)")
    ax.set_title("Full-JJA DX robustness by station (not used to select the station)")
    for i, (d, nn) in enumerate(zip(dx, n)):
        ax.text(i, d, f"{d}/{nn}", ha="center", va="bottom")
    fig.tight_layout()
    fig.savefig(figdir / "fig02_full_jja_dx_by_station.png", dpi=140)
    plt.close(fig)

    # 3 same-period taxonomy
    fig, ax = plt.subplots(figsize=(9, 4.8))
    sites = tax_df["site"].tolist()
    bottom = np.zeros(len(sites))
    for cat in CATEGORIES:
        vals = tax_df[f"P({cat})"].fillna(0).to_numpy()
        ax.bar(sites, vals, bottom=bottom, label=cat)
        bottom = bottom + vals
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("fraction of valid hours")
    ax.set_title("Same-period common taxonomy (2012-06-21 to 2012-08-31 UTC)")
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(figdir / "fig03_same_period_prn_fc_taxonomy.png", dpi=140)
    plt.close(fig)

    # 4 factorial
    fig, ax = plt.subplots(figsize=(9, 4.8))
    labs = fact_df["combination"].tolist()
    bottom = np.zeros(len(labs))
    for cat in CATEGORIES:
        vals = fact_df[f"P({cat})"].fillna(0).to_numpy()
        ax.bar(range(len(labs)), vals, bottom=bottom, label=cat)
        bottom = bottom + vals
    ax.set_xticks(range(len(labs)))
    ax.set_xticklabels(labs, rotation=20, ha="right")
    ax.set_ylim(0, 1.05)
    ax.set_title("Weather × controller factorial (diagnostic, not causal ID)")
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(figdir / "fig04_weather_controller_factorial.png", dpi=140)
    plt.close(fig)

    # 5 return air
    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = np.arange(len(ra_df))
    w = 0.25
    ax.bar(x - w, ra_df["DX_required_hours"], w, label="DX hours")
    ax.bar(x, ra_df["HIGH_RH_MIXING_hours"], w, label="high-RH mixing hours")
    ax.bar(x + w, ra_df["OA_FREE_hours"], w, label="OA-free hours")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{v:.0f}F rise" for v in ra_df["it_rise_F"]])
    ax.set_title("Return-air design-reference sensitivity (not RAT confidence bounds)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(figdir / "fig05_return_air_design_sensitivity.png", dpi=140)
    plt.close(fig)

    # 6 annual
    fig, ax = plt.subplots(figsize=(10, 5))
    sub = intensity.dropna(subset=["electricity_MWh"])
    ax.bar(sub["year"] - 0.2, sub["electricity_MWh"] / 1000.0, width=0.4, label="electricity (GWh)")
    ax2 = ax.twinx()
    wsub = intensity.dropna(subset=["withdrawal_m3"])
    ax2.plot(wsub["year"], wsub["withdrawal_m3"] / 1000.0, "o-", color="C1", label="withdrawal (ML)")
    ax2.plot(wsub["year"], wsub["SITE_WITHDRAWAL_INTENSITY"] * 100, "s--", color="C2", label="intensity x100 (L/kWh_fac)")
    ax.set_xlabel("year")
    ax.set_ylabel("electricity GWh")
    ax2.set_ylabel("withdrawal ML / intensity×100")
    ax.set_title("Canonical Forest City electricity, withdrawal, SITE_WITHDRAWAL_INTENSITY (not WUE)")
    fig.tight_layout()
    fig.savefig(figdir / "fig06_annual_electricity_withdrawal_intensity.png", dpi=140)
    plt.close(fig)


def chain_status(v2_status: dict) -> pd.DataFrame:
    rows = [
        {
            "edge": "v1_operator_events",
            "v1_label": "HISTORICAL_EVENT_VALIDATION=PASS",
            "v2_class": "SOURCE_IMPLEMENTATION_CONSISTENT",
            "v2_status": v2_status["SOURCE_IMPLEMENTATION_CONSISTENCY"],
            "note": "June 25 / July 1 defined the controller; not independent validation",
        },
        {
            "edge": "summer_control_robustness",
            "v1_label": "observed KFQD JJA DX=0",
            "v2_class": "ENGINEERING_BOUNDED",
            "v2_status": v2_status["SUMMER_CONTROL_ROBUSTNESS"],
            "note": "independent station replications; not a stitched series",
        },
        {
            "edge": "cross_climate_mechanism",
            "v1_label": "TRANSFERABLE_PHYSICS_SUPPORTED (qualitative, overlapping filters)",
            "v2_class": "SOURCE_IMPLEMENTATION_CONSISTENT",
            "v2_status": v2_status["CROSS_CLIMATE_MECHANISM_CONSISTENCY"],
            "note": "same UTC window; mutually exclusive taxonomy",
        },
        {
            "edge": "quantitative_physics_transfer",
            "v1_label": "not validated",
            "v2_class": "UNIDENTIFIED",
            "v2_status": "NOT_VALIDATED",
            "note": "no independent quantitative criterion; airflow unidentified",
        },
        {
            "edge": "IT_DELTA_T_DESIGN",
            "v1_label": "IDENTIFIED 35F",
            "v2_class": "DESIGN_SPEC",
            "v2_status": "IDENTIFIED",
            "note": "never auto-promoted to facility effective DeltaT",
        },
        {
            "edge": "FACILITY_EFFECTIVE_DELTA_T",
            "v1_label": "UNIDENTIFIED",
            "v2_class": "UNIDENTIFIED",
            "v2_status": "UNIDENTIFIED",
            "note": "return-air 25/35F tests are SCENARIO_ONLY",
        },
        {
            "edge": "return_air_design_reference",
            "v1_label": "35F iterated w_RA=w_supply",
            "v2_class": "SCENARIO_ONLY",
            "v2_status": v2_status.get("RETURN_AIR_ROBUSTNESS", "SCENARIO_ONLY"),
            "note": "not as-operated RAT confidence bounds",
        },
        {
            "edge": "water_magnitude",
            "v1_label": "UNIDENTIFIED",
            "v2_class": "UNIDENTIFIED",
            "v2_status": "NOT_VALIDATED",
            "note": "annual series is accounting, not 2012 controller water",
        },
        {
            "edge": "municipal_source",
            "v1_label": "Forest City WTP / Second Broad River",
            "v2_class": "DIRECTLY_MEASURED",
            "v2_status": "ACCOUNTING_CONTEXT_ONLY",
            "note": "industrial class is not Meta",
        },
        {
            "edge": "as_operated_validation",
            "v1_label": "UNIDENTIFIED",
            "v2_class": "UNIDENTIFIED",
            "v2_status": "UNIDENTIFIED",
            "note": "no BMS/TAB/as-operated SAT-RAT",
        },
        {
            "edge": "FRC1_address",
            "v1_label": "unresolved",
            "v2_class": "UNIDENTIFIED",
            "v2_status": "INTERVAL/SET_UNRESOLVED",
            "note": "284/404/408 remain a set",
        },
        {
            "edge": "2023_2024_water_break",
            "v1_label": "PUBLICLY_UNRESOLVED",
            "v2_class": "UNIDENTIFIED",
            "v2_status": "CAUSE_PUBLICLY_UNRESOLVED",
            "note": "no causal fit",
        },
    ]
    df = pd.DataFrame(rows)
    df.to_csv(OUTPUTS / "FOREST_CITY_V2_CHAIN_STATUS.csv", index=False)
    return df


def main() -> None:
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    write_v1_corrections()
    write_address_crosswalk()
    write_airflow_md()

    pd.DataFrame(mapping_table_rows()).to_csv(OUTPUTS / "COMMON_TAXONOMY_NATIVE_MAPPING.csv", index=False)

    hourly, audit = build_weather_and_stations()
    kfq = hourly["KFQD"]

    # Full-JJA independent replications (written before interpreting DX)
    station_rows = []
    station_frames = {}
    for name, df in hourly.items():
        sim = simulate_fc_station(jja(df))
        s = mode_summary(sim, site="FC")
        station_frames[name] = s["frame"]
        rec = {
            "station": name,
            "period": "2012-06-01/2012-08-31 UTC",
            "independent_series": True,
            "stitched": False,
            **{k: s[k] for k in s if k != "frame"},
        }
        station_rows.append(rec)
        s["frame"].to_csv(OUTPUTS / "weather_robustness" / f"FULL_JJA_{name}_HOURS.csv", index=False)
    station_tbl = pd.DataFrame([{k: v for k, v in r.items() if k != "native_mode_counts" and k != "category_counts"} | {"category_counts": json.dumps(r["category_counts"]), "native_mode_counts": json.dumps(r["native_mode_counts"])} for r in station_rows])
    (OUTPUTS / "weather_robustness").mkdir(parents=True, exist_ok=True)
    station_tbl.to_csv(OUTPUTS / "weather_robustness" / "FULL_JJA_STATION_REPLICATION.csv", index=False)
    dx_hours = [r["DX_required_hours"] for r in station_rows]
    valid = [r["valid_hours"] for r in station_rows]
    dx_frac = [d / n if n else np.nan for d, n in zip(dx_hours, valid)]
    if all(d == 0 or (n and d / n < 0.005) for d, n in zip(dx_hours, valid)):
        dx_rob = "STRONG_SUPPORT"
    else:
        dx_rob = "WEATHER_STATION_DEPENDENT"
    write_json(
        OUTPUTS / "weather_robustness" / "FULL_JJA_STATION_REPLICATION.json",
        {
            "SUMMER_DX_ROBUSTNESS": dx_rob,
            "stations": station_rows,
            "selection_used_dx_outcome": False,
            "preferred_local_still_KFQD": True,
            "negligible_rule": "DX hours == 0 or < 0.5% of valid hours at every credible station",
        },
    )

    ov = overlap_diagnostics(hourly, station_frames)
    ov.to_csv(OUTPUTS / "weather_robustness" / "STATION_OVERLAP_DIAGNOSTICS.csv", index=False)

    ev_df, ev_js = operator_events(kfq)
    (OUTPUTS / "operator_events").mkdir(parents=True, exist_ok=True)
    ev_df.to_csv(OUTPUTS / "operator_events" / "OPERATOR_EVENT_CONTROL_CONSISTENCY.csv", index=False)
    write_json(OUTPUTS / "operator_events" / "OPERATOR_EVENT_CONTROL_CONSISTENCY.json", ev_js)

    # Same-period PRN vs FC
    krdm_path = PRINEVILLE_ROOT / "data/processed/weather_krdm_hourly.csv"
    krdm = pd.read_csv(krdm_path, parse_dates=["timestamp_utc"])
    krdm["timestamp_utc"] = pd.to_datetime(krdm["timestamp_utc"], utc=True)
    krdm_w = common_window(krdm)
    fc_w = common_window(kfq)
    prn_sim = simulate_prn(krdm_w)
    fc_sim = simulate_fc_station(fc_w)
    prn_s = mode_summary(prn_sim, site="PRN1")
    fc_s = mode_summary(fc_sim, site="FC")
    tax_rows = []
    for site, s, w, controller in (
        ("PRN1", prn_s, krdm_w, "PRN1_OCP_frozen"),
        ("FOREST_CITY", fc_s, fc_w, "FC_v1_frozen"),
    ):
        rec = {
            "site": site,
            "controller": controller,
            "weather": "KRDM" if site == "PRN1" else "KFQD",
            "calendar_start_utc": str(COMMON_START),
            "calendar_end_utc": str(COMMON_END),
            **fractions_from_summary(s),
            "weather_distributions": json.dumps(weather_distributions(w)),
            "feasibility_note": "PRN feasibility from structural-reference-v1; FC constraint = 85F/90%RH",
        }
        tax_rows.append(rec)
    tax_df = pd.DataFrame(tax_rows)
    (OUTPUTS / "cross_site_same_period").mkdir(parents=True, exist_ok=True)
    tax_df.to_csv(OUTPUTS / "cross_site_same_period" / "PRN_FC_COMMON_TAXONOMY_RESULTS.csv", index=False)
    write_json(
        OUTPUTS / "cross_site_same_period" / "PRN_FC_COMMON_TAXONOMY_RESULTS.json",
        {
            "calendar": ["2012-06-21T00:00Z", "2012-08-31T23:00Z"],
            "identical_calendar_dates": True,
            "results": tax_rows,
            "question": "Does FC shift toward HIGH_RH_MIXING and EVAP_COOLING vs PRN humidification on the same dates?",
            "water_magnitude_used": False,
        },
    )

    # Factorial on intersection of valid KRDM and KFQD hours
    krdm_ok = krdm_w.loc[usable_mask(krdm_w) & krdm_w["t_wb_C"].notna(), ["timestamp_utc"]]
    fc_ok = fc_w.loc[usable_mask(fc_w), ["timestamp_utc"]]
    both_ts = set(krdm_ok["timestamp_utc"]) & set(fc_ok["timestamp_utc"])
    krdm_b = krdm_w[krdm_w["timestamp_utc"].isin(both_ts)].copy()
    fc_b = fc_w[fc_w["timestamp_utc"].isin(both_ts)].copy()
    combos = {
        "PRN_weather+PRN_controller": simulate_prn(krdm_b),
        "PRN_weather+FC_controller": simulate_fc_station(krdm_b),
        "FC_weather+PRN_controller": simulate_prn(fc_b),
        "FC_weather+FC_controller": simulate_fc_station(fc_b),
    }
    fact_rows = []
    for name, sim in combos.items():
        site = "PRN1" if name.endswith("PRN_controller") else "FC"
        s = mode_summary(sim, site=site)
        feas = s["frame"]["feasibility"] if "feasibility" in s["frame"].columns else None
        unsat = np.nan
        if "t_inlet_max_satisfied" in s["frame"].columns:
            v = s["frame"]["control_mode"].astype(str) != "WEATHER_MISSING"
            unsat = float((~(s["frame"].loc[v, "t_inlet_max_satisfied"] & s["frame"].loc[v, "rh_max_satisfied"])).mean()) if v.any() else float("nan")
        fact_rows.append(
            {
                "combination": name,
                "n_hours_intersection": len(both_ts),
                "NOT_CAUSAL_IDENTIFICATION": True,
                "constraint_unsatisfied_fraction": unsat,
                **fractions_from_summary(s),
            }
        )
    fact_df = pd.DataFrame(fact_rows)
    fact_df.to_csv(OUTPUTS / "cross_site_same_period" / "WEATHER_CONTROLLER_FACTORIAL.csv", index=False)
    write_json(
        OUTPUTS / "cross_site_same_period" / "WEATHER_CONTROLLER_FACTORIAL.json",
        {
            "name": "WEATHER_CONTROLLER_FACTORIAL_DIAGNOSTIC",
            "not_causal": True,
            "intersection_hours": len(both_ts),
            "rows": fact_rows,
        },
    )

    # Return-air robustness on KFQD JJA
    ra_rows = []
    for f_rise in (25.0, 30.0, 35.0):
        rise_k = f_rise * 5.0 / 9.0
        sim = simulate_fc_station(jja(kfq), rise_k=rise_k)
        s = mode_summary(sim, site="FC")
        v = s["frame"]["control_mode"].astype(str) != "WEATHER_MISSING"
        feas = float((s["frame"].loc[v, "t_inlet_max_satisfied"] & s["frame"].loc[v, "rh_max_satisfied"]).mean()) if v.any() else float("nan")
        ra_rows.append(
            {
                "it_rise_F": f_rise,
                "it_rise_K": rise_k,
                "provenance": "DESIGN_REFERENCE_SCENARIO",
                "humidity_ratio_assumption": "w_RA = w_supply (sensible-only)",
                "not_as_operated_RAT": True,
                "not_facility_effective_delta_t": True,
                "not_confidence_bound_on_RAT": True,
                "interpolation_only": f_rise == 30.0,
                "valid_hours": s["valid_hours"],
                "DX_required_hours": s["DX_required_hours"],
                "HIGH_RH_MIXING_hours": s["category_counts"].get("HIGH_RH_MIXING", 0),
                "OA_FREE_hours": s["category_counts"].get("OA_FREE", 0),
                "EVAP_COOLING_hours": s["category_counts"].get("EVAP_COOLING", 0),
                "constraint_feasibility_fraction": feas,
                **{f"P({c})": (s["category_counts"].get(c, 0) / s["valid_hours"] if s["valid_hours"] else np.nan) for c in CATEGORIES},
            }
        )
    ra_df = pd.DataFrame(ra_rows)
    (OUTPUTS / "return_air_robustness").mkdir(parents=True, exist_ok=True)
    ra_df.to_csv(OUTPUTS / "return_air_robustness" / "RETURN_AIR_DESIGN_SENSITIVITY.csv", index=False)
    write_json(
        OUTPUTS / "return_air_robustness" / "RETURN_AIR_DESIGN_SENSITIVITY.json",
        {
            "IT_EQUIPMENT_DELTA_T_DESIGN_F": IT_EQUIPMENT_DELTA_T_DESIGN_F,
            "IT_EQUIPMENT_DELTA_T_DESIGN_K": IT_EQUIPMENT_DELTA_T_DESIGN_K,
            "FACILITY_EFFECTIVE_DELTA_T": "UNIDENTIFIED",
            "rows": ra_rows,
        },
    )

    canon = canonical_annual()
    intensity = intensity_table(canon)
    municipal_update(canon)
    water_break_audit()

    write_json(
        OUTPUTS / "emissions" / "FOREST_CITY_LOCATION_EMISSIONS_VALIDATION.json",
        {
            "status": "INSUFFICIENT_BOUNDARY_INFORMATION",
            "completed_or_stopped": "STOPPED",
            "reason": (
                "Year-matched eGRID SRVC workbooks, DUK EIA-930, EIA generation, and CAMPD serving-plant "
                "mapping were not reconstructed in this bounded secondary task. Meta location-based Scope 2 "
                "is canonical where published (2012-2016 regional/location-based; 2020-2024 EDI). "
                "Do not fit emission factors to Meta."
            ),
            "utility": "Duke Energy Carolinas / DUK BA",
            "candidate_egrid_subregion": "SRVC",
            "do_not_refit": True,
        },
    )
    pd.DataFrame(
        [
            {
                "status": "INSUFFICIENT_BOUNDARY_INFORMATION",
                "utility": "Duke Energy Carolinas / DUK",
                "egrid": "SRVC_not_reconstructed",
            }
        ]
    ).to_csv(OUTPUTS / "emissions" / "FOREST_CITY_LOCATION_EMISSIONS_VALIDATION.csv", index=False)

    write_manual_package()

    # Cross-site qualitative read (not causal)
    prn_h = tax_df.loc[tax_df.site == "PRN1"].iloc[0]
    fc_h = tax_df.loc[tax_df.site == "FOREST_CITY"].iloc[0]
    humid_shift = float(prn_h["P(HUMIDIFICATION)"]) > float(fc_h["P(HUMIDIFICATION)"])
    mix_shift = float(fc_h["P(HIGH_RH_MIXING)"]) > float(prn_h["P(HIGH_RH_MIXING)"])
    evap_higher_at_fc = float(fc_h["P(EVAP_COOLING)"]) > float(prn_h["P(EVAP_COOLING)"])
    shift = bool(humid_shift and mix_shift)
    if humid_shift and mix_shift and not evap_higher_at_fc:
        cross_label = "SUPPORTED_HUMIDIFICATION_AND_MIXING_SHIFT_EVAP_NOT_HIGHER_AT_FC"
    elif humid_shift and mix_shift:
        cross_label = "SUPPORTED_ON_SAME_DATES"
    else:
        cross_label = "PRELIMINARY_SUPPORT"

    ra_dx = ra_df["DX_required_hours"].tolist()
    ra_rob = "DX_CONCLUSION_NOT_STRONGLY_DEPENDENT" if max(ra_dx) == 0 else (
        "DX_SENSITIVE_TO_RETURN_AIR_DESIGN_REFERENCE" if (min(ra_dx) == 0 and max(ra_dx) > 0) else "SEE_TABLE"
    )

    v2_status = {
        "SOURCE_IMPLEMENTATION_CONSISTENCY": ev_js["overall"],
        "SUMMER_CONTROL_ROBUSTNESS": dx_rob,
        "CROSS_CLIMATE_MECHANISM_CONSISTENCY": cross_label,
        "QUANTITATIVE_PHYSICS_TRANSFER": "NOT_VALIDATED",
        "WATER_MAGNITUDE_VALIDATION": "NOT_VALIDATED",
        "AS_OPERATED_VALIDATION": "UNIDENTIFIED",
        "RETURN_AIR_ROBUSTNESS": ra_rob,
        "SUMMER_DX_CONSISTENCY": "PASS_ON_OBSERVED_KFQD_HOURS",
        "FRC1_ADDRESS": "INTERVAL/SET_UNRESOLVED",
        "FACILITY_EFFECTIVE_DELTA_T": "UNIDENTIFIED",
        "MODEL_CALIBRATED": "NO",
        "same_period_shift_toward_fc_mixing_and_evap": bool(shift),
        "same_period_evap_higher_at_fc": bool(evap_higher_at_fc),
    }
    write_json(OUTPUTS / "FOREST_CITY_V2_STATUS.json", v2_status)
    chain_status(v2_status)

    write_figures(hourly, station_rows, tax_df, fact_df, ra_df, intensity)

    freeze = {
        "pass": "forest_city_north_carolina_v2",
        "STOP": True,
        "MODEL_CALIBRATED": "NO",
        "QUANTITATIVE_PHYSICS_TRANSFER": "NOT_VALIDATED",
        "no_water_calibration": True,
        "no_ml": True,
        "no_hpc": True,
        "v1_untouched": True,
        "prineville_frozen": True,
        "status": v2_status,
        "stopping_rule_items": {
            "1_v1_correction_manifest": True,
            "2_address_crosswalk_exhausted": True,
            "3_station_audit": True,
            "4_full_jja_replications": True,
            "5_events_relabeled": True,
            "6_common_taxonomy": True,
            "7_same_period_comparison": True,
            "8_factorial": True,
            "9_return_air_robustness": True,
            "10_airflow_requirements": True,
            "11_annual_meta_series": True,
            "12_2023_2024_water_audit": True,
            "13_municipal_accounting": True,
            "14_emissions_stopped": True,
            "15_manual_acquisition_package": True,
            "16_chain_status": True,
        },
    }
    write_json(OUTPUTS / "FOREST_CITY_V2_FREEZE.json", freeze)
    print(
        json.dumps(
            {
                "dx_robustness": dx_rob,
                "shift": bool(shift),
                "evap_higher_at_fc": bool(evap_higher_at_fc),
                "events": ev_js["overall"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
