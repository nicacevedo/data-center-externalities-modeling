"""Legal RNG/system-seed pairs, Tier-1 CRN equality, Tier-3 shared-base checks."""

from __future__ import annotations

import numpy as np
import pytest

from src_v3 import dgp
from src_v3.design import resolve_v3_cell, rng_for, seed_list
from src_v3.modes import require_legal
from src_v3.observations import make_observations
from src_v3.rng import StreamBank, component_spawn_key, COMPONENTS


def test_legal_pairs_accepted():
    require_legal("legacy_sequential", "legacy_v2")
    require_legal("named_substreams", "orthogonal_v3")


def test_illegal_mixed_pairs_rejected():
    with pytest.raises(ValueError, match="illegal"):
        require_legal("legacy_sequential", "orthogonal_v3")
    with pytest.raises(ValueError, match="illegal"):
        require_legal("named_substreams", "legacy_v2")


def test_spawn_keys_are_sha256_not_python_hash():
    a = component_spawn_key("pumping_innovations")
    b = component_spawn_key("recharge_innovations")
    assert a != b
    assert component_spawn_key("pumping_innovations") == a
    assert "pumping_degradation_z" in COMPONENTS


def _realize(design, cell_id, seed):
    regime = resolve_v3_cell(design, cell_id)
    streams = StreamBank(int(seed))
    rng = rng_for(int(seed))
    system = dgp.build_system(
        design,
        regime.topology,
        regime.memory,
        regime.gamma,
        system_seed_mode="orthogonal_v3",
    )
    traj = dgp.simulate(design, system, regime, rng, {}, streams=streams)
    bundle = make_observations(design, system, traj, regime, rng, streams=streams)
    return system, traj, bundle


def test_tier1_block_a_shared_arrays_bit_identical(design):
    seed = seed_list(design, "V3_SMOKE")[0]
    systems = {}
    trajs = {}
    bundles = {}
    for cid in ("A_PEXACT", "A_S025", "A_S050", "A_S100", "A_S200"):
        systems[cid], trajs[cid], bundles[cid] = _realize(design, cid, seed)

    ref = "A_PEXACT"
    for cid in ("A_S025", "A_S050", "A_S100", "A_S200"):
        np.testing.assert_array_equal(trajs[cid].h, trajs[ref].h)
        np.testing.assert_array_equal(trajs[cid].Q_true, trajs[ref].Q_true)
        np.testing.assert_array_equal(trajs[cid].R_true, trajs[ref].R_true)
        np.testing.assert_array_equal(trajs[cid].eps, trajs[ref].eps)
        np.testing.assert_array_equal(bundles[cid].R_proxy, bundles[ref].R_proxy)
        np.testing.assert_array_equal(bundles[cid].y, bundles[ref].y)
        z_ref = bundles[ref].meta["pumping_degradation_z"]
        z_cid = bundles[cid].meta["pumping_degradation_z"]
        np.testing.assert_array_equal(z_cid, z_ref)

    q_true = bundles["A_PEXACT"].Q_obs
    z = bundles["A_PEXACT"].meta["pumping_degradation_z"]
    for cid, s in (("A_S025", 0.025), ("A_S050", 0.05), ("A_S100", 0.10), ("A_S200", 0.20)):
        expected = q_true * np.exp(s * z - 0.5 * s * s)
        np.testing.assert_allclose(bundles[cid].Q_obs, expected, rtol=0, atol=1e-12)
        assert not np.array_equal(bundles[cid].Q_obs, q_true)


def test_orthogonal_gamma_storage_identical_across_levels(design):
    seed_parts_systems = []
    for cid in ("B_GNONE", "B_GLOW", "B_GMED", "B_GHIGH"):
        regime = resolve_v3_cell(design, cid)
        sys = dgp.build_system(
            design,
            regime.topology,
            regime.memory,
            regime.gamma,
            system_seed_mode="orthogonal_v3",
        )
        seed_parts_systems.append(sys)
    S0 = seed_parts_systems[0].S
    for sys in seed_parts_systems[1:]:
        np.testing.assert_array_equal(sys.S, S0)
    assert not np.allclose(seed_parts_systems[0].C, seed_parts_systems[-1].C)


def test_legacy_system_seed_depends_on_gamma(design):
    s_none = dgp.build_system(design, "path5", "MED", "NONE", system_seed_mode="legacy_v2")
    s_med = dgp.build_system(design, "path5", "MED", "MED", system_seed_mode="legacy_v2")
    assert not np.array_equal(s_none.S, s_med.S)


def test_tier3_block_c_shared_base_innovations_different_realized_truth(design):
    seed = seed_list(design, "V3_SMOKE")[0]
    sys_m, traj_m, bun_m = _realize(design, "C_REAL_GMED", seed)
    sys_h, traj_h, bun_h = _realize(design, "C_REAL_GHIGH", seed)
    # Structural S identical under orthogonal_v3; coupling (hence A, h) differs.
    np.testing.assert_array_equal(sys_m.S, sys_h.S)
    assert not np.allclose(sys_m.A, sys_h.A)
    assert not np.allclose(traj_m.h, traj_h.h)
    # Shared named-stream forcing innovations: true Q/R base draws match before
    # the state equation; Q_true is generated independently of A, so Q_true matches.
    np.testing.assert_array_equal(traj_m.Q_true, traj_h.Q_true)
    np.testing.assert_array_equal(traj_m.R_true, traj_h.R_true)
    np.testing.assert_array_equal(traj_m.eps, traj_h.eps)
