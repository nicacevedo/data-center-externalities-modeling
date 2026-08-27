#!/usr/bin/env python3
"""Phase 3: acquire/freeze EnergyPlus TMY3 EPW files for selected climate zones only."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

from followup_common import FOLLOWUP_MANIFESTS

import pandas as pd

from common import atomic_write_json, set_threads, sha256_file, utcnow
from followup_common import CLIMATE_CITIES, FOLLOWUP, SELECTED_CELLS, SMOKE_CELL, UE_CLIMATE_ZONES, WEATHER_DIR

NEEDED_ZONES = sorted({SMOKE_CELL["climate_zone"], *(c["climate_zone"] for c in SELECTED_CELLS)})


def epw_urls(meta: dict):
    st = meta["state"]
    eid = meta["epw_id"]
    return [
        f"https://energyplus-weather.s3.amazonaws.com/north_america_wmo_region_4/USA/{st}/{eid}/{eid}.zip",
        f"https://climate.onebuilding.org/WMO_Region_4_North_and_Central_America/USA_United_States_of_America/{st}/{eid}.zip",
        f"https://climate.onebuilding.org/WMO_Region_4_North_and_Central_America/USA_United_States_of_America/{_OB_STATE.get(st, st)}/{eid}.zip",
        f"https://raw.githubusercontent.com/NREL/EnergyPlus/develop/weather/{eid}.epw",
        f"https://www.energycodes.gov/sites/default/files/2022-09/{eid.replace('OHare', 'OHare').replace('.Intl.AP.', '.Intl_.AP_.')}.epw",
    ]


_OB_STATE = {
    "FL": "FL_Florida",
    "TX": "TX_Texas",
    "IL": "IL_Illinois",
    "AK": "AK_Alaska",
    "AZ": "AZ_Arizona",
    "GA": "GA_Georgia",
    "CA": "CA_California",
    "MD": "MD_Maryland",
    "NM": "NM_New_Mexico",
    "WA": "WA_Washington",
    "CO": "CO_Colorado",
    "MN": "MN_Minnesota",
    "MT": "MT_Montana",
}


def download_epw(zone: str, meta: dict) -> dict:
    WEATHER_DIR.mkdir(parents=True, exist_ok=True)
    dest = WEATHER_DIR / f"{zone}_{meta['epw_id']}.epw"
    rec = {
        "climate_zone": zone,
        "city": meta["city"],
        "state": meta["state"],
        "epw_id": meta["epw_id"],
        "wmo": meta["wmo"],
        "path": str(dest),
    }
    if dest.exists() and dest.stat().st_size > 10000:
        rec.update({"downloaded": False, "reused": True, "sha256": sha256_file(dest), "bytes": dest.stat().st_size})
        return rec
    last_err = None
    for url in epw_urls(meta):
        try:
            req = Request(url, headers={"User-Agent": "masanet-followup-v1"})
            with urlopen(req, timeout=120) as resp:
                blob = resp.read()
            if url.lower().endswith(".epw") or blob[:20].lstrip().startswith(b"LOCATION"):
                dest.write_bytes(blob)
                zip_member = None
            else:
                z = zipfile.ZipFile(io.BytesIO(blob))
                epw_name = next(n for n in z.namelist() if n.lower().endswith(".epw"))
                dest.write_bytes(z.read(epw_name))
                zip_member = epw_name
            rec.update(
                {
                    "downloaded": True,
                    "url": url,
                    "zip_member": zip_member,
                    "sha256": sha256_file(dest),
                    "bytes": dest.stat().st_size,
                    "source": url.split("/")[2],
                    "version_note": (
                        "Paper cites EnergyPlus 2016 TMY. Exact vintage of the authors' files is not recoverable; "
                        "using the standard TMY3 station for the DOE representative city."
                    ),
                }
            )
            return rec
        except Exception as e:
            last_err = f"{url}: {type(e).__name__}: {e}"
    rec["error"] = last_err
    return rec


def parse_epw(path: Path):
    lines = path.read_text(errors="replace").splitlines()
    loc = lines[0]
    data = []
    # EPW: 8 header lines, then 8760 data rows
    for ln in lines[8:]:
        if not ln.strip():
            continue
        p = ln.split(",")
        if len(p) < 10:
            continue
        data.append(
            {
                "year": int(float(p[0])),
                "month": int(float(p[1])),
                "day": int(float(p[2])),
                "hour": int(float(p[3])),
                "minute": int(float(p[4])) if p[4] else 0,
                "T_oa": float(p[6]),
                "T_dew": float(p[7]),
                "RH_oa": float(p[8]),
                "P_oa": float(p[9]),
            }
        )
    df = pd.DataFrame(data)
    return df, loc


def main():
    set_threads()
    FOLLOWUP.mkdir(parents=True, exist_ok=True)
    artifacts = []
    parsed = {}
    errors = []
    for z in NEEDED_ZONES:
        meta = CLIMATE_CITIES[z]
        rec = download_epw(z, meta)
        artifacts.append(rec)
        if rec.get("error"):
            errors.append(rec["error"])
            continue
        df, loc = parse_epw(Path(rec["path"]))
        parsed[z] = {
            "location_header": loc,
            "n_rows": int(len(df)),
            "T_oa_C_range": [float(df["T_oa"].min()), float(df["T_oa"].max())],
            "RH_oa_pct_range": [float(df["RH_oa"].min()), float(df["RH_oa"].max())],
            "P_oa_Pa_range": [float(df["P_oa"].min()), float(df["P_oa"].max())],
            "units": {"T_oa": "deg_C", "RH_oa": "percent", "P_oa": "Pa"},
            "n_8760": int(len(df) == 8760),
        }
        outp = FOLLOWUP / f"weather_{z}.parquet"
        df.to_parquet(outp, index=False)
        parsed[z]["parquet"] = str(outp)
    man = {
        "timestamp_utc": utcnow(),
        "needed_zones": NEEDED_ZONES,
        "ue_climate_zones": UE_CLIMATE_ZONES,
        "city_source": (
            "DOE/IECC representative cities corresponding to paper text "
            "'representative city designated by the U.S. Department of Energy'; "
            "Figure 2 bracket labels were not OCR-readable."
        ),
        "artifacts": artifacts,
        "parsed": parsed,
        "errors": errors,
        "status": "PASS" if not errors and all(parsed[z]["n_rows"] == 8760 for z in parsed) else "FAIL",
    }
    atomic_write_json(FOLLOWUP_MANIFESTS / "FOLLOWUP_V1_WEATHER.json", man)
    print(json.dumps({"status": man["status"], "zones": {z: parsed.get(z, {}).get("n_rows") for z in NEEDED_ZONES}, "errors": errors}, indent=2))
    if man["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
