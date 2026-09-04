#!/usr/bin/env python3
"""Acquire and hash the fixed official gridMET OCWD subset."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.gw1c import acquire_gridmet  # noqa: E402


if __name__ == "__main__":
    result = acquire_gridmet()
    print(f"status={result['status']}")
    print(f"period={result['actual_period'][0]}..{result['actual_period'][1]}")
    print(f"grid_cells={result['n_grid_cells']} rows={result['n_rows']}")
    print(f"raw_file_count={result['raw_file_count']} raw_total_bytes={result['raw_total_bytes']}")

