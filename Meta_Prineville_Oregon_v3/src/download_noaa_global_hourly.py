"""Download NOAA NCEI Global Hourly files for KRDM / Redmond Roberts Field.

NCEI public yearly indexes confirm file ID 72692024230 in both 2011 and 2024.
The script deliberately fails if a requested year is not present rather than silently
substituting a different station.
"""
from pathlib import Path
import argparse
import requests

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATION = '72692024230'
URL = 'https://www.ncei.noaa.gov/data/global-hourly/access/{year}/{station}.csv'


def download(year: int, station: str, outdir: Path, force=False):
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f'{station}_{year}.csv'
    if out.exists() and not force:
        print(f'skip {year}: {out.name} exists')
        return
    url = URL.format(year=year, station=station)
    r = requests.get(url, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f'{year}: HTTP {r.status_code} for {url}. Do not substitute a station silently.')
    if 'DATE' not in r.text[:5000] or 'TMP' not in r.text[:5000]:
        raise RuntimeError(f'{year}: response did not look like NOAA Global Hourly CSV.')
    out.write_bytes(r.content)
    print(f'{year}: {len(r.content):,} bytes -> {out}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', type=int, default=2011)
    ap.add_argument('--end', type=int, default=2024)
    ap.add_argument('--station', default=DEFAULT_STATION)
    ap.add_argument('--outdir', type=Path, default=ROOT/'data'/'raw'/'noaa')
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    for y in range(a.start, a.end + 1):
        download(y, a.station, a.outdir, a.force)


if __name__ == '__main__':
    main()
