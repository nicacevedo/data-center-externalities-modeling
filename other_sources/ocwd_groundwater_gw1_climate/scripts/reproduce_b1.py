#!/usr/bin/env python3
"""Run the mandatory frozen-GW-1A B1 reproduction gate."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.gw1c import reproduce_b1_gate  # noqa: E402


if __name__ == "__main__":
    result = reproduce_b1_gate(write_output=True)
    print(f"B1_REPRODUCTION={result['status']}")

