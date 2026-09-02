"""Apply frozen ESIF F4 cooling (and F4 pumps) polynomials. Do not refit."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from fc3_paths import ESIF_FO


def load_selected() -> dict:
    return json.loads((ESIF_FO / "analysis" / "COMPONENT_SELECTED_MODELS.json").read_text())


def _z(x, spec):
    return (np.asarray(x, float) - spec["mean"]) / spec["std"]


def predict_f4_cooling(it_kw, tdb_c, twb_c, selected: dict | None = None) -> np.ndarray:
    sel = selected or load_selected()
    cool = sel["cooling_kw"]
    if cool["selected_spec"] != "F4":
        raise ValueError("frozen cooling spec is not F4")
    coef = np.asarray(cool["coef"], float)
    sc = cool["scaler"]
    zit = _z(it_kw, sc["it_power_kw"])
    ztdb = _z(tdb_c, sc["tdb_c"])
    ztwb = _z(twb_c, sc["twb_c"])
    ones = np.ones_like(zit)
    X = np.column_stack([ones, zit, ztdb, ztwb, zit**2, ztdb**2, ztwb**2, zit * ztwb])
    return X @ coef


def predict_f0_hvac(n: int, selected: dict | None = None) -> np.ndarray:
    sel = selected or load_selected()
    hvac = sel["hvac_kw"]
    if hvac["selected_spec"] != "F0":
        raise ValueError("frozen HVAC spec is not F0")
    return np.full(n, float(hvac["coef"][0]))
