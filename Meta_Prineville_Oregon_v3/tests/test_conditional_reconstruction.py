"""Conditional reconstruction contracts: closure, train-only scale, finite weather."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import conditional_reconstruction as cr  # noqa: E402


def _write_mini_inputs(tmp: Path, nan_weather: bool = False, holdout_water: float = 500.0) -> None:
    hours = 24
    rows = []
    for year in (2020, 2021, 2022, 2023, 2024):
        idx = pd.date_range(f"{year}-07-01", periods=hours, freq="h", tz="UTC")
        tdb = np.linspace(20.0, 30.0, hours) + 0.1 * (year - 2020)
        rec = pd.DataFrame(
            {
                "timestamp_utc": idx,
                "year_local": year,
                "t_db_C": tdb,
                "t_wb_C": tdb - 8.0,
                "rh_pct": np.full(hours, 40.0),
                "pressure_Pa": np.full(hours, 90100.0),
            }
        )
        if nan_weather and year == 2021:
            rec.loc[2, "t_db_C"] = np.nan
        rows.append(rec)
    weather = pd.concat(rows, ignore_index=True)
    weather.to_csv(tmp / "weather_hourly.csv", index=False)

    water = {2020: 200.0, 2021: 220.0, 2022: 250.0, 2023: holdout_water, 2024: holdout_water + 50.0}
    targets = pd.DataFrame(
        {
            "year": [2020, 2021, 2022, 2023, 2024],
            "hours_in_year": hours,
            "electricity_mwh_reported": [1000.0, 1100.0, 1200.0, 1300.0, 1400.0],
            "water_withdrawal_m3_reported": [water[y] for y in (2020, 2021, 2022, 2023, 2024)],
        }
    )
    targets.to_csv(tmp / "meta_prineville_annual.csv", index=False)


def test_annual_electricity_closure_is_calibration_not_prediction(tmp_path, monkeypatch):
    _write_mini_inputs(tmp_path)
    monkeypatch.setattr(cr, "WEATHER", tmp_path / "weather_hourly.csv")
    monkeypatch.setattr(cr, "TARGETS", tmp_path / "meta_prineville_annual.csv")
    hourly, annual, model = cr.reconstruct(train_end_year=2022)
    err = (annual.electricity_mwh_model_closure - annual.electricity_mwh_reported).abs()
    assert float(err.max()) < 1e-8
    assert "NOT observed hourly IT telemetry" in hourly.it_power_provenance.iloc[0]
    assert model["kind"] == "global"
    assert (annual.loc[annual.year.le(2022), "split"] == "train").all()
    assert (annual.loc[annual.year.ge(2023), "split"] == "holdout").all()


def test_water_scale_does_not_use_holdout_observations(tmp_path, monkeypatch):
    _write_mini_inputs(tmp_path, holdout_water=500.0)
    monkeypatch.setattr(cr, "WEATHER", tmp_path / "weather_hourly.csv")
    monkeypatch.setattr(cr, "TARGETS", tmp_path / "meta_prineville_annual.csv")
    _, _, m1 = cr.reconstruct(train_end_year=2022)
    _write_mini_inputs(tmp_path, holdout_water=50000.0)
    _, _, m2 = cr.reconstruct(train_end_year=2022)
    assert m1["scale"] == pytest.approx(m2["scale"], rel=1e-12)


def test_nonfinite_weather_fails_before_annual_sums(tmp_path, monkeypatch):
    _write_mini_inputs(tmp_path, nan_weather=True)
    monkeypatch.setattr(cr, "WEATHER", tmp_path / "weather_hourly.csv")
    monkeypatch.setattr(cr, "TARGETS", tmp_path / "meta_prineville_annual.csv")
    with pytest.raises(ValueError, match="Non-finite required weather driver t_db_C year=2021"):
        cr.reconstruct(train_end_year=2022)
