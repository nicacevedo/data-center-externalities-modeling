"""Finite-input/output contracts for the Prineville gray-box."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from prineville_graybox import Params, simulate  # noqa: E402


def _weather(n: int = 24, nan_col: str | None = None) -> pd.DataFrame:
    idx = pd.date_range("2018-07-01", periods=n, freq="h", tz="UTC")
    df = pd.DataFrame(
        {
            "timestamp_utc": idx,
            "t_db_C": np.linspace(18.0, 32.0, n),
            "t_wb_C": np.linspace(12.0, 18.0, n),
            "rh_pct": np.linspace(25.0, 55.0, n),
            "pressure_Pa": np.full(n, 90100.0),
        }
    )
    if nan_col:
        df.loc[3, nan_col] = np.nan
    return df


def test_finite_weather_yields_finite_nonnegative_outputs():
    out = simulate(_weather(), 10.0)
    for col in ("p_it_mw", "p_fan_mw", "p_other_mw", "p_evap_aux_mw", "p_fac_mw", "t_supply_C", "evap_water_m3_per_h"):
        x = out[col].to_numpy(float)
        assert np.isfinite(x).all(), col
        assert (x >= -1e-12).all(), col
    pit = out["p_it_mw"].to_numpy(float)
    pue = out["pue"].to_numpy(float)
    assert np.isfinite(pue[pit > 0]).all()


def test_facility_power_and_pue_identities():
    out = simulate(_weather(), 8.0)
    recon = out.p_it_mw + out.p_fan_mw + out.p_other_mw + out.p_evap_aux_mw
    assert np.allclose(out.p_fac_mw, recon)
    pit = out.p_it_mw.to_numpy(float)
    assert np.allclose(out.pue.to_numpy(float), out.p_fac_mw.to_numpy(float) / pit)


def test_nonfinite_required_weather_fails_explicitly():
    for col in ("t_db_C", "t_wb_C", "rh_pct", "pressure_Pa"):
        with pytest.raises(ValueError, match=col):
            simulate(_weather(nan_col=col), 5.0)


def test_missing_weather_is_not_treated_as_zero_spray():
    """A NaN driver must fail before auxiliary power can become a silent zero."""
    w = _weather(nan_col="t_wb_C")
    with pytest.raises(ValueError, match="Non-finite required weather"):
        simulate(w, 5.0)
