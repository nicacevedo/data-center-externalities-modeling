"""Focused checks for the KS39 MADIS weather integration."""
from __future__ import annotations

import calendar
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from download_madis_ks39 import hour_key, hours_to_fetch  # noqa: E402
from madis_qc import QCR_VALIDITY, model_usable_scalar  # noqa: E402
from prepare_weather_ks39 import (  # noqa: E402
    SWITCH_LOCAL,
    TZ_LOCAL,
    station_pressure_from_altimeter_pa,
)


def test_resume_skips_completed_ok_and_not_found_hours():
    hours = pd.date_range("2019-07-15T00:00:00Z", periods=4, freq="h", tz="UTC")
    done = {
        hour_key(hours[0]): {"status": "ok"},
        hour_key(hours[1]): {"status": "not_found"},
        hour_key(hours[2]): {"status": "error", "error": "timeout"},
    }
    pending = hours_to_fetch(hours, done)
    keys = {hour_key(ts) for ts in pending}
    assert hour_key(hours[0]) not in keys
    assert hour_key(hours[1]) not in keys
    assert hour_key(hours[2]) in keys
    assert hour_key(hours[3]) in keys


def test_madis_qc_uses_documented_dd_and_validity_bit():
    assert model_usable_scalar(290.0, "V", 0)
    assert model_usable_scalar(290.0, "Z", 0)
    assert not model_usable_scalar(290.0, "X", 0)
    assert not model_usable_scalar(290.0, "B", 0)
    assert not model_usable_scalar(290.0, "Q", 0)
    assert not model_usable_scalar(290.0, "V", QCR_VALIDITY)
    assert not model_usable_scalar(float("nan"), "V", 0)
    assert not model_usable_scalar(290.0, "R", 0)


def test_icao_altimeter_to_station_pressure_is_derived_and_decreases_with_height():
    a = 101325.0
    p0 = station_pressure_from_altimeter_pa(a, 0.0)
    p991 = station_pressure_from_altimeter_pa(a, 991.0)
    assert abs(p0 - a) < 1e-6
    assert p991 < p0
    assert 85000 < p991 < 92000


def test_unique_report_key_after_correction_resolution():
    reports = ROOT / "data" / "raw" / "noaa_madis_ks39" / "ks39_metar_reports.csv.gz"
    if not reports.exists():
        return
    from prepare_weather_ks39 import load_raw_reports, resolve_reports

    z = resolve_reports(load_raw_reports())
    assert z["report_key"].is_unique
    assert not z.duplicated(["stationName", "timeObs", "rawMETAR"]).any()


def test_ks39_hourly_utc_key_unique_monotone():
    path = ROOT / "data" / "processed" / "weather_ks39_hourly.csv"
    if not path.exists():
        return
    h = pd.read_csv(path)
    h["timestamp_utc"] = pd.to_datetime(h["timestamp_utc"], utc=True)
    assert h["timestamp_utc"].is_unique
    assert h["timestamp_utc"].is_monotonic_increasing


def test_canonical_year_lengths_and_dst_preserve_utc_hours():
    path = ROOT / "data" / "processed" / "weather_hourly.csv"
    if not path.exists():
        return
    w = pd.read_csv(path)
    w["timestamp_utc"] = pd.to_datetime(w["timestamp_utc"], utc=True)
    w = w[(w.timestamp_utc >= "2011-01-01T00:00:00Z") & (w.timestamp_utc <= "2024-12-31T23:00:00Z")]
    assert w["timestamp_utc"].is_unique
    assert w["timestamp_utc"].is_monotonic_increasing
    for year, n in w.groupby(w.timestamp_utc.dt.year).size().items():
        expect = 8784 if calendar.isleap(int(year)) else 8760
        assert int(n) == expect, f"{year} has {n} hours, expected {expect}"
    # Fall-back 2016-11-06 America/Los_Angeles: two local 01:00 hours, unique UTC.
    loc = w["timestamp_utc"].dt.tz_convert(TZ_LOCAL)
    fb = loc[(loc.dt.year == 2016) & (loc.dt.month == 11) & (loc.dt.day == 6) & (loc.dt.hour == 1)]
    assert len(fb) == 2
    # Physical UTC hours are complete; local spring-forward is a 23-hour civil day.
    utc_spring = w[(w.timestamp_utc.dt.year == 2016) & (w.timestamp_utc.dt.month == 3) & (w.timestamp_utc.dt.day == 13)]
    assert len(utc_spring) == 24
    local_spring = w[(loc.dt.year == 2016) & (loc.dt.month == 3) & (loc.dt.day == 13)]
    assert len(local_spring) == 23
    local_fall = w[(loc.dt.year == 2016) & (loc.dt.month == 11) & (loc.dt.day == 6)]
    assert len(local_fall) == 25


def test_ks39_coordinates_and_units_plausible():
    path = ROOT / "data" / "processed" / "weather_ks39_hourly.csv"
    if not path.exists():
        return
    h = pd.read_csv(path)
    lat = float(h.latitude.median())
    lon = float(h.longitude.median())
    elev = float(h.elevation_m.median())
    assert abs(lat - 44.28) < 0.05
    assert abs(lon - (-120.90)) < 0.05
    assert abs(elev - 991.0) < 5
    t = h["t_db_C"].dropna()
    assert t.min() > -50
    assert t.max() < 50
    td = h["t_dew_C"].dropna()
    both = h.dropna(subset=["t_db_C", "t_dew_C"])
    assert (both.t_dew_C <= both.t_db_C + 0.3).all()
    rh = h["rh_pct"].dropna()
    assert (rh >= 0).all() and (rh <= 100).all()
    tw = h.dropna(subset=["t_db_C", "t_wb_C"])
    assert (tw.t_wb_C <= tw.t_db_C + 0.3).all()
    p = h["pressure_Pa"].dropna()
    assert (p > 70000).all() and (p < 105000).all()
    if "wind_m_s" in h:
        w = h["wind_m_s"].dropna()
        if len(w):
            assert (w >= 0).all()


def test_coverage_does_not_count_unavailable_archive_as_ks39_absent():
    path = ROOT / "outputs" / "ks39_coverage_annual.csv"
    if not path.exists():
        return
    a = pd.read_csv(path)
    assert "source_hours_unavailable" in a.columns
    assert "archive_hours_ks39_absent_file_ok" in a.columns
    # Absent-when-file-ok must never exceed file-ok hours.
    ok = a["source_hours_ok"].fillna(0)
    absent = a["archive_hours_ks39_absent_file_ok"].fillna(0)
    assert (absent <= ok + 1e-9).all()


def test_canonical_pre2015_is_krdm_and_august_2015_not_intermittent_ks39():
    path = ROOT / "data" / "processed" / "weather_hourly.csv"
    if not path.exists() or "weather_source" not in pd.read_csv(path, nrows=1).columns:
        return
    w = pd.read_csv(path)
    w["timestamp_utc"] = pd.to_datetime(w["timestamp_utc"], utc=True)
    w["timestamp_local"] = w["timestamp_utc"].dt.tz_convert(TZ_LOCAL)
    pre = w[w.timestamp_local < SWITCH_LOCAL]
    assert (pre.weather_source == "KRDM").all()
    aug = w[(w.timestamp_local.dt.year == 2015) & (w.timestamp_local.dt.month == 8)]
    if "weather_source" in aug:
        assert (aug.weather_source == "KRDM").all()


def test_electricity_closure_preserved():
    path = ROOT / "outputs" / "conditional_annual_compare.csv"
    if not path.exists():
        return
    a = pd.read_csv(path)
    resid = (a.electricity_mwh_model_closure - a.electricity_mwh_reported).abs()
    assert resid.max() < 1e-6
