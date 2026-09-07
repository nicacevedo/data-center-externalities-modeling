"""Preregistered scientific summarizer. Frozen BEFORE any ANALYSIS seed is touched."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from io import StringIO
from pathlib import Path

import numpy as np

from .design import MODULE_ROOT
from .evaluation import _nanmean, _nanmedian

OUTPUTS = MODULE_ROOT / "outputs"
FIXTURE_DIR = MODULE_ROOT / "tests" / "fixtures"
SUMMARIZER_OUT = OUTPUTS / "summarizer"

ESTIMATED = "ESTIMATED"
NOT_ESTIMABLE = "NOT_ESTIMABLE"
FIT_FAILED = "FIT_FAILED"
ESTIMATED_FAILED_GATE = "ESTIMATED_FAILED_GATE"
ESTIMATED_PASSED_GATE = "ESTIMATED_PASSED_GATE"

NONINFERENTIAL_BANNER = (
    "NON-INFERENTIAL. This summary was produced from fixtures or SMOKE seeds. "
    "It must not be used to set thresholds, choose regimes, or make scientific claims."
)


def load_records(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        # skip comment banner lines
        lines = [ln for ln in handle if not ln.startswith("#")]
    from io import StringIO

    reader = csv.DictReader(StringIO("".join(lines)))
    records = []
    for row in reader:
        parsed = {}
        for key, value in row.items():
            if value is None or value == "":
                parsed[key] = np.nan
                continue
            try:
                parsed[key] = float(value) if value not in ("True", "False") else (value == "True")
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
    if cid == "G2_strong_edge_f1":
        return aggregate_cell(cell_records, "N", "edge_f1")["median"], False
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
        return {"state": NOT_ESTIMABLE, "reason": "no_records", "pass": False}
    statuses = [_status(r, model) for r in cell_records]
    if all(s == NOT_ESTIMABLE for s in statuses):
        return {
            "state": NOT_ESTIMABLE,
            "reason": str(cell_records[0].get(f"estimability_reason_{model}", "not_estimable")),
            "pass": False,
            "complexity_unsupported": True,
        }
    if all(s == FIT_FAILED for s in statuses):
        return {"state": FIT_FAILED, "reason": "solver_failure", "pass": False}
    failed = []
    for crit in criteria:
        value, skip = _criterion_value(cell_records, model, crit)
        if skip or "threshold" not in crit:
            continue
        ok = _compare(value, crit.get("comparator", "<="), float(crit["threshold"]))
        if not ok:
            failed.append(crit["id"])
    if failed:
        return {"state": ESTIMATED_FAILED_GATE, "failed_criteria": failed, "pass": False}
    return {"state": ESTIMATED_PASSED_GATE, "failed_criteria": [], "pass": True}


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
        model = spec.get("evaluated_model", "L")
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
        report[gate_name] = {
            "cells": cell_results,
            "all_required_cells_pass": all_required_pass and not compensated,
            "oracle_compensated": compensated,
            "realistic_failures": realistic_fail,
        }
        if gate_name == "SGI_G3":
            report[gate_name]["triggers"] = _g3_triggers(spec, by_cell)
    return report


def _g3_triggers(spec: dict, by_cell: dict) -> dict:
    out = {}
    for trig in spec.get("triggers_any_of", []):
        tid = trig["id"]
        cells = trig.get("cells", [])
        rows = [r for cid in cells for r in by_cell.get(cid, [])]
        severity = trig.get("severity", "HARD_FAILURE")
        triggered = False
        value = np.nan
        if "false_edge_count" in str(trig.get("statistic", "")):
            if "fraction" in str(trig.get("statistic", "")):
                flags = [float(r.get("false_edge_any", r.get("false_edge_count", 0)) or 0) >= 1 for r in rows]
                value = float(np.mean(flags)) if flags else np.nan
            else:
                value = _nanmedian(float(r.get("false_edge_count", np.nan)) for r in rows)
            triggered = _compare(value, trig.get("comparator", ">"), float(trig["threshold"]))
        elif "placebo" in tid:
            flags = [float(r.get("placebo_false_effect_L", 0) or 0) == 1 for r in rows]
            value = float(np.mean(flags)) if flags else np.nan
            triggered = _compare(value, trig.get("comparator", ">"), float(trig["threshold"]))
        elif tid == "G3_prediction_intervention_inversion":
            inversions = []
            for cid in cells:
                group = by_cell.get(cid, [])
                if not group:
                    continue
                rmse_n = aggregate_cell(group, "N", "rmse_test_N")["median"]
                nire_n = aggregate_cell(group, "N", "nire_persistent_step_h26_N")["median"]
                rmse_s = _best_simple_rmse(group)
                nire_s = _best_simple_nire(group)
                better_pred = np.isfinite(rmse_n) and np.isfinite(rmse_s) and rmse_n < rmse_s
                worse_int = np.isfinite(nire_n) and np.isfinite(nire_s) and nire_n > nire_s
                inversions.append(bool(better_pred and worse_int))
            value = float(np.mean(inversions)) if inversions else np.nan
            triggered = bool(inversions) and any(inversions)
        out[tid] = {
            "triggered": bool(triggered),
            "value": value,
            "severity": severity,
            "cells": cells,
        }
    hard = any(v["triggered"] and v["severity"] == "HARD_FAILURE" for v in out.values())
    robust = any(v["triggered"] and v["severity"] == "ROBUSTNESS_EVIDENCE" for v in out.values())
    out["_hard_failure"] = hard
    out["_robustness_only"] = bool(robust and not hard)
    return out


def prediction_vs_intervention(records: list[dict]) -> list[dict]:
    """Classify cells as good-prediction/poor-intervention etc. Schema only; not prose."""
    by_cell: dict[str, list[dict]] = defaultdict(list)
    for row in records:
        by_cell[str(row.get("cell_id", ""))].append(row)
    rows = []
    for cell_id, group in by_cell.items():
        rmse_n = aggregate_cell(group, "N", "rmse_test_N")["median"]
        rmse_l = aggregate_cell(group, "L", "rmse_test_L")["median"]
        nire_n = aggregate_cell(group, "N", "nire_persistent_step_h26_N")["median"]
        nire_l = aggregate_cell(group, "L", "nire_persistent_step_h26_L")["median"]
        pred_gain = (rmse_l - rmse_n) / rmse_l if np.isfinite(rmse_l) and rmse_l > 0 else np.nan
        int_gain = (nire_l - nire_n) / nire_l if np.isfinite(nire_l) and nire_l > 0 else np.nan
        inversion = bool(
            np.isfinite(pred_gain) and np.isfinite(int_gain) and pred_gain > 0 and int_gain < 0
        )
        rows.append(
            {
                "cell_id": cell_id,
                "prediction_gain_N_vs_L": pred_gain,
                "intervention_gain_N_vs_L": int_gain,
                "prediction_vs_intervention_inversion": inversion,
            }
        )
    return rows


def data_adequacy_rows(records: list[dict]) -> list[dict]:
    by_cell: dict[str, list[dict]] = defaultdict(list)
    for row in records:
        by_cell[str(row.get("cell_id", ""))].append(row)
    out = []
    for cell_id, group in by_cell.items():
        n_status = aggregate_cell(group, "N", "rmse_test_N")
        out.append(
            {
                "cell_id": cell_id,
                "scenario": group[0].get("scenario", ""),
                "cadence": group[0].get("cadence", np.nan),
                "mcar_fraction": group[0].get("mcar_fraction", np.nan),
                "estimability_rate_N": n_status["estimability_rate"],
                "not_estimable_rate_N": n_status["not_estimable_rate"],
                "complexity_unsupported": bool(n_status["estimability_rate"] == 0.0),
            }
        )
    return out


def summarize(design: dict, records: list[dict], source: str) -> dict:
    gates = evaluate_gates(design, records)
    return {
        "banner": NONINFERENTIAL_BANNER if source != "ANALYSIS" else "SUBSTANTIVE",
        "source": source,
        "n_records": len(records),
        "gates": gates,
        "prediction_vs_intervention": prediction_vs_intervention(records),
        "data_adequacy": data_adequacy_rows(records),
        "analysis_seeds_used": False,
    }


def write_summary(payload: dict, stem: str) -> Path:
    SUMMARIZER_OUT.mkdir(parents=True, exist_ok=True)
    path = SUMMARIZER_OUT / f"{stem}.json"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, default=float)
    return path
