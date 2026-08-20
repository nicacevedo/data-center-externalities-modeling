"""GWIS measurement-semantic QC for a later empirical groundwater-state model.

Does not modify processed observations, interpolate heads, or fit a response model.
Eligibility is from explicit GWIS method/status fields, not numeric magnitude.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LEVELS = ROOT / "data" / "processed" / "groundwater" / "groundwater_level_observations.csv"
INV = ROOT / "data" / "canonical" / "groundwater" / "groundwater_well_inventory.csv"
OUT_DIR = ROOT / "outputs" / "groundwater"
QC_OBS = OUT_DIR / "gwis_measurement_model_qc.csv"
QC_SUMMARY = OUT_DIR / "gwis_measurement_qc_summary.csv"
LARGE_CHANGE = OUT_DIR / "gwis_large_change_audit.csv"
QC_HYDRO = OUT_DIR / "gwis_measurement_qc_hydrograph.png"

# Explicit GWIS method/status values that are not a static groundwater-state target.
EXCLUDE_METHODS = {"NOT MEASURED"}
EXCLUDE_STATUSES = {"PUMPING", "INJECTING", "FLOWING", "DRY"}
UNKNOWN_STATUSES = {"UNKNOWN", ""}
UNKNOWN_METHODS = {"UNKNOWN", ""}
FOCUS_WELLS = ("SRC-GC", "SRC-JA", "SRC-GB", "SRC-GA")
LARGE_CHANGE_FT = 20.0


def classify_eligibility(method: str, status: str, bls) -> tuple[bool, str, str]:
    """Return (eligible_for_state_model, eligibility_class, eligibility_reason).

    eligibility_class is eligible / unknown_ambiguous / excluded.
    Unknown/ambiguous observations are retained (eligible True) but labeled.
    """
    method_u = str(method or "").strip().upper()
    status_u = str(status or "").strip().upper()
    has_bls = pd.notna(bls)

    if method_u in EXCLUDE_METHODS:
        return False, "excluded", "excluded_not_measured"
    if status_u == "PUMPING":
        return False, "excluded", "excluded_pumping_condition"
    if status_u == "INJECTING":
        return False, "excluded", "excluded_injecting_condition"
    if status_u == "FLOWING":
        return False, "excluded", "excluded_flowing_condition"
    if status_u == "DRY":
        return False, "excluded", "excluded_dry_no_water_surface"
    if not has_bls:
        return False, "excluded", "excluded_missing_numeric_bls"

    if status_u in UNKNOWN_STATUSES or method_u in UNKNOWN_METHODS:
        return True, "unknown_ambiguous", "retained_unknown_or_ambiguous_status_or_method"
    if status_u == "STATIC":
        return True, "eligible", "eligible_static_measurement"
    return True, "unknown_ambiguous", "retained_unrecognized_status_labeled_unknown"


def build_observation_qc(levels: pd.DataFrame, inv: pd.DataFrame) -> pd.DataFrame:
    tag = {}
    if "gwis_well_tag" in inv.columns:
        for _, r in inv.iterrows():
            v = r.get("gwis_well_tag")
            if pd.notna(v) and str(v).strip():
                try:
                    tag[str(r.well_node_id)] = str(int(float(v)))
                except (TypeError, ValueError):
                    tag[str(r.well_node_id)] = str(v).strip()

    bls = pd.to_numeric(levels["water_level_below_land_surface"], errors="coerce")
    amsl = pd.to_numeric(levels["water_surface_elevation_or_head"], errors="coerce")
    lsd = pd.to_numeric(levels.get("land_surface_elevation"), errors="coerce")
    rows = []
    for i, r in levels.iterrows():
        eligible, klass, reason = classify_eligibility(
            r.get("measurement_method", ""),
            r.get("measurement_status", ""),
            bls.loc[i],
        )
        node = str(r.get("well_node_id") or "")
        rows.append(
            {
                "observation_key": r.get("observation_key"),
                "well_node_id": node,
                "gwis_site_id": r.get("gwis_site_id"),
                "well_tag": tag.get(node, ""),
                "observation_date": r.get("measurement_date"),
                "observation_datetime": r.get("measurement_datetime"),
                "water_level_bls_ft": bls.loc[i],
                "water_surface_elevation_ft": amsl.loc[i],
                "land_surface_elevation_ft": lsd.loc[i] if lsd is not None else np.nan,
                "vertical_datum": r.get("reference_datum", ""),
                "measurement_method": r.get("measurement_method", ""),
                "measurement_status": r.get("measurement_status", ""),
                "source_agency": r.get("source_agency", ""),
                "quality_flag": r.get("quality_flag", r.get("measurement_status", "")),
                "measurement_source": r.get("source_agency", ""),
                "eligible_for_state_model": eligible,
                "eligibility_class": klass,
                "eligibility_reason": reason,
            }
        )
    qc = pd.DataFrame(rows)

    # Within-well BLS vs AMSL anomaly consistency (paired representations).
    qc["bls_anomaly_ft"] = np.nan
    qc["head_anomaly_ft"] = np.nan
    qc["amsl_anomaly_ft"] = np.nan
    qc["bls_amsl_anomaly_inconsistency_ft"] = np.nan
    for node, g in qc.groupby("well_node_id"):
        idx = g.index
        bls_n = pd.to_numeric(g["water_level_bls_ft"], errors="coerce")
        amsl_n = pd.to_numeric(g["water_surface_elevation_ft"], errors="coerce")
        if bls_n.notna().sum() >= 1:
            bls_anom = bls_n - bls_n.mean()
            qc.loc[idx, "bls_anomaly_ft"] = bls_anom
            qc.loc[idx, "head_anomaly_ft"] = -bls_anom
        if amsl_n.notna().sum() >= 1:
            amsl_anom = amsl_n - amsl_n.mean()
            qc.loc[idx, "amsl_anomaly_ft"] = amsl_anom
        both = bls_n.notna() & amsl_n.notna()
        if int(both.sum()) >= 2:
            bls_p = bls_n[both]
            amsl_p = amsl_n[both]
            qc.loc[bls_p.index, "bls_amsl_anomaly_inconsistency_ft"] = (
                (amsl_p - amsl_p.mean()) + (bls_p - bls_p.mean())
            ).abs()
    return qc


def bls_amsl_consistency_note(qc: pd.DataFrame) -> str:
    inc = pd.to_numeric(qc["bls_amsl_anomaly_inconsistency_ft"], errors="coerce")
    both = qc["water_level_bls_ft"].notna() & qc["water_surface_elevation_ft"].notna()
    if not both.any():
        return "no paired BLS/AMSL observations"
    max_inc = float(inc.max()) if inc.notna().any() else np.nan
    if pd.isna(max_inc) or max_inc < 1e-6:
        return (
            "within each well, AMSL anomaly equals -BLS anomaly to numerical tolerance; "
            "BLS and AMSL are paired representations of the same measurement, not independent observations"
        )
    return f"UNRESOLVED: max |AMSL_anomaly + BLS_anomaly| = {max_inc:.6g} ft"


def large_change_audit(qc: pd.DataFrame) -> pd.DataFrame:
    rows = []
    numeric = qc[qc["water_level_bls_ft"].notna()].copy()
    numeric["dt"] = pd.to_datetime(numeric["observation_datetime"], errors="coerce")
    numeric = numeric[numeric["dt"].notna()].sort_values(["well_node_id", "dt"])
    for node, g in numeric.groupby("well_node_id", sort=False):
        g = g.reset_index(drop=True)
        for i in range(1, len(g)):
            prev, cur = g.iloc[i - 1], g.iloc[i]
            d_bls = float(cur.water_level_bls_ft) - float(prev.water_level_bls_ft)
            method_chg = str(prev.measurement_method) != str(cur.measurement_method)
            status_chg = str(prev.measurement_status) != str(cur.measurement_status)
            involves_excl = (not bool(prev.eligible_for_state_model)) or (
                not bool(cur.eligible_for_state_model)
            )
            if abs(d_bls) < LARGE_CHANGE_FT and not involves_excl:
                continue
            if abs(d_bls) < LARGE_CHANGE_FT and involves_excl and node not in FOCUS_WELLS:
                continue
            gap = (cur["dt"] - prev["dt"]).total_seconds() / 86400.0
            rows.append(
                {
                    "well_node_id": node,
                    "observation_datetime_prev": prev.observation_datetime,
                    "observation_datetime": cur.observation_datetime,
                    "gap_days": gap,
                    "bls_prev_ft": prev.water_level_bls_ft,
                    "bls_ft": cur.water_level_bls_ft,
                    "delta_bls_ft": d_bls,
                    "delta_head_ft": -d_bls,
                    "method_prev": prev.measurement_method,
                    "method": cur.measurement_method,
                    "status_prev": prev.measurement_status,
                    "status": cur.measurement_status,
                    "eligible_prev": bool(prev.eligible_for_state_model),
                    "eligible": bool(cur.eligible_for_state_model),
                    "coincides_with_method_change": method_chg,
                    "coincides_with_status_change": status_chg,
                    "involves_excluded_observation": involves_excl,
                    "abs_delta_bls_ft": abs(d_bls),
                }
            )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["abs_delta_bls_ft", "well_node_id"], ascending=[False, True])


def plot_qc_hydrograph(qc: pd.DataFrame) -> None:
    nodes = [n for n in FOCUS_WELLS if n in set(qc.well_node_id.astype(str))]
    if not nodes:
        return
    fig, axes = plt.subplots(len(nodes), 1, figsize=(11.0, 2.6 * len(nodes)), sharex=False)
    if len(nodes) == 1:
        axes = [axes]
    color = {
        "eligible": "#1d4ed8",
        "unknown_ambiguous": "#6b7280",
        "excluded": "#b91c1c",
    }
    marker = {
        "eligible": "o",
        "unknown_ambiguous": "s",
        "excluded": "x",
    }
    for ax, node in zip(axes, nodes):
        g = qc[qc.well_node_id.astype(str).eq(node)].copy()
        g["dt"] = pd.to_datetime(g["observation_datetime"], errors="coerce")
        g = g[g["water_level_bls_ft"].notna() & g["dt"].notna()].sort_values("dt")
        for klass, sub in g.groupby("eligibility_class"):
            ax.scatter(
                sub["dt"],
                sub["water_level_bls_ft"],
                s=18,
                c=color.get(klass, "#111827"),
                marker=marker.get(klass, "o"),
                label=klass.replace("_", " "),
                zorder=3 if klass == "excluded" else 2,
            )
        ax.invert_yaxis()
        ax.set_ylabel("BLS ft")
        ax.set_title(node, loc="left", fontsize=9)
        ax.grid(True, axis="y", alpha=0.3)
    axes[0].legend(fontsize=7, frameon=False, ncol=3, loc="upper right")
    axes[0].set_title(
        "GWIS BLS by eligibility (larger BLS = lower head; excluded by method/status only)",
        loc="left",
        fontsize=9,
    )
    axes[-1].set_xlabel("Date")
    fig.tight_layout()
    fig.savefig(QC_HYDRO, dpi=160, bbox_inches="tight")
    plt.close(fig)


def _count_row(
    record_type: str,
    key: str,
    n_obs: int,
    n_numeric: int,
    n_elig: int,
    n_excl: int,
    n_unknown: int,
    note: str = "",
) -> dict:
    return {
        "record_type": record_type,
        "key": key,
        "n_observations": n_obs,
        "n_numeric_bls": n_numeric,
        "n_eligible_for_state_model": n_elig,
        "n_excluded": n_excl,
        "n_unknown_ambiguous_retained": n_unknown,
        "note": note,
    }


def summarize(qc: pd.DataFrame, jumps: pd.DataFrame, consistency: str) -> pd.DataFrame:
    n_raw = len(qc)
    n_numeric = int(qc["water_level_bls_ft"].notna().sum())
    n_elig = int(qc["eligible_for_state_model"].sum())
    n_excl = int((~qc["eligible_for_state_model"].astype(bool)).sum())
    n_unknown = int(qc["eligibility_class"].eq("unknown_ambiguous").sum())
    n_clear = int(qc["eligibility_class"].eq("eligible").sum())
    n_amsl = int(qc["water_surface_elevation_ft"].notna().sum())

    heliport = jumps[jumps.well_node_id.eq("SRC-GC")] if not jumps.empty else jumps
    millican = jumps[jumps.well_node_id.eq("SRC-JA")] if not jumps.empty else jumps
    h_flow = (
        (heliport["status"].eq("FLOWING").any() or heliport["status_prev"].eq("FLOWING").any())
        if not heliport.empty
        else False
    )
    m_same = (
        (
            ~millican["coincides_with_method_change"]
            & ~millican["coincides_with_status_change"]
            & millican["abs_delta_bls_ft"].ge(100)
        ).any()
        if not millican.empty
        else False
    )
    excursion_note = (
        "Heliport SRC-GC: the ~121 ft BLS jump on 2024-03-21 is an ETAPE observation with explicit "
        "FLOWING status and reverts within ~6 days; that observation is excluded. Other large Heliport "
        "changes include STATIC/UNKNOWN REPORTED values and are not removed for magnitude. "
        "Millican SRC-JA: two ETAPE PUMPING observations (~494–498 ft BLS) are excluded. Remaining "
        f"{'≥100 ft consecutive BLS changes often occur with unchanged REPORTED/UNKNOWN method and status' if m_same else 'large BLS changes'} "
        "and are retained as unknown/ambiguous rather than deleted. Airport #2 consecutive changes are smaller "
        "(~22 ft) and not method/status exclusions."
    )
    if not h_flow:
        excursion_note = (
            "Large Heliport/Millican consecutive BLS changes were audited against method/status; "
            "see gwis_large_change_audit.csv. Observations are not deleted for magnitude."
        )
    unresolved = (
        "GWIS measurement_status UNKNOWN (and REPORTED method) has no local codebook beyond the "
        "field label; those rows are retained as unknown_ambiguous. Millican bimodal ~370 vs ~500 ft "
        "BLS series is not fully explained by documented method/status except for the two PUMPING rows."
    )
    rows = [
        _count_row(
            "overall",
            "all",
            n_raw,
            n_numeric,
            n_elig,
            n_excl,
            n_unknown,
            (
                f"n_clearly_eligible_static={n_clear}; n_numeric_amsl={n_amsl}; "
                "BLS and AMSL are paired representations of the same measurement, not independent "
                f"observations. {consistency}. "
                "head_anomaly_ft = -(BLS_ft - well_mean_BLS_ft); larger BLS = lower head. "
                "Processed groundwater_level_observations.csv was not modified. No model fitted. "
                f"{excursion_note} UNRESOLVED: {unresolved}"
            ),
        )
    ]
    for node, g in qc.groupby("well_node_id", sort=True):
        rows.append(
            _count_row(
                "well",
                str(node),
                len(g),
                int(g["water_level_bls_ft"].notna().sum()),
                int(g["eligible_for_state_model"].sum()),
                int((~g["eligible_for_state_model"].astype(bool)).sum()),
                int(g["eligibility_class"].eq("unknown_ambiguous").sum()),
            )
        )
    for method, g in qc.groupby(qc["measurement_method"].fillna("(null)"), sort=True):
        rows.append(
            _count_row(
                "measurement_method",
                str(method),
                len(g),
                int(g["water_level_bls_ft"].notna().sum()),
                int(g["eligible_for_state_model"].sum()),
                int((~g["eligible_for_state_model"].astype(bool)).sum()),
                int(g["eligibility_class"].eq("unknown_ambiguous").sum()),
            )
        )
    for status, g in qc.groupby(qc["measurement_status"].fillna("(null)"), sort=True):
        rows.append(
            _count_row(
                "measurement_status",
                str(status),
                len(g),
                int(g["water_level_bls_ft"].notna().sum()),
                int(g["eligible_for_state_model"].sum()),
                int((~g["eligible_for_state_model"].astype(bool)).sum()),
                int(g["eligibility_class"].eq("unknown_ambiguous").sum()),
            )
        )
    for reason, g in qc.groupby("eligibility_reason", sort=True):
        rows.append(
            _count_row(
                "eligibility_reason",
                str(reason),
                len(g),
                int(g["water_level_bls_ft"].notna().sum()),
                int(g["eligible_for_state_model"].sum()),
                int((~g["eligible_for_state_model"].astype(bool)).sum()),
                int(g["eligibility_class"].eq("unknown_ambiguous").sum()),
            )
        )
    return pd.DataFrame(rows)


def main() -> pd.DataFrame:
    levels = pd.read_csv(LEVELS)
    inv = pd.read_csv(INV) if INV.exists() else pd.DataFrame()
    qc = build_observation_qc(levels, inv)
    consistency = bls_amsl_consistency_note(qc)
    jumps = large_change_audit(qc)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    qc.to_csv(QC_OBS, index=False)
    if not jumps.empty:
        jumps.to_csv(LARGE_CHANGE, index=False)
    else:
        pd.DataFrame(
            columns=[
                "well_node_id",
                "delta_bls_ft",
                "delta_head_ft",
                "coincides_with_method_change",
                "coincides_with_status_change",
            ]
        ).to_csv(LARGE_CHANGE, index=False)
    summary = summarize(qc, jumps, consistency)
    summary.to_csv(QC_SUMMARY, index=False)
    plot_qc_hydrograph(qc)
    overall = summary[summary.record_type.eq("overall")].iloc[0]
    print("PASS: GWIS measurement QC (processed observations unchanged).")
    print(f"  qc: {QC_OBS.relative_to(ROOT)}")
    print(
        f"  numeric BLS={int(overall.n_numeric_bls)} eligible={int(overall.n_eligible_for_state_model)} "
        f"excluded={int(overall.n_excluded)} unknown_retained={int(overall.n_unknown_ambiguous_retained)}"
    )
    print(f"  BLS/AMSL: {consistency}")
    return qc


if __name__ == "__main__":
    main()
