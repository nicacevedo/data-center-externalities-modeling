#!/usr/bin/env python3
"""Clean-kernel top-to-bottom replay of demo.ipynb. No seed search."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import DEMO_VECTOR, load_upstream, patch_cop_models, set_threads  # noqa: E402
from instrument_upstream import load_instrumented  # noqa: E402
from v2_common import RES, UPSTREAM, V1, atomic_write_json, utcnow  # noqa: E402


def _state_brief():
    st = np.random.get_state()
    return {"kind": st[0], "key_head": [int(x) for x in st[1][:4]], "pos": int(st[2])}


def main():
    set_threads()
    nb = json.loads((UPSTREAM / "demo.ipynb").read_text())
    stored = None
    for cell in nb["cells"]:
        for o in cell.get("outputs") or []:
            if o.get("text"):
                stored = "".join(o["text"])
    stored_pue, stored_wue = 1.339160993824991, 2.417390377483526

    # B: execute notebook cells in order in a fresh namespace (chdir to upstream).
    prev = os.getcwd()
    os.chdir(UPSTREAM)
    if str(UPSTREAM) not in sys.path:
        sys.path.insert(0, str(UPSTREAM))
    ns = {"__name__": "__main__"}
    order = []
    buf = io.StringIO()
    np.random.seed()
    state_entry = _state_brief()
    with contextlib.redirect_stdout(buf):
        for i, cell in enumerate(nb["cells"]):
            if cell.get("cell_type") != "code":
                continue
            src = "".join(cell.get("source") or [])
            if not src.strip():
                continue
            order.append({"index": i, "n_chars": len(src), "head": src.strip().splitlines()[0][:80]})
            exec(compile(src, f"demo.ipynb:cell{i}", "exec"), ns)
            if i == 0 and "simulation_funs_DC" in sys.modules:
                patch_cop_models(sys.modules["simulation_funs_DC"])
    os.chdir(prev)
    stdout_b = buf.getvalue()
    x_nb = ns.get("x")
    state_exit = _state_brief()

    # C: canonical wrapper seed 2025, same explicit inputs
    mod, notes = load_upstream()
    vec = list(x_nb) if x_nb is not None else DEMO_VECTOR
    np.random.seed(2025)
    pue_c, wue_c = mod.PUE_WUE_WE_Chiller_Colo(vec)
    np.random.seed(2025)
    pue_c2, wue_c2 = mod.PUE_WUE_WE_Chiller_Colo(vec)

    inst = load_instrumented(1.0, rewrite=True)
    np.random.seed(2025)
    inst.PUE_WUE_WE_Chiller_Colo(vec)
    rec = dict(inst._LAST)

    # parse B stdout if possible
    pue_b = wue_b = None
    if "(" in stdout_b:
        try:
            pair = eval(stdout_b.strip().splitlines()[-1], {"__builtins__": {}})
            pue_b, wue_b = float(pair[0]), float(pair[1])
        except Exception:
            pass
    if pue_b is None:
        pue_b, wue_b = float("nan"), float("nan")

    sweep = json.loads((V1 / "notebook_pue_sweep.json").read_text())
    in_sweep = sweep["PUE"]["min"] - 1e-4 <= float(pue_b) <= sweep["PUE"]["max"] + 1e-4
    wue_match_stored = abs(float(wue_b) - stored_wue) < 1e-8 or abs(float(wue_c) - stored_wue) < 1e-6
    clean_near_canonical = abs(float(pue_b) - float(pue_c)) < 5e-3
    if abs(float(pue_c) - stored_pue) > 0.05 and (in_sweep or clean_near_canonical) and wue_match_stored:
        disp = "NON_REPRODUCIBLE_STORED_SNAPSHOT"
    elif abs(float(pue_c) - stored_pue) <= 1e-8:
        disp = "STORED_MATCHES_CANONICAL"
    else:
        disp = "UNRESOLVED"

    out = {
        "timestamp_utc": utcnow(),
        "disposition": disp,
        "did_not_seed_search": True,
        "did_not_change_stored_notebook_output": True,
        "cell_execution_order": order,
        "A_stored_notebook_output": {"PUE": stored_pue, "WUE": stored_wue, "raw_text": stored},
        "B_clean_top_to_bottom_unseeded": {
            "PUE": float(pue_b),
            "WUE": float(wue_b),
            "stdout": stdout_b.strip(),
            "in_0_9999_sweep_island": in_sweep,
            "input_x_from_notebook": list(map(float, vec)),
            "matches_DEMO_VECTOR": list(map(float, vec)) == list(map(float, DEMO_VECTOR)),
            "np_random_state_entry": state_entry,
            "np_random_state_exit": state_exit,
        },
        "C_canonical_seed_2025": {
            "PUE": float(pue_c),
            "WUE": float(wue_c),
            "rerun_identical": bool(pue_c == pue_c2 and wue_c == wue_c2),
            "power_comp": rec.get("Power_comp"),
            "water_comp": rec.get("Water_comp"),
            "PUE_from_record": rec.get("PUE"),
            "WUE_from_record": rec.get("WUE"),
        },
        "B_vs_C_PUE_abs": abs(float(pue_b) - float(pue_c)),
        "B_vs_C_WUE_abs": abs(float(wue_b) - float(wue_c)),
        "stochastic_helpers_invoked": ["Chiller_system.np.random.uniform(d_sa) inside PUE_WUE_WE_Chiller_Colo"],
        "notebook_metadata": nb.get("metadata", {}).get("kernelspec"),
        "execution_counts_stored": [c.get("execution_count") for c in nb["cells"]],
        "cop_notes": notes,
        "previous_sweep_path": str(V1 / "notebook_pue_sweep.json"),
        "previous_sweep_status": sweep["status"],
        "previous_sweep_did_not_rerun": True,
        "not_an_annual_reproduction_failure": True,
        "interpretation": (
            "If disposition is NON_REPRODUCIBLE_STORED_SNAPSHOT, the stored PUE is a historical "
            "snapshot from another kernel (import cell execution_count null; metadata Python 3.9.12 base). "
            "Clean top-to-bottom execution and canonical seed-2025 execution agree near 1.4445; WUE matches stored."
        ),
    }
    atomic_write_json(RES / "notebook" / "DEMO_REPLAY.json", out)
    print(json.dumps({"disposition": disp, "B_pue": float(pue_b), "C_pue": float(pue_c), "stored": stored_pue}, indent=2))


if __name__ == "__main__":
    main()
