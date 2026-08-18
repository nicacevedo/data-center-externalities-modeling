from pathlib import Path
import sys, subprocess

ROOT=Path(__file__).resolve().parent

def water():
    subprocess.run([sys.executable,str(ROOT/'src'/'prepare_owrd_wateruse.py')],check=True)

def eia():
    subprocess.run([sys.executable,str(ROOT/'src'/'prepare_eia930.py'), *sys.argv[2:]],check=True)

def owrd_validate():
    subprocess.run([sys.executable,str(ROOT/'src'/'owrd_water_model_validation.py'), *sys.argv[2:]],check=True)

def audit():
    subprocess.run([sys.executable,str(ROOT/'src'/'build_targets.py')],check=True)
    water()
    subprocess.run([sys.executable,str(ROOT/'src'/'audit_campus_permits.py')],check=True)
    subprocess.run([sys.executable,str(ROOT/'src'/'change_point_seed.py')],check=True)

def conditional():
    # Reconstruction is rebuilt inside owrd-validate so the consistency layer
    # cannot silently use a stale hourly file.
    owrd_validate()

def simulate():
    subprocess.run(
        [sys.executable, str(ROOT/'src'/'stochastic_conditional_simulation.py'), *sys.argv[2:]],
        check=True,
    )

def calibrate():
    print('Public-data calibration uses the conditional reconstruction as the defensible baseline:')
    print('  python run_prineville.py conditional')
    print('It closes annual facility electricity, fits water-scale/optional break on training years only, and leaves 2023-2024 held out.')
    print('OWRD municipal production and Vitesse/Facebook direct POD series are external water evidence; they are not silently substituted for Meta site-meter withdrawal.')
    print('After reconstruction, python run_prineville.py validate (or owrd-validate) compares the modeled monthly campus series with those OWRD observations without using them as calibration targets.')
    print('python run_prineville.py simulate remains the separate stochastic proxy workflow.')

def validate():
    print('\nOWRD water-model validation (external consistency layer; not a calibration target):')
    print('Rebuilding the hourly reconstruction before comparing OWRD series.')
    owrd_validate()

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
    elif cmd=='simulate': simulate()
    elif cmd=='calibrate': calibrate()
    elif cmd=='validate': validate()
    elif cmd=='owrd-validate': owrd_validate()
    elif cmd=='eia': eia()
    else: raise SystemExit('Usage: python run_prineville.py [audit|water|conditional|simulate|calibrate|validate|owrd-validate|eia]')

if __name__=='__main__': main()
