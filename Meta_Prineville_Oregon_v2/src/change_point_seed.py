"""Simple model-agnostic candidate break finder for annual public targets.

This does not declare causal/technology events. It only ranks years where a two-segment
linear fit materially improves over a single linear trend. Compare candidates against
independent permit/event records before defining epochs.
"""
from pathlib import Path
import numpy as np, pandas as pd

ROOT=Path(__file__).resolve().parents[1]
D=pd.read_csv(ROOT/'data'/'canonical'/'meta_prineville_annual.csv')

def sse(x,y):
    X=np.column_stack([np.ones(len(x)),x]); b=np.linalg.lstsq(X,y,rcond=None)[0]
    return float(np.sum((y-X@b)**2))

def rank(metric,min_seg=3):
    z=D[['year',metric]].dropna(); x=z.year.to_numpy(float); y=z[metric].to_numpy(float)
    base=sse(x,y); out=[]
    for k in range(min_seg,len(z)-min_seg+1):
        two=sse(x[:k],y[:k])+sse(x[k:],y[k:])
        out.append({'candidate_break_year':int(x[k]),'metric':metric,'relative_sse_reduction':1-two/base})
    return pd.DataFrame(out).sort_values('relative_sse_reduction',ascending=False)

if __name__=='__main__':
    frames=[]
    for m in ['electricity_mwh_reported','water_withdrawal_m3_reported','water_intensity_L_per_kWh_facility_derived']:
        frames.append(rank(m).head(5))
    out=pd.concat(frames,ignore_index=True)
    p=ROOT/'outputs'/'candidate_annual_breaks.csv'; p.parent.mkdir(exist_ok=True); out.to_csv(p,index=False)
    print(out.to_string(index=False)); print('Wrote',p)
