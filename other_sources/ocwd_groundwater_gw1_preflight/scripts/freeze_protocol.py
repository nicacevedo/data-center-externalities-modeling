#!/usr/bin/env python3
"""Freeze GW-1A data representations and holdout protocol before fitting."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.gw1a import freeze_protocol  # noqa: E402


if __name__ == "__main__":
    result = freeze_protocol()
    window = result["protocol_freeze"]["primary_window"]
    print(f"PROTOCOL_FROZEN: {window['start']} through {window['end']} ({window['months']} months)")
    print(f"SOURCE_INTEGRITY: {result['integrity']['status']}")

