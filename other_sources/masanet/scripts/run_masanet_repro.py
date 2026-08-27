#!/usr/bin/env python3
"""Phase 2: execute nested demo without changing model assumptions; seed reproducibility."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import (
    ARCHETYPE_PARAMS,
    CANONICAL_SEED,
    DEMO_VECTOR,
    EXTRA_SEEDS,
    PY,
    UPSTREAM,
    UPSTREAM_COMMIT,
    WORK_ROOT,
    atomic_write_json,
    atomic_write_text,
    load_upstream,
    set_threads,
    utcnow,
    vector_for,
)


def env_identity():
    import numpy, pandas, sklearn, scipy, CoolProp

    return {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "numpy": numpy.__version__,
        "pandas": pandas.__version__,
        "sklearn": sklearn.__version__,
        "scipy": scipy.__version__,
        "CoolProp": CoolProp.__version__,
        "expected_python": PY.as_posix(),
    }


def run_seeded(fn, x, seed):
    np.random.seed(seed)
    return tuple(float(v) for v in fn(x))


def main():
    set_threads()
    inspect = subprocess.run(
        [sys.executable, str(WORK_ROOT / "scripts" / "inspect_upstream.py")],
        check=False,
    )
    paper = subprocess.run(
        [sys.executable, str(WORK_ROOT / "scripts" / "extract_paper_context.py")],
        check=False,
    )
    mod, cop_notes = load_upstream()
    env = env_identity()
    fn = mod.PUE_WUE_WE_Chiller_Colo
    notebook = (1.339160993824991, 2.417390377483526)
    a = run_seeded(fn, DEMO_VECTOR, CANONICAL_SEED)
    b = run_seeded(fn, DEMO_VECTOR, CANONICAL_SEED)
    extra = {str(s): run_seeded(fn, DEMO_VECTOR, s) for s in EXTRA_SEEDS}
    seeded_ok = a == b
    # Notebook did not set a seed; WUE is expected to be closer than PUE.
    wue_vs_nb = abs(a[1] - notebook[1])
    pue_vs_nb = abs(a[0] - notebook[0])

    cop_ok = {}
    for name, model, X in [
        ("COP_2", mod.COP_gp, np.array([[20.0, 0.5]])),
        ("COP_AC", mod.COP_air_gp, np.array([[20.0, 0.5]])),
        ("COP_DX", mod.COP_DX_gp, np.array([[20.0]])),
    ]:
        try:
            y = float(model.predict(X)[0])
            cop_ok[name] = {"ok": True, "predict": y, "finite": np.isfinite(y)}
        except Exception as e:
            cop_ok[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    finite_archetypes = {}
    for name in ARCHETYPE_PARAMS:
        f = getattr(mod, name)
        x = vector_for(name)
        try:
            np.random.seed(CANONICAL_SEED)
            pue, wue = f(x)
            finite_archetypes[name] = {
                "ok": bool(np.isfinite(pue) and np.isfinite(wue)),
                "PUE": float(pue),
                "WUE": float(wue),
                "PUE_ge_1": bool(pue >= 1),
            }
        except Exception as e:
            finite_archetypes[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    ue_path = UPSTREAM / "Simulation Results" / "UE.xlsx"
    ue = pd.read_excel(ue_path)
    ue_summary = {
        "path": str(ue_path),
        "n_rows": int(len(ue)),
        "columns": list(ue.columns),
        "cases": sorted(ue["Case"].dropna().unique().tolist()) if "Case" in ue.columns else [],
        "climate_zones": sorted(ue["Climate Zone"].dropna().unique().tolist())
        if "Climate Zone" in ue.columns
        else [],
        "quantiles": sorted(ue["Quantile"].dropna().unique().tolist()) if "Quantile" in ue.columns else [],
        "PUE_range": [float(ue["PUE"].min()), float(ue["PUE"].max())],
        "WUE_range": [float(ue["WUE"].min()), float(ue["WUE"].max())],
        "comparison": (
            "Bundled UE.xlsx is climate-zone x case x quantile output, not the demo.ipynb instantaneous "
            "evaluation. Not an apples-to-apples numerical check of the demo vector."
        ),
    }

    cop_all = all(v.get("ok") and v.get("finite", True) for v in cop_ok.values())
    arche_all = all(v.get("ok") for v in finite_archetypes.values())
    if cop_all and seeded_ok and arche_all:
        # Notebook PUE not reconstructed (no seed); WUE matches to ~1e-12.
        status = "PARTIAL" if pue_vs_nb > 1e-3 else "PASS"
        reason = (
            "Implementation runs; COP models load with documented sklearn shim; seed 2025 is bit-stable; "
            "all 8 archetypes return finite PUE/WUE on the canonical demo-mapped vector. "
            "Notebook PUE is not recovered because demo.ipynb did not set np.random.seed; "
            f"canonical-seed WUE differs from notebook by {wue_vs_nb:.3e}."
        )
    else:
        status = "FAIL"
        reason = "Load, seeded repeat, or archetype evaluation failed."

    summary = {
        "status": status,
        "reason": reason,
        "timestamp_utc": utcnow(),
        "upstream_commit": UPSTREAM_COMMIT,
        "environment": env,
        "cop_compat_notes": cop_notes,
        "cop_predict": cop_ok,
        "demo": {
            "function": "PUE_WUE_WE_Chiller_Colo",
            "notebook_output": list(notebook),
            "seed_2025": list(a),
            "seed_2025_repeat": list(b),
            "repeat_exact": seeded_ok,
            "extra_seeds": extra,
            "abs_PUE_vs_notebook": pue_vs_nb,
            "abs_WUE_vs_notebook": wue_vs_nb,
            "pue_varies_with_seed": abs(a[0] - extra[str(EXTRA_SEEDS[0])][0]) > 1e-12,
            "wue_varies_with_seed": abs(a[1] - extra[str(EXTRA_SEEDS[0])][1]) > 1e-12,
        },
        "archetypes_canonical_climate": finite_archetypes,
        "bundled_UE_xlsx": ue_summary,
        "inspect_exit_code": inspect.returncode,
        "paper_extract_exit_code": paper.returncode,
    }
    atomic_write_json(WORK_ROOT / "results" / "masanet_reproduction_summary.json", summary)

    md = f"""# Lei–Masanet reproduction

Status: **{status}**

Upstream commit `{UPSTREAM_COMMIT}`. Nested clone is unlicensed; used in place.

## Environment

Python {env['python']}, numpy {env['numpy']}, sklearn {env['sklearn']}, scipy {env['scipy']}, CoolProp {env['CoolProp']}.
`dc_externalities` lacks CoolProp/sklearn; dedicated env `masanet_lei` was created.

COP pickles were trained on sklearn 0.22.2/0.23.1. They load under 1.0.2. `COP_AC.pkl` lacks `_y_train_std`; our loader sets it to 1 because `normalize_y` is False. Upstream files were not edited.

## Demo

`PUE_WUE_WE_Chiller_Colo` with the notebook vector.

| | PUE | WUE |
| --- | --- | --- |
| notebook (seed unset) | {notebook[0]} | {notebook[1]} |
| seed {CANONICAL_SEED} | {a[0]} | {a[1]} |
| seed {CANONICAL_SEED} repeat | {b[0]} | {b[1]} |
| seed {EXTRA_SEEDS[0]} | {extra[str(EXTRA_SEEDS[0])][0]} | {extra[str(EXTRA_SEEDS[0])][1]} |
| seed {EXTRA_SEEDS[1]} | {extra[str(EXTRA_SEEDS[1])][0]} | {extra[str(EXTRA_SEEDS[1])][1]} |

Seed reset to {CANONICAL_SEED} reproduces exactly: `{seeded_ok}`.
WUE vs notebook absolute difference `{wue_vs_nb:.3e}`. PUE differs because `Chiller_system` draws `d_sa` randomly and the notebook did not seed.

## Bundled `Simulation Results/UE.xlsx`

Climate-zone × case × quantile table (PUE {ue_summary['PUE_range'][0]:.3f}–{ue_summary['PUE_range'][1]:.3f}, WUE {ue_summary['WUE_range'][0]:.3f}–{ue_summary['WUE_range'][1]:.3f}). Not comparable to a single demo climate snapshot.

## Archetypes on mapped canonical vector

All eight PUE/WUE functions evaluated at seed {CANONICAL_SEED}. See JSON.
"""
    atomic_write_text(WORK_ROOT / "docs" / "MASANET_REPRODUCTION.md", md)
    print(json.dumps({"status": status, "seed2025": a, "repeat": seeded_ok}, indent=2))
    if status == "FAIL":
        sys.exit(2)


if __name__ == "__main__":
    main()
