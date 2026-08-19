"""Official NOAA MADIS surface QC semantics.

Source: https://madis.ncep.noaa.gov/madis_sfc_qc_notes.shtml
(MADIS Meteorological Surface Quality Control Checks, last updated 15 March 2017).

Do not infer bit meanings from numeric values in a file. These constants match
the published bitmask table.
"""

# QC data descriptor (DD / QCD summary character)
DD_NO_QC = "Z"  # Preliminary, no QC
DD_COARSE = "C"  # Coarse pass, passed level 1
DD_SCREENED = "S"  # Screened, passed levels 1 and 2
DD_VERIFIED = "V"  # Verified, passed levels 1, 2, and 3
DD_REJECTED = "X"  # Rejected/erroneous, failed level 1
DD_QUESTIONED = "Q"  # Questioned, passed level 1, failed 2 or 3
DD_SUBJECTIVE_GOOD = "G"
DD_SUBJECTIVE_BAD = "B"

# Bitmask for QC Applied (QCA) and QC Results (QCR). Decimal values from NOAA.
# QCA bit=1 => check was applied. QCR bit=1 => check was applied AND failed.
QCR_MASTER = 1  # any failure if set in QCR; any check applied if set in QCA
QCR_VALIDITY = 2  # level 1 validity / gross-range
QCR_RESERVED_3 = 4
QCR_INTERNAL_CONSISTENCY = 8  # level 2
QCR_TEMPORAL_CONSISTENCY = 16  # level 2
QCR_STATISTICAL_SPATIAL = 32  # level 2
QCR_SPATIAL_CONSISTENCY = 64  # level 3

HARD_INVALID_DD = {DD_REJECTED, DD_SUBJECTIVE_BAD}
MODEL_USABLE_DD = {DD_COARSE, DD_SCREENED, DD_VERIFIED, DD_SUBJECTIVE_GOOD, DD_NO_QC}

# ICA/ICR are MADIS ingest-check words. NOAA's published surface QC notes document
# QCA/QCR/DD, not the ICA/ICR bit layout. Preserve ICA/ICR; do not invent bits.


def _as_int(value, default=0) -> int:
    try:
        if value is None:
            return default
        if isinstance(value, float) and value != value:  # NaN
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def dd_char(value) -> str:
    if value is None:
        return ""
    s = str(value).strip().upper()
    if s in {"NAN", "NONE", ""}:
        return ""
    return s[:1]


def validity_failed(qcr) -> bool:
    """True if the documented level-1 validity bit failed (QCR bit 2)."""
    return (_as_int(qcr) & QCR_VALIDITY) != 0


def any_qc_failed(qcr) -> bool:
    """True if the documented master-check bit is set in QCR."""
    return (_as_int(qcr) & QCR_MASTER) != 0


def model_usable_series(values, dd, qcr):
    """Vectorized model_usable_scalar for pandas Series."""
    import numpy as np
    import pandas as pd

    v = pd.to_numeric(values, errors="coerce")
    d = dd.fillna("").astype(str).str.strip().str.upper().str[:1]
    d = d.replace({"NAN": "", "NONE": "", "NAT": ""})
    q = pd.to_numeric(qcr, errors="coerce").fillna(0).astype(np.int64)
    ok = v.notna() & np.isfinite(v.to_numpy(dtype=float, na_value=np.nan))
    ok &= ~d.isin(HARD_INVALID_DD)
    ok &= (q.to_numpy() & QCR_VALIDITY) == 0
    ok &= ~d.eq(DD_QUESTIONED)
    empty = d.eq("")
    ok &= empty | d.isin(MODEL_USABLE_DD)
    return ok


def model_usable_scalar(value, dd, qcr) -> bool:
    """Whether a scalar observation may enter model hourly aggregates.

    Hard-invalid: NOAA DD 'X' (failed level 1) or 'B' (subjective bad), or the
    validity bit set in QCR. Questioned 'Q' (failed level 2/3) is excluded from
    model use but retained in the raw table. Preliminary 'Z' is allowed after
    physical-range checks in the caller.
    """
    import math

    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(v):
        return False
    d = dd_char(dd)
    if d in HARD_INVALID_DD:
        return False
    if validity_failed(qcr):
        return False
    if d == DD_QUESTIONED:
        return False
    if d and d not in MODEL_USABLE_DD:
        return False
    return True
