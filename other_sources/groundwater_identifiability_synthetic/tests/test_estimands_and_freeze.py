"""Cadence-dependent estimands, row admissibility, freeze enforcement, label discipline."""

from __future__ import annotations

import subprocess
import sys

import numpy as np
import pytest

from groundwater_identifiability_synthetic.src import dgp, metrics
from groundwater_identifiability_synthetic.src.design import resolve_regime, rng_for
from groundwater_identifiability_synthetic.src.evaluation import _forcing_sampler, run_replicate
from groundwater_identifiability_synthetic.src.models import build_design
from groundwater_identifiability_synthetic.src.observations import make_observations


# -------------------------------------------------------------------------------------
# Estimands
# -------------------------------------------------------------------------------------


def test_pseudo_true_coarse_B_reduces_to_B_at_cadence_one(design):
    """At k = 1 the aggregate IS the forcing, so the projection must return B exactly."""
    system = dgp.build_system(design, "path5", "MED", "MED")
    B_pseudo = metrics.pseudo_true_coarse_B(
        system.A, system.B_Q, 1, _forcing_sampler(design), 200, rng_for(11)
    )
    assert np.allclose(np.diag(B_pseudo), system.B_Q, atol=1e-8)
    off_diagonal = B_pseudo - np.diag(np.diag(B_pseudo))
    assert np.allclose(off_diagonal, 0.0, atol=1e-8)


def test_pseudo_true_coarse_B_differs_from_naive_scaling_at_k_above_one(design):
    """Neither B nor k*B is the right coarse coefficient; the projection is what it is.

    For interval-aggregated forcing the exact response is sum_r A^{k-1-r} B u_r. Projecting
    it onto the aggregate U = sum_r u_r under the frozen (serially independent within
    interval) forcing gives B * mean_j(A^j), an AVERAGE of decayed responses. It therefore
    lies strictly BELOW B, not between B and k*B: forcing applied early in the interval has
    partly decayed by the end of it.
    """
    k = 4
    system = dgp.build_system(design, "path5", "MED", "MED")
    B_pseudo = metrics.pseudo_true_coarse_B(
        system.A, system.B_Q, k, _forcing_sampler(design), 8000, rng_for(12)
    )
    diagonal = np.diag(B_pseudo)

    assert not np.allclose(diagonal, k * system.B_Q, rtol=0.05), "k*B is not the estimand"
    assert not np.allclose(diagonal, system.B_Q, rtol=0.02), "B is not the estimand either"
    assert np.all(diagonal < system.B_Q), "decay within the interval must reduce the response"


def test_pseudo_true_projection_matches_its_closed_form(design):
    """Validates the Monte Carlo projection against the matrix closed form.

    For forcing that is serially uncorrelated within the interval the projection collapses to
    (1/k) * sum_r A^{k-1-r} diag(B). The frozen pumping process is AR(1), so the realized
    projection sits near but not exactly on this value; the closed form is used here purely
    to confirm the estimator is computing the right object.
    """
    k = 4
    system = dgp.build_system(design, "path5", "MED", "MED")

    def white(rng, steps, n):
        return rng.normal(0.0, 1.0, size=(steps, n))

    B_pseudo = metrics.pseudo_true_coarse_B(
        system.A, system.B_Q, k, white, 20000, rng_for(77)
    )
    closed_form = (
        sum(np.linalg.matrix_power(system.A, k - 1 - r) for r in range(k))
        @ np.diag(system.B_Q)
        / k
    )
    assert np.allclose(B_pseudo, closed_form, atol=0.02)


def test_direct_parameter_recovery_is_primary_only_at_cadence_one(design):
    for cadence, expected in ((1, True), (4, False)):
        regime = resolve_regime(design, "T", "S1", "single", overrides={"cadence": cadence})
        record = run_replicate(design, regime, 555)
        assert record["direct_parameter_recovery_is_primary"] is expected
        if expected:
            assert np.isfinite(record["B_Q_relative_error_median"])
        else:
            assert np.isnan(record["B_Q_relative_error_median"])
            assert "B_Q_pseudo_true_relative_error_median" in record


def test_absolute_storage_is_not_claimed_when_the_pumping_scale_is_unknown(design):
    """P-SCALEBIAS destroys the absolute scale, so absolute S must not be reported."""
    known = resolve_regime(
        design, "T", "S1", "single", overrides={"cadence": 1, "pumping_quality": "P-EXACT"}
    )
    unknown = resolve_regime(
        design, "T", "S1", "single", overrides={"cadence": 1, "pumping_quality": "P-SCALEBIAS"}
    )
    a = run_replicate(design, known, 556)
    b = run_replicate(design, unknown, 556)
    assert a["absolute_S_identifiable"] is True
    assert b["absolute_S_identifiable"] is False
    assert np.isfinite(a["storage_relative_error_median"])
    assert np.isnan(b["storage_relative_error_median"])
    assert b["absolute_pumping_scale_known"] is False


def test_relative_recovery_survives_an_unknown_scale_better_than_absolute(design):
    """Scale bias must hurt ABSOLUTE recovery while leaving the response SHAPE intact."""
    regime = resolve_regime(
        design, "T", "S1", "single",
        overrides={"cadence": 1, "pumping_quality": "P-SCALEBIAS", "snr_head": 20,
                   "mcar_fraction": 0.0, "recharge_quality": "R-EXACT"},
    )
    record = run_replicate(design, regime, 557)
    absolute = record.get("nire_persistent_step_h26_L")
    relative = record.get("relative_shape_error_persistent_step_L")
    assert np.isfinite(absolute) and np.isfinite(relative)
    assert relative < absolute


# -------------------------------------------------------------------------------------
# Row admissibility
# -------------------------------------------------------------------------------------


def test_no_head_interpolation(design):
    """Rows needing a missing head must be DROPPED, never filled."""
    system = dgp.build_system(design, "path5", "MED", "MED")
    regime = resolve_regime(design, "T", "S5", "path5", overrides={"mcar_fraction": 0.30})
    trajectory = dgp.simulate(design, system, regime, rng_for(601), {})
    bundle = make_observations(design, system, trajectory, regime, rng_for(602))

    node_design = build_design(bundle, 2, "L")
    assert np.all(np.isfinite(node_design.X))
    assert np.all(np.isfinite(node_design.y))
    assert len(node_design.rows) < bundle.n_transitions, "missingness should drop rows"
    for row_index, tau in enumerate(node_design.rows):
        assert np.isfinite(bundle.y[tau, 2])
        assert np.isfinite(bundle.y[tau + 1, 2])
        assert node_design.X[row_index, 0] == bundle.y[tau, 2]


def test_network_rows_require_every_candidate_neighbour(design):
    system = dgp.build_system(design, "path5", "MED", "MED")
    regime = resolve_regime(design, "T", "S5", "path5", overrides={"mcar_fraction": 0.30})
    trajectory = dgp.simulate(design, system, regime, rng_for(603), {})
    bundle = make_observations(design, system, trajectory, regime, rng_for(604))

    node_design = build_design(bundle, 2, "N")
    for tau in node_design.rows:
        for j in node_design.kappa_neighbors:
            assert np.isfinite(bundle.y[tau, j])
    local = build_design(bundle, 2, "L")
    assert len(node_design.rows) <= len(local.rows)


def test_block_outages_are_contiguous(design):
    system = dgp.build_system(design, "path5", "MED", "MED")
    regime = resolve_regime(
        design, "T", "S5", "path5", overrides={"mcar_fraction": 0.0, "blocks_per_node": 1}
    )
    trajectory = dgp.simulate(design, system, regime, rng_for(605), {})
    bundle = make_observations(design, system, trajectory, regime, rng_for(606))
    length = int(design["observation"]["missingness"]["block_outage"]["block_length_cadence_steps"])
    for node in range(system.n_nodes):
        missing = np.flatnonzero(np.isnan(bundle.y[:, node]))
        assert missing.size == length, "exactly one contiguous outage expected"
        assert np.all(np.diff(missing) == 1), "outage must be contiguous"


# -------------------------------------------------------------------------------------
# Freeze enforcement
# -------------------------------------------------------------------------------------


def test_runner_refuses_when_the_design_hash_does_not_match(module_root, tmp_path):
    """run_g0.py must refuse to run against a stale freeze."""
    provenance = module_root / "outputs" / "provenance"
    freeze_path = provenance / "DESIGN_FREEZE.json"
    if not freeze_path.exists():
        pytest.skip("design not yet frozen")

    import json

    original = freeze_path.read_text(encoding="utf-8")
    payload = json.loads(original)
    payload["design_hash"] = "0" * 64
    freeze_path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        result = subprocess.run(
            [sys.executable, str(module_root / "scripts" / "run_g0.py")],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "DESIGN HASH MISMATCH" in (result.stdout + result.stderr)
    finally:
        freeze_path.write_text(original, encoding="utf-8")


def test_full_sweep_refuses_without_explicit_authorization(module_root):
    """Phase 2 must not be launchable by accident."""
    result = subprocess.run(
        [sys.executable, str(module_root / "scripts" / "run_experiment.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "REFUSING TO RUN" in result.stdout
    assert not (module_root / "outputs" / "sweep_replicates.csv").exists()


def test_phase_two_artifacts_absent(module_root):
    """The checkpoint stops before any substantive output exists."""
    for name in (
        "FINAL_SYNTHETIC_IDENTIFIABILITY_REPORT.md",
        "FINAL_SYNTHETIC_IDENTIFIABILITY_STATUS.json",
        "scenario_summary.csv",
        "data_adequacy_map.csv",
        "sweep_replicates.csv",
    ):
        assert not (module_root / "outputs" / name).exists(), f"{name} must not exist in phase 1"


# -------------------------------------------------------------------------------------
# Scope and label discipline
# -------------------------------------------------------------------------------------


def test_module_does_not_invent_planning_model_labels(module_root):
    """M0R and M1S do not exist in this repository and must not be used as model labels.

    REPOSITORY_PREMISE_CONFLICTS.md, CHECKPOINT_REPORT.md, and this test file are exempt:
    each names the labels precisely in order to record that the task premise expected them
    and the repository does not contain them. The prohibition is on USING them as if they
    were real planning models, not on reporting their absence.
    """
    exempt = {
        "REPOSITORY_PREMISE_CONFLICTS.md",
        "CHECKPOINT_REPORT.md",
        "test_estimands_and_freeze.py",
    }
    scanned = [
        path
        for pattern in ("src/*.py", "scripts/*.py", "config/*.yaml", "*.md")
        for path in module_root.glob(pattern)
        if path.name not in exempt
    ]
    assert scanned, "nothing scanned"

    offenders = []
    for path in scanned:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for label in ("M0R", "M1S"):
                if label in line:
                    offenders.append(f"{path.name}:{number}: {line.strip()[:80]}")
    assert not offenders, f"invented planning labels: {offenders}"


def test_scope_token_is_declared(design, module_root):
    assert design["scope_token"] == "REDUCED_ORDER_HEAD_PUMPING_RECHARGE_CORE_ONLY"
    scope = (module_root / "SCOPE.md").read_text(encoding="utf-8")
    for phrase in ("GRACE", "Bayesian", "Andhra Pradesh hydrogeology"):
        assert phrase in scope


def test_no_grace_or_bayesian_machinery_in_v1(module_root):
    """v1 adds no GRACE, data-assimilation, Bayesian, or neural machinery.

    Checked on imports rather than substrings, so that ordinary words containing these
    fragments (isinstance, distance) do not produce false positives.
    """
    import ast

    banned = {"pymc", "stan", "pystan", "cmdstanpy", "arviz", "torch", "tensorflow", "keras",
              "jax", "sklearn", "emcee", "numpyro"}
    allowed = {"numpy", "scipy", "yaml", "pandas"}
    imported: set[str] = set()
    for path in list((module_root / "src").glob("*.py")) + list((module_root / "scripts").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module.split(".")[0])
    assert not (imported & banned), f"v1 must not depend on {imported & banned}"

    third_party = imported - allowed - set(sys.stdlib_module_names)
    third_party -= {"groundwater_identifiability_synthetic", "_bootstrap_path"}
    assert not third_party, f"unexpected third-party dependency: {third_party}"

    for path in (module_root / "src").glob("*.py"):
        assert "grace" not in path.read_text(encoding="utf-8").lower()
