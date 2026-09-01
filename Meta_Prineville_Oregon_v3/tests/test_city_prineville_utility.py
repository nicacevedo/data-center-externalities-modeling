"""City of Prineville utility-meter parser, boundaries, and Meta-benchmark protection."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from prepare_city_prineville_utility import (  # noqa: E402
    ENTITY_FACEBOOK_DC,
    GAL_PER_100CF,
    M3_PER_US_GAL,
    PRIMARY_XLSX,
    RAW,
    classify_component,
    is_city_service_row,
    meter_id_to_str,
    usage_gallons,
    usage_m3,
)

META = ROOT / "data" / "canonical" / "meta_prineville_annual.csv"
PROCESSED = ROOT / "data" / "processed" / "city_prineville"

NEED_RAW = pytest.mark.skipif(not (RAW / PRIMARY_XLSX).exists(), reason="City raw package not present")
NEED_PROC = pytest.mark.skipif(
    not (PROCESSED / "city_meter_monthly_long.csv").exists(),
    reason="City processed products not present",
)


def test_unit_conversions():
    assert GAL_PER_100CF == 748
    assert M3_PER_US_GAL == 0.003785411784
    assert usage_gallons(1) == 748
    assert usage_gallons(0) == 0
    assert usage_m3(1) == pytest.approx(748 * 0.003785411784)
    assert usage_gallons(1899.07) == pytest.approx(1899.07 * 748)
    assert usage_m3(1899.07) == pytest.approx(1899.07 * 748 * 0.003785411784)


def test_meter_ids_preserve_leading_zeros():
    assert meter_id_to_str("0001") == "0001"
    assert meter_id_to_str("0002") == "0002"
    assert meter_id_to_str("0003") == "0003"
    assert meter_id_to_str("0004") == "0004"
    assert meter_id_to_str(1) == "0001"
    assert meter_id_to_str(1562600912) == "1562600912"
    assert meter_id_to_str("1562600912") == "1562600912"
    assert meter_id_to_str(1562600912.0) == "1562600912"


def test_city_service_definition_excludes_unresolved_channels():
    assert is_city_service_row(ENTITY_FACEBOOK_DC, 'WATER - COMM 6"')
    assert is_city_service_row(ENTITY_FACEBOOK_DC, "ADD'L WATER - 4\"")
    assert not is_city_service_row(ENTITY_FACEBOOK_DC, "SWR METER")
    assert not is_city_service_row(ENTITY_FACEBOOK_DC, "WELL METER FOR SEW")
    assert not is_city_service_row(ENTITY_FACEBOOK_DC, "BULK WATER")
    assert not is_city_service_row("Facebook Trailer City", 'WATER - COMM 2"')
    assert not is_city_service_row("Facebook Warehouse", 'WATER - COMM 3/4"')
    swr = classify_component(ENTITY_FACEBOOK_DC, "SWR METER")
    assert swr["boundary_status"] == "unresolved"
    assert swr["physical_direction"] == "unknown"
    assert swr["semantic_hint"] == "sewer-related"
    assert swr["model_use"] == "excluded_from_city_service"
    assert "wastewater return" not in swr["semantic_note"].lower() or "not wastewater return" in swr["semantic_note"].lower()
    well = classify_component(ENTITY_FACEBOOK_DC, "WELL METER FOR SEW")
    assert well["physical_direction"] == "unknown"
    assert well["boundary_status"] == "unresolved"
    bulk = classify_component(ENTITY_FACEBOOK_DC, "BULK WATER")
    assert bulk["component_class"] == "bulk_water"


@NEED_RAW
def test_parser_repeated_blocks_and_ids():
    from prepare_city_prineville_utility import parse_primary_meter_report

    long = parse_primary_meter_report(RAW / PRIMARY_XLSX)
    assert long["meter_id_raw"].map(lambda x: isinstance(x, str)).all()
    for mid in ("0001", "0002", "0003", "0004"):
        assert mid in set(long["meter_id_raw"])
    assert not ({"1", "2", "3", "4"} & set(long["meter_id_raw"]))
    years = sorted(int(y) for y in long["year"].unique())
    assert years == list(range(2012, 2027))
    assert long.groupby(["year", "meter_id_raw", "month"]).size().max() == 1
    assert long["month"].between(1, 12).all()


@NEED_PROC
def test_zero_missing_not_observed_distinction():
    long = pd.read_csv(PROCESSED / "city_meter_monthly_long.csv", dtype={"meter_id_raw": str})
    assert "observed_zero" in set(long.observation_status)
    assert "not_observed_yet" in set(long.observation_status)
    future = long[long.observation_status.eq("not_observed_yet")]
    assert (future.year == 2026).all()
    assert (future.month >= 8).all()
    assert (future.usage_100cf.fillna(0) == 0).all()
    # 2015 June is a mid-year source gap, not observed zero.
    june = long[
        (long.year == 2015)
        & (long.month == 6)
        & (long.entity_name == ENTITY_FACEBOOK_DC)
        & (
            long.rate_code_raw.str.startswith("WATER - COMM")
            | long.rate_code_raw.str.startswith("ADD'L WATER")
        )
    ]
    assert not june.empty
    assert set(june.observation_status) <= {"missing", "structurally_unavailable"}


@NEED_PROC
def test_city_service_aggregate_exclusions_and_2026_partial():
    long = pd.read_csv(PROCESSED / "city_meter_monthly_long.csv", dtype={"meter_id_raw": str})
    comps = pd.read_csv(PROCESSED / "city_water_components_monthly.csv")
    obs = long[long.observation_status.isin(["observed", "observed_zero"])]
    svc = obs[
        (obs.entity_name == ENTITY_FACEBOOK_DC)
        & (
            obs.rate_code_raw.str.startswith("WATER - COMM")
            | obs.rate_code_raw.str.startswith("ADD'L WATER")
        )
    ]
    excluded = obs[obs.component_class.isin(
        ["swr_meter", "well_meter_for_sew", "trailer_city_water", "warehouse_water"]
    )]
    # Service total must not include excluded channels.
    assert set(svc.component_class).isdisjoint({"swr_meter", "well_meter_for_sew", "trailer_city_water", "warehouse_water"})
    y2026 = comps[comps.year == 2026]
    assert y2026.loc[y2026.month > 7, "city_metered_water_service_m3"].isna().all()
    assert y2026.loc[y2026.month <= 7, "city_metered_water_service_m3"].notna().all()
    assert "total_campus_water_m3" not in comps.columns
    # Arithmetic: reconstructed service months match the long table.
    recon = svc.groupby(["year", "month"])["usage_m3"].sum()
    for r in comps.itertuples(index=False):
        if pd.isna(r.city_metered_water_service_m3):
            continue
        assert r.city_metered_water_service_m3 == pytest.approx(float(recon.loc[(int(r.year), int(r.month))]))


@NEED_PROC
def test_annual_total_arithmetic_and_documented_anomalies():
    long = pd.read_csv(PROCESSED / "city_meter_monthly_long.csv", dtype={"meter_id_raw": str})
    qa = pd.read_csv(PROCESSED / "city_meter_qa.csv")
    mismatch = qa.loc[qa.check_id.eq("monthly_sum_vs_annual_total"), "status"].iloc[0]
    assert mismatch in {"PASS", "WARN"}
    # Warehouse 1562600912 is the documented annual-total source anomaly; parser does not rewrite it.
    wh = long[long.meter_id_raw.eq("1562600912") & long.year.isin([2020, 2021, 2022, 2023])]
    for year, g in wh.groupby("year"):
        reported = g["annual_total_raw"].iloc[0]
        monthly = g["usage_100cf"].fillna(0).sum()
        if pd.notna(reported) and abs(monthly - float(reported)) > 1e-6:
            assert float(reported) == 0.0
            assert monthly > 0


@NEED_PROC
def test_bulk_dates_not_shifted_to_consumption_month():
    bulk = pd.read_csv(PROCESSED / "city_bulk_water_monthly.csv")
    assert "bill_date" in bulk.columns
    assert "bill_year" in bulk.columns
    assert (bulk["consumption_month_claimed"] == False).all()  # noqa: E712
    assert (bulk["time_basis"] == "city_billing_convention").all()
    dates = pd.to_datetime(bulk["bill_date"])
    assert (dates.dt.year == bulk["bill_year"]).all()
    assert (dates.dt.month == bulk["bill_month"]).all()


@NEED_PROC
def test_lineage_leading_1_not_silently_normalized():
    events = pd.read_csv(PROCESSED / "city_meter_events.csv", dtype={"old_meter_raw": str, "new_meter_raw": str})
    lin = pd.read_csv(PROCESSED / "city_meter_lineage_audit.csv", dtype={"event_meter_id_raw": str, "candidate_consumption_meter_id": str})
    assert "1832148468" in set(events.old_meter_raw.dropna().astype(str))
    row = lin[lin.event_meter_id_raw.eq("1832148468")].iloc[0]
    assert row.match_type == "inferred_leading_1"
    assert row.candidate_consumption_meter_id == "832148468"
    assert bool(row.accepted_for_lineage_boolean) is False
    # Source set date 2026-02-15 vs 2024 consumption is retained as an anomaly.
    assert (events.new_meter_raw.eq("1573376176") & events.event_date.eq("2026-02-15")).any()
    long = pd.read_csv(PROCESSED / "city_meter_monthly_long.csv", dtype={"meter_id_raw": str})
    early = long[
        long.meter_id_raw.eq("1573376176")
        & long.observation_status.isin(["observed", "observed_zero"])
        & (long.year < 2026)
    ]
    assert not early.empty


def test_canonical_meta_annual_benchmark_protection():
    assert META.exists()
    digest = hashlib.sha256(META.read_bytes()).hexdigest()
    meta = pd.read_csv(META)
    # Hard-coded published values must remain; this integration must not rewrite them.
    w = meta.set_index("year")["water_withdrawal_m3_reported"]
    assert w.loc[2014] == pytest.approx(39746.823732)
    assert w.loc[2022] == pytest.approx(240000)
    assert w.loc[2023] == pytest.approx(180000)
    assert w.loc[2024] == pytest.approx(328000)
    if (PROCESSED / "parser_summary.json").exists():
        summary = json.loads((PROCESSED / "parser_summary.json").read_text())
        assert summary["meta_annual_sha256"] == digest
    src = (ROOT / "src" / "prepare_city_prineville_utility.py").read_text(encoding="utf-8")
    assert "to_csv(META" not in src
    assert "to_csv(META_ANNUAL" not in src
    assert "water_withdrawal_m3_reported" in src


@NEED_PROC
def test_source_boundary_guards():
    comps = pd.read_csv(PROCESSED / "city_water_components_monthly.csv")
    recon = pd.read_csv(PROCESSED / "city_meta_annual_reconciliation.csv")
    gate = json.loads((PROCESSED / "model_promotion_gate.json").read_text())
    assert "total_campus_water_m3" not in comps.columns
    assert "combination_label" in recon.columns
    assert recon["combination_label"].str.contains("not_canonical").all()
    assert gate["gate"] in {"PASS", "FAIL"}
    for name in gate["unresolved_excluded_from_response"]:
        assert name in {
            "swr_meter",
            "well_meter_for_sew",
            "bulk_water",
            "trailer_city_water",
            "warehouse_water",
        }
    # City service is not silently treated as Meta withdrawal.
    src = (ROOT / "src" / "prepare_city_prineville_utility.py").read_text(encoding="utf-8")
    assert "Not total Meta withdrawal" in src


@NEED_PROC
def test_promotion_gate_and_no_total_campus_water_product():
    gate = json.loads((PROCESSED / "model_promotion_gate.json").read_text())
    qa = pd.read_csv(PROCESSED / "city_meter_qa.csv")
    blocking = qa[(qa.severity == "blocking") & (qa.status == "FAIL")]
    if gate["gate"] == "PASS":
        assert blocking.empty
        assert not gate["double_count_investigation"]["identified_parent_submeter_double_counting"]
    products = list(PROCESSED.glob("*.csv"))
    assert not any("total_campus_water" in p.name for p in products)


def test_water_command_includes_city_utility_dependencies():
    import ast

    src = (ROOT / "run_prineville.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    water_fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "water")
    called = []
    for node in ast.walk(water_fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called.append(node.func.id)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            called.append(node.func.attr)
    assert "city_utility" in called
    assert "city_utility_models" in called
    water_src = ast.get_source_segment(src, water_fn) or src[src.index("def water(") : src.index("def eia(")]
    assert "prepare_owrd_wateruse.py" in water_src
    assert water_src.index("prepare_owrd_wateruse.py") < water_src.index("city_utility")


def test_common_support_metrics_use_identical_rows():
    from evaluate_city_metered_water_models import (
        MODEL_PRED_COLS,
        common_support_mask,
        common_support_tables,
    )

    preds = pd.DataFrame(
        {
            "year": [2014, 2014, 2016, 2016],
            "month": [1, 2, 1, 2],
            "observed_m3": [10.0, 20.0, 30.0, 40.0],
            "pred_climatology_m3": [11.0, 21.0, 31.0, 41.0],
            "pred_seasonal_persist_m3": [12.0, 22.0, 32.0, 42.0],
            "pred_elec_scale_m3": [13.0, float("nan"), 33.0, 43.0],
            "pred_graybox_scaled_m3": [14.0, 24.0, 34.0, 44.0],
            "pred_scale_plus_evap_m3": [15.0, 25.0, 35.0, 45.0],
        }
    )
    mask = common_support_mask(preds)
    assert int(mask.sum()) == 3
    pooled, by_year, _vs, _beats, cs = common_support_tables(preds)
    assert set(pooled["n"]) == {3}
    keys = set(zip(cs["year"].astype(int), cs["month"].astype(int)))
    assert keys == {(2014, 1), (2016, 1), (2016, 2)}
    assert (2014, 2) not in keys
    for name, col in MODEL_PRED_COLS:
        assert cs[col].notna().all()


@NEED_PROC
def test_common_support_output_n_identical_across_models():
    from evaluate_city_metered_water_models import common_support_mask

    path = ROOT / "outputs" / "city_prineville" / "city_service_model_metrics_common_support.csv"
    if not path.exists():
        pytest.skip("common-support metrics not generated yet")
    cs = pd.read_csv(path)
    assert cs["n"].nunique() == 1
    preds = pd.read_csv(ROOT / "outputs" / "city_prineville" / "city_metered_service_monthly_predictions.csv")
    mask = common_support_mask(preds)
    n = int(mask.sum())
    assert (cs["n"] == n).all()
    by_year = ROOT / "outputs" / "city_prineville" / "city_service_model_metrics_common_support_by_year.csv"
    ytab = pd.read_csv(by_year)
    for _year, g in ytab.groupby("year"):
        assert g["n_months"].nunique() == 1


@NEED_PROC
def test_processed_swr_direction_unknown_and_latest_observed_month():
    long = pd.read_csv(PROCESSED / "city_meter_monthly_long.csv", dtype={"meter_id_raw": str})
    swr = long[long.rate_code_raw.eq("SWR METER")]
    assert not swr.empty
    assert (swr["physical_direction"] == "unknown").all()
    assert (swr["boundary_status"] == "unresolved").all()
    if "semantic_hint" in swr.columns:
        assert (swr["semantic_hint"] == "sewer-related").all()
    summary = json.loads((PROCESSED / "parser_summary.json").read_text())
    assert summary["latest_observed"]["year"] == 2026
    assert summary["latest_observed"]["month"] == 7
    future = long[long.observation_status.eq("not_observed_yet")]
    assert (future.year == 2026).all()
    assert (future.month >= 8).all()


@NEED_PROC
def test_duplicate_csv_is_not_a_scientific_source():
    inv = pd.read_csv(PROCESSED / "city_source_file_inventory.csv")
    extra = inv[inv.filename.eq("FB Meters and Consumption.csv")]
    one = inv[inv.filename.eq("FB Meters and Consumption(1).csv")]
    assert not extra.empty and not one.empty
    assert extra["scientific_role"].iloc[0] == "duplicate_non_source"
    val = extra["counts_as_scientific_source"].iloc[0]
    if isinstance(val, bool):
        assert val is False
    else:
        assert str(val).strip().lower() in {"false", "0", "f"}
    assert extra["sha256"].iloc[0] == one["sha256"].iloc[0]
    sci = inv[inv["counts_as_scientific_source"].astype(str).isin(["True", "true", "1"])]
    assert "FB Meters and Consumption.csv" not in set(sci.filename)
    # One verified hash per counted source filename.
    assert sci["filename"].is_unique
    assert "wait — use exact" not in inv.to_csv(index=False)


@NEED_PROC
def test_annual_reconciliation_share_diagnostics_and_no_total_campus():
    recon = pd.read_csv(PROCESSED / "city_meta_annual_reconciliation.csv")
    comps = pd.read_csv(PROCESSED / "city_water_components_monthly.csv")
    assert "total_campus_water_m3" not in comps.columns
    assert "total_campus_water_m3" not in recon.columns
    for col in (
        "city_service_share_of_meta",
        "city_service_plus_bulk_share_of_meta",
        "city_service_minus_meta_m3",
        "city_service_plus_bulk_minus_meta_m3",
    ):
        assert col in recon.columns
    assert recon["combination_label"].str.contains("bill_year").all()
    assert recon["note"].str.contains("accounting-date").all()


def test_canonical_meta_annual_hash_constant():
    digest = hashlib.sha256(META.read_bytes()).hexdigest()
    assert digest == "1f6b19f466b89a0e08c4914689186bed1bc8a9574c5732bb26c17562e5a1e513"
    freeze = ROOT / "outputs" / "city_prineville" / "frozen_annual_water_validation_v1" / "water_holdout_baseline_compare.csv"
    live = ROOT / "outputs" / "pipeline_report" / "water_holdout_baseline_compare.csv"
    if freeze.exists() and live.exists():
        assert hashlib.sha256(freeze.read_bytes()).hexdigest() == hashlib.sha256(live.read_bytes()).hexdigest()

