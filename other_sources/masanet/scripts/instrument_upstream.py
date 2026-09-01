#!/usr/bin/env python3
"""Runtime-only instrumented copy of the nested source. Not our implementation; not for redistribution."""
from __future__ import annotations

import re
from pathlib import Path

from common import UPSTREAM, WORK_ROOT, patch_cop_models

INSTR_DIR = WORK_ROOT / "results" / "_instrumented"
RECORD_FN = '''
_POWER_IT = 1.0
_LAST = {}

def _record_eval(loc):
    keep = [
        "PUE", "WUE", "Power_comp", "Water_comp", "Power_IT", "Q",
        "AE_use", "WE_use", "HD_use", "COP_chiller",
        "Chiller_heat_removed", "CT_heat_removed", "Cooling_required",
        "WE_heat_removed", "hd_amount", "hd_amount_ae",
        "Power_Fan_CRAC", "Power_Pump_hd", "Power_hd", "Power_Chiller",
        "Power_Pump_CW", "Power_Pump_CT", "Power_Fan_CT", "Power_Pump_WE",
        "T_sa", "d_sa", "T_ra",
    ]
    rec = {}
    for k in keep:
        if k in loc:
            v = loc[k]
            try:
                import numpy as _np
                if isinstance(v, _np.ndarray):
                    rec[k] = v.tolist()
                else:
                    rec[k] = v
            except Exception:
                rec[k] = v
    rec["function"] = loc.get("__name_hint")
    _LAST.clear()
    _LAST.update(rec)
'''


def write_instrumented() -> Path:
    src = (UPSTREAM / "simulation_funs_DC.py").read_text()
    for name in ("COP_2.pkl", "COP_DX.pkl", "COP_AC.pkl"):
        src = src.replace(
            f"pickle.load(open('{name}', 'rb'))",
            f"pickle.load(open(r'{UPSTREAM / name}', 'rb'))",
        )
    src = re.sub(
        r"^([ \t]*)Power_IT\s*=\s*1[ \t]*(#.*)?$",
        r"\1Power_IT = float(_POWER_IT)",
        src,
        flags=re.M,
    )
    src = src.replace("return PUE, WUE", "_record_eval(locals())\n    return PUE, WUE")
    header = (
        "# AUTO-GENERATED diagnostic copy. Nested source is unlicensed; do not redistribute.\n"
        + RECORD_FN
        + "\n"
    )
    INSTR_DIR.mkdir(parents=True, exist_ok=True)
    out = INSTR_DIR / "simulation_funs_DC_instrumented.py"
    out.write_text(header + src)
    readme = INSTR_DIR / "README.md"
    readme.write_text(
        "Generated at runtime from the nested clone for component capture and IT-load scaling tests. "
        "Not a project model. Do not copy into a public tree without a license decision.\n"
    )
    return out


def load_instrumented(power_it: float = 1.0, rewrite: bool = True, path=None):
    import importlib.util
    import sys

    if path is None:
        path = write_instrumented() if rewrite else INSTR_DIR / "simulation_funs_DC_instrumented.py"
        if not path.exists():
            path = write_instrumented()
    else:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)
    spec = importlib.util.spec_from_file_location("masanet_instrumented", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["masanet_instrumented"] = mod
    spec.loader.exec_module(mod)
    patch_cop_models(mod)
    mod._POWER_IT = float(power_it)
    return mod
