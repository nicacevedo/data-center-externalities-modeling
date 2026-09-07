"""Preregistered scientific summarizer. Frozen BEFORE any ANALYSIS seed is touched.

Orchestration rules encoded here (not in design_v2.yaml, so DESIGN_HASH is unchanged):

- G3 evaluated models: S6a/S6b cells -> N; S8 cells -> L; inversion cells -> N.
- G3 falsification is evaluated per required cell, then combined (oracle cannot compensate).
- G2_RAW is performance before falsification; NETWORK_SUPPORT_FINAL applies G3 override.
- Canonical strong-edge F1 column is strong_edge_undirected_f1, alias edge_f1.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from io import StringIO
from pathlib import Path

import numpy as np

from .design import MODULE_ROOT, design_hash, code_hash, seed_list, seed_pool_hash
from .evaluation import _nanmean, _nanmedian

OUTPUTS = MODULE_ROOT / "outputs"
FIXTURE_DIR = MODULE_ROOT / "tests" / "fixtures"
SUMMARIZER_OUT = OUTPUTS / "summarizer"
ANALYSIS_OUT = OUTPUTS / "analysis"
PROVENANCE = OUTPUTS / "provenance"

ESTIMATED = "ESTIMATED"
NOT_ESTIMABLE = "NOT_ESTIMABLE"
FIT_FAILED = "FIT_FAILED"
ESTIMATED_FAILED_GATE = "ESTIMATED_FAILED_GATE"
ESTIMATED_PASSED_GATE = "ESTIMATED_PASSED_GATE"

SUPPORTED = "SUPPORTED"
CONDITIONALLY_SUPPORTED_BUT_NOT_ROBUSTLY_ESTIMABLE = (
    "CONDITIONALLY_SUPPORTED_BUT_NOT_ROBUSTLY_ESTIMABLE"
)
NOT_SUPPORTED = "NOT_SUPPORTED"

# Frozen G3 model assignment. Making the already-stated scientific intent executable.
# S6 null-network falsification is a network (N) test. S8 placebo is a local (L) test.
# Prediction/intervention inversion on G2 cells is a network (N) test.
G3_CELL_EVALUATED_MODEL = {
    "G3R1": "N",
    "G3R2": "N",
    "G3R1b": "N",
    "G3R2b": "N",
    "G3R3": "L",
    "G3R4": "L",
    "G2R1": "N",
    "G2R2": "N",
    "G2R3": "N",
    "G2R4": "N",
}
G3_ORACLE_CELLS = {"G3R2", "G3R2b"}
CANONICAL_EDGE_F1 = "strong_edge_undirected_f1"
EDGE_F1_ALIAS = "edge_f1"

NONINFERENTIAL_BANNER = (
    "NON-INFERENTIAL. This summary was produced from fixtures or SMOKE seeds. "
    "It must not be used to set thresholds, choose regimes, or make scientific claims."
)


def g3_evaluated_model(cell_id: str) -> str:
    if cell_id not in G3_CELL_EVALUATED_MODEL:
        raise KeyError(f"no frozen G3 evaluated model for cell {cell_id}")
    return G3_CELL_EVALUATED_MODEL[cell_id]


def f1_column(record: dict | None = None) -> str:
    if record is not None and CANONICAL_EDGE_F1 in record:
        return CANONICAL_EDGE_F1
    if record is not None and EDGE_F1_ALIAS in record:
        return EDGE_F1_ALIAS
    return CANONICAL_EDGE_F1


def _f1_value(record: dict) -> float:
    raw = record.get(CANONICAL_EDGE_F1, record.get(EDGE_F1_ALIAS, np.nan))
    try:
        return float(raw)
    except (TypeError, ValueError):
        return np.nan


def load_records(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        lines = [ln for ln in handle if not ln.startswith("#")]
    reader = csv.DictReader(StringIO("".join(lines)))
    records = []
    for row in reader:
        parsed = {}
        for key, value in row.items():
            if value is None or value == "":
                parsed[key] = np.nan
                continue
            if value in ("True", "False"):
                parsed[key] = value == "True"
                continue
            # Integer strings (including uint64 seeds) must not pass through float:
            # IEEE-754 cannot represent all 64-bit identifiers exactly.
            if value.lstrip("+-").isdigit():
                parsed[key] = int(value)
                continue
            try:
                parsed[key] = float(value)
            except (TypeError, ValueError):
                parsed[key] = value
        records.append(parsed)
    return records


def _status(record: dict, model: str) -> str:
    raw = str(record.get(f"estimability_status_{model}", "") or "")
    if raw in (NOT_ESTIMABLE, FIT_FAILED, ESTIMATED):
        return raw
    if raw in ("NO_ADMISSIBLE_ROWS", "MODEL_NOT_APPLICABLE", "UNDERDETERMINED", "PARTIAL"):
        return NOT_ESTIMABLE
    if raw == "ESTIMABLE":
        return ESTIMATED
    estimable = record.get(f"estimable_{model}", np.nan)
    try:
        if float(estimable) == 1.0:
            return ESTIMATED
    except (TypeError, ValueError):
        pass
    return NOT_ESTIMABLE


def aggregate_cell(records: list[dict], model: str, metric: str) -> dict:
    """Median over replicates that are ESTIMATED. NOT_ESTIMABLE is retained as a rate."""
    statuses = [_status(r, model) for r in records]
    n = len(records)
    n_not = sum(s == NOT_ESTIMABLE for s in statuses)
    n_fail = sum(s == FIT_FAILED for s in statuses)
    n_est = sum(s == ESTIMATED for s in statuses)
    values = [r.get(metric, np.nan) for r, s in zip(records, statuses) if s == ESTIMATED]
    return {
        "n_replicates": n,
        "n_not_estimable": n_not,
        "n_fit_failed": n_fail,
        "n_estimated": n_est,
        "estimability_rate": n_est / n if n else np.nan,
        "not_estimable_rate": n_not / n if n else np.nan,
        "fit_failure_rate": n_fail / n if n else np.nan,
        "median": _nanmedian(values),
        "mean": _nanmean(values),
        "q10": float(np.nanquantile(np.asarray(values, float), 0.10)) if values else np.nan,
        "q90": float(np.nanquantile(np.asarray(values, float), 0.90)) if values else np.nan,
    }


def _median_metric(records: list[dict], column: str) -> float:
    values = [r.get(column, np.nan) for r in records]
    return _nanmedian(values)


def _best_simple_nire(records: list[dict]) -> float:
    medians = [
        _median_metric(records, f"nire_persistent_step_h26_{m}")
        for m in ("B0", "L", "S")
    ]
    finite = [v for v in medians if np.isfinite(v)]
    return min(finite) if finite else np.nan


def _best_simple_rmse(records: list[dict]) -> float:
    medians = [_median_metric(records, f"rmse_test_{m}") for m in ("B0", "L", "S")]
    finite = [v for v in medians if np.isfinite(v)]
    return min(finite) if finite else np.nan


def _criterion_value(cell_records: list[dict], model: str, crit: dict) -> tuple[float, bool]:
    """Return (value, skip). skip=True means the criterion is owned elsewhere (SGI_G0)."""
    cid = str(crit.get("id", ""))
    statistic = str(crit.get("statistic", ""))
    column = crit.get("metric_column")
    if column == "edge_f1" or column == CANONICAL_EDGE_F1:
        values = [_f1_value(r) for r in cell_records if _status(r, model) == ESTIMATED]
        return _nanmedian(values), False
    if column:
        return aggregate_cell(cell_records, model, column)["median"], False
    if statistic.startswith("max_over_seeds") or statistic.startswith("min_over_seeds"):
        return np.nan, True
    if cid == "G1_sign" or "beta_hat_Q < 0" in statistic:
        estimated = [r for r in cell_records if _status(r, model) == ESTIMATED]
        flags = [float(r.get("beta_q_hat_mean_L", np.nan)) < 0.0 for r in estimated]
        return (float(np.mean(flags)) if flags else np.nan), False
    if cid == "G1_stability_blowup" or "max_abs_protected_prediction" in statistic:
        flags = [
            float(r.get(f"max_abs_protected_prediction_{model}", 0.0) or 0.0) > 1000.0
            for r in cell_records
        ]
        return (float(np.mean(flags)) if flags else np.nan), False
    if cid == "G1_stability_vs_B0":
        rmse_m = aggregate_cell(cell_records, model, f"rmse_test_{model}")["median"]
        rmse_b0 = _median_metric(cell_records, "rmse_test_B0")
        if not (np.isfinite(rmse_m) and np.isfinite(rmse_b0) and rmse_b0 > 0):
            return np.nan, False
        return rmse_m / rmse_b0, False
    if cid == "G2_intervention_gain":
        best = _best_simple_nire(cell_records)
        nire_n = aggregate_cell(cell_records, "N", "nire_persistent_step_h26_N")["median"]
        if not (np.isfinite(best) and best > 0 and np.isfinite(nire_n)):
            return np.nan, False
        return (best - nire_n) / best, False
    if cid == "G2_strong_edge_f1" or "strong_edge_undirected_f1" in statistic:
        values = [_f1_value(r) for r in cell_records if _status(r, "N") == ESTIMATED]
        return _nanmedian(values), False
    if cid == "G2_masked_node_no_collapse":
        masked = aggregate_cell(cell_records, "N", "masked_node_nmpe_N")["median"]
        intact = aggregate_cell(cell_records, "N", "observed_node_nmpe_N")["median"]
        if not (np.isfinite(masked) and np.isfinite(intact) and intact > 0):
            return np.nan, False
        return masked / intact, False
    return np.nan, False


def classify_gate_cell(
    cell_records: list[dict],
    model: str,
    criteria: list[dict],
) -> dict:
    """Per-cell gate classification. NOT_ESTIMABLE in a required cell fails that cell."""
    if not cell_records:
        return {
            "state": NOT_ESTIMABLE,
            "reason": "no_records",
            "pass": False,
            "metrics_pass": False,
            "support_status": NOT_ESTIMABLE,
        }
    statuses = [_status(r, model) for r in cell_records]
    n_est = sum(s == ESTIMATED for s in statuses)
    n_not = sum(s == NOT_ESTIMABLE for s in statuses)
    n_fail = sum(s == FIT_FAILED for s in statuses)

    if n_est == 0 and n_fail == len(statuses):
        return {
            "state": FIT_FAILED,
            "reason": "solver_failure",
            "pass": False,
            "metrics_pass": False,
            "support_status": FIT_FAILED,
        }
    if n_est == 0:
        return {
            "state": NOT_ESTIMABLE,
            "reason": str(cell_records[0].get(f"estimability_reason_{model}", "not_estimable")),
            "pass": False,
            "metrics_pass": False,
            "support_status": NOT_ESTIMABLE,
            "complexity_unsupported": True,
        }

    failed = []
    for crit in criteria:
        value, skip = _criterion_value(cell_records, model, crit)
        if skip or "threshold" not in crit:
            continue
        ok = _compare(value, crit.get("comparator", "<="), float(crit["threshold"]))
        if not ok:
            failed.append(crit["id"])
    metrics_pass = not failed
    incomplete = n_not > 0 or n_fail > 0
    if not metrics_pass:
        support = NOT_SUPPORTED
        state = ESTIMATED_FAILED_GATE
    elif incomplete:
        support = CONDITIONALLY_SUPPORTED_BUT_NOT_ROBUSTLY_ESTIMABLE
        state = ESTIMATED_PASSED_GATE
    else:
        support = SUPPORTED
        state = ESTIMATED_PASSED_GATE
    return {
        "state": state,
        "failed_criteria": failed,
        "pass": metrics_pass,
        "metrics_pass": metrics_pass,
        "support_status": support,
        "n_estimated": n_est,
        "n_not_estimable": n_not,
        "n_fit_failed": n_fail,
        "estimability_rate": n_est / len(statuses),
    }


def _compare(value, comparator: str, threshold: float) -> bool:
    if not np.isfinite(value):
        return False
    if comparator == "<=":
        return value <= threshold
    if comparator == ">=":
        return value >= threshold
    if comparator == ">":
        return value > threshold
    if comparator == "==":
        return abs(value - threshold) <= 1e-12
    raise ValueError(comparator)


def evaluate_gates(design: dict, records: list[dict]) -> dict:
    by_cell: dict[str, list[dict]] = defaultdict(list)
    for row in records:
        by_cell[str(row.get("cell_id", ""))].append(row)

    report = {}
    for gate_name in ("SGI_G0", "SGI_G1", "SGI_G2", "SGI_G3"):
        spec = design["gates"][gate_name]
        if gate_name == "SGI_G3":
            if "evaluated_model" in spec:
                raise RuntimeError(
                    "SGI_G3 must not use a single global evaluated_model; "
                    "use G3_CELL_EVALUATED_MODEL per cell"
                )
            criteria = []
            cell_results = {}
            for cell_id in spec["required_cells"]:
                model = g3_evaluated_model(cell_id)
                cell_results[cell_id] = classify_gate_cell(
                    by_cell.get(cell_id, []), model, criteria
                )
            triggers = _g3_triggers(spec, by_cell)
            oracle = set(spec.get("oracle_cells", [])) or G3_ORACLE_CELLS
            realistic = set(spec.get("realistic_cells", [])) or (
                set(spec["required_cells"]) - oracle
            )
            realistic_fail = [
                cid for cid in realistic
                if cid in cell_results and not cell_results[cid].get("pass")
            ]
            oracle_pass = [
                cid for cid in oracle if cid in cell_results and cell_results[cid].get("pass")
            ]
            report[gate_name] = {
                "cells": cell_results,
                "evaluated_model_by_cell": {
                    cid: g3_evaluated_model(cid) for cid in spec["required_cells"]
                },
                "triggers": triggers,
                "hard_failure": bool(triggers.get("_hard_failure")),
                "robustness_only": bool(triggers.get("_robustness_only")),
                "all_required_cells_pass": (
                    not triggers.get("_hard_failure")
                    and not any(not cell_results[c].get("pass") for c in spec["required_cells"])
                ),
                "oracle_compensated": bool(oracle_pass) and bool(realistic_fail),
                "realistic_failures": realistic_fail,
            }
            continue

        model = spec["evaluated_model"] if "evaluated_model" in spec else (
            "L" if gate_name == "SGI_G1" else "N" if gate_name == "SGI_G2" else "L"
        )
        if gate_name in ("SGI_G1", "SGI_G2") and "evaluated_model" not in spec:
            raise RuntimeError(f"{gate_name} must declare evaluated_model in design_v2")
        criteria = [c for c in spec.get("criteria", []) if isinstance(c, dict)]
        cell_results = {}
        for cell_id in spec["required_cells"]:
            cell_results[cell_id] = classify_gate_cell(by_cell.get(cell_id, []), model, criteria)
        oracle = set(spec.get("oracle_cells", []))
        realistic = set(spec.get("realistic_cells", [])) or (
            set(spec["required_cells"]) - oracle
        )
        realistic_fail = [
            cid for cid in realistic
            if cid in cell_results and not cell_results[cid].get("pass")
        ]
        oracle_pass = [
            cid for cid in oracle if cid in cell_results and cell_results[cid].get("pass")
        ]
        compensated = bool(oracle_pass) and bool(realistic_fail)
        all_required_pass = all(v.get("pass") for v in cell_results.values()) if cell_results else False
        robust = all(
            v.get("support_status") == SUPPORTED for v in cell_results.values()
        ) if cell_results else False
        report[gate_name] = {
            "cells": cell_results,
            "evaluated_model": model,
            "all_required_cells_pass": all_required_pass and not compensated,
            "oracle_compensated": compensated,
            "realistic_failures": realistic_fail,
            "robustly_estimable": robust,
        }
        if gate_name == "SGI_G2":
            report["SGI_G2_RAW"] = dict(report[gate_name])

    g2_raw_pass = bool(report.get("SGI_G2", {}).get("all_required_cells_pass"))
    g3_hard = bool(report.get("SGI_G3", {}).get("hard_failure"))
    g2_conditional = any(
        v.get("support_status") == CONDITIONALLY_SUPPORTED_BUT_NOT_ROBUSTLY_ESTIMABLE
        for v in report.get("SGI_G2", {}).get("cells", {}).values()
    )
    report["NETWORK_SUPPORT_FINAL"] = network_support_final(
        g2_raw_pass=g2_raw_pass,
        g3_hard_fail=g3_hard,
        g2_conditional_estimability=g2_conditional and g2_raw_pass and not g3_hard,
    )
    return report


def network_support_final(
    g2_raw_pass: bool,
    g3_hard_fail: bool,
    g2_conditional_estimability: bool = False,
) -> dict:
    if not g2_raw_pass:
        status = "NOT_EARNED"
    elif g3_hard_fail:
        status = "NOT_EARNED_DUE_TO_FALSIFICATION"
    elif g2_conditional_estimability:
        status = "CONDITIONALLY_SUPPORTED_BUT_NOT_ROBUSTLY_ESTIMABLE"
    else:
        status = "EARNED_UNDER_SPECIFIED_DATA_REGIME"
    return {
        "status": status,
        "SGI_G2_RAW_pass": bool(g2_raw_pass),
        "SGI_G3_hard_fail": bool(g3_hard_fail),
    }


def _g3_cell_metric(trig: dict, rows: list[dict], cell_id: str) -> tuple[float, bool]:
    """(value, triggered) for one cell. Empty rows do not trigger (unit tests may omit cells)."""
    if not rows:
        return np.nan, False
    model = g3_evaluated_model(cell_id)
    statuses = [_status(r, model) for r in rows]
    if statuses and all(s == NOT_ESTIMABLE for s in statuses):
        return np.nan, True
    if statuses and all(s == FIT_FAILED for s in statuses):
        return np.nan, True
    tid = trig["id"]
    statistic = str(trig.get("statistic", ""))
    if "false_edge_count" in statistic:
        if "fraction" in statistic:
            flags = [
                float(r.get("false_edge_any", r.get("false_edge_count", 0)) or 0) >= 1
                for r in rows
            ]
            value = float(np.mean(flags)) if flags else np.nan
        else:
            value = _nanmedian(float(r.get("false_edge_count", np.nan)) for r in rows)
        return value, _compare(value, trig.get("comparator", ">"), float(trig["threshold"]))
    if "placebo" in tid:
        flags = [float(r.get("placebo_false_effect_L", 0) or 0) == 1 for r in rows]
        value = float(np.mean(flags)) if flags else np.nan
        return value, _compare(value, trig.get("comparator", ">"), float(trig["threshold"]))
    if tid == "G3_prediction_intervention_inversion":
        rmse_n = aggregate_cell(rows, "N", "rmse_test_N")["median"]
        nire_n = aggregate_cell(rows, "N", "nire_persistent_step_h26_N")["median"]
        rmse_s = _best_simple_rmse(rows)
        nire_s = _best_simple_nire(rows)
        better_pred = np.isfinite(rmse_n) and np.isfinite(rmse_s) and rmse_n < rmse_s
        worse_int = np.isfinite(nire_n) and np.isfinite(nire_s) and nire_n > nire_s
        triggered = bool(better_pred and worse_int)
        return float(triggered), triggered
    return np.nan, False


def _g3_triggers(spec: dict, by_cell: dict) -> dict:
    """Per-cell falsification, then combine. Oracle success cannot hide realistic failure."""
    out = {}
    for trig in spec.get("triggers_any_of", []):
        tid = trig["id"]
        cells = trig.get("cells", [])
        severity = trig.get("severity", "HARD_FAILURE")
        per_cell = {}
        triggered_cells = []
        for cid in cells:
            value, cell_trig = _g3_cell_metric(trig, by_cell.get(cid, []), cid)
            per_cell[cid] = {
                "value": value,
                "triggered": bool(cell_trig),
                "evaluated_model": g3_evaluated_model(cid),
            }
            if cell_trig:
                triggered_cells.append(cid)
        realistic = [c for c in cells if c not in G3_ORACLE_CELLS]
        realistic_triggered = [c for c in triggered_cells if c in realistic]
        oracle_only = bool(triggered_cells) and not realistic_triggered and bool(realistic)
        triggered = bool(triggered_cells)
        out[tid] = {
            "triggered": triggered,
            "severity": severity,
            "cells": cells,
            "per_cell": per_cell,
            "triggered_cells": triggered_cells,
            "realistic_triggered_cells": realistic_triggered,
            "oracle_cannot_compensate": True,
            "value": (
                _nanmedian(per_cell[c]["value"] for c in triggered_cells)
                if triggered_cells
                else _nanmedian(per_cell[c]["value"] for c in cells)
            ),
        }
        if oracle_only and severity == "HARD_FAILURE":
            # Oracle-only trigger still counts: oracle is a required cell.
            pass
    hard = any(v["triggered"] and v["severity"] == "HARD_FAILURE" for v in out.values())
    robust = any(v["triggered"] and v["severity"] == "ROBUSTNESS_EVIDENCE" for v in out.values())
    out["_hard_failure"] = hard
    out["_robustness_only"] = bool(robust and not hard)
    return out


def prediction_vs_intervention(records: list[dict]) -> list[dict]:
    """Continuous prediction/intervention table. Binary inversion uses the frozen G3 rule."""
    by_cell: dict[str, list[dict]] = defaultdict(list)
    for row in records:
        by_cell[str(row.get("cell_id", ""))].append(row)
    rows = []
    for cell_id, group in by_cell.items():
        rmse_n = aggregate_cell(group, "N", "rmse_test_N")["median"]
        rmse_l = aggregate_cell(group, "L", "rmse_test_L")["median"]
        nire_n = aggregate_cell(group, "N", "nire_persistent_step_h26_N")["median"]
        nire_l = aggregate_cell(group, "L", "nire_persistent_step_h26_L")["median"]
        rmse_s = _best_simple_rmse(group)
        nire_s = _best_simple_nire(group)
        pred_gain = (rmse_l - rmse_n) / rmse_l if np.isfinite(rmse_l) and rmse_l > 0 else np.nan
        int_gain = (nire_l - nire_n) / nire_l if np.isfinite(nire_l) and nire_l > 0 else np.nan
        # Frozen G3 inversion: N better RMSE than best simple AND worse NIRE than best simple.
        g3_inversion = bool(
            np.isfinite(rmse_n) and np.isfinite(rmse_s) and rmse_n < rmse_s
            and np.isfinite(nire_n) and np.isfinite(nire_s) and nire_n > nire_s
        )
        n_vs_l_inversion = bool(
            np.isfinite(pred_gain) and np.isfinite(int_gain) and pred_gain > 0 and int_gain < 0
        )
        rows.append(
            {
                "cell_id": cell_id,
                "scenario": group[0].get("scenario", ""),
                "prediction_gain_N_vs_L": pred_gain,
                "intervention_gain_N_vs_L": int_gain,
                "rmse_test_N_median": rmse_n,
                "rmse_test_L_median": rmse_l,
                "nire_persistent_step_h26_N_median": nire_n,
                "nire_persistent_step_h26_L_median": nire_l,
                "prediction_vs_intervention_inversion": n_vs_l_inversion,
                "g3_prediction_intervention_inversion": g3_inversion,
                "good_prediction_poor_intervention": g3_inversion,
            }
        )
    return rows


def data_adequacy_rows(records: list[dict]) -> list[dict]:
    by_cell: dict[str, list[dict]] = defaultdict(list)
    for row in records:
        by_cell[str(row.get("cell_id", ""))].append(row)
    out = []
    for cell_id, group in by_cell.items():
        first = group[0]
        l_agg = aggregate_cell(group, "L", "nire_persistent_step_h26_L")
        s_agg = aggregate_cell(group, "S", "nire_persistent_step_h26_S")
        n_agg = aggregate_cell(group, "N", "nire_persistent_step_h26_N")
        n_rmse = aggregate_cell(group, "N", "rmse_test_N")
        l_rmse = aggregate_cell(group, "L", "rmse_test_L")
        f1_vals = [_f1_value(r) for r in group if _status(r, "N") == ESTIMATED]
        placebo = [
            float(r.get("placebo_false_effect_L", 0) or 0) == 1
            for r in group if str(first.get("scenario", "")) == "S8"
        ]
        false_edge = [
            float(r.get("false_edge_any", 0) or 0)
            for r in group if _status(r, "N") == ESTIMATED
        ]
        cd = aggregate_cell(group, "L", "cumulative_drawdown_error_persistent_step_L")
        if not np.isfinite(cd["median"]):
            # column name varies; pick any cumulative_drawdown_error_*_L
            cd_keys = [k for k in first if str(k).startswith("cumulative_drawdown_error_") and str(k).endswith("_L")]
            cd = aggregate_cell(group, "L", cd_keys[0]) if cd_keys else cd

        n_rate = n_agg["estimability_rate"]
        l_rate = l_agg["estimability_rate"]
        nire_l = l_agg["median"]
        nire_n = n_agg["median"]
        nire_s = s_agg["median"]
        g1_nire_ok = np.isfinite(nire_l) and nire_l <= 0.20
        if l_rate == 0:
            local_status = NOT_ESTIMABLE
        elif not g1_nire_ok:
            local_status = "local_response_not_identified"
        elif l_rate < 1.0:
            local_status = "local_response_conditionally_supported"
        else:
            local_status = "local_response_supported"

        spatial_useful = (
            np.isfinite(nire_s) and np.isfinite(nire_l) and nire_s < nire_l and s_agg["n_estimated"] > 0
        )
        if n_rate == 0:
            network_status = "network_dynamics_not_estimable"
        elif np.isfinite(nire_n) and np.isfinite(nire_l) and nire_n > nire_l:
            network_status = "network_dynamics_not_earned"
        elif n_rate < 1.0:
            network_status = "network_dynamics_conditionally_supported_but_poorly_estimable"
        else:
            network_status = "network_dynamics_supported_in_this_cell_only"

        scale_status = (
            "absolute_intervention_scale_supported"
            if any(bool(r.get("physical_parameter_identifiable") or r.get("absolute_S_identifiable")) for r in group)
            else "absolute_intervention_scale_unsupported"
        )

        out.append(
            {
                "cell_id": cell_id,
                "scenario": first.get("scenario", ""),
                "cadence_k": first.get("cadence", np.nan),
                "cadence_over_tau_relax": first.get("cadence_over_tau_relax", np.nan),
                "hydraulic_memory_regime": first.get("memory", ""),
                "head_missing_fraction": first.get("mcar_fraction", np.nan),
                "observed_node_fraction": first.get("observed_node_fraction", np.nan),
                "pumping_quality": first.get("pumping_quality", ""),
                "pumping_scale_known": first.get("absolute_pumping_scale_known", np.nan),
                "recharge_quality": first.get("recharge_quality", ""),
                "recharge_lag": first.get("recharge_lag", np.nan),
                "forcing_confounding": first.get("confounding_rho", np.nan),
                "SNR": first.get("snr_head", first.get("realized_snr_head", np.nan)),
                "network_strength": first.get("gamma", ""),
                "candidate_support_status": (
                    "misspecified"
                    if float(first.get("true_edges_outside_candidate_set", 0) or 0) > 0
                    else "nested_or_na"
                ),
                "model": "ladder_B0_L_S_N",
                "estimability_rate_L": l_agg["estimability_rate"],
                "estimability_rate_S": s_agg["estimability_rate"],
                "estimability_rate_N": n_agg["estimability_rate"],
                "fit_failure_rate_L": l_agg["fit_failure_rate"],
                "fit_failure_rate_N": n_agg["fit_failure_rate"],
                "conditional_prediction_error_L": l_rmse["median"],
                "conditional_prediction_error_N": n_rmse["median"],
                "conditional_intervention_error_L": nire_l,
                "conditional_intervention_error_N": nire_n,
                "cumulative_drawdown_error": cd["median"],
                "vulnerability_rank_metric": nire_l,
                "edge_f1": _nanmedian(f1_vals),
                "strong_edge_undirected_f1": _nanmedian(f1_vals),
                "false_edge_rate": float(np.mean(false_edge)) if false_edge else np.nan,
                "placebo_false_effect_rate": float(np.mean(placebo)) if placebo else np.nan,
                "supported_complexity_status": network_status if local_status.startswith("local_response_supported") or local_status == "local_response_conditionally_supported" else local_status,
                "local_response_status": local_status,
                "spatial_forcing_useful": spatial_useful,
                "network_dynamics_status": network_status,
                "absolute_scale_status": scale_status,
                "complexity_unsupported": bool(n_agg["estimability_rate"] == 0.0),
            }
        )
    return out


def strongest_claims(gates: dict, g1_pass: bool, g1_robust: bool) -> tuple[str, str]:
    net = gates.get("NETWORK_SUPPORT_FINAL", {})
    net_status = net.get("status", "NOT_EARNED")
    if not g1_pass:
        supported = "LOCAL_RESPONSE_NOT_IDENTIFIED"
        unsupported = "groundwater-response adequacy for planning is not claimed"
    elif net_status == "EARNED_UNDER_SPECIFIED_DATA_REGIME" and g1_robust:
        supported = "NETWORK_IDENTIFIABLE_UNDER_SPECIFIED_DATA_REGIME"
        unsupported = "empirical Andhra Pradesh parameters, connectivity, and impacts"
    elif net_status == "CONDITIONALLY_SUPPORTED_BUT_NOT_ROBUSTLY_ESTIMABLE":
        supported = "NETWORK_CONDITIONALLY_SUPPORTED_BUT_NOT_ROBUSTLY_ESTIMABLE"
        unsupported = "unconditional network support under incomplete estimability"
    elif net_status == "NOT_EARNED_DUE_TO_FALSIFICATION":
        supported = "LOCAL_RESPONSE_IDENTIFIED_NETWORK_NOT_EARNED"
        unsupported = "network complexity (hard G3 falsification)"
    elif net_status == "NOT_EARNED":
        supported = "LOCAL_RESPONSE_IDENTIFIED_NETWORK_NOT_EARNED"
        unsupported = "network complexity (G2_RAW did not pass)"
    else:
        supported = "INCONCLUSIVE"
        unsupported = "unconditional planning-model claim"
    if not g1_robust and g1_pass and supported.startswith("LOCAL"):
        supported = "LOCAL_RESPONSE_CONDITIONALLY_SUPPORTED_BUT_NOT_ROBUSTLY_ESTIMABLE"
    return supported, unsupported


def summarize(design: dict, records: list[dict], source: str) -> dict:
    gates = evaluate_gates(design, records)
    g1 = gates.get("SGI_G1", {})
    g1_pass = bool(g1.get("all_required_cells_pass"))
    g1_robust = bool(g1.get("robustly_estimable"))
    supported, unsupported = strongest_claims(gates, g1_pass, g1_robust)
    local_status = (
        "LOCAL_RESPONSE_NOT_IDENTIFIED"
        if not g1_pass
        else (
            "SUPPORTED" if g1_robust
            else CONDITIONALLY_SUPPORTED_BUT_NOT_ROBUSTLY_ESTIMABLE
        )
    )
    return {
        "banner": NONINFERENTIAL_BANNER if source != "ANALYSIS" else "SUBSTANTIVE",
        "source": source,
        "n_records": len(records),
        "gates": gates,
        "SGI_G2_RAW": gates.get("SGI_G2_RAW", gates.get("SGI_G2", {})),
        "NETWORK_SUPPORT_FINAL": gates.get("NETWORK_SUPPORT_FINAL", {}),
        "LOCAL_RESPONSE_STATUS": local_status,
        "prediction_vs_intervention": prediction_vs_intervention(records),
        "data_adequacy": data_adequacy_rows(records),
        "analysis_seeds_used": source == "ANALYSIS",
        "strongest_supported_claim": supported,
        "strongest_unsupported_claim": unsupported,
    }


def write_summary(payload: dict, stem: str) -> Path:
    SUMMARIZER_OUT.mkdir(parents=True, exist_ok=True)
    path = SUMMARIZER_OUT / f"{stem}.json"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, default=float)
    return path


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = sorted({k for r in rows for k in r})
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_analysis_outputs(design: dict, records: list[dict], payload: dict, sweep_manifest: dict) -> dict:
    """Canonical ANALYSIS tables. Called only after provenance validation."""
    ANALYSIS_OUT.mkdir(parents=True, exist_ok=True)
    by_cell: dict[str, list[dict]] = defaultdict(list)
    for row in records:
        by_cell[str(row.get("cell_id", ""))].append(row)

    scenario_rows = []
    estim_rows = []
    interv_rows = []
    network_rows = []
    placebo_rows = []
    for cell_id, group in sorted(by_cell.items()):
        first = group[0]
        for model in ("B0", "L", "S", "N"):
            agg_rmse = aggregate_cell(group, model, f"rmse_test_{model}")
            agg_nire = aggregate_cell(group, model, f"nire_persistent_step_h26_{model}")
            estim_rows.append(
                {
                    "cell_id": cell_id,
                    "scenario": first.get("scenario", ""),
                    "model": model,
                    "n_replicates": agg_rmse["n_replicates"],
                    "n_estimated": agg_rmse["n_estimated"],
                    "n_not_estimable": agg_rmse["n_not_estimable"],
                    "n_fit_failed": agg_rmse["n_fit_failed"],
                    "estimability_rate": agg_rmse["estimability_rate"],
                    "not_estimable_rate": agg_rmse["not_estimable_rate"],
                    "fit_failure_rate": agg_rmse["fit_failure_rate"],
                    "conditional_rmse_median": agg_rmse["median"],
                    "conditional_nire_h26_median": agg_nire["median"],
                }
            )
        scenario_rows.append(
            {
                "cell_id": cell_id,
                "scenario": first.get("scenario", ""),
                "topology": first.get("topology", ""),
                "cadence": first.get("cadence", np.nan),
                "memory": first.get("memory", ""),
                "n_replicates": len(group),
                "estimability_rate_L": aggregate_cell(group, "L", "rmse_test_L")["estimability_rate"],
                "estimability_rate_N": aggregate_cell(group, "N", "rmse_test_N")["estimability_rate"],
                "rmse_test_L_median": aggregate_cell(group, "L", "rmse_test_L")["median"],
                "rmse_test_N_median": aggregate_cell(group, "N", "rmse_test_N")["median"],
                "nire_h26_L_median": aggregate_cell(group, "L", "nire_persistent_step_h26_L")["median"],
                "nire_h26_N_median": aggregate_cell(group, "N", "nire_persistent_step_h26_N")["median"],
            }
        )
        interv_rows.append(
            {
                "cell_id": cell_id,
                "scenario": first.get("scenario", ""),
                "nire_persistent_step_h26_B0": aggregate_cell(group, "B0", "nire_persistent_step_h26_B0")["median"],
                "nire_persistent_step_h26_L": aggregate_cell(group, "L", "nire_persistent_step_h26_L")["median"],
                "nire_persistent_step_h26_S": aggregate_cell(group, "S", "nire_persistent_step_h26_S")["median"],
                "nire_persistent_step_h26_N": aggregate_cell(group, "N", "nire_persistent_step_h26_N")["median"],
            }
        )
        f1_vals = [_f1_value(r) for r in group if _status(r, "N") == ESTIMATED]
        network_rows.append(
            {
                "cell_id": cell_id,
                "scenario": first.get("scenario", ""),
                "strong_edge_undirected_f1": _nanmedian(f1_vals),
                "edge_f1": _nanmedian(f1_vals),
                "false_edge_count_median": _nanmedian(float(r.get("false_edge_count", np.nan)) for r in group),
                "false_edge_any_rate": float(np.mean([float(r.get("false_edge_any", 0) or 0) for r in group])),
            }
        )
        if str(first.get("scenario", "")) == "S8":
            placebo_rows.append(
                {
                    "cell_id": cell_id,
                    "placebo_false_effect_rate_L": float(
                        np.mean([float(r.get("placebo_false_effect_L", 0) or 0) == 1 for r in group])
                    ),
                    "placebo_coef_L_median": _nanmedian(float(r.get("placebo_coef_L", np.nan)) for r in group),
                    "s8_real_pumping_present_rate": float(
                        np.mean([float(r.get("s8_real_pumping_present_L", 1) or 0) for r in group])
                    ),
                }
            )

    adequacy = payload["data_adequacy"]
    pred_int = payload["prediction_vs_intervention"]
    gates = payload["gates"]

    gate_rows = []
    for name in ("SGI_G0", "SGI_G1", "SGI_G2", "SGI_G3"):
        spec = gates.get(name, {})
        for cid, cres in spec.get("cells", {}).items():
            gate_rows.append(
                {
                    "gate": name,
                    "cell_id": cid,
                    "evaluated_model": spec.get("evaluated_model_by_cell", {}).get(
                        cid, spec.get("evaluated_model", "")
                    ),
                    "state": cres.get("state", ""),
                    "support_status": cres.get("support_status", ""),
                    "metrics_pass": cres.get("metrics_pass", cres.get("pass")),
                    "pass": cres.get("pass"),
                    "estimability_rate": cres.get("estimability_rate", np.nan),
                }
            )
    gate_rows.append(
        {
            "gate": "SGI_G2_RAW",
            "cell_id": "_OVERALL",
            "evaluated_model": "N",
            "state": "",
            "support_status": "",
            "metrics_pass": gates.get("SGI_G2", {}).get("all_required_cells_pass"),
            "pass": gates.get("SGI_G2", {}).get("all_required_cells_pass"),
            "estimability_rate": np.nan,
        }
    )
    gate_rows.append(
        {
            "gate": "NETWORK_SUPPORT_FINAL",
            "cell_id": "_OVERALL",
            "evaluated_model": "N",
            "state": payload.get("NETWORK_SUPPORT_FINAL", {}).get("status", ""),
            "support_status": payload.get("NETWORK_SUPPORT_FINAL", {}).get("status", ""),
            "metrics_pass": np.nan,
            "pass": payload.get("NETWORK_SUPPORT_FINAL", {}).get("status")
            == "EARNED_UNDER_SPECIFIED_DATA_REGIME",
            "estimability_rate": np.nan,
        }
    )

    g0_path = OUTPUTS / "SGI_G0_RESULT.json"
    g0 = json.loads(g0_path.read_text(encoding="utf-8")) if g0_path.exists() else {"pass": None}

    expected = int(sweep_manifest.get("n_cells", 0)) * int(sweep_manifest.get("n_analysis_seeds", 0))
    observed = len(records)
    status = {
        "design_hash": sweep_manifest.get("design_hash"),
        "code_hash": sweep_manifest.get("code_hash"),
        "analysis_seed_hash": sweep_manifest.get("analysis_seed_hash"),
        "replicate_count_expected": expected,
        "replicate_count_observed": observed,
        "SGI_G0": {"pass": g0.get("pass"), "criteria": g0.get("criteria")},
        "SGI_G1": {
            "all_required_cells_pass": gates.get("SGI_G1", {}).get("all_required_cells_pass"),
            "robustly_estimable": gates.get("SGI_G1", {}).get("robustly_estimable"),
            "cells": gates.get("SGI_G1", {}).get("cells"),
        },
        "SGI_G2_RAW": {
            "all_required_cells_pass": gates.get("SGI_G2", {}).get("all_required_cells_pass"),
            "robustly_estimable": gates.get("SGI_G2", {}).get("robustly_estimable"),
            "cells": gates.get("SGI_G2", {}).get("cells"),
        },
        "SGI_G3": {
            "hard_failure": gates.get("SGI_G3", {}).get("hard_failure"),
            "robustness_only": gates.get("SGI_G3", {}).get("robustness_only"),
            "triggers": gates.get("SGI_G3", {}).get("triggers"),
            "evaluated_model_by_cell": gates.get("SGI_G3", {}).get("evaluated_model_by_cell"),
        },
        "NETWORK_SUPPORT_FINAL": payload.get("NETWORK_SUPPORT_FINAL"),
        "LOCAL_RESPONSE_STATUS": payload.get("LOCAL_RESPONSE_STATUS"),
        "estimability_statuses": {
            "states": [NOT_ESTIMABLE, FIT_FAILED, ESTIMATED_FAILED_GATE, ESTIMATED_PASSED_GATE],
            "support_categories": [
                SUPPORTED,
                CONDITIONALLY_SUPPORTED_BUT_NOT_ROBUSTLY_ESTIMABLE,
                NOT_SUPPORTED,
                NOT_ESTIMABLE,
                FIT_FAILED,
            ],
        },
        "strongest_supported_claim": payload.get("strongest_supported_claim"),
        "strongest_unsupported_claim": payload.get("strongest_unsupported_claim"),
        "analysis_seeds_used": True,
        "source": "ANALYSIS",
    }

    _write_csv(ANALYSIS_OUT / "scenario_summary.csv", scenario_rows)
    _write_csv(ANALYSIS_OUT / "estimability_summary.csv", estim_rows)
    _write_csv(ANALYSIS_OUT / "intervention_recovery.csv", interv_rows)
    _write_csv(ANALYSIS_OUT / "network_recovery.csv", network_rows)
    _write_csv(ANALYSIS_OUT / "placebo_falsification.csv", placebo_rows)
    _write_csv(ANALYSIS_OUT / "prediction_vs_intervention.csv", pred_int)
    _write_csv(ANALYSIS_OUT / "gate_results.csv", gate_rows)
    _write_csv(ANALYSIS_OUT / "data_adequacy_map.csv", adequacy)
    with open(ANALYSIS_OUT / "FINAL_SYNTHETIC_IDENTIFIABILITY_STATUS.json", "w", encoding="utf-8") as handle:
        json.dump(status, handle, indent=2, sort_keys=True, default=float)
    with open(ANALYSIS_OUT / "SUMMARY_PAYLOAD.json", "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, default=float)
    return status


def validate_analysis_inputs(
    design: dict,
    records: list[dict],
    sweep_manifest: dict,
    freeze: dict,
) -> list[str]:
    errors = []
    if sweep_manifest.get("source") not in (None, "ANALYSIS") and sweep_manifest.get("full_sweep_launched") is not True:
        errors.append("sweep manifest is not an ANALYSIS launch")
    if design_hash() != freeze.get("design_hash"):
        errors.append("current DESIGN_HASH != frozen DESIGN_HASH")
    if design_hash() != sweep_manifest.get("design_hash"):
        errors.append("sweep DESIGN_HASH != frozen design")
    if code_hash() != freeze.get("code_hash"):
        errors.append("current CODE_HASH != frozen CODE_HASH")
    if code_hash() != sweep_manifest.get("code_hash"):
        errors.append("sweep CODE_HASH != frozen code")
    expected_seed_hash = freeze["seed_pool_hashes"]["ANALYSIS"]
    actual_seed_hash = seed_pool_hash(design, "ANALYSIS")
    if actual_seed_hash != expected_seed_hash:
        errors.append("ANALYSIS seed-pool hash mismatch vs freeze")
    if sweep_manifest.get("analysis_seed_hash") not in (None, expected_seed_hash, actual_seed_hash):
        errors.append("sweep analysis_seed_hash mismatch")
    analysis_seeds = set(seed_list(design, "ANALYSIS"))
    forbidden = set(seed_list(design, "SMOKE")) | set(seed_list(design, "G0")) | set(seed_list(design, "CALIBRATION"))
    seeds_in = set()
    for row in records:
        if row.get("smoke") in (True, "True", 1, 1.0):
            errors.append("SMOKE records present in ANALYSIS input")
            break
        try:
            seeds_in.add(int(row.get("seed")))
        except (TypeError, ValueError):
            pass
    if seeds_in & forbidden:
        errors.append("G0/SMOKE/CALIBRATION seeds contaminate ANALYSIS records")
    if seeds_in - analysis_seeds:
        errors.append("non-ANALYSIS seeds present")
    expected = int(sweep_manifest.get("n_cells", 0)) * int(sweep_manifest.get("n_analysis_seeds", 0))
    if expected and len(records) != expected:
        errors.append(
            f"replicate count {len(records)} != expected {expected}"
        )
    return errors
