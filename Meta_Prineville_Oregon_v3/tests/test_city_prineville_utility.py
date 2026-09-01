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
    well = classify_component(ENTITY_FACEBOOK_DC, "WELL METER FOR SEW")
    assert well["physical_direction"] == "unknown"
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
