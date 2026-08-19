"""Download and organize USGS NWAA HUC12 water series.

Preserves existing verified IWA and pscutot per-HUC12 files. Retrieves missing
public-supply withdrawal and irrigation series from the USGS NWAA API using
HUC8 (and one extra HUC12 outside the site HUC8) queries, then writes
per-HUC12 extracts without changing source values.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from usgs_nwaa_config import (
    API_BASE,
    CANONICAL_USGS,
    DOWNLOAD_SERIES,
    HUC10_GEOJSON,
    LEGACY_ROOT,
    NETWORK,
    PRIMARY_SCOPES,
    PROVENANCE,
    QC_DIR,
    RAW_AGGREGATES,
    RAW_HUC12,
    RAW_NWAA,
    SCOPES,
    SERIES,
    SITE_GEOJSON,
    SITE_HUC12,
    SITE_HUC8,
    STUDY_HUCS,
    STUDY_HUCS_ROOT,
    THERMO_SCREEN,
    TOUCHING_GEOJSON,
    aggregate_file,
    huc12_raw_dir,
    huc12_raw_file,
    pad_huc12,
)

SLEEP_S = 0.25
TIMEOUT = 300


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


def load_study_hucs() -> pd.DataFrame:
    src = STUDY_HUCS if STUDY_HUCS.exists() else STUDY_HUCS_ROOT
    geo = pd.read_csv(src, dtype=str)
    geo["huc12"] = geo["huc12"].map(pad_huc12)
    for col in (
        "is_site",
        "is_touching_site",
        "same_site_huc10",
        "same_site_huc8",
        "scope_local",
        "scope_hydro_near",
        "network_depth",
    ):
        if col in geo.columns:
            geo[col] = pd.to_numeric(geo[col], errors="coerce")
    geo["areasqkm"] = pd.to_numeric(geo["areasqkm"], errors="coerce")
    return geo


def organize_geography(geo: pd.DataFrame) -> None:
    CANONICAL_USGS.mkdir(parents=True, exist_ok=True)
    copies = [
        (STUDY_HUCS_ROOT, STUDY_HUCS),
        (LEGACY_ROOT / "meta_huc12_hydrologic_network.csv", NETWORK),
        (LEGACY_ROOT / "meta_site_huc12.geojson", SITE_GEOJSON),
        (LEGACY_ROOT / "touching_huc12s.geojson", TOUCHING_GEOJSON),
        (LEGACY_ROOT / "huc12s_in_parent_huc10.geojson", HUC10_GEOJSON),
        (LEGACY_ROOT / "touching_huc12s.csv", CANONICAL_USGS / "touching_huc12s.csv"),
    ]
    for src, dest in copies:
        if src.exists() and src.resolve() != dest.resolve():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
    if not STUDY_HUCS.exists():
        shutil.copy2(STUDY_HUCS_ROOT, STUDY_HUCS)


def organize_existing_aggregates() -> None:
    RAW_AGGREGATES.mkdir(parents=True, exist_ok=True)
    for src in RAW_NWAA.glob("*.csv"):
        dest = RAW_AGGREGATES / src.name
        if dest.exists():
            continue
        shutil.move(str(src), str(dest))


def copy_existing_per_huc12(geo: pd.DataFrame) -> list[dict]:
    """Copy verified IWA/pscutot downloads into the organized raw tree."""
    log = []
    mapping = [
        (
            LEGACY_ROOT / "usgs_nwaa" / "hydrology",
            SERIES["iwa_all"].model,
            SERIES["iwa_all"].variable,
            "hydrology",
        ),
        (
            LEGACY_ROOT / "usgs_nwaa" / "pscutot",
            SERIES["pscutot"].model,
            SERIES["pscutot"].variable,
            "pscutot",
        ),
    ]
    for src_root, model, variable, prefix in mapping:
        for scope in SCOPES:
            src_dir = src_root / scope
            dest_dir = huc12_raw_dir(model, variable, scope)
            dest_dir.mkdir(parents=True, exist_ok=True)
            wanted = geo.loc[geo[scope].astype(int) == 1, "huc12"]
            for huc in wanted:
                src = src_dir / f"{prefix}_{huc}.csv"
                dest = dest_dir / f"{prefix}_{huc}.csv"
                status = "missing_source"
                if src.exists() and src.stat().st_size > 50:
                    if not dest.exists():
                        shutil.copy2(src, dest)
                        status = "copied"
                    else:
                        status = "exists"
                log.append(
                    {
                        "action": "copy_existing_huc12",
                        "model": model,
                        "variable": variable,
                        "scope": scope,
                        "huc12_id": huc,
                        "status": status,
                        "src": str(src),
                        "dest": str(dest),
                    }
                )
                if status == "copied":
                    append_jsonl(
                        PROVENANCE,
                        {
                            "retrieval_utc": None,
                            "note": (
                                "Pre-existing verified per-HUC12 API CSV; "
                                "file contents not modified."
                            ),
                            "model": model,
                            "variable": variable,
                            "location": f"huc12:{huc}",
                            "startdate": SERIES["iwa_all"].startdate
                            if variable == "all"
                            else SERIES["pscutot"].startdate,
                            "enddate": SERIES["iwa_all"].enddate
                            if variable == "all"
                            else SERIES["pscutot"].enddate,
                            "timeres": "monthly",
                            "format": "csv",
                            "units": SERIES["iwa_all"].units
                            if variable == "all"
                            else SERIES["pscutot"].units,
                            "outfile": str(dest),
                            "copied_from": str(src),
                            "status": status,
                        },
                    )
    return log


def _read_nwaa_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    if "huc12_id" not in df.columns:
        raise ValueError(f"{path} missing huc12_id")
    df["huc12_id"] = df["huc12_id"].map(pad_huc12)
    return df


def split_aggregate_to_huc12(
    spec,
    location_label: str,
    geo: pd.DataFrame,
) -> list[dict]:
    src = aggregate_file(spec.model, spec.variable, location_label)
    log = []
    if not src.exists():
        log.append(
            {
                "action": "split_aggregate",
                "model": spec.model,
                "variable": spec.variable,
                "location_label": location_label,
                "status": "missing_aggregate",
                "src": str(src),
            }
        )
        return log
    df = _read_nwaa_csv(src)
    for scope in SCOPES:
        wanted = set(geo.loc[geo[scope].astype(int) == 1, "huc12"])
        dest_dir = huc12_raw_dir(spec.model, spec.variable, scope)
        dest_dir.mkdir(parents=True, exist_ok=True)
        present = set(df["huc12_id"].unique())
        for huc in sorted(wanted):
            dest = huc12_raw_file(spec.model, spec.variable, scope, huc)
            if dest.exists() and dest.stat().st_size > 50:
                status = "exists"
            elif huc not in present:
                status = "huc_not_in_aggregate"
            else:
                part = df.loc[df["huc12_id"] == huc].copy()
                part.to_csv(dest, index=False)
                status = "split"
            log.append(
                {
                    "action": "split_aggregate",
                    "model": spec.model,
                    "variable": spec.variable,
                    "scope": scope,
                    "huc12_id": huc,
                    "status": status,
                    "src": str(src),
                    "dest": str(dest),
                }
            )
    return log


def api_get(params: dict) -> requests.Response:
    return requests.get(API_BASE, params=params, timeout=TIMEOUT)


def download_location(spec, location: str, outfile: Path, log: list[dict]) -> bool:
    if outfile.exists() and outfile.stat().st_size > 50:
        log.append(
            {
                "action": "download",
                "model": spec.model,
                "variable": spec.variable,
                "location": location,
                "status": "exists",
                "outfile": str(outfile),
            }
        )
        return True
    params = {
        "model": spec.model,
        "variable": spec.variable,
        "location": location,
        "startdate": spec.startdate,
        "enddate": spec.enddate,
        "timeres": "monthly",
        "format": "csv",
    }
    outfile.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = api_get(params)
        record = {
            "retrieval_utc": utc_now(),
            "model": spec.model,
            "variable": spec.variable,
            "location": location,
            "startdate": spec.startdate,
            "enddate": spec.enddate,
            "timeres": "monthly",
            "format": "csv",
            "units": spec.units,
            "url": r.url,
            "http_status": r.status_code,
            "outfile": str(outfile),
            "available_period": f"{spec.startdate}/{spec.enddate}",
        }
        if not r.ok:
            record["status"] = "http_error"
            record["response_preview"] = r.text[:1000]
            append_jsonl(PROVENANCE, record)
            log.append({**record, "action": "download"})
            return False
        outfile.write_bytes(r.content)
        record["status"] = "downloaded"
        record["bytes"] = len(r.content)
        append_jsonl(PROVENANCE, record)
        log.append({**record, "action": "download"})
        return True
    except Exception as exc:
        record = {
            "action": "download",
            "retrieval_utc": utc_now(),
            "model": spec.model,
            "variable": spec.variable,
            "location": location,
            "status": "exception",
            "error": repr(exc),
            "outfile": str(outfile),
        }
        append_jsonl(PROVENANCE, record)
        log.append(record)
        return False
    finally:
        time.sleep(SLEEP_S)


def download_missing_series(geo: pd.DataFrame) -> list[dict]:
    log = []
    extra_hucs = sorted(
        set(geo.loc[geo["same_site_huc8"].astype(int) != 1, "huc12"])
    )
    for spec in DOWNLOAD_SERIES:
        huc8_path = aggregate_file(spec.model, spec.variable, f"huc8-{SITE_HUC8}")
        ok = download_location(spec, f"huc8:{SITE_HUC8}", huc8_path, log)
        if ok:
            log.extend(split_aggregate_to_huc12(spec, f"huc8-{SITE_HUC8}", geo))
        for huc in extra_hucs:
            loc_label = f"huc12-{huc}"
            agg = aggregate_file(spec.model, spec.variable, loc_label)
            ok_huc = download_location(spec, f"huc12:{huc}", agg, log)
            if not ok_huc:
                continue
            df = _read_nwaa_csv(agg)
            df["huc12_id"] = df["huc12_id"].map(pad_huc12)
            for scope in SCOPES:
                if int(geo.loc[geo["huc12"] == huc, scope].iloc[0]) != 1:
                    continue
                dest = huc12_raw_file(spec.model, spec.variable, scope, huc)
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists() and dest.stat().st_size > 50:
                    status = "exists"
                else:
                    df.to_csv(dest, index=False)
                    status = "copied_extra_huc12"
                log.append(
                    {
                        "action": "extra_huc12",
                        "model": spec.model,
                        "variable": spec.variable,
                        "scope": scope,
                        "huc12_id": huc,
                        "status": status,
                        "outfile": str(dest),
                    }
                )
    return log


def screen_thermoelectric(geo: pd.DataFrame) -> dict:
    outfile = aggregate_file(
        THERMO_SCREEN.model, THERMO_SCREEN.variable, f"huc8-{SITE_HUC8}"
    )
    log = []
    ok = download_location(
        THERMO_SCREEN, f"huc8:{SITE_HUC8}", outfile, log
    )
    QC_DIR.mkdir(parents=True, exist_ok=True)
    summary = {
        "model": THERMO_SCREEN.model,
        "variable": THERMO_SCREEN.variable,
        "location": f"huc8:{SITE_HUC8}",
        "period": f"{THERMO_SCREEN.startdate}/{THERMO_SCREEN.enddate}",
        "download_ok": ok,
        "raw_file": str(outfile),
        "n_huc12": None,
        "max_tewdftot_mgd": None,
        "sum_tewdftot_mgd": None,
        "relevant_facilities_in_study_huc8": False,
        "added_to_panels": False,
        "note": (
            "Screening only. Thermoelectric series are not added to HUC12 "
            "panels unless modeled withdrawals are non-zero in the study HUC8."
        ),
    }
    if ok:
        df = _read_nwaa_csv(outfile)
        value_col = THERMO_SCREEN.native_column
        df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
        summary["n_huc12"] = int(df["huc12_id"].nunique())
        summary["max_tewdftot_mgd"] = float(df[value_col].max())
        summary["sum_tewdftot_mgd"] = float(df[value_col].sum())
        summary["relevant_facilities_in_study_huc8"] = bool(
            df[value_col].fillna(0).abs().max() > 0
        )
        huc8_ids = set(geo.loc[geo["same_site_huc8"].astype(int) == 1, "huc12"])
        missing = sorted(huc8_ids - set(df["huc12_id"]))
        extra = sorted(set(df["huc12_id"]) - huc8_ids)
        summary["missing_study_huc12s"] = ";".join(missing)
        summary["extra_huc12s"] = ";".join(extra)
    pd.DataFrame([summary]).to_csv(
        QC_DIR / "usgs_thermoelectric_screen.csv", index=False
    )
    return summary


def main() -> None:
    RAW_HUC12.mkdir(parents=True, exist_ok=True)
    RAW_AGGREGATES.mkdir(parents=True, exist_ok=True)
    QC_DIR.mkdir(parents=True, exist_ok=True)

    geo = load_study_hucs()
    organize_geography(geo)
    organize_existing_aggregates()

    log_rows = []
    log_rows.extend(copy_existing_per_huc12(geo))
    for spec in (SERIES["pswdtot"], SERIES["pswdgw"], SERIES["pswdsw"]):
        log_rows.extend(
            split_aggregate_to_huc12(spec, f"huc8-{SITE_HUC8}", geo)
        )
    log_rows.extend(download_missing_series(geo))
    thermo = screen_thermoelectric(geo)

    log_df = pd.DataFrame(log_rows)
    log_path = QC_DIR / "usgs_nwaa_download_log.csv"
    log_df.to_csv(log_path, index=False)

    print("Study HUC12s:", len(geo))
    print("Primary scopes:", PRIMARY_SCOPES)
    print("Download/organize log:", log_path)
    if not log_df.empty and "status" in log_df.columns:
        print(log_df["status"].value_counts().to_string())
    print("Thermoelectric relevant:", thermo["relevant_facilities_in_study_huc8"])
    print("Thermoelectric max mgd:", thermo["max_tewdftot_mgd"])


if __name__ == "__main__":
    main()
