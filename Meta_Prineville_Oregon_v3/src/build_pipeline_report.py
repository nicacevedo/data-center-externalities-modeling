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
from matplotlib.patches import FancyBboxPatch, Patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline_report_catalog import (
    DOC_VS_CODE_DISCREPANCIES,
    HOLDOUT_YEARS,
    MODEL_COLUMNS,
    PROVENANCE_CLASSES,
    QUANTITY_COLUMNS,
    REPORT_SEED,
    SOURCE_COLUMNS,
    TRAIN_END_YEAR,
    model_registry,
    quantity_registry,
    source_inventory,
)

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
    "missing": "#d9d9d9",
    "holdout": "#d73027",
    "train": "#4575b4",
}


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


def write_quantity_registry() -> pd.DataFrame:
    df = pd.DataFrame(quantity_registry(), columns=QUANTITY_COLUMNS)
    bad = set(df["provenance_class"]) - set(PROVENANCE_CLASSES)
    if bad:
        raise ValueError(f"Non-canonical provenance labels: {bad}")
    if df["quantity_id"].duplicated().any():
        raise ValueError("Duplicate quantity_id")
    df.to_csv(OUT / "model_quantity_registry.csv", index=False)
    return df


def write_model_registry() -> pd.DataFrame:
    df = pd.DataFrame(model_registry(), columns=MODEL_COLUMNS)
    if df["model_id"].duplicated().any():
        raise ValueError("Duplicate model_id")
    df.to_csv(OUT / "model_registry.csv", index=False)
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
        interpretation=f"Selection metric on training years only. coefficients={sel['coefficients']}",
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
        interpretation="PRIMARY PREDICTIVE RESULT for the selected energy-only annual model. Retrospective ensemble water closure is not this metric.",
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

    pue_2011 = float(annual.loc[annual.year.eq(2011), "annual_pue_model"].iloc[0])
    add(
        model_or_quantity="gray-box annual PUE vs 2011 design benchmark",
        evidence_type="E. independent external consistency",
        train_period="n/a (not fitted to PUE)",
        test_holdout_period="2011 design point",
        n=1,
        metric="modeled_2011_PUE_minus_1.07",
        value=f"{pue_2011 - 1.07:.4f}",
        interpretation=f"Modeled 2011 annual PUE={pue_2011:.4f} vs Meta 2011 full-load design 1.07. Diagnostic, not a fit target.",
    )

    egrid_cmp = egrid[egrid["meta_location_based_scope2_tonnes"].notna()].copy()
    egrid_cmp["pct_diff"] = 100.0 * (
        egrid_cmp["egrid_estimated_co2e_tonnes"] - egrid_cmp["meta_location_based_scope2_tonnes"]
    ) / egrid_cmp["meta_location_based_scope2_tonnes"]
    add(
        model_or_quantity="eGRID NWPP × Meta MWh vs Meta location Scope 2",
        evidence_type="E. independent external consistency",
        train_period="n/a (benchmark)",
        test_holdout_period="2012-2024 where Meta Scope 2 exists",
        n=int(len(egrid_cmp)),
        metric="median_pct_difference",
        value=f"{float(egrid_cmp['pct_diff'].median()):.2f}",
        interpretation="Physical subregion-average benchmark, not electricity prediction and not a marginal-emissions model.",
    )
    row24 = egrid[egrid.year.eq(2024)].iloc[0]
    add(
        model_or_quantity="eGRID NWPP × Meta MWh vs Meta location Scope 2",
        evidence_type="E. independent external consistency",
        train_period="n/a",
        test_holdout_period="2024 (eGRID2023 rate × 2024 MWh)",
        n=1,
        metric="pct_difference",
        value=f"{float(row24['ratio_or_percent_difference']):.4f}",
        interpretation="Column ratio_or_percent_difference is already percent. Near agreement in 2024 is a benchmark result, not campus carbon telemetry.",
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
            interpretation="City production and direct POD are not treated as Meta withdrawal. No City-vs-Meta prediction error is computed.",
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
        interpretation="Scenario/sensitivity bands. Not coverage-calibrated prediction intervals and not recovered workload telemetry.",
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
    path = OUT / "data_source_tree.mmd"
    lines = [
        "%% Prineville pipeline data-source tree",
        "%% provider → raw → processed → model → quantities",
        "flowchart TB",
        "  classDef gt fill:#dbeafe,stroke:#1d4ed8,color:#111",
        "  classDef wx fill:#ecfccb,stroke:#4d7c0f,color:#111",
        "  classDef wt fill:#cffafe,stroke:#0e7490,color:#111",
        "  classDef gd fill:#fef3c7,stroke:#b45309,color:#111",
        "  classDef gn fill:#fae8ff,stroke:#7e22ce,color:#111",
        "  classDef pm fill:#ffe4e6,stroke:#be123c,color:#111",
        "",
        "  subgraph GT[Facility ground truth]",
        "    MetaPDFs[Meta disclosure PDFs 2014-2025 vintages]",
        "    Annual[canonical meta_prineville_annual.csv]",
        "    Eng2011[2011 engineering design PUE/WUE]",
        "    MetaPDFs --> Annual",
        "    Eng2011 --> GrayPriors[gray-box priors / PUE diagnostic]",
        "  end",
        "",
        "  subgraph WX[Weather]",
        "    NOAA[NOAA NCEI Global Hourly KRDM 72692024230]",
        "    Weather[processed weather_hourly.csv]",
        "    NOAA --> Weather",
        "  end",
        "",
        "  subgraph WT[Water]",
        "    OWRD[OWRD water-use exports City + Vitesse POD]",
        "    OHA[OHA PWS 00682 inventory]",
        "    USGS[USGS NWAA IWA / public-supply / irrigation + WBD]",
        "    OWRDtab[processed OWRD monthly]",
        "    USGStab[processed USGS HUC12 panels]",
        "    Ctx[prineville_water_monthly_context.csv]",
        "    OWRD --> OWRDtab --> Ctx",
        "    OHA --> Ctx",
        "    USGS --> USGStab --> Ctx",
        "  end",
        "",
        "  subgraph GD[Grid / carbon]",
        "    EIA[EIA-930 PACW.xlsx]",
        "    PACW[processed pacw_hourly.csv]",
        "    EGRID[EPA eGRID vintages + Power Profiler ZIP 97754]",
        "    EGtab[egrid_prineville_annual.csv]",
        "    EIA --> PACW",
        "    EGRID --> EGtab",
        "  end",
        "",
        "  subgraph GN[Generators Oregon only]",
        "    CAMPD[EPA CAMPD Oregon hourly]",
        "    EIA860[EIA-860 / 923 / cooling]",
        "    ORtab[oregon_generator_externalities_monthly.csv]",
        "    CAMPD --> ORtab",
        "    EIA860 --> ORtab",
        "  end",
        "",
        "  subgraph PM[Onsite generation / permits]",
        "    DEQ[Oregon DEQ 07-0037 air + GHG workbooks]",
        "    Permits[Crook County inspection summaries]",
        "    Backup[meta_backup_* monthly tables]",
        "    Evt[campus_permit_events.csv]",
        "    DEQ --> Backup",
        "    Permits --> Evt",
        "  end",
        "",
        "  Annual --> Closure[conditional reconstruction: annual electricity closure]",
        "  Weather --> Gray[prineville_graybox.py]",
        "  Gray --> Closure",
        "  Closure --> PIT[fitted hourly IT / facility power / PUE]",
        "  PIT --> Wproxy[raw evaporation × train-only water scale]",
        "  Annual --> Wproxy",
        "  Wproxy --> Wpred[holdout water prediction]",
        "  Annual --> EGtab",
        "  EGtab --> Cbench[eGRID physical Scope 2 benchmark]",
        "  PACW --> Cshape[PACW relative carbon shape]",
        "  Ctx --> External[external water evidence; do not sum boundaries]",
        "  ORtab --> NoAttr[generator water/emissions; site attribution missing]",
        "  Backup --> Onsite[onsite backup hours/emissions; independent of Scope 2]",
        "",
        "  class MetaPDFs,Annual,Eng2011,GrayPriors gt",
        "  class NOAA,Weather wx",
        "  class OWRD,OHA,USGS,OWRDtab,USGStab,Ctx wt",
        "  class EIA,PACW,EGRID,EGtab gd",
        "  class CAMPD,EIA860,ORtab gn",
        "  class DEQ,Permits,Backup,Evt pm",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_quantity_mmd() -> Path:
    path = OUT / "model_quantity_dependency.mmd"
    path.write_text(
        """%% Quantity dependency (implemented chain). Arrow labels are provenance.
flowchart LR
  WLscen[workload scenario Cox/AR/Poisson/Gamma] -->|scenario| U[utilization index]
  U -->|scenario| Shape[IT-power shape]
  MetaE[Meta annual facility electricity] -->|reported| Closure[latent IT-power scale]
  Shape -->|scenario| Closure
  WX[KRDM weather] -->|measured| Gray[gray-box physics]
  Closure -->|fitted| Gray
  Gray -->|derived| Heat[IT heat ≈ P_IT]
  Gray -->|derived| Mode[cooling mode]
  Gray -->|derived| Fac[facility electricity hourly]
  Gray -->|derived| Evap[raw evaporation]
  Fac -->|fitted closure| MetaE
  Evap -->|proxy| Wscale[train-only water scale / energy-only candidate]
  MetaW[Meta annual withdrawal] -->|reported| Wscale
  Wscale -->|proxy| Wpred[predicted annual water]
  Fac -->|derived| PACW[PACW / eGRID]
  PACW -->|reported/derived| C[location carbon]
  MetaS2[Meta location Scope 2] -->|reported| C
  City[OWRD City production] -->|reported| Ctx[regional water context]
  POD[Vitesse/Facebook POD] -->|reported| Ctx
  USGS[USGS IWA/PS/irrigation through 2020] -->|proxy| Ctx
  Gen[Oregon CAMPD/EIA/cooling] -->|measured| GW[generator water/emissions]
  GW -->|unavailable| Attr[site attribution currently missing]
  DEQ[DEQ backup] -->|reported| Onsite[onsite backup emissions]
  GWnet[groundwater network] -->|unavailable| Head[head/storage/recharge not identified]
""",
        encoding="utf-8",
    )
    return path


def _box(ax, x, y, w, h, text, color, fontsize=7):
    p = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.02,rounding_size=0.08",
        facecolor=color,
        edgecolor="#333333",
        linewidth=0.6,
    )
    ax.add_patch(p)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fontsize, wrap=True)


def render_source_tree_png() -> Path:
    fig, ax = plt.subplots(figsize=(14.5, 9.2))
    ax.set_xlim(0, 14.5)
    ax.set_ylim(0, 9.2)
    ax.axis("off")
    ax.set_title("Data-source tree (implemented pipeline)", loc="left", fontsize=12, pad=8)

    groups = [
        (0.2, 7.4, 14.1, 1.6, "#dbeafe", "Facility ground truth",
         [(0.4, 7.6, "Meta PDFs\n2014–2025"), (2.6, 7.6, "canonical\nannual table"),
          (4.8, 7.6, "2011 design\nPUE 1.07 / WUE 0.31"), (7.0, 7.6, "build_targets.py"),
          (9.2, 7.6, "conditional +\nstochastic closure"), (11.5, 7.6, "E_fac, W_with,\nlocation S2")]),
        (0.2, 5.6, 14.1, 1.6, "#ecfccb", "Weather",
         [(0.4, 5.8, "NOAA NCEI\nKRDM 72692024230"), (2.8, 5.8, "raw/noaa\n(if present)"),
          (5.0, 5.8, "prepare_weather.py"), (7.2, 5.8, "weather_hourly.csv"),
          (9.4, 5.8, "gray-box"), (11.6, 5.8, "mode, PUE,\nraw evaporation")]),
        (0.2, 3.8, 14.1, 1.6, "#cffafe", "Water",
         [(0.4, 4.0, "OWRD / OHA"), (2.4, 4.0, "USGS NWAA\n+ WBD"),
          (4.5, 4.0, "prepare_owrd +\nusgs panels"), (6.7, 4.0, "monthly context\n(do not sum)"),
          (9.0, 4.0, "external\nconsistency"), (11.4, 4.0, "City / POD /\nIWA / irrigation")]),
        (0.2, 2.0, 7.0, 1.6, "#fef3c7", "Grid / carbon",
         [(0.4, 2.2, "EIA-930 PACW"), (2.1, 2.2, "EPA eGRID\nZIP 97754"),
          (3.9, 2.2, "prepare_eia930\nprepare_egrid"), (5.6, 2.2, "BA demand +\nNWPP benchmark")]),
        (7.4, 2.0, 6.9, 1.6, "#fae8ff", "Generators (Oregon)",
         [(7.6, 2.2, "CAMPD hourly"), (9.3, 2.2, "EIA-860/923\ncooling"),
          (11.1, 2.2, "QC tables;\nattribution missing")]),
        (0.2, 0.25, 14.1, 1.55, "#ffe4e6", "Onsite generation / permits",
         [(0.4, 0.45, "DEQ 07-0037"), (2.5, 0.45, "DEQ GHG\nPacific Power"),
          (4.7, 0.45, "Crook County\npermits"), (6.9, 0.45, "backup hours\n/ emissions"),
          (9.2, 0.45, "capacity-epoch\nannotations"), (11.5, 0.45, "not IT MW\nnot Scope 2")]),
    ]
    for x, y, w, h, c, title, boxes in groups:
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.05",
                                    facecolor=c, edgecolor="#666", linewidth=0.7, alpha=0.7))
        ax.text(x + 0.08, y + h - 0.18, title, fontsize=8, fontweight="bold", va="top")
        for bx, by, txt in boxes:
            _box(ax, bx, by, 1.7, 0.95, txt, "white", fontsize=6.2)
    fig.tight_layout()
    path = OUT / "data_source_tree.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def render_quantity_png() -> Path:
    fig, ax = plt.subplots(figsize=(13.5, 7.8))
    ax.set_xlim(0, 13.5)
    ax.set_ylim(0, 7.8)
    ax.axis("off")
    ax.set_title("Model-quantity dependency (implemented)", loc="left", fontsize=12)

    nodes = [
        (0.3, 6.4, 2.2, 0.9, COLORS["scenario"], "workload scenario\n(Cox / queue)"),
        (3.0, 6.4, 2.2, 0.9, COLORS["fitted"], "fitted IT power\n(annual scale)"),
        (5.7, 6.4, 2.2, 0.9, COLORS["derived"], "heat / cooling\nmode + P_fac"),
        (8.4, 6.4, 2.2, 0.9, COLORS["reported"], "facility electricity\n(annual reported)"),
        (11.1, 6.4, 2.1, 0.9, COLORS["proxy"], "direct-water proxy\n(evap × scale)"),
        (0.3, 4.4, 2.2, 0.9, COLORS["reported"], "facility electricity"),
        (3.0, 4.4, 2.2, 0.9, COLORS["derived"], "PACW / eGRID\nNWPP"),
        (5.7, 4.4, 2.2, 0.9, COLORS["reported"], "carbon\n(location S2 / bench)"),
        (0.3, 2.5, 2.2, 0.9, COLORS["reported"], "City POD +\nVitesse POD"),
        (3.0, 2.5, 2.2, 0.9, COLORS["proxy"], "USGS HUC12\nthrough 2020"),
        (5.7, 2.5, 2.2, 0.9, COLORS["derived"], "regional water\ncontext"),
        (8.4, 2.5, 2.2, 0.9, COLORS["measured"], "Oregon generator\ndata"),
        (11.1, 2.5, 2.1, 0.9, COLORS["unavailable"], "site attribution\ncurrently missing"),
        (0.3, 0.6, 2.2, 0.9, COLORS["unavailable"], "groundwater\nnetwork"),
        (3.0, 0.6, 2.2, 0.9, COLORS["unavailable"], "head / storage /\nrecharge not identified"),
        (8.4, 0.6, 2.2, 0.9, COLORS["reported"], "DEQ backup"),
        (11.1, 0.6, 2.1, 0.9, COLORS["reported"], "onsite emissions\n≠ Scope 2"),
    ]
    for x, y, w, h, c, t in nodes:
        _box(ax, x, y, w, h, t, c, fontsize=7)

    def arrow(x1, y1, x2, y2, label, color="#333"):
        ax.annotate(
            "",
            xy=(x2, y2),
            xytext=(x1, y1),
            arrowprops=dict(arrowstyle="->", color=color, lw=1.1),
        )
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.12, label, fontsize=6, ha="center", color=color)

    arrow(2.5, 6.85, 3.0, 6.85, "scenario", COLORS["scenario"])
    arrow(5.2, 6.85, 5.7, 6.85, "fitted", COLORS["fitted"])
    arrow(7.9, 6.85, 8.4, 6.85, "closure", COLORS["fitted"])
    arrow(10.6, 6.85, 11.1, 6.85, "proxy", COLORS["proxy"])
    arrow(2.5, 4.85, 3.0, 4.85, "derived", COLORS["derived"])
    arrow(5.2, 4.85, 5.7, 4.85, "benchmark", COLORS["derived"])
    arrow(2.5, 2.95, 3.0, 2.95, "observed", COLORS["reported"])
    arrow(5.2, 2.95, 5.7, 2.95, "proxy", COLORS["proxy"])
    arrow(10.6, 2.95, 11.1, 2.95, "unavailable", COLORS["unavailable"])
    arrow(2.5, 1.05, 3.0, 1.05, "unavailable", COLORS["unavailable"])
    arrow(10.6, 1.05, 11.1, 1.05, "reported", COLORS["reported"])
    ax.plot([9.5, 9.5], [6.4, 4.85], color=COLORS["derived"], lw=1.0)
    ax.text(9.65, 5.5, "derived", fontsize=6, color=COLORS["derived"])

    handles = [
        plt.Line2D([0], [0], marker="s", color="w", markerfacecolor=COLORS[k], markersize=10, label=k)
        for k in ("reported", "derived", "fitted", "proxy", "scenario", "unavailable")
    ]
    ax.legend(handles=handles, loc="lower right", fontsize=7, frameon=False, ncol=3)
    fig.tight_layout()
    path = OUT / "model_quantity_dependency.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def figure1_coverage(meta: pd.DataFrame, water_ctx: pd.DataFrame, pacw_cmp: pd.DataFrame) -> Path:
    years = list(range(2011, 2025))
    rows_spec = []

    def year_status(name, mapping):
        rows_spec.append((name, mapping))

    e = {int(y): "reported" for y in meta.loc[meta.electricity_mwh_reported.notna(), "year"]}
    w = {int(y): "reported" for y in meta.loc[meta.water_withdrawal_m3_reported.notna(), "year"]}
    s2 = {int(y): "reported" for y in meta.loc[meta.location_based_scope2_tco2e_reported.notna(), "year"]}
    year_status("Meta facility electricity", {y: e.get(y, "missing") for y in years})
    year_status("Meta water withdrawal", {y: w.get(y, "missing") for y in years})
    year_status("Meta location Scope 2", {y: s2.get(y, "missing") for y in years})
    year_status("KRDM weather (processed)", {y: "measured" for y in years})
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
    year_status("PACW demand / operations", {y: ("reported" if y >= 2016 or (y == 2015) else "missing") for y in years})
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
    year_status("Hourly IT telemetry", {y: "missing" for y in years})
    year_status("Monthly Meta water/electricity meters", {y: "missing" for y in years})
    year_status("Groundwater head / storage", {y: "missing" for y in years})
    year_status("Indirect electricity water (EWIF)", {y: "missing" for y in years})

    labels = [r[0] for r in rows_spec]
    code = {
        "reported": 0,
        "measured": 1,
        "derived": 2,
        "fitted": 3,
        "proxy": 4,
        "scenario": 5,
        "missing": 6,
        "unavailable": 6,
    }
    Z = np.array([[code[m[y]] for y in years] for _, m in rows_spec], dtype=float)
    cmap = ListedColormap(
        [COLORS["reported"], COLORS["measured"], COLORS["derived"], COLORS["fitted"],
         COLORS["proxy"], COLORS["scenario"], COLORS["missing"]]
    )
    fig, ax = plt.subplots(figsize=(11.5, 7.4))
    im = ax.imshow(Z, aspect="auto", cmap=cmap, vmin=0, vmax=6)
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
            Patch(facecolor=COLORS["missing"], label="missing"),
        ],
        loc="upper center",
        bbox_to_anchor=(0.5, -0.08),
        ncol=5,
        frameon=False,
        fontsize=8,
    )
    fig.tight_layout()
    path = FIG / "fig01_data_coverage_provenance.png"
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)
    return path


def figure2_ground_truth(meta: pd.DataFrame, events: pd.DataFrame) -> Path:
    z = meta.copy()
    z["intensity"] = z["water_intensity_L_per_kWh_facility_derived"]
    fig, axes = plt.subplots(4, 1, figsize=(10.8, 9.2), sharex=True)
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
    axes[3].set_xlabel("Year")

    event_years = {}
    for r in events.itertuples(index=False):
        try:
            yr = int(str(r.date)[:4])
        except (TypeError, ValueError):
            continue
        short = str(r.event_type).replace("_", " ")
        event_years[yr] = short

    for ax in axes:
        ax.axvspan(2022.5, 2024.5, color="#fee2e2", alpha=0.5, zorder=0)
        for yr in event_years:
            ax.axvline(yr, color="#9ca3af", lw=0.8, ls="--", zorder=0)
        ax.set_xlim(2009.5, 2024.5)
        ax.grid(True, axis="y", alpha=0.3)

    axes[0].text(2023.5, axes[0].get_ylim()[1] * 0.92, "holdout\n2023–24", ha="center", va="top", fontsize=7, color="#991b1b")
    ymax0 = axes[0].get_ylim()[1]
    for i, (yr, lab) in enumerate(sorted(event_years.items())):
        axes[0].text(yr, ymax0 * (0.72 - 0.12 * (i % 2)), lab, ha="center", va="top", fontsize=6.5, color="#374151")

    fig.tight_layout()
    path = FIG / "fig02_observed_ground_truth.png"
    fig.savefig(path, dpi=170)
    plt.close(fig)
    return path


def figure3_water_accuracy(cond: pd.DataFrame, stoch: pd.DataFrame, diag: pd.DataFrame) -> Path:
    c = cond.dropna(subset=["water_withdrawal_m3_reported"]).copy()
    s = stoch.dropna(subset=["water_withdrawal_m3_reported"]).copy()
    fig = plt.figure(figsize=(11.2, 8.2))
    gs = fig.add_gridspec(2, 1, height_ratios=[2.4, 1.0], hspace=0.32)
    ax = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1])

    ax.plot(c.year, c.water_withdrawal_m3_reported / 1e3, "o", color="black", ms=7, label="Observed Meta withdrawal")
    ax.plot(
        c.year,
        c.water_pred_m3 / 1e3,
        "-s",
        color="#e66101",
        ms=5,
        label="Conditional train-only prediction (evap × global scale)",
    )
    ax.plot(
        s.year,
        s.water_train_only_pred_m3_median / 1e3,
        "--^",
        color="#5e3c99",
        ms=5,
        label="Selected annual model (energy-only NNLS)",
    )
    ax.axvspan(2022.5, 2024.5, color="#fee2e2", alpha=0.55, zorder=0)
    ax.axvline(2022.5, color="#991b1b", lw=1.0, ls="--")
    ax.set_ylabel("Annual water (thousand m³)")
    ax.set_title("Figure 3 — Water model accuracy (train vs 2023–2024 holdout)", loc="left")
    ax.set_xlim(2013.5, 2024.5)
    ax.grid(True, axis="y", alpha=0.3)
    ymax = max(
        float(c.water_withdrawal_m3_reported.max()),
        float(c.water_pred_m3.max()),
        float(s.water_train_only_pred_m3_median.max()),
    ) / 1e3
    ax.set_ylim(0, ymax * 1.08)
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    ax.text(2023.5, ymax * 1.02, "holdout", ha="center", color="#991b1b", fontsize=9)

    hold_c = c[c.split.eq("holdout")]
    hold_s = s[s.split.eq("holdout")]
    train_c = c[c.split.eq("train")]
    sel = diag[diag.selected.astype(str).str.lower().eq("true")].iloc[0]
    table = [
        ["", "Train MAPE", "2023 %err", "2024 %err", "Holdout MAPE"],
        [
            "Conditional (evap × scale)",
            f"{train_c.water_pct_error.abs().mean():.1f}%",
            f"{float(hold_c.loc[hold_c.year.eq(2023), 'water_pct_error'].iloc[0]):+.1f}%",
            f"{float(hold_c.loc[hold_c.year.eq(2024), 'water_pct_error'].iloc[0]):+.1f}%",
            f"{hold_c.water_pct_error.abs().mean():.1f}%",
        ],
        [
            f"Selected annual ({sel['model']})",
            f"{float(sel['rolling_one_step_mape_pct']):.1f}% one-step",
            f"{float(hold_s.loc[hold_s.year.eq(2023), 'water_train_only_error_pct'].iloc[0]):+.1f}%",
            f"{float(hold_s.loc[hold_s.year.eq(2024), 'water_train_only_error_pct'].iloc[0]):+.1f}%",
            f"{hold_s.water_train_only_error_pct.abs().mean():.1f}%",
        ],
    ]
    ax2.axis("off")
    tbl = ax2.table(cellText=table, loc="center", cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8)
    tbl.scale(1.0, 1.6)
    for j in range(5):
        tbl[0, j].set_facecolor("#e5e7eb")
        tbl[1, j].set_facecolor("#fff7ed")
        tbl[2, j].set_facecolor("#f5f3ff")
    ax2.set_title("Holdout errors are the primary predictive result; train diagnostics are not skill on 2023–2024.", fontsize=8, loc="left", pad=8)

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

    notes = (
        "City production is not Meta delivery. Direct POD is not total Meta withdrawal. "
        "Meta annual withdrawal is repeated across months for alignment only — not a monthly meter. "
        "USGS series are modeled HUC12 context and are omitted after documented coverage."
    )
    fig.text(0.01, 0.005, notes, fontsize=7.5)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
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
    fig.text(
        0.01,
        0.01,
        "Fitted/scenario: P_IT is a within-year constant latent scale (conditional reconstruction), not telemetry. "
        "Water proxy is not a meter. Selection rule is deterministic (hottest complete week), not cherry-picked.",
        fontsize=7.5,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    path = FIG / "fig06_graybox_hot_week.png"
    fig.savefig(path, dpi=170)
    plt.close(fig)
    return path


def write_markdown(
    sources: pd.DataFrame,
    quantities: pd.DataFrame,
    models: pd.DataFrame,
    scorecard: pd.DataFrame,
    week_meta: dict,
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
            "Q_SCOPE2_EGRID", "Q_GEN_OR", "Q_W_IND", "Q_DC_GW", "Q_HEAD", "Q_ELEC_COST",
        ):
            q_lines.append(
                f"### {r.quantity} (`{r.symbol}`)\n\n"
                f"- **What is it?** {r.definition}\n"
                f"- **Where does it come from?** {r.primary_source or 'not identified'}\n"
                f"- **How is it computed?** {r.equation_transformation_model or 'not computed'}\n"
                f"- **Assumptions?** {r.modeling_assumptions or 'n/a'}\n"
                f"- **Provenance:** `{r.provenance_class}` ({r.implementation_status})\n"
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

    gaps = """
| Gap | Why it is unidentified | What would resolve it |
|---|---|---|
| Hourly IT workload / utilization | No public traces; stochastic arrivals are scenario draws | Meta/scheduler traces or feeder+IT submetering |
| Monthly campus electricity and water | Canonical table is annual; monthly Meta values are not inferred | Utility/Meta monthly meters |
| Site water consumption vs withdrawal | No discharge/CoC series | Sewer/discharge or documented consumptive fraction on the campus boundary |
| Campus source-share θ / groundwater extraction q_dc | City production and POD totals are different boundaries | Campus well/utility delivery meters with source IDs |
| Generator-to-Meta attribution | Oregon CAMPD/EIA are state tables only | Contract/path/pseudo-tie evidence or a documented BA-average EWIF used *as such* |
| Indirect electricity water | No EWIF×E_fac coupling | Documented EWIF or generator-resolved water with attribution |
| Groundwater head/storage/recharge | ASR PDFs unused numerically; IWA is surface routing | Well hydrographs + a calibrated groundwater model (out of current scope) |
| ISO WUE | Withdrawal/facility-kWh is not consumption/IT-kWh | Consumption and IT energy on ISO boundaries |
| Cost variables | No tariffs/bills | PacifiCorp / City rate schedules and bills |
| Campus footprint polygon | Site HUC12 is a point-in-polygon designation | Surveyed campus polygon |
| a2 tower WUE curves | Glossary-only; gray-box is air-side evaporative physics | Only if a cooling-tower model is actually implemented |
"""

    md = f"""# Pipeline data and model report — Meta Prineville v3

This report is generated by `src/build_pipeline_report.py` from the registries in `src/pipeline_report_catalog.py` and from **existing** processed artifacts. It describes **implemented code**, not the intended full glossary model. Modeling logic is not changed here.

- Report seed (documentation / any stochastic diagnostic): `{RNG_SEED}`
- Train / holdout convention: train through **{TRAIN_END_YEAR}**; holdout **{HOLDOUT_YEARS[0]}–{HOLDOUT_YEARS[1]}**
- Source count: **{n_src}**. Quantity count: **{n_q}** ({n_unavail} unavailable; {n_impl} rows with implemented/partial implementation text)
- Canonical conceptual list: [`modeling/glossary_mapping.tex`](../modeling/glossary_mapping.tex)
- Do not duplicate the full README; source-specific instructions remain in [`SOURCE_INSTRUCTIONS.md`](../SOURCE_INSTRUCTIONS.md), [`DATA_DICTIONARY.md`](../DATA_DICTIONARY.md), [`MISSING_DATA_PROTOCOL.md`](../MISSING_DATA_PROTOCOL.md)

Registries and figures:

- [`outputs/pipeline_report/data_source_inventory.csv`](../outputs/pipeline_report/data_source_inventory.csv)
- [`outputs/pipeline_report/model_quantity_registry.csv`](../outputs/pipeline_report/model_quantity_registry.csv)
- [`outputs/pipeline_report/model_registry.csv`](../outputs/pipeline_report/model_registry.csv)
- [`outputs/pipeline_report/validation_scorecard.csv`](../outputs/pipeline_report/validation_scorecard.csv)
- [`outputs/pipeline_report/data_source_tree.mmd`](../outputs/pipeline_report/data_source_tree.mmd) / [`.png`](../outputs/pipeline_report/data_source_tree.png)
- [`outputs/pipeline_report/model_quantity_dependency.mmd`](../outputs/pipeline_report/model_quantity_dependency.mmd) / [`.png`](../outputs/pipeline_report/model_quantity_dependency.png)
- Figures: [`outputs/pipeline_report/figures/`](../outputs/pipeline_report/figures/)

---

## 1. Pipeline overview

The implemented pipeline reconstructs a **weather-driven facility** from **annual public campus totals**, then places those totals in **regional water and grid context**. It does **not** recover hourly IT telemetry, does **not** attribute Oregon generators to the campus, and does **not** run a groundwater or DID/causal model.

Layers actually executed:

1. **Targets.** `src/build_targets.py` curates Meta annual electricity (2011–2024), water withdrawal (2014–2024), location Scope 2, and operational GHG into `data/canonical/meta_prineville_annual.csv`.
2. **Weather.** NOAA Global Hourly KRDM → `data/processed/weather_hourly.csv`.
3. **Gray-box physics.** `src/prineville_graybox.py` maps IT power + weather → cooling mode, PUE, raw evaporation.
4. **Conditional reconstruction.** `src/conditional_reconstruction.py` closes annual facility electricity with one latent IT-power scale per year and predicts water with a train-only multiplicative scale on raw evaporation.
5. **Stochastic proxy.** `src/stochastic_conditional_simulation.py` is a **generative scenario** with a separate annual water **prediction** horse-race (energy-only selected).
6. **Context, not coupling.** OWRD City/POD, USGS HUC12 IWA/use, EIA-930 PACW, eGRID NWPP, Oregon CAMPD/EIA, DEQ backup, Crook County permits.

Annual electricity agreement is **closure, not prediction**. IWA `availab = strflow - consum` is an **identity, not hydrologic validation**. City production is **not** Meta delivery. Direct POD is **not** total Meta withdrawal.

---

## 2. Data-source tree

See the diagram ([PNG](../outputs/pipeline_report/data_source_tree.png), [Mermaid](../outputs/pipeline_report/data_source_tree.mmd)) and the full inventory CSV.

**{n_src} sources** are listed. `{int((sources.in_source_manifest=="no").sum())}` of them exist in the executable pipeline but are **absent from `data/source_manifest.csv`** (CAMPD, EIA-860/923/cooling, EPA/EIA crosswalk, Oregon DEQ, Crook County permits). Code behavior wins: they are inventoried here.

Branch groups: facility ground truth; weather; water; grid/carbon; Oregon generators; onsite generation/permits.

---

## 3. Data coverage

[Figure 1](../outputs/pipeline_report/figures/fig01_data_coverage_provenance.png) is the coverage heatmap.

Hard observations that exist:

- Campus **electricity**: annual 2011–2024 (reported).
- Campus **withdrawal**: annual 2014–2024 (reported); 2011–2013 not disclosed at site level.
- **Location Scope 2**: annual 2012–2024 (reported); 2011 not separately disclosed.
- **KRDM weather**: hourly 2011–2024 (measured station; not on-campus).
- **PACW EIA-930**: hourly from 2015-07 (BA, not campus). Consumed CO2 intensity from **2018-07**.
- **eGRID NWPP**: annual vintages covering 2011–2024 (2024 uses eGRID2023).
- **OWRD City and Vitesse/Facebook POD**: monthly reported use (different boundaries).
- **USGS NWAA**: IWA through **2020-09**; public-supply CU through 2020-12; WD/irrigation through **2020-12**. Later years are missing, not zero.
- **Oregon generators / DEQ backup / permits**: present as documented in the inventory; not campus IT meters.

[Figure 2](../outputs/pipeline_report/figures/fig02_observed_ground_truth.png) shows the campus ground-truth evolution with only well-supported annotations (2011 design, 2018 REC agreement, 2021 expansion announcement, 11 buildings through 2024).

---

## 4. Model quantity → source/proxy mapping

Full table: [`model_quantity_registry.csv`](../outputs/pipeline_report/model_quantity_registry.csv). Dependency diagram: [PNG](../outputs/pipeline_report/model_quantity_dependency.png).

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
| M_WATER_ENERGY_NULL | Energy-only annual water (NNLS) | prediction | **yes (selected)** |
| M_WATER_EVAP_PHYS | Evaporation-only annual water | prediction | candidate, not selected |
| M_WATER_TWOCOMP | Energy + evaporation NNLS | prediction | candidate, not selected |
| M_STOCHASTIC | Mixed Cox stochastic proxy | generative simulation | scenario; water horse-race is prediction |
| M_EGRID_BENCH | eGRID NWPP × Meta MWh | benchmark | no |
| M_PACW_CI | PACW consumed-CO2 relative shape | reconstruction | no |
| M_FUEL_IMPORT | Fuel/import carbon score | benchmark / sensitivity | no |
| M_CHANGEPOINT | Annual SSE break ranking | change-point screening | no; not a technology claim |
| M_IWA_IDENTITY | availab = strflow − consum | physics/accounting | no; not validation |
| M_OWRD_EXTERNAL | OWRD external consistency | external-consistency check | no |
| M_OR_GEN_QC | Oregon generator QC | external-consistency check | no |

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

2011 design benchmark used only as a **falsification diagnostic**: full-load PUE 1.07, WUE 0.31 L/kWh. Current modeled 2011 annual PUE = **{float(wm['modeled_2011_annual_pue']):.4f}**.

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

- energy-only (**selected**, \(\\beta_E \\approx 0.3643\\,\\mathrm{{m}}^3/\\mathrm{{MWh}}\), rolling MAPE {float(sel['rolling_one_step_mape_pct']):.2f}%)
- evaporation-only (not selected)
- energy + evaporation NNLS (evaporation coefficient currently 0; still not selected)

### Stochastic proxy

Cox-process arrivals, AR latent intensity, Poisson counts, Gamma work sizes, aggregate queue, utilization → IT-power shape, annual facility-energy scaling, uncertain facility-overhead priors, retrospective water-shape mixture, scenario ensemble (seed {RNG_SEED}, 32 sims/year, `mixed_cox`). This is **not** recovered workload telemetry.

### Carbon

- Meta annual **reported location Scope 2**.
- **eGRID NWPP × Meta MWh** independent physical benchmark.
- **PACW EIA consumed CO2** as regional hourly **relative shape** (optional).
- Fuel/import score: **sensitivity proxy only**.
- None of these is a Meta-specific marginal-emissions model.

### Change-point screening

`src/change_point_seed.py` ranks piecewise-linear SSE reductions. Statistical candidates only (train-only water/intensity peak at 2020). Not a physical technology-change claim.

---

## 7. Validation and predictive accuracy

Scorecard: [`validation_scorecard.csv`](../outputs/pipeline_report/validation_scorecard.csv). Evidence types A–F are separated on purpose.

**Electricity.** Max absolute annual residual in `conditional_annual_compare.csv` is numerically zero. That is **closure**, not forecast skill.

**Water — primary predictive figure:** [Figure 3](../outputs/pipeline_report/figures/fig03_water_model_accuracy.png).

Conditional global scale holdout (Meta annual withdrawal):

- 2023: **{float(hold.loc[hold.year.eq(2023),'water_pct_error'].iloc[0]):+.1f}%**
- 2024: **{float(hold.loc[hold.year.eq(2024),'water_pct_error'].iloc[0]):+.1f}%**
- Holdout MAPE: **{float(hold.water_pct_error.abs().mean()):.1f}%**

Selected annual energy-only model holdout (median prediction):

- 2023: **{float(stoch.loc[stoch.year.eq(2023),'water_train_only_error_pct'].iloc[0]):+.1f}%**
- 2024: **{float(stoch.loc[stoch.year.eq(2024),'water_train_only_error_pct'].iloc[0]):+.1f}%**
- Holdout MAPE: **{float(stoch.loc[stoch.split.eq('holdout'),'water_train_only_error_pct'].abs().mean()):.1f}%**

Train-period water fit is mixed (conditional 2020 **−50%**, 2022 **+70%**). Retrospective stochastic water **closure** to reported annual withdrawal is **not** predictive accuracy.

**External water:** [Figure 4](../outputs/pipeline_report/figures/fig04_external_water_context.png). Series are aligned, never stacked as a single campus total.

**Carbon:** [Figure 5](../outputs/pipeline_report/figures/fig05_carbon_benchmark.png). eGRID is a benchmark. 2024 percentage difference vs Meta location Scope 2 is about **−0.036%**. PACW hourly intensity is coverage, not campus telemetry.

**Gray-box week:** [Figure 6](../outputs/pipeline_report/figures/fig06_graybox_hot_week.png). Selection: {week_meta['rule']}. Selected week start: **{week_meta['week_start_local'][:10]}**, mean dry-bulb **{week_meta['mean_t_db_C']:.2f} °C**, complete weeks considered: {week_meta['n_complete_weeks_considered']}.

---

## 8. What is observed vs inferred vs scenario

| Class | Examples in this pipeline |
|---|---|
| **Observed / reported** | Annual Meta electricity, withdrawal, location Scope 2; KRDM weather; OWRD City and POD; EIA-930 PACW; DEQ backup hours where extractable; CAMPD CEMS; EIA-860/923 where reported |
| **Derived** | PUE, raw evaporation, eGRID tonnes, IWA availability identity, facility-kWh water intensity |
| **Fitted** | Annual IT-power scale; water multiplicative scale; NNLS water coefficients |
| **Proxy** | Hourly withdrawal proxy; USGS HUC12 use/IWA; PACW fuel/import score |
| **Simulated / scenario** | Cox arrivals, queue, utilization index, overhead priors, water-shape mixture |
| **Unavailable** | See section 9 |

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

The command uses existing processed data only, does not download, and fails if prerequisites are missing. It is deterministic (figure 6 week selection is a documented argmax; seed {RNG_SEED} is recorded even though this report draws no new stochastic ensemble).
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
    quantities = write_quantity_registry()
    models = write_model_registry()
    scorecard = write_validation_scorecard()
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
    figure3_water_accuracy(cond, stoch, diag)
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

    write_markdown(sources, quantities, models, scorecard, week_meta)

    required_out = [
        OUT / "data_source_inventory.csv",
        OUT / "model_quantity_registry.csv",
        OUT / "model_registry.csv",
        OUT / "validation_scorecard.csv",
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
