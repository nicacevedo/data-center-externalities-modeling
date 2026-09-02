"""Focused tests for ESIF heat-rejection → conditioning-water / WUE.

Does not refit CPU, H100, facility-overhead, Prineville, or Meta.
Does not treat electrical HVAC/cooling kW as thermal heat rejection.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path

import pandas as pd

HW = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HW / "scripts"))
from heat_water_paths import (  # noqa: E402
    ANALYSIS,
    CPU_FREEZE,
    CPU_FREEZE_SHA256,
    CPU_STATUS,
    CPU_STATUS_SHA256,
    DATA_PROCESSED,
    DOCS,
    FIGURES,
    FO_LAYER_FREEZE,
    FO_LAYER_FREEZE_SHA256,
    FO_STATUS,
    FO_STATUS_SHA256,
    H100_FREEZE,
    H100_FREEZE_SHA256,
    L_PER_M3,
    MANIFESTS,
    PDF_66690,
    PDF_72196,
    POWER_PARQUET,
    POWER_SHA256,
    README_SHA256,
    ROUNDING_WATER_M3_TOL,
    SICKINGER_OPERATIONAL_CAPTION_DATE,
    SOURCES,
    TSC_DB_THRESHOLD_C,
    TSC_DB_THRESHOLD_F,
    TSC_FIRST_YEAR_START,
    TSC_PRE_END_INCLUSIVE,
    TSC_PRE_START,
    TSC_TRANSITION_MONTH,
    US_GAL_PER_M3,
    WEATHER_PARQUET,
    WEATHER_SHA256,
    ESIF_README,
)

SCRIPTS = HW / "scripts"
FORBIDDEN_FIT = ("LightGBM", "XGBoost", "Optuna", "RandomForest", "train_test_split")
PRINEVILLE_MARKERS = ("prineville_graybox", "Meta_Prineville", "2023_2024_water")
META_WATER_MARKERS = ("meta_2023", "meta_2024", "holdout_water")


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _j(rel: Path) -> dict:
    return json.loads(rel.read_text())


def test_upstream_freeze_hashes_unchanged():
    assert _sha(POWER_PARQUET) == POWER_SHA256
    assert _sha(WEATHER_PARQUET) == WEATHER_SHA256
    assert _sha(ESIF_README) == README_SHA256
    assert _sha(CPU_STATUS) == CPU_STATUS_SHA256
    assert _sha(CPU_FREEZE) == CPU_FREEZE_SHA256
    assert _sha(H100_FREEZE) == H100_FREEZE_SHA256
    assert _sha(FO_STATUS) == FO_STATUS_SHA256
    assert _sha(FO_LAYER_FREEZE) == FO_LAYER_FREEZE_SHA256
    init = _j(MANIFESTS / "HEAT_WATER_INITIAL_STATE.json")
    assert init["cpu"]["refit"] is False
    assert init["h100"]["refit"] is False
    assert init["facility_overhead"]["read_only"] is True
    assert set(init["cannot_modify"]) >= {
        "CPU", "H100", "IT-power", "facility-overhead", "Prineville", "Meta",
    }


def test_thermosyphon_epoch_unchanged():
    ep = _j(MANIFESTS / "THERMOSYPHON_EPOCH_FREEZE.json")
    assert ep["common_electrical_weather_start"] == TSC_PRE_START
    assert ep["pre_tsc_available"] == f"{TSC_PRE_START} through {TSC_PRE_END_INCLUSIVE}"
    assert ep["commissioning_transition"] == TSC_TRANSITION_MONTH
    assert ep["sickinger_figure3_operational_date"] == SICKINGER_OPERATIONAL_CAPTION_DATE
    assert ep["use_2016_08_16_as_fitted_breakpoint"] is False
    assert ep["first_full_operating_year"].startswith(TSC_FIRST_YEAR_START)
    assert ep["new_intervention_date_not_estimated"] is True
    assert TSC_DB_THRESHOLD_C == 9.4
    assert TSC_DB_THRESHOLD_F == 49.0


def test_source_hashes():
    prov = _j(MANIFESTS / "WATER_SOURCE_PROVENANCE.json")
    by_id = {r["source_id"]: r for r in prov["resources"] if "source_id" in r}
    assert by_id["SICKINGER_72196"]["sha256"] == _sha(PDF_72196)
    assert by_id["CARTER_66690"]["sha256"] == _sha(PDF_66690)
    assert by_id["SICKINGER_72196"]["doi"] == "10.2172/1471661"
    assert by_id["CARTER_66690"]["doi"] == "10.2172/1343488"
    assert by_id["SICKINGER_72196"]["embedded_supplemental_files"] == 0
    assert "NONE FOUND" in " ".join(prov["search_order_exhausted"])


def test_water_unit_conversions_and_wue_arithmetic():
    e_it_kwh = 7776.0 * 1000.0
    assert abs(0.70 * e_it_kwh / L_PER_M3 - 5443.2) < 1e-9
    assert abs(1.27 * e_it_kwh / L_PER_M3 - 9875.52) < 1e-9
    assert abs(1.42 * e_it_kwh / L_PER_M3 - 11041.92) < 1e-9
    assert abs((1.27 - 0.70) * e_it_kwh / L_PER_M3 - 4432.32) < 1e-6
    assert abs(4400.0 * US_GAL_PER_M3 / 1e6 - 1.162) < 0.005
    assert abs(888.0 * 8760.0 / 1000.0 - 7778.88) < 1e-9
    assert abs(8037500.0 / 7776000.0 - 1.033629) < 1e-6


def test_first_year_accounting_reconciliation():
    rec = _j(ANALYSIS / "FIRST_YEAR_WATER_ACCOUNTING_REPRODUCTION.json")
    assert rec["FIRST_YEAR_ACCOUNTING_REPRODUCTION"] == "PASS"
    assert abs(rec["delta_TSC_m3_from_WUE"] - 4400.0) <= ROUNDING_WATER_M3_TOL
    by = {r["item"]: r for r in rec["rows"]}
    assert by["WUE_obs_L_per_kWh"]["evidence_class"] == "MEASUREMENT_DERIVED"
    assert by["WUE_cf_reuse_L_per_kWh"]["evidence_class"] == "MODELED_COUNTERFACTUAL"
    assert by["WUE_cf_tower_L_per_kWh"]["evidence_class"] == "MODELED_COUNTERFACTUAL"
    assert by["TSC_savings_m3"]["status"] == "PASS"


def test_observed_vs_counterfactual_classification():
    inv = _j(ANALYSIS / "WATER_EVIDENCE_INVENTORY.json")
    items = {r["quantity"]: r for r in inv["items"]}
    assert items["WUE_site_observed"]["evidence_class"] == "MEASUREMENT_DERIVED"
    assert items["WUE_no_TSC_reuse_plus_tower"]["evidence_class"] == "MODELED_COUNTERFACTUAL"
    assert items["WUE_tower_only"]["evidence_class"] == "MODELED_COUNTERFACTUAL"
    assert items["W_TSC_savings_year1"]["evidence_class"] == "MODELED_COUNTERFACTUAL"
    decomp = _j(ANALYSIS / "TECHNOLOGY_WUE_DECOMPOSITION.json")
    by = {s["id"]: s for s in decomp["scenarios"]}
    assert by["A_tower_only"]["observed_or_counterfactual"] == "counterfactual"
    assert by["B_reuse_plus_tower"]["observed_or_counterfactual"] == "counterfactual"
    assert by["C_reuse_TSC_tower"]["observed_or_counterfactual"] == "observed/source-derived"
    assert decomp["never_call_counterfactual_a_measured_treatment_effect"] is True
    for s in decomp["scenarios"]:
        if s["observed_or_counterfactual"] == "counterfactual":
            assert s["evidence_class"] == "MODELED_COUNTERFACTUAL"
            assert "measured" not in s["evidence_class"].lower()


def test_inventory_required_fields_and_classes():
    allowed = {
        "DIRECT_MEASUREMENT",
        "MEASUREMENT_DERIVED",
        "ENGINEERING_CALCULATION",
        "MODELED_COUNTERFACTUAL",
        "FIGURE_DIGITIZED",
        "DOCUMENTED_CONTROL_RULE",
    }
    required = {
        "quantity", "symbol", "physical_meaning", "units", "date_range",
        "temporal_resolution", "measurement_device", "source", "evidence_class",
        "water_thermal_boundary", "observation", "uncertainty", "extraction_method",
        "usable_as_model_target", "usable_as_model_predictor", "usable_as_validation_only",
        "notes",
    }
    items = _j(ANALYSIS / "WATER_EVIDENCE_INVENTORY.json")["items"]
    for r in items:
        missing = required - set(r)
        assert not missing, (r.get("quantity"), missing)
        assert r["evidence_class"] in allowed
    items_by = {r["quantity"]: r for r in items}
    assert items_by["TSC_DB_threshold"]["evidence_class"] == "DOCUMENTED_CONTROL_RULE"
    assert items_by["hvac_kw_electrical"]["usable_as_model_predictor"] is False
    assert items_by["cooling_kw_electrical"]["usable_as_model_predictor"] is False
    assert items_by["MAU_humidification_water"]["water_thermal_boundary"] == "EXPLICITLY_UNMETERED"


def test_no_hourly_water_model_and_temporal_gate():
    elig = _j(MANIFESTS / "WATER_TEMPORAL_MODEL_ELIGIBILITY.json")
    ident = _j(ANALYSIS / "WATER_MODEL_IDENTIFIABILITY.json")
    st = _j(ANALYSIS / "FINAL_ESIF_HEAT_WATER_STATUS.json")
    assert elig["HOURLY_SUPPORTED"] is False
    assert elig["DAILY_SUPPORTED"] is False
    assert elig["MONTHLY_SUPPORTED"] is False
    assert elig["STRUCTURAL_ACCOUNTING_ONLY"] is True
    assert elig["fit_finer_than_gate"] is False
    assert ident["choice"] == "NO_FITTED_MODEL_REQUIRED"
    assert ident["enough_variation_for_OOT_validation"] is False
    assert st["WATER_MODEL"] == "NOT_NEEDED"
    assert st["fitted_water_model"] is False
    assert st["WATER_MODEL_OUT_OF_TIME_VALIDATION"] == "NOT_NEEDED"
    assert st["MONTHLY_WATER_RECONSTRUCTION"] == "UNSUPPORTED"


def test_no_random_temporal_split():
    src = (SCRIPTS / "run_esif_heat_rejection_water.py").read_text()
    for tok in FORBIDDEN_FIT:
        assert tok not in src
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"train_test_split", "KFold", "shuffle"}


def test_no_figure_digitized_false_precision():
    audit = _j(ANALYSIS / "FIGURE_DIGITIZATION_AUDIT.json")
    assert audit["performed"] is False
    inv = _j(ANALYSIS / "WATER_EVIDENCE_INVENTORY.json")
    fig_rows = [r for r in inv["items"] if r["evidence_class"] == "FIGURE_DIGITIZED"]
    for r in fig_rows:
        assert r.get("value") in (None, "")
        blob = " ".join(str(r.get(k) or "") for k in ("notes", "observation")).upper()
        assert "NOT DIGITIZED" in blob or "DIGITIZATION NOT PERFORMED" in blob
    unc = _j(ANALYSIS / "WATER_EVIDENCE_UNCERTAINTY.json")
    assert unc["FIGURE_DIGITIZATION"]["performed"] is False
    assert unc["not_one_global_CI"] is True


def test_thermal_allocation_annual_only():
    df = pd.read_csv(DATA_PROCESSED / "esif_heat_rejection_allocations.csv")
    assert len(df) == 1
    assert bool(df.do_not_expand_to_hourly.iloc[0]) is True
    assert abs(float(df.share_reuse.iloc[0]) + float(df.share_TSC.iloc[0]) + float(df.share_tower.iloc[0]) - 1.0) < 1e-12
    pq = DATA_PROCESSED / "esif_heat_rejection_allocations.parquet"
    assert pq.exists()
    assert len(pd.read_parquet(pq)) == 1


def test_no_hvac_or_cooling_kw_used_as_thermal_rejection():
    src = (SCRIPTS / "run_esif_heat_rejection_water.py").read_text()
    st = _j(ANALYSIS / "FINAL_ESIF_HEAT_WATER_STATUS.json")
    assert st["used_hvac_kw_as_heat"] is False
    assert st["used_cooling_kw_as_heat"] is False
    bnd = _j(MANIFESTS / "HEAT_WATER_BOUNDARY_FREEZE.json")
    assert "hvac_kw" in bnd["electrical_not_thermal"]
    assert "cooling_kw" in bnd["electrical_not_thermal"]
    # Weather path only; power parquet is hashed, not scanned as a heat/water series.
    assert "read_parquet(POWER_PARQUET" not in src
    assert "hvac_kw" not in src.split("weather_mechanism")[1].split("def allocations")[0]


def test_no_prineville_coefficient_fit_or_meta_water():
    src = (SCRIPTS / "run_esif_heat_rejection_water.py").read_text()
    for tok in PRINEVILLE_MARKERS + META_WATER_MARKERS:
        assert tok not in src
    st = _j(ANALYSIS / "FINAL_ESIF_HEAT_WATER_STATUS.json")
    assert st["PRINEVILLE_COEFFICIENT_TRANSFER"] == "NOT_ALLOWED"
    assert st["prineville_modified"] is False
    assert st["meta_water_accessed"] is False
    freeze = _j(MANIFESTS / "ESIF_HEAT_WATER_RESULT_FREEZE.json")
    integ = (DOCS / "ESIF_HEAT_WATER_PROJECT_INTEGRATION.md").read_text()
    for banned in ("0.70", "1.27", "1.42", "42.5%", "49°F", "COC 12.8"):
        # Integration doc must forbid transferring these, not prescribe copying them into Prineville.
        assert "must not" in integ.lower() or "NOT_ALLOWED" in integ
    assert freeze["no_esif_result_may_change_based_on_lei"] is True


def test_lei_mapping_frozen_before_outcome_comparison():
    freeze = _j(MANIFESTS / "ESIF_HEAT_WATER_RESULT_FREEZE.json")
    lei = _j(ANALYSIS / "ESIF_VS_LEI_MASANET.json")
    src = (SCRIPTS / "run_esif_heat_rejection_water.py").read_text()
    freeze_idx = src.index("def freeze_esif_result")
    lei_idx = src.index("def lei_compare")
    assert freeze_idx < lei_idx
    assert freeze["frozen_before_lei_comparison"] is True
    assert freeze["lei_mapping_architecture_only"]["mapping_frozen_before_reading_PUE_WUE_outcomes"] is True
    assert freeze["lei_mapping_architecture_only"]["closest_primary"]["tech_id"] == "LIQ_DRY_AD"
    assert freeze["WUE_obs"] == lei["ESIF_MEASURED_OR_SOURCE_DERIVED"]["WUE"] == 0.70
    assert lei["no_retuning"] is True
    assert lei["esif_results_unchanged_after_comparison"] is True
    st = _j(ANALYSIS / "FINAL_ESIF_HEAT_WATER_STATUS.json")
    assert st["lei_mapping_frozen_before_outcome_comparison"] is True
    assert st["esif_result_changed_after_lei"] is False
    csv = pd.read_csv(ANALYSIS / "ESIF_VS_LEI_MASANET.csv")
    assert set(csv["class"]) >= {"ESIF_MEASURED_OR_SOURCE_DERIVED", "MODELED_COUNTERFACTUAL", "LEI_MASANET_MODELED_SCENARIO"}


def test_water_boundary_canonical_name():
    bnd = _j(MANIFESTS / "HEAT_WATER_BOUNDARY_FREEZE.json")
    assert bnd["water_canonical_name"] == "W_ESIF_reported_cooling"
    assert "MAU humidification" in " ".join(bnd["excludes"])
    assert bnd["first_year_shares"]["evidence_class"] == "MEASUREMENT_DERIVED"
    assert abs(bnd["first_year_shares"]["sum"] - 1.0) < 1e-12


def test_final_disposition_structural_validation():
    st = _j(ANALYSIS / "FINAL_ESIF_HEAT_WATER_STATUS.json")
    assert st["HEAT_WATER_FINAL_DISPOSITION"] == "STRUCTURAL_ACCOUNTING_VALIDATION"
    assert st["FIRST_YEAR_ACCOUNTING_REPRODUCTION"] == "PASS"
    assert st["cpu_untouched"] is True
    assert st["h100_untouched"] is True
    assert st["facility_overhead_untouched"] is True
    for name in (
        "01_thermal_water_hierarchy.png",
        "02_first_year_heat_allocation.png",
        "03_implied_water_volumes.png",
        "04_weather_vs_tsc_season.png",
        "05_wue_technology_decomposition.png",
        "06_esif_vs_lei.png",
    ):
        assert (FIGURES / name).is_file()
    for doc in (
        "ESIF_HEAT_WATER_BOUNDARY.md",
        "ESIF_HEAT_WATER_PROJECT_INTEGRATION.md",
        "ESIF_HEAT_REJECTION_WATER_REPORT.md",
    ):
        assert (DOCS / doc).is_file()


def test_scripts_do_not_import_prineville_or_meta_water():
    for p in SCRIPTS.glob("*.py"):
        text = p.read_text()
        assert "Meta_Prineville_Oregon" not in text
        assert "holdout" not in text.lower() or "NOT_ALLOWED" in text or "cannot_modify" in text
        assert not re.search(r"from\s+prineville", text)
