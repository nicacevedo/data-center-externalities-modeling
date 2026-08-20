"""Groundwater identifiability audit (no dynamics model).

Uses the measurement-QC eligible GWIS subset and OWRD pumping. Diagnostics are
within-well so mixed NGVD29/NAVD88 datums are never compared as absolute heads.

bls_anomaly_ft = BLS − well-mean BLS (deeper water table is positive).
head_anomaly_ft = −bls_anomaly_ft (higher hydraulic head is positive).
delta_head_ft = −ΔBLS.

Combined Airport pumping is not split. ESTIMATION_CANDIDATE means sufficient
data to attempt a validated empirical response model, not identified dynamics.
Lag 0/1/3/6-month correlations are exploratory diagnostics, not a model spec.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from audit_gwis_measurement_qc import QC_OBS, main as run_measurement_qc

ROOT = Path(__file__).resolve().parents[1]
LEVELS = ROOT / "data" / "processed" / "groundwater" / "groundwater_level_observations.csv"
PUMP = ROOT / "data" / "processed" / "groundwater" / "groundwater_pumping_monthly.csv"
XWALK = ROOT / "data" / "canonical" / "groundwater" / "water_source_groundwater_crosswalk.csv"
INV = ROOT / "data" / "canonical" / "groundwater" / "groundwater_well_inventory.csv"
OUT_DIR = ROOT / "outputs" / "groundwater"
BY_WELL = OUT_DIR / "groundwater_identifiability_by_well.csv"
SUMMARY = OUT_DIR / "groundwater_identifiability_summary.csv"
FEAS = OUT_DIR / "groundwater_model_feasibility.csv"
FIG_OVERLAP = OUT_DIR / "groundwater_pumping_head_overlap.png"
FIG_DIAG = OUT_DIR / "groundwater_head_pumping_diagnostics.png"

LAGS_MONTHS = (0, 1, 3, 6)
UNMAPPED_VITESSE = ("64500", "64845")
COMBINED_AIRPORT = "COMBINED_ACCEPTED:SRC-GA+SRC-GB"
ACCEPTED_ALLOCATION = {
    "one_to_one_accepted_group",
    "one_to_one_report_id",
    "do_not_split_combined_pod",
}
META_BOUNDARY = "meta_campus_withdrawal"

# Explicit coverage criteria. Not optimized against diagnostic correlations.
MIN_EST_NUMERIC_HEADS = 12
MIN_EST_YEARS = 3
MIN_EST_MONTHS = 12
MIN_EST_OVERLAP_MONTHS = 12
MIN_EST_SPAN_MONTHS = 24
MIN_HEAD_STD_FT = 1.0
MIN_PUMP_CV = 0.05
MIN_PUMP_STD_M3 = 100.0
MAX_SINGLE_YEAR_SHARE = 0.70
MAX_SINGLE_MONTH_SHARE = 0.50
MIN_VALIDATION_HEADS = 4


def _month_period(series: pd.Series) -> pd.PeriodIndex:
    return pd.to_datetime(series, errors="coerce").dt.to_period("M")


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    mask = np.isfinite(x) & np.isfinite(y)
    if int(mask.sum()) < 6:
        return np.nan
    if np.nanstd(x[mask]) == 0 or np.nanstd(y[mask]) == 0:
        return np.nan
    return float(np.corrcoef(x[mask], y[mask])[0, 1])


def _longest_gap_days(dates: pd.Series) -> float:
    d = pd.to_datetime(dates, errors="coerce").dropna().sort_values().drop_duplicates()
    if len(d) < 2:
        return np.nan
    return float((d.diff().dt.days.dropna()).max())


def classify_identifiability(row: dict) -> str:
    """Reproduce classification from explicit coverage fields only."""
    mapping_ok = bool(row.get("defensible_pumping_mapping"))
    n_heads = int(row.get("n_numeric_head_observations") or 0)
    n_years = int(row.get("n_years_with_observations") or 0)
    n_months = int(row.get("n_months_with_observations") or 0)
    n_overlap = int(row.get("n_head_months_with_same_month_pumping") or 0)
    span = row.get("observation_span_months")
    span = float(span) if pd.notna(span) and str(span) != "" else 0.0
    head_std = row.get("head_anomaly_std_ft")
    head_std = float(head_std) if pd.notna(head_std) and str(head_std) != "" else 0.0
    pump_cv = row.get("pumping_cv_overlap")
    pump_cv = float(pump_cv) if pd.notna(pump_cv) and str(pump_cv) != "" else 0.0
    pump_std = row.get("pumping_std_m3_overlap")
    pump_std = float(pump_std) if pd.notna(pump_std) and str(pump_std) != "" else 0.0
    year_share = row.get("max_year_observation_share")
    year_share = float(year_share) if pd.notna(year_share) and str(year_share) != "" else 1.0
    month_share = row.get("max_month_of_year_share")
    month_share = float(month_share) if pd.notna(month_share) and str(month_share) != "" else 1.0
    nontrivial_pump = (pump_cv >= MIN_PUMP_CV) or (pump_std >= MIN_PUMP_STD_M3)

    estimation = (
        mapping_ok
        and n_heads >= MIN_EST_NUMERIC_HEADS
        and n_years >= MIN_EST_YEARS
        and n_months >= MIN_EST_MONTHS
        and n_overlap >= MIN_EST_OVERLAP_MONTHS
        and span >= MIN_EST_SPAN_MONTHS
        and head_std >= MIN_HEAD_STD_FT
        and nontrivial_pump
        and year_share <= MAX_SINGLE_YEAR_SHARE
        and month_share <= MAX_SINGLE_MONTH_SHARE
    )
    if estimation:
        return "ESTIMATION_CANDIDATE"
    if n_heads >= MIN_VALIDATION_HEADS:
        return "VALIDATION_ONLY"
    return "INSUFFICIENT"


def _defensible_mapping(xw_row: pd.Series) -> bool:
    status = str(xw_row.get("identity_status") or "")
    alloc = str(xw_row.get("pumping_allocation_rule") or "")
    group = str(xw_row.get("pumping_group_id") or "").strip()
    if status != "confirmed_official_id":
        return False
    if not group:
        return False
    if alloc not in ACCEPTED_ALLOCATION:
        return False
    return True


def _eligible_observation_keys(qc: pd.DataFrame) -> set[str]:
    flag = qc["eligible_for_state_model"]
    if flag.dtype == bool:
        hit = flag
    else:
        hit = flag.astype(str).str.lower().isin(["true", "1"])
    return set(qc.loc[hit, "observation_key"].astype(str))


def _well_audit_rows(
    levels: pd.DataFrame,
    pump: pd.DataFrame,
    xwalk: pd.DataFrame,
    inv: pd.DataFrame,
    qc: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    pump = pump.copy()
    pump = pump[pump.boundary_id.ne(META_BOUNDARY)].copy()
    pump["year_month"] = pd.PeriodIndex(pump["year_month"].astype(str), freq="M")
    pump_by_group = {
        gid: g.sort_values("year_month")
        for gid, g in pump.groupby("node_or_reporting_group_id")
    }

    levels = levels.copy()
    levels["bls"] = pd.to_numeric(levels["water_level_below_land_surface"], errors="coerce")
    numeric_all = levels[levels["bls"].notna()].copy()
    n_bls_by_node = numeric_all.groupby(numeric_all["well_node_id"].astype(str)).size().to_dict()
    qc_by_node = qc.groupby(qc["well_node_id"].astype(str))
    n_excl_by_node = {
        node: int((~g["eligible_for_state_model"].astype(bool)).sum())
        if g["eligible_for_state_model"].dtype == bool
        else int((~g["eligible_for_state_model"].astype(str).str.lower().isin(["true", "1"])).sum())
        for node, g in qc_by_node
    }
    n_unknown_by_node = {
        node: int(g["eligibility_class"].eq("unknown_ambiguous").sum()) for node, g in qc_by_node
    }

    eligible_keys = _eligible_observation_keys(qc)
    numeric = numeric_all[numeric_all["observation_key"].astype(str).isin(eligible_keys)].copy()
    numeric["obs_date"] = pd.to_datetime(numeric["measurement_datetime"], errors="coerce")
    numeric = numeric[numeric["obs_date"].notna()].copy()
    numeric["year_month"] = numeric["obs_date"].dt.to_period("M")

    xw = xwalk.set_index("well_node_id")
    inv_i = inv.set_index("well_node_id")

    nodes = sorted(set(numeric_all["well_node_id"].dropna().astype(str)))
    extra = [f"VITESSE:{rid}" for rid in UNMAPPED_VITESSE if f"VITESSE:{rid}" not in nodes]
    rows = []
    monthly_store = {}

    for node in nodes + extra:
        xrow = xw.loc[node] if node in xw.index else pd.Series(dtype=object)
        irow = inv_i.loc[node] if node in inv_i.index else pd.Series(dtype=object)
        sub = numeric[numeric.well_node_id.astype(str).eq(node)].copy()
        group = str(xrow.get("pumping_group_id") or "").strip()
        mapping_status = str(xrow.get("mapping_status") or "")
        identity = str(xrow.get("identity_status") or irow.get("identity_status") or "")
        alloc = str(xrow.get("pumping_allocation_rule") or "")
        datum = ""
        if not sub.empty:
            datum_vals = sub["reference_datum"].dropna().astype(str).str.strip().unique().tolist()
            datum = ";".join(datum_vals)
        elif str(irow.get("elevation_datum") or "").strip():
            datum = str(irow.get("elevation_datum")).strip()

        n_heads = int(len(sub))
        if n_heads:
            first_head = sub["obs_date"].min().date().isoformat()
            last_head = sub["obs_date"].max().date().isoformat()
            span_months = (
                (sub["obs_date"].max().to_period("M") - sub["obs_date"].min().to_period("M")).n
            )
            intervals = sub["obs_date"].sort_values().diff().dt.days.dropna()
            median_interval = float(intervals.median()) if len(intervals) else np.nan
            n_years = int(sub["obs_date"].dt.year.nunique())
            n_months = int(sub["year_month"].nunique())
            year_share = float(sub["obs_date"].dt.year.value_counts(normalize=True).max())
            month_share = float(sub["obs_date"].dt.month.value_counts(normalize=True).max())
            peak_month = int(sub["obs_date"].dt.month.value_counts().idxmax())
            longest_gap = _longest_gap_days(sub["obs_date"])
            gwis_id = str(sub["gwis_site_id"].dropna().astype(str).iloc[0]) if sub["gwis_site_id"].notna().any() else ""
            gwis_tag = ""
            if "gwis_well_tag" in irow.index and pd.notna(irow.get("gwis_well_tag")):
                gwis_tag = str(int(float(irow.get("gwis_well_tag")))) if str(irow.get("gwis_well_tag")).replace(".", "", 1).isdigit() else str(irow.get("gwis_well_tag"))
            aquifer = str(irow.get("aquifer_geologic_unit") or "")
        else:
            first_head = last_head = gwis_id = gwis_tag = aquifer = ""
            span_months = n_years = n_months = 0
            median_interval = year_share = month_share = longest_gap = np.nan
            peak_month = ""

        monthly = (
            sub.groupby("year_month", as_index=True)["bls"].median().rename("median_bls_ft")
            if n_heads
            else pd.Series(dtype=float)
        )
        if len(monthly):
            bls_anomaly = monthly - float(monthly.mean())
            head_anomaly = -bls_anomaly
            delta_bls = monthly.diff()
            delta_head = -delta_bls
        else:
            bls_anomaly = pd.Series(dtype=float)
            head_anomaly = pd.Series(dtype=float)
            delta_bls = pd.Series(dtype=float)
            delta_head = pd.Series(dtype=float)

        pseries = pump_by_group.get(group, pd.DataFrame(columns=["year_month", "pump_m3"]))
        if node in {"SRC-GA", "SRC-GB"} and group != COMBINED_AIRPORT:
            raise AssertionError(f"{node} must map to {COMBINED_AIRPORT}, got {group}")

        if len(pseries):
            pump_lookup = (
                pseries.dropna(subset=["pump_m3"])
                .drop_duplicates(subset=["year_month"], keep="first")
                .set_index("year_month")["pump_m3"]
            )
        else:
            pump_lookup = pd.Series(dtype=float)
        pump_months = pump_lookup.index
        first_pump = str(pump_months.min()) if len(pump_months) else ""
        last_pump = str(pump_months.max()) if len(pump_months) else ""
        n_pump_months = int(len(pump_lookup))

        head_months = monthly.index
        same_month = head_months.intersection(pump_months) if len(head_months) else pd.PeriodIndex([], freq="M")
        n_overlap_months = int(len(same_month))
        n_obs_same_month = int(sub["year_month"].isin(same_month).sum()) if n_heads else 0

        lag_counts = {}
        lag_corr_anom = {}
        lag_corr_delta = {}
        for lag in LAGS_MONTHS:
            if not len(head_months) or pump_lookup.empty:
                lag_counts[lag] = 0
                lag_corr_anom[lag] = np.nan
                lag_corr_delta[lag] = np.nan
                continue
            shifted = []
            anom_vals = []
            delta_vals = []
            pump_vals = []
            n_obs_lag = 0
            for ym in head_months:
                p_ym = ym - lag
                if p_ym in pump_lookup.index:
                    shifted.append(ym)
                    anom_vals.append(float(head_anomaly.loc[ym]))
                    delta_vals.append(float(delta_head.loc[ym]) if ym in delta_head.index else np.nan)
                    pump_vals.append(float(pump_lookup.loc[p_ym]))
                    n_obs_lag += int((sub["year_month"] == ym).sum())
            lag_counts[lag] = int(n_obs_lag)
            lag_corr_anom[lag] = _pearson(np.asarray(anom_vals, float), np.asarray(pump_vals, float))
            lag_corr_delta[lag] = _pearson(np.asarray(delta_vals, float), np.asarray(pump_vals, float))

        if n_overlap_months:
            ov_pump = np.asarray([float(pump_lookup.loc[ym]) for ym in same_month], float)
            ov_anom = np.asarray([float(head_anomaly.loc[ym]) for ym in same_month], float)
            pump_std = float(np.nanstd(ov_pump, ddof=1)) if len(ov_pump) > 1 else 0.0
            pump_mean = float(np.nanmean(np.abs(ov_pump))) if len(ov_pump) else np.nan
            pump_cv = float(pump_std / pump_mean) if pump_mean and np.isfinite(pump_mean) and pump_mean > 0 else np.nan
            head_std = float(np.nanstd(ov_anom, ddof=1)) if len(ov_anom) > 1 else float(np.nanstd(head_anomaly, ddof=1) if len(head_anomaly) > 1 else 0.0)
            bls_std = float(np.nanstd(np.asarray([float(bls_anomaly.loc[ym]) for ym in same_month], float), ddof=1)) if len(ov_anom) > 1 else float(np.nanstd(bls_anomaly, ddof=1) if len(bls_anomaly) > 1 else 0.0)
        else:
            pump_std = pump_cv = np.nan
            head_std = float(np.nanstd(head_anomaly, ddof=1)) if len(head_anomaly) > 1 else (float(sub["bls"].std()) if n_heads > 1 else np.nan)
            bls_std = float(np.nanstd(bls_anomaly, ddof=1)) if len(bls_anomaly) > 1 else head_std

        mapping_ok = False if node in extra else _defensible_mapping(xrow)
        rec = {
            "well_node_id": node,
            "gwis_site_id": gwis_id or str(irow.get("gwis_site_id") or ""),
            "gwis_well_tag": gwis_tag,
            "matched_pumping_group_id": group,
            "mapping_status": mapping_status,
            "mapping_confidence": xrow.get("mapping_confidence", ""),
            "identity_status": identity,
            "pumping_allocation_rule": alloc,
            "defensible_pumping_mapping": mapping_ok,
            "datum": datum,
            "aquifer_geologic_unit": aquifer if n_heads else str(irow.get("aquifer_geologic_unit") or ""),
            "first_head_observation": first_head,
            "last_head_observation": last_head,
            "n_numeric_bls_observations": int(n_bls_by_node.get(node, 0)),
            "n_excluded_by_measurement_qc": int(n_excl_by_node.get(node, 0)),
            "n_unknown_ambiguous_eligible": int(n_unknown_by_node.get(node, 0)),
            "n_numeric_head_observations": n_heads,
            "median_observation_interval_days": median_interval,
            "n_years_with_observations": n_years,
            "n_months_with_observations": n_months,
            "observation_span_months": span_months,
            "first_pumping_month": first_pump,
            "last_pumping_month": last_pump,
            "n_pumping_months": n_pump_months,
            "n_head_observations_with_same_month_pumping": n_obs_same_month,
            "n_head_months_with_same_month_pumping": n_overlap_months,
            "n_head_observations_with_lag1_pumping": lag_counts[1],
            "n_head_observations_with_lag3_pumping": lag_counts[3],
            "n_head_observations_with_lag6_pumping": lag_counts[6],
            "head_anomaly_std_ft": head_std,
            "bls_anomaly_std_ft": bls_std,
            "pumping_std_m3_overlap": pump_std,
            "pumping_cv_overlap": pump_cv,
            "max_year_observation_share": year_share,
            "max_month_of_year_share": month_share,
            "peak_observation_month": peak_month,
            "longest_data_gap_days": longest_gap,
            "corr_head_anomaly_pump_lag0": lag_corr_anom[0],
            "corr_head_anomaly_pump_lag1": lag_corr_anom[1],
            "corr_head_anomaly_pump_lag3": lag_corr_anom[3],
            "corr_head_anomaly_pump_lag6": lag_corr_anom[6],
            "corr_dhead_pump_lag0": lag_corr_delta[0],
            "corr_dhead_pump_lag1": lag_corr_delta[1],
            "corr_dhead_pump_lag3": lag_corr_delta[3],
            "corr_dhead_pump_lag6": lag_corr_delta[6],
            "lags_months_evaluated": "0,1,3,6",
            "lags_are_exploratory_diagnostics_not_model_specification": True,
            "head_target_definition": "head_anomaly_ft=-(BLS_ft-well_mean_BLS_ft); delta_head_ft=-delta_BLS_ft",
            "head_interpolation": "none",
            "absolute_cross_well_gradient": "not_computed",
            "diagnostics_are_identifiability_only": True,
            "estimation_candidate_means": "sufficient data to attempt a validated empirical response model",
        }
        rec["identifiability_class"] = classify_identifiability(rec)
        rec["classification_reason"] = _class_reason(rec)
        rows.append(rec)
        monthly_store[node] = {
            "monthly": monthly,
            "bls_anomaly": bls_anomaly,
            "head_anomaly": head_anomaly,
            "pump": pump_lookup,
            "group": group,
        }

    by_well = pd.DataFrame(rows).sort_values("well_node_id")
    return by_well, monthly_store


def _class_reason(rec: dict) -> str:
    klass = rec["identifiability_class"]
    if klass == "ESTIMATION_CANDIDATE":
        return (
            "sufficient data to attempt a validated empirical response model: confirmed mapping, "
            "≥12 overlapping months, ≥3 years / ≥12 months of eligible heads, span ≥24 months, "
            "nontrivial head and pumping variation, and observations not concentrated in one campaign. "
            "This is not proof that a response is identified."
        )
    if klass == "VALIDATION_ONLY":
        if not rec["defensible_pumping_mapping"]:
            return "measured heads exist, but pumping identity is missing, candidate, or not 1:1/accepted-group."
        return "measured heads exist, but overlap, variation, or temporal distribution is insufficient for estimation."
    if rec["n_numeric_head_observations"] == 0:
        return "no numeric GWIS heads at this node (pumping-only or unmatched)."
    return "too few numeric heads to support estimation or validation."


def _overall(by_well: pd.DataFrame) -> str:
    classes = set(by_well["identifiability_class"])
    if "ESTIMATION_CANDIDATE" in classes:
        return "A-small-subsystem-possible"
    if "VALIDATION_ONLY" in classes:
        return "B-validation-only"
    return "C-not-identifiable"


def _update_feasibility(by_well: pd.DataFrame, overall: str) -> None:
    if not FEAS.exists():
        return
    feas = pd.read_csv(FEAS)
    n_est = int(by_well.identifiability_class.eq("ESTIMATION_CANDIDATE").sum())
    n_val = int(by_well.identifiability_class.eq("VALIDATION_ONLY").sum())
    n_ins = int(by_well.identifiability_class.eq("INSUFFICIENT").sum())
    est_nodes = ",".join(by_well.loc[by_well.identifiability_class.eq("ESTIMATION_CANDIDATE"), "well_node_id"].astype(str))
    feas["identifiability_conclusion"] = overall
    feas["n_estimation_candidate_wells"] = n_est
    feas["n_validation_only_wells"] = n_val
    feas["n_insufficient_wells"] = n_ins
    feas["estimation_candidate_nodes"] = est_nodes
    extra = (
        f" Empirical reduced-order screen (no model fitted; not identified dynamics): {overall}. "
        f"ESTIMATION_CANDIDATE={n_est} [{est_nodes or 'none'}] means sufficient data to attempt "
        f"a validated empirical response model. "
        f"VALIDATION_ONLY={n_val}; INSUFFICIENT={n_ins}. "
        "Identifiability uses measurement-QC eligible GWIS observations only. "
        "head_anomaly_ft = -(BLS − well-mean BLS); BLS and AMSL are paired, not independent. "
        "Broad Class A/B/C above remains the parameterized-aquifer feasibility, not a competing definition."
    )
    marker = " Empirical reduced-order identifiability"
    base = feas["reason"].astype(str).str.split(marker, n=1, expand=True)[0]
    feas["reason"] = base + extra
    feas.to_csv(FEAS, index=False)


def _plot_overlap(by_well: pd.DataFrame, monthly_store: dict) -> None:
    nodes = [n for n in by_well.well_node_id if n in monthly_store]
    fig, axes = plt.subplots(len(nodes), 1, figsize=(11.2, max(2.2, 1.15 * len(nodes))), sharex=True)
    if len(nodes) == 1:
        axes = [axes]
    for ax, node in zip(axes, nodes):
        rec = by_well[by_well.well_node_id.eq(node)].iloc[0]
        store = monthly_store[node]
        monthly = store["monthly"]
        pump = store["pump"]
        if len(pump):
            ax.vlines(
                [p.to_timestamp() for p in pump.index],
                ymin=0.05,
                ymax=0.45,
                color="#94a3b8",
                lw=1.2,
                label="pumping month" if node == nodes[0] else None,
            )
        if len(monthly):
            ax.plot(
                [p.to_timestamp() for p in monthly.index],
                np.full(len(monthly), 0.75),
                "o",
                color="#1d4ed8",
                ms=3.5,
                label="eligible head month (median BLS)" if node == nodes[0] else None,
            )
        ax.set_ylim(0, 1)
        ax.set_yticks([])
        ax.set_ylabel(node, rotation=0, ha="right", va="center", fontsize=8)
        ax.text(
            1.01,
            0.5,
            rec.identifiability_class,
            transform=ax.transAxes,
            fontsize=7.5,
            va="center",
            color="#111827",
        )
        ax.grid(True, axis="x", alpha=0.25)
    axes[0].set_title("Groundwater pumping vs eligible head-month overlap (no interpolation)", loc="left")
    axes[0].legend(loc="upper left", fontsize=7, frameon=False, ncol=2)
    axes[-1].set_xlabel("Month")
    fig.tight_layout()
    fig.savefig(FIG_OVERLAP, dpi=160, bbox_inches="tight")
    plt.close(fig)


def _plot_diagnostics(by_well: pd.DataFrame, monthly_store: dict) -> None:
    ranked = by_well[by_well.n_head_months_with_same_month_pumping.ge(6)].copy()
    if ranked.empty:
        ranked = by_well[by_well.n_numeric_head_observations.ge(MIN_VALIDATION_HEADS)].copy()
    ranked = ranked.sort_values(
        ["identifiability_class", "n_head_months_with_same_month_pumping"],
        ascending=[True, False],
    )
    nodes = ranked.well_node_id.head(4).tolist()
    if not nodes:
        return
    fig, axes = plt.subplots(len(nodes), 2, figsize=(11.4, 2.4 * len(nodes)))
    if len(nodes) == 1:
        axes = np.array([axes])
    for i, node in enumerate(nodes):
        store = monthly_store[node]
        monthly = store["monthly"]
        head_anomaly = store["head_anomaly"]
        pump = store["pump"]
        ax_t, ax_s = axes[i]
        if len(pump):
            ax_t.bar(
                [p.to_timestamp() for p in pump.index],
                pump.to_numpy(float),
                width=20,
                color="#cbd5e1",
                label="pumping m³",
            )
        ax_t.set_ylabel("pump m³", fontsize=8)
        ax_t2 = ax_t.twinx()
        if len(head_anomaly):
            ax_t2.plot(
                [p.to_timestamp() for p in head_anomaly.index],
                head_anomaly.to_numpy(float),
                "-o",
                color="#1d4ed8",
                ms=3,
                label="head anomaly ft",
            )
        ax_t2.set_ylabel("head anomaly ft", fontsize=8)
        ax_t.set_title(node, loc="left", fontsize=9)
        common = head_anomaly.index.intersection(pump.index) if len(head_anomaly) and len(pump) else pd.PeriodIndex([], freq="M")
        if len(common):
            ax_s.scatter(
                pump.loc[common].to_numpy(float),
                head_anomaly.loc[common].to_numpy(float),
                s=18,
                color="#1d4ed8",
            )
        ax_s.set_xlabel("same-month pumping m³", fontsize=8)
        ax_s.set_ylabel("head anomaly ft (higher = higher water level)", fontsize=8)
        ax_s.grid(True, alpha=0.3)
        ax_t.grid(True, axis="y", alpha=0.3)
    fig.suptitle(
        "Coverage diagnostics only (not causal effects, calibrated coefficients, or identified dynamics). "
        "head_anomaly_ft = -(BLS − well-mean BLS).",
        fontsize=10,
        y=1.01,
    )
    fig.tight_layout()
    fig.savefig(FIG_DIAG, dpi=160, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    qc = run_measurement_qc()
    levels = pd.read_csv(LEVELS)
    pump = pd.read_csv(PUMP)
    xwalk = pd.read_csv(XWALK)
    inv = pd.read_csv(INV)

    if pump["node_or_reporting_group_id"].astype(str).isin(["SRC-GA", "SRC-GB"]).any():
        raise AssertionError("Airport pumping was split; combined group required")
    if not QC_OBS.exists():
        raise FileNotFoundError(QC_OBS)

    by_well, monthly_store = _well_audit_rows(levels, pump, xwalk, inv, qc)
    if any(c.startswith("mixed_datum") or c.endswith("_absolute_gradient_ft") for c in by_well.columns):
        raise AssertionError("absolute cross-well gradients must not be computed")
    if "head_anomaly_std_ft" in by_well.columns and "bls_anomaly_std_ft" in by_well.columns:
        both = by_well[["head_anomaly_std_ft", "bls_anomaly_std_ft"]].dropna()
        if not both.empty and not np.allclose(
            both["head_anomaly_std_ft"].to_numpy(float),
            both["bls_anomaly_std_ft"].to_numpy(float),
            atol=1e-8,
            equal_nan=True,
        ):
            raise AssertionError("head_anomaly_std_ft must equal bls_anomaly_std_ft in magnitude")

    overall = _overall(by_well)
    n_est = int(by_well.identifiability_class.eq("ESTIMATION_CANDIDATE").sum())
    n_val = int(by_well.identifiability_class.eq("VALIDATION_ONLY").sum())
    n_ins = int(by_well.identifiability_class.eq("INSUFFICIENT").sum())
    next_step = (
        "If a first groundwater benchmark is frozen, attempt a small empirical reduced-order "
        "head-response model only on ESTIMATION_CANDIDATE well/pumping groups (sufficient data "
        "to attempt a validated empirical response model, not identified dynamics), keeping "
        "combined Airport pumping unsplit, using within-well head_anomaly_ft = -(BLS − mean BLS) "
        "or Δh (no mixed-datum absolute heads), holding VALIDATION_ONLY wells out of estimation, "
        "and treating 0/1/3/6-month lag correlations as exploratory rather than a model specification."
        if overall == "A-small-subsystem-possible"
        else (
            "Do not attempt reduced-order estimation; retain measured heads as validation-only targets "
            "until pumping identity/overlap improves."
            if overall == "B-validation-only"
            else "Groundwater response is not presently identifiable from the current GWIS+OWRD overlap."
        )
    )
    summary = pd.DataFrame(
        [
            {
                "overall_identifiability_conclusion": overall,
                "n_wells_audited": len(by_well),
                "n_estimation_candidate": n_est,
                "n_validation_only": n_val,
                "n_insufficient": n_ins,
                "estimation_candidate_nodes": ",".join(
                    by_well.loc[by_well.identifiability_class.eq("ESTIMATION_CANDIDATE"), "well_node_id"]
                ),
                "validation_only_nodes": ",".join(
                    by_well.loc[by_well.identifiability_class.eq("VALIDATION_ONLY"), "well_node_id"]
                ),
                "insufficient_nodes": ",".join(
                    by_well.loc[by_well.identifiability_class.eq("INSUFFICIENT"), "well_node_id"]
                ),
                "n_numeric_bls_all": int(pd.to_numeric(levels["water_level_below_land_surface"], errors="coerce").notna().sum()),
                "n_eligible_state_observations": int(by_well["n_numeric_head_observations"].sum()),
                "lags_months_evaluated": "0,1,3,6",
                "lags_are_exploratory_diagnostics_not_model_specification": True,
                "head_target_definition": "head_anomaly_ft=-(BLS_ft-well_mean_BLS_ft); delta_head_ft=-delta_BLS_ft",
                "head_interpolation": "none",
                "airport_pumping": COMBINED_AIRPORT,
                "vitesse_unmapped_reports": ",".join(UNMAPPED_VITESSE),
                "datums_note": "within-well anomaly/Δh only; mixed NGVD1929/NAVD1988 absolute heads are not compared",
                "model_fitted": False,
                "diagnostics_are_identifiability_only": True,
                "estimation_candidate_means": "sufficient data to attempt a validated empirical response model",
                "next_scientific_modeling_step": next_step,
            }
        ]
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    by_well.to_csv(BY_WELL, index=False)
    summary.to_csv(SUMMARY, index=False)
    _update_feasibility(by_well, overall)
    _plot_overlap(by_well, monthly_store)
    _plot_diagnostics(by_well, monthly_store)

    print("PASS: groundwater identifiability audit (no model fitted).")
    print(f"  by-well: {BY_WELL.relative_to(ROOT)}")
    print(f"  summary: {SUMMARY.relative_to(ROOT)}")
    print(f"  overall: {overall}")
    print(by_well[["well_node_id", "matched_pumping_group_id", "identifiability_class", "n_numeric_head_observations", "n_head_months_with_same_month_pumping"]].to_string(index=False))
    print(f"  next: {next_step}")


if __name__ == "__main__":
    main()
