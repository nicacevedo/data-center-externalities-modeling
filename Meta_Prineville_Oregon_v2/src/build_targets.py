from pathlib import Path
import calendar
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ROOT / 'data' / 'canonical' / 'meta_prineville_annual.csv'
FLEET = ROOT / 'data' / 'canonical' / 'meta_fleet_kpis.csv'
OUT = ROOT / 'outputs' / 'annual_audit.csv'

EXPECTED_E = {
    2011:71000, 2012:153000, 2013:224000, 2014:262000,
    2015:284000, 2016:327000, 2017:426000, 2018:488000,
    2019:573000, 2020:686000, 2021:898409, 2022:982177,
    2023:1375321, 2024:1728291,
}


def main():
    df = pd.read_csv(TARGETS)
    assert df['year'].tolist() == list(range(2011, 2025)), 'Expected one row for every year 2011-2024.'
    assert not df['electricity_mwh_reported'].isna().any(), 'Electricity must be complete 2011-2024.'
    assert (df['electricity_mwh_reported'] > 0).all()
    numeric = df.drop(columns=['notes'], errors='ignore').select_dtypes(include=[np.number]).drop(columns=['year'], errors='ignore')
    assert numeric.where(numeric.notna(), 0).ge(0).all().all(), 'All observed/derived numeric quantities must be nonnegative.'

    for _, r in df.iterrows():
        y = int(r.year)
        assert int(r.hours_in_year) == (366 if calendar.isleap(y) else 365) * 24
        assert int(r.electricity_mwh_reported) == EXPECTED_E[y]
        expected_mw = r.electricity_mwh_reported / r.hours_in_year
        assert abs(r.avg_facility_power_mw_derived - expected_mw) < 1e-5
        if pd.notna(r.water_withdrawal_m3_reported):
            expected_wi = r.water_withdrawal_m3_reported / r.electricity_mwh_reported
            assert abs(r.water_intensity_L_per_kWh_facility_derived - expected_wi) < 1e-6
        if pd.notna(r.location_based_scope2_tco2e_reported):
            expected_ef = 1000 * r.location_based_scope2_tco2e_reported / r.electricity_mwh_reported
            assert abs(r.location_based_scope2_kg_per_mwh_derived - expected_ef) < 1e-4

    fleet = pd.read_csv(FLEET)
    assert (fleet['site_specific'] == False).all(), 'Fleet KPIs must remain explicitly non-site-specific.'

    audit = df[['year','electricity_mwh_reported','avg_facility_power_mw_derived',
                'water_withdrawal_m3_reported','water_intensity_L_per_kWh_facility_derived',
                'location_based_scope2_tco2e_reported','location_based_scope2_kg_per_mwh_derived',
                'operational_scope1_2_tco2e_reported']].copy()
    audit['electricity_yoy_pct'] = 100 * audit['electricity_mwh_reported'].pct_change()
    audit['water_yoy_pct'] = 100 * audit['water_withdrawal_m3_reported'].pct_change(fill_method=None)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    audit.to_csv(OUT, index=False)
    print(f'PASS: curated annual targets validated. Wrote {OUT}')


if __name__ == '__main__':
    main()
