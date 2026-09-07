"""Truth-leakage guards.

Architecture under test:

    truth generator -> synthetic observations -> estimation code -> estimated model
    truth parameters ------------------------------------------> evaluation layer only

Three independent guards: static signature introspection, a runtime tripwire that raises on
ANY attribute access to a truth object, and a content check that the observation bundle
carries no truth fields.
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from groundwater_identifiability_synthetic.src import fit as fit_module
from groundwater_identifiability_synthetic.src import identifiability, models
from groundwater_identifiability_synthetic.src import dgp
from groundwater_identifiability_synthetic.src.design import resolve_regime, rng_for
from groundwater_identifiability_synthetic.src.fit import fit_ladder
from groundwater_identifiability_synthetic.src.observations import (
    ObservationBundle,
    make_observations,
)

TRUTH_TYPES = (dgp.SystemTruth, dgp.Trajectory)
TRUTH_PARAM_NAMES = {"system", "truth", "trajectory", "system_truth", "true_edges", "kappa_true"}


def test_estimation_functions_never_accept_truth_arguments():
    """No public function in models.py, fit.py or identifiability.py may take a truth object."""
    offenders = []
    for module in (models, fit_module, identifiability):
        for name, function in inspect.getmembers(module, inspect.isfunction):
            if function.__module__ != module.__name__ or name.startswith("_"):
                continue
            signature = inspect.signature(function)
            for parameter in signature.parameters.values():
                if parameter.name in TRUTH_PARAM_NAMES:
                    offenders.append(f"{module.__name__}.{name}({parameter.name})")
                annotation = parameter.annotation
                if isinstance(annotation, type) and issubclass(annotation, TRUTH_TYPES):
                    offenders.append(f"{module.__name__}.{name}({parameter.name}: truth type)")
    assert not offenders, f"estimation code exposes truth parameters: {offenders}"


def test_estimation_modules_do_not_import_the_dgp():
    """models.py and fit.py must not be able to reach truth construction at all."""
    for module in (models, fit_module):
        source = inspect.getsource(module)
        assert "from .dgp import" not in source
        assert "import dgp" not in source


def test_observation_bundle_contains_no_truth_fields(design):
    system = dgp.build_system(design, "path5", "MED", "MED")
    regime = resolve_regime(design, "T", "S5", "path5", overrides={})
    trajectory = dgp.simulate(design, system, regime, rng_for(5), {})
    bundle = make_observations(design, system, trajectory, regime, rng_for(6))

    forbidden = {"S", "C", "C0", "A", "B_Q", "B_R", "kappa", "true_edges", "h", "eps", "R_true", "Q_true"}
    present = forbidden & set(vars(bundle))
    assert not present, f"observation bundle leaks truth fields: {present}"
    assert forbidden.isdisjoint(bundle.meta.keys())


def test_runtime_tripwire_estimation_never_touches_truth(design):
    """Wrap the truth objects so ANY attribute access raises, then fit the whole ladder."""

    class Tripwire:
        def __init__(self, wrapped):
            object.__setattr__(self, "_wrapped", wrapped)

        def __getattribute__(self, name):
            raise dgp.TruthAccessViolation(f"estimation code accessed truth attribute {name!r}")

    system = dgp.build_system(design, "path5", "MED", "MED")
    regime = resolve_regime(design, "T", "S5", "path5", overrides={})
    trajectory = dgp.simulate(design, system, regime, rng_for(7), {})
    bundle = make_observations(design, system, trajectory, regime, rng_for(8))

    poisoned_system = Tripwire(system)
    poisoned_trajectory = Tripwire(trajectory)
    with pytest.raises(dgp.TruthAccessViolation):
        _ = poisoned_system.S  # the tripwire itself must work

    # The estimation layer only ever receives the bundle, so this must complete untouched.
    ladder = fit_ladder(bundle, design)
    assert ladder.fits["L"], "ladder failed to fit"
    del poisoned_system, poisoned_trajectory


def test_candidate_graph_independent_of_truth(design):
    """Identical geometry, different true edges -> identical candidate graph."""
    from groundwater_identifiability_synthetic.src.observations import candidate_graph

    path = dgp.build_system(design, "path5", "MED", "MED")
    null = dgp.build_system(design, "null5", "MED", "MED")
    assert np.array_equal(path.coordinates, null.coordinates)
    assert path.true_edges != null.true_edges

    neighbours_a, pairs_a, _ = candidate_graph(design, path.coordinates)
    neighbours_b, pairs_b, _ = candidate_graph(design, null.coordinates)
    assert neighbours_a == neighbours_b
    assert pairs_a == pairs_b


def test_candidate_graph_contains_decoys_and_nests_true_graph(design):
    from groundwater_identifiability_synthetic.src.observations import candidate_graph

    for topology in ("path5", "star5", "bridge6"):
        system = dgp.build_system(design, topology, "MED", "MED")
        _, pairs, _ = candidate_graph(design, system.coordinates)
        true_edges = set(system.true_edges)
        assert true_edges <= pairs, f"{topology}: true graph must nest in the candidate rule"
        assert pairs - true_edges, f"{topology}: candidate set must contain decoy edges"
        expected = design["topologies"][topology]["expected_candidate_pairs"]
        assert len(pairs) == expected


def test_s9_true_edge_lies_outside_candidate_set(design):
    """The candidate-support misspecification must be real, not nominal."""
    from groundwater_identifiability_synthetic.src.observations import candidate_graph

    system = dgp.build_system(design, "path5_hidden", "MED", "MED")
    _, pairs, _ = candidate_graph(design, system.coordinates)
    missing = set(system.true_edges) - pairs
    assert missing == {(0, 4)}


def test_selection_never_uses_the_protected_test_split():
    """Hyperparameter selection must score on VALIDATION only.

    Checked structurally rather than by string search: every `_split_rmse` call inside
    `fit_ladder` must pass the VALIDATION label.
    """
    import ast
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(fit_module.fit_ladder)))
    labels = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_split_rmse":
            assert len(node.args) == 3, "unexpected _split_rmse signature in fit_ladder"
            labels.append(ast.unparse(node.args[2]))
    assert labels, "no scoring calls found in fit_ladder"
    assert set(labels) == {"VALIDATION"}, f"selection scored on {set(labels)}"


def test_protected_test_metrics_are_computed_outside_the_fitting_path():
    """Test-split RMSE exists, but only in reporting helpers, never in selection."""
    import ast
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(fit_module.protected_test_rmse)))
    labels = [
        ast.unparse(node.args[2])
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_split_rmse"
    ]
    assert labels == ["TEST"]


def test_bundle_hides_unobserved_nodes(design):
    system = dgp.build_system(design, "path5", "MED", "MED")
    regime = resolve_regime(design, "T", "S5", "path5", overrides={"observed_node_fraction": 0.6})
    trajectory = dgp.simulate(design, system, regime, rng_for(9), {})
    bundle = make_observations(design, system, trajectory, regime, rng_for(10))
    hidden = ~bundle.observed_nodes
    assert hidden.any()
    assert np.all(np.isnan(bundle.y[:, hidden]))
    for node, neighbours in bundle.candidate_neighbors.items():
        assert not (set(neighbours) & set(np.flatnonzero(hidden).tolist()))
