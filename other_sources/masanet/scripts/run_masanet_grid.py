#!/usr/bin/env python3
"""Phase 4: small climate factorial on all implemented archetypes. Characterization, not calibration."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import (
    ARCHETYPE_META,
    ARCHETYPE_PARAMS,
    CANONICAL_BY_NAME,
    CANONICAL_SEED,
    EXTRA_SEEDS,
    POWER_LABELS,
    UPSTREAM_COMMIT,
    WATER_LABELS,
    WORK_ROOT,
    atomic_write_json,
    load_upstream,
    set_threads,
    utcnow,
    vector_for,
)
from instrument_upstream import load_instrumented

T_GRID = [-5.0, 5.0, 15.0, 25.0, 35.0]
RH_GRID = [20.0, 50.0, 80.0]
P_OA = 101325.0


def flags_for(name, T, RH, rec, pue, wue):
    flags = []
    if not (np.isfinite(pue) and np.isfinite(wue)):
        flags.append("nonfinite")
    if np.isfinite(pue) and pue < 1:
        flags.append("PUE_lt_1")
    wc = rec.get("Water_comp") or []
    if any(float(v) < -1e-12 for v in wc):
        flags.append("negative_water")
    if name == "PUE_WUE_DX" and T <= 15:
        flags.append("DX_COP_override_T_le_15")
    if rec.get("AE_use") in (0, 1):
        flags.append(f"AE_use={rec.get('AE_use')}")
    if rec.get("WE_use") in (0, 1):
        flags.append(f"WE_use={rec.get('WE_use')}")
    return flags


def eval_one(inst, name, T, RH, seed):
    x = vector_for(name, climate={"T_oa": T, "RH_oa": RH, "P_oa": P_OA})
    np.random.seed(seed)
    fn = getattr(inst, name)
    pue, wue = fn(x)
    rec = dict(inst._LAST)
    pc = rec.get("Power_comp") or []
    wc = rec.get("Water_comp") or []
    row = {
        "archetype": name,
        "archetype_class": ARCHETYPE_META[name]["class"],
        "T_oa_C": T,
        "RH_oa_pct": RH,
        "P_oa_Pa": P_OA,
        "seed": seed,
        "PUE": float(pue),
        "WUE": float(wue),
        "Power_IT": float(rec.get("Power_IT", 1.0)),
        "Q": rec.get("Q"),
        "COP_chiller": rec.get("COP_chiller"),
        "AE_use": rec.get("AE_use"),
        "WE_use": rec.get("WE_use"),
        "upstream_commit": UPSTREAM_COMMIT,
        "flags": "|".join(flags_for(name, T, RH, rec, pue, wue)),
        "finite": bool(np.isfinite(pue) and np.isfinite(wue)),
        "PUE_ge_1": bool(np.isfinite(pue) and pue >= 1),
        "energy_closes": bool(
            len(pc) > 0
            and abs(float(np.sum(pc)) / float(rec.get("Power_IT", 1.0)) - float(pue)) <= 1e-8
        ),
        "water_closes": bool(
            len(wc) > 0
            and abs(float(np.sum(wc)) * 3600 / float(rec.get("Power_IT", 1.0)) - float(wue)) <= 1e-6
        ),
    }
    for lab, val in zip(POWER_LABELS[name], pc):
        row[f"P_{lab}"] = float(val)
    for lab, val in zip(WATER_LABELS[name], wc):
        row[f"W_{lab}_kg_s"] = float(val)
    return row


def main():
    set_threads()
    load_upstream()  # confirm COP shim path
    inst = load_instrumented(1.0)
    rows = []
    errors = []
    for name in ARCHETYPE_PARAMS:
        for T in T_GRID:
            for RH in RH_GRID:
                try:
                    rows.append(eval_one(inst, name, T, RH, CANONICAL_SEED))
                except Exception as e:
                    errors.append(
                        {
                            "archetype": name,
                            "T_oa_C": T,
                            "RH_oa_pct": RH,
                            "seed": CANONICAL_SEED,
                            "error": f"{type(e).__name__}: {e}",
                        }
                    )
        # extra seeds at demo climate and one hot/humid point
        for T, RH in [(9.0, 10.0), (35.0, 80.0)]:
            for seed in EXTRA_SEEDS:
                try:
                    rows.append(eval_one(inst, name, T, RH, seed))
                except Exception as e:
                    errors.append(
                        {
                            "archetype": name,
                            "T_oa_C": T,
                            "RH_oa_pct": RH,
                            "seed": seed,
                            "error": f"{type(e).__name__}: {e}",
                        }
                    )

    df = pd.DataFrame(rows)
    out_parq = WORK_ROOT / "results" / "masanet_grid.parquet"
    out_parq.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_parq, index=False)
    df.to_csv(WORK_ROOT / "results" / "masanet_grid.csv", index=False)

    canon = df[df["seed"] == CANONICAL_SEED]
    figdir = WORK_ROOT / "results" / "figures"
    figdir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(8, 5))
    for name, g in canon.groupby("archetype"):
        gg = g.groupby("T_oa_C")[["PUE", "WUE"]].median()
        ax.plot(gg.index, gg["PUE"], marker="o", label=name.replace("PUE_WUE_", ""))
    ax.set_xlabel("T_oa (C)")
    ax.set_ylabel("PUE")
    ax.legend(fontsize=7, loc="best")
    ax.set_title("Canonical seed: PUE vs dry-bulb (median over RH)")
    fig.tight_layout()
    fig.savefig(figdir / "fig_pue_vs_T.png", dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 5))
    for name, g in canon.groupby("archetype"):
        gg = g.groupby("T_oa_C")[["WUE"]].median()
        ax.plot(gg.index, gg["WUE"], marker="o", label=name.replace("PUE_WUE_", ""))
    ax.set_xlabel("T_oa (C)")
    ax.set_ylabel("WUE (L/kWh intensity units)")
    ax.legend(fontsize=7, loc="best")
    ax.set_title("Canonical seed: WUE vs dry-bulb (median over RH)")
    fig.tight_layout()
    fig.savefig(figdir / "fig_wue_vs_T.png", dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 6))
    for name, g in canon.groupby("archetype"):
        ax.scatter(g["PUE"], g["WUE"], s=18, alpha=0.75, label=name.replace("PUE_WUE_", ""))
    ax.set_xlabel("PUE")
    ax.set_ylabel("WUE")
    ax.legend(fontsize=7)
    ax.set_title("Joint PUE–WUE (do not analyze marginally)")
    fig.tight_layout()
    fig.savefig(figdir / "fig_pue_wue_joint.png", dpi=140)
    plt.close(fig)

    lbnl = {
        "status": "QUALITATIVE_TRIANGULATION_ONLY",
        "reason": (
            "Grid points are instantaneous intensity evaluations at fixed facility parameters. "
            "LBNL 2024 reports annual/stock PUE and water metrics with mixed system boundaries and "
            "shared Lei authorship lineage, so they are not statistically independent validation "
            "and are not comparable to single-hour model points. Karimi et al. SSRN 5131144 is "
            "independent but annual/hot-arid and is used only as directional context."
        ),
        "taxonomy_alignment": {
            "PUE_WUE_DX": "air-cooled DX / CRAC-like",
            "PUE_WUE_AIRChiller": "air-cooled chiller",
            "PUE_WUE_AE_AIRChiller": "air-side economizer + air-cooled chiller",
            "PUE_WUE_Chiller": "water-cooled chiller + cooling tower",
            "PUE_WUE_WE_Chiller_Colo": "waterside economizer + water-cooled chiller (colo)",
            "PUE_WUE_Chiller_Watereconomier": "waterside economizer + water-cooled chiller (hyperscale)",
            "PUE_WUE_AE_Chiller": "air-side economizer / adiabatic + water-cooled chiller (hyperscale)",
            "PUE_WUE_AE_Chiller_Colo": "air-side economizer + water-cooled chiller (colo; no adiabatic humidification in helper)",
        },
        "directional_expectations_not_tests": [
            "Air-cooled archetypes should have lower WUE (humidification-only) and typically higher PUE than water-cooled with economizer in hot conditions.",
            "WE/AE should reduce chiller power when outdoor conditions allow.",
            "Do not treat LBNL annual PUE envelopes as pass/fail bounds on this grid.",
        ],
    }

    n_bad = int((~canon["finite"]).sum()) if len(canon) else 0
    n_pue = int((canon["PUE_ge_1"] == False).sum()) if len(canon) else 0
    summary = {
        "status": "PASS" if not errors and n_bad == 0 else ("PARTIAL" if len(rows) else "FAIL"),
        "timestamp_utc": utcnow(),
        "n_rows": int(len(df)),
        "n_errors": len(errors),
        "errors": errors,
        "grid": {"T_oa_C": T_GRID, "RH_oa_pct": RH_GRID, "P_oa_Pa": P_OA, "canonical_seed": CANONICAL_SEED},
        "held_fixed": "Canonical facility/system vector mapped by parameter name from demo.ipynb WE_Chiller_Colo input (Table B.1 PDF not accessed).",
        "n_nonfinite_canonical": n_bad,
        "n_PUE_lt_1_canonical": n_pue,
        "lbnl_comparison": lbnl,
        "parquet": str(out_parq),
        "figures": [
            str(figdir / "fig_pue_vs_T.png"),
            str(figdir / "fig_wue_vs_T.png"),
            str(figdir / "fig_pue_wue_joint.png"),
        ],
    }
    atomic_write_json(WORK_ROOT / "results" / "masanet_grid_summary.json", summary)
    print(json.dumps({k: summary[k] for k in ("status", "n_rows", "n_errors")}, indent=2))
    if summary["status"] == "FAIL":
        sys.exit(2)


if __name__ == "__main__":
    main()
