#!/usr/bin/env python3
"""Phase 2: paper/code case crosswalk + Table 3 machine-readable spec + UE.xlsx checks."""
from __future__ import annotations

import csv
import json

import pandas as pd

from common import ARCHETYPE_PARAMS, UPSTREAM, atomic_write_json, set_threads, utcnow
from followup_common import (
    FOLLOWUP,
    FOLLOWUP_DOCS,
    PAPER_CASES,
    SELECTED_CELLS,
    UE_CLIMATE_ZONES,
    active_params_for_function,
    table3_ranges,
)


def main():
    set_threads()
    FOLLOWUP.mkdir(parents=True, exist_ok=True)
    FOLLOWUP_DOCS.mkdir(parents=True, exist_ok=True)
    ue = pd.read_excel(UPSTREAM / "Simulation Results" / "UE.xlsx")
    zones = sorted(ue["Climate Zone"].dropna().unique().tolist())
    cases = sorted(int(c) for c in ue["Case"].dropna().unique().tolist())
    quant = sorted(ue["Quantile"].dropna().unique().tolist())
    n = int(len(ue))
    rows = []
    param_rows = []
    mapping_ok = True
    fns = []
    for c, meta in PAPER_CASES.items():
        fn = meta["top_level_code_function"]
        fns.append(fn)
        spec = table3_ranges(c)
        try:
            active = active_params_for_function(c)
            missing = []
        except Exception as e:
            mapping_ok = False
            active = {}
            missing = [str(e)]
        required = [n for n in ARCHETYPE_PARAMS[fn] if n not in ("T_oa", "RH_oa", "P_oa")]
        rows.append(
            {
                "paper_case": c,
                "size_class": meta["size_class"],
                "paper_cooling_configuration": meta["paper_cooling_configuration"],
                "top_level_code_function": fn,
                "shared_function_with_other_case": meta["shared_function_with_other_case"] or "",
                "humidifier_type": meta["humidifier_type"],
                "economizer_type": meta["economizer_type"],
                "chiller_type": meta["chiller_type"],
                "cooling_tower_present": meta["cooling_tower_present"],
                "paper_parameter_source": "Lei-Masanet 2022 preprint Table 2 (cases) / Table 3 (ranges); bundled UE.xlsx for 15 zones",
                "parameter_range_source": "preprint Table 3; final Elsevier PDF not OA (Unpaywall is_oa=false)",
                "expected_climate_zones": "15 zones in UE.xlsx (not preprint '16')",
                "n_required_code_inputs_excluding_climate": len(required),
                "n_active_table3_mapped": len(active),
                "missing": ";".join(missing),
                "notes": meta["notes"] or "",
                "confidence": meta["confidence"],
            }
        )
        for name, sp in spec.items():
            param_rows.append(
                {
                    "paper_case": c,
                    "code_name": name,
                    "inactive": sp["inactive"],
                    "lo_code_units": sp["lo"],
                    "hi_code_units": sp["hi"],
                    "paper_unit": sp.get("paper_unit", "as_code"),
                    "code_unit": sp.get("code_unit", "native"),
                    "required_by_function": name in required,
                    "notes": sp.get("notes", ""),
                }
            )
            if name in required and sp["inactive"]:
                mapping_ok = False
            if name in required and not sp["inactive"] and not (sp["lo"] < sp["hi"] or sp["lo"] <= sp["hi"]):
                mapping_ok = False
            if not sp["inactive"] and sp["lo"] is not None and sp["hi"] is not None and sp["lo"] > sp["hi"]:
                mapping_ok = False

    csv_path = FOLLOWUP_DOCS / "PAPER_CODE_CASE_CROSSWALK.csv"
    fields = list(rows[0].keys())
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    with (FOLLOWUP / "table3_parameter_spec.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(param_rows[0].keys()))
        w.writeheader()
        w.writerows(param_rows)

    unique_cases = len(PAPER_CASES) == 10 and set(PAPER_CASES) == set(range(1, 11))
    ue_ok = cases == list(range(1, 11)) and zones == UE_CLIMATE_ZONES and n == 300 and set(quant) == {"5th", "95th"}
    rh_note = (
        "Table 3 rows labeled RH lower/higher bound are physically reversed relative to code: "
        "the high-RH numeric range maps to RH_up (d_up) and the low-RH range to RH_lw (d_lw). "
        "Dry-bulb and dew-point lower/higher labels match T_lw/T_up and dp_lw/dp_up."
    )
    out = {
        "status": "PASS" if mapping_ok and unique_cases and ue_ok else "FAIL",
        "timestamp_utc": utcnow(),
        "final_paper_source_status": "PREPRINT_USED_JOURNAL_CLOSED",
        "journal_doi": "10.1016/j.resconrec.2022.106323",
        "unpaywall_is_oa": False,
        "preprint": "10.21203/rs.3.rs-769999/v1",
        "n_paper_cases": 10,
        "functions_used": sorted(set(fns)),
        "shared_function_pairs": [[5, 8], [7, 9]],
        "ue_xlsx": {
            "n_rows": n,
            "cases": cases,
            "climate_zones": zones,
            "quantiles": quant,
            "expected_300": n == 300,
            "matches_15_zone_authoritative_set": zones == UE_CLIMATE_ZONES,
        },
        "rh_setpoint_semantics": rh_note,
        "unit_transforms": [
            "percent table values /100 → code fractions (UPS, PD, lighting, efficiencies, SHR, windage, pcop)",
            "pump pressures kPa × 1000 → Pa",
            "fan pressures already Pa",
            "lighting large-scale 0–0.2% → 0–0.002 fraction",
        ],
        "crosswalk_csv": str(csv_path),
        "parameter_csv": str(FOLLOWUP / "table3_parameter_spec.csv"),
        "mapping_ok": mapping_ok,
        "unique_cases": unique_cases,
        "ue_ok": ue_ok,
        "selected_cells_locked_before_ue_error_look": SELECTED_CELLS,
        "selection_rule": (
            "Maximize diagnostic coverage with 6 cells: large AE/adiabatic, large WE, "
            "WC no-economizer, air-cooled or DX, hot-humid, cool/cold; prefer distinct top-level functions. "
            "Locked before comparing reproduced quantiles to UE.xlsx."
        ),
    }
    atomic_write_json(FOLLOWUP / "paper_code_crosswalk.json", out)
    print(json.dumps({"status": out["status"], "ue_rows": n, "zones": len(zones)}, indent=2))
    if out["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
