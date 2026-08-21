"""Build the auditable pipeline-reporting layer from existing artifacts.

Does not download data, does not modify raw/canonical inputs, and does not
retune models. Fails clearly if required processed outputs are missing.

Usage:
    python src/build_pipeline_report.py
    python run_prineville.py report
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch, Patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline_report_catalog import (
    BOUNDARY_VOCABULARY,
    COVERAGE_STATUSES,
    DOC_VS_CODE_DISCREPANCIES,
    HOLDOUT_YEARS,
    MODEL_COLUMNS,
    PROVENANCE_CLASSES,
    QUANTITY_COLUMNS,
    REPORT_SEED,
    SOURCE_COLUMNS,
    TRAIN_END_YEAR,
    model_io_edges,
    model_registry,
    parameter_registry,
    quantity_registry,
    source_inventory,
    source_quantity_edges,
    validate_lineage_ids,
)
from pipeline_report_results import (
    apply_runtime_results,
    audit_report_consistency,
    load_result_claims,
    weather_driver_audit,
    weather_unresolved_count,
)
import pipeline_report_diagrams as _diagrams

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "pipeline_report"
FIG = OUT / "figures"
DOCS = ROOT / "docs"
RNG_SEED = REPORT_SEED

REQUIRED_ARTIFACTS = [
    ROOT / "data" / "canonical" / "meta_prineville_annual.csv",
    ROOT / "data" / "processed" / "weather_hourly.csv",
    ROOT / "data" / "processed" / "water" / "prineville_water_monthly_context.csv",
    ROOT / "outputs" / "conditional_annual_compare.csv",
    ROOT / "outputs" / "conditional_water_model.csv",
    ROOT / "outputs" / "hourly_conditional_reconstruction.csv",
    ROOT / "outputs" / "stochastic_proxy_annual_summary.csv",
    ROOT / "outputs" / "stochastic_proxy_water_model_diagnostics.csv",
    ROOT / "outputs" / "egrid_meta_annual_compare.csv",
    ROOT / "outputs" / "pacw_carbon_shape_compare.csv",
    ROOT / "data" / "canonical" / "campus_events_seed.csv",
]

COLORS = {
    "reported": "#2166ac",
    "measured": "#2166ac",
    "derived": "#4dac26",
    "fitted": "#e66101",
    "proxy": "#f1a340",
    "scenario": "#7b3294",
    "simulated": "#c51b7d",
    "unavailable": "#bdbdbd",
    "not_necessary": "#000000",
    "missing": "#d9d9d9",
    "holdout": "#d73027",
    "train": "#4575b4",
}

FIGURE3_DISPLAY_PREDICTORS = (
    "training_mean",
    "conditional_global_scale",
    "energy_null_frozen_nnls",
)
FIGURE3_FULL_AUDIT_PREDICTORS = (
    "training_mean",
    "training_median",
    "persistence_2022",
    "conditional_global_scale",
    "energy_null_frozen_nnls",
    "energy_null_ensemble_median",
    "evap_physics_frozen_nnls",
    "two_component_frozen_nnls",
)

FIGURE2_DOC_INCLUDE_TYPES = {
    "electric_service": ("power/cooling", "First MESA / Schedule 48 service"),
    "campus_buildout": ("campus/buildout", "Four initial PRN buildings coming online"),
    "planned_facility": ("campus/buildout", "LTEZ ~200k ft² data-center agreement"),
    "infrastructure_agreement": ("campus/buildout", "City/County/Vitesse infrastructure agreement"),
    "water_sewer_agreement": ("water/infrastructure", "Water/sewer service agreement"),
    "water_sewer_amendment": ("water/infrastructure", "Water/sewer agreement amendment"),
    "campus_announcement": ("campus/buildout", "CCO campus announced"),
    "construction_state": ("campus/buildout", "CCO1&2 under construction"),
    "planning": ("campus/buildout", "PRN1 network-core addition (planning)"),
    "water_resiliency_agreement": ("water/infrastructure", "Waterline resiliency agreement"),
    "water_resiliency_amendment": ("water/infrastructure", "Waterline resiliency 70/30 amendment"),
}
FIGURE2_PERMIT_INCLUDE_TYPES = {
    "infrastructure_final": ("water/infrastructure", "Pump house final"),
    "building_final": ("campus/buildout", "Building final"),
    "partial_building_final": ("campus/buildout", "Partial building final"),
    "partial_mechanical_final": ("power/cooling", "Partial mechanical final"),
    "site_utilities_final": ("water/infrastructure", "Water/sewer/storm finals"),
    "fire_life_safety_final": ("campus/buildout", "Fire/life-safety final"),
    "mechanical_final": ("power/cooling", "Mechanical final"),
    "mechanical_commissioning_test": ("power/cooling", "PRN1 hydronic test (chillers/CRAH excluded)"),
    "mechanical_pre_tco_walk": ("power/cooling", "PRN1 mechanical pre-TCO walk"),
    "chiller_operational": ("power/cooling", "PRN1 additional chiller operational"),
    "electrical_final": ("power/cooling", "Electrical final"),
    "plumbing_final": ("water/infrastructure", "PRN1 plumbing final"),
    "phase2_electrical_rough_in": ("power/cooling", "PRN1 Phase 2 electrical rough-in (pending)"),
}
FIGURE2_PERMIT_LABEL_BY_DATE_TYPE = {
    ("2010-12-16", "infrastructure_final"): "Pump house final",
    ("2011-04-14", "building_final"): "Initial campus building finals",
    ("2011-08-24", "building_final"): "Campus sections C&D finals",
    ("2020-03-18", "partial_mechanical_final"): "CCO1 partial mechanical (Admin/E)",
    ("2020-03-20", "partial_building_final"): "CCO1 partial building (Admin/E-core)",
    ("2020-03-24", "partial_mechanical_final"): "CCO1 data halls A&B partial mechanical",
    ("2020-08-03", "site_utilities_final"): "CCO1/2 water/sewer/storm finals",
    ("2020-08-05", "fire_life_safety_final"): "CCO1/2 fire/life-safety final",
    ("2020-08-14", "partial_building_final"): "CCO1/2 partial building A&B",
    ("2020-10-21", "partial_building_final"): "CCO1 area D partial building",
    ("2020-10-23", "partial_building_final"): "CCO1 area C partial building",
    ("2021-06-28", "building_final"): "CCO1&2 full building final",
    ("2021-07-08", "mechanical_final"): "CCO1&2 full mechanical final",
    ("2023-09-21", "mechanical_commissioning_test"): "PRN1 hydronic test (chillers/CRAH excluded)",
    ("2023-12-11", "mechanical_pre_tco_walk"): "PRN1 mechanical pre-TCO walk",
    ("2024-02-02", "chiller_operational"): "PRN1 additional chiller operational",
    ("2024-02-13", "electrical_final"): "PRN1 addition electrical/mechanical finals",
    ("2024-02-13", "mechanical_final"): "PRN1 addition electrical/mechanical finals",
    ("2024-02-20", "building_final"): "PRN1 addition building final",
    ("2024-02-22", "plumbing_final"): "PRN1 plumbing final",
    ("2024-03-14", "phase2_electrical_rough_in"): "PRN1 Phase 2 electrical rough-in (pending)",
}
FIGURE2_GROUP_LABELS = {
    ("2011-04-14", "campus/buildout"): "Initial campus building finals",
    ("2018-08-07", "water/infrastructure"): "Water/sewer agreement amendments",
    ("2024-02-13", "power/cooling"): "PRN1 addition electrical/mechanical finals",
}
FIGURE2_EVENT_CATEGORIES = ("campus/buildout", "water/infrastructure", "power/cooling")
HIGH_CONFIDENCE = {"high", "very_high"}


def check_prerequisites() -> None:
    missing = [p.relative_to(ROOT).as_posix() for p in REQUIRED_ARTIFACTS if not p.exists()]
    if missing:
        lines = "\n".join(f"  - {m}" for m in missing)
        raise FileNotFoundError(
            "Pipeline report cannot run; required processed artifacts are missing "
            "(this command does not download data or rebuild models):\n"
            f"{lines}\n"
            "Rebuild with the relevant `python run_prineville.py` command first "
            "(conditional / simulate / egrid / water-context), then rerun report."
        )


def _existing_paths(spec: str) -> str:
    """Resolve documented paths/globs to existing files; do not invent names."""
    if not spec.strip():
        return ""
    found: list[str] = []
    for token in [t.strip() for t in spec.split(";") if t.strip()]:
        p = ROOT / token if not token.startswith("/") else Path(token)
        if p.is_file():
            try:
                found.append(p.relative_to(ROOT).as_posix())
            except ValueError:
                found.append(str(p))
        elif p.is_dir():
            kids = sorted(
                q.relative_to(ROOT).as_posix()
                for q in p.rglob("*")
                if q.is_file() and q.stat().st_size > 0
            )
            if kids:
                if len(kids) <= 8:
                    found.append("; ".join(kids))
                else:
                    found.append(f"{p.relative_to(ROOT).as_posix()}/ ({len(kids)} files)")
            else:
                found.append(f"{p.relative_to(ROOT).as_posix()}/ (directory exists; no files listed)")
        else:
            found.append(f"{token} (path not found locally)")
    return "; ".join(found)


def write_source_inventory() -> pd.DataFrame:
    rows = []
    for r in source_inventory():
        item = dict(r)
        item["local_raw_files"] = _existing_paths(r["local_raw_files"]) if r["local_raw_files"] else ""
        item["in_source_manifest"] = "yes" if r["in_source_manifest"] else "no"
        rows.append(item)
    df = pd.DataFrame(rows, columns=SOURCE_COLUMNS)
    df.to_csv(OUT / "data_source_inventory.csv", index=False, quoting=csv.QUOTE_MINIMAL)
    return df


def write_quantity_registry(rows=None) -> pd.DataFrame:
    df = pd.DataFrame(rows if rows is not None else quantity_registry(), columns=QUANTITY_COLUMNS)
    bad = set(df["provenance_class"]) - set(PROVENANCE_CLASSES)
    if bad:
        raise ValueError(f"Non-canonical provenance labels: {bad}")
    if df["quantity_id"].duplicated().any():
        raise ValueError("Duplicate quantity_id")
    df.to_csv(OUT / "model_quantity_registry.csv", index=False)
    return df


def write_model_registry(rows=None) -> pd.DataFrame:
    df = pd.DataFrame(rows if rows is not None else model_registry(), columns=MODEL_COLUMNS)
    if df["model_id"].duplicated().any():
        raise ValueError("Duplicate model_id")
    df.to_csv(OUT / "model_registry.csv", index=False)
    return df


def write_source_quantity_edges() -> pd.DataFrame:
    validate_lineage_ids()
    df = pd.DataFrame(source_quantity_edges())
    if df.duplicated(["source_id", "quantity_id", "role"]).any():
        raise ValueError("Duplicate source_quantity edge keys")
    df.to_csv(OUT / "source_quantity_edges.csv", index=False)
    return df


def write_model_io_edges() -> pd.DataFrame:
    df = pd.DataFrame(model_io_edges())
    if df.duplicated(["model_id", "quantity_id", "io_role"]).any():
        raise ValueError("Duplicate model_io edge keys")
    energy_evap = df[
        df["model_id"].eq("M_WATER_ENERGY_NULL") & df["quantity_id"].eq("Q_W_EVAP")
    ]
    if len(energy_evap):
        raise ValueError("Energy-only water model must not take evaporation as I/O")
    df.to_csv(OUT / "model_io_edges.csv", index=False)
    return df


def write_parameter_registry(rows=None) -> pd.DataFrame:
    df = pd.DataFrame(rows if rows is not None else parameter_registry())
    df.to_csv(OUT / "model_parameter_registry.csv", index=False)
    return df


def _holdout_metrics(pred: np.ndarray, obs: np.ndarray, years: np.ndarray) -> dict:
    pred = np.asarray(pred, dtype=float)
    obs = np.asarray(obs, dtype=float)
    err = pred - obs
    mae = float(np.mean(np.abs(err)))
    mape = float(np.mean(np.abs(err) / obs) * 100.0)
    pct = 100.0 * err / obs
    out = {
        "MAE_m3": mae,
        "MAPE_pct": mape,
    }
    for y, p in zip(years.astype(int), pct):
        out[f"pct_error_{y}"] = float(p)
    return out


def write_water_holdout_baseline_compare() -> pd.DataFrame:
    """Frozen naive baselines vs existing water predictors on 2023–2024 only."""
    cond = pd.read_csv(ROOT / "outputs" / "conditional_annual_compare.csv")
    stoch = pd.read_csv(ROOT / "outputs" / "stochastic_proxy_annual_summary.csv")
    diag = pd.read_csv(ROOT / "outputs" / "stochastic_proxy_water_model_diagnostics.csv")

    train = cond[
        cond["split"].eq("train") & cond["water_withdrawal_m3_reported"].notna()
    ].sort_values("year")
    hold = cond[
        cond["split"].eq("holdout") & cond["water_withdrawal_m3_reported"].notna()
    ].sort_values("year")
    stoch_h = stoch[stoch["year"].isin(hold["year"])].sort_values("year")
    if list(stoch_h["year"].astype(int)) != list(hold["year"].astype(int)):
        raise ValueError("Stochastic and conditional holdout years do not align")

    obs = hold["water_withdrawal_m3_reported"].to_numpy(float)
    years = hold["year"].to_numpy(int)
    e_hold = hold["electricity_mwh_reported"].to_numpy(float)
    evap_stoch = stoch_h["raw_evap_m3_median"].to_numpy(float)

    train_mean = float(train["water_withdrawal_m3_reported"].mean())
    train_median = float(train["water_withdrawal_m3_reported"].median())
    persist = float(train.loc[train["year"].eq(2022), "water_withdrawal_m3_reported"].iloc[0])

    coefs = {}
    for r in diag.itertuples(index=False):
        coefs[str(r.model)] = json.loads(str(r.coefficients))

    b_e = float(coefs["energy_null"]["electricity_mwh_reported"])
    b_v = float(coefs["evap_physics"]["raw_evap_m3_median"])
    b2_e = float(coefs["two_component"]["electricity_mwh_reported"])
    b2_v = float(coefs["two_component"].get("raw_evap_m3_median", 0.0))

    series = [
        ("training_mean", "frozen naive baseline", "not in model selection", np.full(len(obs), train_mean)),
        ("training_median", "frozen naive baseline", "not in model selection", np.full(len(obs), train_median)),
        ("persistence_2022", "frozen naive baseline", "not in model selection", np.full(len(obs), persist)),
        (
            "conditional_global_scale",
            "existing predictive model",
            "frozen train log-scale × conditional raw evaporation",
            hold["water_pred_m3"].to_numpy(float),
        ),
        (
            "energy_null_frozen_nnls",
            "existing predictive model",
            "selected equation W = β_E × E_fac; β frozen on 2014-2022; evaporation is not an input",
            b_e * e_hold,
        ),
        (
            "energy_null_ensemble_median",
            "existing published diagnostic",
            "water_train_only_pred_m3_median from residual/bootstrap draws; not a new model",
            stoch_h["water_train_only_pred_m3_median"].to_numpy(float),
        ),
        (
            "evap_physics_frozen_nnls",
            "existing predictive model (not selected)",
            "W = β_v × stochastic raw_evap_m3_median; β frozen on 2014-2022",
            b_v * evap_stoch,
        ),
        (
            "two_component_frozen_nnls",
            "existing predictive model (not selected)",
            "W = β_E × E_fac + β_v × raw_evap; current fit has β_v = 0",
            b2_e * e_hold + b2_v * evap_stoch,
        ),
    ]

    mae_mean = None
    rows = []
    for name, kind, notes, pred in series:
        m = _holdout_metrics(pred, obs, years)
        if name == "training_mean":
            mae_mean = m["MAE_m3"]
        skill = 1.0 - m["MAE_m3"] / mae_mean if mae_mean else np.nan
        rec = {
            "predictor": name,
            "kind": kind,
            "train_period": f"observations through {TRAIN_END_YEAR} only",
            "holdout_period": "2023-2024",
            "n_holdout_years": int(len(obs)),
            "MAE_m3": m["MAE_m3"],
            "MAPE_pct": m["MAPE_pct"],
            "pct_error_2023": m["pct_error_2023"],
            "pct_error_2024": m["pct_error_2024"],
            "skill_MAE_vs_training_mean": skill,
            "notes": notes + ". Holdout N=2; informative diagnostic rather than strong statistical evidence.",
        }
        rows.append(rec)
    df = pd.DataFrame(rows)
    if list(df["predictor"]) != list(FIGURE3_FULL_AUDIT_PREDICTORS):
        raise ValueError("water_holdout_baseline_compare.csv predictor set changed unexpectedly")
    df.to_csv(OUT / "water_holdout_baseline_compare.csv", index=False)
    return df


def _pct(a, b) -> float:
    if not np.isfinite(a) or not np.isfinite(b) or b == 0:
        return np.nan
    return 100.0 * (a - b) / b


def write_validation_scorecard() -> pd.DataFrame:
    rows: list[dict] = []

    def add(**kwargs):
        rec = {
            "model_or_quantity": "",
            "evidence_type": "",
            "train_period": "",
            "test_holdout_period": "",
            "n": "",
            "metric": "",
            "value": "",
            "interpretation": "",
        }
        rec.update(kwargs)
        rows.append(rec)

    annual = pd.read_csv(ROOT / "outputs" / "conditional_annual_compare.csv")
    water_m = pd.read_csv(ROOT / "outputs" / "conditional_water_model.csv").iloc[0]
    stoch = pd.read_csv(ROOT / "outputs" / "stochastic_proxy_annual_summary.csv")
    stoch_diag = pd.read_csv(ROOT / "outputs" / "stochastic_proxy_water_model_diagnostics.csv")
    egrid = pd.read_csv(ROOT / "outputs" / "egrid_meta_annual_compare.csv")
    pacw = pd.read_csv(ROOT / "outputs" / "pacw_carbon_shape_compare.csv")
    meta = pd.read_csv(ROOT / "data" / "canonical" / "meta_prineville_annual.csv")

    elec_err = (annual["electricity_mwh_model_closure"] - annual["electricity_mwh_reported"]).abs()
    add(
        model_or_quantity="conditional reconstruction / facility electricity",
        evidence_type="B. exact accounting/calibration closure",
        train_period="2011-2024 (all years closed)",
        test_holdout_period="none (not a prediction)",
        n=int(len(annual)),
        metric="max_abs_annual_MWh_residual",
        value=f"{float(elec_err.max()):.4e}",
        interpretation="Exact annual electricity agreement is calibration closure, not predictive accuracy.",
    )

    train_w = annual[
        annual["split"].eq("train") & annual["water_withdrawal_m3_reported"].notna()
    ]
    hold_w = annual[
        annual["split"].eq("holdout") & annual["water_withdrawal_m3_reported"].notna()
    ]
    train_mape = float(train_w["water_pct_error"].abs().mean())
    hold_mape = float(hold_w["water_pct_error"].abs().mean())
    add(
        model_or_quantity="conditional water global scale (raw evaporation × s)",
        evidence_type="C. in-sample fit",
        train_period=f"2014-{TRAIN_END_YEAR}",
        test_holdout_period="",
        n=int(len(train_w)),
        metric="MAPE_pct",
        value=f"{train_mape:.2f}",
        interpretation=(
            f"Train-only log-scale s={float(water_m['scale']):.6f}; BIC={float(water_m['bic']):.2f}; "
            "kind=global (one-break not selected). In-sample fit is not holdout skill."
        ),
    )
    add(
        model_or_quantity="conditional water global scale (raw evaporation × s)",
        evidence_type="D. chronological predictive accuracy",
        train_period=f"through {TRAIN_END_YEAR}",
        test_holdout_period="2023-2024",
        n=int(len(hold_w)),
        metric="MAPE_pct",
        value=f"{hold_mape:.2f}",
        interpretation=(
            "PRIMARY PREDICTIVE RESULT: frozen train scale over-predicts holdout withdrawal "
            + "; ".join(
                f"{int(r.year)} {float(r.water_pct_error):+.1f}%"
                for r in hold_w.itertuples(index=False)
            )
            + ". Do not hide this with retrospective stochastic water closure."
        ),
    )
    for r in hold_w.itertuples(index=False):
        add(
            model_or_quantity="conditional water global scale (raw evaporation × s)",
            evidence_type="D. chronological predictive accuracy",
            train_period=f"through {TRAIN_END_YEAR}",
            test_holdout_period=str(int(r.year)),
            n=1,
            metric="pct_error",
            value=f"{float(r.water_pct_error):.2f}",
            interpretation="(pred-obs)/obs × 100 on Meta annual withdrawal.",
        )

    sel = stoch_diag[stoch_diag["selected"].astype(str).str.lower().eq("true")].iloc[0]
    add(
        model_or_quantity=f"annual water predictive candidate {sel['model']}",
        evidence_type="C. in-sample fit",
        train_period=f"2014-{TRAIN_END_YEAR}",
        test_holdout_period="",
        n="",
        metric="expanding_window_one_step_MAPE_pct",
        value=f"{float(sel['rolling_one_step_mape_pct']):.2f}",
        interpretation=(
            "EXPANDING-WINDOW one-step MAPE on training years only (selection metric). "
            "This is not the full-training fitted series and is not 2023-2024 skill. "
            f"coefficients={sel['coefficients']}"
        ),
    )
    stoch_hold = stoch[stoch["split"].eq("holdout") & stoch["water_train_only_error_pct"].notna()]
    add(
        model_or_quantity=f"annual water predictive candidate {sel['model']}",
        evidence_type="D. chronological predictive accuracy",
        train_period=f"2014-{TRAIN_END_YEAR}",
        test_holdout_period="2023-2024",
        n=int(len(stoch_hold)),
        metric="MAPE_pct",
        value=f"{float(stoch_hold['water_train_only_error_pct'].abs().mean()):.2f}",
        interpretation=(
            "Published ensemble-median diagnostic for the selected mechanistic candidate "
            f"{sel['model']}; not the frozen-NNLS point prediction and not a claim of best "
            "overall predictor. Retrospective ensemble water closure is not this metric. "
            "Holdout N=2 is a strong predictive diagnostic, not a formal statistical proof."
        ),
    )
    for r in stoch_hold.itertuples(index=False):
        add(
            model_or_quantity=f"annual water predictive candidate {sel['model']}",
            evidence_type="D. chronological predictive accuracy",
            train_period=f"through {TRAIN_END_YEAR}",
            test_holdout_period=str(int(r.year)),
            n=1,
            metric="pct_error",
            value=f"{float(r.water_train_only_error_pct):.2f}",
            interpretation="median train-only prediction vs Meta annual withdrawal.",
        )

    baselines = write_water_holdout_baseline_compare()
    for r in baselines.itertuples(index=False):
        add(
            model_or_quantity=f"annual water {r.predictor}",
            evidence_type="D. chronological predictive accuracy",
            train_period=f"frozen through {TRAIN_END_YEAR}",
            test_holdout_period="2023-2024",
            n=int(r.n_holdout_years),
            metric="MAE_m3",
            value=f"{float(r.MAE_m3):.4f}",
            interpretation=str(r.notes),
        )
        add(
            model_or_quantity=f"annual water {r.predictor}",
            evidence_type="D. chronological predictive accuracy",
            train_period=f"frozen through {TRAIN_END_YEAR}",
            test_holdout_period="2023-2024",
            n=int(r.n_holdout_years),
            metric="MAPE_pct",
            value=f"{float(r.MAPE_pct):.2f}",
            interpretation=f"skill_MAE vs training-mean baseline = {float(r.skill_MAE_vs_training_mean):+.3f}. Holdout N=2.",
        )
        add(
            model_or_quantity=f"annual water {r.predictor}",
            evidence_type="D. chronological predictive accuracy",
            train_period=f"frozen through {TRAIN_END_YEAR}",
            test_holdout_period="2023",
            n=1,
            metric="pct_error",
            value=f"{float(r.pct_error_2023):.2f}",
            interpretation="(pred-obs)/obs × 100. Frozen predictor; holdout unused in fitting.",
        )
        add(
            model_or_quantity=f"annual water {r.predictor}",
            evidence_type="D. chronological predictive accuracy",
            train_period=f"frozen through {TRAIN_END_YEAR}",
            test_holdout_period="2024",
            n=1,
            metric="pct_error",
            value=f"{float(r.pct_error_2024):.2f}",
            interpretation="(pred-obs)/obs × 100. Frozen predictor; holdout unused in fitting.",
        )

    pue_2011 = float(annual.loc[annual.year.eq(2011), "annual_pue_model"].iloc[0])
    add(
        model_or_quantity="gray-box annual PUE vs 2011 design benchmark",
        evidence_type="E. design/assumption consistency check",
        train_period="n/a (not fitted to PUE)",
        test_holdout_period="2011 design point",
        n=1,
        metric="modeled_2011_PUE_minus_1.07",
        value=f"{pue_2011 - 1.07:.4f}",
        interpretation=(
            f"Modeled 2011 annual PUE={pue_2011:.4f} vs Meta 2011 full-load design 1.07. "
            "Design/assumption consistency or falsification check, not independent validation."
        ),
    )

    egrid_cmp = egrid[egrid["meta_location_based_scope2_tonnes"].notna()].copy()
    egrid_cmp["pct_diff"] = 100.0 * (
        egrid_cmp["egrid_estimated_co2e_tonnes"] - egrid_cmp["meta_location_based_scope2_tonnes"]
    ) / egrid_cmp["meta_location_based_scope2_tonnes"]
    add(
        model_or_quantity="eGRID NWPP × Meta MWh vs Meta location Scope 2",
        evidence_type="E. methodology/accounting consistency benchmark",
        train_period="n/a (benchmark)",
        test_holdout_period="2012-2024 where Meta Scope 2 exists",
        n=int(len(egrid_cmp)),
        metric="median_pct_difference",
        value=f"{float(egrid_cmp['pct_diff'].median()):.2f}",
        interpretation=(
            "Methodology/accounting consistency benchmark, not fully independent external validation "
            "(both sides use Meta campus MWh). Not electricity prediction and not a marginal-emissions model."
        ),
    )
    row24 = egrid[egrid.year.eq(2024)].iloc[0]
    add(
        model_or_quantity="eGRID NWPP × Meta MWh vs Meta location Scope 2",
        evidence_type="E. methodology/accounting consistency benchmark",
        train_period="n/a",
        test_holdout_period="2024 (eGRID2023 rate × 2024 MWh)",
        n=1,
        metric="pct_difference",
        value=f"{float(row24['ratio_or_percent_difference']):.4f}",
        interpretation="Column ratio_or_percent_difference is already percent. Near agreement in 2024 is an accounting-method consistency result, not campus carbon telemetry and not independent validation.",
    )

    pacw_ci = pacw[pacw["n_eia_co2_intensity_consumed"] > 0]
    add(
        model_or_quantity="PACW EIA consumed CO2 intensity",
        evidence_type="A. structural QA",
        train_period="n/a",
        test_holdout_period="coverage 2018-07 onward",
        n=int(pacw_ci["n_eia_co2_intensity_consumed"].sum()) if len(pacw_ci) else 0,
        metric="n_hours_with_consumed_intensity",
        value=str(int(pacw_ci["n_eia_co2_intensity_consumed"].sum()) if len(pacw_ci) else 0),
        interpretation="Regional BA intensity coverage only; not campus meters.",
    )

    iwa_qa = ROOT / "outputs" / "qc" / "usgs_nwaa_qa.csv"
    if iwa_qa.exists():
        q = pd.read_csv(iwa_qa)
        ident = q["iwa_identity_max_abs_error"].dropna()
        if len(ident):
            add(
                model_or_quantity="USGS IWA availab = strflow - consum",
                evidence_type="A. structural QA",
                train_period="n/a",
                test_holdout_period="IWA months 2009-10 to 2020-09",
                n=int(len(ident)),
                metric="max_abs_identity_error",
                value=f"{float(ident.max()):.3e}",
                interpretation="Internal accounting identity in the USGS product. NOT independent hydrologic validation.",
            )

    wc_qa = ROOT / "outputs" / "qc" / "water_context_qa.csv"
    if wc_qa.exists():
        wqa = pd.read_csv(wc_qa)
        n_pass = int((wqa["status"].astype(str).str.upper() == "PASS").sum())
        add(
            model_or_quantity="water context integrated table",
            evidence_type="A. structural QA",
            train_period="n/a",
            test_holdout_period="n/a",
            n=int(len(wqa)),
            metric="n_PASS_checks",
            value=str(n_pass),
            interpretation="Boundaries remain separate; USGS missingness preserved after product end dates.",
        )

    owrd_c = ROOT / "outputs" / "owrd_water_model_validation_checks.csv"
    if owrd_c.exists():
        oc = pd.read_csv(owrd_c)
        add(
            model_or_quantity="OWRD external water-evidence layer",
            evidence_type="A. structural QA",
            train_period="n/a",
            test_holdout_period="n/a",
            n=int(len(oc)),
            metric="n_PASS_checks",
            value=str(int((oc.status.astype(str).str.upper() == "PASS").sum())),
            interpretation="City production and direct POD are boundary/context consistency, not Meta prediction error. No City-vs-Meta prediction error is computed.",
        )

    or_qc = ROOT / "outputs" / "oregon_generator_data_checks.csv"
    if or_qc.exists():
        oq = pd.read_csv(or_qc)
        add(
            model_or_quantity="Oregon CAMPD/EIA generator pipeline",
            evidence_type="A. structural QA",
            train_period="n/a",
            test_holdout_period="2011-2024 Oregon",
            n=int(len(oq)),
            metric="n_PASS_checks",
            value=str(int((oq["status"].astype(str).str.upper() == "PASS").sum())),
            interpretation="Oregon generator QC. No generator-to-Meta attribution.",
        )

    stoch_c = ROOT / "outputs" / "stochastic_proxy_checks.csv"
    if stoch_c.exists():
        sc = pd.read_csv(stoch_c)
        add(
            model_or_quantity="stochastic conditional proxy",
            evidence_type="A. structural QA",
            train_period=f"through {TRAIN_END_YEAR} for water selection",
            test_holdout_period="holdout mutation invariance",
            n=int(len(sc)),
            metric="n_PASS_checks",
            value=str(int((sc.status.astype(str).str.upper() == "PASS").sum())),
            interpretation="Includes electricity/water/carbon closures (not predictions) and holdout-mutation invariance of selected water model.",
        )

    add(
        model_or_quantity="stochastic ensemble water/PUE intervals",
        evidence_type="F. scenario/sensitivity uncertainty",
        train_period="priors, not identified",
        test_holdout_period="n/a as accuracy",
        n=32,
        metric="see stochastic_proxy_annual_summary.csv quantiles",
        value="",
        interpretation="Scenario/sensitivity bands generated by assumed workload and overhead priors. Heuristic predictive ensembles under model assumptions, not calibrated confidence intervals with demonstrated coverage and not recovered workload telemetry.",
    )

    n_meta_e = int(meta["electricity_mwh_reported"].notna().sum())
    n_meta_w = int(meta["water_withdrawal_m3_reported"].notna().sum())
    add(
        model_or_quantity="Meta annual campus table",
        evidence_type="A. structural QA",
        train_period="2011-2024 electricity; 2014-2024 water",
        test_holdout_period="",
        n=int(len(meta)),
        metric="n_years_electricity_water",
        value=f"{n_meta_e} electricity years; {n_meta_w} water years",
        interpretation="Reported ground truth. Monthly campus electricity/water are not inferred.",
    )

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "validation_scorecard.csv", index=False)
    return df


def write_source_tree_mmd(sources: pd.DataFrame) -> Path:
    return _diagrams.write_source_tree_mmd(OUT / "data_source_tree.mmd", sources)


def write_quantity_mmd() -> Path:
    return _diagrams.write_quantity_mmd(OUT / "model_quantity_dependency.mmd")


def _box(ax, x, y, w, h, text, color, fontsize=7):
    return _diagrams._box(ax, x, y, w, h, text, color, fontsize)


def render_source_tree_png() -> Path:
    return _diagrams.render_source_tree_png(OUT / "data_source_tree.png")


def render_quantity_png() -> Path:
    return _diagrams.render_quantity_png(OUT / "model_quantity_dependency.png")


def _high_confidence(value) -> bool:
    return str(value).strip().lower().replace(" ", "_") in HIGH_CONFIDENCE


def _event_x(date_start: str, precision: str) -> float:
    raw = str(date_start).strip()
    prec = str(precision).strip().lower()
    ts = pd.to_datetime(raw, errors="coerce")
    if pd.isna(ts):
        year = int(str(raw)[:4])
        return year + (0.2 if prec in {"early_year"} else 0.5)
    year = int(ts.year)
    if prec in {"year"}:
        return year + 0.5
    if prec in {"early_year"}:
        return year + 0.2
    doy = int(ts.dayofyear)
    return year + (doy - 1) / 365.25


def _normalize_confidence(value) -> str:
    token = str(value).strip().lower().replace(" ", "_")
    if token == "very_high":
        return "VERY_HIGH"
    if token == "high":
        return "HIGH"
    return str(value).strip()


def select_figure2_operational_timeline(write: bool = True) -> pd.DataFrame:
    """Presentation selection of existing high-confidence operational events.

    Does not invent events. Same-date, same-category rows may be grouped for
    display while retaining every underlying event and source ID.
    """
    doc_path = ROOT / "config" / "prineville_documentary_events.csv"
    permit_path = ROOT / "data" / "canonical" / "campus_permit_events.csv"
    doc = pd.read_csv(doc_path)
    permit = pd.read_csv(permit_path)
    rows = []

    for r in doc.itertuples(index=False):
        if not _high_confidence(r.confidence):
            continue
        etype = str(r.event_type).strip()
        if etype not in FIGURE2_DOC_INCLUDE_TYPES:
            continue
        category, label = FIGURE2_DOC_INCLUDE_TYPES[etype]
        date_start = str(r.date_start).strip()
        rows.append(
            {
                "displayed_date": date_start[:10],
                "displayed_year": int(str(date_start)[:4]),
                "display_x": _event_x(date_start, r.date_precision),
                "display_label": label,
                "category": category,
                "underlying_event_ids": str(r.event_id),
                "source_doc_ids": str(r.source_doc_id),
                "confidence": _normalize_confidence(r.confidence),
                "date_precision": str(r.date_precision),
            }
        )

    for r in permit.itertuples(index=False):
        if not _high_confidence(r.confidence):
            continue
        etype = str(r.event_type).strip()
        if etype not in FIGURE2_PERMIT_INCLUDE_TYPES:
            continue
        date = str(r.date).strip()[:10]
        year = int(date[:4])
        if year > 2024:
            continue
        category, default_label = FIGURE2_PERMIT_INCLUDE_TYPES[etype]
        label = FIGURE2_PERMIT_LABEL_BY_DATE_TYPE.get((date, etype), default_label)
        rows.append(
            {
                "displayed_date": date,
                "displayed_year": year,
                "display_x": _event_x(date, r.date_precision),
                "display_label": label,
                "category": category,
                "underlying_event_ids": f"CAMPUS_PERMIT:{date}:{etype}:{r.source_id}",
                "source_doc_ids": str(r.source_id),
                "confidence": _normalize_confidence(r.confidence),
                "date_precision": str(r.date_precision),
            }
        )

    if not rows:
        raise RuntimeError("Figure 2 event timeline selected zero high-confidence operational events")

    raw = pd.DataFrame(rows)
    grouped = []
    for (date, category), g in raw.groupby(["displayed_date", "category"], sort=False):
        g = g.sort_values(["display_x", "underlying_event_ids"])
        label = FIGURE2_GROUP_LABELS.get((date, category), g["display_label"].iloc[0])
        confs = set(g["confidence"])
        grouped.append(
            {
                "displayed_date": date,
                "displayed_year": int(g["displayed_year"].iloc[0]),
                "display_x": float(g["display_x"].mean()),
                "display_label": label,
                "category": category,
                "underlying_event_ids": " | ".join(g["underlying_event_ids"].tolist()),
                "source_doc_ids": ";".join(dict.fromkeys(g["source_doc_ids"].tolist())),
                "confidence": "VERY_HIGH" if "VERY_HIGH" in confs else next(iter(confs)),
                "date_precision": g["date_precision"].iloc[0],
            }
        )
    out = pd.DataFrame(grouped).sort_values(["display_x", "category", "display_label"]).reset_index(drop=True)
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        keep = [
            "displayed_date",
            "displayed_year",
            "display_label",
            "category",
            "underlying_event_ids",
            "source_doc_ids",
            "confidence",
        ]
        out[keep].to_csv(OUT / "figure2_event_timeline.csv", index=False)
    return out


def figure1_coverage(meta: pd.DataFrame, water_ctx: pd.DataFrame, pacw_cmp: pd.DataFrame) -> Path:
    years = list(range(2011, 2025))
    rows_spec = []

    def year_status(name, mapping):
        bad = set(mapping.values()) - set(COVERAGE_STATUSES)
        if bad:
            raise ValueError(f"unknown coverage status in {name}: {bad}")
        rows_spec.append((name, mapping))

    e = {int(y): "reported" for y in meta.loc[meta.electricity_mwh_reported.notna(), "year"]}
    w = {int(y): "reported" for y in meta.loc[meta.water_withdrawal_m3_reported.notna(), "year"]}
    s2 = {int(y): "reported" for y in meta.loc[meta.location_based_scope2_tco2e_reported.notna(), "year"]}
    year_status("Meta facility electricity", {y: e.get(y, "missing") for y in years})
    year_status("Meta water withdrawal", {y: w.get(y, "missing") for y in years})
    year_status("Meta location Scope 2", {y: s2.get(y, "missing") for y in years})
    year_status("Canonical weather (KS39/KRDM + KBDN fallback)", {y: "measured" for y in years})
    year_status("Conditional IT/facility power", {y: "fitted" for y in years})
    year_status("Water proxy (evap × scale)", {y: "proxy" if y >= 2014 else "fitted" for y in years})

    pacw_map = {}
    for r in pacw_cmp.itertuples(index=False):
        yr = int(r.year)
        if int(r.n_eia_co2_intensity_consumed) > 0:
            pacw_map[yr] = "reported"
        elif int(r.n_hours) > 0:
            pacw_map[yr] = "proxy"
        else:
            pacw_map[yr] = "missing"
    year_status(
        "EIA-930 PACW hourly demand",
        {y: ("reported" if y >= 2015 else "not_necessary") for y in years},
    )
    year_status(
        "FERC PacifiCorp-West monthly",
        {y: ("reported" if 2011 <= y <= 2018 else "not_necessary") for y in years},
    )
    year_status(
        "FERC PACW-West hourly proxy",
        {y: ("proxy" if 2011 <= y <= 2018 else "not_necessary") for y in years},
    )
    year_status("PACW consumed CO2 intensity", {y: pacw_map.get(y, "missing") for y in years})
    year_status("eGRID NWPP benchmark", {y: "derived" for y in years})

    ctx = water_ctx.copy()
    ctx["year"] = ctx["calendar_year"].astype(int)
    city_years = set(ctx.loc[ctx["city_municipal_production_m3"].notna(), "year"])
    pod_years = set(ctx.loc[ctx["vitesse_facebook_direct_pod_m3"].notna(), "year"])
    iwa_years = set(ctx.loc[ctx["usgs_iwa_in_period"].astype(str).str.lower().eq("true"), "year"])
    wd_years = set(ctx.loc[ctx["usgs_withdrawal_irrigation_in_period"].astype(str).str.lower().eq("true"), "year"])
    year_status("OWRD City production", {y: ("reported" if y in city_years else "missing") for y in years})
    year_status("OWRD Vitesse/Facebook POD", {y: ("reported" if y in pod_years else "missing") for y in years})
    year_status("USGS IWA (site HUC12)", {y: ("proxy" if y in iwa_years else "missing") for y in years})
    year_status("USGS PS / irrigation", {y: ("proxy" if y in wd_years else "missing") for y in years})
    year_status("Oregon CAMPD/EIA generators", {y: "measured" for y in years})
    year_status("Hourly IT telemetry", {y: "not_necessary" for y in years})
    year_status("Monthly campus water delivery", {y: "missing" for y in years})
    year_status("Monthly campus wastewater/sewer discharge", {y: "missing" for y in years})
    year_status("Monthly/hourly campus electricity meter", {y: "missing" for y in years})

    gw_years = {y: "missing" for y in years}
    gw_path = ROOT / "data" / "processed" / "groundwater" / "groundwater_level_observations.csv"
    if gw_path.exists():
        lv = pd.read_csv(gw_path)
        bls = pd.to_numeric(lv.get("water_level_below_land_surface"), errors="coerce")
        dt = pd.to_datetime(lv.get("measurement_datetime"), errors="coerce")
        if dt.isna().all() and "measurement_date" in lv.columns:
            dt = pd.to_datetime(lv["measurement_date"], errors="coerce")
        for y in dt[bls.notna()].dt.year.dropna().astype(int):
            if y in gw_years:
                gw_years[y] = "measured"
    year_status("Groundwater head observations", gw_years)
    ewif_path = ROOT / "data" / "processed" / "water" / "regional_electricity_water_intensity.csv"
    if ewif_path.exists():
        ew = pd.read_csv(ewif_path)
        ewif_map = {}
        for r in ew.itertuples(index=False):
            yr = int(r.year)
            if str(getattr(r, "partial_coverage_cooling_ewif_usable", "")).lower() in {"true", "1"} and pd.notna(
                getattr(r, "EWIF_withdrawal", None)
            ):
                ewif_map[yr] = "proxy"
            elif pd.notna(getattr(r, "EWIF_withdrawal", None)):
                ewif_map[yr] = "derived"
            else:
                ewif_map[yr] = "missing"
        year_status("Indirect electricity water (EWIF)", {y: ewif_map.get(y, "missing") for y in years})
    else:
        year_status("Indirect electricity water (EWIF)", {y: "missing" for y in years})

    status_rows = [
        {"series": name, "year": y, "coverage_status": mapping[y]}
        for name, mapping in rows_spec
        for y in years
    ]
    status_df = pd.DataFrame(status_rows)
    status_path = OUT / "figure1_coverage_status.csv"
    status_df.to_csv(status_path, index=False)

    labels = [r[0] for r in rows_spec]
    code = {
        "reported": 0,
        "measured": 1,
        "derived": 2,
        "fitted": 3,
        "proxy": 4,
        "scenario": 5,
        "not_necessary": 6,
        "missing": 7,
        "unavailable": 7,
    }
    Z = np.array([[code[m[y]] for y in years] for _, m in rows_spec], dtype=float)
    cmap = ListedColormap(
        [
            COLORS["reported"],
            COLORS["measured"],
            COLORS["derived"],
            COLORS["fitted"],
            COLORS["proxy"],
            COLORS["scenario"],
            COLORS["not_necessary"],
            COLORS["missing"],
        ]
    )
    fig, ax = plt.subplots(figsize=(11.6, 9.0))
    ax.imshow(Z, aspect="auto", cmap=cmap, vmin=0, vmax=7)
    ax.set_xticks(range(len(years)))
    ax.set_xticklabels(years, rotation=0, fontsize=8)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_title("Figure 1 — Data coverage and provenance", loc="left")
    ax.set_xlabel("Calendar year")
    ax.legend(
        handles=[
            Patch(facecolor=COLORS["reported"], label="reported/measured"),
            Patch(facecolor=COLORS["derived"], label="derived"),
            Patch(facecolor=COLORS["fitted"], label="fitted"),
            Patch(facecolor=COLORS["proxy"], label="proxy"),
            Patch(facecolor=COLORS["not_necessary"], label="not an active target"),
            Patch(facecolor=COLORS["missing"], label="missing"),
        ],
        loc="upper center",
        bbox_to_anchor=(0.5, -0.07),
        ncol=6,
        frameon=False,
        fontsize=8,
    )
    fig.tight_layout()
    path = FIG / "fig01_data_coverage_provenance.png"
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)
    return path


def figure2_ground_truth(meta: pd.DataFrame, events: pd.DataFrame | None = None) -> Path:
    del events
    z = meta.copy()
    z["intensity"] = z["water_intensity_L_per_kWh_facility_derived"]
    timeline = select_figure2_operational_timeline(write=True)
    cat_y = {cat: i for i, cat in enumerate(reversed(FIGURE2_EVENT_CATEGORIES))}
    cat_color = {
        "campus/buildout": "#1d4ed8",
        "water/infrastructure": "#0e7490",
        "power/cooling": "#b45309",
    }

    fig, axes = plt.subplots(
        6,
        1,
        figsize=(11.6, 12.4),
        sharex=False,
        gridspec_kw={"height_ratios": [1.0, 1.0, 1.0, 1.0, 0.72, 1.55], "hspace": 0.16},
    )
    years = z.year.to_numpy(int)

    axes[0].plot(years, z.electricity_mwh_reported / 1000.0, "-o", color="#1d4ed8", ms=4)
    axes[0].set_ylabel("Facility electricity\n(GWh)")
    axes[0].set_title("Figure 2 — Observed Prineville ground truth", loc="left")

    axes[1].plot(years, z.water_withdrawal_m3_reported / 1000.0, "-o", color="#0e7490", ms=4)
    axes[1].set_ylabel("Water withdrawal\n(thousand m³)")

    axes[2].plot(years, z.location_based_scope2_tco2e_reported / 1000.0, "-o", color="#b45309", ms=4)
    axes[2].set_ylabel("Location Scope 2\n(ktCO2e)")

    axes[3].plot(years, z.intensity, "-o", color="#7e22ce", ms=4)
    axes[3].set_ylabel("Withdrawal / electricity\n(L/kWh facility)")

    for i, ax in enumerate(axes[:4]):
        if i in (1, 3):
            ax.axvspan(2022.5, 2024.5, color="#fee2e2", alpha=0.5, zorder=0)
        ax.set_xlim(2009.5, 2024.8)
        ax.grid(True, axis="y", alpha=0.3)
        ax.sharex(axes[0])

    axes[1].text(
        2023.5,
        axes[1].get_ylim()[1] * 0.92,
        "2023–2024\nwater-model holdout",
        ha="center",
        va="top",
        fontsize=7,
        color="#991b1b",
    )

    ev_ax = axes[4]
    for n, r in enumerate(timeline.itertuples(index=False), start=1):
        x = float(r.display_x)
        y = cat_y[str(r.category)]
        color = cat_color[str(r.category)]
        ev_ax.scatter([x], [y], s=28, color=color, zorder=3, clip_on=False)
        ev_ax.annotate(
            str(n),
            (x, y),
            xytext=(0, 6),
            textcoords="offset points",
            fontsize=6.2,
            ha="center",
            va="bottom",
            color="#111827",
            clip_on=False,
        )
    ev_ax.set_xlim(2009.5, 2024.8)
    ev_ax.set_yticks(list(cat_y.values()))
    ev_ax.set_yticklabels(list(reversed(FIGURE2_EVENT_CATEGORIES)), fontsize=8)
    ev_ax.set_ylim(-0.55, 2.7)
    ev_ax.set_xlabel("Year")
    ev_ax.grid(True, axis="x", alpha=0.25)
    for name, spine in ev_ax.spines.items():
        if name != "bottom":
            spine.set_visible(False)
    ev_ax.tick_params(axis="y", length=0)
    handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor=cat_color[c], markersize=7, label=c)
        for c in FIGURE2_EVENT_CATEGORIES
    ]
    ev_ax.legend(handles=handles, loc="upper left", frameon=False, fontsize=7, ncol=3)
    ev_ax.set_ylabel("Documentary /\npermit events")

    key_ax = axes[5]
    key_ax.set_xlim(0, 1)
    key_ax.set_ylim(0, 1)
    key_ax.axis("off")
    key_ax.set_title("Event key (source IDs in figure2_event_timeline.csv; not causal water annotations)", loc="left", fontsize=8)
    n = len(timeline)
    ncols = 3
    nrows = int(np.ceil(n / ncols))
    for i, r in enumerate(timeline.itertuples(index=False), start=1):
        col = (i - 1) // nrows
        row = (i - 1) % nrows
        x = 0.02 + col / ncols
        y = 0.96 - row * (0.90 / max(nrows, 1))
        key_ax.text(
            x,
            y,
            f"{i}. {r.display_label}",
            fontsize=6.1,
            ha="left",
            va="top",
            color=cat_color[str(r.category)],
            transform=key_ax.transAxes,
        )

    fig.subplots_adjust(left=0.14, right=0.98, top=0.96, bottom=0.04)
    path = FIG / "fig02_observed_ground_truth.png"
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)
    return path


def figure3_water_accuracy(
    cond: pd.DataFrame,
    stoch: pd.DataFrame,
    diag: pd.DataFrame,
    baselines: pd.DataFrame,
) -> Path:
    c = cond.dropna(subset=["water_withdrawal_m3_reported"]).copy()
    train_c = c[c.split.eq("train")]
    hold_c = c[c.split.eq("holdout")]
    del stoch
    sel = diag[diag.selected.astype(str).str.lower().eq("true")].iloc[0]
    bmap = baselines.set_index("predictor")
    beta_e = json.loads(str(sel["coefficients"]))["electricity_mwh_reported"]
    e_all = c["electricity_mwh_reported"].to_numpy(float)
    energy_pred = beta_e * e_all
    train_mean = float(
        cond.loc[cond.split.eq("train") & cond.water_withdrawal_m3_reported.notna(), "water_withdrawal_m3_reported"].mean()
    )

    fig = plt.figure(figsize=(11.2, 8.6))
    gs = fig.add_gridspec(2, 1, height_ratios=[1.7, 0.85], hspace=0.28)
    ax = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1])

    ax.plot(c.year, c.water_withdrawal_m3_reported / 1e3, "o", color="black", ms=7, zorder=5)
    ax.plot(train_c.year, train_c.water_pred_m3 / 1e3, "s--", color="#c2410c", ms=5)
    ax.plot(hold_c.year, hold_c.water_pred_m3 / 1e3, "s-", color="#c2410c", ms=8)
    ax.plot(train_c.year, (beta_e * train_c["electricity_mwh_reported"].to_numpy(float)) / 1e3, "^--", color="#5e3c99", ms=5)
    ax.plot(hold_c.year, (beta_e * hold_c["electricity_mwh_reported"].to_numpy(float)) / 1e3, "^-", color="#5e3c99", ms=8)
    ax.plot(c.year, np.full(len(c), train_mean) / 1e3, "D--", color="#6b7280", ms=4)

    ax.axvspan(2022.5, 2024.5, color="#fee2e2", alpha=0.55, zorder=0)
    ax.axvline(2022.5, color="#991b1b", lw=1.0, ls="--")
    ax.set_ylabel("Annual water (thousand m³)")
    ax.set_title("Figure 3 — Water-model holdout vs frozen naive baseline (N=2 years)", loc="left")
    ax.set_xlim(2013.5, 2024.5)
    ax.grid(True, axis="y", alpha=0.3)
    ymax = max(
        float(c.water_withdrawal_m3_reported.max()),
        float(c.water_pred_m3.max()),
        float(np.nanmax(energy_pred)),
        train_mean,
    ) / 1e3
    ax.set_ylim(0, ymax * 1.18)
    ax.legend(
        handles=[
            Line2D([0], [0], marker="o", color="black", ls="none", ms=7, label="Observed Meta withdrawal"),
            Line2D([0], [0], marker="s", color="#c2410c", ls="-", ms=6, label="Conditional evap × scale"),
            Line2D([0], [0], marker="^", color="#5e3c99", ls="-", ms=7, label="Energy-only frozen NNLS"),
            Line2D([0], [0], marker="D", color="#6b7280", ls="--", ms=5, label="Training-mean baseline"),
        ],
        loc="upper left",
        fontsize=8,
        frameon=False,
    )
    ax.text(2023.5, ymax * 1.12, "2023–2024 water-model holdout", ha="center", color="#991b1b", fontsize=8)

    display_order = list(FIGURE3_DISPLAY_PREDICTORS)
    labels = {
        "training_mean": "Training mean",
        "conditional_global_scale": "Conditional evap × scale",
        "energy_null_frozen_nnls": "Energy-only NNLS",
    }
    table = [["Predictor", "Holdout MAPE", "2023 % error", "2024 % error"]]
    for key in display_order:
        r = bmap.loc[key]
        table.append(
            [
                labels[key],
                f"{float(r.MAPE_pct):.1f}%",
                f"{float(r.pct_error_2023):+.1f}%",
                f"{float(r.pct_error_2024):+.1f}%",
            ]
        )
    ax2.axis("off")
    tbl = ax2.table(cellText=table, loc="center", cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8.5)
    tbl.scale(1.0, 1.55)
    for j in range(4):
        tbl[0, j].set_facecolor("#e5e7eb")
        tbl[1, j].set_facecolor("#f3f4f6")
        tbl[2, j].set_facecolor("#fff7ed")
        tbl[3, j].set_facecolor("#f5f3ff")
    ax2.set_title(
        "Train: 2014–2022. Holdout: 2023–2024 (N=2).\nNaive baseline was not used in mechanistic model selection.",
        fontsize=8.5,
        loc="left",
        pad=4,
    )

    path = FIG / "fig03_water_model_accuracy.png"
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)
    return path


def figure4_external_water(ctx: pd.DataFrame, meta: pd.DataFrame) -> Path:
    z = ctx.copy()
    z["date"] = pd.to_datetime(z["calendar_month"])
    z = z[(z["date"] >= "2011-01-01") & (z["date"] <= "2024-12-31")].copy()
    fig, axes = plt.subplots(6, 1, figsize=(11.2, 11.4), sharex=True)

    axes[0].plot(z.date, z.city_municipal_production_m3 / 1e3, color="#0369a1", lw=0.9)
    axes[0].set_ylabel("City production\n(10³ m³/mo)")
    axes[0].set_title("Figure 4 — External water evidence (incompatible boundaries; not summed)", loc="left")

    axes[1].plot(z.date, z.vitesse_facebook_direct_pod_m3 / 1e3, color="#0f766e", lw=0.9)
    axes[1].set_ylabel("Vitesse/FB POD\n(10³ m³/mo)")

    # Annual Meta withdrawal plotted as a step on the monthly axis for alignment only.
    axes[2].step(
        z.date,
        z.meta_campus_withdrawal_m3_annual_reported / 1e3,
        where="mid",
        color="black",
        lw=1.1,
    )
    axes[2].set_ylabel("Meta annual\nwithdrawal (10³ m³/y)")

    iwa = z["usgs_iwa_in_period"].astype(str).str.lower().eq("true")
    wd = z["usgs_withdrawal_irrigation_in_period"].astype(str).str.lower().eq("true")
    axes[3].plot(
        z.loc[iwa, "date"],
        z.loc[iwa, "site_huc12_iwa_surface_water_availability_m3_month"] / 1e6,
        color="#a16207",
        lw=0.9,
    )
    axes[3].set_ylabel("IWA availability\n(10⁶ m³/mo)")

    axes[4].plot(
        z.loc[wd, "date"],
        z.loc[wd, "site_huc12_public_supply_withdrawal_total_m3_month"] / 1e3,
        color="#7c3aed",
        lw=0.8,
        label="public-supply WD",
    )
    axes[4].plot(
        z.loc[wd, "date"],
        z.loc[wd, "site_huc12_irrigation_withdrawal_m3_month"] / 1e3,
        color="#db2777",
        lw=0.8,
        label="irrigation WD",
    )
    axes[4].set_ylabel("USGS HUC12 WD\n(10³ m³/mo)")
    axes[4].legend(fontsize=7, loc="upper right", frameon=False)

    wx = z.dropna(subset=["weather_t_db_C_mean"])
    axes[5].plot(wx.date, wx.weather_t_db_C_mean, color="#b45309", lw=0.8)
    axes[5].set_ylabel("KRDM mean\ndry-bulb (°C)")
    axes[5].set_xlabel("Month")

    for ax in axes:
        ax.grid(True, axis="y", alpha=0.3)
        ax.axvline(pd.Timestamp("2020-09-01"), color="#9ca3af", ls=":", lw=0.9)
        ax.axvline(pd.Timestamp("2020-12-01"), color="#d1d5db", ls=":", lw=0.8)
    axes[3].text(pd.Timestamp("2018-01-01"), 0.02, "IWA ends 2020-09; WD/irrigation end 2020-12", fontsize=7, color="#6b7280")

    fig.tight_layout()
    path = FIG / "fig04_external_water_context.png"
    fig.savefig(path, dpi=170)
    plt.close(fig)
    return path


def figure5_carbon(egrid: pd.DataFrame, pacw: pd.DataFrame) -> Path:
    z = egrid.copy()
    fig, axes = plt.subplots(2, 1, figsize=(10.8, 7.2), gridspec_kw={"height_ratios": [2.2, 1.0]})
    ax = axes[0]
    yrs = z.year.to_numpy(int)
    ax.plot(yrs, z.meta_location_based_scope2_tonnes / 1000.0, "o-", color="#111827", label="Meta reported location Scope 2")
    ax.plot(yrs, z.egrid_estimated_co2e_tonnes / 1000.0, "s--", color="#c2410c", label="Meta MWh × eGRID NWPP output rate")
    ax.set_ylabel("ktCO2e / year")
    ax.set_title("Figure 5 — Carbon benchmark (location average, not marginal)", loc="left")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(True, axis="y", alpha=0.3)

    d = 100.0 * (z.egrid_estimated_co2e_tonnes - z.meta_location_based_scope2_tonnes) / z.meta_location_based_scope2_tonnes
    ax2 = axes[1]
    ax2.bar(yrs, d, color=np.where(d.fillna(0) >= 0, "#fb923c", "#38bdf8"))
    ax2.axhline(0, color="#111", lw=0.8)
    ax2.set_ylabel("% difference\n(eGRID − Meta)/Meta")
    ax2.set_xlabel("Year")
    ax2.grid(True, axis="y", alpha=0.3)

    # PACW coverage annotation
    for r in pacw.itertuples(index=False):
        if int(r.n_eia_co2_intensity_consumed) > 0:
            ax.axvspan(int(r.year) - 0.4, int(r.year) + 0.4, color="#dbeafe", alpha=0.35, zorder=0)
    ax.text(0.99, 0.05, "Blue band: PACW hourly consumed-CO2 intensity present (regional shape, not campus telemetry)",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=7, color="#1e3a8a")
    fig.tight_layout()
    path = FIG / "fig05_carbon_benchmark.png"
    fig.savefig(path, dpi=170)
    plt.close(fig)
    return path


def select_hottest_complete_week(hourly: pd.DataFrame, weather: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Hottest complete local week in the reconstruction period.

    Rule: America/Los_Angeles calendar weeks (Monday–Sunday) with exactly 168
    hours and finite dry-bulb and wet-bulb; maximize mean dry-bulb.
    """
    h = hourly.copy()
    h["timestamp_utc"] = pd.to_datetime(h["timestamp_utc"], utc=True)
    w = weather[["timestamp_utc", "t_db_C", "t_wb_C"]].copy()
    w["timestamp_utc"] = pd.to_datetime(w["timestamp_utc"], utc=True)
    z = h.merge(w, on="timestamp_utc", how="left")
    local = z["timestamp_utc"].dt.tz_convert("America/Los_Angeles")
    z["local"] = local
    # ISO week with Monday start in local time
    z["week_start"] = (local - pd.to_timedelta(local.dt.dayofweek, unit="D")).dt.floor("D")
    grouped = []
    for ws, g in z.groupby("week_start"):
        if len(g) != 168:
            continue
        if g["t_db_C"].isna().any() or g["t_wb_C"].isna().any():
            continue
        grouped.append((float(g["t_db_C"].mean()), ws, g.sort_values("timestamp_utc")))
    if not grouped:
        raise RuntimeError("No complete 168-hour local weeks with finite weather in reconstruction.")
    grouped.sort(key=lambda t: (-t[0], t[1]))
    mean_t, ws, g = grouped[0]
    meta = {
        "rule": "hottest complete America/Los_Angeles Monday-Sunday week with 168 finite dry/wet-bulb hours in 2011-2024 reconstruction",
        "week_start_local": str(ws),
        "mean_t_db_C": mean_t,
        "n_hours": int(len(g)),
        "n_complete_weeks_considered": len(grouped),
        "seed": RNG_SEED,
    }
    return g, meta


def figure6_graybox_week(week: pd.DataFrame, meta: dict) -> Path:
    t = week["local"] if "local" in week.columns else pd.to_datetime(week["timestamp_utc"], utc=True)
    fig, axes = plt.subplots(4, 1, figsize=(11.2, 8.8), sharex=True)
    axes[0].plot(t, week["t_db_C"], color="#b45309", lw=1.0, label="dry-bulb")
    axes[0].plot(t, week["t_wb_C"], color="#0369a1", lw=1.0, label="wet-bulb")
    axes[0].set_ylabel("°C")
    axes[0].legend(frameon=False, fontsize=8, loc="upper left")
    axes[0].set_title(
        f"Figure 6 — Gray-box interaction, hottest complete week starting {meta['week_start_local'][:10]} "
        f"(mean Tdb={meta['mean_t_db_C']:.1f} °C)",
        loc="left",
        fontsize=10,
    )

    axes[1].plot(t, week["p_it_mw"], color="#7c3aed", lw=1.0, label="P_IT (fitted scale)")
    axes[1].plot(t, week["p_fac_mw"], color="#1d4ed8", lw=1.0, label="P_fac (derived)")
    axes[1].set_ylabel("MW")
    axes[1].legend(frameon=False, fontsize=8)
    axp = axes[1].twinx()
    axp.plot(t, week["pue"], color="#9ca3af", lw=0.8, label="PUE")
    axp.set_ylabel("PUE")

    mode = week["cooling_mode"].astype(str)
    colors = {"outside_air_or_winter_mix": "#86efac", "partial_evap": "#fde047", "full_evap": "#fb7185"}
    for m, c in colors.items():
        mask = mode.eq(m)
        axes[2].fill_between(t, 0, mask.astype(float), color=c, step="mid", label=m, alpha=0.85)
    axes[2].set_ylim(0, 1.05)
    axes[2].set_yticks([])
    axes[2].legend(frameon=False, fontsize=7, loc="upper right", ncol=3)
    axes[2].set_ylabel("cooling mode")

    axes[3].plot(t, week["evap_water_m3_per_h"], color="#0f766e", lw=1.0, label="raw evaporation (derived)")
    if "water_withdrawal_proxy_m3_per_h" in week.columns:
        axes[3].plot(t, week["water_withdrawal_proxy_m3_per_h"], color="#e11d48", lw=0.9, ls="--",
                     label="withdrawal proxy (fitted scale × raw)")
    axes[3].set_ylabel("m³/h")
    axes[3].legend(frameon=False, fontsize=8)
    axes[3].set_xlabel("Local time (America/Los_Angeles)")
    for ax in axes:
        ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    path = FIG / "fig06_graybox_hot_week.png"
    fig.savefig(path, dpi=170)
    plt.close(fig)
    return path


def _summarize_graybox_run(hourly: pd.DataFrame, annual: pd.DataFrame) -> dict:
    return {
        "annual_raw_evaporation_m3": float(annual["water_raw_m3"].sum()),
        "annual_inferred_it_energy_mwh": float(annual["it_energy_mwh_fitted"].sum()),
        "mean_annual_pue": float(annual["annual_pue_model"].mean()),
        "peak_hourly_pue": float(hourly["pue"].max()),
        "pue_2011": float(annual.loc[annual.year.eq(2011), "annual_pue_model"].iloc[0]),
    }


def write_graybox_parameter_sensitivity() -> tuple[pd.DataFrame, dict]:
    """One-at-a-time sensitivity for parameters with a documented range.

    Uses reconstruct() with overridden Params. Does not write conditional
    reconstruction artifacts and does not retune water models for reporting.
    """
    from dataclasses import replace

    from conditional_reconstruction import reconstruct
    from prineville_graybox import Params

    params = parameter_registry()
    perturbable = []
    for r in params:
        if r["model_id"] != "M_GRAYBOX":
            continue
        if r["used_in_code"] != "yes":
            continue
        if r["plausible_range"] in ("", "range_not_established"):
            continue
        lo, hi = [float(x) for x in r["plausible_range"].split("-")]
        perturbable.append((r["parameter"], float(r["value"]), lo, hi))

    weather_audit = weather_driver_audit()
    n_bad = weather_unresolved_count(weather_audit)
    existing = OUT / "graybox_parameter_sensitivity.csv"
    if n_bad:
        if not existing.exists():
            raise RuntimeError(
                "Gray-box sensitivity cannot be recomputed: processed weather has "
                f"{n_bad} hours with non-finite required drivers, and no existing "
                "sensitivity table is present. Do not impute weather inside the gray-box."
            )
        df = pd.read_csv(existing)
        base = {
            "annual_raw_evaporation_m3": float(
                df.loc[df.parameter.eq("baseline"), "annual_raw_evaporation_m3"].iloc[0]
            ),
            "annual_inferred_it_energy_mwh": float(
                df.loc[df.parameter.eq("baseline"), "annual_inferred_it_energy_mwh"].iloc[0]
            ),
            "mean_annual_pue": float(df.loc[df.parameter.eq("baseline"), "mean_annual_pue"].iloc[0]),
            "peak_hourly_pue": float(df.loc[df.parameter.eq("baseline"), "peak_hourly_pue"].iloc[0]),
            "pue_2011": float(df.loc[df.parameter.eq("baseline"), "pue_2011"].iloc[0]),
            "sensitivity_recomputed": False,
            "weather_nonfinite_hours": n_bad,
        }
        return df, base

    base_params = Params()
    hourly0, annual0, _ = reconstruct(params=base_params)
    base = _summarize_graybox_run(hourly0, annual0)
    base["sensitivity_recomputed"] = True
    base["weather_nonfinite_hours"] = 0

    rows = []
    for name, nominal, lo, hi in perturbable:
        for tag, val in (("low", lo), ("high", hi)):
            run_params = replace(base_params, **{name: val})
            hourly, annual, _ = reconstruct(params=run_params)
            summ = _summarize_graybox_run(hourly, annual)
            rec = {
                "parameter": name,
                "level": tag,
                "value": val,
                "nominal_value": nominal,
                "source_of_range": "sampled_facility_priors documented clip bounds",
                "analysis_type": "one-at-a-time assumption sensitivity; not a confidence interval and not a recalibration",
            }
            for k, v in summ.items():
                rec[k] = v
                rec[f"pct_change_vs_baseline_{k}"] = 100.0 * (v - base[k]) / base[k] if base[k] else np.nan
            rows.append(rec)
    # Baseline row
    rec0 = {
        "parameter": "baseline",
        "level": "nominal",
        "value": "",
        "nominal_value": "",
        "source_of_range": "Params() defaults",
        "analysis_type": "reference; not a CI",
    }
    rec0.update(base)
    for k in base:
        rec0[f"pct_change_vs_baseline_{k}"] = 0.0
    df = pd.DataFrame([rec0] + rows)
    df.to_csv(OUT / "graybox_parameter_sensitivity.csv", index=False)
    return df, base


def figure_graybox_sensitivity(sens: pd.DataFrame, base: dict) -> Path:
    z = sens[sens.parameter.ne("baseline")].copy()
    params = [p for p in z.parameter.unique()]
    metrics = [
        ("annual_raw_evaporation_m3", "annual raw evaporation"),
        ("annual_inferred_it_energy_mwh", "annual inferred IT energy"),
        ("mean_annual_pue", "mean annual PUE"),
        ("peak_hourly_pue", "peak hourly PUE"),
    ]
    fig, axes = plt.subplots(len(metrics), 1, figsize=(10.4, 8.6), sharex=True)
    fig.suptitle(
        "Figure 7 — Gray-box assumption sensitivity (one-at-a-time; not a confidence interval)",
        fontsize=11,
        x=0.01,
        ha="left",
    )
    for ax, (key, title) in zip(axes, metrics):
        col = f"pct_change_vs_baseline_{key}"
        y = np.arange(len(params))
        for i, p in enumerate(params):
            sub = z[z.parameter.eq(p)]
            lo = float(sub.loc[sub.level.eq("low"), col].iloc[0])
            hi = float(sub.loc[sub.level.eq("high"), col].iloc[0])
            ax.plot([lo, hi], [i, i], color="#7c3aed", lw=6, solid_capstyle="round")
            ax.plot([lo], [i], "o", color="#1d4ed8", ms=6)
            ax.plot([hi], [i], "o", color="#c2410c", ms=6)
        ax.axvline(0, color="#111", lw=0.8)
        ax.set_yticks(y)
        ax.set_yticklabels(params, fontsize=8)
        ax.set_ylabel("")
        ax.set_title(f"% change in {title}", loc="left", fontsize=9)
        ax.grid(True, axis="x", alpha=0.3)
    axes[-1].set_xlabel("% change versus baseline Params()")
    axes[-1].plot([], [], "o", color="#1d4ed8", label="documented-range low")
    axes[-1].plot([], [], "o", color="#c2410c", label="documented-range high")
    axes[-1].legend(frameon=False, fontsize=8, loc="lower right")
    fig.tight_layout(rect=(0, 0.02, 1, 0.96))
    path = FIG / "fig07_graybox_parameter_sensitivity.png"
    fig.savefig(path, dpi=170)
    plt.close(fig)
    return path


def write_markdown(
    sources: pd.DataFrame,
    quantities: pd.DataFrame,
    models: pd.DataFrame,
    scorecard: pd.DataFrame,
    week_meta: dict,
    baselines: pd.DataFrame,
    sens: pd.DataFrame,
    claims: pd.DataFrame,
) -> Path:
    n_src = len(sources)
    n_q = len(quantities)
    n_unavail = int(quantities.provenance_class.eq("unavailable").sum())
    n_impl = int(quantities.implementation_status.str.contains("implemented", case=False, na=False).sum())

    cond = pd.read_csv(ROOT / "outputs" / "conditional_annual_compare.csv")
    stoch = pd.read_csv(ROOT / "outputs" / "stochastic_proxy_annual_summary.csv")
    diag = pd.read_csv(ROOT / "outputs" / "stochastic_proxy_water_model_diagnostics.csv")
    wm = pd.read_csv(ROOT / "outputs" / "conditional_water_model.csv").iloc[0]
    hold = cond[cond.split.eq("holdout")]
    sel = diag[diag.selected.astype(str).str.lower().eq("true")].iloc[0]
    cmap = dict(zip(claims["claim_id"], claims["value"]))
    gw_id_path = ROOT / "outputs" / "groundwater" / "groundwater_identifiability_summary.csv"
    if gw_id_path.exists():
        gw_id = pd.read_csv(gw_id_path).iloc[0]
        gw_id_md = (
            f"**Groundwater identifiability (no model fitted):** `{gw_id['overall_identifiability_conclusion']}`. "
            f"ESTIMATION_CANDIDATE (sufficient data to attempt a validated empirical response model, not identified dynamics): `{gw_id['estimation_candidate_nodes'] or 'none'}`. "
            f"VALIDATION_ONLY: `{gw_id['validation_only_nodes'] or 'none'}`. "
            f"INSUFFICIENT: `{gw_id['insufficient_nodes'] or 'none'}`. "
            "GWIS BLS and AMSL are paired representations of the same measurement. "
            "Identifiability uses measurement-QC eligible observations. "
            "head_anomaly_ft = -(BLS − well-mean BLS). "
            "OWRD pumping is reported at its own boundary; permit events are facility technology/commissioning evidence. "
            f"Next modeling step (not executed here): {gw_id['next_scientific_modeling_step']}"
        )
    else:
        gw_id_md = (
            "**Groundwater identifiability:** audit outputs not present. "
            "No groundwater-response model is fitted."
        )

    doc_audit = ROOT / "outputs" / "documentary_evidence_audit.csv"
    if doc_audit.exists():
        doc_md = (
            "**Documentary/regulatory evidence:** curated identity and legal/network facts from "
            "`config/prineville_documentary_*.csv`. PRN and CCO are distinct named campuses. "
            "Meta annual Prineville totals remain hard observations; "
            "`meta_reporting_boundary_status` is `unresolved_prn_vs_prn_plus_cco`. "
            "120/220/180/437 MW facts are interconnection/REC/new-load constraints, not campus load. "
            "Water-infrastructure facts are not campus water meters. No model retuning."
        )
    else:
        doc_md = (
            "**Documentary/regulatory evidence:** audit outputs not present. "
            "This layer is identity/legal context only."
        )

    disc = "\n".join(
        f"- **{d['item']}.** Documentation: {d['documentation']} Code/files: {d['code_or_files']} "
        f"Resolution: {d['resolution']}"
        for d in DOC_VS_CODE_DISCREPANCIES
    )

    q_lines = []
    for r in quantities.itertuples(index=False):
        if r.quantity_id in (
            "Q_ARRIVALS", "Q_P_IT", "Q_E_FAC", "Q_PUE", "Q_W_WITH", "Q_WATER_PROXY",
            "Q_W_CONS", "Q_CITY_PROD", "Q_DIRECT_POD", "Q_IWA_AVAIL", "Q_SCOPE2_META",
            "Q_SCOPE2_EGRID", "Q_GEN_OR", "Q_W_IND", "Q_DC_GW", "Q_HEAD", "Q_GW_OBS", "Q_ELEC_COST",
        ):
            q_lines.append(
                f"### {r.quantity} (`{r.symbol}`)\n\n"
                f"- **What is it?** {r.definition}\n"
                f"- **Where does it come from?** {r.primary_source or 'not identified'}\n"
                f"- **How is it computed?** {r.equation_transformation_model or 'not computed'}\n"
                f"- **Assumptions?** {r.modeling_assumptions or 'n/a'}\n"
                f"- **Provenance:** `{r.provenance_class}` ({r.implementation_status})\n"
                f"- **Accounting boundary:** `{r.boundary_id}` — {r.accounting_boundary_note}\n"
                f"- **Validation?** {r.accuracy_diagnostic_available or 'none'}\n"
                f"- **Confidence:** {r.confidence_level}. {r.missing_information_limitation}\n"
            )

    unavail = quantities[quantities.provenance_class.eq("unavailable")][
        ["quantity_id", "quantity", "missing_information_limitation"]
    ]

    unavail_md = "\n".join(
        f"- **{r.quantity}** (`{r.quantity_id}`): {r.missing_information_limitation}"
        for r in unavail.itertuples(index=False)
    )

    b_lines = [
        "| Predictor | Kind | MAE m³ | MAPE % | 2023 %err | 2024 %err | skill_MAE vs train mean |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in baselines.itertuples(index=False):
        b_lines.append(
            f"| `{r.predictor}` | {r.kind} | {float(r.MAE_m3):,.0f} | {float(r.MAPE_pct):.1f} | "
            f"{float(r.pct_error_2023):+.1f} | {float(r.pct_error_2024):+.1f} | "
            f"{float(r.skill_MAE_vs_training_mean):+.3f} |"
        )
    baseline_md = "\n".join(b_lines)

    n_bounds = int(quantities["boundary_id"].nunique()) if "boundary_id" in quantities.columns else 0
    implemented_q = quantities[quantities.provenance_class.ne("unavailable")]
    n_impl_bounds = int(implemented_q["boundary_id"].nunique()) if len(implemented_q) else 0

    gaps = """
| Gap | Why it is unidentified | What would resolve it |
|---|---|---|
| Hourly IT workload / utilization | No public traces; stochastic arrivals are scenario draws | Meta/scheduler traces or feeder+IT submetering |
| Monthly campus electricity and water | Canonical table is annual; monthly Meta values are not inferred | Utility/Meta monthly meters |
| Site water consumption vs withdrawal | No discharge/CoC series | Sewer/discharge or documented consumptive fraction on the campus boundary |
| Campus source-share θ / groundwater extraction q_dc | City production and POD totals are different boundaries | Campus well/utility delivery meters with source IDs |
| Generator-to-Meta attribution | Oregon CAMPD/EIA are state tables only | Contract/path/pseudo-tie evidence |
| Indirect electricity water | Only a regional-average cooling EWIF × Meta MWh proxy exists | Generator-resolved water with attribution, or a documented BA-average used as such |
| Groundwater head observations | GWIS well-level BLS/AMSL ingested as paired representations of the same measurement; a modeled head field is still unidentified | Measurement QC + identifiability screen exist; ESTIMATION_CANDIDATE means sufficient data to attempt a validated empirical response model, not identified dynamics |
| Groundwater storage / recharge | Storativity, specific yield, and recharge are not recovered from local PDFs or GWIS | Catalogued ASR attachments (still not local) or pumping-test reports; IWA is surface routing |
| ISO WUE | Withdrawal/facility-kWh is not consumption/IT-kWh | Consumption and IT energy on ISO boundaries |
| Cost variables | No tariffs/bills | PacifiCorp / City rate schedules and bills |
| Campus footprint polygon | Site HUC12 is a point-in-polygon designation | Surveyed campus polygon |
| a2 tower WUE curves | Glossary-only; gray-box is air-side evaporative physics | Only if a cooling-tower model is actually implemented |
"""

    md = f"""# Pipeline data and model report — Meta Prineville v3

This report is generated by `src/build_pipeline_report.py` from the registries in `src/pipeline_report_catalog.py` and from **existing** processed artifacts. It describes **implemented code**, not the intended full glossary model. Modeling logic is not changed here. After the Pipeline Audit v1 corrections, source→quantity and model I/O lineage is taken from canonical edge tables rather than a separately maintained diagram.

**Freeze label: Prineville Public-Data Baseline v1.** This freeze is the current public-data baseline after GWIS integration, PRN1 strictly-valuable permit context, and the groundwater identifiability audit. No groundwater-response model is fitted in this freeze.

- Report seed (documentation / any stochastic diagnostic): `{RNG_SEED}`
- Train / holdout convention: train through **{TRAIN_END_YEAR}**; **2023–2024 is the water-model holdout only** (electricity and Scope 2 are not held-out predictions)
- Source count: **{n_src}**. Quantity count: **{n_q}** ({n_unavail} unavailable; {n_impl} rows with implemented/partial implementation text). Boundary IDs in use: **{n_bounds}** ({n_impl_bounds} among non-unavailable quantities). Sensitivity rows: **{len(sens)}**.
- Canonical conceptual list: [`modeling/glossary_mapping.tex`](../modeling/glossary_mapping.tex)
- Do not duplicate the full README; source-specific instructions remain in [`SOURCE_INSTRUCTIONS.md`](../SOURCE_INSTRUCTIONS.md), [`DATA_DICTIONARY.md`](../DATA_DICTIONARY.md), [`MISSING_DATA_PROTOCOL.md`](../MISSING_DATA_PROTOCOL.md)

Registries and figures:

- [`outputs/pipeline_report/data_source_inventory.csv`](../outputs/pipeline_report/data_source_inventory.csv)
- [`outputs/pipeline_report/model_quantity_registry.csv`](../outputs/pipeline_report/model_quantity_registry.csv)
- [`outputs/pipeline_report/model_registry.csv`](../outputs/pipeline_report/model_registry.csv)
- [`outputs/pipeline_report/source_quantity_edges.csv`](../outputs/pipeline_report/source_quantity_edges.csv)
- [`outputs/pipeline_report/model_io_edges.csv`](../outputs/pipeline_report/model_io_edges.csv)
- [`outputs/pipeline_report/model_parameter_registry.csv`](../outputs/pipeline_report/model_parameter_registry.csv)
- [`outputs/pipeline_report/validation_scorecard.csv`](../outputs/pipeline_report/validation_scorecard.csv)
- [`outputs/pipeline_report/water_holdout_baseline_compare.csv`](../outputs/pipeline_report/water_holdout_baseline_compare.csv)
- [`outputs/pipeline_report/figure2_event_timeline.csv`](../outputs/pipeline_report/figure2_event_timeline.csv)
- [`outputs/pipeline_report/result_claims.csv`](../outputs/pipeline_report/result_claims.csv)
- [`outputs/pipeline_report/report_consistency_audit.csv`](../outputs/pipeline_report/report_consistency_audit.csv)
- [`outputs/pipeline_report/weather_finite_driver_audit.csv`](../outputs/pipeline_report/weather_finite_driver_audit.csv)
- [`outputs/pipeline_report/graybox_parameter_sensitivity.csv`](../outputs/pipeline_report/graybox_parameter_sensitivity.csv)
- [`outputs/pipeline_report/data_source_tree.mmd`](../outputs/pipeline_report/data_source_tree.mmd) / [`.png`](../outputs/pipeline_report/data_source_tree.png)
- [`outputs/pipeline_report/model_quantity_dependency.mmd`](../outputs/pipeline_report/model_quantity_dependency.mmd) / [`.png`](../outputs/pipeline_report/model_quantity_dependency.png)
- Figures: [`outputs/pipeline_report/figures/`](../outputs/pipeline_report/figures/)

---

## 1. Pipeline overview

The implemented pipeline reconstructs a **weather-driven facility** from **annual public campus totals**, then places those totals in **regional water and grid context**. It does **not** recover hourly IT telemetry, does **not** attribute Oregon generators to the campus, and does **not** run a groundwater or DID/causal model.

Layers actually executed:

1. **Targets.** `src/build_targets.py` curates Meta annual electricity (2011–2024), water withdrawal (2014–2024), location Scope 2, and operational GHG into `data/canonical/meta_prineville_annual.csv`.
2. **Weather.** Canonical KS39/KRDM with KBDN tertiary gap-only fallback → `data/processed/weather_hourly.csv` (122,736 unique local-calendar hours, 2011–2024).
3. **Gray-box physics.** `src/prineville_graybox.py` maps IT power + weather → cooling mode, PUE, raw evaporation.
4. **Conditional reconstruction.** `src/conditional_reconstruction.py` closes annual facility electricity with one latent IT-power scale per year and predicts water with a train-only multiplicative scale on raw evaporation.
5. **Stochastic proxy.** `src/stochastic_conditional_simulation.py` is a **generative scenario** with a separate annual water **prediction** horse-race (energy-only selected).
6. **Context, not coupling.** OWRD City/POD, USGS HUC12 IWA/use, EIA-930 PACW, FERC Form 714 PacifiCorp-West monthly / East+West shape, eGRID NWPP, Oregon CAMPD/EIA, DEQ backup, Crook County permits, documentary/regulatory identity and legal/network context.

Annual electricity agreement is **closure, not prediction**. IWA `availab = strflow - consum` is an **identity, not hydrologic validation**. City production is **not** Meta delivery. Direct POD is **not** total Meta withdrawal.

---

## 2. Data-source tree

See the diagram ([PNG](../outputs/pipeline_report/data_source_tree.png), [Mermaid](../outputs/pipeline_report/data_source_tree.mmd)) generated from [`source_quantity_edges.csv`](../outputs/pipeline_report/source_quantity_edges.csv) and [`model_io_edges.csv`](../outputs/pipeline_report/model_io_edges.csv). The PNG uses **visible directional arrows**.

**{n_src} sources** are listed. `{int((sources.in_source_manifest=="no").sum())}` of them exist in the executable pipeline but are **absent from `data/source_manifest.csv`**. `data/source_manifest.csv` is a **legacy/local acquisition manifest**, not the complete executable inventory. The complete executable inventory is this report's [`data_source_inventory.csv`](../outputs/pipeline_report/data_source_inventory.csv) plus the code-backed `source_inventory()` in `src/pipeline_report_catalog.py`. Lineage validation requires every source ID used by registered source→quantity edges to exist in that executable inventory. Code behavior wins.

{gw_id_md}

{doc_md}

The diagrams distinguish:

- **Conditional branch:** Meta annual facility electricity + weather → annual latent IT-scale closure → fitted hourly IT/facility power → gray-box evaporation → train-only conditional water scale → annual water prediction.
- **Stochastic branch:** scenario workload → scenario utilization / IT-power shape + Meta annual electricity → annual scaling → scenario facility/cooling quantities.
- **Separate annual water candidates:** energy-only (Meta electricity only; **evaporation is not an input**); evaporation-only; two-component NNLS.
- **Parallel external evidence:** OWRD City/POD and USGS HUC12 products are contextual series. Neither produces the other.

Branch groups: facility ground truth; weather; water; grid/carbon; Oregon generators; onsite generation/permits.

---

## 3. Data coverage

[Figure 1](../outputs/pipeline_report/figures/fig01_data_coverage_provenance.png) is the coverage heatmap.

Hard observations that exist:

- Campus **electricity**: annual 2011–2024 (reported).
- Campus **withdrawal**: annual 2014–2024 (reported); 2011–2013 not disclosed at site level.
- **Location Scope 2**: annual 2012–2024 (reported); 2011 not separately disclosed.
- **Canonical weather (KS39/KRDM + KBDN fallback)**: hourly 2011–2024 (measured stations; not on-campus). KS39 preferred from 2015-09-01 local when QC-usable. KBDN is a tertiary observational fallback only. Figure 1 provenance for this row remains `measured`.
- **PACW EIA-930**: reported hourly BA demand from 2015-07 (not campus). Consumed CO2 intensity from **2018-07**. 2011–2014 have no EIA-930 PACW hours.
- **FERC Form 714 PacifiCorp-West monthly**: reported 2011–2018 NEL/generation/interchange/peak/minimum.
- **FERC PACW-West hourly**: reconstructed proxy (West monthly level × East+West shape), 2011–2018. Not observed hourly PACW demand.
- **FERC East+West hourly**: reported combined planning-area shape; not PACW-West.
- **eGRID NWPP**: annual vintages covering 2011–2024 (2024 uses eGRID2023).
- **OWRD City and Vitesse/Facebook POD**: monthly reported use (different boundaries).
- **GWIS groundwater levels**: measured well observations from the local export (not a fitted head field). OWRD pumping remains a separate accounting series.
- **USGS NWAA**: IWA through **2020-09**; public-supply CU through 2020-12; WD/irrigation through **2020-12**. Later years are missing, not zero.
- **Oregon generators / DEQ backup / permits**: present as documented in the inventory; not campus IT meters.

Coverage statuses in Figure 1 are distinct from quantity provenance. **not an active target** (internal status `not_necessary`, black) means additional observations are not an acquisition target for that source/period because a replacement already covers the role or the quantity is intentionally latent/scenario. It does **not** mean the quantity would have no scientific value. **missing** (light gray) remains an active data gap. EIA-930 PACW hourly demand before native availability, FERC PacifiCorp-West monthly after 2018, the FERC PACW-West hourly proxy after the proxy window, and hourly IT telemetry are `not_necessary`. Hourly IT telemetry `not_necessary` means **not an active acquisition target for the current public-data pipeline**, not that hourly IT data are scientifically useless. 2011–2013 Meta water, monthly campus water delivery, monthly campus wastewater/sewer discharge, monthly/hourly campus electricity meter, early PACW consumed-CO2 intensity, post-2020 USGS hydrologic context, and 2011 Meta-reported Scope 2 remain `missing`. Those three campus-meter rows are absent as public time series in the current repository; they are not inferred from annual totals or OWRD City/POD series.

**Groundwater head observations** are `measured` for a calendar year when **at least one** valid GWIS groundwater-level observation exists in that year. That status does **not** imply continuous monthly coverage or complete spatial-network coverage. Well×year density and identifiability classifications in `outputs/groundwater/` remain authoritative.

**Permit events** from Crook County inspection summaries (including the PRN1 2021–2024 strictly-valuable package) are facility technology/commissioning evidence. They are **not** measured groundwater heads, **not** OWRD pumping, and **not** a fitted groundwater-response model.

[Figure 2](../outputs/pipeline_report/figures/fig02_observed_ground_truth.png) shows the campus ground-truth evolution plus a compact documentary/permit event strip. Observed annual series are unchanged. The pink band is labeled **2023–2024 water-model holdout** on the water and intensity panels only; electricity and Scope 2 are **not** held-out predictions. Displayed events are a presentation selection of existing HIGH/VERY_HIGH documentary facts (`config/prineville_documentary_events.csv`) and Crook County permit chronology (`data/canonical/campus_permit_events.csv`). Same-year events are not collapsed; same-date, same-category facts may share one display label while retaining all event/source IDs in [`figure2_event_timeline.csv`](../outputs/pipeline_report/figure2_event_timeline.csv). Identity-only, road/name, and renewable-accounting seed rows are excluded. The event strip is chronological context only: it does **not** attribute the 2020 water peak or later decline to any documentary event.

---

## 4. Model quantity → source/proxy mapping

Full table: [`model_quantity_registry.csv`](../outputs/pipeline_report/model_quantity_registry.csv). Dependency diagram: [PNG](../outputs/pipeline_report/model_quantity_dependency.png) generated from [`model_io_edges.csv`](../outputs/pipeline_report/model_io_edges.csv).

Each quantity has a `boundary_id` from a small controlled vocabulary. This makes mechanically visible that Meta campus withdrawal is not City production, not Vitesse/Facebook POD use, and not USGS public-supply WD; USGS local-use quantities are not routed IWA quantities; Meta facility electricity is not PACW BA demand; PACW/eGRID are not Oregon generator output. There is no boundary algebra beyond these two columns.

Provenance classes used (exactly one per row): `reported / measured / derived / fitted / simulated / scenario / proxy / unavailable`.

{"".join(q_lines)}

---

## 5. Explicit models currently used

Classification avoids calling every unit conversion a predictive model. Full table: [`model_registry.csv`](../outputs/pipeline_report/model_registry.csv).

**Implemented estimation / prediction / generative simulation / reconstruction models:**

| ID | Name | Class | Prediction? |
|---|---|---|---|
| M_GRAYBOX | Gray-box air-side physics | physics/accounting | no |
| M_ELEC_CLOSURE | Annual electricity closure via latent IT scale | reconstruction | **no (closure)** |
| M_WATER_SCALE_GLOBAL | Global log-scale on raw evaporation | estimation → holdout prediction | yes (holdout water) |
| M_WATER_SCALE_ONEBREAK | One-break water scale | estimation | not selected |
| M_WATER_ENERGY_NULL | Energy-only annual water (selected mechanistic candidate) | prediction | **yes (selected among mechanistic candidates; not best-overall)** |
| M_WATER_EVAP_PHYS | Evaporation-only annual water | prediction | candidate, not selected |
| M_WATER_TWOCOMP | Energy + evaporation NNLS | prediction | candidate, not selected |
| M_STOCHASTIC | Mixed Cox stochastic proxy | generative simulation | scenario; water horse-race is prediction |
| M_EGRID_BENCH | eGRID NWPP × Meta MWh | benchmark | no |
| M_PACW_CI | PACW consumed-CO2 relative shape | reconstruction | no |
| M_FERC714_BACKCAST | FERC-constrained PACW-West hourly proxy | reconstruction | no |
| M_FUEL_IMPORT | Fuel/import carbon score | benchmark / sensitivity | no |
| M_CHANGEPOINT | Annual SSE break ranking | change-point screening | no; not a technology claim |
| M_IWA_IDENTITY | availab = strflow − consum | physics/accounting | no; not validation |
| M_OWRD_EXTERNAL | OWRD external consistency | external-consistency check | no |
| M_OR_GEN_QC | Oregon generator QC | external-consistency check | no |
| M_GW_SCAFFOLD | Groundwater observation scaffold | physics/accounting | no; no dynamics |
| M_EWIF_PARTIAL | Partial-coverage Oregon cooling EWIF | physics/accounting | no; not Meta attribution |

---

## 6. Core equations and assumptions

### Gray-box (`src/prineville_graybox.py`)

Assumed parameters (code priors, **not reported Meta facts** except the 2011 technology class):

- `supply_target_C = 25`
- `return_air_C = 35` (**declared but unused** in `simulate()`)
- `evap_effectiveness = 0.85`
- `server_deltaT_C = 12`
- `dry_air_cp_J_kgK = 1006`
- `fan_fraction_of_it = 0.025`
- `other_facility_fraction_of_it = 0.035`
- evaporative auxiliary `0.005 × P_IT × spray`

Equations actually coded:

1. **IT heat / airflow:** \(m_\\mathrm{{air}} = P^{{IT}} \\times 10^6 / (c_p \\Delta T_\\mathrm{{server}})\).
2. **Full-evap outlet:** \(T_\\mathrm{{full}} = T_{{db}} - \\varepsilon \\max(T_{{db}}-T_{{wb}},0)\).
3. **Supply:** outdoor if \(T_{{db}} \\le 25\); else 25 °C if reachable; else \(T_\\mathrm{{full}}\).
4. **Evaporative water:** humidity-ratio increase at constant moist-air enthalpy; \(\\mathrm{{m}}^3/\\mathrm{{h}} = (\\mathrm{{kg/s}}) \\times 3.6\).
5. **Facility power:** \(P_\\mathrm{{fac}} = P^{{IT}} + 0.025 P^{{IT}} + 0.035 P^{{IT}} + 0.005 P^{{IT}} \\mathrm{{spray}}\).
6. **PUE:** \(P_\\mathrm{{fac}} / P^{{IT}}\).
7. **Modes:** `outside_air_or_winter_mix` / `partial_evap` / `full_evap`.

2011 design benchmark used only as a **design/assumption consistency or falsification check**, not independent validation: full-load PUE 1.07, WUE 0.31 L/kWh. Current modeled 2011 annual PUE = **{float(wm['modeled_2011_annual_pue']):.4f}**. Parameter inventory: [`model_parameter_registry.csv`](../outputs/pipeline_report/model_parameter_registry.csv). `return_air_C` is **declared but unused**. One-at-a-time sensitivity of documented-range overhead fractions is [Figure 7](../outputs/pipeline_report/figures/fig07_graybox_parameter_sensitivity.png); it is an assumption audit, **not a confidence interval**.

The gray-box remains a **simplified common-architecture baseline**. Crook County PRN1 permits document a meaningful late-2023 commissioning → early-2024 post-addition infrastructure transition (chilled-water / CRAH / chiller scope at PRN1). That evidence is a plausible source of model misspecification and future scenario structure. It is **not** used retrospectively to introduce a post-2023 cooling regime, retune parameters, or add a breakpoint to improve the 2023–2024 water holdout.

### Conditional reconstruction

1. Annual electricity **closure** via one latent IT-power scale (linear gray-box).
2. Weather-driven hourly gray-box **shape**.
3. Water **raw-evaporation proxy**.
4. Global vs one-break multiplicative water scale; **global selected** (\(s={float(wm['scale']):.6f}\), BIC={float(wm['bic']):.2f}).
5. Log-scale fitting (geometric mean).
6. BIC with a required improvement of 2 to prefer one-break (3 parameters).
7. Training through 2022; **2023–2024 holdout**.

### Annual water prediction candidates (stochastic workflow)

Pre-registered nonnegative no-intercept models, expanding-window one-step MAPE on train, then freeze:

- energy-only (**selected mechanistic candidate**, \(\\beta_E \\approx {float(cmap['selected_beta_e']):.4f}\\,\\mathrm{{m}}^3/\\mathrm{{MWh}}\), rolling MAPE {float(cmap['selected_rolling_mape']):.2f}%). Selected among pre-registered mechanistic/covariate candidates; **not** a claim of best overall predictor.
- evaporation-only (not selected)
- energy + evaporation NNLS (evaporation coefficient currently 0; still not selected)

### Stochastic proxy

Cox-process arrivals, AR latent intensity, Poisson counts, Gamma work sizes, aggregate queue, utilization → IT-power shape, annual facility-energy scaling, uncertain facility-overhead priors, retrospective water-shape mixture, scenario ensemble (seed {RNG_SEED}, 32 sims/year, `mixed_cox`). This is **not** recovered workload telemetry. Stochastic water/PUE intervals are **heuristic scenario ensembles under assumed workload priors**, not calibrated confidence intervals with demonstrated coverage.

### Carbon

- Meta annual **reported location Scope 2**.
- **eGRID NWPP × Meta MWh** is a **methodology/accounting consistency benchmark**, not fully independent external validation (both sides use Meta campus MWh).
- **PACW EIA consumed CO2** as regional hourly **relative shape** (optional).
- Fuel/import score: **sensitivity proxy only**.
- None of these is a Meta-specific marginal-emissions model.

### Change-point screening

`src/change_point_seed.py` ranks piecewise-linear SSE reductions. Statistical candidates only (train-only water/intensity peak at 2020). Not a physical technology-change claim.

---

## 7. Validation and predictive accuracy

Scorecard: [`validation_scorecard.csv`](../outputs/pipeline_report/validation_scorecard.csv). Evidence types A–F are separated on purpose. Type E is **not** “independent external validation”: eGRID is a methodology/accounting consistency benchmark; 2011 PUE is a design/assumption consistency check.

**Electricity.** Max absolute annual residual in `conditional_annual_compare.csv` is numerically zero. That is **calibration closure**, not forecast skill.

**Water — primary predictive figure:** [Figure 3](../outputs/pipeline_report/figures/fig03_water_model_accuracy.png).

The main figure shows observed Meta annual withdrawal, the conditional evaporation × frozen scale model, the selected energy-only frozen NNLS mechanistic candidate, and the frozen training-mean naive baseline. The complete eight-predictor comparison remains in [`water_holdout_baseline_compare.csv`](../outputs/pipeline_report/water_holdout_baseline_compare.csv).

Displayed models:

- Conditional: `W_hat_y = s * V_raw_evap_y`, with frozen `s = {float(cmap['cond_water_scale']):.6f}`.
- Selected mechanistic energy-only: `W_hat_y = beta_E * E_fac_y`.
- Frozen training mean: mean 2014–2022 observed withdrawal; not entered into mechanistic selection.

The first two are **not** dynamic time-series models. 2023–2024 was unused in fitting/selection. Holdout \(N=2\) is a diagnostic, not strong statistical evidence. The naive mean currently performs much better on holdout.

The current water specifications **perform poorly** on the pre-specified 2023–2024 holdout and are **not validated predictors** of the recent operating regime. With only two holdout years, this is a **strong predictive diagnostic failure**, not a formal statistical proof or falsification test.

The **selected mechanistic candidate** is `{cmap['selected_mechanistic_candidate']}` (expanding-window train MAPE **{float(cmap['selected_rolling_mape']):.2f}%**; frozen-NNLS holdout MAPE **{float(cmap['selected_holdout_mape']):.1f}%**). That label means it won among the pre-registered mechanistic/covariate candidates. It is **not** a claim that it is the best predictor overall. The frozen training-mean baseline was **not** entered into selection and currently has holdout MAPE **{float(cmap['training_mean_holdout_mape']):.1f}%**, much better on these two years.

The conditional scale \(s={float(cmap['cond_water_scale']):.6f}\) is an **empirically fitted mapping** from simplified raw-evaporation physics to the broader withdrawal accounting boundary — **not** a physical cooling multiplier or mass-balance parameter.

MAE, MAPE, percent error, and skill versus the training-mean baseline are **informative diagnostics rather than strong statistical evidence**. Naive baselines (training mean, training median, 2022 persistence) are frozen from training observations through 2022 and were **not** entered into model selection.

Expanding-window one-step MAPE for the selected energy-only candidate is a **train-period selection metric**. Full-training fitted/historical values are **not** those expanding-window predictions. 2023–2024 remain untouched holdout predictions.

{baseline_md}

Conditional global scale holdout (Meta annual withdrawal):

- 2023: **{float(hold.loc[hold.year.eq(2023),'water_pct_error'].iloc[0]):+.1f}%**
- 2024: **{float(hold.loc[hold.year.eq(2024),'water_pct_error'].iloc[0]):+.1f}%**
- Holdout MAPE: **{float(hold.water_pct_error.abs().mean()):.1f}%**

Selected annual energy-only model published ensemble-median diagnostic:

- 2023: **{float(stoch.loc[stoch.year.eq(2023),'water_train_only_error_pct'].iloc[0]):+.1f}%**
- 2024: **{float(stoch.loc[stoch.year.eq(2024),'water_train_only_error_pct'].iloc[0]):+.1f}%**
- Holdout MAPE: **{float(stoch.loc[stoch.split.eq('holdout'),'water_train_only_error_pct'].abs().mean()):.1f}%**

Train-period water fit is mixed (conditional 2020 **−50%**, 2022 **+70%**). Retrospective stochastic water **closure** to reported annual withdrawal is **not** predictive accuracy.

**External water:** [Figure 4](../outputs/pipeline_report/figures/fig04_external_water_context.png). Series are aligned, never stacked as a single campus total. OWRD City/POD comparisons are **boundary/context consistency, not Meta prediction error**. USGS `availab = strflow - consum` is **structural QA, not hydrologic validation**. City production is not Meta delivery. Direct POD is not total Meta withdrawal. Meta annual withdrawal is repeated across months for alignment only — not a monthly meter. USGS series are modeled HUC12 context and are omitted after documented coverage.

**Carbon:** [Figure 5](../outputs/pipeline_report/figures/fig05_carbon_benchmark.png). eGRID × Meta MWh vs Meta location Scope 2 is a **methodology/accounting consistency benchmark**, not fully independent external validation. 2024 percentage difference is about **−0.036%**. PACW hourly intensity is coverage, not campus telemetry.

**Gray-box week:** [Figure 6](../outputs/pipeline_report/figures/fig06_graybox_hot_week.png). Weather-shaped reconstruction closed to annual reported electricity; **not measured hourly campus load/IT telemetry**. Water proxy is not a meter. Selection rule is deterministic (hottest complete week), not cherry-picked. Selection: {week_meta['rule']}. Selected week start: **{week_meta['week_start_local'][:10]}**, mean dry-bulb **{week_meta['mean_t_db_C']:.2f} °C**, complete weeks considered: {week_meta['n_complete_weeks_considered']}.

**Gray-box assumption sensitivity:** [Figure 7](../outputs/pipeline_report/figures/fig07_graybox_parameter_sensitivity.png). Only `fan_fraction_of_it` and `other_facility_fraction_of_it` have a repository-documented numeric range (stochastic `sampled_facility_priors`). Other gray-box parameters have `range_not_established` and are not perturbed. Electricity closure recouples IT scale when overhead fractions change. This is not a confidence interval and not a new calibration.

---

## 8. What is observed vs inferred vs scenario

| Class | Examples in this pipeline |
|---|---|
| **Observed / reported** | Annual Meta electricity, withdrawal, location Scope 2; KS39/KRDM weather; OWRD City pumping and Vitesse/Facebook POD use (each at its own accounting boundary); GWIS measured well water levels; EIA-930 PACW hourly; FERC PacifiCorp-West monthly; FERC East+West combined hourly; DEQ backup hours where extractable; CAMPD CEMS; EIA-860/923 where reported |
| **Permit document evidence** | PRN1 addition/commissioning facts (area range, circuit counts, chilled-water/CRAH/chiller presence). Provenance `reported_permit_document_evidence`. Not measurements, not MW, not consumption |
| **Derived** | PUE, raw evaporation, eGRID tonnes, IWA availability identity, facility-kWh water intensity |
| **Fitted** | Annual IT-power scale; water multiplicative scale; NNLS water coefficients |
| **Proxy** | Hourly withdrawal proxy; USGS HUC12 use/IWA; PACW fuel/import score; FERC-constrained PACW-West hourly backcast |
| **Document context / engineering estimate** | ASR 260 MG/y application citation; GWIS well-log construction and aquifer names. Not inferred groundwater dynamics. |
| **Simulated / scenario** | Cox arrivals, queue, utilization index, overhead priors, water-shape mixture |
| **Unavailable** | See section 9. A reduced-order groundwater-head model is not fitted. |

---

## 9. Quantities still unidentified

{unavail_md}

---

## 10. What additional data would resolve each major gap

{gaps}

---

## Documentation vs executable code

If documentation disagrees with code, **code behavior wins**. Current discrepancies:

{disc}

---

## Reproducibility

```bash
python run_prineville.py report
```

The command uses existing processed data only, does not download, and fails if prerequisites are missing. Mutable fitted/result numbers are read from canonical outputs into [`result_claims.csv`](../outputs/pipeline_report/result_claims.csv) and checked by [`report_consistency_audit.csv`](../outputs/pipeline_report/report_consistency_audit.csv). It is deterministic (figure 6 week selection is a documented argmax; seed {RNG_SEED} is recorded even though this report draws no new stochastic ensemble). This generated report corresponds to freeze **Prineville Public-Data Baseline v1**. Tested Python: **3.11.15**. Direct-dependency lock: [`requirements-lock.txt`](../requirements-lock.txt).
"""
    DOCS.mkdir(parents=True, exist_ok=True)
    path = DOCS / "PIPELINE_DATA_MODEL_REPORT.md"
    path.write_text(md, encoding="utf-8")
    return path


def main() -> None:
    rng = np.random.default_rng(RNG_SEED)  # reserved; report is deterministic
    _ = rng
    check_prerequisites()
    OUT.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)

    sources = write_source_inventory()
    write_source_quantity_edges()
    write_model_io_edges()
    scorecard = write_validation_scorecard()
    baselines = pd.read_csv(OUT / "water_holdout_baseline_compare.csv")
    claims = load_result_claims()
    qty_rows, model_rows, param_rows = apply_runtime_results(
        quantity_registry(), model_registry(), parameter_registry(), claims
    )
    quantities = write_quantity_registry(qty_rows)
    models = write_model_registry(model_rows)
    write_parameter_registry(param_rows)
    claims.to_csv(OUT / "result_claims.csv", index=False)
    weather_audit = weather_driver_audit()
    weather_audit.to_csv(OUT / "weather_finite_driver_audit.csv", index=False)
    consistency = audit_report_consistency(
        quantities,
        models,
        pd.read_csv(OUT / "model_parameter_registry.csv"),
        claims,
    )
    consistency.to_csv(OUT / "report_consistency_audit.csv", index=False)
    write_source_tree_mmd(sources)
    write_quantity_mmd()
    render_source_tree_png()
    render_quantity_png()

    meta = pd.read_csv(ROOT / "data" / "canonical" / "meta_prineville_annual.csv")
    events = pd.read_csv(ROOT / "data" / "canonical" / "campus_events_seed.csv")
    water_ctx = pd.read_csv(ROOT / "data" / "processed" / "water" / "prineville_water_monthly_context.csv")
    pacw = pd.read_csv(ROOT / "outputs" / "pacw_carbon_shape_compare.csv")
    cond = pd.read_csv(ROOT / "outputs" / "conditional_annual_compare.csv")
    stoch = pd.read_csv(ROOT / "outputs" / "stochastic_proxy_annual_summary.csv")
    diag = pd.read_csv(ROOT / "outputs" / "stochastic_proxy_water_model_diagnostics.csv")
    egrid = pd.read_csv(ROOT / "outputs" / "egrid_meta_annual_compare.csv")

    figure1_coverage(meta, water_ctx, pacw)
    figure2_ground_truth(meta, events)
    figure3_water_accuracy(cond, stoch, diag, baselines)
    figure4_external_water(water_ctx, meta)
    figure5_carbon(egrid, pacw)

    hourly = pd.read_csv(
        ROOT / "outputs" / "hourly_conditional_reconstruction.csv",
        usecols=[
            "timestamp_utc", "p_it_mw", "p_fac_mw", "pue", "evap_water_m3_per_h",
            "cooling_mode", "water_withdrawal_proxy_m3_per_h",
        ],
    )
    weather = pd.read_csv(
        ROOT / "data" / "processed" / "weather_hourly.csv",
        usecols=["timestamp_utc", "t_db_C", "t_wb_C"],
    )
    week, week_meta = select_hottest_complete_week(hourly, weather)
    (OUT / "figure6_week_selection.json").write_text(json.dumps(week_meta, indent=2), encoding="utf-8")
    figure6_graybox_week(week, week_meta)

    sens, sens_base = write_graybox_parameter_sensitivity()
    figure_graybox_sensitivity(sens, sens_base)

    write_markdown(sources, quantities, models, scorecard, week_meta, baselines, sens, claims)

    required_out = [
        OUT / "data_source_inventory.csv",
        OUT / "model_quantity_registry.csv",
        OUT / "model_registry.csv",
        OUT / "source_quantity_edges.csv",
        OUT / "model_io_edges.csv",
        OUT / "model_parameter_registry.csv",
        OUT / "validation_scorecard.csv",
        OUT / "water_holdout_baseline_compare.csv",
        OUT / "figure2_event_timeline.csv",
        OUT / "result_claims.csv",
        OUT / "report_consistency_audit.csv",
        OUT / "weather_finite_driver_audit.csv",
        OUT / "graybox_parameter_sensitivity.csv",
        OUT / "data_source_tree.png",
        OUT / "data_source_tree.mmd",
        OUT / "model_quantity_dependency.png",
        OUT / "model_quantity_dependency.mmd",
        FIG / "fig01_data_coverage_provenance.png",
        FIG / "fig02_observed_ground_truth.png",
        FIG / "fig03_water_model_accuracy.png",
        FIG / "fig04_external_water_context.png",
        FIG / "fig05_carbon_benchmark.png",
        FIG / "fig06_graybox_hot_week.png",
        FIG / "fig07_graybox_parameter_sensitivity.png",
        OUT / "figure1_coverage_status.csv",
        ROOT / "docs" / "PIPELINE_DATA_MODEL_REPORT.md",
    ]
    missing = [p.as_posix() for p in required_out if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Report finished but missing artifacts: {missing}")

    print("Wrote pipeline report:")
    print(f"  sources={len(sources)} quantities={len(quantities)} models={len(models)} scorecard_rows={len(scorecard)}")
    print(f"  figure6_week={week_meta['week_start_local']} mean_tdb={week_meta['mean_t_db_C']:.2f}C")
    print(f"  markdown={DOCS / 'PIPELINE_DATA_MODEL_REPORT.md'}")


if __name__ == "__main__":
    main()
