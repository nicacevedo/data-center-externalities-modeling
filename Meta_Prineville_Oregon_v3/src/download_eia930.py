"""Download EIA APIv2 RTO data for PacifiCorp West (PACW).

Requires a free EIA API key in EIA_API_KEY. The downloader intentionally queries
metadata and pulls all `type` values for PACW rather than hard-coding type codes.
"""
from pathlib import Path
import argparse, os, json
import requests
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
BASE='https://api.eia.gov/v2/electricity/rto'


def key():
    k=os.getenv('EIA_API_KEY')
    if not k: raise SystemExit('Set EIA_API_KEY to your free EIA key (https://www.eia.gov/opendata/).')
    return k


def get_json(url, params=None):
    p={'api_key':key()}; p.update(params or {})
    r=requests.get(url,params=p,timeout=120); r.raise_for_status(); return r.json()


def discover():
    for route in ['', '/region-data', '/fuel-type-data']:
        u=BASE+route
        j=get_json(u)
        print('\n###',u)
        print(json.dumps(j.get('response',j),indent=2)[:20000])


def pull(route,start,end,ba='PACW'):
    url=f'{BASE}/{route}/data/'
    params=[
        ('frequency','hourly'), ('data[0]','value'),
        ('facets[respondent][]',ba), ('start',start), ('end',end),
        ('sort[0][column]','period'), ('sort[0][direction]','asc'),
    ]
    rows=[]; offset=0; page=5000
    while True:
        p=params+[('offset',str(offset)),('length',str(page)),('api_key',key())]
        r=requests.get(url,params=p,timeout=120); r.raise_for_status(); j=r.json()
        block=j.get('response',{}).get('data',[])
        rows.extend(block)
        total=int(j.get('response',{}).get('total',len(rows)))
        print(route,offset,len(block),'of',total)
        offset += len(block)
        if not block or offset>=total: break
    return pd.DataFrame(rows)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--discover',action='store_true')
    ap.add_argument('--start',default='2019-01-01T00')
    ap.add_argument('--end',default='2024-12-31T23')
    ap.add_argument('--ba',default='PACW')
    a=ap.parse_args()
    if a.discover: return discover()
    out=ROOT/'data'/'raw'/'eia930'; out.mkdir(parents=True,exist_ok=True)
    for route in ['region-data','fuel-type-data']:
        d=pull(route,a.start,a.end,a.ba)
        p=out/f'{a.ba}_{route}_{a.start[:4]}_{a.end[:4]}.csv'
        d.to_csv(p,index=False); print('wrote',p,len(d))


if __name__=='__main__': main()
