#!/usr/bin/env python3
"""Run frozen GW-1A B0-B3 OOS comparisons."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.gw1a import run_benchmarks  # noqa: E402


if __name__ == "__main__":
    result = run_benchmarks()
    for key in [
        "GW1A_STATUS", "STRONGEST_NO_PUMPING_BASELINE",
        "PUBLIC_HYDROLOGIC_INCREMENTAL_SKILL",
        "TEMPORAL_PREDICTION_DIFFICULTY",
        "SPATIAL_GENERALIZATION_DIFFICULTY", "READY_FOR_GW1B",
    ]:
        print(f"{key}={result[key]}")

