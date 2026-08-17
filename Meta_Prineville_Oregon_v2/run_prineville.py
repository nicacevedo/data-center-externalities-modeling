from pathlib import Path
import sys, subprocess

ROOT=Path(__file__).resolve().parent

def water():
    subprocess.run([sys.executable,str(ROOT/'src'/'prepare_owrd_wateruse.py')],check=True)

def audit():
    subprocess.run([sys.executable,str(ROOT/'src'/'build_targets.py')],check=True)
    water()
    subprocess.run([sys.executable,str(ROOT/'src'/'change_point_seed.py')],check=True)

def conditional():
    subprocess.run([sys.executable,str(ROOT/'src'/'conditional_reconstruction.py')],check=True)

def calibrate():
    print('Public-data calibration uses the conditional reconstruction as the defensible baseline:')
    print('  python run_prineville.py conditional')
    print('It closes annual facility electricity, fits water-scale/optional break on training years only, and leaves 2023-2024 held out.')
    print('OWRD municipal production and Vitesse/Facebook direct POD series are external water evidence; they are not silently substituted for Meta site-meter withdrawal.')

def validate():
    p=ROOT/'outputs'/'conditional_annual_compare.csv'
    if p.exists():
        import pandas as pd
        z=pd.read_csv(p)
        print(z.to_string(index=False))
        h=z[z.split=='holdout'].dropna(subset=['water_pct_error'])
        if len(h):
            print('\nHeld-out water absolute percentage errors (%):')
            print(h[['year','water_pct_error']].assign(abs_pct_error=lambda x:x.water_pct_error.abs()).to_string(index=False))
        print('\nReminder: annual electricity is calibration closure in this baseline, not held-out prediction.')
    else:
        print('Conditional outputs not present; skipping conditional comparison.')

    audit_path=ROOT/'outputs'/'owrd_mapping_audit.csv'
    if audit_path.exists():
        import pandas as pd
        a=pd.read_csv(audit_path)
        print('\nOWRD source mapping status:')
        print(a.groupby('mapping_status',dropna=False).size().rename('sources').to_string())
        unresolved=a[a['mapping_status'].isin(['UNRESOLVED_CURRENT','CONFLICT_DO_NOT_MAP','AMBIGUOUS_COMBINED_ALIAS'])]
        if len(unresolved):
            print('\nOWRD sources intentionally not auto-mapped:')
            print(unresolved[['oha_facility_id','canonical_source_name','mapping_status']].to_string(index=False))

def main():
    cmd=sys.argv[1] if len(sys.argv)>1 else 'audit'
    if cmd=='audit': audit()
    elif cmd=='water': water()
    elif cmd=='conditional': conditional()
    elif cmd=='calibrate': calibrate()
    elif cmd=='validate': validate()
    else: raise SystemExit('Usage: python run_prineville.py [audit|water|conditional|calibrate|validate]')

if __name__=='__main__': main()
