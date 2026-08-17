from pathlib import Path
import sys, subprocess

ROOT=Path(__file__).resolve().parent

def audit():
    subprocess.run([sys.executable,str(ROOT/'src'/'build_targets.py')],check=True)
    subprocess.run([sys.executable,str(ROOT/'src'/'change_point_seed.py')],check=True)

def conditional():
    subprocess.run([sys.executable,str(ROOT/'src'/'conditional_reconstruction.py')],check=True)

def calibrate():
    print('Public-data calibration uses the conditional reconstruction as the defensible baseline:')
    print('  python run_prineville.py conditional')
    print('It closes annual facility electricity, fits water-scale/optional break on training years only, and leaves 2023-2024 held out.')
    print('After City/OWRD monthly data arrive, replace annual-only water fitting with monthly likelihood and keep the same accounting/physics layer.')

def validate():
    p=ROOT/'outputs'/'conditional_annual_compare.csv'
    if not p.exists():
        raise SystemExit('Missing conditional outputs. Run: python run_prineville.py conditional')
    import pandas as pd
    z=pd.read_csv(p)
    print(z.to_string(index=False))
    h=z[z.split=='holdout'].dropna(subset=['water_pct_error'])
    if len(h):
        print('\nHeld-out water absolute percentage errors (%):')
        print(h[['year','water_pct_error']].assign(abs_pct_error=lambda x:x.water_pct_error.abs()).to_string(index=False))
    print('\nReminder: annual electricity is calibration closure in this baseline, not held-out prediction.')

def main():
    cmd=sys.argv[1] if len(sys.argv)>1 else 'audit'
    if cmd=='audit': audit()
    elif cmd=='conditional': conditional()
    elif cmd=='calibrate': calibrate()
    elif cmd=='validate': validate()
    else: raise SystemExit('Usage: python run_prineville.py [audit|conditional|calibrate|validate]')

if __name__=='__main__': main()
