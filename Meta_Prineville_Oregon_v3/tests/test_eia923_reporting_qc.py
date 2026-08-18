"""QC tests: EIA-923 annual respondents are not treated as observed monthly reporters."""
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from oregon_generation_qc import (
    classify_annual_reconciliation,
    is_annual_only_eia923,
    is_observed_monthly_eia923,
    monthly_generation_basis,
    monthly_outlier_is_primary_conflict,
    monthly_ratio_is_extreme,
    normalize_reporting_frequency,
)
from oregon_exception_report import generation_outliers


def _audit_row(plant_id: int) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "camd_facility_id": plant_id,
                "camd_unit_id": "GT1",
                "eia_plant_id": plant_id,
                "eia_generator_id": "GT1",
                "mapping_cardinality": "one_to_one",
                "match_method": "exact",
                "match_type": "one_to_one|exact",
            }
        ]
    )


def _compare_row(plant_id: int, year: int, month: int, frequency: str, ratio: float, campd: float, eia: float) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "plant_id": plant_id,
                "year": year,
                "month": month,
                "plant_name_campd": "Test Plant",
                "plant_name": "Test Plant",
                "reporting_frequency": frequency,
                "monthly_generation_basis": monthly_generation_basis(frequency),
                "campd_gross_generation_mwh": campd,
                "generation_mwh": eia,
                "r_campd_over_eia923": ratio,
                "join_status": "both",
                "n_reporting_units": 4,
                "n_hours": 100,
            }
        ]
    )


def test_annual_frequency_is_not_observed_monthly():
    assert normalize_reporting_frequency("A") == "A"
    assert is_annual_only_eia923("A")
    assert not is_observed_monthly_eia923("A")
    assert monthly_generation_basis("A") == "eia_allocated_from_annual"
    assert not monthly_outlier_is_primary_conflict("A")


def test_monthly_and_am_remain_observed_monthly():
    for freq in ("M", "AM", "AM/A"):
        assert is_observed_monthly_eia923(freq)
        assert not is_annual_only_eia923(freq)
        assert monthly_generation_basis(freq) == "respondent_monthly"
        assert monthly_outlier_is_primary_conflict(freq)


def test_annual_reconciliation_is_primary_qc_for_annual_respondents():
    assert classify_annual_reconciliation(29027.5, 28442.0, "A") == "ok"
    assert classify_annual_reconciliation(32747.33, 27048.001, "A") == "annual_comparability_warning"
    assert monthly_ratio_is_extreme(10.42)
    rows = generation_outliers(
        _compare_row(99999, 2011, 5, "A", 10.42, 6716.92, 644.412),
        _audit_row(99999),
    )
    assert len(rows) == 1
    assert rows[0]["root_cause_class"] == "coverage_limitation"
    assert rows[0]["needs_manual_review"] is False
    assert rows[0]["root_cause_id"] == "eia923_annual_respondent_monthly_not_observed"


def test_monthly_reporters_remain_eligible_for_monthly_discrepancy_qc():
    rows = generation_outliers(
        _compare_row(88888, 2015, 7, "M", 12.6, 1000.0, 79.0),
        _audit_row(88888),
    )
    assert len(rows) == 1
    assert rows[0]["root_cause_class"] == "unresolved_source_conflict"
    assert rows[0]["needs_manual_review"] is True


def test_klamath_annual_reporter_behavior_without_plant_specific_logic():
    src_exception = (SRC / "oregon_exception_report.py").read_text()
    src_prepare = (SRC / "prepare_oregon_generators.py").read_text()
    src_qc = (SRC / "oregon_generation_qc.py").read_text()
    for text in (src_exception, src_prepare, src_qc):
        assert "55544" not in text
        assert "plant_55544" not in text
        assert "oregon_plant_55544_generation_outlier_diagnosis.csv" not in text

    klamath = _compare_row(55544, 2011, 5, "A", 10.423332, 6716.92, 644.412)
    rows_a = generation_outliers(klamath, _audit_row(55544))
    assert len(rows_a) == 1
    assert rows_a[0]["needs_manual_review"] is False
    assert rows_a[0]["root_cause_class"] == "coverage_limitation"

    klamath_as_monthly = klamath.copy()
    klamath_as_monthly["reporting_frequency"] = "M"
    klamath_as_monthly["monthly_generation_basis"] = monthly_generation_basis("M")
    rows_m = generation_outliers(klamath_as_monthly, _audit_row(55544))
    assert rows_m[0]["needs_manual_review"] is True
    assert rows_m[0]["root_cause_class"] == "unresolved_source_conflict"


if __name__ == "__main__":
    test_annual_frequency_is_not_observed_monthly()
    test_monthly_and_am_remain_observed_monthly()
    test_annual_reconciliation_is_primary_qc_for_annual_respondents()
    test_monthly_reporters_remain_eligible_for_monthly_discrepancy_qc()
    test_klamath_annual_reporter_behavior_without_plant_specific_logic()
    print("PASS: tests/test_eia923_reporting_qc.py")
