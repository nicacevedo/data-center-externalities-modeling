"""Runtime fitted/result claims for the pipeline report.

Static model metadata lives in pipeline_report_catalog.py. Mutable fitted numbers
are read here from canonical output artifacts so Markdown, CSV registries, and
plot annotations cannot drift from one another.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
REPORT = OUT / "pipeline_report"
DOCS = ROOT / "docs"

COND_WATER = OUT / "conditional_water_model.csv"
COND_ANNUAL = OUT / "conditional_annual_compare.csv"
STOCH_DIAG = OUT / "stochastic_proxy_water_model_diagnostics.csv"
STOCH_ANNUAL = OUT / "stochastic_proxy_annual_summary.csv"
BASELINES = REPORT / "water_holdout_baseline_compare.csv"
WEATHER = ROOT / "data" / "processed" / "weather_hourly.csv"

CLAIM_COLUMNS = [
    "claim_id",
    "value",
    "unit",
    "source_artifact",
    "source_field_or_formula",
    "filter_or_scope",
    "formatting_note",
]

REQUIRED_WEATHER_DRIVERS = ("t_db_C", "t_wb_C", "rh_pct", "pressure_Pa")


def _station_id_cell(x) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return ""
    s = str(x).strip()
    if s in {"", "nan", "None"}:
        return ""
    if s.startswith("KBDN"):
        return "KBDN/72063800224" if "72063800224" in s.replace(".0", "") else s
    try:
        f = float(s)
        if np.isfinite(f) and abs(f - 72063800224) < 0.5:
            return "KBDN/72063800224"
        if np.isfinite(f) and f == int(f):
            return str(int(f))
    except (TypeError, ValueError):
        pass
    return s


def _f(x) -> float:
    return float(x)


def _claim(**kwargs) -> dict:
    row = {k: "" for k in CLAIM_COLUMNS}
    for k, v in kwargs.items():
        if k in CLAIM_COLUMNS:
            row[k] = v
    row["value"] = "" if kwargs.get("value") is None else str(kwargs["value"])
    return row


def _mape(pct_errors: np.ndarray) -> float:
    return float(np.mean(np.abs(np.asarray(pct_errors, dtype=float))))


def weather_unresolved_count(audit: pd.DataFrame | None = None) -> int:
    df = weather_driver_audit() if audit is None else audit
    if df.empty:
        return 0
    if "post_resolution_finite" in df.columns:
        return int(pd.to_numeric(df["post_resolution_finite"], errors="coerce").fillna(1).eq(0).sum())
    if "n_nonfinite_any_required" in df.columns:
        return int(pd.to_numeric(df["n_nonfinite_any_required"], errors="coerce").fillna(0).sum())
    return 0


def weather_driver_audit(weather: pd.DataFrame | None = None) -> pd.DataFrame:
    """Hour-level resolution audit for required-driver gaps. Does not impute."""
    w = weather if weather is not None else pd.read_csv(WEATHER)
    if "required_driver_pre_fill_nonfinite" in w.columns:
        z = w[pd.to_numeric(w["required_driver_pre_fill_nonfinite"], errors="coerce").fillna(0).eq(1)].copy()
        if z.empty:
            return pd.DataFrame(
                columns=[
                    "timestamp_utc",
                    "year_local",
                    "affected_drivers",
                    "source_station",
                    "gap_length_hours",
                    "gap_class",
                    "fallback_source",
                    "fallback_available",
                    "resolution_method",
                    "final_provenance",
                    "post_resolution_finite",
                    "weather_source",
                    "weather_method",
                    "weather_fill_method",
                ]
            )
        return pd.DataFrame(
            {
                "timestamp_utc": z["timestamp_utc"],
                "year_local": z["year_local"] if "year_local" in z.columns else "",
                "affected_drivers": z["affected_drivers_pre_fill"] if "affected_drivers_pre_fill" in z.columns else "",
                "source_station": z["station"] if "station" in z.columns else z.get("weather_source", ""),
                "gap_length_hours": z["weather_gap_length"] if "weather_gap_length" in z.columns else "",
                "gap_class": z["weather_gap_class"] if "weather_gap_class" in z.columns else "",
                "fallback_source": z["fallback_source"] if "fallback_source" in z.columns else "",
                "fallback_available": z["fallback_available"] if "fallback_available" in z.columns else 0,
                "resolution_method": z["resolution_method"] if "resolution_method" in z.columns else "",
                "final_provenance": z["provenance"] if "provenance" in z.columns else "",
                "post_resolution_finite": z["post_resolution_finite"] if "post_resolution_finite" in z.columns else 0,
                "weather_source": z["weather_source"] if "weather_source" in z.columns else "",
                "weather_method": z["weather_method"] if "weather_method" in z.columns else "",
                "weather_fill_method": z["weather_fill_method"] if "weather_fill_method" in z.columns else "",
                "t_db_primitive_gap_hours": z["t_db_primitive_gap_hours"] if "t_db_primitive_gap_hours" in z.columns else "",
                "t_dew_primitive_gap_hours": z["t_dew_primitive_gap_hours"] if "t_dew_primitive_gap_hours" in z.columns else "",
                "pressure_primitive_gap_hours": z["pressure_primitive_gap_hours"] if "pressure_primitive_gap_hours" in z.columns else "",
                "short_gap_variable_specific_ok": z["short_gap_variable_specific_ok"] if "short_gap_variable_specific_ok" in z.columns else "",
                "tertiary_source": (
                    z["tertiary_source"].map(_station_id_cell)
                    if "tertiary_source" in z.columns
                    else ""
                ),
                "source_selection_independent_of_model_results": (
                    z["source_selection_independent_of_model_results"]
                    if "source_selection_independent_of_model_results" in z.columns
                    else "yes"
                ),
            }
        )
    if "year_local" in w.columns and w["year_local"].notna().any():
        year = pd.to_numeric(w["year_local"], errors="coerce")
    else:
        ts = pd.to_datetime(w["timestamp_utc"], utc=True)
        year = ts.dt.tz_convert("America/Los_Angeles").dt.year
    rows = []
    for y, g in w.assign(_year=year).groupby("_year"):
        if not np.isfinite(y):
            continue
        rec = {"year": int(y), "n_hours": int(len(g))}
        any_bad = np.zeros(len(g), dtype=bool)
        for col in REQUIRED_WEATHER_DRIVERS:
            x = pd.to_numeric(g[col], errors="coerce").to_numpy(dtype=float)
            n_bad = int((~np.isfinite(x)).sum())
            rec[f"n_nonfinite_{col}"] = n_bad
            any_bad |= ~np.isfinite(x)
        rec["n_nonfinite_any_required"] = int(any_bad.sum())
        rec["status"] = "PASS" if rec["n_nonfinite_any_required"] == 0 else "NONFINITE_PRESENT"
        rows.append(rec)
    return pd.DataFrame(rows).sort_values("year")


def load_result_claims() -> pd.DataFrame:
    missing = [p for p in (COND_WATER, COND_ANNUAL, STOCH_DIAG, STOCH_ANNUAL, BASELINES) if not p.exists()]
    if missing:
        names = ", ".join(p.relative_to(ROOT).as_posix() for p in missing)
        raise FileNotFoundError(f"Cannot build result claims; missing artifacts: {names}")

    wm = pd.read_csv(COND_WATER).iloc[0]
    annual = pd.read_csv(COND_ANNUAL)
    diag = pd.read_csv(STOCH_DIAG)
    stoch = pd.read_csv(STOCH_ANNUAL)
    base = pd.read_csv(BASELINES)

    hold = annual[annual["split"].eq("holdout") & annual["water_withdrawal_m3_reported"].notna()]
    train_w = annual[annual["split"].eq("train") & annual["water_withdrawal_m3_reported"].notna()]
    e2023 = _f(hold.loc[hold.year.eq(2023), "water_pct_error"].iloc[0])
    e2024 = _f(hold.loc[hold.year.eq(2024), "water_pct_error"].iloc[0])
    cond_mape = _mape(hold["water_pct_error"].to_numpy(float))
    cond_train_mape = _mape(train_w["water_pct_error"].to_numpy(float))

    elec_err = (annual["electricity_mwh_model_closure"] - annual["electricity_mwh_reported"]).abs()

    sel = diag[diag["selected"].astype(str).str.lower().eq("true")]
    if len(sel) != 1:
        raise ValueError(f"Expected one selected mechanistic water candidate, found {len(sel)}")
    sel = sel.iloc[0]
    sel_coefs = json.loads(str(sel["coefficients"]))
    by_model = {str(r.model): r for r in diag.itertuples(index=False)}

    def _base(name: str) -> pd.Series:
        hit = base[base["predictor"].eq(name)]
        if len(hit) != 1:
            raise ValueError(f"Expected one baseline row for {name}, found {len(hit)}")
        return hit.iloc[0]

    b_mean = _base("training_mean")
    b_sel = _base("energy_null_frozen_nnls")
    b_ens = _base("energy_null_ensemble_median")
    b_cond = _base("conditional_global_scale")

    stoch_hold = stoch[stoch["split"].eq("holdout") & stoch["water_train_only_error_pct"].notna()]
    ens_mape = _mape(stoch_hold["water_train_only_error_pct"].to_numpy(float))

    evap = by_model["evap_physics"]
    two = by_model["two_component"]
    evap_coefs = json.loads(str(evap.coefficients))
    two_coefs = json.loads(str(two.coefficients))

    claims = [
        _claim(
            claim_id="cond_water_scale",
            value=f"{_f(wm['scale']):.15g}",
            unit="1",
            source_artifact="outputs/conditional_water_model.csv",
            source_field_or_formula="scale",
            filter_or_scope="kind=global train-only log-scale",
            formatting_note="15 significant digits; display ~6 decimals in prose",
            tex_macro="CondWaterScale",
        ),
        _claim(
            claim_id="cond_water_kind",
            value=str(wm["kind"]),
            unit="",
            source_artifact="outputs/conditional_water_model.csv",
            source_field_or_formula="kind",
            filter_or_scope="selected conditional water form",
            formatting_note="string",
            tex_macro="CondWaterKind",
        ),
        _claim(
            claim_id="cond_water_bic",
            value=f"{_f(wm['bic']):.15g}",
            unit="1",
            source_artifact="outputs/conditional_water_model.csv",
            source_field_or_formula="bic",
            filter_or_scope="global model BIC on training years",
            formatting_note="15 significant digits; display 2 decimals in prose",
            tex_macro="CondWaterBIC",
        ),
        _claim(
            claim_id="cond_holdout_pct_error_2023",
            value=f"{e2023:.15g}",
            unit="percent",
            source_artifact="outputs/conditional_annual_compare.csv",
            source_field_or_formula="water_pct_error",
            filter_or_scope="year=2023 split=holdout",
            formatting_note="percent; display 1 decimal with sign",
            tex_macro="CondHoldoutPctErrMMXXIII",
        ),
        _claim(
            claim_id="cond_holdout_pct_error_2024",
            value=f"{e2024:.15g}",
            unit="percent",
            source_artifact="outputs/conditional_annual_compare.csv",
            source_field_or_formula="water_pct_error",
            filter_or_scope="year=2024 split=holdout",
            formatting_note="percent; display 1 decimal with sign",
            tex_macro="CondHoldoutPctErrMMXXIV",
        ),
        _claim(
            claim_id="cond_holdout_mape",
            value=f"{cond_mape:.15g}",
            unit="percent",
            source_artifact="outputs/conditional_annual_compare.csv",
            source_field_or_formula="mean(abs(water_pct_error))",
            filter_or_scope="split=holdout years with observed water",
            formatting_note="percent; display 1 decimal",
            tex_macro="CondHoldoutMAPE",
        ),
        _claim(
            claim_id="cond_train_mape",
            value=f"{cond_train_mape:.15g}",
            unit="percent",
            source_artifact="outputs/conditional_annual_compare.csv",
            source_field_or_formula="mean(abs(water_pct_error))",
            filter_or_scope="split=train years with observed water",
            formatting_note="percent; display 1 decimal",
            tex_macro="CondTrainMAPE",
        ),
        _claim(
            claim_id="cond_modeled_2011_pue",
            value=f"{_f(wm['modeled_2011_annual_pue']):.15g}",
            unit="1",
            source_artifact="outputs/conditional_water_model.csv",
            source_field_or_formula="modeled_2011_annual_pue",
            filter_or_scope="2011 design/assumption check",
            formatting_note="4 decimals in prose",
            tex_macro="CondModeledPUEMMXI",
        ),
        _claim(
            claim_id="elec_closure_max_abs_mwh",
            value=f"{_f(elec_err.max()):.15g}",
            unit="MWh",
            source_artifact="outputs/conditional_annual_compare.csv",
            source_field_or_formula="max(abs(electricity_mwh_model_closure - electricity_mwh_reported))",
            filter_or_scope="all reconstructed years",
            formatting_note="scientific notation in scorecard",
            tex_macro="ElecClosureMaxAbsMWh",
        ),
        _claim(
            claim_id="selected_mechanistic_candidate",
            value=str(sel["model"]),
            unit="",
            source_artifact="outputs/stochastic_proxy_water_model_diagnostics.csv",
            source_field_or_formula="model where selected=True",
            filter_or_scope="pre-registered mechanistic/covariate candidates only",
            formatting_note="string; not a claim of best overall predictor",
            tex_macro="SelectedMechanisticCandidate",
        ),
        _claim(
            claim_id="selected_rolling_mape",
            value=f"{_f(sel['rolling_one_step_mape_pct']):.15g}",
            unit="percent",
            source_artifact="outputs/stochastic_proxy_water_model_diagnostics.csv",
            source_field_or_formula="rolling_one_step_mape_pct",
            filter_or_scope="selected mechanistic candidate; train expanding-window",
            formatting_note="percent; display 2 decimals",
            tex_macro="SelectedRollingMAPE",
        ),
        _claim(
            claim_id="selected_beta_e",
            value=f"{_f(sel_coefs['electricity_mwh_reported']):.15g}",
            unit="m3/MWh",
            source_artifact="outputs/stochastic_proxy_water_model_diagnostics.csv",
            source_field_or_formula="coefficients.electricity_mwh_reported",
            filter_or_scope="selected energy_null NNLS",
            formatting_note="15 significant digits",
            tex_macro="SelectedBetaE",
        ),
        _claim(
            claim_id="selected_holdout_mape",
            value=f"{_f(b_sel['MAPE_pct']):.15g}",
            unit="percent",
            source_artifact="outputs/pipeline_report/water_holdout_baseline_compare.csv",
            source_field_or_formula="MAPE_pct",
            filter_or_scope="predictor=energy_null_frozen_nnls",
            formatting_note="percent; display 1 decimal; selected equation frozen on train",
            tex_macro="SelectedHoldoutMAPE",
        ),
        _claim(
            claim_id="selected_holdout_pct_error_2023",
            value=f"{_f(b_sel['pct_error_2023']):.15g}",
            unit="percent",
            source_artifact="outputs/pipeline_report/water_holdout_baseline_compare.csv",
            source_field_or_formula="pct_error_2023",
            filter_or_scope="predictor=energy_null_frozen_nnls",
            formatting_note="percent; display 1 decimal with sign",
            tex_macro="SelectedHoldoutPctErrMMXXIII",
        ),
        _claim(
            claim_id="selected_holdout_pct_error_2024",
            value=f"{_f(b_sel['pct_error_2024']):.15g}",
            unit="percent",
            source_artifact="outputs/pipeline_report/water_holdout_baseline_compare.csv",
            source_field_or_formula="pct_error_2024",
            filter_or_scope="predictor=energy_null_frozen_nnls",
            formatting_note="percent; display 1 decimal with sign",
            tex_macro="SelectedHoldoutPctErrMMXXIV",
        ),
        _claim(
            claim_id="energy_null_ensemble_holdout_mape",
            value=f"{ens_mape:.15g}",
            unit="percent",
            source_artifact="outputs/stochastic_proxy_annual_summary.csv",
            source_field_or_formula="mean(abs(water_train_only_error_pct))",
            filter_or_scope="split=holdout ensemble-median diagnostic; not model selection",
            formatting_note="percent; display 1 decimal",
            tex_macro="EnergyNullEnsembleHoldoutMAPE",
        ),
        _claim(
            claim_id="training_mean_holdout_mape",
            value=f"{_f(b_mean['MAPE_pct']):.15g}",
            unit="percent",
            source_artifact="outputs/pipeline_report/water_holdout_baseline_compare.csv",
            source_field_or_formula="MAPE_pct",
            filter_or_scope="predictor=training_mean; not in mechanistic selection",
            formatting_note="percent; display 1 decimal",
            tex_macro="TrainingMeanHoldoutMAPE",
        ),
        _claim(
            claim_id="training_mean_pct_error_2023",
            value=f"{_f(b_mean['pct_error_2023']):.15g}",
            unit="percent",
            source_artifact="outputs/pipeline_report/water_holdout_baseline_compare.csv",
            source_field_or_formula="pct_error_2023",
            filter_or_scope="predictor=training_mean",
            formatting_note="percent; display 1 decimal with sign",
            tex_macro="TrainingMeanPctErrMMXXIII",
        ),
        _claim(
            claim_id="training_mean_pct_error_2024",
            value=f"{_f(b_mean['pct_error_2024']):.15g}",
            unit="percent",
            source_artifact="outputs/pipeline_report/water_holdout_baseline_compare.csv",
            source_field_or_formula="pct_error_2024",
            filter_or_scope="predictor=training_mean",
            formatting_note="percent; display 1 decimal with sign",
            tex_macro="TrainingMeanPctErrMMXXIV",
        ),
        _claim(
            claim_id="conditional_baseline_holdout_mape",
            value=f"{_f(b_cond['MAPE_pct']):.15g}",
            unit="percent",
            source_artifact="outputs/pipeline_report/water_holdout_baseline_compare.csv",
            source_field_or_formula="MAPE_pct",
            filter_or_scope="predictor=conditional_global_scale",
            formatting_note="must match cond_holdout_mape",
            tex_macro="ConditionalBaselineHoldoutMAPE",
        ),
        _claim(
            claim_id="evap_physics_beta_v",
            value=f"{_f(evap_coefs['raw_evap_m3_median']):.15g}",
            unit="1",
            source_artifact="outputs/stochastic_proxy_water_model_diagnostics.csv",
            source_field_or_formula="coefficients.raw_evap_m3_median",
            filter_or_scope="evap_physics not selected",
            formatting_note="15 significant digits",
            tex_macro="EvapPhysicsBetaV",
        ),
        _claim(
            claim_id="evap_physics_rolling_mape",
            value=f"{_f(evap.rolling_one_step_mape_pct):.15g}",
            unit="percent",
            source_artifact="outputs/stochastic_proxy_water_model_diagnostics.csv",
            source_field_or_formula="rolling_one_step_mape_pct",
            filter_or_scope="evap_physics not selected",
            formatting_note="percent; display 2 decimals",
            tex_macro="EvapPhysicsRollingMAPE",
        ),
        _claim(
            claim_id="two_component_beta_e",
            value=f"{_f(two_coefs['electricity_mwh_reported']):.15g}",
            unit="m3/MWh",
            source_artifact="outputs/stochastic_proxy_water_model_diagnostics.csv",
            source_field_or_formula="coefficients.electricity_mwh_reported",
            filter_or_scope="two_component not selected",
            formatting_note="15 significant digits",
            tex_macro="TwoComponentBetaE",
        ),
        _claim(
            claim_id="two_component_beta_v",
            value=f"{_f(two_coefs.get('raw_evap_m3_median', 0.0)):.15g}",
            unit="1",
            source_artifact="outputs/stochastic_proxy_water_model_diagnostics.csv",
            source_field_or_formula="coefficients.raw_evap_m3_median",
            filter_or_scope="two_component not selected",
            formatting_note="15 significant digits",
            tex_macro="TwoComponentBetaV",
        ),
        _claim(
            claim_id="two_component_rolling_mape",
            value=f"{_f(two.rolling_one_step_mape_pct):.15g}",
            unit="percent",
            source_artifact="outputs/stochastic_proxy_water_model_diagnostics.csv",
            source_field_or_formula="rolling_one_step_mape_pct",
            filter_or_scope="two_component not selected",
            formatting_note="percent; display 2 decimals",
            tex_macro="TwoComponentRollingMAPE",
        ),
        _claim(
            claim_id="energy_null_ensemble_holdout_mape_from_baselines",
            value=f"{_f(b_ens['MAPE_pct']):.15g}",
            unit="percent",
            source_artifact="outputs/pipeline_report/water_holdout_baseline_compare.csv",
            source_field_or_formula="MAPE_pct",
            filter_or_scope="predictor=energy_null_ensemble_median",
            formatting_note="must match energy_null_ensemble_holdout_mape",
            tex_macro="EnergyNullEnsembleHoldoutMAPEFromBaselines",
        ),
    ]
    df = pd.DataFrame(claims, columns=CLAIM_COLUMNS)
    if df["claim_id"].duplicated().any():
        dups = df.loc[df["claim_id"].duplicated(), "claim_id"].tolist()
        raise ValueError(f"Duplicate claim_id values: {dups}")
    return df


def claims_map(claims: pd.DataFrame) -> dict[str, str]:
    return dict(zip(claims["claim_id"], claims["value"]))


def claim_float(claims: pd.DataFrame, claim_id: str) -> float:
    return float(claims_map(claims)[claim_id])


def fmt_signed_pct(value: float, digits: int = 1) -> str:
    return f"{value:+.{digits}f}"


def fmt_pct(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}"


def apply_runtime_results(
    quantities: list[dict],
    models: list[dict],
    parameters: list[dict],
    claims: pd.DataFrame,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Fill fitted/current-result fields from runtime claims. Catalog stays static."""
    c = claims_map(claims)
    scale = c["cond_water_scale"]
    bic = c["cond_water_bic"]
    kind = c["cond_water_kind"]
    e23 = fmt_signed_pct(float(c["cond_holdout_pct_error_2023"]))
    e24 = fmt_signed_pct(float(c["cond_holdout_pct_error_2024"]))
    cond_mape = fmt_pct(float(c["cond_holdout_mape"]))
    sel_name = c["selected_mechanistic_candidate"]
    roll = fmt_pct(float(c["selected_rolling_mape"]), 2)
    beta = c["selected_beta_e"]
    sel_mape = fmt_pct(float(c["selected_holdout_mape"]))
    mean_mape = fmt_pct(float(c["training_mean_holdout_mape"]))
    evap_b = c["evap_physics_beta_v"]
    evap_r = fmt_pct(float(c["evap_physics_rolling_mape"]), 2)
    two_e = c["two_component_beta_e"]
    two_v = c["two_component_beta_v"]
    two_r = fmt_pct(float(c["two_component_rolling_mape"]), 2)

    for q in quantities:
        if q["quantity_id"] == "Q_WATER_PROXY":
            q["fitted_parameters"] = (
                f"{kind} scale {scale} (train through 2022); one-break not selected. "
                "Scale is an empirical mapping from raw evaporation to the withdrawal "
                "accounting boundary, not a physical cooling multiplier."
            )
            q["accuracy_diagnostic_available"] = (
                f"water_pct_error in conditional_annual_compare.csv; "
                f"holdout 2023 {e23}%, 2024 {e24}%; holdout MAPE {cond_mape}%"
            )
            q["modeling_assumptions"] = (
                "raw evaporation shape is a weather driver; the fitted scale maps "
                "simplified raw-evaporation physics onto the broader Meta withdrawal "
                "accounting boundary and is not a physical cooling multiplier or "
                "mass-balance parameter"
            )
            q["confidence_level"] = (
                "low (holdout fails; not a validated predictor of the 2023-2024 regime)"
            )

    for m in models:
        if m["model_id"] == "M_WATER_SCALE_GLOBAL":
            m["parameters_priors"] = (
                f"s_hat = {scale} from outputs/conditional_water_model.csv; "
                "empirical withdrawal-boundary mapping, not a physical cooling multiplier"
            )
            m["selection_rule"] = (
                f"BIC vs one-break; require BIC improvement > 2 to prefer one-break. "
                f"Current selection: {kind}, BIC={float(bic):.2f}"
            )
            m["notes"] = (
                f"Selected over the one-break alternative. Holdout 2023 {e23}%, 2024 {e24}% "
                f"(MAPE {cond_mape}%) is a two-year predictive diagnostic failure, not a "
                "formal statistical proof. Frozen training-mean baseline is not in this "
                "selection and currently performs much better on the two holdout years."
            )
        elif m["model_id"] == "M_WATER_ENERGY_NULL":
            m["model_name"] = "Annual water selected mechanistic candidate: energy-only"
            m["parameters_priors"] = (
                f"β_E = {beta} m³/MWh in current diagnostics"
            )
            m["notes"] = (
                f"Selected mechanistic candidate among pre-registered energy/evaporation "
                f"candidates (not a claim of best overall predictor). Expanding-window "
                f"train MAPE {roll}%; frozen-NNLS holdout MAPE {sel_mape}%. Frozen "
                f"training-mean baseline holdout MAPE {mean_mape}% was not in selection. "
                "Holdout N=2 is a diagnostic, not a formal proof."
            )
        elif m["model_id"] == "M_WATER_EVAP_PHYS":
            m["parameters_priors"] = (
                f"β_v = {evap_b} in current diagnostics (not used for selected predictions)"
            )
            m["selection_rule"] = (
                f"same expanding-window MAPE; score {evap_r}% (worse than {sel_name})"
            )
        elif m["model_id"] == "M_WATER_TWOCOMP":
            m["parameters_priors"] = f"β_E={two_e}; β_v={two_v} in current diagnostics"
            m["parameter_provenance"] = (
                f"NNLS on train; not selected (higher rolling MAPE {two_r}%)"
            )
        elif m["model_id"] == "M_STOCHASTIC":
            m["notes"] = (
                m.get("notes", "")
                + " Stochastic water/PUE intervals are heuristic scenario ensembles "
                "under assumed workload/overhead priors, not calibrated confidence "
                "intervals with demonstrated coverage."
            ).strip()

    for p in parameters:
        if p["model_id"] == "M_WATER_SCALE_GLOBAL" and p["parameter"] == "water_scale":
            p["value"] = scale
            p["notes"] = (
                "Geometric-mean scale fitted on train years with water. Empirical mapping "
                "from simplified raw-evaporation physics to the Meta withdrawal accounting "
                "boundary; not a gray-box physical parameter and not a mass-balance multiplier."
            )
        if p["model_id"] == "M_WATER_ENERGY_NULL" and p["parameter"] == "beta_electricity_m3_per_mwh":
            p["value"] = beta

    return quantities, models, parameters


def _close(a: float, b: float, rtol: float = 1e-9, atol: float = 1e-8) -> bool:
    return math.isclose(a, b, rel_tol=rtol, abs_tol=atol)


def audit_report_consistency(
    quantities: pd.DataFrame,
    models: pd.DataFrame,
    parameters: pd.DataFrame,
    claims: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    def add(check: str, status: str, detail: str) -> None:
        rows.append({"check": check, "status": status, "detail": detail})

    if claims["claim_id"].duplicated().any():
        add("claim_ids_unique", "FAIL", str(claims.loc[claims["claim_id"].duplicated(), "claim_id"].tolist()))
    else:
        add("claim_ids_unique", "PASS", f"n={len(claims)}")

    c = claims_map(claims)
    scale = float(c["cond_water_scale"])
    bic = float(c["cond_water_bic"])
    e23 = float(c["cond_holdout_pct_error_2023"])
    e24 = float(c["cond_holdout_pct_error_2024"])
    mape = float(c["cond_holdout_mape"])
    sel = c["selected_mechanistic_candidate"]
    beta = float(c["selected_beta_e"])
    roll = float(c["selected_rolling_mape"])
    sel_mape = float(c["selected_holdout_mape"])

    wm = pd.read_csv(COND_WATER).iloc[0]
    annual = pd.read_csv(COND_ANNUAL)
    diag = pd.read_csv(STOCH_DIAG)
    hold = annual[annual["split"].eq("holdout") & annual["water_withdrawal_m3_reported"].notna()]
    src_e23 = float(hold.loc[hold.year.eq(2023), "water_pct_error"].iloc[0])
    src_e24 = float(hold.loc[hold.year.eq(2024), "water_pct_error"].iloc[0])
    src_mape = float(np.mean(np.abs(hold["water_pct_error"].to_numpy(float))))
    sel_row = diag[diag["selected"].astype(str).str.lower().eq("true")].iloc[0]
    src_beta = float(json.loads(str(sel_row["coefficients"]))["electricity_mwh_reported"])
    b_mean = pd.read_csv(BASELINES)
    b_mean = b_mean[b_mean["predictor"].eq("training_mean")].iloc[0]

    add(
        "cond_scale_matches_artifact",
        "PASS" if _close(scale, float(wm["scale"])) else "FAIL",
        f"claim={scale} artifact={wm['scale']}",
    )
    add(
        "cond_kind_matches_artifact",
        "PASS" if str(c["cond_water_kind"]) == str(wm["kind"]) else "FAIL",
        f"claim={c['cond_water_kind']} artifact={wm['kind']}",
    )
    add(
        "cond_bic_matches_artifact",
        "PASS" if _close(bic, float(wm["bic"])) else "FAIL",
        f"claim={bic} artifact={wm['bic']}",
    )
    add(
        "cond_holdout_2023_matches_artifact",
        "PASS" if _close(e23, src_e23) else "FAIL",
        f"claim={e23} artifact={src_e23}",
    )
    add(
        "cond_holdout_2024_matches_artifact",
        "PASS" if _close(e24, src_e24) else "FAIL",
        f"claim={e24} artifact={src_e24}",
    )
    add(
        "cond_holdout_mape_matches_artifact",
        "PASS" if _close(mape, src_mape) else "FAIL",
        f"claim={mape} artifact={src_mape}",
    )
    add(
        "selected_candidate_matches_diagnostics",
        "PASS" if sel == str(sel_row["model"]) else "FAIL",
        f"claim={sel} artifact={sel_row['model']}",
    )
    add(
        "selected_beta_matches_diagnostics",
        "PASS" if _close(beta, src_beta) else "FAIL",
        f"claim={beta} artifact={src_beta}",
    )
    add(
        "selected_rolling_mape_matches_diagnostics",
        "PASS" if _close(roll, float(sel_row["rolling_one_step_mape_pct"])) else "FAIL",
        f"claim={roll} artifact={sel_row['rolling_one_step_mape_pct']}",
    )
    add(
        "cond_mape_matches_baseline_table",
        "PASS" if _close(mape, float(c["conditional_baseline_holdout_mape"])) else "FAIL",
        f"cond_holdout_mape={mape} baseline={c['conditional_baseline_holdout_mape']}",
    )
    add(
        "training_mean_holdout_mape_matches_baseline",
        "PASS" if _close(float(c["training_mean_holdout_mape"]), float(b_mean["MAPE_pct"])) else "FAIL",
        f"claim={c['training_mean_holdout_mape']} artifact={b_mean['MAPE_pct']}",
    )
    add(
        "ensemble_mape_matches_baseline_table",
        "PASS" if _close(float(c["energy_null_ensemble_holdout_mape"]), float(c["energy_null_ensemble_holdout_mape_from_baselines"])) else "FAIL",
        f"stoch={c['energy_null_ensemble_holdout_mape']} baseline={c['energy_null_ensemble_holdout_mape_from_baselines']}",
    )

    q = quantities[quantities["quantity_id"].eq("Q_WATER_PROXY")].iloc[0]
    add(
        "quantity_registry_scale",
        "PASS" if scale_str_in(q["fitted_parameters"], scale) else "FAIL",
        str(q["fitted_parameters"])[:240],
    )
    add(
        "quantity_registry_holdout_2023",
        "PASS" if fmt_signed_pct(e23) in str(q["accuracy_diagnostic_available"]) else "FAIL",
        str(q["accuracy_diagnostic_available"]),
    )
    add(
        "quantity_registry_holdout_2024",
        "PASS" if fmt_signed_pct(e24) in str(q["accuracy_diagnostic_available"]) else "FAIL",
        str(q["accuracy_diagnostic_available"]),
    )

    m_scale = models[models["model_id"].eq("M_WATER_SCALE_GLOBAL")].iloc[0]
    add(
        "model_registry_scale",
        "PASS" if scale_str_in(m_scale["parameters_priors"], scale) else "FAIL",
        str(m_scale["parameters_priors"])[:240],
    )
    add(
        "model_registry_bic",
        "PASS" if f"{bic:.2f}" in str(m_scale["selection_rule"]) else "FAIL",
        str(m_scale["selection_rule"]),
    )
    m_null = models[models["model_id"].eq("M_WATER_ENERGY_NULL")].iloc[0]
    add(
        "model_registry_selected_name",
        "PASS" if "selected mechanistic candidate" in str(m_null["model_name"]).lower() else "FAIL",
        str(m_null["model_name"]),
    )
    add(
        "model_registry_selected_beta",
        "PASS" if scale_str_in(m_null["parameters_priors"], beta) else "FAIL",
        str(m_null["parameters_priors"])[:240],
    )
    add(
        "model_registry_selected_rolling",
        "PASS" if fmt_pct(roll, 2) in str(m_null["notes"]) else "FAIL",
        str(m_null["notes"])[:240],
    )
    add(
        "model_registry_selected_holdout",
        "PASS" if fmt_pct(sel_mape) in str(m_null["notes"]) else "FAIL",
        str(m_null["notes"])[:240],
    )

    p_scale = parameters[
        parameters["model_id"].eq("M_WATER_SCALE_GLOBAL") & parameters["parameter"].eq("water_scale")
    ].iloc[0]
    add(
        "parameter_registry_scale",
        "PASS" if _close(float(p_scale["value"]), scale) else "FAIL",
        f"param={p_scale['value']} claim={scale}",
    )
    p_beta = parameters[
        parameters["model_id"].eq("M_WATER_ENERGY_NULL")
        & parameters["parameter"].eq("beta_electricity_m3_per_mwh")
    ].iloc[0]
    add(
        "parameter_registry_beta",
        "PASS" if _close(float(p_beta["value"]), beta) else "FAIL",
        f"param={p_beta['value']} claim={beta}",
    )

    df = pd.DataFrame(rows)
    fails = df[df["status"].eq("FAIL")]
    if len(fails):
        detail = "; ".join(f"{r.check}: {r.detail}" for r in fails.itertuples(index=False))
        raise AssertionError(f"Report consistency audit FAILED ({len(fails)} checks): {detail}")
    return df


def scale_str_in(text: str, number: float) -> bool:
    text = str(text)
    if f"{number:.15g}" in text:
        return True
    if f"{number:.6f}" in text:
        return True
    if f"{number:.4f}" in text:
        return True
    return str(number) in text
