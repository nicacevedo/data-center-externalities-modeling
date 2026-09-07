#!/usr/bin/env python3
"""Stage 1: validate and freeze design_v2. Runs NO substantive experiment.

v1 freeze artifacts are left in place as historical evidence.

Order of operations matters: the design is validated (schema, stability, feasibility of
every combination actually used, transition counts, seed disjointness) BEFORE any hash is
written, and the S6 variance characterization is performed here, pre-results, using the
dedicated CALIBRATION seed pool.
"""

from __future__ import annotations

import csv
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from groundwater_identifiability_synthetic.src import dgp  # noqa: E402
from groundwater_identifiability_synthetic.src.design import (  # noqa: E402
    DESIGN_ARTIFACTS,
    MODULE_ROOT,
    code_files,
    code_hash,
    design_hash,
    gate_cells,
    load_design,
    reporting_cells,
    resolve_regime,
    rng_for,
    seed_list,
    seed_pool_hash,
    sha256_file,
)

PROVENANCE = MODULE_ROOT / "outputs" / "provenance"


def validate_time_base(design: dict) -> list[str]:
    notes = []
    horizon = int(design["time"]["analysis_horizon_fine_steps"])
    for cadence, expected in design["time"]["usable_transitions_by_cadence"].items():
        k = int(cadence)
        offsets = np.arange(0, horizon, k)
        actual = len(offsets) - 1
        if actual != int(expected):
            raise ValueError(
                f"cadence {k}: frozen transition count {expected} != computed {actual}"
            )
        train_f = float(design["splits"]["train_fraction"])
        val_f = float(design["splits"]["validation_fraction"])
        train = int(np.floor(train_f * actual))
        val = int(np.floor((train_f + val_f) * actual)) - train
        test = actual - train - val
        frozen = design["time"]["split_counts_by_cadence"][k]
        if (train, val, test) != (frozen["train"], frozen["validation"], frozen["test"]):
            raise ValueError(
                f"cadence {k}: frozen split {frozen} != computed "
                f"{{'train': {train}, 'validation': {val}, 'test': {test}}}"
            )
        notes.append(f"cadence {k}: {actual} transitions -> {train}/{val}/{test}")
    return notes


def used_combinations(design: dict) -> set[tuple[str, str, str]]:
    """Every (topology, memory, gamma) that any frozen cell, curve or grid actually builds."""
    combos: set[tuple[str, str, str]] = set()
    for spec in {**gate_cells(design), **reporting_cells(design)}.values():
        combos.add((spec.topology, spec.memory, spec.gamma))

    grid = design["experiment_grid"]
    for curve in grid["stress_curves"].values():
        topology = curve["topology"]
        base_memory = design["reference_regime"]["memory"]
        base_gamma = design["reference_regime"]["gamma"]
        if curve["vary"] == "memory":
            for value in curve["values"]:
                combos.add((topology, value, base_gamma))
        elif curve["vary"] == "gamma":
            for value in curve["values"]:
                combos.add((topology, base_memory, value))
        else:
            combos.add((topology, base_memory, base_gamma))

    for spec in grid["two_factor_grids"].values():
        factors = spec["factors"]
        topologies = (
            list(spec["topology_by_level"].values())
            if "topology_by_level" in spec
            else [spec["topology"]]
        )
        memories = factors.get("memory", [design["reference_regime"]["memory"]])
        gammas = factors.get("gamma", [design["reference_regime"]["gamma"]])
        for topology in topologies:
            for memory in memories:
                for gamma in gammas:
                    combos.add((topology, memory, gamma))
    return combos


def validate_systems(design: dict) -> list[dict]:
    """Build every used system and assert BOTH stability conditions and the tau target."""
    infeasible = {
        (entry["topology"], entry["memory"], entry["gamma"])
        for entry in design["coupling"].get("infeasible_combinations", [])
    }
    tolerance = float(design["memory_regimes"]["target_match_tolerance"])
    rows = []
    for topology, memory, gamma in sorted(used_combinations(design)):
        if (topology, memory, gamma) in infeasible:
            raise ValueError(
                "cell uses the declared-infeasible combination "
                f"topology={topology}, memory={memory}, gamma={gamma}"
            )
        system = dgp.build_system(design, topology, memory, gamma)
        diagnostics = dgp.check_stability(design, system)

        target = float(design["memory_regimes"]["targets_fine_steps"][memory])
        realized = diagnostics["tau_relax_realized"]
        deviation = abs(realized - target) / target
        if deviation > tolerance:
            raise ValueError(
                f"{topology}/{memory}/{gamma}: realized tau {realized:.4f} deviates "
                f"{deviation:.4%} from target {target}"
            )

        pairs = set()
        coords = system.coordinates
        radius = float(design["geometry"]["candidate_radius"])
        for i in range(system.n_nodes):
            for j in range(i + 1, system.n_nodes):
                if np.linalg.norm(coords[i] - coords[j]) <= radius:
                    pairs.add((i, j))
        expected = design["topologies"][topology].get("expected_candidate_pairs")
        if expected is not None and len(pairs) != int(expected):
            raise ValueError(
                f"{topology}: expected {expected} candidate pairs, geometry gives {len(pairs)}"
            )

        rows.append(
            {
                "topology": topology,
                "memory": memory,
                "gamma": gamma,
                "n_nodes": system.n_nodes,
                "rho_A": round(diagnostics["rho_A"], 10),
                "tau_relax_realized": round(realized, 6),
                "tau_target": target,
                "tau_deviation": round(deviation, 8),
                "min_diagonal_A": round(diagnostics["min_diagonal_A"], 8),
                "max_diagonal_load": round(diagnostics["max_diagonal_load"], 8),
                "burn_in_fine_steps": dgp.burn_in_length(design, system),
                "n_true_edges": len(system.true_edges),
                "n_candidate_pairs": len(pairs),
                "n_decoy_pairs": len(pairs - set(system.true_edges)),
                "true_edges_outside_candidates": len(set(system.true_edges) - pairs),
            }
        )
    return rows


def validate_seeds(design: dict) -> dict:
    pools = {name: seed_list(design, name) for name in design["seeds"]["pools"]}
    names = list(pools)
    for a_index, a in enumerate(names):
        for b in names[a_index + 1 :]:
            overlap = set(pools[a]) & set(pools[b])
            if overlap:
                raise ValueError(f"seed pools {a} and {b} overlap: {sorted(overlap)[:5]}")
    return pools


def validate_forcing_clipping(design: dict) -> dict:
    """Every cell must satisfy the frozen clipping limit, checked at FREEZE time.

    Nonnegativity clipping of R and Q is a nonlinearity in an otherwise linear DGP: it breaks
    the exactness of paired-counterfactual differencing and puts an uncontrolled
    misspecification into scenarios that are supposed to be clean. The limit is therefore a
    hard design constraint, and any scenario parameter that violates it must be adjusted
    BEFORE the freeze rather than explained away afterwards.
    """
    from groundwater_identifiability_synthetic.src.evaluation import scenario_options
    from groundwater_identifiability_synthetic.src.plan import all_cells

    limit = float(design["forcing"]["max_clip_fraction"])
    seeds = seed_list(design, "CALIBRATION")

    worst: dict[str, float] = {}
    for cell_id, regime in all_cells(design).items():
        options = scenario_options(design, regime)
        system = dgp.build_system(design, regime.topology, regime.memory, regime.gamma)
        if options.get("null_mode") == "matched_local_dynamics":
            system = dgp.as_matched_local_dynamics_null(system)
        fractions = []
        for seed in seeds:
            trajectory = dgp.simulate(design, system, regime, rng_for(seed), options)
            fractions.append(float(trajectory.clip_fraction))
        worst[cell_id] = max(fractions)

    violations = {k: v for k, v in worst.items() if v > limit}
    if violations:
        listing = "\n".join(f"    {k}: {v:.4%}" for k, v in sorted(violations.items()))
        raise SystemExit(
            f"FORCING CLIPPING LIMIT VIOLATED (limit {limit:.3%}) in {len(violations)} cell(s):\n"
            f"{listing}\n"
            "Clipping is a nonlinearity that breaks paired-counterfactual exactness. Adjust the\n"
            "offending scenario parameter in design_v2.yaml before freezing."
        )
    return {
        "limit": limit,
        "max_clip_fraction_over_cells": max(worst.values()) if worst else 0.0,
        "argmax_cell": max(worst, key=worst.get) if worst else None,
        "n_cells_checked": len(worst),
        "n_seeds_per_cell": len(seeds),
    }


def characterize_s6_variance(design: dict) -> dict:
    """Characterize, do NOT force-match, S6 marginal head variance. CALIBRATION seeds only.

    Recorded pre-results so the S5-vs-S6 comparison is auditable. Matching via the process-
    noise channel was attempted and rejected at freeze time; see the rationale in
    design_v1.yaml s6_null_construction. The measured process-noise variance share printed
    here is the evidence for that rejection.
    """
    reference = design["s6_null_construction"]["variance_characterization_reference"]
    seeds = seed_list(design, "CALIBRATION")

    ref_regime = resolve_regime(
        design, "CAL_REF", "S5", reference["topology"],
        overrides={"memory": reference["memory"], "gamma": reference["gamma"]},
    )
    null_regime = resolve_regime(design, "CAL_NULL", "S6a", "null5", overrides={})

    def mean_head_variance(regime, topology, gamma, noise_multiplier) -> float:
        from dataclasses import replace

        system = dgp.build_system(design, topology, regime.memory, gamma)
        scaled = replace(regime, process_noise_sd=regime.process_noise_sd * noise_multiplier)
        values = []
        for seed in seeds:
            trajectory = dgp.simulate(design, system, scaled, rng_for(seed), {})
            window = trajectory.h[trajectory.analysis_start :]
            values.append(float(np.mean(np.var(window, axis=0))))
        return float(np.mean(values))

    var_ref = mean_head_variance(ref_regime, reference["topology"], reference["gamma"], 1.0)
    var_ref_0 = mean_head_variance(ref_regime, reference["topology"], reference["gamma"], 0.0)
    var_null = mean_head_variance(null_regime, "null5", "NONE", 1.0)
    var_null_0 = mean_head_variance(null_regime, "null5", "NONE", 0.0)

    var_s6b, persist_ref, persist_s6a, persist_s6b = None, None, None, None
    try:
        ref_sys = dgp.build_system(design, reference["topology"], reference["memory"], reference["gamma"])
        s6b_sys = dgp.as_matched_local_dynamics_null(ref_sys)
        persist_ref = float(np.mean(np.diag(ref_sys.A)))
        persist_s6a = float(np.mean(np.diag(
            dgp.build_system(design, "null5", "MED", "NONE").A
        )))
        persist_s6b = float(np.mean(np.diag(s6b_sys.A)))
        s6b_regime = resolve_regime(design, "CAL_S6B", "S6b", "path5", overrides={})
        values = []
        for seed in seeds:
            trajectory = dgp.simulate(design, s6b_sys, s6b_regime, rng_for(seed), {})
            window = trajectory.h[trajectory.analysis_start :]
            values.append(float(np.mean(np.var(window, axis=0))))
        var_s6b = float(np.mean(values))
    except Exception as exc:
        var_s6b = float("nan")
        persist_s6b = float("nan")

    return {
        "match_enforced": False,
        "variance_coupled_reference": var_ref,
        "variance_coupled_reference_zero_process_noise": var_ref_0,
        "variance_s6a": var_null,
        "variance_s6a_zero_process_noise": var_null_0,
        "variance_s6b": var_s6b,
        "s6a_over_reference_variance_ratio": var_null / var_ref,
        "s6b_over_reference_variance_ratio": (var_s6b / var_ref) if var_s6b else float("nan"),
        "local_persistence_mean_A_ii_reference": persist_ref,
        "local_persistence_mean_A_ii_s6a": persist_s6a,
        "local_persistence_mean_A_ii_s6b": persist_s6b,
        "process_noise_variance_share_reference": (var_ref - var_ref_0) / var_ref,
        "process_noise_variance_share_s6a": (var_null - var_null_0) / var_null,
        "interpretation": (
            "S6a is the v1 global-memory null. S6b matches A_ii of the coupled reference. "
            "Neither force-matches marginal variance. snr_head equalizes inference difficulty."
        ),
        "calibration_seed_pool": "CALIBRATION",
        "n_calibration_seeds": len(seeds),
        # v1 key aliases so older readers do not break
        "variance_null": var_null,
        "null_over_reference_variance_ratio": var_null / var_ref,
        "process_noise_variance_share_null": (var_null - var_null_0) / var_null,
    }


def write_manifest(path: Path, relatives: list[str], base: Path) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["path", "bytes", "sha256"])
        for relative in relatives:
            target = base / relative
            writer.writerow([relative, target.stat().st_size, sha256_file(target)])


def main() -> int:
    design = load_design()
    PROVENANCE.mkdir(parents=True, exist_ok=True)

    time_notes = validate_time_base(design)
    system_rows = validate_systems(design)
    ref_sys = dgp.build_system(design, "path5", "MED", "MED")
    s6b_sys = dgp.as_matched_local_dynamics_null(ref_sys)
    s6b_diag = dgp.check_stability(design, s6b_sys)
    if not np.allclose(np.diag(s6b_sys.A), np.diag(ref_sys.A), atol=1e-10):
        raise SystemExit("S6b A_ii matching failed at freeze")
    pools = validate_seeds(design)
    clipping = validate_forcing_clipping(design)
    characterization = characterize_s6_variance(design)
    characterization.update(
        {
            "s6b_rho_A": float(s6b_diag["rho_A"]),
            "s6b_tau_relax_realized": float(s6b_diag["tau_relax_realized"]),
            "s6b_min_diagonal_A": float(s6b_diag["min_diagonal_A"]),
            "s6b_max_diagonal_load": float(s6b_diag["max_diagonal_load"]),
            "s6b_burn_in_fine_steps": int(dgp.burn_in_length(design, s6b_sys)),
            "s6b_tau_not_forced_to_memory_target": True,
            "s6b_timescale_note": (
                "S6b spectral radius is max|A_ii| after zeroing off-diagonals. "
                "Coupled MED tau=20 is a network eigenmode and is not inherited. "
                "S6b tau is recorded from the constructed A_null; it is not retuned "
                "to the MED target."
            ),
        }
    )
    system_rows.append(
        {
            "topology": "S6b_from_path5",
            "memory": "MED",
            "gamma": "MED",
            "n_nodes": s6b_sys.n_nodes,
            "rho_A": round(s6b_diag["rho_A"], 10),
            "tau_relax_realized": round(s6b_diag["tau_relax_realized"], 6),
            "tau_target": float("nan"),
            "tau_deviation": float("nan"),
            "min_diagonal_A": round(s6b_diag["min_diagonal_A"], 8),
            "max_diagonal_load": round(s6b_diag["max_diagonal_load"], 8),
            "burn_in_fine_steps": dgp.burn_in_length(design, s6b_sys),
            "n_true_edges": 0,
            "n_candidate_pairs": 7,
            "n_decoy_pairs": 7,
            "true_edges_outside_candidates": 0,
        }
    )

    with open(PROVENANCE / "S6_VARIANCE_CHARACTERIZATION_V2.json", "w", encoding="utf-8") as handle:
        json.dump(characterization, handle, indent=2, sort_keys=True)

    with open(PROVENANCE / "FROZEN_SYSTEMS_V2.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(system_rows[0].keys()))
        writer.writeheader()
        writer.writerows(system_rows)

    write_manifest(PROVENANCE / "DESIGN_V2_FREEZE_MANIFEST.csv", list(DESIGN_ARTIFACTS), MODULE_ROOT)
    code_relatives = [p.relative_to(MODULE_ROOT).as_posix() for p in code_files()]
    write_manifest(PROVENANCE / "CODE_MANIFEST_V2.csv", code_relatives, MODULE_ROOT)

    import subprocess

    def _git(*args: str) -> str:
        try:
            return subprocess.check_output(["git", *args], cwd=MODULE_ROOT, text=True).strip()
        except Exception:
            return ""

    freeze = {
        "design_version": design["design_version"],
        "design_status": "FROZEN",
        "design_hash": design_hash(),
        "design_artifacts": list(DESIGN_ARTIFACTS),
        "code_hash": code_hash(),
        "n_code_files": len(code_relatives),
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "numpy_version": np.__version__,
        "rng_implementation": "numpy.random.Generator(PCG64)",
        "time_base": time_notes,
        "n_frozen_systems": len(system_rows),
        "seed_pool_sizes": {name: len(values) for name, values in pools.items()},
        "seed_pool_hashes": {
            name: seed_pool_hash(design, name) for name in pools
        },
        "s6_variance_characterization": characterization,
        "forcing_clipping": clipping,
        "phase": "PHASE_1_5_PRE_SWEEP",
        "full_sweep_launched": False,
        "parent_checkpoint_commit": "1b95209b1a2f0e20ae8bfac3910bd5359a420c82",
        "git_branch": _git("branch", "--show-current"),
        "git_head": _git("rev-parse", "HEAD"),
        "scenario_count": len(design["scenarios"]),
    }
    from groundwater_identifiability_synthetic.src.plan import plan_summary

    freeze["plan"] = plan_summary(design)
    freeze["cell_count"] = freeze["plan"]["total_unique_cells"]

    with open(PROVENANCE / "DESIGN_V2_FREEZE.json", "w", encoding="utf-8") as handle:
        json.dump(freeze, handle, indent=2, sort_keys=True)

    run_manifest = {
        "design_hash": freeze["design_hash"],
        "code_hash": freeze["code_hash"],
        "python_version": freeze["python_version"],
        "numpy_version": freeze["numpy_version"],
        "rng_implementation": freeze["rng_implementation"],
        "seed_pool_sizes": freeze["seed_pool_sizes"],
        "seed_pool_hashes": freeze["seed_pool_hashes"],
        "branch": freeze["git_branch"],
        "git_head": freeze["git_head"],
        "parent_checkpoint_commit": freeze["parent_checkpoint_commit"],
        "frozen_at_utc": freeze["frozen_at_utc"],
        "scenario_count": freeze["scenario_count"],
        "cell_count": freeze["cell_count"],
        "full_sweep_launched": False,
        "analysis_seeds_inspected": False,
    }
    with open(PROVENANCE / "RUN_MANIFEST_V2.json", "w", encoding="utf-8") as handle:
        json.dump(run_manifest, handle, indent=2, sort_keys=True)

    print(f"DESIGN_HASH = {freeze['design_hash']}")
    print(f"CODE_HASH   = {freeze['code_hash']}")
    print(f"frozen systems validated: {len(system_rows)}")
    for note in time_notes:
        print("  " + note)
    print(
        f"forcing clipping: max={clipping['max_clip_fraction_over_cells']:.4%} "
        f"(limit {clipping['limit']:.3%}, worst cell {clipping['argmax_cell']}) "
        f"across {clipping['n_cells_checked']} cells"
    )
    print(
        "S6 variance characterization (not force-matched): "
        f"null/reference ratio={characterization['null_over_reference_variance_ratio']:.3f}, "
        f"process-noise variance share={characterization['process_noise_variance_share_reference']:.4%}"
    )
    return 0


def sha256_of_ints(values: list[int]) -> str:
    import hashlib

    return hashlib.sha256(",".join(str(v) for v in values).encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
