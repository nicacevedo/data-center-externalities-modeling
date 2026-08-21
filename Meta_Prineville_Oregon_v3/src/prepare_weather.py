"""Clean NOAA Global Hourly CSVs into one regular hourly weather table.

Output columns are sufficient for the Prineville cooling model. This script preserves
source QC codes, rejects NOAA missing sentinels/impossible physical values, applies
official NCEI/ISD QC to temperature, dew point, and sea-level pressure, and computes
RH and pressure-aware wet-bulb temperature. Long gaps remain missing by design.
"""
from pathlib import Path
import math
import pandas as pd
import numpy as np

try:
    import psychrolib
    psychrolib.SetUnitSystem(psychrolib.SI)
except Exception:
    psychrolib = None

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT/'data'/'raw'/'noaa'
OUT = ROOT/'data'/'processed'/'weather_krdm_hourly.csv'
QC_FREQ_OUT = ROOT/'outputs'/'weather_ks39'/'krdm_ncei_qc_frequencies.csv'
STATION = '72692024230'
ELEV_M = 929.0

# NCEI ISD additional-data quality codes (isd-format-document.pdf).
# Passed gross / all QC: 0, 1, 4, 5, 9.
# Editorial/manual retained by official meaning:
#   A = flagged suspect but accepted as a good value
#   C = AWOS whole °C; automated QC applied, treated as valid
#   M = manual change from QC analysis
#   P = replaced by validator
# Suspect/erroneous, including NCEI-source variants: 2, 3, 6, 7 — reject.
# Unknown / undocumented (I, R, U, empty, other): reject conservatively.
NCEI_QC_PASSED = frozenset({"0", "1", "4", "5", "9"})
NCEI_QC_EDITORIAL_RETAIN = frozenset({"A", "C", "M", "P"})
NCEI_QC_SUSPECT_ERRONEOUS = frozenset({"2", "3", "6", "7"})
SHORT_GAP_LIMIT_HOURS = 2


def ncei_qc_code(x) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return ""
    s = str(x).strip().upper()
    if s in {"", "NAN", "NONE", "NAT"}:
        return ""
    return s[:1]


def ncei_qc_usable(code) -> bool:
    c = ncei_qc_code(code)
    return c in NCEI_QC_PASSED or c in NCEI_QC_EDITORIAL_RETAIN


def ncei_qc_action(code) -> str:
    c = ncei_qc_code(code)
    if ncei_qc_usable(c):
        return "retain"
    if c in NCEI_QC_SUSPECT_ERRONEOUS:
        return "reject_suspect_erroneous"
    return "reject_unknown_conservative"


def _join_qc_codes(series) -> str:
    codes = sorted({ncei_qc_code(x) for x in series if ncei_qc_code(x)})
    return ";".join(codes)


def write_krdm_qc_frequencies(raw: pd.DataFrame, path: Path) -> pd.DataFrame:
    rows = []
    n = len(raw)
    for var, col in (("TMP", "tmp_qc"), ("DEW", "dew_qc"), ("SLP", "slp_qc")):
        codes = raw[col].map(ncei_qc_code)
        codes = codes.mask(codes.eq(""), "(empty)")
        vc = codes.value_counts(dropna=False)
        for code, cnt in vc.items():
            raw_code = "" if code == "(empty)" else str(code)
            rows.append({
                "variable": var,
                "qc_code": code,
                "n": int(cnt),
                "pct": 100.0 * int(cnt) / n if n else np.nan,
                "action": ncei_qc_action(raw_code),
            })
    out = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)
    out.to_csv(ROOT / "outputs" / "krdm_ncei_qc_frequencies.csv", index=False)
    return out


def scaled_with_qc(x, scale=10.0, missing=9999):
    if pd.isna(x): return (np.nan, '')
    p = str(x).split(',')
    try:
        raw = int(p[0])
    except Exception:
        return (np.nan, p[1] if len(p)>1 else '')
    if abs(raw) >= missing:
        return (np.nan, p[1] if len(p)>1 else '')
    return (raw/scale, p[1] if len(p)>1 else '')


def wind_speed(x):
    if pd.isna(x): return np.nan
    p = str(x).split(',')
    if len(p) < 5: return np.nan
    try:
        v = int(p[3])
        return np.nan if v >= 9999 else v/10.0
    except Exception:
        return np.nan


def precip_depth(x):
    if pd.isna(x): return np.nan
    p = str(x).split(',')
    if len(p) < 2: return np.nan
    try:
        v = int(p[1])
        return np.nan if v >= 9999 else v/10.0
    except Exception:
        return np.nan


def rh_from_t_td(t, td):
    # Magnus approximation; percent.
    if not np.isfinite(t) or not np.isfinite(td): return np.nan
    a, b = 17.625, 243.04
    return float(np.clip(100*np.exp(a*td/(b+td) - a*t/(b+t)), 0, 100))


def station_pressure_from_slp(slp_hpa, t_c, elev_m=ELEV_M):
    if np.isfinite(slp_hpa):
        # Hypsometric approximation from sea-level to station pressure.
        tk = (t_c if np.isfinite(t_c) else 10.0) + 273.15
        return slp_hpa*100.0 * math.exp(-9.80665*float(elev_m)/(287.05*tk))
    return 101325.0 * (1 - 2.25577e-5*float(elev_m))**5.2559


def short_gap_interpolated(s, limit: int = SHORT_GAP_LIMIT_HOURS):
    """Linear interpolation for isolated gaps of at most `limit` hours.

    A longer gap is left entirely missing. Bracketing observations must be finite.
    Precipitation must not be passed to this helper.
    """
    x = pd.to_numeric(s, errors="coerce").to_numpy(dtype=float)
    missing = ~np.isfinite(x)
    out = x.copy()
    filled = np.zeros(len(x), dtype=bool)
    n = len(x)
    i = 0
    while i < n:
        if not missing[i]:
            i += 1
            continue
        j = i
        while j < n and missing[j]:
            j += 1
        gap_len = j - i
        left = i - 1
        right = j
        has_left = left >= 0 and np.isfinite(out[left])
        has_right = right < n and np.isfinite(out[right])
        if gap_len <= limit and has_left and has_right:
            span = right - left
            for k in range(i, j):
                w = (k - left) / span
                out[k] = out[left] * (1.0 - w) + out[right] * w
                filled[k] = True
        i = j
    return pd.Series(out, index=s.index), pd.Series(filled, index=s.index)


def gap_run_lengths(mask) -> np.ndarray:
    """Consecutive True-run length for each position; 0 where mask is False."""
    m = np.asarray(mask, dtype=bool)
    n = len(m)
    lengths = np.zeros(n, dtype=int)
    i = 0
    while i < n:
        if not m[i]:
            i += 1
            continue
        j = i
        while j < n and m[j]:
            j += 1
        lengths[i:j] = j - i
        i = j
    return lengths


def wetbulb(t, td, p_pa, rh):
    if psychrolib is not None and np.isfinite(t) and np.isfinite(td) and np.isfinite(p_pa):
        try: return psychrolib.GetTWetBulbFromTDewPoint(float(t), float(td), float(p_pa))
        except Exception: pass
    # Stull fallback; less accurate and ignores pressure.
    if not np.isfinite(t) or not np.isfinite(rh): return np.nan
    R=float(np.clip(rh,1e-3,100))
    return (t*math.atan(0.151977*math.sqrt(R+8.313659)) + math.atan(t+R)
            - math.atan(R-1.676331) + 0.00391838*(R**1.5)*math.atan(0.023101*R) - 4.686035)


def read_one(path: Path):
    d = pd.read_csv(path, low_memory=False)
    ts = pd.to_datetime(d['DATE'], utc=True, errors='coerce')
    tmp = d['TMP'].apply(lambda x: scaled_with_qc(x,10,9999))
    dew = d['DEW'].apply(lambda x: scaled_with_qc(x,10,9999))
    slp = d['SLP'].apply(lambda x: scaled_with_qc(x,10,99999)) if 'SLP' in d else pd.Series([(np.nan,'')]*len(d))
    z = pd.DataFrame({
        'timestamp_utc':ts,
        't_db_C':[x[0] for x in tmp], 'tmp_qc':[x[1] for x in tmp],
        't_dew_C':[x[0] for x in dew], 'dew_qc':[x[1] for x in dew],
        'slp_hPa':[x[0] for x in slp], 'slp_qc':[x[1] for x in slp],
        'wind_m_s':d['WND'].apply(wind_speed) if 'WND' in d else np.nan,
        'precip_mm':d['AA1'].apply(precip_depth) if 'AA1' in d else np.nan,
        'source_file':path.name,
    }).dropna(subset=['timestamp_utc'])
    z.loc[~z['t_db_C'].between(-60,60),'t_db_C']=np.nan
    z.loc[~z['t_dew_C'].between(-80,50),'t_dew_C']=np.nan
    return z


def apply_ncei_qc(raw: pd.DataFrame) -> pd.DataFrame:
    """Null T/Td/SLP that fail documented NCEI QC. Preserve original QC codes."""
    z = raw.copy()
    z['t_db_C'] = z['t_db_C'].where(z['tmp_qc'].map(ncei_qc_usable))
    z['t_dew_C'] = z['t_dew_C'].where(z['dew_qc'].map(ncei_qc_usable))
    z['slp_hPa'] = z['slp_hPa'].where(z['slp_qc'].map(ncei_qc_usable))
    return z


def process_ncei_global_hourly(
    station: str,
    elev_m: float,
    raw_dir: Path,
    out_path: Path,
    station_label: str,
    slp_method: str,
    std_method: str,
    qc_freq_out: Path | None = None,
) -> pd.DataFrame:
    """Hourly NCEI Global Hourly product. Does not interpolate long gaps."""
    files = sorted(raw_dir.glob(f"{station}_*.csv"))
    if not files:
        raise SystemExit(f"No NOAA files found in {raw_dir} for {station}.")
    raw = pd.concat([read_one(p) for p in files], ignore_index=True)
    if qc_freq_out is not None:
        write_krdm_qc_frequencies(raw, qc_freq_out)
    raw = apply_ncei_qc(raw)
    raw["hour"] = raw["timestamp_utc"].dt.floor("h")
    h = raw.groupby("hour", as_index=False).agg(
        t_db_C=("t_db_C", "mean"),
        t_dew_C=("t_dew_C", "mean"),
        slp_hPa=("slp_hPa", "mean"),
        wind_m_s=("wind_m_s", "mean"),
        precip_mm=("precip_mm", "sum"),
        tmp_qc=("tmp_qc", _join_qc_codes),
        dew_qc=("dew_qc", _join_qc_codes),
        slp_qc=("slp_qc", _join_qc_codes),
        source_file=("source_file", lambda x: ";".join(sorted(set(x)))),
    ).rename(columns={"hour": "timestamp_utc"})
    h["rh_pct"] = [rh_from_t_td(t, td) for t, td in zip(h.t_db_C, h.t_dew_C)]
    h["pressure_Pa"] = [
        station_pressure_from_slp(p, t, elev_m=elev_m) for p, t in zip(h.slp_hPa, h.t_db_C)
    ]
    h["pressure_method"] = np.where(h["slp_hPa"].notna(), slp_method, std_method)
    h["t_wb_C"] = [
        wetbulb(t, td, p, rh) for t, td, p, rh in zip(h.t_db_C, h.t_dew_C, h.pressure_Pa, h.rh_pct)
    ]
    idx = pd.date_range(h.timestamp_utc.min(), h.timestamp_utc.max(), freq="h", tz="UTC")
    h = h.set_index("timestamp_utc").reindex(idx).rename_axis("timestamp_utc").reset_index()
    h.loc[h["slp_hPa"].notna(), "pressure_method"] = slp_method
    h.loc[h["pressure_Pa"].notna() & h["slp_hPa"].isna(), "pressure_method"] = std_method
    h["pressure_method"] = h["pressure_method"].fillna("")
    h["station"] = station_label
    h["provenance"] = (
        "measured NOAA station observation; NCEI QC on T/Td/SLP; "
        "hourly aggregation; derived RH/wet-bulb"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    h.to_csv(out_path, index=False)
    miss = 100 * h["t_db_C"].isna().mean()
    print(f"Wrote {out_path}: {len(h):,} hours; dry-bulb missing {miss:.2f}%")
    return h


def main():
    process_ncei_global_hourly(
        station=STATION,
        elev_m=ELEV_M,
        raw_dir=RAW,
        out_path=OUT,
        station_label="KRDM / 72692024230",
        slp_method="krdm_slp_derived",
        std_method="krdm_standard_atmosphere_fallback",
        qc_freq_out=QC_FREQ_OUT,
    )
    print("KRDM baseline only. Canonical model weather is data/processed/weather_hourly.csv (KS39/KRDM mix).")


if __name__=='__main__':
    main()
