"""Focused FERC Form 714 parser, accounting, and provenance checks."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from prepare_ferc714 import (  # noqa: E402
    EIA_CANONICAL,
    EIA_REPORTED_MAX_MW,
    EIA_REPORTED_MIN_MW,
    EXTENDED,
    OUT,
    OUT_PNG,
    OUT_QA,
    OUT_VAL,
    RAW,
    discover_filings,
    eia_reported_usable,
    nel_identity_table,
)

PREPARE_SRC = ROOT / "src" / "prepare_ferc714.py"
WEST = OUT / "pacw_west_monthly.csv"
EW = OUT / "pacificorp_east_west_hourly.csv"
BACKCAST = OUT / "pacw_hourly_backcast.csv"


def test_discover_2011_2018_paired_filings():
    filings = discover_filings(RAW)
    assert not filings.empty
    years_w = set(filings.loc[filings.kind.eq("pacificorp_west_monthly"), "report_year_from_name"].astype(int))
    years_ew = set(filings.loc[filings.kind.eq("east_west_combined_hourly"), "report_year_from_name"].astype(int))
    assert years_w == set(range(2011, 2019))
    assert years_ew == set(range(2011, 2019))
    assert filings["kind"].isin(["pacificorp_west_monthly", "east_west_combined_hourly"]).all()


def test_west_year_month_unique_and_nel_identity():
    west = pd.read_csv(WEST)
    assert set(west["year"].astype(int)) == set(range(2011, 2019))
    assert not west.duplicated(["year", "month"]).any()
    assert len(west) == 96
    ident = nel_identity_table(west)
    assert float(ident["nel_minus_gen_plus_interchange_mwh"].abs().max()) < 1e-6


def test_combined_hourly_utc_unique_after_dst():
    ew = pd.read_csv(EW)
    ts = pd.to_datetime(ew["timestamp_utc"], utc=True)
    assert ts.is_unique
    assert not ts.isna().any()
    assert "year_local" in ew.columns and "month_local" in ew.columns
    assert "local_timestamp" in ew.columns


def test_east_west_not_labeled_observed_west():
    ew = pd.read_csv(EW)
    assert set(ew["series_label"]) == {"pacificorp_east_west_combined_planning_area"}
    assert ew["provenance_class"].eq("reported").all()
    assert ew["provenance"].str.contains("not PACW-West", case=False).all()
    assert not ew["provenance"].str.contains("reported PACW-West hourly", case=False).any()
    header = ",".join(ew.columns).lower()
    assert "west_hourly_backcast" not in header
    assert "west_net_energy_for_load" not in header


def test_backcast_monthly_closes_to_west_nel():
    b = pd.read_csv(BACKCAST)
    chk = b.groupby(["year_local", "month_local"], as_index=False).agg(
        s=("west_hourly_backcast_mw", "sum"),
        n=("west_nel_mwh", "first"),
    )
    assert (chk["s"] - chk["n"]).abs().max() < 1e-3
    assert b["provenance_class"].eq("proxy").all()
    assert b["source"].str.contains("ferc714").all()
    assert b["provenance"].str.contains("not reported PACW hourly demand", case=False).all()


def test_eia_overlap_artifacts_exist():
    assert OUT_QA.exists()
    assert OUT_VAL.exists()
    assert OUT_PNG.exists()
    val = pd.read_csv(OUT_VAL)
    assert "hourly_2016_2018" in set(val["subset"])
    qa = pd.read_csv(OUT_QA)
    items = set(qa["item"])
    assert "campus_electricity" in items
    campus = str(qa.loc[qa["item"].eq("campus_electricity"), "value"].iloc[0]).lower()
    assert "never" in campus


def test_ferc_never_overwrites_eia_pacw():
    text = PREPARE_SRC.read_text(encoding="utf-8")
    assert "to_csv" in text
    assert 'EIA_CANONICAL).to_csv' not in text.replace(" ", "")
    assert "pacw_hourly.csv" in text
    assert EIA_CANONICAL.exists()
    assert "OUT / \"pacw_hourly.csv\"" not in text
    eia = pd.read_csv(EIA_CANONICAL, nrows=5)
    assert "demand_reported_mwh" in eia.columns


def test_extended_series_usable_hierarchy():
    ext = pd.read_csv(EXTENDED)
    eia = pd.read_csv(EIA_CANONICAL, usecols=["timestamp_utc", "demand_reported_mwh"])
    required = {
        "demand_reported_raw_mwh",
        "demand_reported_usable_mwh",
        "demand_adjusted_mwh",
        "demand_ferc_proxy_mwh",
        "demand_best_available_mwh",
        "provenance",
        "provenance_class",
    }
    assert required.issubset(ext.columns)
    best = pd.to_numeric(ext["demand_best_available_mwh"], errors="coerce")
    usable = pd.to_numeric(ext["demand_reported_usable_mwh"], errors="coerce")
    raw = pd.to_numeric(ext["demand_reported_raw_mwh"], errors="coerce")
    proxy = pd.to_numeric(ext["demand_ferc_proxy_mwh"], errors="coerce")
    assert not ((best <= EIA_REPORTED_MIN_MW) | (best > EIA_REPORTED_MAX_MW)).any()
    filled = best.notna()
    assert ((usable.notna() & (best == usable)) | (usable.isna() & filled & (best == proxy)) | (~filled)).all()
    first_usable = pd.to_datetime(ext.loc[usable.notna(), "timestamp_utc"], utc=True).min()
    ts = pd.to_datetime(ext["timestamp_utc"], utc=True)
    assert not (proxy.notna() & (ts >= first_usable)).any()
    assert not (ext["provenance"].eq("FERC constrained proxy") & (ts >= first_usable)).any()
    assert ext.loc[usable.notna(), "provenance"].eq("EIA-930 reported usable").all()
    assert ext.loc[ext["provenance"].eq("FERC constrained proxy"), "provenance_class"].eq("proxy").all()
    assert not ext["provenance"].str.contains("observed PACW", case=False).any()
    eia_ts = pd.to_datetime(eia["timestamp_utc"], utc=True)
    eia_usable = eia_reported_usable(eia["demand_reported_mwh"])
    overlap = pd.DataFrame(
        {
            "timestamp_utc": ts,
            "best": best,
            "provenance": ext["provenance"],
            "proxy": proxy,
        }
    ).merge(
        pd.DataFrame({"timestamp_utc": eia_ts, "eia_usable": eia_usable}),
        on="timestamp_utc",
        how="inner",
    )
    both = overlap["eia_usable"].notna()
    assert overlap.loc[both, "provenance"].eq("EIA-930 reported usable").all()
    assert (overlap.loc[both, "best"] == overlap.loc[both, "eia_usable"]).all()
    assert overlap.loc[both, "proxy"].isna().all()
    assert raw.notna().any()
    unusable_raw = raw.notna() & ((raw <= EIA_REPORTED_MIN_MW) | (raw > EIA_REPORTED_MAX_MW))
    assert unusable_raw.any()
    assert usable[unusable_raw].isna().all()
    assert best[unusable_raw & (ts >= first_usable)].isna().all()


def test_ferc_is_regional_not_campus_electricity():
    west = pd.read_csv(WEST)
    assert west["provenance"].str.contains("not campus electricity", case=False).all()
    b = pd.read_csv(BACKCAST)
    assert b["provenance"].str.contains("not campus electricity", case=False).all()
    stoch = (ROOT / "src" / "stochastic_conditional_simulation.py").read_text(encoding="utf-8")
    assert 'PACW_HOURLY = ROOT / "data" / "processed" / "pacw_hourly.csv"' in stoch
    assert "pacw_hourly_backcast" not in stoch
    assert "pacw_demand_hourly_extended" not in stoch
