"""Layer-2 / Layer-3 pseudo-true training benchmarks and the frozen benchmark pool.

`F_train_true` uses the latent true variables; `F_train_obs` uses the actual estimator-facing
variables. Both run on the same admissible-row support so the gap between them is about value
corruption, not row attrition.
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from src_v3 import benchmarks as bm
from src_v3 import dgp
from src_v3.benchmarks import (
    benchmark_prefixes,
    latent_true_columns,
    pseudo_true_targets,
    true_l_design_block,
)
from src_v3.design import resolve_regime, resolve_v3_cell, rng_for, seed_list
from src_v3.evaluation import scenario_options
from src_v3.models import build_design
from src_v3.modes import RNG_NAMED, SEED_ORTHOGONAL
from src_v3.observations import TRAIN, make_observations
from src_v3.rng import StreamBank

PREFIXES = (16, 32, 64, 128)


# -------------------------------------------------------------------------------------
# The frozen benchmark pool
# -------------------------------------------------------------------------------------


def test_benchmark_pool_is_128_seeds(design):
    spec = design["seeds"]["pools"]["V3_BENCHMARK"]
    assert int(spec["n_seeds"]) == 128
    assert int(spec["previous_n_seeds_pass1"]) == 16
    assert [int(m) for m in spec["convergence_prefixes"]] == list(PREFIXES)
    assert benchmark_prefixes(design) == PREFIXES
    seeds = seed_list(design, "V3_BENCHMARK")
    assert len(seeds) == 128
    assert len(set(seeds)) == 128
    assert all(0 <= s < 2**64 for s in seeds)


def test_benchmark_convergence_prefixes_are_strictly_nested(design):
    """spawn(128)[:m] == spawn(m): one pool, nested prefixes, not four pools."""
    entropy = int(design["seeds"]["pools"]["V3_BENCHMARK"]["entropy"])
    full = seed_list(design, "V3_BENCHMARK")
    for m in PREFIXES:
        root = np.random.SeedSequence(entropy=entropy)
        prefix = [int(c.generate_state(1, dtype=np.uint64)[0]) for c in root.spawn(m)]
        assert prefix == full[:m], m


def test_benchmark_pool_and_every_prefix_disjoint_from_all_other_pools(design):
    from groundwater_identifiability_synthetic.src.design import (
        load_design as load_v2,
        seed_list as v2_seeds,
    )
    from src_v3.design import V2_PARENT_ROOT

    v2 = load_v2(V2_PARENT_ROOT / "config" / "design_v2.yaml")
    others = {p: set(seed_list(design, p)) for p in ("V3_DETERMINISM", "V3_SMOKE", "V3_ANALYSIS")}
    others.update({f"V2_{p}": set(v2_seeds(v2, p)) for p in ("G0", "CALIBRATION", "SMOKE", "ANALYSIS")})
    full = seed_list(design, "V3_BENCHMARK")
    for m in PREFIXES:
        prefix = set(full[:m])
        for name, pool in others.items():
            assert not (prefix & pool), f"V3_BENCHMARK[:{m}] overlaps {name}"


def test_benchmark_module_reads_no_analysis_seeds():
    source = inspect.getsource(bm)
    assert "V3_ANALYSIS" not in source
    assert 'seed_list(design, "V3_BENCHMARK")' in source


# -------------------------------------------------------------------------------------
# The latent-true design block
# -------------------------------------------------------------------------------------


def _realize(design, regime, seed):
    options = scenario_options(design, regime)
    system = dgp.build_system(
        design,
        regime.topology,
        regime.memory,
        regime.gamma,
        recharge_efficiency=float(options.get("recharge_efficiency", 1.0)),
        system_seed_mode=SEED_ORTHOGONAL,
    )
    streams = StreamBank(int(seed))
    traj = dgp.simulate(design, system, regime, rng_for(int(seed)), options, streams=streams)
    bundle = make_observations(design, system, traj, regime, rng_for(int(seed)), streams=streams)
    return system, traj, bundle


def test_true_design_block_shares_columns_rows_and_support(design):
    regime = resolve_v3_cell(design, "A_S200")
    seed = seed_list(design, "V3_BENCHMARK")[0]
    _system, traj, bundle = _realize(design, regime, seed)
    columns = latent_true_columns(traj, bundle)
    obs = build_design(bundle, 0, "L")
    X_true, y_true, names = true_l_design_block(obs, columns, bundle, 0)
    assert names == obs.names
    assert X_true.shape == obs.X.shape
    assert y_true.shape == obs.y.shape
    # Deterministic calendar columns are shared bit-for-bit.
    for col in ("season_sin", "season_cos", "time_trend"):
        j = list(names).index(col)
        np.testing.assert_array_equal(X_true[:, j], obs.X[:, j])
    # The corrupted channels differ.
    j_q = list(names).index("pumping")
    assert not np.allclose(X_true[:, j_q], obs.X[:, j_q])
    # Same TRAIN support.
    assert int(np.sum(obs.split == TRAIN)) > 0


def test_true_design_block_rejects_a_column_without_a_latent_counterpart(design):
    regime = resolve_v3_cell(design, "A_PEXACT")
    seed = seed_list(design, "V3_BENCHMARK")[0]
    _system, traj, bundle = _realize(design, regime, seed)
    columns = latent_true_columns(traj, bundle)
    obs = build_design(bundle, 0, "L")
    bogus = type(obs)(**{**obs.__dict__, "names": obs.names + ("unknown_channel",)})
    with pytest.raises(ValueError, match="latent-true counterpart"):
        true_l_design_block(bogus, columns, bundle, 0)


# -------------------------------------------------------------------------------------
# Layer-2 / Layer-3 fixtures
# -------------------------------------------------------------------------------------


def test_f_train_true_equals_f_train_obs_under_a_fully_clean_observation_map(design):
    """P-EXACT + R-EXACT + no head noise + no missingness => the two designs coincide exactly."""
    regime = resolve_regime(
        design,
        "BENCH_CLEAN",
        "S1",
        "single",
        overrides={
            "memory": "MED",
            "cadence": 4,
            "gamma": "NONE",
            "pumping_quality": "P-EXACT",
            "recharge_quality": "R-EXACT",
            "confounding_rho": 0.0,
            "mcar_fraction": 0.0,
            "blocks_per_node": 0,
            "observed_node_fraction": 1.0,
            "snr_head": 0.0,
            "process_noise_sd": 0.05,
        },
    )
    seed = seed_list(design, "V3_BENCHMARK")[0]
    _system, traj, bundle = _realize(design, regime, seed)
    columns = latent_true_columns(traj, bundle)
    obs = build_design(bundle, 0, "L")
    X_true, y_true, _names = true_l_design_block(obs, columns, bundle, 0)
    np.testing.assert_array_equal(X_true, obs.X)
    np.testing.assert_array_equal(y_true, obs.y)

    out = pseudo_true_targets(design, regime, RNG_NAMED, SEED_ORTHOGONAL)
    assert out["F_train_true"] == pytest.approx(out["F_train_obs"], rel=0, abs=1e-12)
    assert out["F_train_true_a_pumped"] == pytest.approx(
        out["F_train_obs_a_pumped"], rel=0, abs=1e-12
    )


def test_f_train_true_is_invariant_across_the_tier1_sigma_ladder(design):
    """The latent truth is shared bit-for-bit by CRN, so Layer 2 cannot move with sigma.

    Layer 3 must move, because only the observed pumping column changes. This is exactly the
    separation the split of `F_train` into two quantities was introduced to make.
    """
    exact = pseudo_true_targets(
        design, resolve_v3_cell(design, "A_PEXACT"), RNG_NAMED, SEED_ORTHOGONAL
    )
    noisy = pseudo_true_targets(
        design, resolve_v3_cell(design, "A_S200"), RNG_NAMED, SEED_ORTHOGONAL
    )
    assert exact["F_train_true"] == pytest.approx(noisy["F_train_true"], rel=0, abs=1e-12)
    assert exact["F_train_true_beta_q_pumped"] == pytest.approx(
        noisy["F_train_true_beta_q_pumped"], rel=0, abs=1e-12
    )
    assert abs(noisy["F_train_obs"] - exact["F_train_obs"]) > 0.05
    # Attenuation direction: the observed pumping amplitude shrinks toward zero.
    assert abs(noisy["F_train_obs_beta_q_pumped"]) < abs(exact["F_train_obs_beta_q_pumped"])


def test_layer_1_is_at_or_below_layer_2_at_the_same_scoring_set(design):
    from src_v3.benchmarks import f_intervention_for_system

    seed = seed_list(design, "V3_BENCHMARK")[0]
    for cell_id in ("A_PEXACT", "A_S200", "B_GHIGH"):
        regime = resolve_v3_cell(design, cell_id)
        system, traj, bundle = _realize(design, regime, seed)
        layer1 = f_intervention_for_system(design, system, traj, bundle)["F_intervention_all"]
        layer2 = pseudo_true_targets(design, regime, RNG_NAMED, SEED_ORTHOGONAL)["F_train_true"]
        assert layer1 <= layer2 + 1e-9, cell_id


# -------------------------------------------------------------------------------------
# Convergence output schema
# -------------------------------------------------------------------------------------


def test_f_train_convergence_output_schema(design):
    regime = resolve_v3_cell(design, "A_PEXACT")
    out = pseudo_true_targets(design, regime, RNG_NAMED, SEED_ORTHOGONAL)
    convergence = out["F_train_convergence"]
    assert [row["prefix_n"] for row in convergence] == list(PREFIXES)
    required = (
        "F_train_true_nire",
        "F_train_obs_nire",
        "F_train_true_a_pumped",
        "F_train_obs_a_pumped",
        "F_train_true_beta_q_pumped",
        "F_train_obs_beta_q_pumped",
        "F_train_true_beta_recharge_pumped",
        "F_train_obs_beta_recharge_pumped",
    )
    for row in convergence:
        for key in required:
            assert key in row, key
            assert np.isfinite(float(row[key])), (row["prefix_n"], key)
        assert row["F_train_true_n_mc"] == row["prefix_n"]
        assert row["F_train_obs_n_mc"] == row["prefix_n"]
        assert row["F_train_true_pooled_train_rows"] > 0

    for lo, hi in zip(PREFIXES[:-1], PREFIXES[1:]):
        for key in required:
            assert f"delta_{key}_{lo}_to_{hi}" in out
    # Pooled rows must grow strictly with the prefix (nesting is respected).
    rows = [row["F_train_obs_pooled_train_rows"] for row in convergence]
    assert rows == sorted(rows) and rows[0] < rows[-1]
    assert out["F_train_n_mc"] == 128
    assert out["F_train_pool"] == "V3_BENCHMARK"
    assert out["F_train_prefixes"] == list(PREFIXES)
    # The reported values are the largest prefix.
    assert out["F_train_true"] == convergence[-1]["F_train_true_nire"]
    assert out["F_train_obs"] == convergence[-1]["F_train_obs_nire"]


def test_frozen_convergence_artifact_schema(v3_root):
    import csv

    path = v3_root / "outputs" / "benchmarks" / "BENCHMARK_CONVERGENCE_V3.csv"
    if not path.exists():
        pytest.skip("benchmark convergence not yet computed in this working tree")
    with open(path, "r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 21 * len(PREFIXES)
    assert {int(r["prefix_n"]) for r in rows} == set(PREFIXES)
    assert len({r["cell_id"] for r in rows}) == 21
