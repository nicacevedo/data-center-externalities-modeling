"""SGI_G0 exact recovery, transition-matrix algebra, metric behaviour, and design integrity."""

from __future__ import annotations

import subprocess

import numpy as np
import pytest

from groundwater_identifiability_synthetic.src import dgp, metrics
from groundwater_identifiability_synthetic.src.design import (
    DESIGN_ARTIFACTS,
    code_hash,
    design_hash,
    resolve_regime,
    rng_for,
    seed_list,
)
from groundwater_identifiability_synthetic.src.evaluation import evaluate_g0, run_replicate
from groundwater_identifiability_synthetic.src.fit import fit_ladder, implied_transition_matrix
from groundwater_identifiability_synthetic.src.observations import make_observations
from groundwater_identifiability_synthetic.src.plan import all_cells


# -------------------------------------------------------------------------------------
# SGI_G0
# -------------------------------------------------------------------------------------


def test_g0_recovers_known_truth_exactly(design, g0_regime):
    """Noise-free, exact forcing, cadence 1: the estimator must reproduce truth numerically."""
    seeds = seed_list(design, "G0")
    records = [run_replicate(design, g0_regime, seed) for seed in seeds]
    result = evaluate_g0(design, records)
    assert result["pass"], result["criteria"]
    for record in records:
        assert record["g0_max_abs_transition_residual"] < 1e-9
        assert record["g0_max_abs_relative_coef_error"] < 1e-8
        assert record["g0_storage_relative_error"] < 1e-8
        assert record["rank_deficiency_max_L"] == 0


def test_g0_cell_is_actually_noise_free(design, g0_regime):
    assert g0_regime.process_noise_sd == 0.0
    assert not np.isfinite(g0_regime.snr_head)
    assert g0_regime.cadence == 1
    assert g0_regime.pumping_quality == "P-EXACT"
    assert g0_regime.recharge_quality == "R-EXACT"
    assert g0_regime.mcar_fraction == 0.0


def test_g0_design_is_well_excited(design, g0_regime, g0_seed):
    """G0 must fail for a bug, not for a rank-deficient or unexcited design."""
    record = run_replicate(design, g0_regime, g0_seed)
    assert record["rank_deficiency_max_L"] == 0
    assert record["condition_number_L"] < 1e6
    assert record["pumping_excitation_fraction_L"] > 0.01


# -------------------------------------------------------------------------------------
# Transition-matrix algebra
# -------------------------------------------------------------------------------------


def test_implied_transition_matrix_accounts_for_the_head_difference(design):
    """N regresses on (y_j - y_i), so A_ii = a_i - sum_j kappa_ij, not a_i."""
    system = dgp.build_system(design, "path5", "MED", "HIGH")
    regime = resolve_regime(
        design, "T", "S4", "path5",
        overrides={"cadence": 1, "snr_head": 50, "process_noise_sd": 0.01,
                   "mcar_fraction": 0.0, "pumping_quality": "P-EXACT",
                   "recharge_quality": "R-EXACT", "gamma": "HIGH"},
    )
    trajectory = dgp.simulate(design, system, regime, rng_for(401), {})
    bundle = make_observations(design, system, trajectory, regime, rng_for(402))
    ladder = fit_ladder(bundle, design, models=("N",))

    A_hat = implied_transition_matrix(ladder, "N", system.n_nodes)
    fit = ladder.fits["N"][0]
    kappa = fit.kappa_vector(system.n_nodes)
    assert A_hat[0, 0] == pytest.approx(fit.coef_of("own_level") - kappa.sum())
    for j in fit.kappa_neighbors:
        assert A_hat[0, j] == pytest.approx(kappa[j])

    # Row sums of the true A are 1 - kappa_i0, so an accurate A_hat must be close.
    assert abs(A_hat[0].sum() - system.A[0].sum()) < 0.15


def test_kappa_estimates_are_nonnegative(design):
    system = dgp.build_system(design, "path5", "MED", "MED")
    regime = resolve_regime(design, "T", "S5", "path5", overrides={})
    trajectory = dgp.simulate(design, system, regime, rng_for(403), {})
    bundle = make_observations(design, system, trajectory, regime, rng_for(404))
    ladder = fit_ladder(bundle, design, models=("N",))
    for fit in ladder.fits["N"].values():
        if fit is None:
            continue
        assert np.all(fit.kappa_vector(system.n_nodes) >= -1e-12)


# -------------------------------------------------------------------------------------
# Metrics
# -------------------------------------------------------------------------------------


def test_normalized_error_is_zero_for_perfect_recovery():
    truth = np.array([-1.0, -2.0, -3.0])
    assert metrics.normalized_error(truth, truth) == pytest.approx(0.0)
    assert metrics.normalized_error(truth, np.zeros(3)) == pytest.approx(1.0)


def test_relative_shape_error_is_scale_invariant():
    truth = np.array([-1.0, -2.0, -3.0])
    assert metrics.relative_shape_error(truth, 5.0 * truth) == pytest.approx(0.0, abs=1e-12)
    assert metrics.normalized_error(truth, 5.0 * truth) > 1.0


def test_edge_metrics_count_out_of_candidate_true_edges_as_false_negatives():
    true_edges = {(0, 1), (0, 4)}
    predicted = {(0, 1)}
    all_pairs = {(i, j) for i in range(5) for j in range(i + 1, 5)}
    result = metrics.edge_metrics(true_edges, predicted, all_pairs)
    assert result["edge_false_negative"] == 1.0
    assert result["edge_recall"] == pytest.approx(0.5)


def test_d_phys_is_bounded_and_symmetric():
    kappa = np.array([[0.0, 0.05], [0.04, 0.0]])
    S = np.array([1.0, 1.25])
    pairs = {(0, 1)}
    forward = metrics.d_phys(kappa, S, pairs, 0.01, 1e-9, True)
    backward = metrics.d_phys(kappa.T, S[::-1], pairs, 0.01, 1e-9, True)
    assert 0.0 <= forward["d_phys_median"] <= 1.0
    assert forward["d_phys_median"] == pytest.approx(backward["d_phys_median"])
    # Exactly consistent conductances give zero.
    consistent = np.array([[0.0, 0.05], [0.04, 0.0]])
    exact = metrics.d_phys(consistent, np.array([1.0, 1.25]), pairs, 0.01, 1e-9, True)
    assert exact["d_phys_median"] == pytest.approx(0.0, abs=1e-8)


def test_d_phys_is_null_when_scale_is_unidentifiable():
    kappa = np.array([[0.0, 0.05], [0.04, 0.0]])
    result = metrics.d_phys(kappa, np.array([1.0, 1.25]), {(0, 1)}, 0.01, 1e-9, False)
    assert np.isnan(result["d_phys_median"])


def test_d_phys_ignores_degenerate_directions():
    kappa = np.array([[0.0, 0.05], [0.0001, 0.0]])
    result = metrics.d_phys(kappa, np.array([1.0, 1.25]), {(0, 1)}, 0.01, 1e-9, True)
    assert result["d_phys_n_pairs"] == 0.0


# -------------------------------------------------------------------------------------
# Design integrity
# -------------------------------------------------------------------------------------


def test_gate_definitions_enumerate_cells_and_avoid_vague_language(design):
    banned = ["relevant replicates", "realistic regimes", "as appropriate", "reasonable"]
    for name in ("SGI_G0", "SGI_G1", "SGI_G2", "SGI_G3"):
        gate = design["gates"][name]
        assert gate["required_cells"], f"{name} has no enumerated cells"
        assert "seed_pool" in gate
        blob = str(gate).lower()
        for phrase in banned:
            assert phrase not in blob, f"{name} uses vague language: {phrase!r}"


def test_gate_cells_resolve_and_are_feasible(design):
    from groundwater_identifiability_synthetic.src.design import gate_cells

    infeasible = {
        (e["topology"], e["memory"], e["gamma"])
        for e in design["coupling"]["infeasible_combinations"]
    }
    for cell_id, regime in gate_cells(design).items():
        assert (regime.topology, regime.memory, regime.gamma) not in infeasible, cell_id
        system = dgp.build_system(design, regime.topology, regime.memory, regime.gamma)
        dgp.check_stability(design, system)


def test_every_planned_cell_is_feasible(design):
    infeasible = {
        (e["topology"], e["memory"], e["gamma"])
        for e in design["coupling"]["infeasible_combinations"]
    }
    for cell_id, regime in all_cells(design).items():
        assert (regime.topology, regime.memory, regime.gamma) not in infeasible, cell_id


def test_gate_names_do_not_collide_with_the_ocwd_feasibility_gates(design):
    """ocwd_groundwater_feasibility already defines G1-G10 with unrelated meanings."""
    gate_names = [
        name
        for name, body in design["gates"].items()
        if isinstance(body, dict) and "required_cells" in body
    ]
    assert gate_names, "no gates found"
    for name in gate_names:
        assert name.startswith("SGI_G"), f"{name} would collide with the OCWD G1-G10 namespace"
        assert design["gates"][name]["alias"] in ("G0", "G1", "G2", "G3")


def test_uncertainty_coverage_is_not_a_gate_criterion(design):
    assert design["uncertainty"]["coverage_is_a_gate_criterion"] is False
    assert design["gates"]["SGI_G1"]["coverage_criterion"] == "EXCLUDED_IN_V1"
    assert design["uncertainty"]["iid_bootstrap"] == "PROHIBITED_DEPENDENT_SERIES"
    blob = str(design["gates"]["SGI_G1"]["criteria"]).lower()
    assert "coverage" not in blob


def test_hashes_are_stable_and_cover_all_design_artifacts(module_root):
    assert design_hash() == design_hash()
    assert code_hash() == code_hash()
    assert len(DESIGN_ARTIFACTS) >= 2
    assert "DESIGN_FREEZE.md" in DESIGN_ARTIFACTS
    for relative in DESIGN_ARTIFACTS:
        assert (module_root / relative).exists()


def test_design_hash_changes_when_a_design_artifact_changes(module_root, tmp_path):
    import shutil

    staging = tmp_path / "module"
    staging.mkdir()
    (staging / "config").mkdir()
    shutil.copy(module_root / "config" / "design_v1.yaml", staging / "config" / "design_v1.yaml")
    shutil.copy(module_root / "DESIGN_FREEZE.md", staging / "DESIGN_FREEZE.md")
    before = design_hash(staging)

    with open(staging / "DESIGN_FREEZE.md", "a", encoding="utf-8") as handle:
        handle.write("\nscientific change\n")
    assert design_hash(staging) != before, "DESIGN_FREEZE.md must be inside the freeze scope"


ALLOWED_PREFIX = "other_sources/groundwater_identifiability_synthetic/"
PREEXISTING_GITLINK = "Data-center-PUE-prediction-tool"
# The gitlink commit recorded in the index at the start of this work. It must not move.
PREEXISTING_GITLINK_SHA = "11663ab76cd03100c56ab7adcb3ab65b4dd728ca"


def _git(repo_root, *args) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True, text=True, check=True
    ).stdout


def test_no_edits_outside_the_module(repo_root):
    """Nothing outside the isolated module may change."""
    offenders = []
    for line in _git(repo_root, "status", "--porcelain").splitlines():
        if not line.strip():
            continue
        path = line[3:].strip().strip('"')
        if path.startswith(ALLOWED_PREFIX) or path == PREEXISTING_GITLINK:
            continue
        offenders.append(line)
    assert not offenders, f"files changed outside the module: {offenders}"


def test_preexisting_dirty_gitlink_is_untouched(repo_root):
    """The pre-existing dirty gitlink must be left exactly as found.

    The meaningful invariants are that its recorded commit has not moved and that nothing
    about it has been staged. The porcelain status CHARACTER is deliberately not asserted:
    git reports 'm' or 'M' for a dirty gitlink depending on stat-cache refresh state, and
    pinning it would make this guard fail for a reason unrelated to repository discipline.
    """
    entry = _git(repo_root, "ls-files", "-s", PREEXISTING_GITLINK).split()
    assert entry[0] == "160000", "gitlink mode changed"
    assert entry[1] == PREEXISTING_GITLINK_SHA, "the recorded gitlink commit moved"
    assert entry[2] == "0", "gitlink has a merge-conflict stage entry"

    for line in _git(repo_root, "status", "--porcelain").splitlines():
        path = line[3:].strip().strip('"')
        if path == PREEXISTING_GITLINK:
            assert line[0] == " ", f"the gitlink was staged: {line!r}"

    staged = _git(repo_root, "diff", "--cached", "--name-only").splitlines()
    assert PREEXISTING_GITLINK not in staged, "the gitlink must never be staged"
