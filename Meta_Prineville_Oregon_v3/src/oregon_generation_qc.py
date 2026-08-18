"""EIA-923 reporting-frequency and CAMPD/EIA-923 generation QC helpers.

CAMPD gross generation and EIA-923 net generation are different boundaries.
They are never rescaled to force agreement.

EIA Form 923 / instructions: monthly sample plants report monthly; annual
respondents other than the listed monthly-on-annual exceptions report a
calendar-year total and do not break it down by month. Published monthly
Netgen columns for frequency=A plants are therefore not respondent monthly
observations.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ANNUAL_RATIO_LOW = 0.85
ANNUAL_RATIO_HIGH = 1.15
MONTHLY_EXTREME_HIGH = 5.0
MONTHLY_EXTREME_LOW = 0.05

OBSERVED_MONTHLY_FREQUENCIES = frozenset({"M", "AM", "AM/A"})
ANNUAL_ONLY_FREQUENCIES = frozenset({"A"})


def normalize_reporting_frequency(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip().upper().replace(" ", "")
    if not text or text in {"NAN", "NONE", "<NA>", "NAT"}:
        return ""
    aliases = {
        "A": "A",
        "ANNUAL": "A",
        "M": "M",
        "MONTHLY": "M",
        "AM": "AM",
        "A/M": "AM",
        "AM/A": "AM/A",
        "A/AM": "AM/A",
    }
    return aliases.get(text, text)


def is_observed_monthly_eia923(frequency) -> bool:
    """True when EIA-923 monthly columns are respondent-provided monthly values."""
    return normalize_reporting_frequency(frequency) in OBSERVED_MONTHLY_FREQUENCIES


def is_annual_only_eia923(frequency) -> bool:
    """True when the respondent files a calendar-year total only (frequency=A)."""
    return normalize_reporting_frequency(frequency) in ANNUAL_ONLY_FREQUENCIES


def monthly_generation_basis(frequency) -> str:
    freq = normalize_reporting_frequency(frequency)
    if freq == "A":
        return "eia_allocated_from_annual"
    if freq in OBSERVED_MONTHLY_FREQUENCIES:
        return "respondent_monthly"
    return "unknown"


def annual_ratio(campd_mwh, eia923_mwh):
    campd = pd.to_numeric(pd.Series([campd_mwh]), errors="coerce").iloc[0]
    eia = pd.to_numeric(pd.Series([eia923_mwh]), errors="coerce").iloc[0]
    if pd.isna(campd) or pd.isna(eia) or eia == 0:
        return np.nan
    return float(campd / eia)


def relative_difference(campd_mwh, eia923_mwh):
    campd = pd.to_numeric(pd.Series([campd_mwh]), errors="coerce").iloc[0]
    eia = pd.to_numeric(pd.Series([eia923_mwh]), errors="coerce").iloc[0]
    if pd.isna(campd) or pd.isna(eia) or eia == 0:
        return np.nan
    return float((campd - eia) / eia)


def classify_annual_reconciliation(campd_mwh, eia923_mwh, frequency=None) -> str:
    """Primary generation QC label for a plant-year. Does not rescale either source."""
    campd = pd.to_numeric(pd.Series([campd_mwh]), errors="coerce").iloc[0]
    eia = pd.to_numeric(pd.Series([eia923_mwh]), errors="coerce").iloc[0]
    campd_missing = pd.isna(campd)
    eia_missing = pd.isna(eia)
    if campd_missing and eia_missing:
        return "not_comparable"
    if campd_missing:
        return "eia923_only"
    if eia_missing:
        return "campd_only"
    if campd == 0 and eia == 0:
        return "ok"
    if eia == 0:
        return "not_comparable"
    ratio = campd / eia
    if ANNUAL_RATIO_LOW <= ratio <= ANNUAL_RATIO_HIGH:
        return "ok"
    return "annual_comparability_warning"


def annual_reconciliation_notes(qc_status: str, frequency, campd_heat=None, eia_fuel=None) -> str:
    freq = normalize_reporting_frequency(frequency)
    basis = monthly_generation_basis(freq)
    parts = []
    if freq == "A":
        parts.append(
            "EIA-923 annual respondent (Plant Frame frequency=A). "
            "Published monthly Netgen is not a respondent monthly observation; "
            "primary CAMPD/EIA-923 generation QC is the annual total."
        )
    elif freq in OBSERVED_MONTHLY_FREQUENCIES:
        parts.append(
            f"EIA-923 respondent monthly generation (Plant Frame frequency={freq}). "
            "Monthly CAMPD/EIA-923 comparison remains eligible."
        )
    elif freq:
        parts.append(f"EIA-923 Plant Frame frequency={freq}; monthly_generation_basis={basis}.")
    else:
        parts.append("EIA-923 Plant Frame frequency missing for this plant-year.")

    if qc_status == "ok":
        parts.append(
            f"Annual CAMPD gross / EIA-923 net is inside the documented "
            f"{ANNUAL_RATIO_LOW:.2f}-{ANNUAL_RATIO_HIGH:.2f} envelope "
            "(gross vs net plus ordinary reporting noise). Sources were not rescaled."
        )
    elif qc_status == "annual_comparability_warning":
        parts.append(
            f"Annual CAMPD gross / EIA-923 net is outside the documented "
            f"{ANNUAL_RATIO_LOW:.2f}-{ANNUAL_RATIO_HIGH:.2f} envelope. "
            "Monthly allocation cannot explain an annual gap. "
            "Values were not rescaled; this is a comparability warning, not a correction."
        )
    elif qc_status == "campd_only":
        parts.append("CAMPD generation present; EIA-923 net generation missing.")
    elif qc_status == "eia923_only":
        parts.append("EIA-923 net generation present; CAMPD generation missing.")
    elif qc_status == "not_comparable":
        parts.append("Annual generation is not comparable (missing or zero EIA-923 denominator).")

    heat = pd.to_numeric(pd.Series([campd_heat]), errors="coerce").iloc[0]
    fuel = pd.to_numeric(pd.Series([eia_fuel]), errors="coerce").iloc[0]
    if pd.notna(heat) or pd.notna(fuel):
        parts.append(f"CAMPD heat input mmBtu={heat}; EIA-923 annual fuel mmBtu={fuel}.")
    return " ".join(parts)


def monthly_ratio_is_extreme(ratio) -> bool:
    r = pd.to_numeric(pd.Series([ratio]), errors="coerce").iloc[0]
    if pd.isna(r):
        return False
    return bool(r > MONTHLY_EXTREME_HIGH or r < MONTHLY_EXTREME_LOW)


def monthly_outlier_is_primary_conflict(frequency) -> bool:
    """Monthly extreme ratios are unresolved only for respondent monthly reporters."""
    return is_observed_monthly_eia923(frequency)
