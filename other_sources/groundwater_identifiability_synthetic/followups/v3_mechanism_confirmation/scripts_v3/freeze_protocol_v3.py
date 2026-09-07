#!/usr/bin/env python3
"""Freeze V3 design/code hashes, seed pools, and parent manifests. No ANALYSIS."""

from __future__ import annotations

import csv
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import _bootstrap_path  # noqa: F401
import numpy as np

from src_v3.design import (
    CODE_GLOBS,
    DESIGN_ARTIFACTS,
    MODULE_ROOT,
    V2_PARENT_ROOT,
    code_files,
    code_hash,
    design_hash,
    load_design,
    resolved_cell_table,
    seed_list,
    seed_pool_hash,
    sha256_file,
    v2_parent_code_hash,
    v2_parent_design_hash,
    v3_all_cells,
)
from src_v3.modes import LEGAL_PAIRS

PROVENANCE = MODULE_ROOT / "outputs" / "provenance"
CHANGED_VENDORED = {
    "src_v3/design.py",
    "src_v3/dgp.py",
    "src_v3/observations.py",
    "src_v3/evaluation.py",
    "src_v3/plan.py",
    "src_v3/__init__.py",
}


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def parent_manifest_rows() -> list[dict]:
    rows = []
    v2_src = V2_PARENT_ROOT / "src"
    for parent in sorted(v2_src.glob("*.py")):
        vendored = MODULE_ROOT / "src_v3" / parent.name
        parent_hash = sha256_file(parent)
        vendored_hash = sha256_file(vendored)
        rel = f"src_v3/{parent.name}"
        classification = "changed" if rel in CHANGED_VENDORED else "unchanged"
        if classification == "unchanged" and parent_hash != vendored_hash:
            raise SystemExit(f"unlisted vendored change: {rel}")
        if classification == "changed" and parent_hash == vendored_hash:
            raise SystemExit(f"listed as changed but identical: {rel}")
        rows.append(
            {
                "parent_path": f"src/{parent.name}",
                "parent_sha256": parent_hash,
                "vendored_path": rel,
                "vendored_sha256": vendored_hash,
                "classification": classification,
            }
        )
    return rows


def main() -> int:
    design = load_design()
    if design.get("gates") not in ({}, None):
        raise SystemExit("V3 design must have gates: {}")
    cells = v3_all_cells(design)
    if len(cells) != 21:
        raise SystemExit(f"expected 21 cells, found {len(cells)}")

    v2_design_h = v2_parent_design_hash()
    v2_code_h = v2_parent_code_hash()
    from src_v3.design import V2_EXPECTED_CODE_HASH, V2_EXPECTED_DESIGN_HASH

    if v2_design_h != V2_EXPECTED_DESIGN_HASH:
        raise SystemExit("V2 DESIGN_HASH mutated")
    if v2_code_h != V2_EXPECTED_CODE_HASH:
        raise SystemExit("V2 CODE_HASH mutated")

    from groundwater_identifiability_synthetic.src.design import (
        load_design as load_v2,
        seed_list as v2_seed_list,
        seed_pool_hash as v2_seed_pool_hash,
    )

    v2 = load_v2(V2_PARENT_ROOT / "config" / "design_v2.yaml")
    v3_pools = ["V3_DETERMINISM", "V3_SMOKE", "V3_BENCHMARK", "V3_ANALYSIS"]
    v3_sets = {p: set(seed_list(design, p)) for p in v3_pools}
    v2_sets = {p: set(v2_seed_list(v2, p)) for p in ("G0", "CALIBRATION", "SMOKE", "ANALYSIS")}
    all_named = [(f"V3:{k}", v) for k, v in v3_sets.items()] + [(f"V2:{k}", v) for k, v in v2_sets.items()]
    for i, (ni, si) in enumerate(all_named):
        for nj, sj in all_named[i + 1 :]:
            if si & sj:
                raise SystemExit(f"seed overlap {ni} vs {nj}")

    # The benchmark convergence prefixes must be strictly nested subsets of one pool.
    bench_seeds = seed_list(design, "V3_BENCHMARK")
    for m in design["seeds"]["pools"]["V3_BENCHMARK"].get("convergence_prefixes", []):
        m = int(m)
        root = np.random.SeedSequence(
            entropy=int(design["seeds"]["pools"]["V3_BENCHMARK"]["entropy"])
        )
        prefix = [int(c.generate_state(1, dtype=np.uint64)[0]) for c in root.spawn(m)]
        if prefix != bench_seeds[:m]:
            raise SystemExit(f"V3_BENCHMARK prefix {m} is not nested")

    table = resolved_cell_table(design)
    table_payload = json.dumps(table, sort_keys=True).encode("utf-8")
    table_hash = hashlib.sha256(table_payload).hexdigest()

    PROVENANCE.mkdir(parents=True, exist_ok=True)
    parent_rows = parent_manifest_rows()
    _write_csv(PROVENANCE / "V2_PARENT_MANIFEST.csv", parent_rows)
    _write_csv(PROVENANCE / "DESIGN_V3_FREEZE_MANIFEST.csv", [
        {"relative_path": rel, "sha256": sha256_file(MODULE_ROOT / rel)}
        for rel in DESIGN_ARTIFACTS
    ])
    _write_csv(
        PROVENANCE / "CODE_MANIFEST_V3.csv",
        [
            {
                "relative_path": p.relative_to(MODULE_ROOT).as_posix(),
                "sha256": sha256_file(p),
            }
            for p in code_files()
        ],
    )
    _write_csv(PROVENANCE / "RESOLVED_CELLS_V3.csv", table)

    v3_design_h = design_hash()
    v3_code_h = code_hash()
    seed_hashes = {p: seed_pool_hash(design, p) for p in v3_pools}
    v2_seed_hashes = {p: v2_seed_pool_hash(v2, p) for p in ("G0", "CALIBRATION", "SMOKE", "ANALYSIS")}

    bench_spec = design["seeds"]["pools"]["V3_BENCHMARK"]
    freeze = {
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "checkpoint": "PASS_1_2_EXACT_IO_RESUME_HARDENING",
        "design_version": design["design_version"],
        "V3_DESIGN_HASH": v3_design_h,
        "V3_CODE_HASH": v3_code_h,
        "V2_PARENT_DESIGN_HASH": v2_design_h,
        "V2_PARENT_CODE_HASH": v2_code_h,
        "resolved_cell_count": 21,
        "resolved_cell_manifest_hash": table_hash,
        "gates": {},
        "legal_mode_pairs": [list(p) for p in sorted(LEGAL_PAIRS)],
        "seed_pool_hashes": seed_hashes,
        "v2_seed_pool_hashes": v2_seed_hashes,
        "n_seeds": {p: int(design["seeds"]["pools"][p]["n_seeds"]) for p in v3_pools},
        "V3_ANALYSIS_POOL_FROZEN": True,
        "V3_ANALYSIS_REPLICATES_RUN": 0,
        "V3_ANALYSIS_OUTCOMES_INSPECTED": False,
        "platform": platform.platform(),
        "code_globs": list(CODE_GLOBS),
        "design_artifacts": list(DESIGN_ARTIFACTS),
        "benchmark_pool": {
            "name": "V3_BENCHMARK",
            "n_seeds": int(bench_spec["n_seeds"]),
            "previous_n_seeds_pass1": int(bench_spec.get("previous_n_seeds_pass1", 16)),
            "convergence_prefixes": [int(m) for m in bench_spec.get("convergence_prefixes", [])],
            "prefix_nesting_verified": True,
            "role": str(bench_spec["role"]),
        },
        "pass_1_1_change_summary": {
            "cells_changed": 0,
            "resolved_cell_count": 21,
            "ANALYSIS_seed_count_changed": 0,
            "ANALYSIS_seeds_per_cell": int(design["v3"]["n_analysis_seeds_per_cell"]),
            "BENCHMARK_pool_count_change": (
                f"{int(bench_spec.get('previous_n_seeds_pass1', 16))} -> "
                f"{int(bench_spec['n_seeds'])}"
            ),
            "benchmark_definitions_changed": True,
            "launcher_now_executes_frozen_full_run": True,
            "source_changes_required_for_pass_2": 0,
        },
        "pass_1_2_change_summary": {
            "cells_changed": 0,
            "resolved_cell_count": 21,
            "ANALYSIS_seed_count_changed": 0,
            "ANALYSIS_seeds_per_cell": int(design["v3"]["n_analysis_seeds_per_cell"]),
            "BENCHMARK_n": int(bench_spec["n_seeds"]),
            "hypotheses_unchanged": True,
            "sesoi_unchanged": True,
            "gates": {},
            "exact_uint64_provenance": True,
            "typed_scientific_csv": True,
            "resume_exact_integer_keys": True,
            "canonical_summary_requires_complete_result_set": True,
            "source_changes_required_for_pass_2": 0,
        },
        "benchmark_layers": {
            "ordering": list(design["benchmark_layers"]["ordering"]),
            "decomposition_is_additive": False,
            "companions": sorted(design["benchmark_layers"]["companions"]),
            "f_intervention_domain": str(
                design["benchmark_layers"]["f_intervention_global_validity"]["parameter_domain"]
            ),
            "paper_language": str(
                design["benchmark_layers"]["f_intervention_global_validity"].get(
                    "paper_language",
                    "numerically globally verified over the full extended-real response parameterization",
                )
            ),
        },
        "summarizer": {
            "module": "src_v3/summarize_v3.py",
            "entrypoint": "summarize_analysis",
            "record_parser": "src_v3/records.py",
            "across_seed_bootstrap_resamples": int(
                design["v3"]["summarizer"]["across_seed_bootstrap_resamples"]
            ),
            "emits_gates": False,
            "emits_support_status": False,
            "reinterprets_v2": False,
        },
        "analysis_launcher": {
            "script": "scripts_v3/run_v3.py",
            "requires_token": True,
            "executes_frozen_plan_with_token": True,
            "preflight_only_flag": "--preflight-only",
            "expected_replicates": 4200,
            "canonical_summary_requires_complete_result_set": True,
            "resume_keys": "exact (cell_id, uint64 seed)",
        },
    }
    with open(PROVENANCE / "DESIGN_V3_FREEZE.json", "w", encoding="utf-8") as handle:
        json.dump(freeze, handle, indent=2, sort_keys=True)
        handle.write("\n")

    seed_doc = {
        "hashes": seed_hashes,
        "n_seeds": freeze["n_seeds"],
        "V3_ANALYSIS_values": "REDACTED_MATERIALIZED_FOR_HASH_ONLY",
        "V3_DETERMINISM": seed_list(design, "V3_DETERMINISM"),
        "V3_SMOKE": seed_list(design, "V3_SMOKE"),
        "V3_BENCHMARK": seed_list(design, "V3_BENCHMARK"),
        "V3_BENCHMARK_convergence_prefixes": [
            int(m) for m in design["seeds"]["pools"]["V3_BENCHMARK"].get("convergence_prefixes", [])
        ],
        "V3_BENCHMARK_prefix_hashes": {
            str(int(m)): hashlib.sha256(
                ",".join(str(v) for v in seed_list(design, "V3_BENCHMARK")[: int(m)]).encode("utf-8")
            ).hexdigest()
            for m in design["seeds"]["pools"]["V3_BENCHMARK"].get("convergence_prefixes", [])
        },
        "disjointness": (
            "pairwise disjoint from V3_DETERMINISM / V3_SMOKE / V3_ANALYSIS and all V2 pools"
        ),
    }
    with open(PROVENANCE / "SEED_POOL_V3.json", "w", encoding="utf-8") as handle:
        json.dump(seed_doc, handle, indent=2)
        handle.write("\n")

    run_manifest = {
        "phase": "PASS_1_2",
        "rng_mode_substantive": "named_substreams",
        "system_seed_mode_substantive": "orthogonal_v3",
        "rng_mode_parity": "legacy_sequential",
        "system_seed_mode_parity": "legacy_v2",
        "V3_DESIGN_HASH": v3_design_h,
        "V3_CODE_HASH": v3_code_h,
        "V3_ANALYSIS_POOL_FROZEN": True,
        "V3_ANALYSIS_REPLICATES_RUN": 0,
        "V3_ANALYSIS_OUTCOMES_INSPECTED": False,
        "interval_semantics": (
            "Reported 95% bootstrap and Wilson intervals are pointwise Monte Carlo "
            "uncertainty intervals for their individual estimands. They are not "
            "simultaneous family-wise confidence bands over all V3 contrasts."
        ),
        "checkpoint": "PASS_1_2_EXACT_IO_RESUME_HARDENING",
        "expected_analysis_replicates": 4200,
        "analysis_launcher_executable": True,
        "analysis_launcher_executed": False,
        "source_changes_required_for_pass_2": 0,
        "benchmark_pool_n": int(bench_spec["n_seeds"]),
        "exact_uint64_provenance": True,
        "canonical_summary_requires_complete_result_set": True,
    }
    with open(PROVENANCE / "RUN_MANIFEST_V3.json", "w", encoding="utf-8") as handle:
        json.dump(run_manifest, handle, indent=2)
        handle.write("\n")

    checkpoint = {
        "phase": "PASS_1_2_COMPLETE",
        "V3_ANALYSIS_POOL_FROZEN": True,
        "V3_ANALYSIS_REPLICATES_RUN": 0,
        "V3_ANALYSIS_OUTCOMES_INSPECTED": False,
        "authorize_token_used": False,
        "full_analysis_launcher_implemented": True,
        "full_analysis_launcher_executed": False,
        "source_changes_required_for_pass_2": 0,
        "V3_DESIGN_HASH": v3_design_h,
        "V3_CODE_HASH": v3_code_h,
        "resolved_cells": 21,
        "ANALYSIS_seeds_per_cell": 200,
        "expected_ANALYSIS_replicates": 4200,
        "BENCHMARK_n": int(bench_spec["n_seeds"]),
        "cells_changed": 0,
        "ANALYSIS_seed_count_changed": 0,
        "exact_uint64_provenance": True,
        "resume_idempotency": True,
        "canonical_summary_requires_complete_result_set": True,
        "interval_semantics": run_manifest["interval_semantics"],
    }
    with open(PROVENANCE / "PASS1_2_CHECKPOINT.json", "w", encoding="utf-8") as handle:
        json.dump(checkpoint, handle, indent=2)
        handle.write("\n")

    print(f"V3_DESIGN_HASH={v3_design_h}")
    print(f"V3_CODE_HASH={v3_code_h}")
    print(f"resolved_cell_manifest_hash={table_hash}")
    print(f"V3_BENCHMARK_n={int(bench_spec['n_seeds'])}")
    print("V3_ANALYSIS_REPLICATES_RUN=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
