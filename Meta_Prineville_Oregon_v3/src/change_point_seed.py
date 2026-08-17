"""Model-agnostic candidate break finder for annual public targets.

Produces both an exploratory all-years ranking and a training-only ranking. The latter
must be used for model selection when 2023-2024 are treated as held-out years.
Neither ranking declares causal/technology events; compare candidates against the
independent permit chronology before defining epochs.
"""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
D = pd.read_csv(ROOT / 'data' / 'canonical' / 'meta_prineville_annual.csv')
TRAIN_END_YEAR = 2022
METRICS = [
    'electricity_mwh_reported',
    'water_withdrawal_m3_reported',
    'water_intensity_L_per_kWh_facility_derived',
]


def sse(x, y):
    X = np.column_stack([np.ones(len(x)), x])
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    return float(np.sum((y - X @ b) ** 2))


def rank(metric, data, min_seg=3):
    z = data[['year', metric]].dropna().sort_values('year')
    x = z.year.to_numpy(float)
    y = z[metric].to_numpy(float)
    if len(z) < 2 * min_seg:
        return pd.DataFrame(columns=['candidate_break_year', 'metric', 'relative_sse_reduction'])
    base = sse(x, y)
    out = []
    for k in range(min_seg, len(z) - min_seg + 1):
        two = sse(x[:k], y[:k]) + sse(x[k:], y[k:])
        reduction = np.nan if base == 0 else 1 - two / base
        out.append({
            'candidate_break_year': int(x[k]),
            'metric': metric,
            'relative_sse_reduction': reduction,
        })
    return pd.DataFrame(out).sort_values('relative_sse_reduction', ascending=False)


def build_table(data):
    frames = [rank(m, data).head(5) for m in METRICS]
    return pd.concat(frames, ignore_index=True)


if __name__ == '__main__':
    exploratory = build_table(D)
    train_only = build_table(D[D.year <= TRAIN_END_YEAR])

    outdir = ROOT / 'outputs'
    outdir.mkdir(exist_ok=True)
    p_ex = outdir / 'candidate_annual_breaks_exploratory.csv'
    p_legacy = outdir / 'candidate_annual_breaks.csv'
    p_tr = outdir / 'candidate_annual_breaks_train_only.csv'
    exploratory.to_csv(p_ex, index=False)
    exploratory.to_csv(p_legacy, index=False)  # backward-compatible alias
    train_only.to_csv(p_tr, index=False)

    print('Exploratory candidate breaks (all available years; NOT for holdout model selection):')
    print(exploratory.to_string(index=False))
    print(f'Wrote {p_ex}')
    print(f'Wrote {p_legacy} (backward-compatible alias)')
    print(f'\nTraining-only candidate breaks (through {TRAIN_END_YEAR}; use for model selection):')
    print(train_only.to_string(index=False))
    print(f'Wrote {p_tr}')
