#!/usr/bin/env python3
"""V2 recovery, provenance, UE semantics, weather audit, cell disposition, RNG callsites.

Does not overwrite followup_v1. Does not run annual replications.
"""
from __future__ import annotations

import ast
import csv
import json
import os
import platform
import socket
import subprocess
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from v2_common import (  # noqa: E402
    AN,
    DOCS,
    LOCKED_CELLS,
    LOGS,
    MAN,
    PARENT,
    PY,
    PY_DC,
    RES,
    UPSTREAM,
    UPSTREAM_COMMIT,
    V1,
    WORK_ROOT,
    atomic_write_json,
    set_threads,
    sha256_file,
    utcnow,
)
from followup_common import CLIMATE_CITIES, PAPER_CASES  # noqa: E402
from common import ARCHETYPE_META, ARCHETYPE_PARAMS  # noqa: E402


def _git(cmd, cwd):
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    return (r.stdout or "").strip(), r.returncode


def recover_v1():
    cells = {}
    for c in LOCKED_CELLS:
        key = f"case{c['paper_case']}_{c['climate_zone']}"
        p = V1 / f"annual_{key}_r0.json"
        d = json.loads(p.read_text()) if p.exists() else None
        vu = (d or {}).get("vs_ue") or {}
        extra = vu.get("extra_lhs_quantile_estimates") or []
        st = vu.get("status")
        if st == "CONSISTENT_WITH_PUBLISHED_RANGE" and not extra:
            disp = "already_clearly_compatible"
        elif st == "CONSISTENT_WITH_PUBLISHED_RANGE":
            disp = "compatible_after_extra_lhs"
        elif st == "INCONSISTENT":
            disp = "failed"
        elif st is None:
            disp = "missing_unrun"
        else:
            disp = "marginal"
        cells[key] = {
            "paper_case": c["paper_case"],
            "climate_zone": c["climate_zone"],
            "v1_status": st,
            "disposition_before_v2": disp,
            "path": str(p),
            "exists": p.exists(),
            "inside_first_design_bootstrap": vu.get("published_inside_first_design_bootstrap"),
            "n_extra_lhs": len(extra),
            "reproduced": vu.get("reproduced"),
            "published": vu.get("published"),
            "delta_hat_minus_published": vu.get("delta_hat_minus_published"),
            "fn": PAPER_CASES[c["paper_case"]]["top_level_code_function"],
            "stochastic_helpers": ARCHETYPE_META[PAPER_CASES[c["paper_case"]]["top_level_code_function"]][
                "stochastic_helpers"
            ],
        }
    status = json.loads((V1 / "FOLLOWUP_V1_STATUS.json").read_text()) if (V1 / "FOLLOWUP_V1_STATUS.json").exists() else None
    gate = json.loads((V1 / "MASANET_ANNUAL_CLOSURE_STATUS.json").read_text()) if (V1 / "MASANET_ANNUAL_CLOSURE_STATUS.json").exists() else None
    cmp_ = json.loads((V1 / "annual_selected_comparison.json").read_text())
    rng = json.loads((V1 / "annual_rng.json").read_text())
    nb = json.loads((V1 / "notebook_pue_sweep.json").read_text())
    front = json.loads((V1 / "FRONTIER_CLOSURE_STATUS.json").read_text())
    slurm = json.loads((WORK_ROOT / "manifests" / "SLURM_FOLLOWUP_V1.json").read_text())
    rec = {
        "timestamp_utc": utcnow(),
        "repo_head_now": _git(["git", "rev-parse", "HEAD"], PARENT)[0],
        "repo_branch_now": _git(["git", "rev-parse", "--abbrev-ref", "HEAD"], PARENT)[0],
        "git_status_short_now": _git(["git", "status", "--short"], PARENT)[0],
        "v1_overall_status": (status or {}).get("overall_status"),
        "v1_annual_reproduction_status": (cmp_ or {}).get("status"),
        "v1_gate": (gate or {}).get("status"),
        "v1_proceed_to_adapter": (gate or {}).get("proceed_to_adapter"),
        "passed": [
            "paper_code_crosswalk",
            "parameter_ranges",
            "weather_8760_locked_zones",
            "annual_smoke_short",
            "annual_smoke_full_execution",
            "paper_aggregation_identity",
            "annual_rng_on_case1_1A_immaterial_zero_spread",
            "frontier_missing_time_correction_closed",
            "cells_2x1A_7x8_10x5A_consistent_under_v1_5th95th_bootstrap",
        ],
        "partial": [
            "notebook_pue_NOTEBOOK_VALUE_NOT_REACHED_WUE_exact",
            "final_journal_PDF_not_OA_preprint_used_for_Table3",
        ],
        "failed": [
            "annual_gate_FAIL",
            "cells_1x1A_2x8_5x2A_INCONSISTENT_under_v1_5th95th_plus_4_extra_LHS",
        ],
        "blocked": ["adapter_tests", "prineville_2022_weather_smoke"],
        "never_completed_due_to_afterok": {
            "PROJECT_ADAPTER_TEST": "21394445 CANCELLED",
            "PRINEVILLE_WEATHER_SMOKE": "21394446 CANCELLED",
            "FINALIZE_as_separate_job": "21394447 CANCELLED; gate still wrote FOLLOWUP_V1_STATUS.json",
        },
        "v1_slurm": {
            "PREFLIGHT": {"id": "21394438", "state": "COMPLETED", "exit": "0:0", "elapsed": "00:00:36"},
            "NOTEBOOK": {"id": "21394439", "state": "COMPLETED", "exit": "0:0", "elapsed": "00:06:58"},
            "FRONTIER": {"id": "21394440", "state": "COMPLETED", "exit": "0:0", "elapsed": "00:00:51"},
            "ANNUAL_SMOKE": {"id": "21394441", "state": "COMPLETED", "exit": "0:0", "elapsed": "07:07:58"},
            "ANNUAL_SELECTED_ARRAY": {
                "id": "21394442",
                "tasks": {
                    "1": {"cell": "2x8", "elapsed": "02:45:07", "state": "COMPLETED"},
                    "2": {"cell": "2x1A", "elapsed": "00:51:25", "state": "COMPLETED"},
                    "3": {"cell": "5x2A", "elapsed": "04:07:22", "state": "COMPLETED"},
                    "4": {"cell": "7x8", "elapsed": "00:05:51", "state": "COMPLETED"},
                    "5": {"cell": "10x5A", "elapsed": "00:04:08", "state": "COMPLETED"},
                },
            },
            "ANNUAL_RNG": {"id": "21394443", "state": "COMPLETED", "exit": "0:0", "elapsed": "01:05:26"},
            "ANNUAL_GATE": {"id": "21394444", "state": "FAILED", "exit": "2:0", "elapsed": "00:00:08"},
        },
        "notebook_sweep": {
            "status": nb.get("status"),
            "n_seeds": nb.get("n_seeds"),
            "pue_min": nb["PUE"]["min"],
            "pue_max": nb["PUE"]["max"],
            "notebook_pue": nb.get("notebook_pue"),
            "wue_unique": nb["WUE"]["unique_rounded_12"],
            "path": str(V1 / "notebook_pue_sweep.json"),
            "do_not_rerun_0_9999": True,
        },
        "frontier": front,
        "annual_rng_v1": {
            "status": rng.get("status"),
            "cell": rng.get("cell"),
            "caveat": (
                "V1 RNG test used case 1 / PUE_WUE_AE_Chiller, which has no live np.random helper. "
                "Zero seed spread is expected for that architecture and does not close RNG for Chiller_system cells."
            ),
            "path": str(V1 / "annual_rng.json"),
        },
        "cells": cells,
        "v1_comparison_path": str(V1 / "annual_selected_comparison.json"),
        "v1_status_path": str(V1 / "FOLLOWUP_V1_STATUS.json"),
        "v1_summary_path": str(WORK_ROOT / "docs" / "followup_v1" / "FOLLOWUP_V1_SUMMARY.md"),
        "did_not_overwrite_v1": True,
        "did_read_meta_2023_2024_water": False,
        "slurm_manifest": slurm.get("job_ids"),
    }
    atomic_write_json(MAN / "V1_RECOVERY.json", rec)
    return rec


def cell_disposition(rec):
    # Positive control chosen from V1 only, before V2 annual results.
    # case 7 × 8: CONSISTENT, extra_n=0, first-design bootstrap contained published endpoints,
    # air-cooled (distinct from the three failed water-cooled cells).
    pos = "case7_8"
    failed = [k for k, v in rec["cells"].items() if v["disposition_before_v2"] == "failed"]
    compatible = [k for k, v in rec["cells"].items() if v["disposition_before_v2"] == "already_clearly_compatible"]
    out = {
        "timestamp_utc": utcnow(),
        "written_before_v2_annual_results": True,
        "selection_locked_before_v1_errors": True,
        "cells": rec["cells"],
        "full_50_publication_scale_replications_required": failed,
        "no_full_50_rerun_clearly_compatible": [k for k in compatible if k != pos],
        "positive_control": {
            "cell": pos,
            "n_replications": 10,
            "justification_from_v1_only": (
                "V1 first 50-LHS design already placed all four published 5th/95th endpoints inside the "
                "bootstrap interval of the quantile estimator (extra_n=0). Architecture PUE_WUE_AIRChiller "
                "is distinct from the three V1-failed water-cooled cells."
            ),
        },
        "v2_rng_cells_chosen_before_v2_rng_outcomes": {
            "rng_active_problematic": {
                "cell": "case5_2A",
                "fn": "PUE_WUE_Chiller",
                "reason": "Live Chiller_system np.random.uniform(d_sa) per evaluation; V1 annual INCONSISTENT.",
            },
            "contrasting_architecture": {
                "cell": "case1_1A",
                "fn": "PUE_WUE_AE_Chiller",
                "reason": (
                    "No live np.random in Air_side_economizer / AE_Chiller path (commented T_sa draws only in other helpers). "
                    "V1 RNG spread was exactly 0 on this cell. Contrasts Chiller_system stochasticity; still a V1-failed annual cell."
                ),
            },
        },
        "v1_estimator_note": (
            "V1 compared UE.xlsx 5th/95th labels to np.quantile(..., 0.05/0.95). V2 re-audits that those labels "
            "are the paper's published range estimator, then repeats publication-scale 50-LHS replications."
        ),
    }
    atomic_write_json(MAN / "CELL_DISPOSITION_BEFORE_V2.json", out)
    return out


def reference_semantics():
    ue_path = UPSTREAM / "Simulation Results" / "UE.xlsx"
    df = pd.read_excel(ue_path)
    csv_path = AN / "published_reference_table.csv"
    df.to_csv(csv_path, index=False)
    always_pue = True
    always_wue = True
    for (_, _), g in df.groupby(["Case", "Climate Zone"]):
        q = {str(r["Quantile"]): r for _, r in g.iterrows()}
        if float(q["5th"]["PUE"]) >= float(q["95th"]["PUE"]):
            always_pue = False
        if float(q["5th"]["WUE"]) >= float(q["95th"]["WUE"]):
            always_wue = False
    # paper quotes (preprint; Elsevier PDF not in tree / Unpaywall closed)
    semantics = {
        "timestamp_utc": utcnow(),
        "ue_xlsx": str(ue_path),
        "sha256": sha256_file(ue_path),
        "sheets": ["Sheet1"],
        "columns": list(df.columns),
        "n_rows": int(len(df)),
        "cases": sorted(int(x) for x in df["Case"].unique()),
        "climate_zones": sorted(df["Climate Zone"].unique().tolist()),
        "quantile_labels_in_workbook": sorted(df["Quantile"].unique().tolist()),
        "units_in_workbook": "not labeled in columns; paper: PUE dimensionless, WUE L/kWh onsite use / IT electricity",
        "n_case_climate": 150,
        "n_records_per_case_climate": 2,
        "always_5th_lt_95th_PUE": always_pue,
        "always_5th_lt_95th_WUE": always_wue,
        "generation_code_in_public_repo": False,
        "generation_code_search": "no UE.xlsx writer, no quantile dump, no LHS annual loop in nested clone or notebooks",
        "final_journal_article": {
            "doi": "10.1016/j.resconrec.2022.106323",
            "pdf_in_workspace": False,
            "unpaywall_is_oa_as_of_v1": False,
            "used_instead": "Research Square preprint rs.3.rs-769999/v1 + workbook labels",
        },
        "paper_definition": {
            "n_lhs": 50,
            "distributions": "uniform over Table 3 ranges",
            "aggregation": "annual average of hourly PUE/WUE under each sampled facility scenario",
            "practical_minimum": "preprint §4.3: 'represented by the 5th quantiles of the simulation results'",
            "upper_label_in_workbook": "95th",
            "not_min_max": (
                "Workbook column is Quantile with values 5th and 95th; preprint explicitly names 5th quantiles "
                "as practical minima. Min/max of 50 scenarios is NOT the labeled statistic."
            ),
            "remaining_uncertainty": (
                "Exact numpy/scipy quantile interpolation (linear vs nearest, type 7 vs Hyndman) and original LHS "
                "seed/library are not in the public code. Elsevier typeset wording was not available; preprint + "
                "UE.xlsx labels agree on 5th/95th."
            ),
        },
        "estimator_for_v2": {
            "lower": "np.quantile(annual_values, 0.05)  # linear, numpy default",
            "upper": "np.quantile(annual_values, 0.95)",
            "numpy_interpolation": "linear (default)",
            "not_min_max": True,
        },
        "reference_csv": str(csv_path),
        "immutable": True,
        "never_used_as_calibration_target": True,
    }
    atomic_write_json(MAN / "REFERENCE_SEMANTICS.json", semantics)
    return semantics


def weather_audit():
    weather_man = json.loads((WORK_ROOT / "manifests" / "FOLLOWUP_V1_WEATHER.json").read_text())
    rows = []
    for art in weather_man["artifacts"]:
        z = art["climate_zone"]
        p = Path(art["path"])
        parsed = weather_man["parsed"][z]
        loc = parsed["location_header"]
        leap = False
        if p.exists():
            text = p.read_text(errors="replace")
            n_feb29 = sum(1 for ln in text.splitlines()[8:] if ln.startswith(tuple()) or False)
            # EPW month,day fields
            n_feb29 = 0
            data_rows = 0
            hours = set()
            for ln in text.splitlines()[8:]:
                if not ln.strip():
                    continue
                parts = ln.split(",")
                if len(parts) < 10:
                    continue
                data_rows += 1
                mo, dy, hr = int(float(parts[1])), int(float(parts[2])), int(float(parts[3]))
                if mo == 2 and dy == 29:
                    n_feb29 += 1
                hours.add((mo, dy, hr))
            leap = n_feb29 > 0
        chicago_ok = True
        if z == "5A":
            chicago_ok = (
                "Chicago" in loc
                and "725300" in loc
                and "TMY3" in loc
                and art["epw_id"] == "USA_IL_Chicago-OHare.Intl.AP.725300_TMY3"
            )
        rows.append(
            {
                "climate_zone": z,
                "representative_city": art["city"],
                "doe_iecc_city_identity": CLIMATE_CITIES[z]["city"],
                "epw_id": art["epw_id"],
                "wmo": art["wmo"],
                "path": art["path"],
                "sha256": sha256_file(p),
                "bytes": p.stat().st_size if p.exists() else None,
                "location_header": loc,
                "n_rows": parsed["n_rows"],
                "exactly_8760": parsed["n_rows"] == 8760,
                "feb29_rows": n_feb29 if p.exists() else None,
                "leap_contamination": leap,
                "units": parsed["units"],
                "T_oa_C_range": parsed["T_oa_C_range"],
                "RH_oa_pct_range": parsed["RH_oa_pct_range"],
                "P_oa_Pa_range": parsed["P_oa_Pa_range"],
                "timestamp_interpretation": (
                    "Hourly TMY sequence; model uses T, RH, P only. Calendar timestamps are not used by PUE_WUE_*."
                ),
                "chicago_is_intended_ohare_tmy3_wmo725300": chicago_ok if z == "5A" else None,
                "source_note": weather_man["city_source"],
                "parquet": str(V1 / f"weather_{z}.parquet"),
                "parquet_sha256": sha256_file(V1 / f"weather_{z}.parquet"),
            }
        )
    out = {
        "timestamp_utc": utcnow(),
        "did_not_download_substitute": True,
        "v1_weather_manifest": str(WORK_ROOT / "manifests" / "FOLLOWUP_V1_WEATHER.json"),
        "chicago_nrel_replacement": {
            "why_used_in_v1": "EnergyPlus S3 zip 404; NREL EnergyPlus weather tree raw EPW used",
            "identity_check": "LOCATION header Chicago Ohare Intl Ap, TMY3, WMO 725300 matches intended DOE 5A city",
            "not_merely_convenient_wrong_station": True,
            "sha256": sha256_file(WORK_ROOT / "external" / "energyplus_tmy" / "5A_USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw"),
        },
        "zones": rows,
        "status": "PASS" if all(r["exactly_8760"] and not r["leap_contamination"] for r in rows) else "FAIL",
    }
    atomic_write_json(MAN / "WEATHER_AUDIT.json", out)
    return out


def rng_callsite_audit():
    src = (UPSTREAM / "simulation_funs_DC.py").read_text()
    tree = ast.parse(src)
    lines = src.splitlines()
    fn_by_line = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            fn_by_line[node.lineno] = node.name
    ordered = sorted(fn_by_line)
    def fn_at(lineno):
        cur = None
        for ln in ordered:
            if ln <= lineno:
                cur = fn_by_line[ln]
            else:
                break
        return cur
    sites = []
    for i, ln in enumerate(lines, 1):
        if "np.random" in ln:
            live = not ln.strip().startswith("#")
            sites.append(
                {
                    "line": i,
                    "function": fn_at(i),
                    "live": live,
                    "code": ln.strip(),
                    "output_affected": "d_sa (supply-air humidity) if live; commented T_sa draws are inactive",
                    "frequency": "per helper call; helpers may be invoked multiple times per hourly evaluation",
                    "deterministic_if_global_np_seed_fixed": True,
                }
            )
    used_by = {
        "Air_side_economizer_colo": ["PUE_WUE_AE_Chiller_Colo"],
        "Chiller_system": [
            "PUE_WUE_Chiller_Watereconomier",
            "PUE_WUE_WE_Chiller_Colo",
            "PUE_WUE_Chiller",
            "PUE_WUE_AIRChiller",
        ],
        "Chiller_system_DX": ["PUE_WUE_DX"],
        "Air_side_economizer": [],
    }
    out = {
        "timestamp_utc": utcnow(),
        "source": str(UPSTREAM / "simulation_funs_DC.py"),
        "source_sha256": sha256_file(UPSTREAM / "simulation_funs_DC.py"),
        "did_not_alter_upstream": True,
        "sites": sites,
        "helpers_used_by_top_level": used_by,
        "locked_cells": {
            "case1_1A": {"fn": "PUE_WUE_AE_Chiller", "live_np_random": False},
            "case2_8": {"fn": "PUE_WUE_Chiller_Watereconomier", "live_np_random": True, "helper": "Chiller_system"},
            "case2_1A": {"fn": "PUE_WUE_Chiller_Watereconomier", "live_np_random": True, "helper": "Chiller_system"},
            "case5_2A": {"fn": "PUE_WUE_Chiller", "live_np_random": True, "helper": "Chiller_system"},
            "case7_8": {"fn": "PUE_WUE_AIRChiller", "live_np_random": True, "helper": "Chiller_system"},
            "case10_5A": {"fn": "PUE_WUE_DX", "live_np_random": True, "helper": "Chiller_system_DX"},
        },
        "v1_rng_limitation": "V1 annual RNG experiment held a case-1 facility vector; that path has no live np.random.",
    }
    atomic_write_json(AN / "RNG_CALLSITE_AUDIT.json", out)
    return out


def provenance():
    head, _ = _git(["git", "rev-parse", "HEAD"], PARENT)
    branch, _ = _git(["git", "rev-parse", "--abbrev-ref", "HEAD"], PARENT)
    status, _ = _git(["git", "status", "--short"], PARENT)
    up, _ = _git(["git", "rev-parse", "HEAD"], UPSTREAM)
    hashes = {}
    for p in [
        UPSTREAM / "simulation_funs_DC.py",
        UPSTREAM / "Simulation Results" / "UE.xlsx",
        UPSTREAM / "COP_2.pkl",
        UPSTREAM / "COP_AC.pkl",
        UPSTREAM / "COP_DX.pkl",
        WORK_ROOT / "external" / "energyplus_tmy" / "1A_USA_FL_Miami.Intl.AP.722020_TMY3.epw",
        WORK_ROOT / "external" / "energyplus_tmy" / "2A_USA_TX_Houston-Bush.Intercontinental.AP.722430_TMY3.epw",
        WORK_ROOT / "external" / "energyplus_tmy" / "5A_USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw",
        WORK_ROOT / "external" / "energyplus_tmy" / "8_USA_AK_Fairbanks.Intl.AP.702610_TMY3.epw",
        WORK_ROOT / "scripts" / "followup_common.py",
        WORK_ROOT / "scripts" / "followup_annual.py",
        Path(__file__),
    ]:
        hashes[str(p)] = {"sha256": sha256_file(p), "bytes": p.stat().st_size if p.exists() else None}
    for p in sorted((WORK_ROOT / "scripts" / "final_repro_v2").glob("*.py")):
        hashes[str(p)] = {"sha256": sha256_file(p), "bytes": p.stat().st_size}
    # package versions under PYTHONNOUSERSITE
    pkg = {}
    import numpy, pandas, sklearn, scipy

    pkg = {
        "numpy": numpy.__version__,
        "pandas": pandas.__version__,
        "sklearn": sklearn.__version__,
        "scipy": scipy.__version__,
        "scipy_file": scipy.__file__,
        "lhs": "scipy.stats.qmc.LatinHypercube",
        "lhs_init_signature": "LatinHypercube(d, *, centered=False, seed=None)  # scipy 1.7.3",
    }
    try:
        import CoolProp

        pkg["CoolProp"] = CoolProp.__version__
    except Exception as e:
        pkg["CoolProp"] = f"MISSING {e}"
    conda_list = subprocess.run(
        ["conda", "list", "-n", "masanet_lei"], capture_output=True, text=True
    ).stdout
    (MAN / "conda_list_masanet_lei.txt").write_text(conda_list)
    dc_list = subprocess.run(
        ["conda", "list", "-n", "dc_externalities"], capture_output=True, text=True
    ).stdout
    (MAN / "conda_list_dc_externalities.txt").write_text(dc_list)
    out = {
        "timestamp_utc": utcnow(),
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "repo_head": head,
        "repo_branch": branch,
        "git_status_short": status,
        "upstream_commit": up,
        "upstream_commit_expected": UPSTREAM_COMMIT,
        "python_scientific": {
            "requested_by_user": str(PY_DC),
            "dc_externalities_cannot_load_model": "sklearn/joblib missing; CoolProp missing; numpy 2.4 vs COP pickles",
            "used_for_science": str(PY),
            "reason": (
                "dc_externalities cannot import CoolProp or a working sklearn. Using masanet_lei with "
                "PYTHONNOUSERSITE=1 (scipy 1.7.3, sklearn 1.0.2) matching V1 cluster jobs. "
                "Without PYTHONNOUSERSITE, ~/.local scipy 1.13.1 shadows the env."
            ),
            "PYTHONNOUSERSITE": os.environ.get("PYTHONNOUSERSITE"),
            "version": sys.version.split()[0],
            "packages": pkg,
        },
        "sklearn_shim": {
            "affected_model": "COP_AC.pkl",
            "missing__y_train_std": True,
            "shim_sets_to_1": True,
            "reason": "normalize_y is False; identity scale",
            "pickle_mutated_on_disk": False,
        },
        "hashes": hashes,
        "did_not_mutate_pickles_or_ue_or_upstream_or_weather": True,
    }
    atomic_write_json(MAN / "PROVENANCE.json", out)
    return out


def lhs_spec():
    out = {
        "timestamp_utc": utcnow(),
        "paper": "McKay et al. 2000 cited; 50 uniform LHS samples of Table 3 parameters per case×climate; original seed/library not in public code",
        "public_repo_has_lhs_driver": False,
        "closest_recoverable_procedure": {
            "library": "scipy.stats.qmc.LatinHypercube",
            "version": "1.7.3 under PYTHONNOUSERSITE masanet_lei",
            "centered": False,
            "scramble": "not a scipy 1.7 parameter; do not use scipy>=1.8 default scramble=True",
            "optimization": None,
            "scaling": "scipy.stats.qmc.scale(u, lows, highs) independent per dimension",
            "transformations_before_call": "Table 3 percent→fraction, kPa→Pa, RH label swap to RH_up/RH_lw as in followup_common.table3_ranges",
            "dependencies_between_parameters": "none imposed beyond per-case N/A exclusions",
            "categorical": "none; inactive equipment not sampled",
        },
        "exact_original_realization_unavailable": True,
        "exact_numerical_equality_not_expected": True,
        "will_not_search_seeds_to_match_UE": True,
        "v1_used": "LatinHypercube(d, seed=seed) then scale; same as this spec when scipy is 1.7.3",
    }
    atomic_write_json(MAN / "LHS_PROCEDURE.json", out)
    return out


def freeze_task_manifest(disp):
    """All V2 LHS/internal seeds frozen BEFORE any V2 annual result is inspected."""
    import numpy as np

    tasks = []
    tid = 0
    # 50 reps for each failed cell
    plan = [
        ("case1_1A", 1, "1A", 50, "failed_full"),
        ("case2_8", 2, "8", 50, "failed_full"),
        ("case5_2A", 5, "2A", 50, "failed_full"),
        ("case7_8", 7, "8", 10, "positive_control"),
    ]
    ss = np.random.SeedSequence(20260901)
    child = ss.spawn(200)
    k = 0
    for name, case, zone, nrep, role in plan:
        for r in range(nrep):
            rng = np.random.default_rng(child[k])
            k += 1
            lhs_seed = int(rng.integers(1, 2**31 - 1))
            internal_seed = int(rng.integers(1, 2**31 - 1))
            facility_internal_seeds = [int(internal_seed + i * 10007) for i in range(50)]
            tasks.append(
                {
                    "task_id": tid,
                    "cell": name,
                    "paper_case": case,
                    "climate_zone": zone,
                    "replication": r,
                    "n_lhs": 50,
                    "n_hours": 8760,
                    "lhs_seed": lhs_seed,
                    "internal_stream_seed": internal_seed,
                    "internal_seed_formula": "internal_stream_seed + facility_sample_id * 10007",
                    "facility_internal_seeds": facility_internal_seeds,
                    "role": role,
                }
            )
            tid += 1
    man = {
        "timestamp_utc": utcnow(),
        "frozen_before_results": True,
        "n_tasks": len(tasks),
        "n_scenario_years": len(tasks) * 50,
        "n_hourly_evals": len(tasks) * 50 * 8760,
        "seed_root": 20260901,
        "tasks": tasks,
        "will_not_modify_after_results_visible": True,
        "internal_rng_note": (
            "Each of the 50 facility-years in a replication is seeded once at the start of the 8760-hour loop; "
            "np.random then advances naturally within the year. Seeds frozen before any V2 annual result."
        ),
    }
    tasks_only = json.dumps({"seed_root": 20260901, "tasks": tasks}, sort_keys=True, separators=(",", ":"))
    import hashlib

    man["tasks_sha256"] = hashlib.sha256(tasks_only.encode()).hexdigest()
    atomic_write_json(MAN / "TASK_MANIFEST.json", man)
    (MAN / "TASK_MANIFEST.sha256").write_text(man["tasks_sha256"] + "\n")
    # RNG experiment seeds also frozen now
    rng_ss = np.random.SeedSequence(20260902)
    rng_child = rng_ss.spawn(2)
    rng_plan = {
        "timestamp_utc": utcnow(),
        "frozen_before_rng_outcomes": True,
        "cells": [
            {
                "cell": "case5_2A",
                "paper_case": 5,
                "climate_zone": "2A",
                "n_facility_vectors": 20,
                "n_internal_seeds": 8,
                "facility_lhs_seed": int(np.random.default_rng(rng_child[0]).integers(1, 2**31 - 1)),
                "internal_seeds": [int(x) for x in np.random.default_rng(rng_child[0]).integers(1, 2**31 - 1, size=8)],
                "range_rerun_lhs_seed": int(np.random.default_rng(rng_child[0]).integers(1, 2**31 - 1)),
                "range_rerun_n_internal_seeds": 8,
            },
            {
                "cell": "case1_1A",
                "paper_case": 1,
                "climate_zone": "1A",
                "n_facility_vectors": 20,
                "n_internal_seeds": 8,
                "facility_lhs_seed": int(np.random.default_rng(rng_child[1]).integers(1, 2**31 - 1)),
                "internal_seeds": [int(x) for x in np.random.default_rng(rng_child[1]).integers(1, 2**31 - 1, size=8)],
            },
        ],
        "thresholds_are_project_rules_not_lei_masanet": {
            "f_rng_lt_10pct": "RNG small/secondary",
            "f_rng_10_to_25pct": "material but secondary → possible PARTIAL",
            "f_rng_gt_25pct": "potentially problematic",
        },
    }
    atomic_write_json(MAN / "RNG_TASK_MANIFEST.json", rng_plan)
    (MAN / "RNG_TASK_MANIFEST.sha256").write_text(sha256_file(MAN / "RNG_TASK_MANIFEST.json") + "\n")
    man["sha256_sidecar"] = (MAN / "TASK_MANIFEST.sha256").read_text().strip()
    return man


def main():
    set_threads()
    for p in (MAN, AN, RES, LOGS, DOCS):
        p.mkdir(parents=True, exist_ok=True)
    rec = recover_v1()
    disp = cell_disposition(rec)
    reference_semantics()
    weather_audit()
    rng_callsite_audit()
    provenance()
    lhs_spec()
    freeze_task_manifest(disp)
    print(json.dumps({"v1_gate": rec["v1_gate"], "failed_cells": disp["full_50_publication_scale_replications_required"], "n_tasks": json.loads((MAN / "TASK_MANIFEST.json").read_text())["n_tasks"]}, indent=2))


if __name__ == "__main__":
    main()
