#!/usr/bin/env python3
"""V3 summarizer CLI. No gates. Pointwise intervals only.

Pass 2 usage (zero source-code changes):

    python scripts_v3/summarize_v3.py --analysis

requires the frozen ANALYSIS replicate table already written by `run_v3.py`.
This script never launches replicates.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import _bootstrap_path  # noqa: F401

from src_v3.design import MODULE_ROOT, code_hash, design_hash
from src_v3.summarize_v3 import summarize_analysis, summarize_records

ANALYSIS_CSV = MODULE_ROOT / "outputs" / "analysis" / "V3_ANALYSIS_REPLICATES.csv"
ANALYSIS_OUT = MODULE_ROOT / "outputs" / "analysis" / "V3_ANALYSIS_SUMMARY.json"
SMOKE_CSV = MODULE_ROOT / "outputs" / "smoke" / "SMOKE_V3_REPLICATES.csv"
SMOKE_OUT = MODULE_ROOT / "outputs" / "smoke" / "SMOKE_V3_SUMMARIZER.json"
FREEZE_JSON = MODULE_ROOT / "outputs" / "provenance" / "DESIGN_V3_FREEZE.json"
BENCHMARK_JSON = MODULE_ROOT / "outputs" / "benchmarks" / "BENCHMARKS_V3.json"


def _coerce(records: list[dict]) -> list[dict]:
    coerced = []
    for row in records:
        out = dict(row)
        for key, value in row.items():
            if value == "":
                out[key] = float("nan")
                continue
            try:
                out[key] = float(value)
            except (TypeError, ValueError):
                pass
        coerced.append(out)
    return coerced


def _load_csv(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return _coerce(list(csv.DictReader(handle)))


def _load_benchmarks() -> tuple[dict[str, dict] | None, list[dict] | None]:
    if not BENCHMARK_JSON.exists():
        return None, None
    with open(BENCHMARK_JSON, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    rows = {str(r["cell_id"]): r for r in payload.get("rows", [])}
    return (rows or None), (payload.get("convergence") or None)


def _require_matching_freeze() -> dict:
    if not FREEZE_JSON.exists():
        raise SystemExit("missing DESIGN_V3_FREEZE.json; run freeze_protocol_v3.py")
    with open(FREEZE_JSON, "r", encoding="utf-8") as handle:
        freeze = json.load(handle)
    live_design = design_hash()
    live_code = code_hash()
    if live_design != freeze.get("V3_DESIGN_HASH"):
        raise SystemExit(
            f"V3_DESIGN_HASH mismatch: live={live_design} frozen={freeze.get('V3_DESIGN_HASH')}"
        )
    if live_code != freeze.get("V3_CODE_HASH"):
        raise SystemExit(
            f"V3_CODE_HASH mismatch: live={live_code} frozen={freeze.get('V3_CODE_HASH')}"
        )
    return freeze


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--analysis",
        action="store_true",
        help="summarize frozen V3 ANALYSIS replicates (does not run any replicate)",
    )
    args = parser.parse_args(argv)

    if args.analysis:
        freeze = _require_matching_freeze()
        if not ANALYSIS_CSV.exists():
            raise SystemExit(
                "no ANALYSIS replicates on disk; Pass 2 must run scripts_v3/run_v3.py "
                "with the authorization token first. This summarizer does not launch replicates."
            )
        records = _load_csv(ANALYSIS_CSV)
        benchmarks, convergence = _load_benchmarks()
        payload = summarize_analysis(
            records, benchmarks=benchmarks, convergence=convergence
        )
        payload["source"] = "V3_ANALYSIS"
        payload["non_inferential"] = False
        payload["V3_DESIGN_HASH"] = freeze["V3_DESIGN_HASH"]
        payload["V3_CODE_HASH"] = freeze["V3_CODE_HASH"]
        ANALYSIS_OUT.parent.mkdir(parents=True, exist_ok=True)
        with open(ANALYSIS_OUT, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)
            handle.write("\n")
        print("wrote", ANALYSIS_OUT)
        return 0

    if not SMOKE_CSV.exists():
        raise SystemExit("no smoke replicates to summarize")
    records = _load_csv(SMOKE_CSV)
    benchmarks, convergence = _load_benchmarks()
    payload = summarize_records(records, benchmarks=benchmarks, convergence=convergence)
    payload["source"] = "V3_SMOKE"
    payload["non_inferential"] = True
    SMOKE_OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(SMOKE_OUT, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)
        handle.write("\n")
    print("wrote", SMOKE_OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
