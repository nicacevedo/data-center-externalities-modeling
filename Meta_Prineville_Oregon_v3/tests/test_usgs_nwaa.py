"""Unit-conversion and identifier checks for the USGS NWAA module."""
from __future__ import annotations

import calendar
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from usgs_nwaa_config import (
    M3_PER_MILLION_US_GALLONS,
    MM_OVER_KM2_TO_M3,
    pad_huc12,
)


def test_pad_huc12_preserves_twelve_characters():
    assert pad_huc12("170703051002") == "170703051002"
    assert pad_huc12(170703051002) == "170703051002"
    assert len(pad_huc12("170703051002")) == 12


def test_mm_to_m3_identity():
    # 1 mm over 1 km2 = 1000 m3
    assert 1.0 * 1.0 * MM_OVER_KM2_TO_M3 == 1000.0
    # 2 mm over 69.22 km2
    assert abs(2.0 * 69.22 * MM_OVER_KM2_TO_M3 - 138440.0) < 1e-9


def test_mgd_to_m3_uses_actual_month_length():
    feb_leap = 1.0 * calendar.monthrange(2020, 2)[1] * M3_PER_MILLION_US_GALLONS
    feb_common = 1.0 * calendar.monthrange(2019, 2)[1] * M3_PER_MILLION_US_GALLONS
    jan = 1.0 * 31 * M3_PER_MILLION_US_GALLONS
    assert calendar.monthrange(2020, 2)[1] == 29
    assert calendar.monthrange(2019, 2)[1] == 28
    assert abs(feb_leap - 29 * 3785.411784) < 1e-9
    assert abs(feb_common - 28 * 3785.411784) < 1e-9
    assert abs(jan - 31 * 3785.411784) < 1e-9
    assert feb_leap > feb_common


def test_iwa_identity_example():
    strflow = 4.16668876866631
    consum = 0.0279983072986122
    availab = 4.1386904613677
    assert abs(availab - (strflow - consum)) < 1e-12
