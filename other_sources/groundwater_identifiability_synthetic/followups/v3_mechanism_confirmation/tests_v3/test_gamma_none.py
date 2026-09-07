"""gamma=NONE uses the validated V2 zero-coupling construction."""

from __future__ import annotations

import inspect

import numpy as np

from src_v3 import dgp
from src_v3.design import resolve_v3_cell
from src_v3.diagnostics import neighbour_flux_share


def test_gamma_none_source_has_no_division_by_gamma():
    source = inspect.getsource(dgp.build_system)
    assert "has_coupling = gamma > 0.0 and len(edges) > 0" in source
    assert "unit_C0 = np.ones(n, dtype=float)" in source


def test_gamma_none_exact_zero_coupling_finite_stable(design):
    regime = resolve_v3_cell(design, "B_GNONE")
    system = dgp.build_system(
        design,
        regime.topology,
        regime.memory,
        regime.gamma,
        system_seed_mode="orthogonal_v3",
    )
    assert np.all(system.C == 0.0)
    assert np.all(np.diag(system.A) != 0)
    off = system.A.copy()
    np.fill_diagonal(off, 0.0)
    assert np.allclose(off, 0.0)
    assert np.all(np.isfinite(system.A))
    assert np.all(np.isfinite(system.C0))
    assert np.all(np.isfinite(system.S))
    assert system.rho_A < 1.0 - float(design["stability"]["contraction_margin_delta"]) + 1e-12
    tau_target = float(design["memory_regimes"]["targets_fine_steps"][regime.memory])
    tol = float(design["memory_regimes"]["target_match_tolerance"])
    assert abs(system.tau_relax_realized - tau_target) / tau_target <= tol + 1e-12

    from src_v3.design import rng_for
    traj = dgp.simulate(design, system, regime, rng_for(1), {})
    assert neighbour_flux_share(system, traj) == 0.0
