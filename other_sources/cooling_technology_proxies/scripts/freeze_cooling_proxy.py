#!/usr/bin/env python3
"""Final correction/freeze builder for the Lei-2025 cooling source-scenario proxy.

Local only. Does not mutate UEs_16cases.csv, masanet/, or Meta 2023-2024 holdout files.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/home/nacevedo/RA/data-center-externalities-modeling/other_sources/cooling_technology_proxies")
UES = ROOT / "sources/lei2025/UEs_16cases.csv"

LIQUID_MAP = {
    "15_1": "REAR_DOOR_HEAT_EXCHANGER",
    "16_1": "REAR_DOOR_HEAT_EXCHANGER",
    "15_2": "DIRECT_TO_CHIP_COLD_PLATE",
    "16_2": "DIRECT_TO_CHIP_COLD_PLATE",
    "15_3": "IMMERSION",
    "16_3": "IMMERSION",
}
LIQUID_RMD_SOURCE = (
    "SI Supporting Code.Rmd UE_LC chunk: "
    "subcase 15_1/16_1 ~ Rear Door Heat Exchanger; "
    "15_2/16_2 ~ Cold Plate; TRUE ~ Immersion (15_3/16_3)."
)

# Paper ten cooling technologies (Lei et al. 2025 eScholarship OA, methods footnote).
PAPER_CORE_LABELS = {
    "Air-cooled chiller",
    "Airside economizer (air-cooled chiller)",
    "Airside economizer (water-cooled chiller)",
    "Airside economizer& adiabatic cooling (air-cooled chiller)",
    "Airside economizer& adiabatic cooling (water-cooled chiller)",
    "Direct expansion system",
    "Water-cooled chiller",
    "Waterside economizer (water-cooled chiller)",
    "IT Liquid cooling: waterside economizer (water-cooled chiller)",
    "IT Liquid cooling: dry cooler with adiabatic assist (air-cooled chiller)",
}
SOURCE_EXTRA_LABELS = {
    "Dry cooler (air-cooled chiller)",
    "Dry cooler with adiabatic assist (air-cooled chiller)",
}

TECH_ID = {
    "Direct expansion system": "DX",
    "Air-cooled chiller": "ACC",
    "Water-cooled chiller": "WCC",
    "Airside economizer (air-cooled chiller)": "AE_ACC",
    "Airside economizer (water-cooled chiller)": "AE_WCC",
    "Airside economizer& adiabatic cooling (air-cooled chiller)": "AE_AD_ACC",
    "Airside economizer& adiabatic cooling (water-cooled chiller)": "AE_AD_WCC",
    "Waterside economizer (water-cooled chiller)": "WE_WCC",
    "Dry cooler (air-cooled chiller)": "DRY_ACC",
    "Dry cooler with adiabatic assist (air-cooled chiller)": "DRY_AD_ACC",
    "IT Liquid cooling: dry cooler with adiabatic assist (air-cooled chiller)": "LIQ_DRY_AD",
    "IT Liquid cooling: waterside economizer (water-cooled chiller)": "LIQ_WE_WCC",
}

HEAT_REJ = {
    "LIQ_DRY_AD": "dry_adiabatic_hybrid",
    "LIQ_WE_WCC": "waterside_economizer_tower",
}


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def qtile(x, q):
    return float(np.quantile(np.asarray(x, dtype=float), q, interpolation="linear"))


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def annotate(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    orig = out["Case (Original)"].astype(str)
    out["liquid_cooling_type"] = orig.map(lambda x: LIQUID_MAP.get(x, "NOT_APPLICABLE"))
    out["tech_id"] = out["Cooling system"].map(TECH_ID)
    out["source_scope_status"] = np.where(
        out["Cooling system"].isin(PAPER_CORE_LABELS),
        "PAPER_CORE",
        np.where(out["Cooling system"].isin(SOURCE_EXTRA_LABELS), "SOURCE_EXTRA_EXTENDED", "UNCLASSIFIED"),
    )
    out["liquid_it"] = out["tech_id"].isin(["LIQ_DRY_AD", "LIQ_WE_WCC"])
    out["heat_rejection_family"] = np.where(
        out["tech_id"] == "LIQ_DRY_AD",
        "dry_adiabatic_hybrid",
        np.where(out["tech_id"] == "LIQ_WE_WCC", "waterside_economizer_tower", "see_taxonomy"),
    )
    out["WUE_site_model"] = out["WUE"].astype(float)
    out["W_conditioning_intensity_model"] = out["WUE"].astype(float)
    out["scenario_semantics"] = "SOURCE_MODEL_SCENARIO"
    out["quantile_semantics"] = "SOURCE_SCENARIO_QUANTILE"
    out["weighting_default"] = "UNWEIGHTED_ENSEMBLE"
    out["paired"] = True
    out["PUE_boundary"] = "facility_electricity_over_IT_electricity"
    out["WUE_boundary"] = (
        "WUE_site_model = onsite conditioning-water use intensity (L/kWh_IT); "
        "includes humidification and/or adiabatic water; tower cases also include "
        "evaporation + windage/drift + draw-off/blowdown. Not groundwater."
    )
    out["source_id"] = "LEI2025_UES16"
    out["scenario_id"] = np.arange(len(out), dtype=int)
    out["lineage"] = "SAME_LEI_MASANET_LINEAGE"
    return out


def summary_table(df):
    keys = [
        "tech_id",
        "Cooling system",
        "Climate Zone",
        "Data center size",
        "type",
        "Case",
        "Case (Original)",
        "liquid_cooling_type",
        "source_scope_status",
        "liquid_it",
    ]
    rows = []
    for k, g in df.groupby(keys, dropna=False):
        rec = dict(zip(keys, k))
        pue = g["PUE"].to_numpy(float)
        wue = g["WUE_site_model"].to_numpy(float)
        rec.update(
            {
                "n": int(len(g)),
                "PUE_mean": float(pue.mean()),
                "PUE_sd": float(pue.std(ddof=1)) if len(pue) > 1 else 0.0,
                "PUE_p05": qtile(pue, 0.05),
                "PUE_p25": qtile(pue, 0.25),
                "PUE_p50": float(np.median(pue)),
                "PUE_p75": qtile(pue, 0.75),
                "PUE_p95": qtile(pue, 0.95),
                "WUE_site_model_mean": float(wue.mean()),
                "WUE_site_model_sd": float(wue.std(ddof=1)) if len(wue) > 1 else 0.0,
                "WUE_site_model_p05": qtile(wue, 0.05),
                "WUE_site_model_p25": qtile(wue, 0.25),
                "WUE_site_model_p50": float(np.median(wue)),
                "WUE_site_model_p75": qtile(wue, 0.75),
                "WUE_site_model_p95": qtile(wue, 0.95),
                "cov_PUE_WUE_site_model": float(np.cov(pue, wue, ddof=1)[0, 1]) if len(pue) > 1 else 0.0,
                "pearson": float(np.corrcoef(pue, wue)[0, 1]) if pue.std() > 0 and wue.std() > 0 else math.nan,
                "paired": True,
                "quantile_semantics": "SOURCE_SCENARIO_QUANTILE",
                "scenario_semantics": "SOURCE_MODEL_SCENARIO",
                "source_id": "LEI2025_UES16",
            }
        )
        rows.append(rec)
    return pd.DataFrame(rows)


def domain_matrix(df, summary):
    rows = []
    keys = ["tech_id", "Cooling system", "Climate Zone", "Data center size", "liquid_cooling_type", "source_scope_status", "Case (Original)"]
    for k, g in df.groupby(keys, dropna=False):
        rec = dict(zip(keys, k))
        rec["n"] = int(len(g))
        rec["source"] = "LEI2025_UES16"
        rec["scenario_id_min"] = int(g["scenario_id"].min())
        rec["scenario_id_max"] = int(g["scenario_id"].max())
        rec["PUE_min"] = float(g["PUE"].min())
        rec["PUE_max"] = float(g["PUE"].max())
        rec["PUE_p05"] = qtile(g["PUE"], 0.05)
        rec["PUE_p95"] = qtile(g["PUE"], 0.95)
        rec["WUE_site_model_min"] = float(g["WUE_site_model"].min())
        rec["WUE_site_model_max"] = float(g["WUE_site_model"].max())
        rec["WUE_site_model_p05"] = qtile(g["WUE_site_model"], 0.05)
        rec["WUE_site_model_p95"] = qtile(g["WUE_site_model"], 0.95)
        rec["evidence_status"] = "SOURCE_MODEL_SCENARIO_SAME_LINEAGE"
        rec["supported"] = True
        rows.append(rec)
    return pd.DataFrame(rows)


def overlap(a0, a1, b0, b1):
    lo, hi = max(a0, b0), min(a1, b1)
    return max(0.0, hi - lo)


def matched_comparisons(df):
    """Distributional comparisons within climate × facility class. Not row-paired LHS."""
    recs = []
    large = df[df["Data center size"] == "Large-scale"]
    techs = ["AE_AD_ACC", "AE_AD_WCC", "WE_WCC", "DRY_AD_ACC", "LIQ_DRY_AD", "LIQ_WE_WCC"]
    # For liquid, compare pooled-within-tech only when subtype held fixed — so compare at subtype grain for liquid.
    for climate, gclim in large.groupby("Climate Zone"):
        cells = []
        for tid in techs:
            sub = gclim[gclim["tech_id"] == tid]
            if sub.empty:
                continue
            if tid in ("LIQ_DRY_AD", "LIQ_WE_WCC"):
                for lt, gs in sub.groupby("liquid_cooling_type"):
                    cells.append((tid, lt, gs))
            else:
                cells.append((tid, "NOT_APPLICABLE", sub))
        for i in range(len(cells)):
            for j in range(i + 1, len(cells)):
                ta, la, ga = cells[i]
                tb, lb, gb = cells[j]
                pa, pb = ga["PUE"].to_numpy(float), gb["PUE"].to_numpy(float)
                wa, wb = ga["WUE_site_model"].to_numpy(float), gb["WUE_site_model"].to_numpy(float)
                recs.append(
                    {
                        "climate": climate,
                        "facility_class": "Large-scale",
                        "tech_a": ta,
                        "liquid_a": la,
                        "tech_b": tb,
                        "liquid_b": lb,
                        "n_a": int(len(ga)),
                        "n_b": int(len(gb)),
                        "pairing": "DISTRIBUTION_CELL_NOT_ROW_LHS",
                        "PUE_p50_a": float(np.median(pa)),
                        "PUE_p50_b": float(np.median(pb)),
                        "dPUE_p50_b_minus_a": float(np.median(pb) - np.median(pa)),
                        "PUE_p05_a": qtile(pa, 0.05),
                        "PUE_p95_a": qtile(pa, 0.95),
                        "PUE_p05_b": qtile(pb, 0.05),
                        "PUE_p95_b": qtile(pb, 0.95),
                        "PUE_5_95_overlap": overlap(qtile(pa, 0.05), qtile(pa, 0.95), qtile(pb, 0.05), qtile(pb, 0.95)),
                        "WUE_p50_a": float(np.median(wa)),
                        "WUE_p50_b": float(np.median(wb)),
                        "dWUE_p50_b_minus_a": float(np.median(wb) - np.median(wa)),
                        "WUE_p05_a": qtile(wa, 0.05),
                        "WUE_p95_a": qtile(wa, 0.95),
                        "WUE_p05_b": qtile(wb, 0.05),
                        "WUE_p95_b": qtile(wb, 0.95),
                        "WUE_5_95_overlap": overlap(qtile(wa, 0.05), qtile(wa, 0.95), qtile(wb, 0.05), qtile(wb, 0.95)),
                        "interpretation": "source-model envelope difference under matched climate and Large-scale class; not a causal treatment effect",
                    }
                )
    return pd.DataFrame(recs)


def liquid_decomposition(df):
    liq = df[df["liquid_it"]].copy()
    recs = []
    subtypes = ["REAR_DOOR_HEAT_EXCHANGER", "DIRECT_TO_CHIP_COLD_PLATE", "IMMERSION"]
    for climate, gc in liq.groupby("Climate Zone"):
        # within heat rejection, subtype diffs
        for rej, gr in gc.groupby("tech_id"):
            med = {lt: gr[gr["liquid_cooling_type"] == lt] for lt in subtypes}
            if any(v.empty for v in med.values()):
                continue
            p = {lt: float(np.median(v["PUE"])) for lt, v in med.items()}
            w = {lt: float(np.median(v["WUE_site_model"])) for lt, v in med.items()}
            recs.append(
                {
                    "climate": climate,
                    "contrast": "subtype_within_heat_rejection",
                    "heat_rejection": HEAT_REJ[rej],
                    "tech_id": rej,
                    "PUE_rdhx": p["REAR_DOOR_HEAT_EXCHANGER"],
                    "PUE_coldplate": p["DIRECT_TO_CHIP_COLD_PLATE"],
                    "PUE_immersion": p["IMMERSION"],
                    "PUE_subtype_range": max(p.values()) - min(p.values()),
                    "WUE_rdhx": w["REAR_DOOR_HEAT_EXCHANGER"],
                    "WUE_coldplate": w["DIRECT_TO_CHIP_COLD_PLATE"],
                    "WUE_immersion": w["IMMERSION"],
                    "WUE_subtype_range": max(w.values()) - min(w.values()),
                    "semantics": "SOURCE_MODEL_SCENARIO",
                }
            )
        # within subtype, heat-rejection diffs
        for lt in subtypes:
            dry = gc[(gc["tech_id"] == "LIQ_DRY_AD") & (gc["liquid_cooling_type"] == lt)]
            we = gc[(gc["tech_id"] == "LIQ_WE_WCC") & (gc["liquid_cooling_type"] == lt)]
            if dry.empty or we.empty:
                continue
            pdry, pwe = float(np.median(dry["PUE"])), float(np.median(we["PUE"]))
            wdry, wwe = float(np.median(dry["WUE_site_model"])), float(np.median(we["WUE_site_model"]))
            recs.append(
                {
                    "climate": climate,
                    "contrast": "heat_rejection_within_subtype",
                    "liquid_cooling_type": lt,
                    "PUE_dry_adiabatic": pdry,
                    "PUE_we_tower": pwe,
                    "dPUE_we_minus_dry": pwe - pdry,
                    "rel_dPUE_we_minus_dry": (pwe - pdry) / pdry if pdry else math.nan,
                    "WUE_dry_adiabatic": wdry,
                    "WUE_we_tower": wwe,
                    "dWUE_we_minus_dry": wwe - wdry,
                    "rel_dWUE_we_minus_dry": (wwe - wdry) / wdry if wdry else math.nan,
                    "semantics": "SOURCE_MODEL_SCENARIO",
                }
            )
    return pd.DataFrame(recs)


def figures(df, decomp):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figdir = ROOT / "figures"
    figdir.mkdir(exist_ok=True)
    note = "MODELED SOURCE ENSEMBLE — LEI/MASANET/LBNL LINEAGE"
    liq = df[df["liquid_it"]]
    order = ["REAR_DOOR_HEAT_EXCHANGER", "DIRECT_TO_CHIP_COLD_PLATE", "IMMERSION"]
    short = {"REAR_DOOR_HEAT_EXCHANGER": "RDHX", "DIRECT_TO_CHIP_COLD_PLATE": "Cold plate", "IMMERSION": "Immersion"}
    fig, axes = plt.subplots(2, 2, figsize=(10, 8))
    panels = [
        ("LIQ_DRY_AD", "PUE", 0, 0, "Liquid + dry/adiabatic — PUE"),
        ("LIQ_DRY_AD", "WUE_site_model", 0, 1, "Liquid + dry/adiabatic — WUE_site_model"),
        ("LIQ_WE_WCC", "PUE", 1, 0, "Liquid + WE/tower — PUE"),
        ("LIQ_WE_WCC", "WUE_site_model", 1, 1, "Liquid + WE/tower — WUE_site_model"),
    ]
    for tid, col, r, c, title in panels:
        ax = axes[r, c]
        data = [liq[(liq.tech_id == tid) & (liq.liquid_cooling_type == lt)][col].to_numpy(float) for lt in order]
        ax.boxplot(data, labels=[short[lt] for lt in order], showfliers=False)
        ax.set_title(title, fontsize=9)
        ax.set_ylabel("PUE" if col == "PUE" else "WUE_site_model (L/kWh)")
    fig.suptitle("Liquid subtype source-scenario envelopes by heat rejection\n" + note, fontsize=11)
    fig.tight_layout()
    fig.savefig(figdir / "liquid_subtype_by_heat_rejection.png", dpi=140)
    plt.close(fig)

    # climate: facet by subtype for liquid dry
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    sub = liq[liq.tech_id == "LIQ_DRY_AD"]
    zones = sorted(sub["Climate Zone"].unique())
    for ax, lt in zip(axes, order):
        med, lo, hi = [], [], []
        for z in zones:
            v = sub[(sub.liquid_cooling_type == lt) & (sub["Climate Zone"] == z)]["WUE_site_model"]
            med.append(float(np.median(v)))
            lo.append(qtile(v, 0.05))
            hi.append(qtile(v, 0.95))
        x = np.arange(len(zones))
        ax.errorbar(x, med, yerr=[np.array(med) - np.array(lo), np.array(hi) - np.array(med)], fmt="o", ms=3)
        ax.set_ylabel("WUE_site_model")
        ax.set_title(short[lt] + " — LIQ_DRY_AD (faceted; not pooled)", fontsize=9)
    axes[-1].set_xticks(np.arange(len(zones)))
    axes[-1].set_xticklabels(zones, rotation=90, fontsize=7)
    fig.suptitle("Climate WUE_site_model source-scenario 5/50/95 by liquid subtype\n" + note, fontsize=11)
    fig.tight_layout()
    fig.savefig(figdir / "wue_climate_liquid_faceted_subtype.png", dpi=140)
    plt.close(fig)

    # technology map using Large-scale PAPER_CORE only (matched class)
    large = df[(df["Data center size"] == "Large-scale") & (df["source_scope_status"] == "PAPER_CORE")]
    med = large.groupby("tech_id")[["PUE", "WUE_site_model"]].median().reset_index()
    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.scatter(med["WUE_site_model"], med["PUE"], s=40)
    for _, r in med.iterrows():
        ax.annotate(r["tech_id"], (r["WUE_site_model"], r["PUE"]), fontsize=8)
    ax.set_xlabel("Source-scenario median WUE_site_model (L/kWh)")
    ax.set_ylabel("Source-scenario median PUE")
    ax.set_title("Source-model PUE–WUE technology map\nLarge-scale PAPER_CORE only — not a causal frontier\n" + note)
    fig.tight_layout()
    fig.savefig(figdir / "source_model_pue_wue_technology_map.png", dpi=140)
    plt.close(fig)

    # liquid effect: median |dWUE| heat rejection vs subtype range
    hr = decomp[decomp.contrast == "heat_rejection_within_subtype"]
    st = decomp[decomp.contrast == "subtype_within_heat_rejection"]
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    ax.bar(
        [0, 1],
        [float(hr["dWUE_we_minus_dry"].abs().median()), float(st["WUE_subtype_range"].median())],
        tick_label=["Heat rejection\n(WE/tower − dry) |ΔWUE|", "Liquid subtype\nrange within rejection"],
    )
    ax.set_ylabel("Median across climates of |Δ WUE_site_model| (L/kWh)")
    ax.set_title("Source-model: heat rejection vs liquid subtype (WUE)\n" + note)
    fig.tight_layout()
    fig.savefig(figdir / "liquid_heat_rejection_vs_subtype.png", dpi=140)
    plt.close(fig)

    # validation coverage simple table figure created separately if matrix exists
    return [
        "liquid_subtype_by_heat_rejection.png",
        "wue_climate_liquid_faceted_subtype.png",
        "source_model_pue_wue_technology_map.png",
        "liquid_heat_rejection_vs_subtype.png",
    ]


def prineville_validation(df):
    """Compare predeclared early-Prineville operator evidence to AE_AD_ACC × 5B × Large-scale."""
    cell = df[
        (df["tech_id"] == "AE_AD_ACC")
        & (df["Climate Zone"] == "5B")
        & (df["Data center size"] == "Large-scale")
        & (df["liquid_cooling_type"] == "NOT_APPLICABLE")
    ]
    pue = cell["PUE"].to_numpy(float)
    wue = cell["WUE_site_model"].to_numpy(float)

    def loc(val, arr):
        p05, p95 = qtile(arr, 0.05), qtile(arr, 0.95)
        if p05 <= val <= p95:
            return "inside_source_scenario_5_95"
        if val < p05:
            return "below_source_scenario_p05"
        return "above_source_scenario_p95"

    rows = []
    obs = [
        ("PUE_commissioning_full_load", 1.07, "PUE", "OCP/Meta 2011 commissioning; OPERATOR_REPORTED_MEASURED"),
        ("PUE_operating_range_low", 1.06, "PUE", "OCP Learning Lessons Apr–Sep 2011 histogram; OPERATOR_REPORTED_MEASURED"),
        ("PUE_operating_range_high", 1.10, "PUE", "same; 1.06–1.1"),
        ("WUE_PRN1_Q2_2012", 0.22, "WUE", "OCP Water Efficiency blog; cooling-only quarterly; OPERATOR_REPORTED_MEASURED"),
        ("WUE_design_2011", 0.31, "WUE", "Meta engineering 2011 DESIGN point, not a meter"),
        ("PUE_TTM_Mar2013_dashboard", 1.09, "PUE", "Wayback fbpuewue.com/prineville TTM as of end Mar 2013; OPERATOR_REPORTED_MEASURED; campus period may exceed PRN1-only"),
        ("WUE_TTM_Mar2013_dashboard", 0.52, "WUE", "same capture; not used to choose k"),
    ]
    for name, val, kind, note in obs:
        arr = pue if kind == "PUE" else wue
        p50 = float(np.median(arr))
        rows.append(
            {
                "observed_id": name,
                "observed_value": val,
                "kind": kind,
                "source_cell": "AE_AD_ACC|5B|Large-scale|NOT_APPLICABLE",
                "n_source": int(len(cell)),
                "source_p05": qtile(arr, 0.05),
                "source_p50": p50,
                "source_p95": qtile(arr, 0.95),
                "discrepancy_obs_minus_source_p50": val - p50,
                "location_vs_source_5_95": loc(val, arr),
                "notes": note,
            }
        )
    # overall classification
    wue_q2 = loc(0.22, wue)
    pue_comm = loc(1.07, pue)
    if wue_q2 != "inside_source_scenario_5_95" and pue_comm != "inside_source_scenario_5_95":
        overall = "materially_discrepant"
    elif wue_q2 != "inside_source_scenario_5_95":
        overall = "partially_compatible"
    else:
        overall = "compatible"
    meta = {
        "overall_classification": overall,
        "rule": "PUE commissioning and PRN1 Q2 2012 WUE vs predeclared AE_AD_ACC 5B Large-scale cell; no k retuning",
        "architecture_mismatch": "Lei AE_AD_ACC retains supplemental air-cooled chiller; Prineville 2011/2012 PRN1 has no chiller/tower",
        "water_boundary_mismatch": "Facebook WUE is cooling-water (may include RO reject 25%); Lei air-adiabatic WUE is humidification/adiabatic intensity without RO pretreatment reject",
        "did_not_choose_k_from_residual": True,
    }
    return pd.DataFrame(rows), meta


def write_static_tables():
    tax_fields = [
        "tech_id", "source_label", "source_scope_status", "paper_core_index",
        "IT_HEAT_CAPTURE", "HEAT_TRANSPORT", "HEAT_REJECTION", "ECONOMIZER",
        "MECHANICAL_COOLING", "DIRECT_WATER_MECHANISM", "liquid_it",
        "lei2025_cases", "liquid_cooling_type", "confidence", "notes",
    ]
    tax = [
        {"tech_id": "ACC", "source_label": "Air-cooled chiller", "source_scope_status": "PAPER_CORE", "paper_core_index": "1", "IT_HEAT_CAPTURE": "air", "HEAT_TRANSPORT": "air", "HEAT_REJECTION": "dry", "ECONOMIZER": "none", "MECHANICAL_COOLING": "air-cooled chiller", "DIRECT_WATER_MECHANISM": "humidification", "liquid_it": "no", "lei2025_cases": "4,10", "liquid_cooling_type": "NOT_APPLICABLE", "confidence": "high", "notes": "paper item (1)"},
        {"tech_id": "AE_ACC", "source_label": "Airside economizer (air-cooled chiller)", "source_scope_status": "PAPER_CORE", "paper_core_index": "2", "IT_HEAT_CAPTURE": "air", "HEAT_TRANSPORT": "air", "HEAT_REJECTION": "dry", "ECONOMIZER": "airside", "MECHANICAL_COOLING": "air-cooled chiller", "DIRECT_WATER_MECHANISM": "humidification", "liquid_it": "no", "lei2025_cases": "2", "liquid_cooling_type": "NOT_APPLICABLE", "confidence": "high", "notes": "paper item (2)"},
        {"tech_id": "AE_WCC", "source_label": "Airside economizer (water-cooled chiller)", "source_scope_status": "PAPER_CORE", "paper_core_index": "3", "IT_HEAT_CAPTURE": "air", "HEAT_TRANSPORT": "air", "HEAT_REJECTION": "evaporative tower", "ECONOMIZER": "airside", "MECHANICAL_COOLING": "water-cooled chiller", "DIRECT_WATER_MECHANISM": "cooling tower", "liquid_it": "no", "lei2025_cases": "1", "liquid_cooling_type": "NOT_APPLICABLE", "confidence": "high", "notes": "paper item (3)"},
        {"tech_id": "AE_AD_ACC", "source_label": "Airside economizer& adiabatic cooling (air-cooled chiller)", "source_scope_status": "PAPER_CORE", "paper_core_index": "4", "IT_HEAT_CAPTURE": "air", "HEAT_TRANSPORT": "air", "HEAT_REJECTION": "hybrid dry/adiabatic", "ECONOMIZER": "airside", "MECHANICAL_COOLING": "air-cooled chiller supplemental", "DIRECT_WATER_MECHANISM": "adiabatic_and_humidification", "liquid_it": "no", "lei2025_cases": "0", "liquid_cooling_type": "NOT_APPLICABLE", "confidence": "high", "notes": "paper item (4); closest but not exact PRN1 map"},
        {"tech_id": "AE_AD_WCC", "source_label": "Airside economizer& adiabatic cooling (water-cooled chiller)", "source_scope_status": "PAPER_CORE", "paper_core_index": "5", "IT_HEAT_CAPTURE": "air", "HEAT_TRANSPORT": "air", "HEAT_REJECTION": "hybrid plus tower if chiller", "ECONOMIZER": "airside", "MECHANICAL_COOLING": "water-cooled chiller supplemental", "DIRECT_WATER_MECHANISM": "multiple", "liquid_it": "no", "lei2025_cases": "6", "liquid_cooling_type": "NOT_APPLICABLE", "confidence": "high", "notes": "paper item (5)"},
        {"tech_id": "DX", "source_label": "Direct expansion system", "source_scope_status": "PAPER_CORE", "paper_core_index": "6", "IT_HEAT_CAPTURE": "air", "HEAT_TRANSPORT": "air", "HEAT_REJECTION": "dry", "ECONOMIZER": "none", "MECHANICAL_COOLING": "DX", "DIRECT_WATER_MECHANISM": "humidification", "liquid_it": "no", "lei2025_cases": "5,11", "liquid_cooling_type": "NOT_APPLICABLE", "confidence": "high", "notes": "paper item (6)"},
        {"tech_id": "WCC", "source_label": "Water-cooled chiller", "source_scope_status": "PAPER_CORE", "paper_core_index": "7", "IT_HEAT_CAPTURE": "air", "HEAT_TRANSPORT": "air", "HEAT_REJECTION": "evaporative tower", "ECONOMIZER": "none", "MECHANICAL_COOLING": "water-cooled chiller", "DIRECT_WATER_MECHANISM": "cooling tower", "liquid_it": "no", "lei2025_cases": "3,9", "liquid_cooling_type": "NOT_APPLICABLE", "confidence": "high", "notes": "paper item (7)"},
        {"tech_id": "WE_WCC", "source_label": "Waterside economizer (water-cooled chiller)", "source_scope_status": "PAPER_CORE", "paper_core_index": "8", "IT_HEAT_CAPTURE": "air", "HEAT_TRANSPORT": "liquid loop", "HEAT_REJECTION": "evaporative tower", "ECONOMIZER": "waterside", "MECHANICAL_COOLING": "water-cooled chiller supplemental", "DIRECT_WATER_MECHANISM": "cooling tower", "liquid_it": "no", "lei2025_cases": "7,8", "liquid_cooling_type": "NOT_APPLICABLE", "confidence": "high", "notes": "paper item (8)"},
        {"tech_id": "LIQ_WE_WCC", "source_label": "IT Liquid cooling: waterside economizer (water-cooled chiller)", "source_scope_status": "PAPER_CORE", "paper_core_index": "9", "IT_HEAT_CAPTURE": "liquid subtype via Case (Original)", "HEAT_TRANSPORT": "liquid loop", "HEAT_REJECTION": "evaporative tower", "ECONOMIZER": "waterside", "MECHANICAL_COOLING": "water-cooled chiller supplemental", "DIRECT_WATER_MECHANISM": "cooling tower", "liquid_it": "yes", "lei2025_cases": "15_1,15_2,15_3", "liquid_cooling_type": "RDHX/cold-plate/immersion via 15_1/2/3", "confidence": "high", "notes": "paper item (9); Case integer 15 = WE (CSV verified)"},
        {"tech_id": "LIQ_DRY_AD", "source_label": "IT Liquid cooling: dry cooler with adiabatic assist (air-cooled chiller)", "source_scope_status": "PAPER_CORE", "paper_core_index": "10", "IT_HEAT_CAPTURE": "liquid subtype via Case (Original)", "HEAT_TRANSPORT": "liquid loop", "HEAT_REJECTION": "hybrid dry/adiabatic", "ECONOMIZER": "none", "MECHANICAL_COOLING": "air-cooled chiller supplemental", "DIRECT_WATER_MECHANISM": "adiabatic assist", "liquid_it": "yes", "lei2025_cases": "16_1,16_2,16_3", "liquid_cooling_type": "RDHX/cold-plate/immersion via 16_1/2/3", "confidence": "high", "notes": "paper item (10); Case integer 16 = dry/adiabatic (CSV verified)"},
        {"tech_id": "DRY_ACC", "source_label": "Dry cooler (air-cooled chiller)", "source_scope_status": "SOURCE_EXTRA_EXTENDED", "paper_core_index": "", "IT_HEAT_CAPTURE": "air", "HEAT_TRANSPORT": "liquid loop", "HEAT_REJECTION": "dry", "ECONOMIZER": "none", "MECHANICAL_COOLING": "air-cooled chiller", "DIRECT_WATER_MECHANISM": "humidification", "liquid_it": "no", "lei2025_cases": "17", "liquid_cooling_type": "NOT_APPLICABLE", "confidence": "medium", "notes": "Present in UEs CSV; Rmd drops Case 17; not in paper ten"},
        {"tech_id": "DRY_AD_ACC", "source_label": "Dry cooler with adiabatic assist (air-cooled chiller)", "source_scope_status": "SOURCE_EXTRA_EXTENDED", "paper_core_index": "", "IT_HEAT_CAPTURE": "air", "HEAT_TRANSPORT": "liquid loop", "HEAT_REJECTION": "hybrid dry/adiabatic", "ECONOMIZER": "none", "MECHANICAL_COOLING": "air-cooled chiller", "DIRECT_WATER_MECHANISM": "adiabatic assist", "liquid_it": "no", "lei2025_cases": "18", "liquid_cooling_type": "NOT_APPLICABLE", "confidence": "medium", "notes": "Present in UEs CSV; Rmd drops Case 18; not in paper ten"},
    ]
    write_csv(ROOT / "data_processed/COOLING_TAXONOMY.csv", tax, tax_fields)

    xw_fields = ["lei2022_paper_case", "lei2022_code_function", "lei2025_case", "lei2025_label", "tech_id", "source_scope_status", "lbnl2024_table42", "mapping", "confidence", "rationale", "uncertainty"]
    xw = [
        {"lei2022_paper_case": "7", "lei2022_code_function": "PUE_WUE_AIRChiller", "lei2025_case": "4,10", "lei2025_label": "Air-cooled chiller", "tech_id": "ACC", "source_scope_status": "PAPER_CORE", "lbnl2024_table42": "Air-cooled chiller", "mapping": "equivalent", "confidence": "high", "rationale": "no economizer air-cooled", "uncertainty": "size split"},
        {"lei2022_paper_case": "6", "lei2022_code_function": "PUE_WUE_AE_AIRChiller", "lei2025_case": "0", "lei2025_label": "Airside economizer& adiabatic cooling (air-cooled chiller)", "tech_id": "AE_AD_ACC", "source_scope_status": "PAPER_CORE", "lbnl2024_table42": "Airside economizer & adiabatic cooling", "mapping": "equivalent", "confidence": "medium", "rationale": "AE+adiabatic+AC", "uncertainty": "Lei supplemental chiller vs Prineville no-chiller"},
        {"lei2022_paper_case": "3", "lei2022_code_function": "PUE_WUE_AE_Chiller_Colo", "lei2025_case": "1", "lei2025_label": "Airside economizer (water-cooled chiller)", "tech_id": "AE_WCC", "source_scope_status": "PAPER_CORE", "lbnl2024_table42": "Airside economizer", "mapping": "approximate", "confidence": "medium", "rationale": "midsize AE+WC", "uncertainty": "numbering"},
        {"lei2022_paper_case": "1", "lei2022_code_function": "PUE_WUE_AE_Chiller", "lei2025_case": "6", "lei2025_label": "Airside economizer& adiabatic cooling (water-cooled chiller)", "tech_id": "AE_AD_WCC", "source_scope_status": "PAPER_CORE", "lbnl2024_table42": "Airside economizer & adiabatic cooling", "mapping": "equivalent", "confidence": "high", "rationale": "large AE+adiabatic+WC", "uncertainty": "size"},
        {"lei2022_paper_case": "10", "lei2022_code_function": "PUE_WUE_DX", "lei2025_case": "5,11", "lei2025_label": "Direct expansion system", "tech_id": "DX", "source_scope_status": "PAPER_CORE", "lbnl2024_table42": "DX mentioned; not Table 4.2 focus", "mapping": "equivalent", "confidence": "high", "rationale": "DX", "uncertainty": ""},
        {"lei2022_paper_case": "5", "lei2022_code_function": "PUE_WUE_Chiller", "lei2025_case": "3,9", "lei2025_label": "Water-cooled chiller", "tech_id": "WCC", "source_scope_status": "PAPER_CORE", "lbnl2024_table42": "Water-cooled chiller", "mapping": "equivalent", "confidence": "high", "rationale": "WC no economizer", "uncertainty": ""},
        {"lei2022_paper_case": "2/4", "lei2022_code_function": "PUE_WUE_Chiller_Watereconomier / WE_Chiller_Colo", "lei2025_case": "7,8", "lei2025_label": "Waterside economizer (water-cooled chiller)", "tech_id": "WE_WCC", "source_scope_status": "PAPER_CORE", "lbnl2024_table42": "Waterside economizer", "mapping": "equivalent", "confidence": "high", "rationale": "WE+WC", "uncertainty": "size split"},
        {"lei2022_paper_case": "NA", "lei2022_code_function": "NOT IN 2022 PUBLIC CODE", "lei2025_case": "15_1/2/3", "lei2025_label": "IT Liquid cooling: waterside economizer (water-cooled chiller)", "tech_id": "LIQ_WE_WCC", "source_scope_status": "PAPER_CORE", "lbnl2024_table42": "IT liquid cooling: waterside economizer", "mapping": "equivalent_to_lbnl_label", "confidence": "high", "rationale": "CSV Case 15 = WE liquid; subtypes via original IDs", "uncertainty": "hourly engine not public"},
        {"lei2022_paper_case": "NA", "lei2022_code_function": "NOT IN 2022 PUBLIC CODE", "lei2025_case": "16_1/2/3", "lei2025_label": "IT Liquid cooling: dry cooler with adiabatic assist (air-cooled chiller)", "tech_id": "LIQ_DRY_AD", "source_scope_status": "PAPER_CORE", "lbnl2024_table42": "IT liquid cooling: dry cooler with/without adiabatic", "mapping": "equivalent_to_lbnl_label", "confidence": "high", "rationale": "CSV Case 16 = dry/adiabatic liquid", "uncertainty": "hourly engine not public"},
        {"lei2022_paper_case": "NA", "lei2022_code_function": "NOT IN 2022 PUBLIC CODE", "lei2025_case": "17", "lei2025_label": "Dry cooler (air-cooled chiller)", "tech_id": "DRY_ACC", "source_scope_status": "SOURCE_EXTRA_EXTENDED", "lbnl2024_table42": "Dry cooler with or without adiabatic assist", "mapping": "approximate", "confidence": "medium", "rationale": "CSV present; excluded from paper ten / Rmd figures", "uncertainty": "not equivalent to paper-core"},
        {"lei2022_paper_case": "NA", "lei2022_code_function": "NOT IN 2022 PUBLIC CODE", "lei2025_case": "18", "lei2025_label": "Dry cooler with adiabatic assist (air-cooled chiller)", "tech_id": "DRY_AD_ACC", "source_scope_status": "SOURCE_EXTRA_EXTENDED", "lbnl2024_table42": "Dry cooler with adiabatic assist", "mapping": "approximate", "confidence": "medium", "rationale": "CSV present; Rmd Case 18 filter", "uncertainty": "not equivalent to paper-core"},
        {"lei2022_paper_case": "NA", "lei2022_code_function": "", "lei2025_case": "12,13,14", "lei2025_label": "(absent)", "tech_id": "", "source_scope_status": "ABSENT_FROM_PUBLIC_CSV", "lbnl2024_table42": "", "mapping": "not-comparable", "confidence": "high", "rationale": "integers missing from UEs_16cases.csv; Rmd also filters them", "uncertainty": ""},
    ]
    write_csv(ROOT / "data_processed/MASANET_LEI2025_LBNL_CROSSWALK.csv", xw, xw_fields)


def main():
    os.environ.setdefault("PYTHONNOUSERSITE", "1")
    raw = pd.read_csv(UES)
    df = annotate(raw)
    assert set(LIQUID_MAP) <= set(df["Case (Original)"].astype(str))
    assert (df.loc[df["Case (Original)"].astype(str).isin(LIQUID_MAP), "liquid_cooling_type"] != "NOT_APPLICABLE").all()
    # Case integer vs heat rejection
    assert set(df.loc[df["Case"] == 15, "tech_id"].unique()) == {"LIQ_WE_WCC"}
    assert set(df.loc[df["Case"] == 16, "tech_id"].unique()) == {"LIQ_DRY_AD"}

    df.to_parquet(ROOT / "data_processed/cooling_proxy_scenarios.parquet", index=False)
    summary = summary_table(df)
    summary.to_csv(ROOT / "data_processed/cooling_proxy_summary.csv", index=False)
    domain = domain_matrix(df, summary)
    domain.to_csv(ROOT / "data_processed/SUPPORTED_DOMAIN_MATRIX.csv", index=False)
    write_static_tables()

    matched = matched_comparisons(df)
    matched.to_csv(ROOT / "analysis/MATCHED_TECHNOLOGY_COMPARISONS.csv", index=False)
    decomp = liquid_decomposition(df)
    decomp.to_csv(ROOT / "analysis/LIQUID_EFFECT_DECOMPOSITION.csv", index=False)

    figs = figures(df, decomp)
    (ROOT / "analysis/FIGURES.json").write_text(json.dumps({"files": figs, "note": "MODELED SOURCE ENSEMBLE"}, indent=2) + "\n")

    val_rows, val_meta = prineville_validation(df)
    val_rows.to_csv(ROOT / "analysis/PRINEVILLE_EARLY_EPOCH_VALIDATION.csv", index=False)
    (ROOT / "analysis/PRINEVILLE_EARLY_VALIDATION_META.json").write_text(json.dumps(val_meta, indent=2) + "\n")

    # QC
    qc = {
        "timestamp_utc": utcnow(),
        "n_scenario_rows": int(len(df)),
        "n_summary_cells": int(len(summary)),
        "n_domain_cells": int(len(domain)),
        "paired_pairs_preserved": True,
        "scenario_semantics": "SOURCE_MODEL_SCENARIO",
        "quantile_semantics": "SOURCE_SCENARIO_QUANTILE",
        "equal_weight_name": "DESIGN_PRIOR_UNIFORM",
        "n_paper_core": int((df.source_scope_status == "PAPER_CORE").sum()),
        "n_source_extra": int((df.source_scope_status == "SOURCE_EXTRA_EXTENDED").sum()),
        "n_liquid_subtype_not_na": int((df.liquid_cooling_type != "NOT_APPLICABLE").sum()),
        "liquid_map_source": LIQUID_RMD_SOURCE,
        "PAIRED_SAMPLING_REQUIRED": True,
        "did_read_meta_2023_2024_water": False,
        "prineville_early_validation_overall": val_meta["overall_classification"],
    }
    (ROOT / "analysis/COOLING_PROXY_QC.json").write_text(json.dumps(qc, indent=2) + "\n")
    print(json.dumps({"n": len(df), "summary": len(summary), "domain": len(domain), "validation": val_meta["overall_classification"]}, indent=2))


if __name__ == "__main__":
    main()
