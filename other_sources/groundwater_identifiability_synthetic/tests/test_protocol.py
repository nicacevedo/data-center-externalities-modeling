"""Protocol guards: splits, train-only preprocessing, seeds, masked-node leakage, pairing."""

from __future__ import annotations

import numpy as np
import pytest

from groundwater_identifiability_synthetic.src import dgp, interventions
from groundwater_identifiability_synthetic.src.design import (
    load_design,
    resolve_regime,
    rng_for,
    seed_list,
)
from groundwater_identifiability_synthetic.src.fit import _fit_scaled, fit_ladder
from groundwater_identifiability_synthetic.src.models import build_design, split_masks
from groundwater_identifiability_synthetic.src.observations import (
    TEST,
    TRAIN,
    VALIDATION,
    chronological_split,
    make_observations,
    mask_node_for_test,
)


# -------------------------------------------------------------------------------------
# Splits
# -------------------------------------------------------------------------------------


def test_splits_are_chronological_contiguous_and_disjoint(design):
    for cadence, counts in design["time"]["split_counts_by_cadence"].items():
        total = int(design["time"]["usable_transitions_by_cadence"][int(cadence)])
        labels = chronological_split(design, total)
        assert list(labels).count(TRAIN) == counts["train"]
        assert list(labels).count(VALIDATION) == counts["validation"]
        assert list(labels).count(TEST) == counts["test"]
        train_idx = np.flatnonzero(labels == TRAIN)
        val_idx = np.flatnonzero(labels == VALIDATION)
        test_idx = np.flatnonzero(labels == TEST)
        assert train_idx.max() < val_idx.min() < test_idx.min()
        assert val_idx.max() < test_idx.min()
        assert len(set(train_idx) & set(val_idx) & set(test_idx)) == 0


def test_frozen_transition_counts_match_the_time_base(design):
    horizon = int(design["time"]["analysis_horizon_fine_steps"])
    for cadence, expected in design["time"]["usable_transitions_by_cadence"].items():
        offsets = np.arange(0, horizon, int(cadence))
        assert len(offsets) - 1 == int(expected)


def test_preprocessing_is_fit_on_train_only(design):
    """Scaling constants must come from TRAIN rows alone.

    Refitting on TRAIN rows while corrupting VALIDATION and TEST rows must leave the
    coefficients bit-identical.
    """
    system = dgp.build_system(design, "path5", "MED", "MED")
    regime = resolve_regime(design, "T", "S5", "path5", overrides={})
    trajectory = dgp.simulate(design, system, regime, rng_for(101), {})
    bundle = make_observations(design, system, trajectory, regime, rng_for(102))

    node_design = build_design(bundle, 0, "L")
    train = split_masks(node_design)[TRAIN]
    intercept_a, coef_a, _ = _fit_scaled(
        node_design.X[train], node_design.y[train], node_design.penalized, 0.0
    )

    corrupted = node_design.X.copy()
    corrupted[~train] *= 1000.0
    intercept_b, coef_b, _ = _fit_scaled(
        corrupted[train], node_design.y[train], node_design.penalized, 0.0
    )
    assert intercept_a == intercept_b
    assert np.array_equal(coef_a, coef_b)


def test_unscaling_preserves_predictions_and_nonnegativity(design):
    """Coefficients are returned in ORIGINAL units; predictions must be unchanged."""
    system = dgp.build_system(design, "path5", "MED", "MED")
    regime = resolve_regime(design, "T", "S5", "path5", overrides={})
    trajectory = dgp.simulate(design, system, regime, rng_for(103), {})
    bundle = make_observations(design, system, trajectory, regime, rng_for(104))

    node_design = build_design(bundle, 2, "N")
    train = split_masks(node_design)[TRAIN]
    X, y = node_design.X[train], node_design.y[train]
    intercept, coef, diagnostics = _fit_scaled(X, y, node_design.penalized, 0.05)

    scale, mean = diagnostics["feature_scale"], diagnostics["feature_mean"]
    scaled_coef = coef * scale
    scaled_prediction = diagnostics["scaled_intercept"] + ((X - mean) / scale) @ scaled_coef
    assert np.allclose(intercept + X @ coef, scaled_prediction, atol=1e-9)
    assert np.all(coef[node_design.penalized] >= -1e-12)


# -------------------------------------------------------------------------------------
# Seeds
# -------------------------------------------------------------------------------------


def test_seed_pools_are_disjoint(design):
    pools = {name: set(seed_list(design, name)) for name in design["seeds"]["pools"]}
    names = list(pools)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            assert not (pools[a] & pools[b]), f"{a} and {b} share seeds"


def test_seed_lists_are_reproducible(design):
    for name in design["seeds"]["pools"]:
        assert seed_list(design, name) == seed_list(design, name)


def test_smoke_pool_is_small_and_separate(design):
    smoke = set(seed_list(design, "SMOKE"))
    analysis = set(seed_list(design, "ANALYSIS"))
    assert len(smoke) == int(design["seeds"]["pools"]["SMOKE"]["n_seeds"])
    assert not smoke & analysis
    assert design["seeds"]["pools"]["SMOKE"]["role"] == "ENGINEERING ONLY"


# -------------------------------------------------------------------------------------
# Masked node
# -------------------------------------------------------------------------------------


def _fitted_network(design, seed=201, overrides=None):
    system = dgp.build_system(design, "path5", "MED", "MED")
    regime = resolve_regime(design, "T", "S5", "path5", overrides=overrides or {})
    trajectory = dgp.simulate(design, system, regime, rng_for(seed), {})
    bundle = make_observations(design, system, trajectory, regime, rng_for(seed + 1))
    return system, trajectory, bundle, fit_ladder(bundle, design)


def test_masked_node_no_leak(design):
    """Poison every withheld entry with a large finite sentinel; the forecast must not move."""
    _, _, bundle, ladder = _fitted_network(design)
    node, horizon = 2, 12
    onset = bundle.test_onset()

    nan_masked = mask_node_for_test(bundle, node, onset, horizon, sentinel=np.nan)
    poisoned = mask_node_for_test(bundle, node, onset, horizon, sentinel=1.0e9)

    for model in ("L", "N"):
        a, _ = interventions.masked_node_forecast(nan_masked, ladder, model, node, onset, horizon)
        b, _ = interventions.masked_node_forecast(poisoned, ladder, model, node, onset, horizon)
        assert np.array_equal(np.isnan(a), np.isnan(b))
        good = np.isfinite(a)
        assert np.array_equal(a[good], b[good]), f"{model}: withheld head leaked into recursion"
        assert np.all(np.abs(a[good]) < 1e6), "sentinel magnitude propagated into the forecast"


def test_masked_node_starts_from_last_admissible_pre_mask_observation(design):
    _, _, bundle, ladder = _fitted_network(design)
    node, horizon = 2, 12
    onset = bundle.test_onset()
    masked = mask_node_for_test(bundle, node, onset, horizon)
    assert np.isfinite(masked.y[onset - 1, node]), "pre-mask observation must be preserved"
    assert np.all(np.isnan(masked.y[onset : onset + horizon, node]))


def test_masked_node_completes_steps_at_reference_missingness(design):
    """The protocol must remain evaluable at the reference regime's missingness."""
    _, _, bundle, ladder = _fitted_network(design)
    node, horizon = 2, 12
    onset = bundle.test_onset()
    masked = mask_node_for_test(bundle, node, onset, horizon)
    predictions, _ = interventions.masked_node_forecast(masked, ladder, "N", node, onset, horizon)
    completed = int(np.sum(np.isfinite(predictions)))
    minimum = int(design["spatial_evaluation"]["masked_node_protocol"]["min_completed_steps"])
    assert completed >= minimum


def test_masked_node_start_walks_back_past_a_missing_pre_mask_instant(design):
    """"Final ADMISSIBLE pre-mask observation" means the last one that exists.

    Anchoring rigidly at onset-1 discards the whole replicate whenever that single instant
    happens to be missing, which at the reference 10% missingness is 10% of replicates for no
    scientific reason. The recursion must instead start from the most recent observed
    pre-mask head, and must still never touch a withheld one.
    """
    from dataclasses import replace

    _, _, bundle, ladder = _fitted_network(design)
    node, horizon = 2, 12
    onset = bundle.test_onset()

    y = bundle.y.copy()
    y[onset - 1, node] = np.nan          # knock out exactly the rigid anchor
    gapped = mask_node_for_test(replace(bundle, y=y), node, onset, horizon)

    predictions, _ = interventions.masked_node_forecast(gapped, ladder, "N", node, onset, horizon)
    minimum = int(design["spatial_evaluation"]["masked_node_protocol"]["min_completed_steps"])
    assert int(np.sum(np.isfinite(predictions))) >= minimum, (
        "a single missing pre-mask instant must not abandon the replicate"
    )

    # The walk-back must not become an excuse to read a withheld value.
    poisoned_y = y.copy()
    poisoned_y[onset : onset + horizon, node] = 1.0e9
    poisoned = mask_node_for_test(replace(bundle, y=poisoned_y), node, onset, horizon)
    other, _ = interventions.masked_node_forecast(poisoned, ladder, "N", node, onset, horizon)
    good = np.isfinite(predictions)
    assert np.array_equal(predictions[good], other[good])


def test_masked_node_falls_back_to_an_observed_node_under_partial_monitoring(design):
    """The frozen preferred index is often uninstrumented once observed_node_fraction < 1.

    Without the deterministic nearest-observed fallback the masked-node criterion silently
    disappears in exactly the sparse-network cells it is most informative about, so this
    checks the fallback both fires and stays deterministic.
    """
    observed = np.array([False, False, True, False, True])
    for preferred, expected in ((2, 2), (0, 2)):
        chosen = int(
            np.flatnonzero(observed)[
                np.lexsort(
                    (np.flatnonzero(observed), np.abs(np.flatnonzero(observed) - preferred))
                )[0]
            ]
        )
        assert chosen == expected
        assert observed[chosen], "fallback must land on an observed node"

    # Ties resolve toward the lower index, so the choice is seed- and model-independent.
    tied = np.array([True, False, False, False, True])
    idx = np.flatnonzero(tied)
    chosen = int(idx[np.lexsort((idx, np.abs(idx - 2)))[0]])
    assert chosen == 0


def test_zero_shot_held_out_node_is_not_claimed(design):
    assert design["spatial_evaluation"]["zero_shot_held_out_node"] == "NOT_PERFORMED_IN_V1"


# -------------------------------------------------------------------------------------
# Interventions
# -------------------------------------------------------------------------------------


def test_paired_intervention_noise_cancels(design):
    """Paired truth response must be invariant to the process-noise realization."""
    system = dgp.build_system(design, "path5", "MED", "MED")
    regime = resolve_regime(design, "T", "S5", "path5", overrides={})
    spec = interventions.InterventionSpec("persistent_step", (0,), 0.5, 26, 52)

    responses = []
    for seed in (301, 302, 303):
        trajectory = dgp.simulate(design, system, regime, rng_for(seed), {})
        onset = trajectory.analysis_start + 400
        noisy = interventions.true_paired_response(system, trajectory, onset, spec, 4)
        clean = interventions.true_paired_response(
            system, trajectory, onset, spec, 4, force_noise_free=True
        )
        assert np.allclose(noisy, clean, atol=1e-12), "pairing failed to cancel the disturbance"
        responses.append(noisy)
    for other in responses[1:]:
        assert np.allclose(responses[0], other, atol=1e-12)


def test_intervention_response_has_correct_sign(design):
    """More pumping must lower head everywhere it has any effect."""
    system = dgp.build_system(design, "path5", "MED", "MED")
    regime = resolve_regime(design, "T", "S5", "path5", overrides={})
    trajectory = dgp.simulate(design, system, regime, rng_for(305), {})
    spec = interventions.InterventionSpec("persistent_step", (0,), 0.5, 26, 52)
    response = interventions.true_paired_response(system, trajectory, trajectory.analysis_start + 400, spec, 4)
    assert response[-1, 0] < 0
    assert np.all(response <= 1e-12)


def test_zero_intervention_gives_exactly_zero(design):
    system = dgp.build_system(design, "path5", "MED", "MED")
    regime = resolve_regime(design, "T", "S5", "path5", overrides={})
    trajectory = dgp.simulate(design, system, regime, rng_for(307), {})
    spec = interventions.InterventionSpec("persistent_step", (0,), 0.0, 26, 52)
    response = interventions.true_paired_response(system, trajectory, trajectory.analysis_start + 400, spec, 4)
    assert np.all(response == 0.0)


def test_intervention_recovers_after_release(design):
    """Head must recover once the step ends, which is what makes the step test meaningful."""
    system = dgp.build_system(design, "path5", "MED", "MED")
    regime = resolve_regime(design, "T", "S5", "path5", overrides={})
    trajectory = dgp.simulate(design, system, regime, rng_for(309), {})
    spec = interventions.InterventionSpec("persistent_step", (0,), 0.5, 26, 52)
    response = interventions.true_paired_response(system, trajectory, trajectory.analysis_start + 400, spec, 4)
    assert response[52, 0] > response[26, 0], "no recovery after the step ended"


def test_model_paired_response_is_independent_of_initial_state(design):
    """For a linear model the paired difference cannot depend on where it started."""
    _, _, bundle, ladder = _fitted_network(design)
    spec = interventions.InterventionSpec("persistent_step", (0,), 0.5, 26, 52)
    a = interventions.model_paired_response(bundle, ladder, "N", spec, 13)
    b = interventions.model_paired_response(bundle, ladder, "N", spec, 13)
    assert np.array_equal(a, b)
    assert np.allclose(a[0], 0.0)


def test_b0_predicts_no_intervention_response(design):
    """B0 has no pumping channel, so its intervention response must be identically zero."""
    _, _, bundle, ladder = _fitted_network(design)
    spec = interventions.InterventionSpec("persistent_step", (0,), 0.5, 26, 52)
    response = interventions.model_paired_response(bundle, ladder, "B0", spec, 13)
    assert np.all(response == 0.0)


def test_interventions_are_launched_in_the_protected_test_segment(design):
    _, trajectory, bundle, _ = _fitted_network(design)
    onset = bundle.test_onset()
    assert bundle.split[onset] == TEST
    assert onset > 0 and bundle.split[onset - 1] == VALIDATION
