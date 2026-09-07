#!/usr/bin/env python3
"""V3 ANALYSIS launcher. FROZEN AND EXECUTABLE.

Contract (Pass 1.1 hard requirement):

    missing / wrong authorization              -> REFUSE
    correct authorization
      + correct V3_DESIGN_HASH
      + correct V3_CODE_HASH
      + correct V3_ANALYSIS seed-pool hash
      + correct 21-cell resolved manifest hash
      + correct n = 200 ANALYSIS seeds per cell
      + correct substantive mode pair          -> execute exactly the frozen 21 x 200 plan

The substantive mode pair is exactly `(named_substreams, orthogonal_v3)`. The legacy pair
`(legacy_sequential, legacy_v2)` exists only for the V2 bit-for-bit parity script and is
rejected here. Mixed combinations are illegal everywhere.

Pass 2 therefore requires ZERO source-code changes:

    python scripts_v3/freeze_protocol_v3.py                 # verify / refresh hashes
    python scripts_v3/run_v3.py --preflight-only            # verify invariants, runs nothing
    python scripts_v3/run_v3.py --authorize <TOKEN>         # run 4200 replicates

`--preflight-only` executes ZERO replicates and needs no token, so the whole invariant and
orchestration path is testable without touching a substantive seed. `execute_plan` refuses
to run the `V3_ANALYSIS` pool unless `authorized=True` is passed explicitly, which the test
suite never does; tests exercise orchestration against injected runners and non-ANALYSIS
temporary plans instead.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

import _bootstrap_path  # noqa: F401

from src_v3.design import (
    MODULE_ROOT,
    code_hash,
    design_hash,
    load_design,
    resolved_cell_table,
    seed_list,
    seed_pool_hash,
    v2_parent_code_hash,
    v2_parent_design_hash,
    v3_all_cells,
    V2_EXPECTED_CODE_HASH,
    V2_EXPECTED_DESIGN_HASH,
)
from src_v3.evaluation import run_replicate
from src_v3.modes import RNG_NAMED, SEED_ORTHOGONAL, require_legal
from src_v3.summarize_v3 import summarize_analysis

ANALYSIS_POOL = "V3_ANALYSIS"
EXPECTED_CELLS = 21
EXPECTED_SEEDS_PER_CELL = 200
EXPECTED_REPLICATES = EXPECTED_CELLS * EXPECTED_SEEDS_PER_CELL
FREEZE_JSON = MODULE_ROOT / "outputs" / "provenance" / "DESIGN_V3_FREEZE.json"
ANALYSIS_DIR = MODULE_ROOT / "outputs" / "analysis"
BENCHMARK_JSON = MODULE_ROOT / "outputs" / "benchmarks" / "BENCHMARKS_V3.json"


class PreflightError(RuntimeError):
    """A frozen-state invariant failed. The sweep must not run."""


class AuthorizationError(RuntimeError):
    """The ANALYSIS authorization token was missing or incorrect."""


@dataclass(frozen=True)
class AnalysisPlan:
    """A fully materialized execution plan. Holds cell ids and seeds, nothing else."""

    pool: str
    cell_ids: tuple[str, ...]
    seeds: tuple[int, ...]
    rng_mode: str
    system_seed_mode: str
    regimes: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def expected_replicates(self) -> int:
        return len(self.cell_ids) * len(self.seeds)

    def jobs(self):
        for cell_id in self.cell_ids:
            for seed in self.seeds:
                yield cell_id, int(seed)


def resolved_cell_manifest_hash(design: dict[str, Any]) -> str:
    payload = json.dumps(resolved_cell_table(design), sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_plan(
    design: dict[str, Any],
    pool: str = ANALYSIS_POOL,
    rng_mode: str = RNG_NAMED,
    system_seed_mode: str = SEED_ORTHOGONAL,
) -> AnalysisPlan:
    """Materialize the frozen execution plan for a named seed pool."""
    require_legal(rng_mode, system_seed_mode)
    regimes = v3_all_cells(design)
    return AnalysisPlan(
        pool=str(pool),
        cell_ids=tuple(regimes),
        seeds=tuple(int(s) for s in seed_list(design, pool)),
        rng_mode=str(rng_mode),
        system_seed_mode=str(system_seed_mode),
        regimes=regimes,
    )


def load_freeze(path: Path | None = None) -> dict[str, Any]:
    target = path or FREEZE_JSON
    if not target.exists():
        raise PreflightError(
            f"missing frozen provenance file {target}; run scripts_v3/freeze_protocol_v3.py"
        )
    with open(target, "r", encoding="utf-8") as handle:
        return json.load(handle)


def preflight(
    design: dict[str, Any],
    plan: AnalysisPlan,
    freeze: dict[str, Any] | None = None,
    freeze_path: Path | None = None,
    analysis_dir: Path | None = None,
    allow_existing_outputs: bool = False,
    strict: bool = True,
) -> dict[str, Any]:
    """Verify every frozen-state invariant the substantive sweep depends on.

    Returns a report. Raises `PreflightError` on the first failure when `strict`.
    """
    freeze = freeze if freeze is not None else load_freeze(freeze_path)
    analysis_dir = analysis_dir or ANALYSIS_DIR
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, expected: Any = None, observed: Any = None) -> None:
        checks.append(
            {"check": name, "ok": bool(ok), "expected": expected, "observed": observed}
        )

    # -- mode legality and substantiveness -------------------------------------------
    try:
        require_legal(plan.rng_mode, plan.system_seed_mode)
        legal = True
    except ValueError:
        legal = False
    check("mode_pair_legal", legal, [RNG_NAMED, SEED_ORTHOGONAL], [plan.rng_mode, plan.system_seed_mode])
    check(
        "mode_pair_is_substantive",
        (plan.rng_mode, plan.system_seed_mode) == (RNG_NAMED, SEED_ORTHOGONAL),
        [RNG_NAMED, SEED_ORTHOGONAL],
        [plan.rng_mode, plan.system_seed_mode],
    )
    check(
        "mode_pair_matches_config",
        plan.rng_mode == str(design["v3"]["rng_mode_substantive"])
        and plan.system_seed_mode == str(design["v3"]["system_seed_mode_substantive"]),
        [design["v3"]["rng_mode_substantive"], design["v3"]["system_seed_mode_substantive"]],
        [plan.rng_mode, plan.system_seed_mode],
    )

    # -- design shape ----------------------------------------------------------------
    check("no_v3_gates", design.get("gates") in ({}, None), {}, design.get("gates"))
    check("pool_is_analysis", plan.pool == ANALYSIS_POOL, ANALYSIS_POOL, plan.pool)
    check("cell_count_21", len(plan.cell_ids) == EXPECTED_CELLS, EXPECTED_CELLS, len(plan.cell_ids))
    check(
        "cell_ids_match_config",
        list(plan.cell_ids) == [str(c) for c in design["v3"]["cell_ids"]],
        list(design["v3"]["cell_ids"]),
        list(plan.cell_ids),
    )
    check(
        "n_analysis_seeds_per_cell_200",
        len(plan.seeds) == EXPECTED_SEEDS_PER_CELL
        and int(design["v3"]["n_analysis_seeds_per_cell"]) == EXPECTED_SEEDS_PER_CELL
        and int(design["seeds"]["pools"][ANALYSIS_POOL]["n_seeds"]) == EXPECTED_SEEDS_PER_CELL,
        EXPECTED_SEEDS_PER_CELL,
        len(plan.seeds),
    )
    check(
        "expected_replicates_4200",
        plan.expected_replicates == EXPECTED_REPLICATES,
        EXPECTED_REPLICATES,
        plan.expected_replicates,
    )
    check("seeds_unique", len(set(plan.seeds)) == len(plan.seeds), len(plan.seeds), len(set(plan.seeds)))
    check(
        "seeds_uint64_range",
        all(0 <= int(s) < 2**64 for s in plan.seeds),
        "0 <= seed < 2**64",
        None,
    )

    # -- frozen hashes ---------------------------------------------------------------
    live_design = design_hash()
    live_code = code_hash()
    live_manifest = resolved_cell_manifest_hash(design)
    live_seed_hash = seed_pool_hash(design, ANALYSIS_POOL)
    check("V3_DESIGN_HASH", live_design == freeze.get("V3_DESIGN_HASH"), freeze.get("V3_DESIGN_HASH"), live_design)
    check("V3_CODE_HASH", live_code == freeze.get("V3_CODE_HASH"), freeze.get("V3_CODE_HASH"), live_code)
    check(
        "resolved_cell_manifest_hash",
        live_manifest == freeze.get("resolved_cell_manifest_hash"),
        freeze.get("resolved_cell_manifest_hash"),
        live_manifest,
    )
    check(
        "V3_ANALYSIS_seed_pool_hash",
        live_seed_hash == (freeze.get("seed_pool_hashes") or {}).get(ANALYSIS_POOL),
        (freeze.get("seed_pool_hashes") or {}).get(ANALYSIS_POOL),
        live_seed_hash,
    )
    check(
        "freeze_resolved_cell_count_21",
        int(freeze.get("resolved_cell_count", -1)) == EXPECTED_CELLS,
        EXPECTED_CELLS,
        freeze.get("resolved_cell_count"),
    )

    # -- V2 immutability -------------------------------------------------------------
    v2_design = v2_parent_design_hash()
    v2_code = v2_parent_code_hash()
    check("V2_DESIGN_HASH_unchanged", v2_design == V2_EXPECTED_DESIGN_HASH, V2_EXPECTED_DESIGN_HASH, v2_design)
    check("V2_CODE_HASH_unchanged", v2_code == V2_EXPECTED_CODE_HASH, V2_EXPECTED_CODE_HASH, v2_code)

    # -- seed-pool disjointness ------------------------------------------------------
    overlap = _seed_overlap(design)
    check("seed_pools_pairwise_disjoint", not overlap, [], overlap)

    # -- output guard ----------------------------------------------------------------
    existing = sorted(p.name for p in analysis_dir.glob("*replicates*")) if analysis_dir.exists() else []
    check(
        "no_pre_existing_analysis_replicates",
        allow_existing_outputs or not existing,
        [],
        existing,
    )

    failures = [c for c in checks if not c["ok"]]
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "pool": plan.pool,
        "rng_mode": plan.rng_mode,
        "system_seed_mode": plan.system_seed_mode,
        "n_cells": len(plan.cell_ids),
        "n_seeds": len(plan.seeds),
        "expected_replicates": plan.expected_replicates,
        "V3_DESIGN_HASH": live_design,
        "V3_CODE_HASH": live_code,
        "resolved_cell_manifest_hash": live_manifest,
        "V3_ANALYSIS_seed_pool_hash": live_seed_hash,
        "V2_PARENT_DESIGN_HASH": v2_design,
        "V2_PARENT_CODE_HASH": v2_code,
        "checks": checks,
        "n_checks": len(checks),
        "n_failed": len(failures),
        "ok": not failures,
        "V3_ANALYSIS_REPLICATES_RUN": 0,
    }
    if strict and failures:
        raise PreflightError(
            "V3 ANALYSIS preflight failed: "
            + "; ".join(
                f"{c['check']} expected={c['expected']!r} observed={c['observed']!r}"
                for c in failures
            )
        )
    return report


def _seed_overlap(design: dict[str, Any]) -> list[list[str]]:
    """Pairwise overlap between every V3 and V2 seed pool. Empty list means disjoint."""
    from groundwater_identifiability_synthetic.src.design import (
        load_design as load_v2,
        seed_list as v2_seed_list,
    )
    from src_v3.design import V2_PARENT_ROOT

    v2 = load_v2(V2_PARENT_ROOT / "config" / "design_v2.yaml")
    pools = {
        f"V3:{p}": set(seed_list(design, p))
        for p in ("V3_DETERMINISM", "V3_SMOKE", "V3_BENCHMARK", ANALYSIS_POOL)
    }
    pools.update(
        {f"V2:{p}": set(v2_seed_list(v2, p)) for p in ("G0", "CALIBRATION", "SMOKE", "ANALYSIS")}
    )
    names = list(pools)
    overlap: list[list[str]] = []
    for i, ni in enumerate(names):
        for nj in names[i + 1 :]:
            if pools[ni] & pools[nj]:
                overlap.append([ni, nj])
    return overlap


def _existing_keys(csv_path: Path) -> set[tuple[str, int]]:
    if not csv_path.exists():
        return set()
    keys: set[tuple[str, int]] = set()
    with open(csv_path, "r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                keys.add((str(row["cell_id"]), int(float(row["seed"]))))
            except (KeyError, TypeError, ValueError):
                continue
    return keys


def execute_plan(
    design: dict[str, Any],
    plan: AnalysisPlan,
    out_dir: Path,
    runner: Callable[..., dict[str, Any]] = run_replicate,
    authorized: bool = False,
    resume: bool = False,
    progress_every: int = 100,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Execute exactly `plan.expected_replicates` replicates and stream them to disk.

    `authorized` must be explicitly True for the `V3_ANALYSIS` pool. This is the hard
    interlock that lets the test suite exercise this function against injected runners and
    non-ANALYSIS temporary plans without any possibility of running a substantive seed.
    """
    if plan.pool == ANALYSIS_POOL and not authorized:
        raise AuthorizationError(
            "execute_plan refuses the V3_ANALYSIS pool without authorized=True"
        )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "V3_ANALYSIS_REPLICATES.csv"
    jsonl_path = out_dir / "V3_ANALYSIS_REPLICATES.jsonl"
    done = _existing_keys(csv_path) if resume else set()
    if not resume:
        for path in (csv_path, jsonl_path):
            if path.exists():
                path.unlink()

    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    fieldnames: list[str] | None = None
    if resume and csv_path.exists():
        with open(csv_path, "r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or []) or None
            records.extend(dict(row) for row in reader)

    started = time.perf_counter()
    n_attempted = 0
    with open(jsonl_path, "a", encoding="utf-8") as stream:
        for cell_id, seed in plan.jobs():
            if (cell_id, seed) in done:
                continue
            n_attempted += 1
            try:
                record = runner(
                    design,
                    plan.regimes[cell_id],
                    int(seed),
                    rng_mode=plan.rng_mode,
                    system_seed_mode=plan.system_seed_mode,
                )
            except Exception as exc:  # a single replicate must not kill the sweep
                failures.append(
                    {
                        "cell_id": cell_id,
                        "seed": int(seed),
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    }
                )
                continue
            record = dict(record)
            record.setdefault("cell_id", cell_id)
            record["seed"] = int(seed)
            record["source_pool"] = plan.pool
            records.append(record)
            stream.write(json.dumps(record, default=str) + "\n")
            if fieldnames is None:
                fieldnames = sorted(record)
                with open(csv_path, "w", encoding="utf-8", newline="") as handle:
                    csv.DictWriter(handle, fieldnames=fieldnames).writeheader()
            with open(csv_path, "a", encoding="utf-8", newline="") as handle:
                csv.DictWriter(
                    handle, fieldnames=fieldnames, extrasaction="ignore"
                ).writerow(record)
            if progress_every and len(records) % progress_every == 0:
                log(f"  {len(records)}/{plan.expected_replicates} replicates")
    elapsed = time.perf_counter() - started

    def _count(field_name: str, value: str) -> int:
        return sum(1 for r in records if str(r.get(field_name, "")) == value)

    return {
        "pool": plan.pool,
        "rng_mode": plan.rng_mode,
        "system_seed_mode": plan.system_seed_mode,
        "n_expected": plan.expected_replicates,
        "n_completed": len(records),
        "n_attempted_this_invocation": n_attempted,
        "n_failures": len(failures),
        "failures": failures,
        "elapsed_s": elapsed,
        "NOT_ESTIMABLE_L": _count("estimability_status_L", "NOT_ESTIMABLE"),
        "FIT_FAILED_L": _count("estimability_status_L", "FIT_FAILED"),
        "NOT_ESTIMABLE_N": _count("estimability_status_N", "NOT_ESTIMABLE"),
        "FIT_FAILED_N": _count("estimability_status_N", "FIT_FAILED"),
        "replicates_csv": str(csv_path),
        "replicates_jsonl": str(jsonl_path),
        "records": records,
    }


def _load_benchmarks() -> tuple[dict[str, dict] | None, list[dict] | None]:
    if not BENCHMARK_JSON.exists():
        return None, None
    with open(BENCHMARK_JSON, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    rows = {str(r["cell_id"]): r for r in payload.get("rows", [])}
    return (rows or None), (payload.get("convergence") or None)


def main(argv: Sequence[str] | None = None) -> int:
    design = load_design()
    token = str(design["v3"]["analysis_authorization_token"])
    parser = argparse.ArgumentParser(
        description="V3 ANALYSIS launcher (frozen 21 x 200 substantive sweep)."
    )
    parser.add_argument("--authorize", default="", help="explicit ANALYSIS authorization token")
    parser.add_argument("--pool", default=ANALYSIS_POOL, help="must be V3_ANALYSIS")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="verify every frozen invariant and print the plan; executes ZERO replicates",
    )
    parser.add_argument("--resume", action="store_true", help="skip (cell, seed) pairs already on disk")
    parser.add_argument("--out-dir", default=str(ANALYSIS_DIR))
    parser.add_argument("--no-summarize", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.pool != ANALYSIS_POOL:
        raise SystemExit("run_v3.py is the ANALYSIS launcher only")

    plan = build_plan(design)
    out_dir = Path(args.out_dir)

    if args.preflight_only:
        report = preflight(
            design,
            plan,
            analysis_dir=out_dir,
            allow_existing_outputs=bool(args.resume),
            strict=False,
        )
        print(json.dumps(report, indent=2, default=str))
        print("PREFLIGHT_ONLY: V3_ANALYSIS_REPLICATES_RUN=0")
        return 0 if report["ok"] else 1

    if args.authorize != token:
        raise SystemExit(
            "V3 ANALYSIS refused: missing/incorrect --authorize token. "
            "V3_ANALYSIS_REPLICATES_RUN=0"
        )

    report = preflight(
        design,
        plan,
        analysis_dir=out_dir,
        allow_existing_outputs=bool(args.resume),
        strict=True,
    )
    print(
        f"preflight ok: {report['n_checks']} invariants; "
        f"{plan.expected_replicates} replicates over {len(plan.cell_ids)} cells"
    )

    summary = execute_plan(
        design,
        plan,
        out_dir=out_dir,
        authorized=True,
        resume=bool(args.resume),
    )
    benchmarks, convergence = _load_benchmarks()

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "phase": "PASS_2_ANALYSIS",
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "authorized": True,
        "preflight": report,
        "execution": {k: v for k, v in summary.items() if k != "records"},
        "V3_ANALYSIS_POOL_FROZEN": True,
        "V3_ANALYSIS_REPLICATES_RUN": summary["n_completed"],
        "V3_ANALYSIS_OUTCOMES_INSPECTED": True,
    }
    with open(out_dir / "RUN_MANIFEST_V3_ANALYSIS.json", "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, default=str)
        handle.write("\n")

    if not args.no_summarize:
        payload = summarize_analysis(
            summary["records"], benchmarks=benchmarks, convergence=convergence
        )
        with open(out_dir / "V3_ANALYSIS_SUMMARY.json", "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)
            handle.write("\n")

    if summary["n_failures"] or summary["n_completed"] != plan.expected_replicates:
        raise SystemExit(
            f"V3 ANALYSIS incomplete: {summary['n_completed']}/{plan.expected_replicates} "
            f"failures={summary['n_failures']}"
        )
    print(
        f"V3 ANALYSIS complete: {summary['n_completed']}/{plan.expected_replicates} "
        f"in {summary['elapsed_s']:.1f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
