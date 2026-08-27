#!/usr/bin/env python3
"""AST/grep inventory of the nested Lei-Masanet implementation. Does not modify upstream."""
from __future__ import annotations

import ast
import json
import re
from collections import Counter
from pathlib import Path

from common import UPSTREAM, WORK_ROOT, atomic_write_json, set_threads

SRC = UPSTREAM / "simulation_funs_DC.py"
PUE_FUNS = {
    "PUE_WUE_AE_Chiller",
    "PUE_WUE_Chiller_Watereconomier",
    "PUE_WUE_AE_Chiller_Colo",
    "PUE_WUE_WE_Chiller_Colo",
    "PUE_WUE_Chiller",
    "PUE_WUE_DX",
    "PUE_WUE_AIRChiller",
    "PUE_WUE_AE_AIRChiller",
}


def _call_names(node: ast.AST) -> Counter:
    c = Counter()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Name):
                c[n.func.id] += 1
            elif isinstance(n.func, ast.Attribute):
                c[n.func.attr] += 1
    return c


def _random_lines(text: str):
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        if "np.random" in line:
            out.append({"line": i, "text": line.strip(), "commented": line.strip().startswith("#")})
    return out


def main():
    set_threads()
    src = SRC.read_text()
    tree = ast.parse(src)
    functions = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        calls = _call_names(node)
        assigns = []
        power_it = []
        for n in ast.walk(node):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        assigns.append(t.id)
                        if t.id == "Power_IT":
                            power_it.append(
                                {
                                    "line": n.lineno,
                                    "value": ast.unparse(n.value) if hasattr(ast, "unparse") else None,
                                }
                            )
        params = []
        for n in node.body:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                val = n.value
                if isinstance(val, ast.Subscript) and isinstance(val.value, ast.Name) and val.value.id == "w":
                    sl = val.slice
                    idx = sl.n if isinstance(sl, ast.Num) else (sl.value if isinstance(sl, ast.Constant) else None)
                    params.append({"index": idx, "name": n.targets[0].id, "line": n.lineno})
        functions.append(
            {
                "name": node.name,
                "lineno": node.lineno,
                "end_lineno": getattr(node, "end_lineno", None),
                "is_pue_wue": node.name in PUE_FUNS,
                "power_it_assigns": power_it,
                "w_params": params,
                "n_w_params": len(params),
                "calls": dict(calls),
                "n_Air_side_economizer": calls.get("Air_side_economizer", 0),
                "n_Air_side_economizer_colo": calls.get("Air_side_economizer_colo", 0),
                "n_Chiller_system": calls.get("Chiller_system", 0),
                "n_Chiller_system_DX": calls.get("Chiller_system_DX", 0),
                "n_Cooling_Tower": calls.get("Cooling_Tower", 0),
                "n_waterside_economizer": calls.get("waterside_economizer", 0),
                "n_predict": calls.get("predict", 0),
                "assigns_power_like": [a for a in assigns if a.startswith("Power_") or a in {"Q", "PUE", "WUE"}],
                "assigns_water_like": [
                    a for a in assigns if "Water" in a or a in {"hd_amount", "hd_amount_ae", "Water_comp"}
                ],
            }
        )
    inventory = {
        "source": str(SRC),
        "n_lines": src.count("\n") + 1,
        "imports": [
            ast.unparse(n) if hasattr(ast, "unparse") else None
            for n in tree.body
            if isinstance(n, (ast.Import, ast.ImportFrom))
        ],
        "pickle_loads": [
            {"line": i, "text": ln.strip()}
            for i, ln in enumerate(src.splitlines(), 1)
            if "pickle.load" in ln
        ],
        "np_random": _random_lines(src),
        "functions": functions,
        "pue_wue_functions": [f["name"] for f in functions if f["is_pue_wue"]],
        "notes": [
            "Pickle COP models are loaded at import time with relative paths; cwd must be the clone.",
            "Every PUE/WUE function assigns Power_IT = 1 (intensity model).",
            "Several PUE functions call stochastic helpers more than once per evaluation.",
        ],
    }
    out = WORK_ROOT / "results" / "upstream_inventory.json"
    atomic_write_json(out, inventory)
    print("WROTE", out)


if __name__ == "__main__":
    main()
