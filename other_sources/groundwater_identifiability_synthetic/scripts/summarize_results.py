#!/usr/bin/env python3
"""CLI for the preregistered summarizer.

    python scripts/summarize_results.py --fixtures
    python scripts/summarize_results.py --smoke
    python scripts/summarize_results.py --analysis
"""

from __future__ import annotations

import argparse
import json

import _bootstrap_path  # noqa: F401

from groundwater_identifiability_synthetic.src.design import load_design
from groundwater_identifiability_synthetic.src.summarize import (
    ANALYSIS_OUT,
    FIXTURE_DIR,
    NONINFERENTIAL_BANNER,
    OUTPUTS,
    PROVENANCE,
    load_records,
    summarize,
    validate_analysis_inputs,
    write_analysis_outputs,
    write_summary,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--analysis", action="store_true")
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

    if args.analysis:
        freeze_path = PROVENANCE / "DESIGN_V2_FREEZE.json"
        manifest_path = PROVENANCE / "SWEEP_MANIFEST.json"
        sweep_csv = ANALYSIS_OUT / "sweep_replicates.csv"
        if not freeze_path.exists():
            raise SystemExit("ANALYSIS summarizer: freeze record missing")
        if not manifest_path.exists():
            raise SystemExit("ANALYSIS summarizer: raw sweep manifest missing")
        if not sweep_csv.exists():
            raise SystemExit("ANALYSIS summarizer: sweep_replicates.csv missing")
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        records = load_records(sweep_csv)
        errors = validate_analysis_inputs(design, records, manifest, freeze)
        if errors:
            print("ANALYSIS summarizer REFUSING:")
            for err in errors:
                print(" -", err)
            return 2
        payload = summarize(design, records, source="ANALYSIS")
        if payload["analysis_seeds_used"] is not True:
            raise SystemExit("internal error: analysis_seeds_used is not True")
        if payload["source"] != "ANALYSIS":
            raise SystemExit("internal error: source is not ANALYSIS")
        status = write_analysis_outputs(design, records, payload, manifest)
        write_summary(payload, "ANALYSIS_SUMMARY")
        print(
            f"ANALYSIS summary written: records={len(records)} "
            f"NETWORK_SUPPORT_FINAL={status['NETWORK_SUPPORT_FINAL']['status']}"
        )
        return 0

    print("summarize_results.py: pass --fixtures, --smoke, or --analysis.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
