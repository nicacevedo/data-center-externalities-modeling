#!/usr/bin/env python3
"""V3 summarizer CLI. No gates. Pointwise intervals only."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import _bootstrap_path  # noqa: F401

from src_v3.design import MODULE_ROOT
from src_v3.summarize_v3 import summarize_records

def main() -> int:
    smoke = MODULE_ROOT / "outputs" / "smoke" / "SMOKE_V3_REPLICATES.csv"
    if not smoke.exists():
        raise SystemExit("no smoke replicates to summarize")
    with open(smoke, "r", encoding="utf-8", newline="") as handle:
        records = list(csv.DictReader(handle))
    # coerce numerics where possible
    coerced = []
    for row in records:
        out = dict(row)
        for k, v in row.items():
            if v == "":
                out[k] = float("nan")
                continue
            try:
                out[k] = float(v)
            except ValueError:
                pass
        coerced.append(out)
    payload = summarize_records(coerced)
    payload["source"] = "V3_SMOKE"
    payload["non_inferential"] = True
    out = MODULE_ROOT / "outputs" / "smoke" / "SMOKE_V3_SUMMARIZER.json"
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
