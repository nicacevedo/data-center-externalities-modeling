"""Retrospective chronological models for observed City-metered service water.

Runs only if the observational promotion gate PASSed. Does not overwrite the
frozen annual Meta-withdrawal water-model holdout (2023–2024).

Response: city_metered_water_service_m3
Not: Meta total monthly withdrawal, campus consumptive use, or groundwater.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed" / "city_prineville"
FIG = ROOT / "outputs" / "city_prineville" / "figures"
MODEL_OUT = ROOT / "outputs" / "city_prineville"
FREEZE_DIR = ROOT / "outputs" / "city_prineville" / "frozen_annual_water_validation_v1"
GATE = OUT / "model_promotion_gate.json"
COMPONENTS = OUT / "city_water_components_monthly.csv"
META = ROOT / "data" / "canonical" / "meta_prineville_annual.csv"
HOURLY = ROOT / "outputs" / "hourly_conditional_reconstruction.csv"

EXPERIMENT_LABEL = "retrospective_exploratory_chronological_validation"
RESPONSE = "city_metered_water_service_m3"

SUMMER = {6, 7, 8}

MODEL_PRED_COLS = [
    ("climatology", "pred_climatology_m3"),
    ("seasonal_persistence", "pred_seasonal_persist_m3"),
    ("annual_electricity_scale", "pred_elec_scale_m3"),
    ("graybox_evap_scale", "pred_graybox_scaled_m3"),
    ("scale_plus_evap", "pred_scale_plus_evap_m3"),
]

# Information actually used when predicting a target month. Roles are descriptive;
# the model mathematics are unchanged.
MODEL_INFORMATION_SETS = [
    {
        "model": "climatology",
        "evaluation_role": "prospective_forecastable_baseline",
        "forecastable_ex_ante": True,
        "uses_realized_target_month_weather": False,
        "uses_target_year_annual_electricity": False,
        "uses_target_year_water_information": False,
        "information_set_note": (
            "Month-of-year mean of city_metered_water_service_m3 from earlier complete "
            "years only. No target-month weather and no target-year electricity."
        ),
    },
    {
        "model": "seasonal_persistence",
        "evaluation_role": "prospective_forecastable_baseline",
        "forecastable_ex_ante": True,
        "uses_realized_target_month_weather": False,
        "uses_target_year_annual_electricity": False,
        "uses_target_year_water_information": False,
        "information_set_note": (
            "Same calendar month from the previous complete year (climatology fallback "
            "if that month is missing). No target-month weather and no target-year electricity."
        ),
    },
    {
        "model": "annual_electricity_scale",
        "evaluation_role": "contemporaneous_explanatory",
        "forecastable_ex_ante": False,
        "uses_realized_target_month_weather": False,
        "uses_target_year_annual_electricity": True,
        "uses_target_year_water_information": False,
        "information_set_note": (
            "Train-only β maps prior-year Meta annual facility MWh to City-service annual "
            "totals; target-month allocation uses climatology shares, but the year scale "
            "uses realized target-year annual electricity. Not strictly prospective."
        ),
    },
    {
        "model": "graybox_evap_scale",
        "evaluation_role": "contemporaneous_explanatory",
        "forecastable_ex_ante": False,
        "uses_realized_target_month_weather": True,
        "uses_target_year_annual_electricity": True,
        "uses_target_year_water_information": False,
        "information_set_note": (
            "s fitted on prior years only. Target-month raw evaporation uses realized "
            "target-month weather and the conditional reconstruction IT scale closed to "
            "that year's facility electricity. Contemporaneous / retrospective explanatory, "
            "not an ex-ante forecast."
        ),
    },
    {
        "model": "scale_plus_evap",
        "evaluation_role": "contemporaneous_explanatory",
        "forecastable_ex_ante": False,
        "uses_realized_target_month_weather": True,
        "uses_target_year_annual_electricity": True,
        "uses_target_year_water_information": False,
        "information_set_note": (
            "a×(E_fac,y/12)+b×raw_evap. Uses realized target-year annual electricity and "
            "realized target-month weather (via evaporation). Contemporaneous explanatory, "
            "not an ex-ante forecast."
        ),
    },
]


def _metrics(y, yhat) -> dict:
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    mask = np.isfinite(y) & np.isfinite(yhat)
    y, yhat = y[mask], yhat[mask]
    if len(y) == 0:
        return {
            "n": 0,
            "mae": np.nan,
            "rmse": np.nan,
            "smape": np.nan,
            "median_absolute_error": np.nan,
        }
    err = yhat - y
    abs_err = np.abs(err)
    mae = float(np.mean(abs_err))
    rmse = float(np.sqrt(np.mean(err**2)))
    denom = np.abs(y) + np.abs(yhat)
    smape_mask = denom > 0
    smape = (
        float(np.mean(2.0 * np.abs(err[smape_mask]) / denom[smape_mask]))
        if smape_mask.any()
        else np.nan
    )
    return {
        "n": int(len(y)),
        "mae": mae,
        "rmse": rmse,
        "smape": smape,
        "median_absolute_error": float(np.median(abs_err)),
    }


def freeze_old_annual_holdout() -> list[str]:
    """Copy annual water-holdout artifacts once; never overwrite an existing freeze."""
    FREEZE_DIR.mkdir(parents=True, exist_ok=True)
    copied = []
    candidates = [
        ROOT / "outputs" / "pipeline_report" / "water_holdout_baseline_compare.csv",
        ROOT / "outputs" / "stochastic_proxy_water_model_diagnostics.csv",
        ROOT / "outputs" / "owrd_water_model_validation.csv",
        ROOT / "outputs" / "pipeline_report" / "validation_scorecard.csv",
    ]
    for src in candidates:
        dest = FREEZE_DIR / src.name
        if dest.exists():
            copied.append(str(dest.relative_to(ROOT)))
            continue
        if src.exists():
            shutil.copy2(src, dest)
            copied.append(str(dest.relative_to(ROOT)))
    note = FREEZE_DIR / "README.txt"
    if not note.exists():
        note.write_text(
            "Frozen copies of pre-City-meter annual water-model artifacts.\n"
            "These remain the 2023-2024 chronological validation of models for Meta "
            "annual campus withdrawal. They are not retuned after observing City meters.\n"
        )
    return copied


def monthly_evap(hourly_path: Path) -> pd.DataFrame:
    if not hourly_path.exists():
        return pd.DataFrame(columns=["year", "month", "raw_evap_m3"])
    h = pd.read_csv(hourly_path, usecols=["timestamp_utc", "evap_water_m3_per_h"])
    ts = pd.to_datetime(h["timestamp_utc"], utc=True).dt.tz_convert("America/Los_Angeles")
    h["year"] = ts.dt.year
    h["month"] = ts.dt.month
    g = h.groupby(["year", "month"], as_index=False)["evap_water_m3_per_h"].sum()
    return g.rename(columns={"evap_water_m3_per_h": "raw_evap_m3"})


def complete_years(df: pd.DataFrame) -> list[int]:
    n = df.groupby("year")[RESPONSE].apply(lambda s: int(s.notna().sum()))
    return [int(y) for y, k in n.items() if k == 12]


def climatology(train: pd.DataFrame) -> dict[int, float]:
    return {
        int(m): float(g[RESPONSE].mean())
        for m, g in train.groupby("month")
        if g[RESPONSE].notna().any()
    }


def fit_nnls_scale(x: np.ndarray, y: np.ndarray) -> float:
    """Nonnegative scalar s in y ≈ s x."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    if len(x) == 0 or float(np.dot(x, x)) == 0:
        return 0.0
    s = float(np.dot(x, y) / np.dot(x, x))
    return max(s, 0.0)


def fit_two_nnls(x1, x2, y) -> tuple[float, float]:
    """Nonnegative least squares for y ≈ a x1 + b x2 via simple projected LS."""
    X = np.column_stack([np.asarray(x1, float), np.asarray(x2, float)])
    y = np.asarray(y, float)
    m = np.isfinite(X).all(1) & np.isfinite(y)
    X, y = X[m], y[m]
    if len(y) < 2:
        return 0.0, 0.0
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    a, b = float(max(coef[0], 0.0)), float(max(coef[1], 0.0))
    # one projected-NNLS step: if a sign-constrained already, done; else re-fit on remaining
    if coef[0] < 0 and coef[1] >= 0:
        b = fit_nnls_scale(X[:, 1], y)
        a = 0.0
    elif coef[1] < 0 and coef[0] >= 0:
        a = fit_nnls_scale(X[:, 0], y)
        b = 0.0
    elif coef[0] < 0 and coef[1] < 0:
        a = b = 0.0
    return a, b


def run_models(obs: pd.DataFrame, evap: pd.DataFrame, meta: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = obs.merge(evap, on=["year", "month"], how="left")
    elec = meta.set_index("year")["electricity_mwh_reported"].to_dict()
    df["electricity_mwh_annual"] = df["year"].map(elec)
    years = complete_years(df)
    pred_rows = []
    for test_year in years:
        train_years = [y for y in years if y < test_year]
        if not train_years:
            continue
        train = df[df["year"].isin(train_years) & df[RESPONSE].notna()]
        test = df[df["year"].eq(test_year) & df[RESPONSE].notna()]
        clim = climatology(train)
        persist_map = {
            int(m): float(v)
            for m, v in train.loc[train["year"].eq(max(train_years))]
            .set_index("month")[RESPONSE]
            .items()
        }
        # C: W_annual ≈ β E_annual, then month = clim_share * β E_y
        ann = train.groupby("year").agg(w=(RESPONSE, "sum"), e=("electricity_mwh_annual", "first"))
        beta_e = fit_nnls_scale(ann["e"].to_numpy(), ann["w"].to_numpy())
        clim_total = sum(clim.values()) or 1.0
        shares = {m: clim[m] / clim_total for m in clim}
        # D: monthly scale on evap
        s_evap = fit_nnls_scale(train["raw_evap_m3"].to_numpy(), train[RESPONSE].to_numpy())
        # E: a * (E/12) + b * evap
        a_e, b_v = fit_two_nnls(
            train["electricity_mwh_annual"].to_numpy() / 12.0,
            train["raw_evap_m3"].to_numpy(),
            train[RESPONSE].to_numpy(),
        )
        for r in test.itertuples(index=False):
            m = int(r.month)
            y = int(r.year)
            pred_rows.append(
                {
                    "year": y,
                    "month": m,
                    "observed_m3": float(getattr(r, RESPONSE)),
                    "raw_evap_m3": float(r.raw_evap_m3) if pd.notna(r.raw_evap_m3) else np.nan,
                    "electricity_mwh_annual": float(r.electricity_mwh_annual)
                    if pd.notna(r.electricity_mwh_annual)
                    else np.nan,
                    "pred_climatology_m3": clim.get(m, np.nan),
                    "pred_seasonal_persist_m3": persist_map.get(m, clim.get(m, np.nan)),
                    "pred_elec_scale_m3": shares.get(m, np.nan) * beta_e * float(r.electricity_mwh_annual)
                    if pd.notna(r.electricity_mwh_annual)
                    else np.nan,
                    "pred_graybox_scaled_m3": s_evap * float(r.raw_evap_m3)
                    if pd.notna(r.raw_evap_m3)
                    else np.nan,
                    "pred_scale_plus_evap_m3": (
                        a_e * (float(r.electricity_mwh_annual) / 12.0)
                        + b_v * float(r.raw_evap_m3)
                    )
                    if pd.notna(r.electricity_mwh_annual) and pd.notna(r.raw_evap_m3)
                    else np.nan,
                    "beta_e": beta_e,
                    "s_evap": s_evap,
                    "a_elec_over_12": a_e,
                    "b_evap": b_v,
                    "train_years": ",".join(str(t) for t in train_years),
                    "experiment_label": EXPERIMENT_LABEL,
                }
            )
    preds = pd.DataFrame(pred_rows)
    native_scores = score_predictions(preds, support="native")
    return preds, native_scores


def common_support_mask(preds: pd.DataFrame) -> pd.Series:
    """Months with observed response and a finite prediction from every compared model."""
    mask = preds["observed_m3"].notna()
    for _, col in MODEL_PRED_COLS:
        mask = mask & np.isfinite(preds[col])
    return mask


def score_predictions(preds: pd.DataFrame, support: str) -> pd.DataFrame:
    if preds.empty:
        return pd.DataFrame(
            columns=["support", "scope", "model", "n", "mae", "rmse", "smape", "median_absolute_error"]
        )
    score_rows = []
    for name, col in MODEL_PRED_COLS:
        met = _metrics(preds["observed_m3"], preds[col])
        score_rows.append({"support": support, "scope": "pooled", "model": name, **met})
        for y, g in preds.groupby("year"):
            met_y = _metrics(g["observed_m3"], g[col])
            score_rows.append({"support": support, "scope": f"year_{int(y)}", "model": name, **met_y})
    return pd.DataFrame(score_rows)


def common_support_tables(preds: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Primary ranking tables: identical (year, month) rows for every model."""
    if preds.empty:
        empty = pd.DataFrame()
        return empty, empty, empty, empty, empty
    cs = preds.loc[common_support_mask(preds)].copy()
    pooled_rows = []
    year_rows = []
    if cs.empty:
        empty = pd.DataFrame()
        return empty, empty, empty, empty, cs
    start = cs.sort_values(["year", "month"]).iloc[0]
    end = cs.sort_values(["year", "month"]).iloc[-1]
    for name, col in MODEL_PRED_COLS:
        met = _metrics(cs["observed_m3"], cs[col])
        pooled_rows.append(
            {
                "model": name,
                "n": met["n"],
                "evaluation_start": f"{int(start.year):04d}-{int(start.month):02d}",
                "evaluation_end": f"{int(end.year):04d}-{int(end.month):02d}",
                "mae": met["mae"],
                "rmse": met["rmse"],
                "smape": met["smape"],
                "median_absolute_error": met["median_absolute_error"],
            }
        )
        for y, g in cs.groupby("year"):
            met_y = _metrics(g["observed_m3"], g[col])
            year_rows.append(
                {
                    "year": int(y),
                    "model": name,
                    "n_months": met_y["n"],
                    "mae": met_y["mae"],
                    "rmse": met_y["rmse"],
                }
            )
    pooled = pd.DataFrame(pooled_rows)
    by_year = pd.DataFrame(year_rows)
    persist = by_year[by_year["model"].eq("seasonal_persistence")][["year", "mae"]].rename(
        columns={"mae": "seasonal_persistence_mae"}
    )
    vs = by_year.merge(persist, on="year", how="left")
    vs["beats_seasonal_persistence"] = np.where(
        vs["model"].eq("seasonal_persistence"),
        False,
        vs["mae"] < vs["seasonal_persistence_mae"],
    )
    n_years = int(vs["year"].nunique())
    beat_rows = []
    for name, _col in MODEL_PRED_COLS:
        sub = vs[vs["model"].eq(name)]
        n_beats = (
            np.nan
            if name == "seasonal_persistence"
            else int(sub["beats_seasonal_persistence"].sum())
        )
        beat_rows.append(
            {
                "model": name,
                "n_years_compared": n_years,
                "n_years_beats_seasonal_persistence": n_beats,
            }
        )
    beats_summary = pd.DataFrame(beat_rows)
    return pooled, by_year, vs, beats_summary, cs


def information_set_table() -> pd.DataFrame:
    return pd.DataFrame(MODEL_INFORMATION_SETS)


def graybox_shape(obs: pd.DataFrame, evap: pd.DataFrame) -> pd.DataFrame:
    df = obs.merge(evap, on=["year", "month"], how="left")
    years = complete_years(df)
    rows = []
    pooled_obs = []
    pooled_gray = []
    for y in years:
        g = df[df["year"].eq(y)].sort_values("month")
        w = g[RESPONSE].to_numpy(dtype=float)
        e = g["raw_evap_m3"].to_numpy(dtype=float)
        if not np.isfinite(w).all() or w.sum() <= 0:
            continue
        if not np.isfinite(e).all() or e.sum() <= 0:
            continue
        p_obs = w / w.sum()
        p_gray = e / e.sum()
        pooled_obs.extend(p_obs.tolist())
        pooled_gray.extend(p_gray.tolist())
        mae = float(np.mean(np.abs(p_obs - p_gray)))
        corr = float(np.corrcoef(p_obs, p_gray)[0, 1]) if len(p_obs) > 1 else np.nan
        peak_obs = int(g["month"].iloc[int(np.argmax(p_obs))])
        peak_gray = int(g["month"].iloc[int(np.argmax(p_gray))])
        summer_obs = float(p_obs[[m - 1 for m in sorted(SUMMER)]].sum())
        summer_gray = float(p_gray[[m - 1 for m in sorted(SUMMER)]].sum())
        amp_obs = float((p_obs.max() - p_obs.min()) / (p_obs.mean() if p_obs.mean() else np.nan))
        amp_gray = float((p_gray.max() - p_gray.min()) / (p_gray.mean() if p_gray.mean() else np.nan))
        rows.append(
            {
                "year": int(y),
                "scope": "year",
                "share_mae": mae,
                "share_corr": corr,
                "peak_month_obs": peak_obs,
                "peak_month_gray": peak_gray,
                "peak_month_error": peak_gray - peak_obs,
                "summer_fraction_obs": summer_obs,
                "summer_fraction_gray": summer_gray,
                "amplitude_obs": amp_obs,
                "amplitude_gray": amp_gray,
                "n_months": 12,
            }
        )
        for m, po, pg in zip(g["month"].astype(int), p_obs, p_gray):
            rows.append(
                {
                    "year": int(y),
                    "month": int(m),
                    "scope": "month",
                    "p_obs": float(po),
                    "p_gray": float(pg),
                    "share_abs_error": abs(float(po - pg)),
                }
            )
    if pooled_obs:
        po = np.array(pooled_obs)
        pg = np.array(pooled_gray)
        rows.insert(
            0,
            {
                "year": None,
                "scope": "pooled",
                "share_mae": float(np.mean(np.abs(po - pg))),
                "share_corr": float(np.corrcoef(po, pg)[0, 1]),
                "n_months": int(len(po)),
            },
        )
    return pd.DataFrame(rows)


def plot_shape(obs: pd.DataFrame, evap: pd.DataFrame, shape: pd.DataFrame) -> Path:
    import matplotlib.pyplot as plt

    FIG.mkdir(parents=True, exist_ok=True)
    df = obs.merge(evap, on=["year", "month"], how="left")
    years = [y for y in complete_years(df) if y >= 2016]
    n = min(6, len(years))
    show = years[-n:]
    fig, axes = plt.subplots(2, 3, figsize=(11, 6), sharex=True)
    axes = axes.ravel()
    for ax, y in zip(axes, show):
        g = df[df["year"].eq(y)].sort_values("month")
        w = g[RESPONSE].to_numpy(float)
        e = g["raw_evap_m3"].to_numpy(float)
        if w.sum() <= 0 or not np.isfinite(e).all() or e.sum() <= 0:
            ax.set_title(str(y))
            continue
        ax.plot(g["month"], w / w.sum(), "o-", label="observed City-service share")
        ax.plot(g["month"], e / e.sum(), "s--", label="gray-box raw-evap share")
        ax.set_title(str(int(y)))
        ax.set_xticks(range(1, 13))
    axes[0].legend(fontsize=7, loc="upper left")
    fig.suptitle(
        "Within-year monthly shares: observed City-metered service vs gray-box evaporation\n"
        "(shape only; levels are not forced to match. Retrospective / exploratory.)"
    )
    fig.supxlabel("month")
    fig.supylabel("share of annual total")
    fig.tight_layout()
    p = FIG / "city_service_vs_graybox_shape.png"
    fig.savefig(p, dpi=140)
    plt.close(fig)
    return p


def plot_model_ts(preds: pd.DataFrame) -> Path:
    import matplotlib.pyplot as plt

    FIG.mkdir(parents=True, exist_ok=True)
    t = pd.to_datetime(dict(year=preds.year.astype(int), month=preds.month.astype(int), day=1))
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(t, preds["observed_m3"], "k-", lw=1.8, label="observed City-metered service")
    ax.plot(t, preds["pred_climatology_m3"], label="climatology baseline")
    ax.plot(t, preds["pred_seasonal_persist_m3"], label="seasonal persistence")
    ax.plot(t, preds["pred_graybox_scaled_m3"], label="gray-box evap × train scale")
    ax.plot(t, preds["pred_scale_plus_evap_m3"], label="annual electricity + evap")
    ax.axvline(pd.Timestamp("2023-09-01"), color="#9467bd", ls=":", alpha=0.7)
    ax.axvline(pd.Timestamp("2024-02-01"), color="#8c564b", ls=":", alpha=0.7)
    ax.set_ylabel("m³ / month")
    ax.set_title(
        "City-metered service water: chronological expanding-window predictions\n"
        "(retrospective / exploratory; primary ranking uses common-support months only)"
    )
    ax.legend(fontsize=7)
    fig.tight_layout()
    p = FIG / "city_service_monthly_models.png"
    fig.savefig(p, dpi=140)
    plt.close(fig)
    return p


def best_model(common_pooled: pd.DataFrame) -> dict:
    pooled = common_pooled.copy()
    pooled = pooled.sort_values(["mae", "rmse"])
    winner = pooled.iloc[0]
    clim = pooled[pooled.model.eq("climatology")].iloc[0]
    persist = pooled[pooled.model.eq("seasonal_persistence")].iloc[0]
    gray = pooled[pooled.model.eq("graybox_evap_scale")].iloc[0]
    weather_better = float(gray["mae"]) < min(float(clim["mae"]), float(persist["mae"]))
    return {
        "ranking_support": "common",
        "best_by_mae": winner["model"],
        "best_mae": float(winner["mae"]),
        "best_rmse": float(winner["rmse"]),
        "common_n": int(winner["n"]),
        "climatology_mae": float(clim["mae"]),
        "seasonal_persistence_mae": float(persist["mae"]),
        "graybox_evap_scale_mae": float(gray["mae"]),
        "weather_beats_seasonal_baselines": weather_better,
        "interpretation": (
            "On common support, gray-box/weather monthly levels beat climatology and seasonal persistence."
            if weather_better
            else "On common support, weather/evaporation-scaled models do not beat strong seasonal baselines on MAE."
        ),
    }


def run() -> dict:
    MODEL_OUT.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    copied = freeze_old_annual_holdout()
    if not GATE.exists():
        raise SystemExit("Promotion gate file missing; run prepare_city_prineville_utility.py first.")
    gate = json.loads(GATE.read_text())
    if gate.get("gate") != "PASS":
        skip = {
            "status": "SKIPPED",
            "reason": "observational promotion gate did not PASS",
            "gate": gate,
            "frozen_copies": copied,
        }
        (MODEL_OUT / "city_metered_service_models_skipped.json").write_text(json.dumps(skip, indent=2) + "\n")
        print(json.dumps(skip, indent=2))
        return skip

    obs = pd.read_csv(COMPONENTS)
    meta = pd.read_csv(META)
    evap = monthly_evap(HOURLY)
    preds, native_scores = run_models(obs, evap, meta)
    cs_pooled, cs_year, cs_vs, cs_beats, cs_preds = common_support_tables(preds)
    info = information_set_table()
    shape = graybox_shape(obs, evap)
    figs = []
    if not preds.empty:
        figs.append(str(plot_model_ts(preds).relative_to(ROOT)))
        figs.append(str(plot_shape(obs, evap, shape).relative_to(ROOT)))
    summary = best_model(cs_pooled) if not cs_pooled.empty else {}
    pooled_shape = shape[shape.scope.eq("pooled")]
    year_shape = shape[shape.scope.eq("year")]
    preds.to_csv(MODEL_OUT / "city_metered_service_monthly_predictions.csv", index=False)
    native_scores.to_csv(MODEL_OUT / "city_metered_service_model_scores.csv", index=False)
    if not cs_pooled.empty:
        cs_pooled.to_csv(MODEL_OUT / "city_service_model_metrics_common_support.csv", index=False)
        cs_year.to_csv(MODEL_OUT / "city_service_model_metrics_common_support_by_year.csv", index=False)
        cs_vs.to_csv(MODEL_OUT / "city_service_model_vs_seasonal_persistence_by_year.csv", index=False)
        cs_beats.to_csv(MODEL_OUT / "city_service_model_beats_seasonal_persistence_summary.csv", index=False)
    info.to_csv(MODEL_OUT / "city_service_model_information_sets.csv", index=False)
    shape.to_csv(MODEL_OUT / "city_metered_service_graybox_shape.csv", index=False)
    result = {
        "status": "RAN",
        "experiment_label": EXPERIMENT_LABEL,
        "response": RESPONSE,
        "gate": "PASS",
        "frozen_annual_holdout_copies": copied,
        "n_prediction_months_native": int(len(preds)),
        "n_prediction_months_common_support": int(len(cs_preds)),
        "primary_ranking_support": "common",
        "model_scores_common_support_pooled": cs_pooled.to_dict(orient="records") if not cs_pooled.empty else [],
        "model_scores_native_pooled": native_scores[native_scores.scope.eq("pooled")].to_dict(orient="records")
        if not native_scores.empty
        else [],
        "beats_seasonal_persistence_summary": cs_beats.to_dict(orient="records") if not cs_beats.empty else [],
        "information_sets": info.to_dict(orient="records"),
        "best": summary,
        "graybox_shape_pooled": pooled_shape.to_dict(orient="records"),
        "graybox_shape_years": year_shape.to_dict(orient="records"),
        "figures": figs,
        "notes": [
            "Primary cross-model ranking uses common support (identical year-month rows).",
            "Native-support scores are a secondary completeness diagnostic.",
            "Not untouched holdout, prospective validation, or confirmatory validation.",
            "City data were inspected during development.",
            "Old annual Meta-withdrawal holdout artifacts were copied once, not overwritten.",
            "Electricity/weather models are contemporaneous explanatory, not strictly prospective.",
        ],
    }
    (MODEL_OUT / "city_metered_service_model_summary.json").write_text(
        json.dumps(result, indent=2, default=str) + "\n"
    )
    print(json.dumps({k: result[k] for k in result if k != "graybox_shape_years"}, indent=2, default=str))
    return result


if __name__ == "__main__":
    run()
