"""v2 protocol corrections: S6a/S6b, S8 placebo, physical identifiability, freeze lock."""

from __future__ import annotations

import numpy as np
import pytest

from groundwater_identifiability_synthetic.src import dgp, interventions, models
from groundwater_identifiability_synthetic.src.design import (
    DESIGN_ARTIFACTS,
    V1_CONFIG_PATH,
    design_hash,
    load_design,
    resolve_regime,
    rng_for,
    seed_list,
)
from groundwater_identifiability_synthetic.src.evaluation import (
    run_replicate,
    scenario_options,
)
from groundwater_identifiability_synthetic.src.fit import fit_ladder
from groundwater_identifiability_synthetic.src.observations import make_observations


def test_design_v1_materials_are_preserved(module_root):
    assert (module_root / "config" / "design_v1.yaml").exists()
    assert (module_root / "DESIGN_FREEZE.md").exists()
    v1 = (module_root / "config" / "design_v1.yaml").read_text(encoding="utf-8")
    assert "design_version: design_v1" in v1
    assert "config/design_v1.yaml" not in DESIGN_ARTIFACTS
    assert V1_CONFIG_PATH.exists()


def test_active_protocol_is_design_v2(design):
    assert design["design_version"] == "design_v2"
    assert "S6a" in design["scenarios"]
    assert "S6b" in design["scenarios"]


def test_s6b_preserves_local_diagonal_and_zeros_off_diagonal(design):
    ref = dgp.build_system(design, "path5", "MED", "MED")
    null = dgp.as_matched_local_dynamics_null(ref)
    assert np.allclose(np.diag(null.A), np.diag(ref.A), atol=1e-10)
    off = null.A.copy()
    np.fill_diagonal(off, 0.0)
    assert np.allclose(off, 0.0)
    assert null.true_edges == frozenset()
    assert np.allclose(null.S, ref.S)
    assert np.allclose(null.B_Q, ref.B_Q)
    dgp.check_stability(design, null)


def test_s6a_and_s6b_are_distinct_nulls(design):
    s6a = dgp.build_system(design, "null5", "MED", "NONE")
    ref = dgp.build_system(design, "path5", "MED", "MED")
    s6b = dgp.as_matched_local_dynamics_null(ref)
    assert s6a.true_edges == frozenset()
    assert s6b.true_edges == frozenset()
    # S6a targets tau independently; S6b matches A_ii of the coupled reference.
    assert not np.allclose(np.diag(s6a.A), np.diag(ref.A))
    assert np.allclose(np.diag(s6b.A), np.diag(ref.A), atol=1e-10)


def test_s8_real_pumping_and_placebo_both_present(design):
    system = dgp.build_system(design, "path5", "MED", "MED")
    regime = resolve_regime(design, "T", "S8", "path5", overrides={})
    options = scenario_options(design, regime)
    assert options["placebo_correlation"] > 0
    trajectory = dgp.simulate(design, system, regime, rng_for(11), options)
    assert trajectory.Q_placebo is not None
    assert trajectory.Q_true is not None
    # Truth coefficient on placebo is identically zero: swapping placebo into Q must
    # not be how the DGP is written — heads are generated from Q_true only.
    assert not np.allclose(trajectory.Q_true, trajectory.Q_placebo)
    bundle = make_observations(design, system, trajectory, regime, rng_for(12))
    assert bundle.P_placebo is not None
    assert bundle.Q_obs is not None
    assert bundle.P_placebo.shape == bundle.Q_obs.shape
    design_l = models.build_design(bundle, 0, "L")
    assert "pumping" in design_l.names
    assert "placebo" in design_l.names
    ladder = fit_ladder(bundle, design)
    fit = next(iter(ladder.fits["L"].values()))
    assert "pumping" in fit.names
    assert "placebo" in fit.names


def test_s8_refuses_to_replace_real_pumping(design):
    system = dgp.build_system(design, "single", "MED", "NONE")
    regime = resolve_regime(design, "T", "S8", "single", overrides={})
    trajectory = dgp.simulate(design, system, regime, rng_for(13), scenario_options(design, regime))
    with pytest.raises(ValueError, match="must not replace real pumping"):
        make_observations(
            design, system, trajectory, regime, rng_for(14), use_placebo_as_pumping=True
        )


def test_physical_identifiability_is_not_just_known_pumping_scale(design):
    """k=1 and known scale are necessary, not sufficient."""
    # Scale-biased pumping at k=1 must not be labelled physical S recovery.
    rec = run_replicate(
        design,
        resolve_regime(design, "T", "S1", "single", overrides={"cadence": 1, "pumping_quality": "P-SCALEBIAS"}),
        seed_list(design, "SMOKE")[0],
    )
    assert rec["absolute_pumping_scale_known"] is False
    assert rec["physical_parameter_identifiable"] in (False, 0.0)
    assert not rec["absolute_S_identifiable"]

    # Confounded recharge even with exact pumping is not physical S recovery.
    rec2 = run_replicate(
        design,
        resolve_regime(
            design,
            "T",
            "S2",
            "single",
            overrides={"cadence": 1, "pumping_quality": "P-EXACT", "recharge_quality": "R-EXACT", "confounding_rho": 0.6},
        ),
        seed_list(design, "SMOKE")[0],
    )
    assert rec2["physical_parameter_identifiable"] in (False, 0.0)


def test_bootstrap_does_not_claim_physical_coverage_at_coarse_cadence(design):
    rec = run_replicate(
        design,
        resolve_regime(design, "T", "S5", "path5", overrides={"cadence": 4}),
        seed_list(design, "SMOKE")[0],
        with_bootstrap=True,
        n_bootstrap=int(design["uncertainty"]["n_bootstrap_smoke"]),
    )
    assert rec["cadence"] == 4
    assert not rec.get("physical_parameter_identifiable")
    # Physical coverage must be absent/NaN at k>1.
    phys = rec.get("bootstrap_coverage_beta_q_physical", np.nan)
    assert not (isinstance(phys, float) and np.isfinite(phys) and rec.get("bootstrap_coverage_beta_q") == phys and rec["cadence"] > 1 and np.isfinite(phys))
    if "bootstrap_coverage_beta_q_physical" in rec:
        assert not np.isfinite(rec["bootstrap_coverage_beta_q_physical"]) or rec["cadence"] == 1


def test_full_sweep_authorization_lock_still_active(module_root):
    import subprocess, sys

    result = subprocess.run(
        [sys.executable, str(module_root / "scripts" / "run_experiment.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "REFUSING TO RUN" in result.stdout


def test_analysis_and_smoke_seeds_remain_disjoint(design):
    analysis = set(seed_list(design, "ANALYSIS"))
    smoke = set(seed_list(design, "SMOKE"))
    g0 = set(seed_list(design, "G0"))
    cal = set(seed_list(design, "CALIBRATION"))
    assert not (analysis & smoke)
    assert not (analysis & g0)
    assert not (analysis & cal)
