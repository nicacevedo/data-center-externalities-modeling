#!/usr/bin/env python3
"""Emit Block D factorial contrasts from smoke or analysis records."""

from __future__ import annotations

import csv
import json

import _bootstrap_path  # noqa: F401

from src_v3.design import MODULE_ROOT
from src_v3.summarize_v3 import block_d_factorial


def main() -> int:
    path = MODULE_ROOT / "outputs" / "smoke" / "SMOKE_V3_REPLICATES.csv"
    if not path.exists():
        raise SystemExit("no records")
    with open(path, "r", encoding="utf-8", newline="") as handle:
        records = list(csv.DictReader(handle))
    coerced = []
    for row in records:
        out = dict(row)
        for k, v in row.items():
            try:
                out[k] = float(v)
            except (ValueError, TypeError):
                pass
        coerced.append(out)
    payload = block_d_factorial(coerced)
    payload["non_inferential"] = True
    payload["source"] = "V3_SMOKE"
    out = MODULE_ROOT / "outputs" / "smoke" / "BLOCK_D_FACTORIAL_SMOKE.json"
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
