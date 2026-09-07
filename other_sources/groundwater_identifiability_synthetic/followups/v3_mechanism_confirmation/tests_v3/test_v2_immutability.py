"""V2 hashes immutable; vendored-parent parity; no V3 files in V2 globs."""

from __future__ import annotations

import hashlib
from pathlib import Path

from src_v3.design import (
    V2_EXPECTED_CODE_HASH,
    V2_EXPECTED_DESIGN_HASH,
    V2_PARENT_ROOT,
    MODULE_ROOT,
    sha256_file,
    v2_parent_code_hash,
    v2_parent_design_hash,
)

CHANGED_VENDORED = {
    "src_v3/design.py",
    "src_v3/dgp.py",
    "src_v3/observations.py",
    "src_v3/evaluation.py",
    "src_v3/plan.py",
    "src_v3/__init__.py",
}

UNCHANGED_VENDORED = {
    "src_v3/fit.py",
    "src_v3/identifiability.py",
    "src_v3/interventions.py",
    "src_v3/metrics.py",
    "src_v3/models.py",
    "src_v3/summarize.py",
}


def test_v2_design_hash_unchanged():
    assert v2_parent_design_hash() == V2_EXPECTED_DESIGN_HASH


def test_v2_code_hash_unchanged():
    assert v2_parent_code_hash() == V2_EXPECTED_CODE_HASH


def test_v2_seed_hashes_unchanged():
    from groundwater_identifiability_synthetic.src.design import load_design, seed_pool_hash

    v2 = load_design(V2_PARENT_ROOT / "config" / "design_v2.yaml")
    assert seed_pool_hash(v2, "ANALYSIS") == (
        "bd6db2aac7743cc83d5d5ecd8b5f07fefe18747649e3489a5b89e7e0cb689015"
    )


def test_unchanged_vendored_files_match_parents():
    for rel in sorted(UNCHANGED_VENDORED):
        vendored = MODULE_ROOT / rel
        parent = V2_PARENT_ROOT / rel.replace("src_v3/", "src/")
        assert vendored.exists() and parent.exists()
        assert sha256_file(vendored) == sha256_file(parent), rel


def test_changed_vendored_files_listed_and_differ():
    for rel in sorted(CHANGED_VENDORED):
        vendored = MODULE_ROOT / rel
        parent = V2_PARENT_ROOT / rel.replace("src_v3/", "src/")
        assert vendored.exists() and parent.exists()
        assert sha256_file(vendored) != sha256_file(parent), rel


def test_divergence_manifest_lists_every_changed_vendored_file():
    text = (MODULE_ROOT / "V3_DIVERGENCE_FROM_V2.md").read_text(encoding="utf-8")
    for rel in sorted(CHANGED_VENDORED):
        assert rel in text, rel


def test_no_v3_python_under_v2_src_scripts_tests():
    v3_dir = MODULE_ROOT
    for folder in ("src", "scripts", "tests"):
        root = V2_PARENT_ROOT / folder
        for path in root.rglob("*.py"):
            assert v3_dir not in path.parents
            assert path.name not in ("rng.py", "benchmarks.py", "summarize_v3.py")
