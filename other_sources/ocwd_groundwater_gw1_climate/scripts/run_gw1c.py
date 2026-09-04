#!/usr/bin/env python3
"""Run the deterministic GW-1C benchmark after climate acquisition."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.gw1c import run_gw1c  # noqa: E402


if __name__ == "__main__":
    result = run_gw1c()
    for key in [
        "GW1C_STATUS", "CLIMATE_INCREMENTAL_SKILL",
        "PRADO_AFTER_CLIMATE_SKILL", "GW1B_BACKGROUND_MODEL",
        "GW1B_DATA_STATUS",
    ]:
        print(f"{key}={result[key]}")

