"""Exact uint64 I/O, typed CSV, resume idempotency, summary equivalence.

NON-ANALYSIS fixtures only. Seeds are integers greater than 2^53 whose IEEE-754
float representation is not the original integer. This suite never authorizes
the V3_ANALYSIS pool and never supplies the ANALYSIS token.
"""

from __future__ import annotations

import importlib.util
import inspect
import math
import sys
from pathlib import Path

import numpy as np
import pytest

from src_v3.design import MODULE_ROOT, v3_all_cells
from src_v3.modes import RNG_NAMED, SEED_ORTHOGONAL
from src_v3.records import (
    FLOAT64_EXACT_INT_MAX,
    append_record,
    existing_keys,
    fieldnames_of,
    is_boolean_field,
    is_categorical_field,
    is_integer_field,
    parse_bool,
    parse_csv,
    parse_record,
    parse_seed,
    scientific_equal,
    unique_pairs,
    write_csv,
)
from src_v3.summarize_v3 import paired_contrast, summarize_analysis

_SCRIPTS = MODULE_ROOT / "scripts_v3"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
_SPEC = importlib.util.spec_from_file_location("run_v3_io_under_test", _SCRIPTS / "run_v3.py")
run_v3 = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules["run_v3_io_under_test"] = run_v3
_SPEC.loader.exec_module(run_v3)


SEED_GT_2P53 = 6102701586134898939
SEED_2P53_PLUS_1 = FLOAT64_EXACT_INT_MAX + 1  # 9007199254740993
SEED_C = 14299546645614273481

BLOCK_D = (
    "D_PE_RE_R0",
    "D_PE_RE_R3",
    "D_PE_RN_R0",
    "D_PE_RN_R3",
    "D_PM_RE_R0",
    "D_PM_RE_R3",
    "D_PM_RN_R0",
    "D_PM_RN_R3",
)


def test_fixture_seeds_are_not_exact_in_float64():
    for seed in (SEED_GT_2P53, SEED_2P53_PLUS_1, SEED_C):
        assert seed > FLOAT64_EXACT_INT_MAX
        as_float = float(seed)
        assert int(as_float) != seed


def test_parse_seed_accepts_int_numpy_and_digit_string():
    assert parse_seed(SEED_GT_2P53) == SEED_GT_2P53
    assert parse_seed(np.uint64(SEED_GT_2P53)) == SEED_GT_2P53
    assert parse_seed(np.uint64(SEED_C)) == SEED_C
    assert parse_seed(str(SEED_GT_2P53)) == SEED_GT_2P53
    assert parse_seed(SEED_2P53_PLUS_1) == SEED_2P53_PLUS_1


def test_parse_seed_rejects_float_and_lossy_strings():
    with pytest.raises(Exception, match="floating point"):
        parse_seed(float(SEED_GT_2P53))
    with pytest.raises(Exception, match="floating point"):
        parse_seed(np.float64(SEED_GT_2P53))
    with pytest.raises(Exception, match="decimal digit"):
        parse_seed(f"{SEED_GT_2P53}.0")
    with pytest.raises(Exception, match="decimal digit"):
        parse_seed("1e19")
    with pytest.raises(Exception, match="boolean"):
        parse_seed(True)
    with pytest.raises(Exception, match="uint64"):
        parse_seed(-1)
    with pytest.raises(Exception, match="missing"):
        parse_seed("")


def test_parse_bool_canonical_true_false_and_missing():
    assert parse_bool(True) is True
    assert parse_bool(False) is False
    assert parse_bool("True") is True
    assert parse_bool("False") is False
    assert parse_bool("") is None
    assert parse_bool("nan") is None
    assert parse_bool(1.0) is True
    assert parse_bool(0.0) is False
    with pytest.raises(Exception, match="non-canonical"):
        parse_bool("true")


def test_schema_kinds():
    assert is_integer_field("seed")
    assert is_boolean_field("placebo_false_effect_L")
    assert is_boolean_field("false_edge_any")
    assert is_categorical_field("cell_id")
    assert is_categorical_field("status")
    assert is_categorical_field("rng_mode")
    assert is_categorical_field("system_seed_mode")


def _typed_row(cell_id: str, seed: int, *, false_effect: bool, nire: float, missing: float):
    return {
        "cell_id": cell_id,
        "seed": seed,
        "rng_mode": "named_substreams",
        "system_seed_mode": "orthogonal_v3",
        "placebo_false_effect_L": false_effect,
        "false_edge_any": False,
        "nire_persistent_step_h26_L": nire,
        "placebo_relative_to_true_L": missing,
        "estimability_status_L": "ESTIMATED",
        "source_pool": "V3_SMOKE",
        "status": "ok",
    }


def test_csv_round_trip_uint64_bool_nan_float_and_categorical(tmp_path):
    original = _typed_row(
        "D_PM_RN_R3",
        SEED_GT_2P53,
        false_effect=True,
        nire=0.4375,
        missing=float("nan"),
    )
    original["false_edge_any"] = False
    path = tmp_path / "roundtrip.csv"
    write_csv(path, [original])
    loaded = parse_csv(path)
    assert len(loaded) == 1
    row = loaded[0]
    assert row["seed"] == SEED_GT_2P53
    assert type(row["seed"]) is int
    assert row["placebo_false_effect_L"] is True
    assert row["false_edge_any"] is False
    assert type(row["placebo_false_effect_L"]) is bool
    assert row["nire_persistent_step_h26_L"] == 0.4375
    assert math.isnan(row["placebo_relative_to_true_L"])
    assert row["cell_id"] == "D_PM_RN_R3"
    assert row["rng_mode"] == "named_substreams"
    assert row["system_seed_mode"] == "orthogonal_v3"
    assert row["status"] == "ok"
    assert row["estimability_status_L"] == "ESTIMATED"
    text = path.read_text(encoding="utf-8")
    assert str(SEED_GT_2P53) in text
    assert "True" in text
    assert "False" in text


def test_parse_record_coerces_evaluation_zero_one_flags():
    row = parse_record(
        {
            "cell_id": "A_PEXACT",
            "seed": str(SEED_2P53_PLUS_1),
            "placebo_false_effect_L": 1.0,
            "false_edge_any": 0.0,
            "estimable_L": 1,
        }
    )
    assert row["seed"] == SEED_2P53_PLUS_1
    assert row["placebo_false_effect_L"] is True
    assert row["false_edge_any"] is False
    assert row["estimable_L"] is True


def test_writer_includes_unexpected_metric_via_union_schema(tmp_path):
    row = _typed_row("A_PEXACT", SEED_2P53_PLUS_1, false_effect=False, nire=0.1, missing=0.0)
    row["unexpected_metric"] = 1.25
    path = tmp_path / "extra.csv"
    fields = write_csv(path, [row])
    assert "unexpected_metric" in fields
    assert "unexpected_metric" in fieldnames_of([row])
    loaded = parse_csv(path)
    assert loaded[0]["unexpected_metric"] == 1.25
    header = path.read_text(encoding="utf-8").splitlines()[0]
    assert "unexpected_metric" in header.split(",")


def test_append_record_expands_schema_instead_of_dropping(tmp_path):
    path = tmp_path / "grow.csv"
    first = _typed_row("A_PEXACT", SEED_GT_2P53, false_effect=False, nire=0.2, missing=0.0)
    existing = append_record(path, first, [])
    second = _typed_row("A_S100", SEED_C, false_effect=True, nire=0.3, missing=0.0)
    second["brand_new_metric"] = 9.5
    append_record(path, second, existing)
    header = path.read_text(encoding="utf-8").splitlines()[0]
    assert "brand_new_metric" in header.split(",")
    loaded = parse_csv(path)
    assert loaded[1]["brand_new_metric"] == 9.5
    assert math.isnan(loaded[0]["brand_new_metric"])


def test_writer_never_silently_drops_fields():
    combined = inspect.getsource(write_csv) + "\n" + inspect.getsource(append_record)
    assert 'extrasaction="raise"' in combined
    writer_calls = [line for line in combined.splitlines() if "csv.DictWriter" in line]
    assert writer_calls
    assert all("raise" in line for line in writer_calls)
    assert all("ignore" not in line for line in writer_calls)


def test_resume_is_idempotent_for_uint64_keys(tmp_path, design):
    source = inspect.getsource(run_v3.execute_plan)
    assert "done = _existing_keys(csv_path) if resume else set()" in source
    assert "existing_keys(csv_path)" in inspect.getsource(run_v3._existing_keys)

    regimes = v3_all_cells(design)
    cell_ids = tuple(list(regimes)[:2])
    seeds = (SEED_GT_2P53, SEED_2P53_PLUS_1, SEED_C)
    plan = run_v3.AnalysisPlan(
        pool="V3_SMOKE",
        cell_ids=cell_ids,
        seeds=seeds,
        rng_mode=RNG_NAMED,
        system_seed_mode=SEED_ORTHOGONAL,
        regimes={cid: regimes[cid] for cid in cell_ids},
    )
    expected_jobs = [(cid, seed) for cid in cell_ids for seed in seeds]
    assert len(expected_jobs) == 6

    partial = [
        _typed_row(expected_jobs[0][0], expected_jobs[0][1], false_effect=True, nire=0.2, missing=0.0),
        _typed_row(expected_jobs[1][0], expected_jobs[1][1], false_effect=False, nire=0.3, missing=0.0),
    ]
    csv_path = tmp_path / "V3_ANALYSIS_REPLICATES.csv"
    write_csv(csv_path, partial)
    keys = existing_keys(csv_path)
    assert keys == {
        (expected_jobs[0][0], expected_jobs[0][1]),
        (expected_jobs[1][0], expected_jobs[1][1]),
    }
    assert all(type(seed) is int for _, seed in keys)

    seen: list[tuple[str, int]] = []

    def runner(design_arg, regime, seed, rng_mode, system_seed_mode):
        seen.append((regime.cell_id, parse_seed(seed)))
        return _typed_row(regime.cell_id, parse_seed(seed), false_effect=False, nire=0.11, missing=0.0)

    summary = run_v3.execute_plan(
        design, plan, out_dir=tmp_path, runner=runner, authorized=False, resume=True
    )
    assert summary["n_expected"] == 6
    assert summary["n_completed"] == 6
    assert summary["n_unique_pairs"] == 6
    assert summary["n_duplicate_pairs"] == 0
    assert summary["n_failures"] == 0
    assert summary["n_attempted_this_invocation"] == 4
    assert seen == expected_jobs[2:]
    loaded = parse_csv(csv_path)
    actual_pairs = set(unique_pairs(loaded))
    assert actual_pairs == set(expected_jobs)
    assert len(loaded) == 6
    missing = set(expected_jobs) - actual_pairs
    extra = actual_pairs - set(expected_jobs)
    assert missing == set()
    assert extra == set()
    assert {row["seed"] for row in loaded} == set(seeds)
    for row in loaded:
        assert type(row["seed"]) is int
        assert type(row["placebo_false_effect_L"]) is bool

    seen.clear()
    summary2 = run_v3.execute_plan(
        design, plan, out_dir=tmp_path, runner=runner, authorized=False, resume=True
    )
    assert seen == []
    assert summary2["n_attempted_this_invocation"] == 0
    assert summary2["n_completed"] == 6
    assert summary2["n_duplicate_pairs"] == 0
    assert summary2["n_unique_pairs"] == 6
    assert summary2["n_failures"] == 0


def test_in_memory_summary_equals_csv_reloaded_summary(tmp_path):
    seeds = (SEED_GT_2P53, SEED_2P53_PLUS_1)
    records = []
    for seed in seeds:
        for cell in BLOCK_D:
            false_effect = "PM" in cell and "RN" in cell
            records.append(
                {
                    "cell_id": cell,
                    "seed": seed,
                    "rng_mode": "named_substreams",
                    "system_seed_mode": "orthogonal_v3",
                    "nire_persistent_step_h26_L": 0.55 if false_effect else 0.20,
                    "placebo_false_effect_L": false_effect,
                    "placebo_relative_to_true_L": float("nan") if false_effect else 0.05,
                    "false_edge_any": false_effect,
                    "estimability_status_L": "ESTIMATED",
                    "estimable_L": True,
                    "s8_real_pumping_present_L": True,
                }
            )
    in_memory = summarize_analysis(records, n_bootstrap=40)
    path = tmp_path / "summary_roundtrip.csv"
    write_csv(path, records)
    from_csv = summarize_analysis(parse_csv(path), n_bootstrap=40)
    scientific_equal(in_memory, from_csv)

    d_mem = in_memory["block_D_factorial"]
    d_csv = from_csv["block_D_factorial"]
    assert d_mem["outcomes"]["placebo_false_effect_L"]["main_pumping"]["n_paired_seeds"] == 2
    assert d_csv["outcomes"]["placebo_false_effect_L"]["main_pumping"]["n_paired_seeds"] == 2
    rate_mem = in_memory["rate_outcomes"]["per_cell"]["D_PM_RN_R3"]["placebo_false_effect_L"]["rate"]
    rate_csv = from_csv["rate_outcomes"]["per_cell"]["D_PM_RN_R3"]["placebo_false_effect_L"]["rate"]
    assert rate_mem == 1.0
    assert rate_csv == 1.0
    assert in_memory["rate_outcomes"]["per_cell"]["D_PE_RE_R0"]["placebo_false_effect_L"]["rate"] == 0.0

    contrast_mem = paired_contrast(
        records, "D_PE_RE_R0", "D_PM_RE_R0", "nire_persistent_step_h26_L", 1, "io_fixture", 40
    )
    contrast_csv = paired_contrast(
        parse_csv(path), "D_PE_RE_R0", "D_PM_RE_R0", "nire_persistent_step_h26_L", 1, "io_fixture", 40
    )
    scientific_equal(contrast_mem, contrast_csv)
    assert contrast_mem["n_paired_seeds"] == 2
    assert contrast_csv["n_paired_seeds"] == 2


def test_incomplete_plan_does_not_write_canonical_summary(tmp_path, design):
    regimes = v3_all_cells(design)
    cell_ids = tuple(list(regimes)[:2])
    seeds = (SEED_GT_2P53, SEED_2P53_PLUS_1)
    plan = run_v3.AnalysisPlan(
        pool="V3_SMOKE",
        cell_ids=cell_ids,
        seeds=seeds,
        rng_mode=RNG_NAMED,
        system_seed_mode=SEED_ORTHOGONAL,
        regimes={cid: regimes[cid] for cid in cell_ids},
    )
    stale = tmp_path / run_v3.CANONICAL_SUMMARY_NAME
    stale.write_text("{}", encoding="utf-8")

    def runner(design_arg, regime, seed, rng_mode, system_seed_mode):
        if parse_seed(seed) == SEED_2P53_PLUS_1:
            raise RuntimeError("injected failure")
        return _typed_row(regime.cell_id, parse_seed(seed), false_effect=False, nire=0.2, missing=0.0)

    summary = run_v3.execute_plan(
        design, plan, out_dir=tmp_path, runner=runner, authorized=False, resume=False
    )
    assert summary["n_failures"] == 2
    assert summary["n_completed"] < plan.expected_replicates
    result = run_v3.write_canonical_analysis_summary(plan, summary, tmp_path)
    assert result["wrote_canonical_summary"] is False
    assert result["validation"]["ANALYSIS_INCOMPLETE"] is True
    assert not (tmp_path / run_v3.CANONICAL_SUMMARY_NAME).exists()
    assert (tmp_path / run_v3.INCOMPLETE_MARKER_NAME).exists()
    marker = (tmp_path / run_v3.INCOMPLETE_MARKER_NAME).read_text(encoding="utf-8")
    assert "ANALYSIS_INCOMPLETE" in marker
    assert "NOT_WRITTEN" in marker


def test_complete_small_plan_may_write_canonical_summary(tmp_path, design):
    regimes = v3_all_cells(design)
    cell_ids = tuple(list(regimes)[:2])
    seeds = (SEED_GT_2P53, SEED_2P53_PLUS_1)
    plan = run_v3.AnalysisPlan(
        pool="V3_SMOKE",
        cell_ids=cell_ids,
        seeds=seeds,
        rng_mode=RNG_NAMED,
        system_seed_mode=SEED_ORTHOGONAL,
        regimes={cid: regimes[cid] for cid in cell_ids},
    )

    def runner(design_arg, regime, seed, rng_mode, system_seed_mode):
        return _typed_row(regime.cell_id, parse_seed(seed), false_effect=False, nire=0.2, missing=0.0)

    summary = run_v3.execute_plan(
        design, plan, out_dir=tmp_path, runner=runner, authorized=False, resume=False
    )
    result = run_v3.write_canonical_analysis_summary(
        plan, summary, tmp_path, n_bootstrap=20
    )
    assert result["validation"]["ok"] is True
    assert result["wrote_canonical_summary"] is True
    assert (tmp_path / run_v3.CANONICAL_SUMMARY_NAME).exists()
    assert not (tmp_path / run_v3.INCOMPLETE_MARKER_NAME).exists()


def test_v3_production_source_has_no_lossy_seed_coercion():
    offenders = []
    skip = {"summarize.py", "interventions.py", "metrics.py", "fit.py", "models.py", "identifiability.py"}
    for folder in ("src_v3", "scripts_v3"):
        for path in sorted((MODULE_ROOT / folder).glob("*.py")):
            if path.name in skip:
                continue
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "int(float(" in line:
                    offenders.append(f"{path.name}:{i}:{stripped}")
                if 'float(row["seed"])' in line or "float(row['seed'])" in line:
                    offenders.append(f"{path.name}:{i}:{stripped}")
                if "float(seed" in line and "parse_seed" not in line and "isinstance" not in line:
                    offenders.append(f"{path.name}:{i}:{stripped}")
    assert not offenders, offenders
