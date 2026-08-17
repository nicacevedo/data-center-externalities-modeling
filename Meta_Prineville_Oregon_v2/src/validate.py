from pathlib import Path
import pandas as pd
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
TARGETS=ROOT/'data'/'canonical'/'meta_prineville_annual.csv'


def annual_compare(hourly: pd.DataFrame, target_years=None):
    t=pd.read_csv(TARGETS)
    if target_years is not None: t=t[t.year.isin(target_years)]
    h=hourly.copy(); h['timestamp_utc']=pd.to_datetime(h.timestamp_utc,utc=True); h['year']=h.timestamp_utc.dt.year
    agg=h.groupby('year').agg(
        electricity_mwh_model=('p_fac_mw','sum'),
        water_m3_model=('evap_water_m3_per_h','sum'),
        min_pue=('pue','min'), max_pue=('pue','max')
    ).reset_index()
    z=t.merge(agg,on='year',how='left')
    z['electricity_pct_error']=100*(z.electricity_mwh_model-z.electricity_mwh_reported)/z.electricity_mwh_reported
    z['water_pct_error']=100*(z.water_m3_model-z.water_withdrawal_m3_reported)/z.water_withdrawal_m3_reported
    return z


def identity_checks(hourly):
    assert (hourly[['p_it_mw','p_fan_mw','p_other_mw','p_evap_aux_mw','p_fac_mw']].dropna()>=0).all().all()
    assert (hourly['pue'].dropna()>=1).all()
    assert (hourly['evap_water_m3_per_h'].dropna()>=0).all()
    lhs=hourly['p_it_mw']+hourly['p_fan_mw']+hourly['p_other_mw']+hourly['p_evap_aux_mw']
    assert np.nanmax(np.abs(lhs-hourly['p_fac_mw']))<1e-9
    return True
