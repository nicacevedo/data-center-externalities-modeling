"""Frozen ANALYSIS launcher: refusal, preflight, executable full-run path, no ANALYSIS seeds.

This suite never supplies the ANALYSIS authorization token to `main()`, and never calls
`execute_plan(..., authorized=True)` on the `V3_ANALYSIS` pool. The full-run pathway is
proved by (a) inspecting the frozen `main()` wiring and (b) exercising `execute_plan` on
injected runners / non-ANALYSIS temporary plans.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from pathlib import Path

import pytest

from src_v3.design import (
    MODULE_ROOT,
    code_hash,
    design_hash,
    resolved_cell_table,
    seed_list,
    seed_pool_hash,
    v3_all_cells,
)
from src_v3.modes import RNG_LEGACY, RNG_NAMED, SEED_LEGACY, SEED_ORTHOGONAL

_SCRIPTS = MODULE_ROOT / "scripts_v3"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
# Register before exec_module: dataclasses.KW_ONLY (and frozen dataclasses generally)
# look up the module in sys.modules during class creation.
_SPEC = importlib.util.spec_from_file_location("run_v3_under_test", _SCRIPTS / "run_v3.py")
run_v3 = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules["run_v3_under_test"] = run_v3
_SPEC.loader.exec_module(run_v3)


def _live_freeze(design):
    return {
        "V3_DESIGN_HASH": design_hash(),
        "V3_CODE_HASH": code_hash(),
        "resolved_cell_manifest_hash": run_v3.resolved_cell_manifest_hash(design),
        "resolved_cell_count": 21,
        "seed_pool_hashes": {"V3_ANALYSIS": seed_pool_hash(design, "V3_ANALYSIS")},
    }


def test_main_refuses_missing_token(tmp_path):
    with pytest.raises(SystemExit, match="V3 ANALYSIS refused"):
        run_v3.main(["--out-dir", str(tmp_path)])


def test_main_refuses_wrong_token(tmp_path):
    with pytest.raises(SystemExit, match="V3 ANALYSIS refused"):
        run_v3.main(["--authorize", "WRONG_TOKEN", "--out-dir", str(tmp_path)])


def test_main_refuses_non_analysis_pool(tmp_path):
    with pytest.raises(SystemExit, match="ANALYSIS launcher only"):
        run_v3.main(["--pool", "V3_SMOKE", "--out-dir", str(tmp_path)])


def test_frozen_token_exists_and_this_suite_does_not_supply_it(design):
    token = str(design["v3"]["analysis_authorization_token"])
    assert token.startswith("I_AUTHORIZE_")
    source = Path(__file__).read_text(encoding="utf-8")
    assert token not in source
    assert "authorized=True" in Path(run_v3.__file__).read_text(encoding="utf-8")


def test_main_source_wires_token_then_preflight_then_authorized_execute():
    """Pass 2 requires zero source changes: the frozen main() already executes the plan."""
    source = inspect.getsource(run_v3.main)
    assert "args.authorize != token" in source
    assert "preflight(" in source
    assert "execute_plan(" in source
    assert "authorized=True" in source
    assert "summarize_analysis(" in source
    assert source.index("args.authorize != token") < source.index("execute_plan(")


def test_build_plan_is_exactly_21_by_200(design):
    plan = run_v3.build_plan(design)
    assert plan.pool == "V3_ANALYSIS"
    assert plan.rng_mode == RNG_NAMED
    assert plan.system_seed_mode == SEED_ORTHOGONAL
    assert len(plan.cell_ids) == 21
    assert len(plan.seeds) == 200
    assert plan.expected_replicates == 4200
    assert list(plan.cell_ids) == list(design["v3"]["cell_ids"])
    assert list(plan.cell_ids) == list(v3_all_cells(design))
    jobs = list(plan.jobs())
    assert len(jobs) == 4200
    assert jobs[0] == (plan.cell_ids[0], plan.seeds[0])
    assert jobs[-1] == (plan.cell_ids[-1], plan.seeds[-1])


def test_preflight_accepts_a_matching_frozen_state(design, tmp_path):
    plan = run_v3.build_plan(design)
    report = run_v3.preflight(
        design,
        plan,
        freeze=_live_freeze(design),
        analysis_dir=tmp_path,
        strict=True,
    )
    assert report["ok"] is True
    assert report["n_failed"] == 0
    assert report["expected_replicates"] == 4200
    assert report["V3_ANALYSIS_REPLICATES_RUN"] == 0
    names = {c["check"] for c in report["checks"]}
    for required in (
        "mode_pair_legal",
        "mode_pair_is_substantive",
        "no_v3_gates",
        "cell_count_21",
        "n_analysis_seeds_per_cell_200",
        "expected_replicates_4200",
        "V3_DESIGN_HASH",
        "V3_CODE_HASH",
        "V3_ANALYSIS_seed_pool_hash",
        "resolved_cell_manifest_hash",
        "V2_DESIGN_HASH_unchanged",
        "V2_CODE_HASH_unchanged",
        "seed_pools_pairwise_disjoint",
        "no_pre_existing_analysis_replicates",
    ):
        assert required in names


def test_preflight_rejects_legacy_mode_pair(design, tmp_path):
    plan = run_v3.build_plan(design, rng_mode=RNG_LEGACY, system_seed_mode=SEED_LEGACY)
    with pytest.raises(run_v3.PreflightError, match="mode_pair_is_substantive"):
        run_v3.preflight(
            design, plan, freeze=_live_freeze(design), analysis_dir=tmp_path, strict=True
        )


def test_preflight_rejects_hash_mismatch(design, tmp_path):
    freeze = _live_freeze(design)
    freeze["V3_CODE_HASH"] = "0" * 64
    plan = run_v3.build_plan(design)
    with pytest.raises(run_v3.PreflightError, match="V3_CODE_HASH"):
        run_v3.preflight(design, plan, freeze=freeze, analysis_dir=tmp_path, strict=True)


def test_execute_plan_refuses_analysis_pool_without_authorized(design, tmp_path):
    plan = run_v3.build_plan(design)
    with pytest.raises(run_v3.AuthorizationError, match="authorized=True"):
        run_v3.execute_plan(design, plan, out_dir=tmp_path, authorized=False)


def test_execute_plan_runs_a_temporary_non_analysis_plan_against_a_mock(design, tmp_path):
    """The orchestration that Pass 2 will use, exercised without any ANALYSIS seed."""
    regimes = v3_all_cells(design)
    cell_ids = tuple(list(regimes)[:2])
    seeds = tuple(int(s) for s in seed_list(design, "V3_SMOKE")[:2])
    plan = run_v3.AnalysisPlan(
        pool="V3_SMOKE",
        cell_ids=cell_ids,
        seeds=seeds,
        rng_mode=RNG_NAMED,
        system_seed_mode=SEED_ORTHOGONAL,
        regimes={cid: regimes[cid] for cid in cell_ids},
    )
    seen: list[tuple[str, int]] = []

    def runner(design_arg, regime, seed, rng_mode, system_seed_mode):
        seen.append((regime.cell_id, int(seed)))
        assert rng_mode == RNG_NAMED
        assert system_seed_mode == SEED_ORTHOGONAL
        assert design_arg is design
        return {
            "cell_id": regime.cell_id,
            "seed": int(seed),
            "rng_mode": rng_mode,
            "system_seed_mode": system_seed_mode,
            "estimability_status_L": "ESTIMATED",
            "nire_persistent_step_h26_L": 0.0,
        }

    summary = run_v3.execute_plan(
        design, plan, out_dir=tmp_path, runner=runner, authorized=False
    )
    assert summary["n_expected"] == 4
    assert summary["n_completed"] == 4
    assert summary["n_failures"] == 0
    assert seen == [(cid, seed) for cid in cell_ids for seed in seeds]
    csv_path = tmp_path / "V3_ANALYSIS_REPLICATES.csv"
    jsonl_path = tmp_path / "V3_ANALYSIS_REPLICATES.jsonl"
    assert csv_path.exists()
    assert jsonl_path.exists()
    assert csv_path.read_text(encoding="utf-8").count("\n") == 5  # header + 4


def test_preflight_only_cli_executes_zero_replicates(design, tmp_path, monkeypatch):
    freeze_path = tmp_path / "DESIGN_V3_FREEZE.json"
    freeze_path.write_text(json.dumps(_live_freeze(design)), encoding="utf-8")
    monkeypatch.setattr(run_v3, "FREEZE_JSON", freeze_path)
    rc = run_v3.main(["--preflight-only", "--out-dir", str(tmp_path / "analysis")])
    assert rc == 0
    assert not list((tmp_path / "analysis").glob("*replicates*"))


def test_resolved_cell_manifest_hash_is_stable_to_the_21_cell_matrix(design):
    table = resolved_cell_table(design)
    assert len(table) == 21
    assert [row["cell_id"] for row in table] == list(design["v3"]["cell_ids"])
    first = run_v3.resolved_cell_manifest_hash(design)
    second = run_v3.resolved_cell_manifest_hash(design)
    assert first == second
    assert len(first) == 64
