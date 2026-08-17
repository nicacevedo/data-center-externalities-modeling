"""Clean NOAA Global Hourly CSVs into one regular hourly weather table.

Output columns are sufficient for the Prineville cooling model. This script preserves
source QC codes, rejects NOAA missing sentinels/impossible physical values, and computes
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
OUT = ROOT/'data'/'processed'/'weather_hourly.csv'
STATION = '72692024230'
ELEV_M = 929.0


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


def station_pressure_from_slp(slp_hpa, t_c):
    if np.isfinite(slp_hpa):
        # Hypsometric approximation from sea-level to station pressure.
        tk = (t_c if np.isfinite(t_c) else 10.0) + 273.15
        return slp_hpa*100.0 * math.exp(-9.80665*ELEV_M/(287.05*tk))
    return 101325.0 * (1 - 2.25577e-5*ELEV_M)**5.2559


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


def main():
    files=sorted(RAW.glob(f'{STATION}_*.csv'))
    if not files:
        raise SystemExit(f'No NOAA files found in {RAW}. Run download_noaa_global_hourly.py first.')
    raw=pd.concat([read_one(p) for p in files], ignore_index=True)
    raw['hour']=raw['timestamp_utc'].dt.floor('h')
    # Multiple sub-hourly obs -> arithmetic hourly means for continuous variables.
    h=raw.groupby('hour',as_index=False).agg(
        t_db_C=('t_db_C','mean'), t_dew_C=('t_dew_C','mean'), slp_hPa=('slp_hPa','mean'),
        wind_m_s=('wind_m_s','mean'), precip_mm=('precip_mm','sum'),
        source_file=('source_file',lambda x:';'.join(sorted(set(x))))
    ).rename(columns={'hour':'timestamp_utc'})
    h['rh_pct']=[rh_from_t_td(t,td) for t,td in zip(h.t_db_C,h.t_dew_C)]
    h['pressure_Pa']=[station_pressure_from_slp(p,t) for p,t in zip(h.slp_hPa,h.t_db_C)]
    h['t_wb_C']=[wetbulb(t,td,p,rh) for t,td,p,rh in zip(h.t_db_C,h.t_dew_C,h.pressure_Pa,h.rh_pct)]
    # Reindex to a complete regular UTC hourly grid; do not fill long gaps.
    idx=pd.date_range(h.timestamp_utc.min(),h.timestamp_utc.max(),freq='h',tz='UTC')
    h=h.set_index('timestamp_utc').reindex(idx).rename_axis('timestamp_utc').reset_index()
    h['station']='KRDM / 72692024230'
    h['provenance']='measured NOAA station observation; hourly aggregation; derived RH/wet-bulb'
    OUT.parent.mkdir(parents=True,exist_ok=True)
    h.to_csv(OUT,index=False)
    miss=100*h['t_db_C'].isna().mean()
    print(f'Wrote {OUT}: {len(h):,} hours; dry-bulb missing {miss:.2f}%')


if __name__=='__main__':
    main()
