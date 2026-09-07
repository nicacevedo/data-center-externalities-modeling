"""21-cell matrix, seed disjointness, uint64 preservation, no V3 gates."""

from __future__ import annotations

import numpy as np

from src_v3.design import (
    load_design,
    resolved_cell_table,
    seed_list,
    seed_pool_hash,
    v3_all_cells,
)
from src_v3.design import V2_PARENT_ROOT


EXPECTED_IDS = [
    "A_PEXACT", "A_S025", "A_S050", "A_S100", "A_S200",
    "A1_PEXACT_K1", "A1_S100_K1",
    "B_GNONE", "B_GLOW", "B_GMED", "B_GHIGH",
    "C_REAL_GMED", "C_REAL_GHIGH",
    "D_PE_RE_R0", "D_PE_RE_R3", "D_PE_RN_R0", "D_PE_RN_R3",
    "D_PM_RE_R0", "D_PM_RE_R3", "D_PM_RN_R0", "D_PM_RN_R3",
]


def test_resolved_21_cell_matrix_exact(design):
    cells = v3_all_cells(design)
    assert list(cells) == EXPECTED_IDS
    assert len(cells) == 21
    table = resolved_cell_table(design)
    assert len(table) == 21
    yaml_ids = list(design["v3_cells"])
    assert yaml_ids == EXPECTED_IDS
    for row, cid in zip(table, EXPECTED_IDS):
        spec = design["v3_cells"][cid]
        assert row["cell_id"] == cid
        assert row["gamma"] == spec["gamma"]
        assert row["cadence"] == spec["cadence"]
        assert row["pumping_quality"] == spec["pumping_quality"]


def test_no_v3_gates(design):
    assert design.get("gates") == {} or design.get("gates") is None
    from src_v3.design import gate_cells
    assert gate_cells(design) == {}


def test_uint64_seed_preservation(design):
    for pool in ("V3_DETERMINISM", "V3_SMOKE", "V3_ANALYSIS", "V3_BENCHMARK"):
        values = seed_list(design, pool)
        spec = design["seeds"]["pools"][pool]
        root = np.random.SeedSequence(entropy=int(spec["entropy"]))
        children = root.spawn(int(spec["n_seeds"]))
        expected = [int(child.generate_state(1, dtype=np.uint64)[0]) for child in children]
        assert values == expected
        assert all(0 <= v < 2**64 for v in values)


def test_seed_pool_disjointness(design):
    from groundwater_identifiability_synthetic.src.design import (
        load_design as load_v2,
        seed_list as v2_seeds,
    )

    v2 = load_v2(V2_PARENT_ROOT / "config" / "design_v2.yaml")
    v3_pools = {p: set(seed_list(design, p)) for p in (
        "V3_DETERMINISM", "V3_SMOKE", "V3_ANALYSIS", "V3_BENCHMARK"
    )}
    v2_pools = {p: set(v2_seeds(v2, p)) for p in ("G0", "CALIBRATION", "SMOKE", "ANALYSIS")}
    names = list(v3_pools) + [f"V2_{k}" for k in v2_pools]
    sets = list(v3_pools.values()) + list(v2_pools.values())
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            overlap = sets[i] & sets[j]
            assert not overlap, f"{names[i]} overlaps {names[j]}"
    assert len(v3_pools["V3_ANALYSIS"]) == 200
    _ = seed_pool_hash(design, "V3_ANALYSIS")  # materialize-for-hash only


def test_analysis_outcomes_not_present(v3_root):
    analysis_dir = v3_root / "outputs" / "analysis"
    if analysis_dir.exists():
        assert not list(analysis_dir.glob("*replicates*"))
