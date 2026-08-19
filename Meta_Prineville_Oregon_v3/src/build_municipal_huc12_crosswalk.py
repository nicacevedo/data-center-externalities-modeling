"""Assign Prineville municipal water sources to HUC12s using official coordinates.

Does not infer locations from TRSQQ or narrative bearings. Sources without
official latitude/longitude remain unresolved. The Meta campus footprint is
not verified beyond the existing site-point HUC12 designation.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from usgs_nwaa_config import (
    CITY_SOURCES,
    MUNICIPAL_CROSSWALK,
    OWRD_CROSSWALK,
    OWRD_WELL_DETAILS,
    QC_DIR,
    SITE_HUC12,
    SITE_HUC12_DESIGNATION,
    SITE_HUC12_NAME,
    SITE_HUC12_NOTE,
    STUDY_HUCS,
    WBD_HUC12_URL,
    pad_huc12,
)

LAT_RE = re.compile(
    r'id="lb_latitude_dec"[^>]*>\s*([+-]?\d+(?:\.\d+)?)', re.I
)
LON_RE = re.compile(
    r'id="lb_longitude_dec"[^>]*>\s*([+-]?\d+(?:\.\d+)?)', re.I
)


def fetch_owrd_well_coords(wl_id: str) -> tuple[float | None, float | None, str]:
    if not wl_id or str(wl_id).lower() in {"nan", "none"}:
        return None, None, "no_wl_id"
    url = f"{OWRD_WELL_DETAILS}?wl_id={wl_id}"
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
    except Exception as exc:
        return None, None, f"owrd_well_log_fetch_failed:{exc!r}"
    lat_m = LAT_RE.search(r.text)
    lon_m = LON_RE.search(r.text)
    if not lat_m or not lon_m:
        return None, None, "owrd_well_log_page_missing_decimal_degrees"
    return float(lat_m.group(1)), float(lon_m.group(1)), "owrd_well_log_decimal_degrees"


def wbd_huc12(lat: float, lon: float) -> tuple[str, str, str]:
    params = {
        "f": "json",
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "huc12,name",
        "returnGeometry": "false",
    }
    r = requests.get(WBD_HUC12_URL, params=params, timeout=120)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    feats = data.get("features") or []
    if not feats:
        return "", "", "wbd_no_intersect"
    attrs = feats[0]["attributes"]
    return pad_huc12(attrs.get("huc12")), str(attrs.get("name") or ""), "wbd_point_in_polygon"


def load_sources() -> pd.DataFrame:
    city = pd.read_csv(CITY_SOURCES, dtype=str)
    owrd = pd.read_csv(OWRD_CROSSWALK, dtype=str)
    out = city.merge(
        owrd,
        how="left",
        left_on="oha_facility_id",
        right_on="oha_facility_id",
        suffixes=("", "_owrd"),
    )
    return out


def pick_coords(row: pd.Series) -> tuple[float | None, float | None, str, str]:
    inv_lat = row.get("current_well_latitude_if_known")
    inv_lon = row.get("current_well_longitude_if_known")
    if pd.notna(inv_lat) and pd.notna(inv_lon) and str(inv_lat).strip() and str(inv_lon).strip():
        return (
            float(inv_lat),
            float(inv_lon),
            "inventory_current_well_coordinates",
            "official_decimal_degrees_in_owrd_crosswalk",
        )
    wl_id = str(row.get("owrd_wl_id_known") or "").strip()
    lat, lon, method = fetch_owrd_well_coords(wl_id)
    time.sleep(0.25)
    if lat is None or lon is None:
        return None, None, "unresolved_missing_coordinates", method
    return lat, lon, method, f"owrd_wl_id={wl_id}"


def write_site_designation() -> None:
    SITE_HUC12_NOTE.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "designation": SITE_HUC12_DESIGNATION,
                "huc12_id": SITE_HUC12,
                "huc12_name": SITE_HUC12_NAME,
                "campus_footprint_verified": False,
                "note": (
                    "Existing verified site HUC12 is the Watershed Boundary Dataset "
                    "HUC12 containing the previously identified Meta Prineville site "
                    "point. No campus-building polygon is present in this repository, "
                    f"so full-footprint containment in {SITE_HUC12} remains outstanding. "
                    "The HUC12 containing the Meta buildings is not necessarily the "
                    "HUC12 from which Prineville withdraws water that serves Meta."
                ),
            }
        ]
    ).to_csv(SITE_HUC12_NOTE, index=False)


def main() -> None:
    geo = pd.read_csv(STUDY_HUCS, dtype=str)
    geo["huc12"] = geo["huc12"].map(pad_huc12)
    study_ids = set(geo["huc12"])
    study_names = dict(zip(geo["huc12"], geo["name"]))

    sources = load_sources()
    rows = []
    for _, src in sources.iterrows():
        lat, lon, match_method, match_detail = pick_coords(src)
        huc12_id = ""
        huc12_name = ""
        confidence = "unresolved"
        in_study = False
        if lat is not None and lon is not None:
            huc12_id, huc12_name, wbd_method = wbd_huc12(lat, lon)
            time.sleep(0.2)
            if huc12_id:
                match_method = f"{match_method}+{wbd_method}"
                in_study = huc12_id in study_ids
                if in_study:
                    confidence = "coordinate_wbd_intersect"
                    if not huc12_name:
                        huc12_name = study_names.get(huc12_id, "")
                else:
                    confidence = "out_of_study_geography"
                    match_detail = (
                        f"{match_detail}; WBD HUC12 {huc12_id} is outside the "
                        "Prineville study HUC12 set. Official well-log coordinates "
                        "were not replaced. Possible wl_id mismatch; do not infer "
                        "a Crooked River location."
                    )
            else:
                match_method = f"{match_method}+{wbd_method}"
                confidence = "coordinates_found_huc12_unresolved"
        rows.append(
            {
                "water_system": "City of Prineville PWS 00682",
                "source_id": src.get("oha_facility_id"),
                "well_id": src.get("well_log") or src.get("canonical_well_log"),
                "source_name": src.get("source_name") or src.get("canonical_source_name"),
                "source_type": src.get("water_type"),
                "source_group": src.get("source_group"),
                "status": src.get("status"),
                "latitude": lat,
                "longitude": lon,
                "huc12_id": huc12_id,
                "huc12_name": huc12_name,
                "water_right_or_pod_id": src.get("accepted_owrd_report_ids"),
                "owrd_wl_id_known": src.get("owrd_wl_id_known"),
                "confidence": confidence,
                "match_method": match_method,
                "match_detail": match_detail,
                "accepted_location": src.get("accepted_location"),
                "accepted_trsqq": src.get("accepted_trsqq"),
                "current_well_trsqq_if_known": src.get("current_well_trsqq_if_known"),
                "in_study_geography": in_study,
                "unresolved_reason": (
                    ""
                    if huc12_id and in_study
                    else (
                        "WBD-assigned HUC12 is outside the Prineville study set; "
                        "coordinates were not inferred or replaced."
                        if huc12_id
                        else (
                            "No official latitude/longitude available in the municipal "
                            "inventory or OWRD well-log details page; TRSQQ/bearing text "
                            "was not converted to a point."
                        )
                    )
                ),
            }
        )
    out = pd.DataFrame(rows)
    MUNICIPAL_CROSSWALK.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(MUNICIPAL_CROSSWALK, index=False)
    write_site_designation()

    QC_DIR.mkdir(parents=True, exist_ok=True)
    summary = pd.DataFrame(
        [
            {
                "n_sources": len(out),
                "n_assigned_in_study_huc12": int(
                    ((out["huc12_id"].fillna("") != "") & out["in_study_geography"]).sum()
                ),
                "n_out_of_study_huc12": int(
                    ((out["huc12_id"].fillna("") != "") & ~out["in_study_geography"]).sum()
                ),
                "n_unresolved_missing_coordinates": int(
                    (out["huc12_id"].fillna("") == "").sum()
                ),
                "n_in_site_huc12": int((out["huc12_id"] == SITE_HUC12).sum()),
                "assigned_in_study_huc12_ids": ";".join(
                    sorted(
                        {
                            h
                            for h, ok in zip(out["huc12_id"].fillna(""), out["in_study_geography"])
                            if h and ok
                        }
                    )
                ),
                "site_huc12_id": SITE_HUC12,
                "site_designation": SITE_HUC12_DESIGNATION,
                "campus_footprint_verified": False,
            }
        ]
    )
    summary.to_csv(QC_DIR / "municipal_source_huc12_crosswalk_qa.csv", index=False)
    print("Wrote", MUNICIPAL_CROSSWALK)
    print(summary.to_string(index=False))
    print(out[["source_id", "source_name", "huc12_id", "confidence"]].to_string(index=False))


if __name__ == "__main__":
    main()
