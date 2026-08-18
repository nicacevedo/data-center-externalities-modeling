"""Unit tests for CAMPD hourly gross generation = Gross Load (MW) * Operating Time."""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from prepare_oregon_generators import hourly_gross_generation_mwh, self_test


def test_full_hour_generation():
    load = pd.Series([100.0, 25.5])
    ot = pd.Series([1.0, 1.0])
    gen = hourly_gross_generation_mwh(load, ot)
    assert abs(gen.iloc[0] - 100.0) < 1e-12
    assert abs(gen.iloc[1] - 25.5) < 1e-12


def test_partial_hour_generation():
    load = pd.Series([100.0, 80.0, 60.0])
    ot = pd.Series([0.25, 0.5, 0.75])
    gen = hourly_gross_generation_mwh(load, ot)
    assert abs(gen.iloc[0] - 25.0) < 1e-12
    assert abs(gen.iloc[1] - 40.0) < 1e-12
    assert abs(gen.iloc[2] - 45.0) < 1e-12


def test_missing_operands_stay_missing():
    load = pd.Series([50.0, np.nan, 50.0])
    ot = pd.Series([np.nan, 1.0, 0.0])
    gen = hourly_gross_generation_mwh(load, ot)
    assert pd.isna(gen.iloc[0])
    assert pd.isna(gen.iloc[1])
    assert gen.iloc[2] == 0.0


if __name__ == "__main__":
    test_full_hour_generation()
    test_partial_hour_generation()
    test_missing_operands_stay_missing()
    self_test()
    print("PASS: tests/test_campd_generation.py")
