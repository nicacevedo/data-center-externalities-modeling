#!/usr/bin/env python3
"""Endpoint/range/global compatibility, RNG summary, figures, scientific gate.

Does not tune tolerances to force PASS. Does not overwrite V1.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from v2_common import AN, DOCS, LOGS, MAN, PARENT, REPS, RES, V1, WORK_ROOT, atomic_write_json, utcnow  # noqa: E402

ENDPOINTS = ["PUE_lower_5th", "PUE_upper_95th", "WUE_lower_5th", "WUE_upper_95th"]
PUB_KEYS = {
    "PUE_lower_5th": ("PUE", "5th"),
    "PUE_upper_95th": ("PUE", "95th"),
    "WUE_lower_5th": ("WUE", "5th"),
    "WUE_upper_95th": ("WUE", "95th"),
}


def mad(x):
    x = np.asarray(x, dtype=float)
    med = np.median(x)
    return float(np.median(np.abs(x - med)))


def robust_scale(x, how):
    x = np.asarray(x, dtype=float)
    if how == "mad":
        s = 1.4826 * mad(x)
    elif how == "iqr":
        q75, q25 = np.quantile(x, 0.75), np.quantile(x, 0.25)
        s = float((q75 - q25) / 1.349)
    elif how == "sd":
        s = float(np.std(x, ddof=1))
    else:
        raise ValueError(how)
    return max(s, 1e-12)


def interval_overlap(a_lo, a_hi, b_lo, b_hi):
    inter = max(0.0, min(a_hi, b_hi) - max(a_lo, b_lo))
    union = max(a_hi, b_hi) - min(a_lo, b_lo)
    width_a = a_hi - a_lo
    width_b = b_hi - b_lo
    return {
        "intersection_width": inter,
        "union_width": union,
        "jaccard": inter / union if union > 0 else 0.0,
        "overlap_over_published_width": inter / width_a if width_a > 0 else 0.0,
        "overlap_over_replicated_width": inter / width_b if width_b > 0 else 0.0,
        "published_width": width_a,
        "replicated_width": width_b,
        "published_center": 0.5 * (a_lo + a_hi),
        "replicated_center": 0.5 * (b_lo + b_hi),
    }


def published_table():
    df = pd.read_csv(AN / "published_reference_table.csv")
    out = {}
    for _, r in df.iterrows():
        key = (int(r["Case"]), str(r["Climate Zone"]), str(r["Quantile"]))
        out[key] = {"PUE": float(r["PUE"]), "WUE": float(r["WUE"])}
    return out


def load_reps():
    rows = []
    for p in sorted(REPS.glob("rep_*.json")):
        if p.name.endswith(".tmp"):
            continue
        d = json.loads(p.read_text())
        est = d["estimators"]
        rows.append(
            {
                "path": str(p),
                "task_id": d["task_id"],
                "cell": d["cell"],
                "paper_case": d["paper_case"],
                "climate_zone": d["climate_zone"],
                "replication": d["replication"],
                "role": d["role"],
                "lhs_seed": d["lhs_seed"],
                "elapsed_s": d.get("elapsed_s"),
                "finite_all": d.get("finite_all"),
                "n_hours": d.get("n_hours"),
                **{k: est[k] for k in ENDPOINTS},
                "PUE_center": 0.5 * (est["PUE_lower_5th"] + est["PUE_upper_95th"]),
                "PUE_width": est["PUE_upper_95th"] - est["PUE_lower_5th"],
                "WUE_center": 0.5 * (est["WUE_lower_5th"] + est["WUE_upper_95th"]),
                "WUE_width": est["WUE_upper_95th"] - est["WUE_lower_5th"],
            }
        )
    return pd.DataFrame(rows)


def endpoint_rows(df, pub):
    recs = []
    for (cell, case, zone), g in df.groupby(["cell", "paper_case", "climate_zone"], sort=True):
        n = len(g)
        for ep in ENDPOINTS:
            metric, qlab = PUB_KEYS[ep]
            published = pub[(int(case), str(zone), qlab)][metric]
            xs = g[ep].to_numpy(dtype=float)
            xs_sorted = np.sort(xs)
            # rank of published among replicated endpoints: fraction of reps <= published
            rank_le = int((xs <= published).sum())
            pct = (rank_le / n) * 100.0
            med = float(np.median(xs))
            recs.append(
                {
                    "cell": cell,
                    "paper_case": int(case),
                    "climate_zone": zone,
                    "endpoint": ep,
                    "n_replications": n,
                    "published": published,
                    "replicated_mean": float(np.mean(xs)),
                    "replicated_median": med,
                    "q2.5": float(np.quantile(xs, 0.025)),
                    "q5": float(np.quantile(xs, 0.05)),
                    "q25": float(np.quantile(xs, 0.25)),
                    "q75": float(np.quantile(xs, 0.75)),
                    "q95": float(np.quantile(xs, 0.95)),
                    "q97.5": float(np.quantile(xs, 0.975)),
                    "sd": float(np.std(xs, ddof=1)) if n > 1 else 0.0,
                    "iqr": float(np.quantile(xs, 0.75) - np.quantile(xs, 0.25)),
                    "mad": mad(xs),
                    "n_reps_le_published": rank_le,
                    "empirical_percentile_of_published": pct,
                    "abs_discrepancy_median_minus_published": abs(med - published),
                    "rel_discrepancy_median_minus_published": (med - published) / published if published != 0 else math.nan,
                    "signed_median_minus_published": med - published,
                    "published_range_width": abs(
                        pub[(int(case), str(zone), "95th")][metric]
                        - pub[(int(case), str(zone), "5th")][metric]
                    ),
                    "discrepancy_over_published_range_width": (med - published)
                    / abs(
                        pub[(int(case), str(zone), "95th")][metric]
                        - pub[(int(case), str(zone), "5th")][metric]
                    ),
                    "min_rep": float(xs_sorted[0]),
                    "max_rep": float(xs_sorted[-1]),
                }
            )
    return pd.DataFrame(recs)


def range_rows(df, pub):
    recs = []
    for (cell, case, zone), g in df.groupby(["cell", "paper_case", "climate_zone"], sort=True):
        for metric in ("PUE", "WUE"):
            plo = pub[(int(case), str(zone), "5th")][metric]
            phi = pub[(int(case), str(zone), "95th")][metric]
            lo_col = f"{metric}_lower_5th" if metric == "PUE" else "WUE_lower_5th"
            hi_col = f"{metric}_upper_95th" if metric == "PUE" else "WUE_upper_95th"
            # wait WUE columns are WUE_lower_5th already
            lo_col = f"{metric}_lower_5th"
            hi_col = f"{metric}_upper_95th"
            overlaps = []
            for _, r in g.iterrows():
                ov = interval_overlap(plo, phi, float(r[lo_col]), float(r[hi_col]))
                overlaps.append(ov)
            jacs = [o["jaccard"] for o in overlaps]
            recs.append(
                {
                    "cell": cell,
                    "paper_case": int(case),
                    "climate_zone": zone,
                    "metric": metric,
                    "n_replications": len(g),
                    "published_lower": plo,
                    "published_upper": phi,
                    "published_center": 0.5 * (plo + phi),
                    "published_width": phi - plo,
                    "replicated_center_median": float(np.median(g[f"{metric}_center"])),
                    "replicated_width_median": float(np.median(g[f"{metric}_width"])),
                    "replicated_center_mean": float(np.mean(g[f"{metric}_center"])),
                    "replicated_width_mean": float(np.mean(g[f"{metric}_width"])),
                    "replicated_width_sd": float(np.std(g[f"{metric}_width"], ddof=1)) if len(g) > 1 else 0.0,
                    "replicated_width_iqr": float(np.quantile(g[f"{metric}_width"], 0.75) - np.quantile(g[f"{metric}_width"], 0.25)),
                    "median_jaccard": float(np.median(jacs)),
                    "mean_jaccard": float(np.mean(jacs)),
                    "min_jaccard": float(np.min(jacs)),
                    "width_iqr_over_median": (
                        float(np.quantile(g[f"{metric}_width"], 0.75) - np.quantile(g[f"{metric}_width"], 0.25))
                        / float(np.median(g[f"{metric}_width"]))
                        if float(np.median(g[f"{metric}_width"])) > 0
                        else math.nan
                    ),
                }
            )
    return pd.DataFrame(recs)


def cell_global(g, pub, case, zone, how="mad"):
    """LOO max standardized discrepancy for a 4-endpoint vector."""
    X = g[ENDPOINTS].to_numpy(dtype=float)
    n = len(X)
    pub_vec = np.array(
        [
            pub[(int(case), str(zone), PUB_KEYS[ep][1])][PUB_KEYS[ep][0]]
            for ep in ENDPOINTS
        ],
        dtype=float,
    )
    loc = np.array([np.median(X[:, j]) for j in range(4)])
    scale = np.array([robust_scale(X[:, j], how) for j in range(4)])
    z_pub = (pub_vec - loc) / scale
    d_pub = float(np.max(np.abs(z_pub)))
    d_loo = []
    for i in range(n):
        mask = np.ones(n, dtype=bool)
        mask[i] = False
        loc_i = np.array([np.median(X[mask, j]) for j in range(4)])
        scale_i = np.array([robust_scale(X[mask, j], how) for j in range(4)])
        z_i = (X[i] - loc_i) / scale_i
        d_loo.append(float(np.max(np.abs(z_i))))
    d_loo = np.array(d_loo)
    tail = float(np.mean(d_loo >= d_pub))
    ranks = {}
    for j, ep in enumerate(ENDPOINTS):
        ranks[ep] = float((X[:, j] <= pub_vec[j]).mean())
    return {
        "standardization": how,
        "n": n,
        "published_vector": {ep: float(pub_vec[j]) for j, ep in enumerate(ENDPOINTS)},
        "location_median": {ep: float(loc[j]) for j, ep in enumerate(ENDPOINTS)},
        "scale": {ep: float(scale[j]) for j, ep in enumerate(ENDPOINTS)},
        "z_published": {ep: float(z_pub[j]) for j, ep in enumerate(ENDPOINTS)},
        "D_published": d_pub,
        "D_loo_median": float(np.median(d_loo)),
        "D_loo_q95": float(np.quantile(d_loo, 0.95)),
        "empirical_tail_P_Dloo_ge_Dpub": tail,
        "n_loo_ge_Dpub": int((d_loo >= d_pub).sum()),
        "component_empirical_cdf_of_published": ranks,
        "not_an_exact_classical_hypothesis_test": True,
    }


def figures(df, ep, rng_summaries):
    figdir = AN / "figures"
    figdir.mkdir(parents=True, exist_ok=True)
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        return {"status": "SKIP", "reason": str(e)}
    cells = list(df["cell"].unique())
    # endpoints
    ncell = max(1, len(cells))
    fig, axes = plt.subplots(ncell, 4, figsize=(14, 2.6 * ncell), squeeze=False)
    for i, cell in enumerate(sorted(cells)):
        g = df[df["cell"] == cell]
        case, zone = int(g["paper_case"].iloc[0]), str(g["climate_zone"].iloc[0])
        for j, ekey in enumerate(ENDPOINTS):
            ax = axes[i][j]
            xs = g[ekey].to_numpy(dtype=float)
            ax.boxplot(xs, vert=True, widths=0.5)
            sub = ep[(ep["cell"] == cell) & (ep["endpoint"] == ekey)]
            if len(sub):
                ax.axhline(float(sub["published"].iloc[0]), color="crimson", lw=1.2)
            ax.set_title(f"{cell} {ekey}", fontsize=8)
            ax.tick_params(labelsize=7)
    fig.tight_layout()
    fig.savefig(figdir / "published_endpoints_over_replicated.png", dpi=140)
    plt.close(fig)
    # center/width
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for ax, metric in zip(axes, ("PUE", "WUE")):
        for cell in sorted(cells):
            g = df[df["cell"] == cell]
            ax.scatter(g[f"{metric}_center"], g[f"{metric}_width"], s=12, alpha=0.7, label=cell)
        ax.set_xlabel(f"{metric} range center")
        ax.set_ylabel(f"{metric} range width")
        ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(figdir / "range_center_width.png", dpi=140)
    plt.close(fig)
    # RNG
    if rng_summaries:
        fig, ax = plt.subplots(figsize=(6, 4))
        labels, pue_f, wue_f = [], [], []
        for s in rng_summaries:
            labels.append(s["cell"])
            pue_f.append(s.get("PUE", {}).get("f_RNG", 0))
            wue_f.append(s.get("WUE", {}).get("f_RNG", 0))
        x = np.arange(len(labels))
        ax.bar(x - 0.15, pue_f, 0.3, label="PUE")
        ax.bar(x + 0.15, wue_f, 0.3, label="WUE")
        ax.axhline(0.10, ls="--", color="gray", lw=0.8)
        ax.axhline(0.25, ls="--", color="gray", lw=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_ylabel("f_RNG")
        ax.legend()
        fig.tight_layout()
        fig.savefig(figdir / "rng_vs_facility_variance.png", dpi=140)
        plt.close(fig)
    return {"status": "WROTE", "dir": str(figdir)}


def rng_bundle():
    out = {"variance": [], "range_rerun": None}
    for p in sorted((RES / "rng").glob("variance_*.json")):
        out["variance"].append(json.loads(p.read_text()))
    rr = RES / "rng" / "range_rerun_case5_2A.json"
    if rr.exists():
        d = json.loads(rr.read_text())
        ests = [x["estimators"] for x in d["per_internal_seed"]]
        edf = pd.DataFrame(ests)
        out["range_rerun"] = {
            "cell": d["cell"],
            "frozen_lhs_seed": d["frozen_lhs_seed"],
            "n_internal_seeds": len(ests),
            "endpoint_sd_from_internal_rng": {k: float(edf[k].std(ddof=1)) if len(edf) > 1 else 0.0 for k in ENDPOINTS},
            "endpoint_iqr_from_internal_rng": {
                k: float(np.quantile(edf[k], 0.75) - np.quantile(edf[k], 0.25)) for k in ENDPOINTS
            },
            "per_internal_seed": d["per_internal_seed"],
        }
    return out


def slurm_resource_summary(job_ids):
    if not job_ids:
        return {"sacct": None}
    ids = ",".join(str(x) for x in job_ids if x)
    r = subprocess.run(
        ["sacct", "-j", ids, "--parsable2", "--noheader", "-o", "JobID,JobName,Partition,State,ExitCode,Elapsed,MaxRSS,NodeList,AllocCPUS"],
        capture_output=True,
        text=True,
    )
    return {"cmd": "sacct", "stdout": r.stdout, "stderr": r.stderr}


def decide_gate(ep, rg, glob, rng, disp, nb):
    reasons = []
    caveats = []
    failed_cells = disp["full_50_publication_scale_replications_required"]
    per_cell_tails = {c: glob["cells"][c]["mad"]["empirical_tail_P_Dloo_ge_Dpub"] for c in glob["cells"]}
    joint_tail = glob["joint_50rep_cells"]["mad"]["empirical_tail_P_Dk_ge_Dpub"]
    # systematic directional bias on failed cells
    sub = ep[ep["cell"].isin(failed_cells)]
    bias_notes = []
    for ekey in ENDPOINTS:
        s = sub[sub["endpoint"] == ekey]
        signs = np.sign(s["signed_median_minus_published"].to_numpy())
        if len(s) >= 3 and np.all(signs == signs[0]) and abs(float(s["signed_median_minus_published"].median())) > 0:
            zish = s["discrepancy_over_published_range_width"].abs().median()
            bias_notes.append({"endpoint": ekey, "common_sign": float(signs[0]), "median_discrepancy_over_width": float(zish)})
    ordering = glob.get("qualitative_ordering", {})
    rng_fracs = []
    rng_disp = []
    for v in rng.get("variance") or []:
        for metric in ("PUE", "WUE"):
            f = v[metric]["f_RNG"]
            rng_fracs.append(f)
            if f > 0.25:
                rng_disp.append(f"{v['cell']} {metric} f_RNG={f:.3f} > 0.25")
            elif f >= 0.10:
                rng_disp.append(f"{v['cell']} {metric} f_RNG={f:.3f} in 10-25% (project rule)")
    rng_small = all(f < 0.10 for f in rng_fracs) if rng_fracs else False
    rng_material = any(0.10 <= f <= 0.25 for f in rng_fracs)
    rng_large = any(f > 0.25 for f in rng_fracs)
    width_unstable = bool((rg["width_iqr_over_median"] > 0.5).any()) if len(rg) else False
    nb_ok = (nb or {}).get("disposition") in (
        "NON_REPRODUCIBLE_STORED_SNAPSHOT",
        "STORED_MATCHES_CANONICAL",
    )
    no_det_error = True
    if not nb_ok:
        no_det_error = False
        reasons.append("notebook replay disposition unresolved")
    # joint compatibility: published not more extreme than ordinary paired replications
    jointly_ok = joint_tail >= 0.05
    isolated = []
    for c, t in per_cell_tails.items():
        if t < 0.02:
            isolated.append(c)
    ordering_ok = ordering.get("case2_hot_1A_higher_PUE_upper_than_cold_8", True)
    systematic = len(bias_notes) >= 2
    adapter = False
    if (
        no_det_error
        and jointly_ok
        and not systematic
        and ordering_ok
        and rng_small
        and not rng_large
        and not width_unstable
        and not isolated
    ):
        status = "PASS"
        adapter = True
        reasons.append("Published endpoint vector is not more extreme than ordinary 50-LHS realizations; RNG secondary; ordering preserved.")
    elif (not jointly_ok) and systematic and not ordering_ok:
        status = "FAIL"
        reasons.append("Published ranges jointly inconsistent, systematic directional bias, and qualitative ordering failure.")
    elif (not jointly_ok) and systematic:
        status = "FAIL"
        reasons.append("Published range endpoints systematically inconsistent with repeated publication-scale execution of the frozen public implementation.")
    elif rng_large or width_unstable:
        status = "FAIL"
        reasons.append("Hidden RNG dominates or the N=50 range estimator is unstable.")
        if rng_large:
            reasons.extend(rng_disp)
        if width_unstable:
            reasons.append("range width IQR/median > 0.5 on at least one metric/cell")
    elif (not jointly_ok) or isolated or rng_material or systematic:
        status = "PARTIAL"
        reasons.append("Physical/accounting/climate×technology structure remains useful, but quantitative envelopes are only partially compatible.")
        if not jointly_ok:
            reasons.append(f"joint empirical tail {joint_tail:.3f}")
        if isolated:
            reasons.append(f"isolated extreme cells: {isolated}")
        if rng_material:
            reasons.extend(rng_disp)
        if systematic:
            reasons.append(f"same-sign median bias on {bias_notes}")
    else:
        status = "PARTIAL"
        reasons.append("Default PARTIAL: evidence incomplete or mixed.")
    if not rng.get("variance"):
        caveats.append("RNG variance experiment files missing at finalize time.")
        if status == "PASS":
            status = "PARTIAL"
            adapter = False
            reasons.append("PASS blocked because RNG experiment did not complete.")
    expected = 160
    n_have = int(ep["n_replications"].sum() / 4) if len(ep) else 0
    # n_replications is per endpoint row; 4 endpoints
    n_files = int(len(list(REPS.glob("rep_*.json"))))
    if n_files < expected:
        caveats.append(f"Have {n_files}/{expected} replication files.")
        if status == "PASS":
            status = "PARTIAL"
            adapter = False
    return {
        "status": status,
        "proceed_to_adapter": adapter,
        "reasons": reasons,
        "caveats": caveats,
        "per_cell_empirical_tails": per_cell_tails,
        "joint_empirical_tail": joint_tail,
        "systematic_bias_notes": bias_notes,
        "ordering_ok": ordering_ok,
        "rng_small": rng_small,
        "rng_material_secondary": rng_material,
        "rng_large": rng_large,
        "width_unstable": width_unstable,
        "notebook_disposition": (nb or {}).get("disposition"),
        "thresholds_joint_tail_0.05_is_empirical_rank_not_pue_percent_tolerance": True,
        "f_RNG_thresholds_are_project_rules_not_lei_masanet": True,
    }


def write_summary(status, ep, rg, glob, rng, disp, nb, n_files):
    lines = []
    lines.append("# Final Lei–Masanet reproducibility closure (v2)")
    lines.append("")
    lines.append("Evidence-only. V1 artifacts were not overwritten. Meta 2023–2024 water was not read.")
    lines.append("No seed search, range tuning, weather substitution, or upstream-physics edit was used to change the verdict.")
    lines.append("")
    lines.append(f"## Final disposition: **{status['status']}**")
    lines.append("")
    lines.append(f"Adapter promotion: **{'YES' if status['proceed_to_adapter'] else 'NO / blocked'}**")
    lines.append("")
    lines.append("Reasons:")
    for r in status["reasons"]:
        lines.append(f"- {r}")
    lines.append("")
    lines.append("## A. What Lei–Masanet strongly supports")
    lines.append("")
    lines.append("- Ten public cooling archetypes as intensity models (`P_IT = 1` in all `PUE_WUE_*` functions).")
    lines.append("- Climate-hour physics through TMY T/RH/P and economizer/chiller helpers.")
    lines.append("- Onsite conditioning-water *use* components (humidification/adiabatic, CT evaporation, windage, draw-off), not source/groundwater.")
    lines.append("- Qualitative hot-vs-cold / wet-vs-DX structure on the pre-registered cells, if ordering_ok is true.")
    lines.append("")
    lines.append("## B. What is supported only as a planning/intensity approximation")
    lines.append("")
    lines.append("- Finite-N=50 LHS 5th/95th envelopes as *typical* published-range construction under the frozen public code, not as a unique seed-matched table.")
    lines.append("- Homogeneous map `P_fac = P_IT · PUE(w,θ)`, `W_conditioning = P_IT · WUE(w,θ)` if and only if the adapter was promoted.")
    lines.append("")
    lines.append("## C. What remains unsupported")
    lines.append("")
    lines.append("- Exact numerical equality to `UE.xlsx` (original LHS seed/library unavailable).")
    lines.append("- Stored `demo.ipynb` PUE 1.33916 as a reproducible snapshot (see notebook disposition).")
    lines.append("- Nonlinear IT part-load digital twin; liquid-cooled AI archetypes; groundwater pumping; municipal withdrawal/consumption; Meta 2023–2024 site water.")
    lines.append("- Full 10×15 published table (only locked cells were retested).")
    lines.append("")
    lines.append("## Notebook")
    lines.append("")
    lines.append(f"Disposition: `{status.get('notebook_disposition')}`")
    lines.append("This is not by itself a failure of the annual scientific reproduction.")
    lines.append("")
    lines.append("## Joint compatibility")
    lines.append("")
    lines.append(f"Empirical tail P(D_k ≥ D_published) = {status['joint_empirical_tail']}")
    lines.append(f"Per-cell tails: {json.dumps(status['per_cell_empirical_tails'])}")
    lines.append("")
    lines.append("## RNG")
    lines.append("")
    if rng.get("variance"):
        for v in rng["variance"]:
            lines.append(
                f"- {v['cell']}: PUE f_RNG={v['PUE']['f_RNG']:.4f}; WUE f_RNG={v['WUE']['f_RNG']:.4f} "
                "(project rules: <10% secondary; 10–25% material secondary; >25% problematic)."
            )
    else:
        lines.append("- RNG variance files not present.")
    if rng.get("range_rerun"):
        lines.append(f"- Case 5×2A same-LHS internal-RNG endpoint SDs: {rng['range_rerun']['endpoint_sd_from_internal_rng']}")
    lines.append("")
    lines.append("## Replication count")
    lines.append("")
    lines.append(f"Result files: {n_files}. Planned publication-scale tasks: 160 (50+50+50+10).")
    lines.append("")
    lines.append("## Stopping rule")
    lines.append("")
    lines.append("Stop further Lei–Masanet reproducibility work unless genuinely new upstream evidence appears.")
    lines.append("")
    text = "\n".join(lines) + "\n"
    (DOCS / "FINAL_MASANET_SUMMARY.md").write_text(text)
    return str(DOCS / "FINAL_MASANET_SUMMARY.md")


def main():
    pub = published_table()
    df = load_reps()
    if df.empty:
        atomic_write_json(
            RES / "FINAL_MASANET_STATUS.json",
            {"status": "INCOMPLETE", "reason": "no rep_*.json yet", "timestamp_utc": utcnow()},
        )
        print("no reps")
        sys.exit(3)
    # drop accidental smoke n_hours != 8760
    full = df[df["n_hours"].fillna(8760) == 8760].copy()
    ep = endpoint_rows(full, pub)
    rg = range_rows(full, pub)
    ep.to_csv(AN / "endpoint_compatibility.csv", index=False)
    rg.to_csv(AN / "range_compatibility.csv", index=False)
    disp = json.loads((MAN / "CELL_DISPOSITION_BEFORE_V2.json").read_text())
    glob_cells = {}
    for (cell, case, zone), g in full.groupby(["cell", "paper_case", "climate_zone"]):
        glob_cells[cell] = {how: cell_global(g, pub, case, zone, how) for how in ("mad", "iqr", "sd")}
    # paired joint over the three 50-rep cells
    failed = disp["full_50_publication_scale_replications_required"]
    joint = {}
    for how in ("mad", "iqr", "sd"):
        # build 12-vector for each paired replication index 0..49
        mats = []
        pub12 = []
        labels = []
        ok = True
        for cell in failed:
            g = full[full["cell"] == cell].sort_values("replication")
            if len(g) < 50:
                ok = False
                break
            g50 = g.iloc[:50]
            case, zone = int(g50["paper_case"].iloc[0]), str(g50["climate_zone"].iloc[0])
            X = g50[ENDPOINTS].to_numpy(dtype=float)
            loc = np.array([np.median(X[:, j]) for j in range(4)])
            scale = np.array([robust_scale(X[:, j], how) for j in range(4)])
            Z = (X - loc) / scale
            mats.append(Z)
            pv = np.array(
                [pub[(case, zone, PUB_KEYS[e][1])][PUB_KEYS[e][0]] for e in ENDPOINTS],
                dtype=float,
            )
            pub12.append((pv - loc) / scale)
            labels.extend([f"{cell}:{e}" for e in ENDPOINTS])
        if not ok:
            joint[how] = {"status": "INCOMPLETE", "n_failed_cells_with_50": None}
            continue
        Zall = np.concatenate(mats, axis=1)  # 50 x 12
        zpub = np.concatenate(pub12)
        Dpub = float(np.max(np.abs(zpub)))
        Dk = np.max(np.abs(Zall), axis=1)
        joint[how] = {
            "n_paired_replications": 50,
            "n_endpoints": 12,
            "endpoint_labels": labels,
            "D_published": Dpub,
            "D_k_median": float(np.median(Dk)),
            "D_k_q95": float(np.quantile(Dk, 0.95)),
            "empirical_tail_P_Dk_ge_Dpub": float(np.mean(Dk >= Dpub)),
            "n_k_ge_Dpub": int((Dk >= Dpub).sum()),
            "z_published": {lab: float(z) for lab, z in zip(labels, zpub)},
            "not_an_exact_classical_hypothesis_test": True,
            "pairing_note": (
                "Replication index k is paired across independently seeded cells to form a 12-vector. "
                "The paper's original table may have used a shared LHS stream; that sharing is unavailable."
            ),
        }
    # qualitative ordering: case2 1A vs 8. 1A not retested in V2; use V1 reproduced + published.
    v1_cmp = json.loads((V1 / "annual_selected_comparison.json").read_text())
    v1_21a = next(c for c in v1_cmp["cells"] if c["paper_case"] == 2 and c["climate_zone"] == "1A")
    v2_28 = full[full["cell"] == "case2_8"]
    ordering = {}
    if len(v2_28):
        med_pue_hi_8 = float(np.median(v2_28["PUE_upper_95th"]))
        ordering = {
            "case2_hot_1A_published_PUE_95th": v1_21a["published"]["PUE_95th"],
            "case2_hot_1A_v1_reproduced_PUE_95th": v1_21a["reproduced"]["PUE_95th"],
            "case2_cold_8_v2_median_PUE_95th": med_pue_hi_8,
            "case2_hot_1A_higher_PUE_upper_than_cold_8": v1_21a["published"]["PUE_95th"] > med_pue_hi_8,
            "note": "case 2×1A was V1-compatible and not fully retested; comparison uses V1/published 1A vs V2 8.",
        }
    glob = {
        "timestamp_utc": utcnow(),
        "cells": glob_cells,
        "joint_50rep_cells": joint,
        "qualitative_ordering": ordering,
        "sensitivity_standardizations": ["mad", "iqr", "sd"],
    }
    atomic_write_json(AN / "global_compatibility.json", glob)
    rng = rng_bundle()
    if rng.get("range_rerun") and len(v2_28) == 0:
        pass
    # compare RNG endpoint SD to LHS-replication SD for case5
    if rng.get("range_rerun"):
        g5 = full[full["cell"] == "case5_2A"]
        if len(g5):
            lhs_sd = {k: float(g5[k].std(ddof=1)) for k in ENDPOINTS}
            rng["range_rerun"]["endpoint_sd_across_50_LHS_replications"] = lhs_sd
            rng["range_rerun"]["rng_sd_over_lhs_sd"] = {
                k: rng["range_rerun"]["endpoint_sd_from_internal_rng"][k] / lhs_sd[k] if lhs_sd[k] else math.nan
                for k in ENDPOINTS
            }
    atomic_write_json(AN / "rng_variance_components.json", rng)
    rng_var_table = []
    for v in rng.get("variance") or []:
        for metric in ("PUE", "WUE"):
            rng_var_table.append({"cell": v["cell"], "metric": metric, **v[metric], "elapsed_s": v.get("elapsed_s")})
    if rng_var_table:
        pd.DataFrame(rng_var_table).to_csv(AN / "rng_variance_components.csv", index=False)
    fig = figures(full, ep, rng.get("variance") or [])
    nb = None
    nbp = RES / "notebook" / "DEMO_REPLAY.json"
    if nbp.exists():
        nb = json.loads(nbp.read_text())
    slurm_man = MAN / "SLURM_FINAL_REPRO_V2.json"
    job_ids = []
    if slurm_man.exists():
        sm = json.loads(slurm_man.read_text())
        job_ids = list((sm.get("all_job_ids") or sm.get("job_ids") or {}).values()) if isinstance(sm.get("job_ids"), dict) else sm.get("all_job_ids") or []
        if isinstance(job_ids, dict):
            job_ids = list(job_ids.values())
        flat = []
        for x in job_ids:
            if isinstance(x, list):
                flat.extend(x)
            elif isinstance(x, dict):
                flat.extend(x.values())
            else:
                flat.append(x)
        job_ids = [str(x) for x in flat if x]
    resources = slurm_resource_summary(job_ids)
    (AN / "slurm_sacct.txt").write_text(json.dumps(resources, indent=2)[:500000])
    gate = decide_gate(ep, rg, glob, rng, disp, nb)
    n_files = int((full["n_hours"] == 8760).sum()) if "n_hours" in full else len(full)
    n_files = len(full)
    conv_needed = gate["width_unstable"] and gate["status"] in ("PARTIAL", "FAIL")
    if conv_needed:
        atomic_write_json(
            MAN / "CONVERGENCE_REQUESTED.json",
            {
                "timestamp_utc": utcnow(),
                "reason": "N=50 range width IQR/median > 0.5 on at least one retested metric",
                "cells": failed,
                "sample_sizes": [35, 50, 75, 100],
            },
        )
    else:
        if (MAN / "CONVERGENCE_REQUESTED.json").exists():
            pass
    conv = None
    cp = AN / "sample_size_convergence.json"
    if cp.exists():
        conv = json.loads(cp.read_text())
    files_changed = []
    for root in (MAN, RES, LOGS, DOCS, WORK_ROOT / "scripts" / "final_repro_v2", WORK_ROOT / "slurm" / "final_repro_v2"):
        if Path(root).exists():
            for p in Path(root).rglob("*"):
                if p.is_file():
                    files_changed.append(str(p))
    status_obj = {
        "timestamp_utc": utcnow(),
        "status": gate["status"],
        "proceed_to_adapter": gate["proceed_to_adapter"],
        "proceed_to_prineville": False,
        "adapter_ran": False,
        "prineville_ran": False,
        "did_read_meta_2023_2024_water": False,
        "did_not_tune_to_pass": True,
        "did_not_overwrite_v1": True,
        "n_replication_files": n_files,
        "n_scenario_years_evaluated": int(n_files * 50),
        "n_hourly_evals": int(n_files * 50 * 8760),
        "gate": gate,
        "notebook": nb,
        "global_compatibility_path": str(AN / "global_compatibility.json"),
        "endpoint_table": str(AN / "endpoint_compatibility.csv"),
        "range_table": str(AN / "range_compatibility.csv"),
        "rng": rng,
        "figures": fig,
        "convergence_requested": conv_needed,
        "convergence_result": conv,
        "stopping_rule": "No further Lei–Masanet reproducibility work unless new upstream evidence.",
        "known_limitations": [
            "Public implementation is an intensity/archetype model, not a nonlinear IT part-load digital twin.",
            "WUE is modeled onsite conditioning-water use, not withdrawal/consumption/source or groundwater pumping.",
            "Modern liquid-cooled AI systems are outside the main validated archetype family.",
            "Stored notebook PUE may remain a non-reproducible historical snapshot.",
            "dc_externalities conda env cannot load the model; science used masanet_lei + PYTHONNOUSERSITE=1.",
        ],
        "files_under_v2_tree": files_changed,
    }
    if gate["proceed_to_adapter"]:
        r = subprocess.run(
            [
                "/home/nacevedo/.conda/envs/masanet_lei/bin/python",
                "-m",
                "pytest",
                str(WORK_ROOT / "tests" / "test_followup_v1_adapter.py"),
                "-q",
                "--tb=short",
            ],
            cwd=str(WORK_ROOT),
            capture_output=True,
            text=True,
        )
        status_obj["adapter_ran"] = True
        status_obj["adapter_pytest"] = {
            "returncode": r.returncode,
            "stdout": r.stdout[-4000:],
            "stderr": r.stderr[-2000:],
        }
        status_obj["adapter_status"] = "PASS" if r.returncode == 0 else "FAIL"
        if r.returncode == 0:
            status_obj["proceed_to_prineville"] = True
        else:
            status_obj["proceed_to_prineville"] = False
    else:
        status_obj["adapter_status"] = "BLOCKED"
        status_obj["prineville_status"] = "BLOCKED"
    atomic_write_json(RES / "FINAL_MASANET_STATUS.json", status_obj)
    write_summary(gate, ep, rg, glob, rng, disp, nb, n_files)
    print(json.dumps({"status": gate["status"], "n_files": n_files, "adapter": gate["proceed_to_adapter"]}, indent=2))
    if gate["status"] == "INCOMPLETE":
        sys.exit(3)


if __name__ == "__main__":
    main()
