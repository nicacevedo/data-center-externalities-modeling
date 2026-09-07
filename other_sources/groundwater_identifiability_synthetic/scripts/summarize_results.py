#!/usr/bin/env python3
"""CLI for the preregistered summarizer. Frozen before ANALYSIS seeds are touched.

    python scripts/summarize_results.py --fixtures
    python scripts/summarize_results.py --smoke
"""

from __future__ import annotations

import argparse

import _bootstrap_path  # noqa: F401

from groundwater_identifiability_synthetic.src.design import load_design
from groundwater_identifiability_synthetic.src.summarize import (
    FIXTURE_DIR,
    NONINFERENTIAL_BANNER,
    OUTPUTS,
    load_records,
    summarize,
    write_summary,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    design = load_design()

    if args.fixtures:
        for fixture in sorted(FIXTURE_DIR.glob("*.csv")):
            records = load_records(fixture)
            payload = summarize(design, records, source="FIXTURE")
            payload["fixture"] = fixture.name
            write_summary(payload, f"fixture_{fixture.stem}")
            print(f"fixture {fixture.name}: records={len(records)}")
        return 0

    if args.smoke:
        smoke_csv = OUTPUTS / "SMOKE_ENGINEERING_REPLICATES.csv"
        if not smoke_csv.exists():
            raise SystemExit("no smoke replicates; run scripts/run_smoke.py first")
        records = load_records(smoke_csv)
        payload = summarize(design, records, source="SMOKE")
        write_summary(payload, "SMOKE_SUMMARY_NONINFERENTIAL")
        print(NONINFERENTIAL_BANNER)
        print(f"smoke records={len(records)} written to summarizer/SMOKE_SUMMARY_NONINFERENTIAL.json")
        return 0

    print("summarize_results.py: pass --fixtures or --smoke. ANALYSIS is not authorized here.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
