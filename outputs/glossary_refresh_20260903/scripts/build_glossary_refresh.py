#!/usr/bin/env python3
"""Build the 2026-09-03 advisor-glossary reporting artifacts.

This script reads frozen/canonical repository artifacts only.  It does not fit,
select, tune, or promote any scientific model, and it does not rewrite the
Prineville package outputs.  The one plot recomputation from source code is the
canonical Figure 1 coverage renderer, redirected to this isolated reporting
directory.  City-service plots and tables are presentations of stored
predictions, metrics, and reconciliations.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/glossary-refresh-mpl")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[3]
PRN = REPO / "Meta_Prineville_Oregon_v3"
OUT = REPO / "outputs" / "glossary_refresh_20260903"
FIG = OUT / "figures"
TAB = OUT / "tables"
REG = OUT / "registries"
APP = OUT / "appendix"
TARGET_TEX = REPO / "main_documents" / "glossary" / "Network_Based_Data_Center_Glossary.tex"
TARGET_PDF = TARGET_TEX.with_suffix(".pdf")


class TexRaw(str):
    """A deliberately generated TeX fragment that must not be escaped again."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def md_table(headers: list[str], rows: list[list[object]]) -> str:
    def cell(v: object) -> str:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return ""
        return str(v).replace("|", "\\|").replace("\n", " ")

    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def tex_escape(value: object) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    s = str(value)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
        # Surround relationship arrows with ordinary spaces so registry prose
        # remains line-breakable in the narrow machine-generated appendices.
        "→": r" $\rightarrow$ ",
        "↔": r" $\leftrightarrow$ ",
        "×": r"$\times$",
        "≤": r"$\leq$",
        "≥": r"$\geq$",
        "≠": r"$\neq$",
        "Δ": r"$\Delta$",
        "ρ": r"$\rho$",
        "θ": r"$\theta$",
        "τ": r"$\tau$",
        "ε": r"$\varepsilon$",
        "ξ": r"$\xi$",
        "∂": r"$\partial$",
        "≈": r"$\approx$",
        "₂": r"$_2$",
        "²": r"$^2$",
        "³": r"$^3$",
        "°": r"$^\circ$",
        "’": "'",
        "−": "--",
        "–": "--",
        "—": "---",
        "…": r"\ldots{}",
    }
    # Protect literal backslashes until all input-character escaping is done;
    # subsequent replacements intentionally introduce TeX commands.
    backslash_tex = replacements.pop("\\")
    s = s.replace("\\", "@@LITERAL_BACKSLASH@@")
    for old, new in replacements.items():
        s = s.replace(old, new)
    return s.replace("@@LITERAL_BACKSLASH@@", backslash_tex).replace("\n", " ")


def tex_cell(value: object) -> str:
    return str(value) if isinstance(value, TexRaw) else tex_escape(value)


def write_tex_longtable(
    path: Path,
    caption: str,
    headers: list[str],
    rows: list[list[object]],
    widths: list[float],
    footnote_size: str = "\\scriptsize",
) -> None:
    cols = "".join(f"p{{{w:.3f}\\linewidth}}" for w in widths)
    n = len(headers)
    lines = [
        r"\begingroup",
        footnote_size,
        r"\setlength{\tabcolsep}{3pt}",
        r"\setlength{\emergencystretch}{3em}",
        r"\raggedright",
        r"\sloppy",
        rf"\begin{{longtable}}{{@{{}}{cols}@{{}}}}",
        rf"\caption{{{tex_escape(caption)}}}\\",
        r"\toprule",
        " & ".join(rf"\textbf{{{tex_escape(h)}}}" for h in headers) + r" \\",
        r"\midrule",
        r"\endfirsthead",
        r"\toprule",
        " & ".join(rf"\textbf{{{tex_escape(h)}}}" for h in headers) + r" \\",
        r"\midrule",
        r"\endhead",
        r"\midrule",
        rf"\multicolumn{{{n}}}{{r}}{{\emph{{Continued on next page}}}}\\",
        r"\endfoot",
        r"\bottomrule",
        r"\endlastfoot",
    ]
    for row in rows:
        lines.append(" & ".join(tex_cell(v) for v in row) + r" \\")
    lines += [r"\end{longtable}", r"\endgroup", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def record_manifest(paths: list[Path], dest: Path) -> pd.DataFrame:
    rows = []
    for p in paths:
        rp = p.relative_to(REPO).as_posix()
        rows.append(
            {
                "path": rp,
                "exists": p.exists(),
                "bytes": p.stat().st_size if p.exists() else None,
                "sha256": sha256(p) if p.exists() and p.is_file() else None,
            }
        )
    df = pd.DataFrame(rows)
    df.to_csv(dest, index=False)
    return df


def regenerate_registries_and_coverage() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sys.path.insert(0, str(PRN / "src"))
    import build_pipeline_report as bpr
    from pipeline_report_catalog import model_registry, parameter_registry, quantity_registry
    from pipeline_report_results import apply_runtime_results, load_result_claims

    bpr.OUT = REG
    bpr.FIG = FIG
    REG.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    sources = bpr.write_source_inventory()
    claims = load_result_claims()
    qrows, mrows, prows = apply_runtime_results(quantity_registry(), model_registry(), parameter_registry(), claims)
    quantities = bpr.write_quantity_registry(qrows)
    models = bpr.write_model_registry(mrows)
    bpr.write_parameter_registry(prows)
    bpr.write_source_quantity_edges()
    bpr.write_model_io_edges()

    meta = pd.read_csv(PRN / "data" / "canonical" / "meta_prineville_annual.csv")
    water_ctx = pd.read_csv(PRN / "data" / "processed" / "water" / "prineville_water_monthly_context.csv")
    pacw = pd.read_csv(PRN / "outputs" / "pacw_carbon_shape_compare.csv")

    # Save the canonical Matplotlib figure to both PNG and vector PDF without
    # altering its rendering function or the package's canonical output tree.
    original_savefig = matplotlib.figure.Figure.savefig

    def save_png_and_pdf(fig_obj, fname, *args, **kwargs):
        result = original_savefig(fig_obj, fname, *args, **kwargs)
        p = Path(fname)
        if p.name == "fig01_data_coverage_provenance.png":
            pdf_kwargs = dict(kwargs)
            pdf_kwargs.pop("dpi", None)
            original_savefig(fig_obj, p.with_suffix(".pdf"), *args, **pdf_kwargs)
        return result

    matplotlib.figure.Figure.savefig = save_png_and_pdf
    try:
        bpr.figure1_coverage(meta, water_ctx, pacw)
    finally:
        matplotlib.figure.Figure.savefig = original_savefig

    coverage = pd.read_csv(REG / "figure1_coverage_status.csv")
    return sources, quantities, models, coverage


def coverage_summary(sources: pd.DataFrame, quantities: pd.DataFrame, models: pd.DataFrame) -> dict:
    city = pd.read_csv(PRN / "data" / "processed" / "city_prineville" / "city_water_components_monthly.csv")
    meta = pd.read_csv(PRN / "data" / "canonical" / "meta_prineville_annual.csv")
    weather = pd.read_csv(
        PRN / "data" / "processed" / "weather_hourly.csv",
        usecols=["timestamp_local", "year_local", "weather_source", "weather_method", "post_resolution_finite"],
    )
    pumping = pd.read_csv(PRN / "data" / "processed" / "groundwater" / "groundwater_pumping_monthly.csv")
    gw = pd.read_csv(PRN / "data" / "processed" / "groundwater" / "groundwater_level_observations.csv")
    pacw = pd.read_csv(PRN / "data" / "processed" / "pacw_hourly.csv")
    ferc = pd.read_csv(PRN / "data" / "processed" / "ferc714" / "pacw_hourly_backcast.csv")

    svc = city.loc[city.city_metered_water_service_m3.notna()].copy()
    service_months_by_year = svc.groupby("year").month.nunique()
    partial_service_years = sorted(service_months_by_year.loc[service_months_by_year.ne(12)].index.astype(int).tolist())
    water = meta.loc[meta.water_withdrawal_m3_reported.notna()].copy()
    gwdt = pd.to_datetime(gw.measurement_datetime, errors="coerce")
    numeric = pd.to_numeric(gw.water_level_below_land_surface, errors="coerce").notna()
    gw_qc = pd.read_csv(PRN / "outputs" / "groundwater" / "gwis_measurement_qc_summary.csv")
    gw_overall = gw_qc.loc[gw_qc.record_type.eq("overall")].iloc[0]
    pmonths = pd.to_datetime(pumping.year_month, errors="coerce")
    pdt = pd.to_datetime(pacw.iloc[:, 0], errors="coerce")
    fdt = pd.to_datetime(ferc.iloc[:, 0], errors="coerce")
    out = {
        "source_count": int(len(sources)),
        "quantity_count": int(len(quantities)),
        "method_model_count": int(len(models)),
        "city_service": {
            "observed_months": int(len(svc)),
            "first_observed": f"{int(svc.iloc[0].year):04d}-{int(svc.iloc[0].month):02d}",
            "last_observed": f"{int(svc.iloc[-1].year):04d}-{int(svc.iloc[-1].month):02d}",
            "years_with_observation": sorted(svc.year.astype(int).unique().tolist()),
            "partial_years": partial_service_years,
            "boundary": "observed City customer-service component; not total Meta monthly withdrawal",
        },
        "meta_annual_withdrawal": {
            "reported_years": sorted(water.year.astype(int).tolist()),
            "n_years": int(len(water)),
            "boundary": "reported annual Meta campus withdrawal",
        },
        "weather": {
            "rows": int(len(weather)),
            "unique_local_hours": int(weather.timestamp_local.nunique()),
            "first_year": int(weather.year_local.min()),
            "last_year": int(weather.year_local.max()),
            "finite_driver_hours": int(pd.to_numeric(weather.post_resolution_finite, errors="coerce").eq(1).sum()),
            "source_hours": {str(k): int(v) for k, v in weather.weather_source.value_counts().items()},
            "method_hours": {str(k): int(v) for k, v in weather.weather_method.value_counts().items()},
            "hierarchy": "KS39 when QC-usable; KRDM observational fallback/backbone; monthly-bias-adjusted KBDN tertiary fallback; short bracketed gaps only",
        },
        "pumping_gwis": {
            "pumping_rows": int(len(pumping)),
            "pumping_groups": int(pumping.node_or_reporting_group_id.nunique()),
            "pumping_first_month": pmonths.min().strftime("%Y-%m"),
            "pumping_last_month": pmonths.max().strftime("%Y-%m"),
            "gwis_rows": int(len(gw)),
            "gwis_numeric_bls": int(numeric.sum()),
            "gwis_eligible_state_rows": int(gw_overall.n_eligible_for_state_model),
            "gwis_first_year_numeric": int(gwdt[numeric].dt.year.min()),
            "gwis_last_year_numeric": int(gwdt[numeric].dt.year.max()),
            "response_model_fitted": False,
        },
        "regional_grid": {
            "eia930_rows": int(len(pacw)),
            "eia930_first_timestamp": pdt.min().isoformat(),
            "eia930_last_timestamp": pdt.max().isoformat(),
            "ferc_backcast_rows": int(len(ferc)),
            "ferc_backcast_first_timestamp": fdt.min().isoformat(),
            "ferc_backcast_last_timestamp": fdt.max().isoformat(),
            "boundary": "PACW regional context; not campus electricity",
        },
        "registry_gap_note": "All-source monthly campus withdrawal is explicit in coverage/reporting but is not a distinct row in the current 82-row quantity registry; Q_W_WITH is annual.",
    }
    (OUT / "COVERAGE_PROVENANCE_SUMMARY.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    rows = [
        ["Prineville source products", len(sources), "current executable catalog", "External validation streams excluded"],
        ["Registered quantities", len(quantities), "current executable catalog", "Includes unavailable quantities"],
        ["Registered methods/models", len(models), "current executable catalog", "Not all are predictive models"],
        ["Meta annual withdrawal", len(water), f"{int(water.year.min())}--{int(water.year.max())}", "REPORTED; annual campus boundary"],
        ["City customer service", len(svc), f"{int(svc.iloc[0].year)}-{int(svc.iloc[0].month):02d} to {int(svc.iloc[-1].year)}-{int(svc.iloc[-1].month):02d}", f"OBSERVED component; partial years {', '.join(map(str, partial_service_years))}"],
        ["Canonical weather", len(weather), f"{int(weather.year_local.min())}--{int(weather.year_local.max())}", "KS39 -> KRDM -> KBDN; all required drivers finite"],
        ["Groundwater pumping", len(pumping), f"{pmonths.min():%Y-%m} to {pmonths.max():%Y-%m}", f"{pumping.node_or_reporting_group_id.nunique()} accepted reporting groups"],
        ["GWIS observations", len(gw), f"{int(gwdt[numeric].dt.year.min())}--{int(gwdt[numeric].dt.year.max())}", f"{int(numeric.sum())} numeric BLS; {int(gw_overall.n_eligible_for_state_model)} state-eligible"],
        ["EIA-930 PACW", len(pacw), f"{pdt.min():%Y-%m-%d} to {pdt.max():%Y-%m-%d}", "regional boundary"],
        ["FERC PACW backcast", len(ferc), f"{fdt.min():%Y-%m-%d} to {fdt.max():%Y-%m-%d}", "validated historical proxy"],
    ]
    pd.DataFrame(rows, columns=["item", "count", "coverage", "boundary_or_note"]).to_csv(TAB / "coverage_provenance_summary.csv", index=False)
    (TAB / "coverage_provenance_summary.md").write_text(md_table(["Item", "Count", "Coverage", "Boundary / note"], rows), encoding="utf-8")
    return out


def city_validation_outputs() -> dict:
    cdir = PRN / "outputs" / "city_prineville"
    summary = json.loads((cdir / "city_metered_service_model_summary.json").read_text(encoding="utf-8"))
    pred = pd.read_csv(cdir / "city_metered_service_monthly_predictions.csv")
    shape = pd.read_csv(cdir / "city_metered_service_graybox_shape.csv")
    city = pd.read_csv(PRN / "data" / "processed" / "city_prineville" / "city_water_components_monthly.csv")

    metrics = pd.DataFrame(summary["model_scores_common_support_pooled"])
    roles = {r["model"]: r for r in summary["information_sets"]}
    metrics["information_set"] = metrics.model.map(lambda x: roles[x]["evaluation_role"])
    metrics["forecastable_ex_ante"] = metrics.model.map(lambda x: roles[x]["forecastable_ex_ante"])
    metrics["primary_ranking_support"] = summary["primary_ranking_support"]
    metrics["response_boundary"] = "observed City WATER-COMM + ADD'L WATER service component"
    metrics.to_csv(TAB / "city_service_validation_metrics.csv", index=False)

    best = summary["best"]
    pooled = summary["graybox_shape_pooled"][0]
    year_rows = [r for r in summary["graybox_shape_years"] if r.get("scope") == "year"]
    obs_summer = [float(r["summer_fraction_obs"]) for r in year_rows]
    gray_summer = [float(r["summer_fraction_gray"]) for r in year_rows]
    result = {
        "status": summary["status"],
        "gate": summary["gate"],
        "primary_support": "common",
        "n": int(best["common_n"]),
        "evaluation_start": metrics.evaluation_start.iloc[0],
        "evaluation_end": metrics.evaluation_end.iloc[0],
        "best_model": best["best_by_mae"],
        "best_mae_m3": float(best["best_mae"]),
        "best_rmse_m3": float(best["best_rmse"]),
        "graybox_mae_m3": float(best["graybox_evap_scale_mae"]),
        "graybox_shape_share_corr": float(pooled["share_corr"]),
        "graybox_shape_share_mae": float(pooled["share_mae"]),
        "observed_summer_share_range": [min(obs_summer), max(obs_summer)],
        "graybox_summer_share_range": [min(gray_summer), max(gray_summer)],
        "conclusion": "Seasonal persistence has lower common-support error than the frozen gray-box evaporation candidate; gray-box seasonal signal is positive but too summer-concentrated.",
    }
    (OUT / "CITY_SERVICE_VALIDATION_STATUS.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    display = metrics.copy()
    display["model"] = display.model.map(
        {
            "climatology": "Month-of-year climatology",
            "seasonal_persistence": "Seasonal persistence",
            "annual_electricity_scale": "Annual-electricity scale",
            "graybox_evap_scale": "Gray-box evaporation scale",
            "scale_plus_evap": "Electricity + evaporation",
        }
    )
    rows = [
        [r.model, int(r.n), f"{r.mae:,.1f}", f"{r.rmse:,.1f}", f"{r.smape:.3f}", f"{r.median_absolute_error:,.1f}", r.information_set]
        for r in display.itertuples(index=False)
    ]
    caption = (
        "Frozen City-service validation metrics on identical common support (n=120 months across ten complete years in 2014--2024; incomplete 2015 excluded). "
        "Response is the observed City WATER-COMM + ADD'L WATER service component, not all-source Meta campus withdrawal."
    )
    write_tex_longtable(
        TAB / "city_service_validation_metrics.tex",
        caption,
        ["Model", "n", "MAE (m3)", "RMSE (m3)", "SMAPE", "Median AE (m3)", "Information set"],
        rows,
        [0.18, 0.04, 0.10, 0.10, 0.08, 0.11, 0.27],
        footnote_size=r"\footnotesize",
    )
    (TAB / "city_service_validation_metrics.md").write_text(
        caption + "\n\n" + md_table(["Model", "n", "MAE (m3)", "RMSE (m3)", "SMAPE", "Median AE (m3)", "Information set"], rows),
        encoding="utf-8",
    )

    city["date"] = pd.to_datetime(dict(year=city.year, month=city.month, day=1))
    pred["date"] = pd.to_datetime(dict(year=pred.year, month=pred.month, day=1))
    common = pred.loc[pred.year.le(2024)].copy()
    month_rows = shape.loc[shape.scope.eq("month")].copy()
    clim = month_rows.groupby("month", as_index=False)[["p_obs", "p_gray"]].mean()

    fig, axes = plt.subplots(1, 2, figsize=(13.2, 5.1), gridspec_kw={"width_ratios": [1.65, 1.0]})
    ax = axes[0]
    ax.plot(city.date, city.city_metered_water_service_m3, color="#1f4e79", lw=1.8, marker="o", ms=2.4, label="Observed City service")
    ax.plot(common.date, common.pred_seasonal_persist_m3, color="#238b45", lw=1.25, label="Seasonal persistence")
    ax.plot(common.date, common.pred_graybox_scaled_m3, color="#d95f0e", lw=1.25, label="Gray-box evaporation")
    ax.axvspan(pd.Timestamp("2012-01-01"), pd.Timestamp("2012-12-31"), color="#bdbdbd", alpha=0.18)
    ax.axvspan(pd.Timestamp("2015-01-01"), pd.Timestamp("2015-12-31"), color="#bdbdbd", alpha=0.18)
    ax.axvspan(pd.Timestamp("2026-01-01"), pd.Timestamp("2026-12-31"), color="#bdbdbd", alpha=0.18)
    ax.text(pd.Timestamp("2012-07-01"), ax.get_ylim()[1] * 0.79, "2012: Dec only", ha="center", va="top", fontsize=8, color="#666666", rotation=90)
    ax.text(pd.Timestamp("2015-07-01"), ax.get_ylim()[1] * 0.79, "2015: 11 months", ha="center", va="top", fontsize=8, color="#666666", rotation=90)
    ax.text(pd.Timestamp("2026-04-01"), ax.get_ylim()[1] * 0.94, "2026: Jan--Jul", ha="center", va="top", fontsize=8, color="#666666", rotation=90)
    ax.set_title("A  Frozen monthly validation", loc="left", fontweight="bold")
    ax.set_ylabel("Monthly volume (m$^3$)")
    ax.set_xlabel("Calendar month")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False, fontsize=8, loc="upper left")

    ax = axes[1]
    ax.plot(clim.month, 100 * clim.p_obs, color="#1f4e79", marker="o", lw=2, label="Observed service")
    ax.plot(clim.month, 100 * clim.p_gray, color="#d95f0e", marker="s", lw=2, label="Gray-box")
    ax.set_xticks(range(1, 13))
    ax.set_xticklabels(list("JFMAMJJASOND"))
    ax.set_title("B  Normalized seasonal climatology", loc="left", fontweight="bold")
    ax.set_xlabel("Month")
    ax.set_ylabel("Mean within-year share (%)")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    ax.text(
        0.03,
        0.03,
        f"Common-support n={best['common_n']} months\n"
        f"MAE: persistence {best['seasonal_persistence_mae']:,.0f} m$^3$; gray-box {best['graybox_evap_scale_mae']:,.0f} m$^3$\n"
        f"Pooled share r={pooled['share_corr']:.3f}",
        transform=ax.transAxes,
        fontsize=8,
        va="bottom",
        bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "edgecolor": "#bdbdbd", "alpha": 0.9},
    )
    fig.suptitle("City-service monthly validation — observed component, not total Meta campus withdrawal", x=0.01, ha="left", fontsize=12, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(FIG / "fig04_city_service_validation.png", dpi=180, bbox_inches="tight")
    fig.savefig(FIG / "fig04_city_service_validation.pdf", bbox_inches="tight")
    plt.close(fig)
    return result


def water_boundary_outputs() -> dict:
    cdata = PRN / "data" / "processed" / "city_prineville"
    comp = pd.read_csv(cdata / "city_water_components_monthly.csv")
    recon = pd.read_csv(cdata / "city_meta_annual_reconciliation.csv")
    compare = pd.read_csv(cdata / "city_owrd_well_meter_compare.csv")
    direct = pd.read_csv(PRN / "data" / "processed" / "owrd" / "owrd_meta_direct_monthly_use.csv")

    def span(series: pd.Series) -> tuple[int, str]:
        d = comp.loc[series.notna(), ["year", "month"]]
        return len(d), f"{int(d.iloc[0].year)}-{int(d.iloc[0].month):02d} to {int(d.iloc[-1].year)}-{int(d.iloc[-1].month):02d}"

    svc_n, svc_span = span(comp.city_metered_water_service_m3)
    bulk_n, bulk_span = span(comp.bulk_water_bill_month_m3)
    swr_n, swr_span = span(comp.swr_meter_volume_m3)
    well_n, well_span = span(comp.well_meter_for_sew_volume_m3)
    ddate = pd.to_datetime(direct.calendar_month, errors="coerce")
    rows = [
        ["Meta annual withdrawal", "Q_W_WITH / W_Meta,y", "REPORTED", "2014--2024 (11 annual values)", "No", "Annual campus disclosure; withdrawal, not consumption; no monthly allocation implied."],
        ["City WATER-COMM + ADD'L WATER service", "Q_CITY_METER_SERVICE / W_City,service,m", "OBSERVED/REPORTED", f"{svc_span} ({svc_n} observed months; 2012, 2015, and 2026 partial)", "No", "Customer municipal-service component; model response; not all-source campus withdrawal."],
        ["City bulk/hydrant", "Q_CITY_BULK_WATER", "OBSERVED/REPORTED", f"{bulk_span} ({bulk_n} billing months)", "No", "Billing-month component with unresolved campus/use boundary; service+bulk is diagnostic only."],
        ["City SWR METER", "Q_CITY_SWR_METER", "OBSERVED/REPORTED; identity unresolved", f"{swr_span} ({swr_n} months)", "No", "Keep separate; naming/numerical proximity does not establish master/submeter or return semantics."],
        ["City WELL METER FOR SEW", "Q_CITY_WELL_METER_SEW", "OBSERVED/REPORTED; identity unresolved", f"{well_span} ({well_n} months)", "No", "Weak OWRD-POD correspondence; do not infer source, sewer, or master/submeter identity."],
        ["OWRD direct Vitesse/Facebook POD", "Q_DIRECT_POD", "REPORTED", f"{ddate.min():%Y-%m} to {ddate.max():%Y-%m} ({int(direct.volume_m3.notna().sum())} reported POD-month rows)", "No", "Direct-POD reporting boundary; not total Meta withdrawal and not automatically additive to City service."],
        ["All-source monthly Meta/campus withdrawal", "W_Meta,total,m (coverage/report concept; no distinct registry row)", "NOT IDENTIFIED", "None", "No", "Service, bulk, SWR/WELL, direct POD, reuse/return/storage, lifecycle, and campus-scope relations do not close a mass balance."],
    ]
    cols = ["boundary_source", "canonical_quantity", "status", "temporal_coverage", "automatically_sum", "model_role_key_caveat"]
    pd.DataFrame(rows, columns=cols).to_csv(TAB / "city_water_boundary_accounting.csv", index=False)
    caption = "City/Meta/OWRD water-boundary map. No row may be automatically summed with another without an identified accounting relationship."
    write_tex_longtable(
        TAB / "city_water_boundary_accounting.tex",
        caption,
        ["Boundary / source", "Canonical quantity", "Status / coverage", "Auto-sum?", "Role / caveat"],
        [
            [
                r[0],
                TexRaw(r"\path{" + r[1].split(" / ")[0] + "}" + (r"\newline " + tex_escape(" / ".join(r[1].split(" / ")[1:])) if " / " in r[1] else "")) if r[1].startswith("Q_") else r[1],
                f"{r[2]}; {r[3]}",
                r[4],
                r[5],
            ]
            for r in rows
        ],
        [0.17, 0.17, 0.20, 0.08, 0.30],
        footnote_size=r"\scriptsize",
    )
    (TAB / "city_water_boundary_accounting.md").write_text(caption + "\n\n" + md_table(cols, rows), encoding="utf-8")

    complete = recon.loc[recon.meta_annual_withdrawal_m3.notna() & recon.n_service_months.eq(12)].copy()
    complete["bulk_complete"] = complete.n_bulk_months.eq(12)
    for col in ["bulk_water_bill_month_m3", "diagnostic_service_plus_bulk_m3", "residual_meta_minus_service_plus_bulk_m3", "city_service_plus_bulk_share_of_meta"]:
        complete.loc[~complete.bulk_complete, col] = np.nan
    outcols = [
        "year", "meta_annual_withdrawal_m3", "city_metered_water_service_m3", "residual_meta_minus_service_m3",
        "city_service_share_of_meta", "n_bulk_months", "bulk_water_bill_month_m3", "diagnostic_service_plus_bulk_m3",
        "residual_meta_minus_service_plus_bulk_m3", "city_service_plus_bulk_share_of_meta", "bulk_complete",
    ]
    complete[outcols].to_csv(TAB / "city_water_boundary_reconciliation_diagnostic.csv", index=False)
    diag_rows = []
    for r in complete.itertuples(index=False):
        diag_rows.append(
            [
                int(r.year), f"{r.meta_annual_withdrawal_m3:,.0f}", f"{r.city_metered_water_service_m3:,.0f}",
                f"{r.city_service_share_of_meta:.3f}",
                "" if not r.bulk_complete else f"{r.bulk_water_bill_month_m3:,.0f}",
                "" if not r.bulk_complete else f"{r.diagnostic_service_plus_bulk_m3:,.0f}",
                "" if not r.bulk_complete else f"{r.city_service_plus_bulk_share_of_meta:.3f}",
            ]
        )
    diag_caption = "Annual boundary-reconciliation diagnostic for complete City-service years. Service + bulk is diagnostic only -- not an identified campus mass balance; blank bulk combinations lack 12 billing months."
    write_tex_longtable(
        TAB / "city_water_boundary_reconciliation_diagnostic.tex",
        diag_caption,
        ["Year", "Meta", "City service", "Svc./Meta", "Bulk", "Service+bulk", "(S+B)/Meta"],
        diag_rows,
        [0.07, 0.13, 0.15, 0.12, 0.11, 0.15, 0.17],
        footnote_size=r"\footnotesize",
    )
    (TAB / "city_water_boundary_reconciliation_diagnostic.md").write_text(
        diag_caption + "\n\n" + md_table(["Year", "Meta m3", "City service m3", "Service/Meta", "Bulk m3", "Service+bulk m3", "(Service+bulk)/Meta"], diag_rows),
        encoding="utf-8",
    )

    overlap = compare[["well_meter_for_sew_m3", "owrd_direct_pod_m3"]].dropna()
    both_nonzero = overlap.loc[overlap.ne(0).all(axis=1)]
    well_status = {
        "all_overlap_n": int(len(overlap)),
        "all_overlap_pearson_r": float(overlap.corr().iloc[0, 1]),
        "both_nonzero_n": int(len(both_nonzero)),
        "both_nonzero_pearson_r": float(both_nonzero.corr().iloc[0, 1]),
        "identity_status": "UNRESOLVED",
        "inference_prohibited": "Numerical closeness/correlation does not identify source attribution or a master/submeter relationship.",
    }
    (TAB / "well_meter_for_sew_vs_owrd_pod_check.json").write_text(json.dumps(well_status, indent=2), encoding="utf-8")
    return well_status


def external_validation_outputs() -> None:
    rows = [
        ["M100", "CLOSED / FROZEN; limitations", "Measured accounting and weather structure; node power strongly bridges to, but is not equal to, facility IT.", "No generic coefficient/PUE/cooling-fraction/water transfer; node/system is not facility IT.", "Retain explicit IT + weather facility structure and boundary separation."],
        ["Frontier", "CLOSED", "Independent 9-fold evidence that IT load improves accessory-power prediction; corrected time-grid coverage 93.4%.", "No WUE, withdrawal, site-water, or transferable thermal coefficient claim.", "Retain IT-load-dependent accessory-power structure; thermal formula is an accounting reproduction."],
        ["Lei--Masanet", "PARTIAL / CLOSED; adapter blocked", "Climate-by-technology intensity and onsite conditioning-water component structure are useful.", "No quantitative adapter promotion, nonlinear IT-load twin, source/groundwater inference, or Meta calibration.", "Use only bounded qualitative/archetype scenarios; preserve P_IT=1 intensity semantics."],
        ["NLR/ESIF facility overhead", "PARTIAL / CLOSED", "Stationary IT+weather total-overhead mapping fails across the persistent 2024 HVAC/configuration regime shift.", "No coefficient transfer or claim that one cross-epoch HVAC law is validated.", "Include architecture/configuration and operating state; validate components and epochs."],
        ["Forest City v3", "Qualitative PARTIAL; quantitative NOT VALIDATED", "Same-window climate/controller replay supports mechanism-specific transportability and station-robust zero summer DX.", "Effective facility Delta-T, airflow, cooling-only water, and numerical transfer remain unidentified; model not calibrated.", "Transfer qualitative mechanisms only; engineering/utility records bind further progress."],
        ["Modern AI IT-power layer", "FROZEN / BOUNDED; node uncertainty", "Controlled CPU/H100 compute-component energy is workload/mode/scale conditioned; independent H100 sanity check passes.", "Full-node AC and same-system component-to-node bridge are unsupported; production workload mix and facility IT boundary remain incomplete.", "Use bounded workload-specific compute scenarios plus explicit uncertainty for other-node, network, storage, and service power."],
    ]
    cols = ["evidence_stream", "final_status", "strongest_supported_result", "not_identified_or_prohibited_inference", "canonical_model_consequence"]
    pd.DataFrame(rows, columns=cols).to_csv(TAB / "external_validation_synthesis.csv", index=False)
    caption = "Final frozen external-validation synthesis. These streams constrain model structure at their stated boundaries; none supplies a calibrated Prineville facility/water model."
    write_tex_longtable(
        TAB / "external_validation_synthesis.tex",
        caption,
        ["Evidence stream", "Final status", "Strongest supported result", "Not identified / prohibited inference", "Model consequence"],
        rows,
        [0.12, 0.15, 0.23, 0.23, 0.19],
        footnote_size=r"\scriptsize",
    )
    (TAB / "external_validation_synthesis.md").write_text(caption + "\n\n" + md_table(cols, rows), encoding="utf-8")


def registry_appendices(sources: pd.DataFrame, quantities: pd.DataFrame, models: pd.DataFrame) -> None:
    source_rows = []
    for r in sources.itertuples(index=False):
        source_rows.append(
            [
                TexRaw(rf"\path{{{r.source_id}}}"),
                f"{r.provider_institution}: {r.dataset_product}",
                f"{r.coverage}; {r.temporal_resolution}; status={r.reported_measured_modeled_status}",
                f"{r.model_role} Boundary: {r.spatial_resolution}. Caveat: {r.known_limitations}",
            ]
        )
    write_tex_longtable(
        APP / "source_inventory_appendix.tex",
        f"Machine-generated Prineville source inventory ({len(sources)} products). Exact acquisition routes and local paths are preserved in the accompanying regenerated CSV. External validation datasets are not included in this site-specific count.",
        ["Source ID", "Provider / product", "Coverage / status", "Role / boundary / caveat"],
        source_rows,
        [0.16, 0.25, 0.20, 0.31],
        footnote_size=r"\tiny",
    )
    (APP / "source_inventory_appendix.md").write_text(
        md_table(["Source ID", "Provider / product", "Coverage / status", "Role / boundary / caveat"], source_rows), encoding="utf-8"
    )

    quantity_rows = []
    for r in quantities.itertuples(index=False):
        quantity_rows.append(
            [
                TexRaw(rf"\path{{{r.quantity_id}}}: {tex_escape(r.quantity)}"),
                f"Unit: {r.unit}; time: {r.time_resolution}",
                TexRaw(f"{tex_escape(r.provenance_class)}; {tex_escape(r.implementation_status)}; boundary=\\path{{{r.boundary_id}}}"),
                f"{r.definition} Source/model: {r.primary_source}. Limitation: {r.missing_information_limitation}",
            ]
        )
    write_tex_longtable(
        APP / "quantity_registry_appendix.tex",
        f"Machine-generated model quantity registry ({len(quantities)} quantities).",
        ["Quantity", "Unit / resolution", "Provenance / status / boundary", "Definition / source / limitation"],
        quantity_rows,
        [0.20, 0.15, 0.22, 0.35],
        footnote_size=r"\tiny",
    )
    (APP / "quantity_registry_appendix.md").write_text(
        md_table(["Quantity", "Unit / resolution", "Provenance / status / boundary", "Definition / source / limitation"], quantity_rows), encoding="utf-8"
    )

    model_rows = []
    for r in models.itertuples(index=False):
        model_rows.append(
            [
                TexRaw(rf"\path{{{r.model_id}}}: {tex_escape(r.model_name)}"),
                f"{r.model_class}; prediction={r.is_prediction}",
                f"Training: {r.training_period}; holdout: {r.holdout_period}. {r.what_it_does}",
                f"Rule/status: {r.selection_rule}. {r.notes}",
            ]
        )
    write_tex_longtable(
        APP / "model_registry_appendix.tex",
        f"Machine-generated method/model registry ({len(models)} entries). Not every registered method is predictive.",
        ["Method / model", "Class", "Period / purpose", "Selection / status / caveat"],
        model_rows,
        [0.23, 0.15, 0.25, 0.29],
        footnote_size=r"\tiny",
    )
    (APP / "model_registry_appendix.md").write_text(
        md_table(["Method / model", "Class", "Period / purpose", "Selection / status / caveat"], model_rows), encoding="utf-8"
    )


def main() -> None:
    for d in [OUT, FIG, TAB, REG, APP]:
        d.mkdir(parents=True, exist_ok=True)

    protected_figures = [
        PRN / "outputs" / "pipeline_report" / "figures" / "fig02_observed_ground_truth.png",
        PRN / "outputs" / "pipeline_report" / "figures" / "fig03_water_model_accuracy.png",
        PRN / "outputs" / "pipeline_report" / "figures" / "fig_advisor_gwis_estimation_candidates.png",
    ]
    canonical_paths = [
        TARGET_TEX,
        TARGET_PDF,
        PRN / "README.md",
        PRN / "docs" / "PIPELINE_DATA_MODEL_REPORT.md",
        PRN / "outputs" / "pipeline_report" / "data_source_inventory.csv",
        PRN / "outputs" / "pipeline_report" / "model_quantity_registry.csv",
        PRN / "outputs" / "pipeline_report" / "model_registry.csv",
        PRN / "outputs" / "city_prineville" / "city_metered_service_model_summary.json",
        PRN / "outputs" / "city_prineville" / "city_metered_service_monthly_predictions.csv",
        PRN / "data" / "processed" / "city_prineville" / "city_meta_annual_reconciliation.csv",
        PRN / "data" / "processed" / "city_prineville" / "city_owrd_well_meter_compare.csv",
        REPO / "other_sources" / "m100" / "results" / "suitability_2021_v3_closure" / "final_status.json",
        REPO / "other_sources" / "masanet" / "results" / "followup_v1" / "FRONTIER_CLOSURE_STATUS.json",
        REPO / "other_sources" / "masanet" / "results" / "final_repro_v2" / "FINAL_MASANET_STATUS.json",
        REPO / "other_sources" / "nlr_esif_fullstack" / "facility_overhead" / "analysis" / "FINAL_ESIF_FACILITY_OVERHEAD_STATUS.json",
        REPO / "Meta_Forest_City_North_Carolina_v3" / "outputs" / "FOREST_CITY_V3_FREEZE.json",
        REPO / "Meta_Forest_City_North_Carolina_v3" / "outputs" / "FINAL_CLAIMS_LEDGER.json",
        REPO / "other_sources" / "it_power" / "analysis" / "FINAL_IT_POWER_STATUS.json",
        *protected_figures,
    ]
    before = record_manifest(canonical_paths, OUT / "CANONICAL_INPUT_HASHES_BEFORE.csv")
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "branch": git("branch", "--show-current"),
        "head": git("rev-parse", "HEAD"),
        "git_status_at_generation": git("status", "--short").splitlines(),
        "target_tex": TARGET_TEX.relative_to(REPO).as_posix(),
        "target_pdf": TARGET_PDF.relative_to(REPO).as_posix(),
        "prineville_readme": "Meta_Prineville_Oregon_v3/README.md",
        "prineville_report": "Meta_Prineville_Oregon_v3/docs/PIPELINE_DATA_MODEL_REPORT.md",
        "canonical_registry_paths": [
            "Meta_Prineville_Oregon_v3/outputs/pipeline_report/data_source_inventory.csv",
            "Meta_Prineville_Oregon_v3/outputs/pipeline_report/model_quantity_registry.csv",
            "Meta_Prineville_Oregon_v3/outputs/pipeline_report/model_registry.csv",
        ],
        "mode": "REPORTING_ONLY_NO_SCIENTIFIC_REFIT",
    }
    (OUT / "REPORTING_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    sources, quantities, models, coverage = regenerate_registries_and_coverage()
    summary = coverage_summary(sources, quantities, models)
    city_status = city_validation_outputs()
    well_status = water_boundary_outputs()
    external_validation_outputs()
    registry_appendices(sources, quantities, models)

    comparisons = []
    for name in ["data_source_inventory.csv", "model_quantity_registry.csv", "model_registry.csv"]:
        canonical = PRN / "outputs" / "pipeline_report" / name
        regenerated = REG / name
        comparisons.append(
            {
                "artifact": name,
                "canonical_sha256": sha256(canonical),
                "regenerated_sha256": sha256(regenerated),
                "byte_identical": canonical.read_bytes() == regenerated.read_bytes(),
            }
        )
    pd.DataFrame(comparisons).to_csv(OUT / "REGISTRY_REPRODUCTION_COMPARISON.csv", index=False)
    run_status = {
        "status": "PASS" if all(x["byte_identical"] for x in comparisons) else "DISCREPANCY",
        "reporting_only": True,
        "scientific_models_refit": False,
        "source_count": summary["source_count"],
        "quantity_count": summary["quantity_count"],
        "method_model_count": summary["method_model_count"],
        "coverage_rows": int(len(coverage)),
        "city_validation": city_status,
        "well_meter_vs_owrd_check": well_status,
        "protected_figure_hashes_before": {
            p.relative_to(REPO).as_posix(): sha256(p) for p in protected_figures
        },
    }
    (OUT / "REFRESH_GENERATION_STATUS.json").write_text(json.dumps(run_status, indent=2), encoding="utf-8")
    print(json.dumps(run_status, indent=2))


if __name__ == "__main__":
    main()
