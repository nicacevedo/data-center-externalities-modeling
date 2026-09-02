#!/usr/bin/env python3
"""Post-test scientific closure for ESIF facility-overhead.

Descriptive audits only. Does not refit F0–F4, alter splits, or revise TEST metrics.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from facility_paths import (  # noqa: E402
    ANALYSIS,
    COVERAGE_MIN,
    CPU_FREEZE,
    CPU_STATUS,
    DATA_PROCESSED,
    DOCS,
    H100_FREEZE,
    MANIFESTS,
    POWER_PARQUET,
    RESULTS,
    TOWER_FILTER_PUMP_KW,
    WEATHER_PARQUET,
)
from run_esif_facility_overhead import (  # noqa: E402
    f_to_c,
    hourly_aggregate,
    stull_wetbulb_c,
)

FROZEN_RELATIVE = [
    "manifests/FACILITY_MODEL_PROTOCOL_FREEZE.json",
    "manifests/FACILITY_TEMPORAL_SPLIT_FREEZE.json",
    "analysis/COMPONENT_SELECTED_MODELS.json",
    "analysis/COMPONENT_CV_METRICS.csv",
    "analysis/FINAL_TEST_METRICS.csv",
    "analysis/FINAL_TEST_METRICS.json",
    "analysis/PUE_PREDICTION_METRICS.csv",
    "analysis/PUE_PREDICTION_METRICS.json",
    "analysis/FACILITY_OVERHEAD_UNCERTAINTY.json",
]
# Original runner may be patched for generating-code corrections; its pre-closure hash is recorded separately.
RUNNER_REL = "scripts/run_esif_facility_overhead.py"
FO_ROOT = Path(__file__).resolve().parents[1]

TSC_PRE_START = pd.Timestamp("2016-06-12")
TSC_PRE_END = pd.Timestamp("2016-08-01")  # exclusive; through 2016-07-31
TSC_TRANS_START = pd.Timestamp("2016-08-01")
TSC_TRANS_END = pd.Timestamp("2016-09-01")
TSC_YEAR_START = pd.Timestamp("2016-09-01")
TSC_YEAR_END = pd.Timestamp("2017-09-01")  # exclusive; through 2017-08-31
SICKINGER_OPERATIONAL_CAPTION_DATE = "2016-08-16"
OUTAGE_START = pd.Timestamp("2025-06-26")
OUTAGE_END = pd.Timestamp("2025-07-01")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def jdump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=_json_default) + "\n")


def _json_default(x):
    if isinstance(x, (np.floating, np.integer)):
        return float(x) if isinstance(x, np.floating) else int(x)
    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, (pd.Timestamp, Path)):
        return str(x)
    if pd.isna(x):
        return None
    raise TypeError(type(x))


def load_freeze() -> dict:
    return json.loads((MANIFESTS / "FACILITY_OVERHEAD_POSTTEST_CLOSURE_INITIAL_STATE.json").read_text())


def assert_numerical_freeze(init: dict, also_runner: bool = False) -> None:
    arts = init["frozen_numerical_artifacts"]
    for rel in FROZEN_RELATIVE:
        got = sha256_file(FO_ROOT / rel)
        exp = arts[rel]["sha256"]
        if got != exp:
            raise RuntimeError(f"NUMERICAL FREEZE VIOLATED: {rel}")
    if also_runner:
        got = sha256_file(FO_ROOT / RUNNER_REL)
        exp = arts[RUNNER_REL]["sha256"]
        if got != exp:
            raise RuntimeError("Original runner hash changed unexpectedly during hash-only check")


def ensure_hourly() -> pd.DataFrame:
    dest = DATA_PROCESSED / "esif_facility_hourly.parquet"
    if dest.exists():
        return pd.read_parquet(dest)
    pcols = ["it_power_kw", "cooling_kw", "hvac_kw", "pump_kw", "plug_and_light_kw", "pue", "energy_reuse"]
    p = pd.read_parquet(POWER_PARQUET)
    p["ts"] = pd.to_datetime(p.ts)
    p = p[p.ts >= "2015-11-01"]
    for c in pcols:
        if c in ("pue", "energy_reuse"):
            continue
        p.loc[p[c] < 0, c] = np.nan
    w = pd.read_parquet(WEATHER_PARQUET).rename(
        columns={"outdoor_air_temp": "outside_air_temp", "outdoor_air_humidity": "outside_air_humidity"}
    )
    w["ts"] = pd.to_datetime(w.ts)
    w = w[w.ts >= "2016-01-01"]
    w.loc[(w.outside_air_temp < -50) | (w.outside_air_temp > 120), "outside_air_temp"] = np.nan
    w.loc[(w.outside_air_humidity < 0) | (w.outside_air_humidity > 100), "outside_air_humidity"] = np.nan
    ph = hourly_aggregate(p, pcols)
    wh = hourly_aggregate(w, ["outside_air_temp", "outside_air_humidity"])
    h = ph.merge(wh, on="hour", how="inner", suffixes=("_power", "_weather"))
    if "coverage_power" in h.columns:
        h["coverage"] = h["coverage_power"]
        h["weather_coverage"] = h["coverage_weather"]
    h["tdb_f"] = h["outside_air_temp"]
    h["rh_pct"] = h["outside_air_humidity"]
    h["tdb_c"] = f_to_c(h["tdb_f"])
    rh_ok = h["rh_pct"].between(5, 99) & h["tdb_c"].between(-40, 50)
    h["twb_c"] = np.where(rh_ok, stull_wetbulb_c(h["tdb_c"].to_numpy(), h["rh_pct"].to_numpy()), np.nan)
    h["aux_source_kw"] = h["cooling_kw"] + h["hvac_kw"] + h["pump_kw"] + h["plug_and_light_kw"]
    h["pump_physical_kw"] = h["pump_kw"] + TOWER_FILTER_PUMP_KW
    h["cooling_fans_trace_kw"] = h["cooling_kw"] - TOWER_FILTER_PUMP_KW
    outage = (h.hour >= OUTAGE_START) & (h.hour < OUTAGE_END)
    h["documented_outage"] = outage
    h["valid_it"] = h["it_power_kw"].gt(0) & h["coverage"].ge(COVERAGE_MIN) & ~outage
    h["valid_weather"] = h["tdb_c"].notna() & h["rh_pct"].notna() & h["weather_coverage"].ge(COVERAGE_MIN)
    h["valid_twb"] = h["twb_c"].notna()
    for t, flag in [
        ("cooling_kw", "valid_cooling"),
        ("hvac_kw", "valid_hvac"),
        ("pump_kw", "valid_pump"),
        ("plug_and_light_kw", "valid_plug"),
    ]:
        h[flag] = h[t].notna() & h["valid_it"] & h["valid_weather"] & h["valid_twb"]
    h["valid_all"] = h["valid_cooling"] & h["valid_hvac"] & h["valid_pump"] & h["valid_plug"]
    h["pue_reconstructed"] = np.where(
        h["it_power_kw"] > 0, (h["it_power_kw"] + h["aux_source_kw"]) / h["it_power_kw"], np.nan
    )
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    h.to_parquet(dest, index=False)
    return h


def monthly_block(v: pd.DataFrame, start, end) -> dict:
    s = v[(v.hour >= start) & (v.hour < end)]
    if s.empty:
        return {"n_hours": 0}
    return {
        "n_hours": int(len(s)),
        "it_kw_mean": float(s.it_power_kw.mean()),
        "cooling_kw_mean": float(s.cooling_kw.mean()),
        "hvac_kw_mean": float(s.hvac_kw.mean()),
        "pump_kw_mean": float(s.pump_kw.mean()),
        "plug_and_light_kw_mean": float(s.plug_and_light_kw.mean()),
        "aux_kw_mean": float(s.aux_source_kw.mean()),
        "pue_source_mean": float(s.pue.mean()) if "pue" in s else None,
        "pue_reconstructed_mean": float(s.pue_reconstructed.mean()),
        "tdb_c_mean": float(s.tdb_c.mean()),
        "twb_c_mean": float(s.twb_c.mean()),
        "rh_pct_mean": float(s.rh_pct.mean()),
        "it_kwh": float(s.it_power_kw.sum()),
        "aux_kwh": float(s.aux_source_kw.sum()),
    }


def thermosyphon_audit(h: pd.DataFrame) -> dict:
    v = h[h.valid_all].copy()
    months = []
    t = pd.Timestamp("2016-06-01")
    end = pd.Timestamp("2017-09-01")
    while t < end:
        nxt = t + pd.offsets.MonthBegin(1)
        rec = monthly_block(v, t, nxt)
        rec["month"] = str(t.date())[:7]
        rec["regime"] = (
            "pre_tsc_available"
            if t < TSC_TRANS_START
            else ("commissioning_transition" if t < TSC_YEAR_START else "first_full_tsc_year")
        )
        months.append(rec)
        t = nxt
    pre = monthly_block(v, TSC_PRE_START, TSC_PRE_END)
    trans = monthly_block(v, TSC_TRANS_START, TSC_TRANS_END)
    yr = monthly_block(v, TSC_YEAR_START, TSC_YEAR_END)
    common_start = str(v.hour.min())
    common_end = str(v.hour.max())
    crosses = (v.hour.min() < TSC_TRANS_START) and (v.hour.max() >= TSC_YEAR_END)
    audit = {
        "thermosyphon_in_sample": True,
        "NOT_IN_SAMPLE": False,
        "common_valid_span": [common_start, common_end],
        "source_crosses_commissioning": bool(crosses),
        "pre_tsc_available": {"start": "2016-06-12", "end_inclusive": "2016-07-31", **pre},
        "commissioning_transition": {
            "start": "2016-08-01",
            "end_inclusive": "2016-08-31",
            "month_treated_as": "transitional",
            "sickinger_figure_caption_operational_date": SICKINGER_OPERATIONAL_CAPTION_DATE,
            "do_not_invent_a_fitted_August_day": True,
            **trans,
        },
        "first_full_tsc_year": {"start": "2016-09-01", "end_inclusive": "2017-08-31", **yr},
        "primary_sources": [
            {
                "identity": "Sickinger et al. 2018 NREL/TP-2C00-72196",
                "doi": "10.2172/1471661",
                "statements_used": [
                    "In August 2016, NREL installed a thermosyphon hybrid cooling system",
                    "The TCHS became operational in August 2016",
                    "Figure 3 caption: August 16 is when TSC became operational",
                    "first full year of thermosyphon operation: September 1, 2016 through August 31, 2017",
                    "hourly average IT load first year 888 kW; IT energy 7,776 MWh",
                    "review of monthly mean PUE does not show negative impacts on energy efficiency when adding the TSC",
                    "extra pump energy to TSC and TSC fan energy are accounted in PUE",
                ],
            },
            {
                "identity": "NREL news 2018 Data Center Water-Savings Win Wins",
                "url": "https://www.nrel.gov/grid/news/program/2018/data-center-water-savings-win-wins",
                "statements_used": ["BlueStream Hybrid Cooling System born on the roof of the ESIF in August 2016"],
            },
        ],
        "comparison_with_sickinger_quantities_that_are_actually_reported": {
            "first_full_operating_year_definition": "MATCHES_SOURCE (2016-09-01 through 2017-08-31)",
            "our_first_full_year_IT_kw_mean": yr.get("it_kw_mean"),
            "sickinger_first_year_hourly_average_IT_kw": 888.0,
            "IT_mean_difference_kw": None if not yr.get("it_kw_mean") else float(yr["it_kw_mean"] - 888.0),
            "our_first_full_year_IT_MWh": None if not yr.get("it_kwh") else float(yr["it_kwh"] / 1000.0),
            "sickinger_first_year_IT_MWh": 7776.0,
            "our_first_full_year_source_PUE_mean": yr.get("pue_source_mean"),
            "sickinger_trailing_12_month_PUE_context": "facility maintained trailing 12-month average PUE of 1.06 or better since opening; extra TSC pump/fan energy included in PUE",
            "sickinger_conclusion_used": "TSC addition did not materially degrade data-center energy efficiency (authors: monthly mean PUE review shows no negative impacts)",
            "do_not_claim_matched_pre_post_causal_TSC_electrical_effect": True,
        },
        "limitations": [
            "Pre-TSC electrical overlap in this power/weather sample is only 2016-06-12 through 2016-07-31 (~7 weeks) plus a transitional August.",
            "Pre-period is high-summer at Golden, CO; seasonal confounding with commissioning is severe.",
            "August 2016 is a mixed installation/operational month; Sickinger notes an August 2016 PUE jump from a planned outage for an unrelated project.",
            "This audit does not estimate a causal TSC electrical effect.",
            "cooling_kw and hvac_kw are electrical meters, not rejected thermal energy.",
        ],
        "purpose": [
            "correct source chronology",
            "prove the electrical dataset overlaps the TSC intervention",
            "establish the correct regime boundary for the next water/WUE stage",
        ],
        "monthly": months,
    }
    if audit["comparison_with_sickinger_quantities_that_are_actually_reported"]["IT_mean_difference_kw"] is not None:
        pass
    jdump(ANALYSIS / "THERMOSYPHON_COMMISSIONING_AUDIT.json", audit)
    pd.DataFrame(months).to_csv(ANALYSIS / "THERMOSYPHON_COMMISSIONING_AUDIT.csv", index=False)
    return audit


def daily_weekly(h: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    v = h[h.valid_all].copy()
    v["day"] = v.hour.dt.floor("D")
    daily = (
        v.groupby("day")
        .agg(
            n_hours=("hour", "size"),
            it_kw=("it_power_kw", "mean"),
            cooling_kw=("cooling_kw", "mean"),
            hvac_kw=("hvac_kw", "mean"),
            pump_kw=("pump_kw", "mean"),
            plug_kw=("plug_and_light_kw", "mean"),
            aux_kw=("aux_source_kw", "mean"),
            pue=("pue", "mean"),
            pue_recon=("pue_reconstructed", "mean"),
            tdb_c=("tdb_c", "mean"),
            twb_c=("twb_c", "mean"),
        )
        .reset_index()
    )
    daily["week"] = daily.day.dt.to_period("W-SUN").dt.start_time
    weekly = (
        daily.groupby("week")
        .agg(
            n_days=("day", "size"),
            it_kw=("it_kw", "mean"),
            cooling_kw=("cooling_kw", "mean"),
            hvac_kw=("hvac_kw", "mean"),
            pump_kw=("pump_kw", "mean"),
            plug_kw=("plug_kw", "mean"),
            aux_kw=("aux_kw", "mean"),
            pue=("pue", "mean"),
        )
        .reset_index()
    )
    return daily, weekly


def window_scan(daily: pd.DataFrame, window: int) -> pd.DataFrame:
    d = daily.sort_values("day").reset_index(drop=True)
    rows = []
    start = pd.Timestamp("2023-10-01")
    end = pd.Timestamp("2024-07-31")
    min_days = int(np.ceil(0.8 * window))
    for ts in pd.date_range(start, end, freq="D"):
        before = d[(d.day >= ts - pd.Timedelta(days=window)) & (d.day < ts)]
        after = d[(d.day >= ts) & (d.day < ts + pd.Timedelta(days=window))]
        persist = d[(d.day >= ts + pd.Timedelta(days=window)) & (d.day < ts + pd.Timedelta(days=2 * window))]
        if len(before) < min_days or len(after) < min_days:
            continue
        rec = {
            "candidate": str(ts.date()),
            "window_days": window,
            "n_before": int(len(before)),
            "n_after": int(len(after)),
            "hvac_before": float(before.hvac_kw.mean()),
            "hvac_after": float(after.hvac_kw.mean()),
            "hvac_delta": float(after.hvac_kw.mean() - before.hvac_kw.mean()),
            "cooling_delta": float(after.cooling_kw.mean() - before.cooling_kw.mean()),
            "pump_delta": float(after.pump_kw.mean() - before.pump_kw.mean()),
            "plug_delta": float(after.plug_kw.mean() - before.plug_kw.mean()),
            "aux_delta": float(after.aux_kw.mean() - before.aux_kw.mean()),
            "it_delta": float(after.it_kw.mean() - before.it_kw.mean()),
            "pue_delta": float(after.pue.mean() - before.pue.mean()),
            "hvac_persist": float(persist.hvac_kw.mean()) if len(persist) >= min_days else None,
            "persistent": bool(len(persist) >= min_days and persist.hvac_kw.mean() > 0.5 * after.hvac_kw.mean()),
        }
        rows.append(rec)
    return pd.DataFrame(rows)


def native_hvac_artifacts(center: pd.Timestamp) -> dict:
    p = pd.read_parquet(POWER_PARQUET, columns=["ts", "hvac_kw", "cooling_kw", "pump_kw", "plug_and_light_kw", "it_power_kw"])
    p["ts"] = pd.to_datetime(p.ts)
    lo, hi = center - pd.Timedelta(days=21), center + pd.Timedelta(days=21)
    w = p[(p.ts >= lo) & (p.ts < hi)].sort_values("ts")
    x = w.hvac_kw.to_numpy(float)
    finite = np.isfinite(x)
    xf = x[finite]
    dt = w.ts.diff().dt.total_seconds()
    # unique rounding / quantization
    if len(xf) == 0:
        return {"n": 0}
    rounded = np.round(xf, 6)
    n_unique = int(len(np.unique(rounded)))
    diffs = np.diff(np.sort(np.unique(np.round(xf, 3))))
    diffs = diffs[diffs > 0]
    # consecutive native diffs
    cdiff = np.diff(xf)
    # pre/post 7-day native means
    pre = w[(w.ts >= center - pd.Timedelta(days=7)) & (w.ts < center)]
    post = w[(w.ts >= center) & (w.ts < center + pd.Timedelta(days=7))]
    pre_m = float(pre.hvac_kw.mean()) if len(pre) else None
    post_m = float(post.hvac_kw.mean()) if len(post) else None
    ratio = None if not pre_m else (None if pre_m == 0 else (post_m / pre_m if post_m is not None else None))
    offset = None if pre_m is None or post_m is None else post_m - pre_m
    # other components 7-day
    def mcol(df, c):
        return float(df[c].mean()) if len(df) and df[c].notna().any() else None

    return {
        "window": [str(lo), str(hi)],
        "n_native_rows": int(len(w)),
        "n_finite_hvac": int(finite.sum()),
        "n_negative_hvac": int((xf < 0).sum()) if len(xf) else 0,
        "n_zero_hvac": int((xf == 0).sum()) if len(xf) else 0,
        "n_unique_hvac_1e6": n_unique,
        "median_positive_unique_step_rounded_1e3": float(np.median(diffs)) if len(diffs) else None,
        "native_dt_s_median": float(dt.median()) if dt.notna().any() else None,
        "n_gaps_gt_180s": int((dt > 180).sum()),
        "longest_gap_s": float(dt.max()) if dt.notna().any() else None,
        "abs_consecutive_hvac_diff_p50": float(np.median(np.abs(cdiff))) if len(cdiff) else None,
        "abs_consecutive_hvac_diff_p99": float(np.quantile(np.abs(cdiff), 0.99)) if len(cdiff) else None,
        "seven_day_pre_mean_hvac": pre_m,
        "seven_day_post_mean_hvac": post_m,
        "seven_day_ratio_post_over_pre": ratio,
        "seven_day_offset_post_minus_pre": offset,
        "exact_integer_multiplicative_scaling_2_or_10": bool(ratio is not None and any(abs(ratio - k) < 0.05 for k in (2, 5, 10))),
        "seven_day_pre_post_other": {
            "cooling_pre": mcol(pre, "cooling_kw"),
            "cooling_post": mcol(post, "cooling_kw"),
            "pump_pre": mcol(pre, "pump_kw"),
            "pump_post": mcol(post, "pump_kw"),
            "plug_pre": mcol(pre, "plug_and_light_kw"),
            "plug_post": mcol(post, "plug_and_light_kw"),
            "it_pre": mcol(pre, "it_power_kw"),
            "it_post": mcol(post, "it_power_kw"),
        },
        "abrupt_baseline_insertion_signature": "large persistent mean offset without matching drop in another listed component; native series remains continuously sampled",
    }


def event_timeline() -> pd.DataFrame:
    rows = [
        {
            "date_start": "2023-03",
            "date_end": "2023-03",
            "event": "Kestrel Phase I equipment arrival (CPU nodes and parallel storage) at ESIF HPC data center",
            "evidence_source": "NREL news 2024-08-19 'Kestrel Supercomputer Ready To Energize Renewable Energy Research'",
            "source_type": "NREL/NLR official news",
            "direct_physical_relevance": "facility IT/power/cooling load preparation; not an HVAC-meter definition",
            "attribution_confidence": "HIGH as CPU-arrival date; LOW as HVAC-step cause",
            "notes": "CPU phase installed summer 2023; early users then; opened for all projects at start of FY2024.",
        },
        {
            "date_start": "2023-summer",
            "date_end": "2023-09",
            "event": "Kestrel CPU phase installed; early-user availability",
            "evidence_source": "NREL news 2024-08-19",
            "source_type": "NREL/NLR official news",
            "direct_physical_relevance": "IT load increase possible; HVAC electrical mapping unknown",
            "attribution_confidence": "MEDIUM date precision (season only)",
            "notes": "Do not treat summer 2023 CPU install as the 2024 HVAC step.",
        },
        {
            "date_start": "2023-10-01",
            "date_end": "2023-10-01",
            "event": "Kestrel opened for all projects at start of FY2024",
            "evidence_source": "NREL news 2024-08-19",
            "source_type": "NREL/NLR official news",
            "direct_physical_relevance": "production CPU load",
            "attribution_confidence": "HIGH as policy date; LOW as HVAC-step cause",
            "notes": "FY2024 begins 1 Oct 2023.",
        },
        {
            "date_start": "2023",
            "date_end": "2024",
            "event": "ESIF HPC data-center electrical and mechanical work to raise capacity from 5 MW to 7.5 MW of electrical AND cooling capacity",
            "evidence_source": "NLR HPC announcement 2024-06-11 'Recent Outages - Continuity of Operations Plan'",
            "source_type": "NLR official HPC operations announcement",
            "direct_physical_relevance": "HIGH: electrical and mechanical plant work explicitly cited as driver of 2024 planned outages",
            "attribution_confidence": "HIGH that such work occurred in 2024; LOW that a named device is the HVAC kW step",
            "notes": "NLR: 'Many of the planned outages were driven by electrical and mechanical work required to upgrade the ESIF data center from 5MW to 7.5MW of electrical and cooling capacity.' Typo 'mechancial' in source. Secondary contractor profile (EEI, not NLR) describes a 2023 HPCDC expansion commissioning +2.5 MW cooling; not used as the primary date.",
        },
        {
            "date_start": "2024-01-29",
            "date_end": "2024-02-09",
            "event": "Kestrel planned outage for maintenance and Phase II GPU integration",
            "evidence_source": "NLR HPC announcement 2024-01-12 'Kestrel Planned Outage and Phase II GPU Integration'",
            "source_type": "NLR official HPC operations announcement",
            "direct_physical_relevance": "IT/system integration outage; GPU nodes integrated then tested later",
            "attribution_confidence": "HIGH as outage window; LOW as HVAC-step cause",
            "notes": "Tentative start Monday Jan 29 07:00; scheduled through Friday Feb 9. GPU nodes then undergo functionality/acceptance testing for production later in FY24.",
        },
        {
            "date_start": "2024-02",
            "date_end": "2024-02",
            "event": "Arrival/integration of Kestrel GPU nodes (NREL news: 132 4×H100 nodes)",
            "evidence_source": "NREL news 2024-08-19; NLR 2024-01-12 outage announcement",
            "source_type": "NREL/NLR official",
            "direct_physical_relevance": "new IT heat/electrical load class; not proof of HVAC meter change",
            "attribution_confidence": "HIGH that GPUs arrived Feb 2024; document discrepancy on node count (see notes)",
            "notes": "NREL 2024-08-19 and DCD 2024-08-21: 132 GPU nodes × 4 H100. Current NLR Kestrel System Configuration page lists 156 GPU-accelerated nodes. Discrepancy preserved; not silently reconciled. Do not infer HVAC jump = GPU heat.",
        },
        {
            "date_start": "2024-05",
            "date_end": "2024-05",
            "event": "GPU node testing/validation completed; early users invited",
            "evidence_source": "NREL news 2024-08-19",
            "source_type": "NREL/NLR official news",
            "direct_physical_relevance": "early GPU production load possible",
            "attribution_confidence": "MEDIUM date precision (month)",
            "notes": "NLR 2024-06-11 still said GPU nodes 'coming soon' / early testers in next couple of weeks — public documents are not identical on GA timing.",
        },
        {
            "date_start": "2024-06-11",
            "date_end": "2024-06-11",
            "event": "NLR states GPU nodes in final acceptance testing; Eagle decommission date confirmed",
            "evidence_source": "NLR HPC announcement 2024-06-11 'Kestrel GPUs and Eagle End of Service'",
            "source_type": "NLR official HPC operations announcement",
            "direct_physical_relevance": "operational timeline marker",
            "attribution_confidence": "HIGH as announcement date",
            "notes": "Same day as the 5–7.5 MW outage-explanation note.",
        },
        {
            "date_start": "2024-06-15",
            "date_end": "2024-06-15",
            "event": "Eagle decommissioning",
            "evidence_source": "NLR HPC announcement 2024-06-11",
            "source_type": "NLR official HPC operations announcement",
            "direct_physical_relevance": "removal of Eagle IT load; HVAC mapping unknown",
            "attribution_confidence": "HIGH as decommission date; LOW as HVAC-step cause",
            "notes": "Do not call the HVAC step Eagle-caused from coincidence. Eagle storage access intended through 2024-09-30.",
        },
        {
            "date_start": "2024-08-19",
            "date_end": "2024-08-21",
            "event": "Public statements that Kestrel full buildout / GPU production availability is complete",
            "evidence_source": "NREL news 2024-08-19; Data Center Dynamics 2024-08-21 (secondary report of NREL completion)",
            "source_type": "NREL official news plus trade press",
            "direct_physical_relevance": "GPU production era; TEST split begins 2024-08-29",
            "attribution_confidence": "HIGH that summer 2024 is full-buildout messaging; exact GA instant not unique across documents",
            "notes": "Experiment GPU_GA marker 2024-08-21 follows the DCD date and is a documented-timing epoch, not a residual-mined breakpoint.",
        },
        {
            "date_start": "2012-2014",
            "date_end": "2014",
            "event": "COUNTERPOINT: original ESIF HPC design already included main fan-wall air-handling units",
            "evidence_source": "NREL ESIF HPC Data Center fact sheet OSTI 1050124; dataset README hvac_kw definition",
            "source_type": "NREL/NLR primary design/meter documentation",
            "direct_physical_relevance": "HVAC meter already defined to capture fan walls, electrical-room fan coils, make-up air",
            "attribution_confidence": "HIGH that fan walls are original; therefore 2024 HVAC jump ≠ new fan walls unless a primary 2024 document says so",
            "notes": "No primary NLR/NREL document in this audit states that new/additional fan-wall equipment or a new HVAC meter was commissioned in 2024.",
        },
    ]
    df = pd.DataFrame(rows)
    df.to_csv(ANALYSIS / "ESIF_2024_DOCUMENTED_EVENT_TIMELINE.csv", index=False)
    return df


def hvac_audit(h: pd.DataFrame, daily: pd.DataFrame) -> dict:
    scans = {w: window_scan(daily, w) for w in (14, 28, 56)}
    best = {}
    for w, df in scans.items():
        persist = df[df.persistent]
        use = persist if not persist.empty else df
        i = use.hvac_delta.idxmax()
        best[str(w)] = use.loc[i].to_dict()
    # component reallocation / total boundary around primary 28-day max
    b28 = best["28"]
    cand = pd.Timestamp(b28["candidate"])
    native = native_hvac_artifacts(cand)
    # yearly means (descriptive; should match frozen EPOCH file)
    v = h[h.valid_all]
    yearly = v.groupby(v.hour.dt.year).hvac_kw.mean().to_dict()
    yearly = {str(k): float(x) for k, x in yearly.items()}
    # 2023 vs 2024 calendar
    y2023 = v[v.hour.dt.year == 2023]
    y2024 = v[v.hour.dt.year == 2024]
    hvac_delta_28 = float(b28["hvac_delta"])
    aux_delta_28 = float(b28["aux_delta"])
    cooling_delta_28 = float(b28["cooling_delta"])
    pump_delta_28 = float(b28["pump_delta"])
    plug_delta_28 = float(b28["plug_delta"])
    offset_sum = cooling_delta_28 + pump_delta_28 + plug_delta_28
    reclass = abs(offset_sum + hvac_delta_28) < 0.25 * abs(hvac_delta_28) and abs(aux_delta_28) < 0.25 * abs(hvac_delta_28)
    total_rises = aux_delta_28 > 0.5 * hvac_delta_28 and hvac_delta_28 > 20
    pue_rises = float(b28["pue_delta"]) > 0.01
    # source definition history
    source_def = {
        "current_readme_hvac": "fan walls, fan coils that support the data center electrical rooms, and the make-up air unit",
        "nlr_pue_page_hvac": "same wording as README (retrieved 2026-09-02)",
        "osti_3015212_hvac": "same wording",
        "catalog_power_resource_version": 3,
        "public_changelog_showing_2024_hvac_redefinition": False,
        "cannot_rule_out_unpublished_meter_boundary_change": True,
    }
    if reclass and not total_rises:
        disposition = "METER_CATEGORY_RECLASSIFICATION_SUPPORTED"
    elif total_rises and not reclass:
        disposition = "PHYSICAL_OR_OPERATIONAL_INFRASTRUCTURE_CHANGE_SUPPORTED_EXACT_CAUSE_UNRESOLVED"
        if native.get("exact_integer_multiplicative_scaling_2_or_10"):
            disposition = "MULTIPLE_EXPLANATIONS_REMAIN"
    else:
        disposition = "MULTIPLE_EXPLANATIONS_REMAIN"
    rec = {
        "post_hoc_only": True,
        "used_for_model_fitting": False,
        "used_to_revise_TEST": False,
        "primary_28day_transition_candidate": b28,
        "sensitivity_14_56": {"14": best["14"], "56": best["56"]},
        "yearly_hvac_mean_kw": yearly,
        "calendar_2023_vs_2024": {
            "hvac_2023": float(y2023.hvac_kw.mean()) if len(y2023) else None,
            "hvac_2024": float(y2024.hvac_kw.mean()) if len(y2024) else None,
            "aux_2023": float(y2023.aux_source_kw.mean()) if len(y2023) else None,
            "aux_2024": float(y2024.aux_source_kw.mean()) if len(y2024) else None,
            "pue_2023": float(y2023.pue.mean()) if len(y2023) else None,
            "pue_2024": float(y2024.pue.mean()) if len(y2024) else None,
            "it_2023": float(y2023.it_power_kw.mean()) if len(y2023) else None,
            "it_2024": float(y2024.it_power_kw.mean()) if len(y2024) else None,
        },
        "A_component_reallocation_test": {
            "hvac_delta_28d": hvac_delta_28,
            "cooling_delta_28d": cooling_delta_28,
            "pump_delta_28d": pump_delta_28,
            "plug_delta_28d": plug_delta_28,
            "other_components_delta_sum": offset_sum,
            "aux_delta_28d": aux_delta_28,
            "reclassification_plausible": bool(reclass),
            "interpretation": "If HVAC rose while others fell by a comparable amount and AUX stayed stable, category reclassification would be plausible.",
        },
        "B_total_boundary_test": {
            "aux_rises_with_hvac": bool(total_rises),
            "pue_rises": bool(pue_rises),
            "pue_delta_28d": float(b28["pue_delta"]),
            "pure_within_category_reclassification_disfavored": bool(total_rises),
        },
        "C_meter_artifact_check": native,
        "D_source_definition_history": source_def,
        "E_event_compatibility": {
            "do_not_infer_causality_from_proximity": True,
            "temporally_compatible_documented_events": [
                "2024 electrical/mechanical 5→7.5 MW capacity work (NLR 2024-06-11)",
                "Jan 29–Feb 9 2024 Kestrel Phase-II GPU integration outage",
                "Feb 2024 GPU node arrival",
                "June 15 2024 Eagle decommission",
            ],
            "not_supported_as_narrow_causes": [
                "GPU-caused HVAC",
                "Eagle-caused HVAC",
                "new-fan-wall HVAC",
            ],
            "fan_wall_counterpoint": "Original ESIF design already included fan-wall AHUs (NREL fact sheet OSTI 1050124).",
        },
        "HVAC_REGIME_CAUSE": disposition,
        "confidence": {
            "HVAC_level_shift_exists": "HIGH",
            "stationary_IT_weather_fails_across_shift": "HIGH",
            "broader_facility_operational_or_infrastructure_regime_change_compatible": "MEDIUM_HIGH" if total_rises else "MEDIUM",
            "exact_device_or_event": "LOW",
        },
        "closed_production_models": {
            "epoch_aware_HVAC_model": "NOT_FITTED",
            "reason": "hypothesis became salient after TEST; no clean new independent holdout",
        },
    }
    jdump(ANALYSIS / "HVAC_2024_REGIME_ATTRIBUTION.json", rec)
    # compact csv of scans
    scans[28].assign(scan="28").to_csv(ANALYSIS / "HVAC_2024_REGIME_ATTRIBUTION.csv", index=False)
    return rec, scans


def patch_residual_and_epoch(h: pd.DataFrame, tsc: dict) -> None:
    resid = json.loads((ANALYSIS / "RESIDUAL_DIAGNOSTICS.json").read_text())
    acf = resid["dev_cooling_acf"]
    # preserve ACF exactly
    new_resid = {
        "dev_cooling_acf": acf,
        "current_input_models_fail_predeclared_WAPE_gt_0.25": True,
        "fallback_trigger_condition_met": True,
        "lagged_input_extension_tested": False,
        "protocol_deviation": False,
        "target_lag_used": False,
        "optional_fallback_deliberately_not_exercised": True,
        "TEST_untouched": True,
        "explanation": (
            "The frozen protocol made a lagged-INPUT diagnostic optional if current-input models clearly failed "
            "and a consistent lag signature appeared on DEV. That trigger was met (cooling DEV daily-energy WAPE > 0.25 "
            "and ACF at 24 h > 0.5). The optional fallback was deliberately not exercised because the dominant "
            "out-of-time failure is an HVAC level shift, not cooling lag, and there is no clean new independent holdout. "
            "No lagged TARGET was used. No TEST-driven model change occurred. This is therefore not a protocol deviation."
        ),
        "COOLING_DYNAMICS_UNRESOLVED": True,
        "reason_no_lagged_target": "lagged TARGET values forbidden; lagged inputs only if DEV consistently fails; optional and not used",
    }
    jdump(ANALYSIS / "RESIDUAL_DIAGNOSTICS.json", new_resid)

    ep = json.loads((ANALYSIS / "EPOCH_STABILITY.json").read_text())
    ep["epochs"]["thermosyphon_commissioning"] = "IN_SAMPLE"
    ep["thermosyphon"] = {
        "in_sample": True,
        "pre_tsc_available": "2016-06-12 through 2016-07-31",
        "commissioning_transition": "2016-08 (month-level; Sickinger Fig. 3 caption operational date 2016-08-16 is recorded but not used as a fitted breakpoint)",
        "first_full_tsc_year": "2016-09-01 through 2017-08-31",
        "prior_false_statement": "NOT_IN_SAMPLE (ESIF thermosyphon predates 2015 start) — CORRECTED",
        "common_valid_power_weather_begins": "2016-06-12",
        "audit": "analysis/THERMOSYPHON_COMMISSIONING_AUDIT.json",
    }
    # preserve TEST_by_epoch, yearly HVAC, DEV vs TEST exactly
    jdump(ANALYSIS / "EPOCH_STABILITY.json", ep)


def write_lessons_and_closed() -> None:
    jdump(
        ANALYSIS / "POSTTEST_VALIDATION_LESSONS.json",
        {
            "original_46_fold_expanding_CV": "UNCHANGED",
            "do_not_apply_retroactively": True,
            "what_happened": (
                "Equal-weight mean of 46 expanding 60-day DEV folds is dominated by the long 2016–2023 HVAC regime "
                "(~8–10 kW). A persistent 2024 HVAC level shift occupies only late DEV folds, so mean CV selected F0 "
                "with CV daily-energy WAPE 0.147 while full-DEV F0 daily-energy WAPE was already 0.986. TEST then failed."
            ),
            "future_facility_time_series_experiments_should_predeclare_both": [
                "mean rolling-origin CV performance",
                "latest-regime / final-pretest-epoch stability",
            ],
            "this_experiment": "selection rule was not changed after TEST",
        },
    )
    jdump(
        ANALYSIS / "CLOSED_POSTTEST_HYPOTHESES.json",
        {
            "epoch_aware_HVAC_model": "NOT_FITTED",
            "lagged_input_cooling_model": "NOT_FITTED",
            "lagged_target_model": "FORBIDDEN_AND_NOT_USED",
            "F5_plus": "NOT_FITTED",
            "post_TEST_feature_selection": "NOT_PERFORMED",
            "COOLING_DYNAMICS_UNRESOLVED": True,
            "reason": (
                "These hypotheses became salient after TEST. There is no clean new independent holdout. "
                "The untouched negative TEST is more valuable than a repaired model evaluated on already-inspected data."
            ),
        },
    )


def main() -> None:
    os.environ.setdefault("PYTHONNOUSERSITE", "1")
    init = load_freeze()
    assert_numerical_freeze(init, also_runner=False)
    print("hourly…", flush=True)
    h = ensure_hourly()
    print("thermosyphon…", flush=True)
    tsc = thermosyphon_audit(h)
    print("timeline…", flush=True)
    event_timeline()
    print("hvac daily/weekly…", flush=True)
    daily, weekly = daily_weekly(h)
    daily.to_csv(ANALYSIS / "HVAC_2023_2025_DAILY_SUMMARY.csv", index=False)
    weekly.to_csv(ANALYSIS / "HVAC_2023_2025_WEEKLY_SUMMARY.csv", index=False)
    print("hvac attribution…", flush=True)
    hvac, _scans = hvac_audit(h, daily)
    print("residual/epoch patch…", flush=True)
    patch_residual_and_epoch(h, tsc)
    write_lessons_and_closed()
    assert_numerical_freeze(init, also_runner=False)
    summary = {
        "tsc_in_sample": tsc["thermosyphon_in_sample"],
        "tsc_first_year_IT": tsc["first_full_tsc_year"].get("it_kw_mean"),
        "tsc_first_year_PUE": tsc["first_full_tsc_year"].get("pue_source_mean"),
        "hvac_candidate_28d": hvac["primary_28day_transition_candidate"]["candidate"],
        "hvac_delta_28d": hvac["primary_28day_transition_candidate"]["hvac_delta"],
        "aux_delta_28d": hvac["primary_28day_transition_candidate"]["aux_delta"],
        "reclass": hvac["A_component_reallocation_test"]["reclassification_plausible"],
        "aux_rises": hvac["B_total_boundary_test"]["aux_rises_with_hvac"],
        "cause": hvac["HVAC_REGIME_CAUSE"],
    }
    print(json.dumps(summary, indent=2), flush=True)
    print("CLOSURE_CORE_DONE", flush=True)


if __name__ == "__main__":
    main()
