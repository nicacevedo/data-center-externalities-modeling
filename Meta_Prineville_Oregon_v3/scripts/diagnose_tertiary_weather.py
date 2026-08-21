"""Variable-specific interpolation QA and tertiary NCEI station screen.

Does not write canonical weather. Does not retune models.
"""
from __future__ import annotations

import io
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from prepare_weather import (  # noqa: E402
    SHORT_GAP_LIMIT_HOURS,
    apply_ncei_qc,
    gap_run_lengths,
    ncei_qc_usable,
    read_one,
    short_gap_interpolated,
)
from prepare_weather_ks39 import SWITCH_LOCAL, TZ_LOCAL  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "pipeline_report"
CANON = ROOT / "data" / "processed" / "weather_hourly.csv"
KRDM = ROOT / "data" / "processed" / "weather_krdm_hourly.csv"
KS39 = ROOT / "data" / "processed" / "weather_ks39_hourly.csv"
AUDIT = OUT / "weather_finite_driver_audit.csv"
RAW_NOAA = ROOT / "data" / "raw" / "noaa"
ISD_HISTORY = "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"
GH_URL = "https://www.ncei.noaa.gov/data/global-hourly/access/{year}/{station}.csv"

# Prineville Airport / campus vicinity and KRDM.
PRN_LAT, PRN_LON = 44.286, -120.904
KRDM_LAT, KRDM_LON = 44.2559, -121.1406
MAX_KM = 80.0

GAPS = [
    ("2011-05-26 05:00:00+00:00", "2011-05-26 11:00:00+00:00"),
    ("2011-09-04 22:00:00+00:00", "2011-09-05 00:00:00+00:00"),
    ("2012-05-19 08:00:00+00:00", "2012-05-19 20:00:00+00:00"),
    ("2013-05-31 20:00:00+00:00", "2013-06-01 01:00:00+00:00"),
    ("2013-10-06 00:00:00+00:00", "2013-10-06 02:00:00+00:00"),
    ("2016-09-10 22:00:00+00:00", "2016-09-11 00:00:00+00:00"),
]


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def hourly_index(s: pd.Series) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    return x


def primitive_gaps(series: pd.Series) -> pd.Series:
    miss = ~np.isfinite(pd.to_numeric(series, errors="coerce").to_numpy(dtype=float))
    return pd.Series(gap_run_lengths(miss), index=series.index)


def interp_illegal(series: pd.Series, filled_mask: pd.Series) -> int:
    """Count filled hours whose primitive run exceeds the protocol limit."""
    runs = primitive_gaps(series)
    filled = filled_mask.to_numpy(dtype=bool)
    return int((filled & (runs.to_numpy(dtype=int) > SHORT_GAP_LIMIT_HOURS)).sum())


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    w = pd.read_csv(CANON)
    w["timestamp_utc"] = pd.to_datetime(w["timestamp_utc"], utc=True)
    krdm = pd.read_csv(KRDM)
    krdm["timestamp_utc"] = pd.to_datetime(krdm["timestamp_utc"], utc=True)
    ks = pd.read_csv(KS39)
    ks["timestamp_utc"] = pd.to_datetime(ks["timestamp_utc"], utc=True)
    audit = pd.read_csv(AUDIT)
    audit["timestamp_utc"] = pd.to_datetime(audit["timestamp_utc"], utc=True)

    req = ["t_db_C", "t_wb_C", "rh_pct", "pressure_Pa"]
    live_bad = ~np.isfinite(w[req].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)).all(axis=1)
    print(f"live_canonical_n={len(w)} live_nonfinite_any={int(live_bad.sum())}")

    interp = audit[audit["resolution_method"].astype(str).str.contains("interpolated_short_gap")].copy()
    print(f"audit_interpolated_rows={len(interp)}")

    # Align KRDM primitives onto canonical UTC index (unfilled KRDM product).
    k = krdm.set_index("timestamp_utc")[["t_db_C", "t_dew_C", "slp_hPa", "pressure_Pa", "tmp_qc", "dew_qc", "slp_qc"]]
    k = k.reindex(w["timestamp_utc"].to_numpy())
    ks_idx = ks.set_index("timestamp_utc")
    ks_t = ks_idx.reindex(w["timestamp_utc"].to_numpy())["t_db_C"] if "t_db_C" in ks_idx else pd.Series(np.nan, index=range(len(w)))
    ks_td = ks_idx.reindex(w["timestamp_utc"].to_numpy())["t_dew_C"] if "t_dew_C" in ks_idx else pd.Series(np.nan, index=range(len(w)))
    loc = w["timestamp_utc"].dt.tz_convert(TZ_LOCAL)
    in_ks = loc >= SWITCH_LOCAL
    ks_t = pd.to_numeric(ks_t, errors="coerce").to_numpy(dtype=float)
    ks_td = pd.to_numeric(ks_td, errors="coerce").to_numpy(dtype=float)
    ks_t = np.where(in_ks.to_numpy(), ks_t, np.nan)
    ks_td = np.where(in_ks.to_numpy(), ks_td, np.nan)

    kr_t = pd.to_numeric(k["t_db_C"], errors="coerce")
    kr_td = pd.to_numeric(k["t_dew_C"], errors="coerce")
    kr_slp = pd.to_numeric(k["slp_hPa"], errors="coerce")
    kr_t.index = w.index
    kr_td.index = w.index
    kr_slp.index = w.index

    # Pre-interpolation mix primitives.
    mix_t = np.where(np.isfinite(ks_t) & np.isfinite(ks_td), ks_t, kr_t.to_numpy(dtype=float))
    mix_td = np.where(np.isfinite(ks_t) & np.isfinite(ks_td), ks_td, kr_td.to_numpy(dtype=float))

    _, kr_t_was = short_gap_interpolated(kr_t)
    _, kr_td_was = short_gap_interpolated(kr_td)
    _, kr_slp_was = short_gap_interpolated(kr_slp)
    _, ks_t_was = short_gap_interpolated(pd.Series(ks_t))
    _, ks_td_was = short_gap_interpolated(pd.Series(ks_td))
    _, mix_t_was = short_gap_interpolated(pd.Series(mix_t))
    _, mix_td_was = short_gap_interpolated(pd.Series(mix_td))

    illegal = {
        "kr_t": interp_illegal(kr_t, kr_t_was),
        "kr_td": interp_illegal(kr_td, kr_td_was),
        "kr_slp": interp_illegal(kr_slp, kr_slp_was),
        "ks_t": interp_illegal(pd.Series(ks_t), ks_t_was),
        "ks_td": interp_illegal(pd.Series(ks_td), ks_td_was),
        "mix_t": interp_illegal(pd.Series(mix_t), mix_t_was),
        "mix_td": interp_illegal(pd.Series(mix_td), mix_td_was),
    }
    print("illegal_long_primitive_interpolations", illegal)

    # Per interpolated audit row: primitive gap of the field that was missing.
    interp_ts = set(interp["timestamp_utc"].astype(str))
    w2 = w.copy()
    w2["kr_t_gap"] = primitive_gaps(kr_t).to_numpy()
    w2["kr_td_gap"] = primitive_gaps(kr_td).to_numpy()
    w2["kr_slp_gap"] = primitive_gaps(kr_slp).to_numpy()
    w2["mix_t_gap"] = primitive_gaps(pd.Series(mix_t)).to_numpy()
    w2["mix_td_gap"] = primitive_gaps(pd.Series(mix_td)).to_numpy()
    hit = w2[w2["timestamp_utc"].astype(str).isin(interp_ts)]
    # A fill is invalid if the mixed T gap >2 AND T was interpolated, or mixed Td gap >2 AND Td interpolated.
    t_fill = mix_t_was.reindex(w2.index).fillna(False).to_numpy(dtype=bool)
    td_fill = mix_td_was.reindex(w2.index).fillna(False).to_numpy(dtype=bool)
    kr_t_fill = kr_t_was.reindex(w2.index).fillna(False).to_numpy(dtype=bool)
    kr_td_fill = kr_td_was.reindex(w2.index).fillna(False).to_numpy(dtype=bool)
    bad_t = (t_fill | kr_t_fill) & (w2["mix_t_gap"].to_numpy() > SHORT_GAP_LIMIT_HOURS) & (w2["kr_t_gap"].to_numpy() > SHORT_GAP_LIMIT_HOURS)
    bad_td = (td_fill | kr_td_fill) & (w2["mix_td_gap"].to_numpy() > SHORT_GAP_LIMIT_HOURS) & (w2["kr_td_gap"].to_numpy() > SHORT_GAP_LIMIT_HOURS)
    # Restrict to interpolated audit hours
    mask_interp_hours = w2["timestamp_utc"].astype(str).isin(interp_ts).to_numpy()
    n_bad_t = int((bad_t & mask_interp_hours).sum())
    n_bad_td = int((bad_td & mask_interp_hours).sum())
    print(f"interpolated_hours_with_illegal_T_primitive_gap={n_bad_t}")
    print(f"interpolated_hours_with_illegal_Td_primitive_gap={n_bad_td}")

    # Bracket QC: KRDM tmp_qc/dew_qc on neighboring hours for interpolated KRDM fills.
    qc_fail = 0
    for ts in interp["timestamp_utc"]:
        row = w2[w2.timestamp_utc.eq(ts)]
        if row.empty:
            continue
        i = int(row.index[0])
        if i <= 0 or i >= len(w2) - 1:
            qc_fail += 1
            continue
        # If KRDM T was filled, require usable QC on bracketing KRDM T hours when codes exist.
        if bool(kr_t_fill[i]):
            left = str(k["tmp_qc"].iloc[i - 1]) if i - 1 < len(k) else ""
            right = str(k["tmp_qc"].iloc[i + 1]) if i + 1 < len(k) else ""
            # Empty QC on reindexed missing rows is expected; only fail if a code exists and is unusable.
            if left and left not in {"nan", "None"} and not ncei_qc_usable(left.split(";")[0]):
                qc_fail += 1
            if right and right not in {"nan", "None"} and not ncei_qc_usable(right.split(";")[0]):
                qc_fail += 1
    print(f"interpolated_hours_with_unusable_krdm_bracket_qc_codes={qc_fail}")

    unresolved = audit[pd.to_numeric(audit["post_resolution_finite"], errors="coerce").fillna(1).eq(0)]
    print(f"audit_unresolved={len(unresolved)}")
    print("unresolved_timestamps:")
    for ts in unresolved["timestamp_utc"].astype(str).tolist():
        print(" ", ts)

    # Live canonical vs listed gaps.
    print("=== live gap windows ===")
    for a, b in GAPS:
        a_ts, b_ts = pd.Timestamp(a), pd.Timestamp(b)
        sl = w[(w.timestamp_utc >= a_ts) & (w.timestamp_utc <= b_ts)]
        bad = ~np.isfinite(sl[req].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)).all(axis=1)
        print(f"{a} to {b}: n={len(sl)} nonfinite={int(bad.sum())}")
        if len(sl):
            print(sl[["timestamp_utc", "t_db_C", "t_dew_C", "rh_pct", "t_wb_C", "pressure_Pa", "weather_source", "weather_method"]].to_string(index=False))

    # Raw KRDM at gap hours: any observation present at all (including failed QC)?
    print("=== raw KRDM presence in gap hours ===")
    for a, b in GAPS:
        year = pd.Timestamp(a).year
        path = RAW_NOAA / f"72692024230_{year}.csv"
        extra = RAW_NOAA / f"72692024230_{pd.Timestamp(b).year}.csv"
        files = [path]
        if extra != path and extra.exists():
            files.append(extra)
        raw = pd.concat([read_one(p) for p in files if p.exists()], ignore_index=True)
        raw = apply_ncei_qc(raw)
        raw["hour"] = raw["timestamp_utc"].dt.floor("h")
        hours = pd.date_range(a, b, freq="h", tz="UTC")
        for h in hours:
            g = raw[raw.hour.eq(h)]
            n = len(g)
            n_t = int(g["t_db_C"].notna().sum()) if n else 0
            n_td = int(g["t_dew_C"].notna().sum()) if n else 0
            n_slp = int(g["slp_hPa"].notna().sum()) if n else 0
            print(f"  {h} raw_obs={n} qc_usable_T={n_t} Td={n_td} SLP={n_slp}")

    # Nearby ISD stations
    print("=== downloading ISD history ===")
    r = requests.get(ISD_HISTORY, timeout=120)
    r.raise_for_status()
    hist = pd.read_csv(io.StringIO(r.text))
    hist.columns = [c.strip().upper() for c in hist.columns]
    # Typical columns: USAF, WBAN, STATION NAME, CTRY, ST, CALL, LAT, LON, ELEV(M), BEGIN, END
    lat_col = [c for c in hist.columns if c.startswith("LAT")][0]
    lon_col = [c for c in hist.columns if c.startswith("LON")][0]
    hist[lat_col] = pd.to_numeric(hist[lat_col], errors="coerce")
    hist[lon_col] = pd.to_numeric(hist[lon_col], errors="coerce")
    hist = hist[hist[lat_col].between(43.4, 45.2) & hist[lon_col].between(-122.2, -119.8)].copy()
    hist["dist_prn_km"] = [
        haversine_km(PRN_LAT, PRN_LON, la, lo) if np.isfinite(la) and np.isfinite(lo) else np.nan
        for la, lo in zip(hist[lat_col], hist[lon_col])
    ]
    nearby = hist[hist["dist_prn_km"] <= MAX_KM].copy()
    def _file_id(df):
        usaf = df[[c for c in df.columns if "USAF" in c][0]].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
        wban = df[[c for c in df.columns if "WBAN" in c][0]].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(5)
        return usaf + wban

    nearby["file_id"] = _file_id(nearby)
    hist["file_id"] = _file_id(hist)
    name_col = [c for c in hist.columns if "NAME" in c or "STATION" in c]
    call_col = [c for c in hist.columns if c in {"CALL", "ICAO"} or "CALL" in c]
    print(nearby.sort_values("dist_prn_km")[
        ["file_id", name_col[0] if name_col else nearby.columns[2], call_col[0] if call_col else nearby.columns[5], lat_col, lon_col, "dist_prn_km"]
        + [c for c in nearby.columns if c in {"BEGIN", "END", "ELEV(M)"}]
    ].head(25).to_string(index=False))

    # Exclude KRDM itself. Keep nearby stations whose POR overlaps 2011-2016.
    cands = nearby[~nearby["file_id"].eq("72692024230")].copy()
    if "BEGIN" in cands.columns:
        begin = pd.to_numeric(cands["BEGIN"], errors="coerce")
        end = pd.to_numeric(cands["END"], errors="coerce")
        cands = cands[(begin.fillna(0) <= 20110526) & (end.fillna(99999999) >= 20160910)]
    extras = []
    if call_col:
        extras.append(hist[hist[call_col[0]].astype(str).str.upper().isin(["KBDN", "BDN", "KS39", "S39"])])
    if name_col:
        extras.append(hist[hist[name_col[0]].astype(str).str.upper().str.contains("BEND|PRINEVILLE", na=False)])
    if extras:
        cands = pd.concat([cands, *extras], ignore_index=True)
    cands = cands.drop_duplicates("file_id").sort_values("dist_prn_km")
    # Probe nearest 15 plus any explicit Bend/Prineville ICAO rows.
    probe = cands.head(15)
    print(f"n_candidates_to_probe={len(probe)}")
    cands = probe
    # Probe yearly Global Hourly files at the 35 unresolved hours.
    gap_hours = []
    for a, b in GAPS:
        gap_hours.extend(list(pd.date_range(a, b, freq="h", tz="UTC")))
    years_needed = sorted({pd.Timestamp(h).year for h in gap_hours})
    rows = []
    for _, st in cands.head(8).iterrows():
        sid = st["file_id"]
        rec = {
            "file_id": sid,
            "name": str(st[name_col[0]]) if name_col else "",
            "call": str(st[call_col[0]]) if call_col else "",
            "lat": float(st[lat_col]),
            "lon": float(st[lon_col]),
            "dist_prn_km": float(st["dist_prn_km"]),
            "elev_m": st.get("ELEV(M)", ""),
        }
        n_ok = 0
        n_t = 0
        n_td = 0
        by_year = {}
        for year in years_needed:
            url = GH_URL.format(year=year, station=sid)
            try:
                rr = requests.get(url, timeout=90)
            except Exception as e:
                rec[f"http_{year}"] = f"err:{e}"
                continue
            rec[f"http_{year}"] = rr.status_code
            if rr.status_code != 200 or "TMP" not in rr.text[:4000]:
                continue
            d = pd.read_csv(io.StringIO(rr.text), usecols=lambda c: c in {"DATE", "TMP", "DEW", "SLP", "CALL_SIGN", "NAME"}, low_memory=False)
            d["timestamp_utc"] = pd.to_datetime(d["DATE"], utc=True, errors="coerce")
            d["hour"] = d["timestamp_utc"].dt.floor("h")
            by_year[year] = d
        for h in gap_hours:
            d = by_year.get(h.year)
            if d is None:
                continue
            g = d[d.hour.eq(h)]
            if g.empty:
                continue
            n_ok += 1
            tmp = str(g["TMP"].iloc[0]) if "TMP" in g else ""
            dew = str(g["DEW"].iloc[0]) if "DEW" in g else ""
            if tmp and not tmp.startswith("+9999") and "9999" not in tmp.split(",")[0]:
                n_t += 1
            if dew and not dew.startswith("+9999") and "9999" not in dew.split(",")[0]:
                n_td += 1
        rec["gap_hours_with_any_obs"] = n_ok
        rec["gap_hours_with_tmp"] = n_t
        rec["gap_hours_with_dew"] = n_td
        rec["n_gap_hours"] = len(gap_hours)
        rows.append(rec)
        print(f"CANDIDATE {sid} {rec['name']} {rec['call']} dist={rec['dist_prn_km']:.1f}km obs={n_ok}/{len(gap_hours)} T={n_t} Td={n_td}")

    pd.DataFrame(rows).to_csv(OUT / "tertiary_station_screen.csv", index=False)
    print(f"wrote {OUT / 'tertiary_station_screen.csv'}")


if __name__ == "__main__":
    main()
