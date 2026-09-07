"""Independent recomputation of DESIGN_HASH / CODE_HASH / seed-pool hashes.

Read-only. Reimplements the hashing rules from src/design.py rather than importing
them, so that a bug in the frozen module would show up as a mismatch.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(
    "/home/nacevedo/RA/data-center-externalities-modeling/"
    "other_sources/groundwater_identifiability_synthetic"
)
DESIGN_ARTIFACTS = ("config/design_v2.yaml", "DESIGN_FREEZE_V2.md")
CODE_GLOBS = ("src/*.py", "scripts/*.py", "tests/*.py")


def sha256_file(path: Path) -> str:
    d = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            d.update(chunk)
    return d.hexdigest()


def design_hash() -> str:
    acc = hashlib.sha256()
    for rel in DESIGN_ARTIFACTS:
        acc.update(rel.encode("utf-8"))
        acc.update(sha256_file(ROOT / rel).encode("utf-8"))
    return acc.hexdigest()


def code_files() -> list[Path]:
    found: list[Path] = []
    for pattern in CODE_GLOBS:
        found.extend(sorted(ROOT.glob(pattern)))
    return [p for p in found if "__pycache__" not in p.parts]


def code_hash() -> str:
    acc = hashlib.sha256()
    for p in code_files():
        acc.update(p.relative_to(ROOT).as_posix().encode("utf-8"))
        acc.update(sha256_file(p).encode("utf-8"))
    return acc.hexdigest()


def seed_list(design, pool: str) -> list[int]:
    spec = design["seeds"]["pools"][pool]
    root = np.random.SeedSequence(entropy=int(spec["entropy"]))
    children = root.spawn(int(spec["n_seeds"]))
    return [int(c.generate_state(1, dtype=np.uint64)[0]) for c in children]


def main() -> None:
    with open(ROOT / "config" / "design_v2.yaml", encoding="utf-8") as fh:
        design = yaml.safe_load(fh)

    out = {
        "recomputed_design_hash": design_hash(),
        "recomputed_code_hash": code_hash(),
        "n_code_files": len(code_files()),
        "seed_pool_hashes": {},
        "seed_pool_sizes": {},
    }
    for pool in sorted(design["seeds"]["pools"]):
        vals = seed_list(design, pool)
        out["seed_pool_hashes"][pool] = hashlib.sha256(
            ",".join(str(v) for v in vals).encode("utf-8")
        ).hexdigest()
        out["seed_pool_sizes"][pool] = len(vals)
        if pool == "ANALYSIS":
            out["analysis_seeds_recomputed"] = vals

    # Compare against frozen records
    with open(ROOT / "outputs/provenance/DESIGN_V2_FREEZE.json", encoding="utf-8") as fh:
        freeze = json.load(fh)
    with open(ROOT / "outputs/provenance/SWEEP_MANIFEST.json", encoding="utf-8") as fh:
        sweep = json.load(fh)

    checks = {
        "design_hash_matches_freeze": out["recomputed_design_hash"] == freeze["design_hash"],
        "design_hash_matches_sweep": out["recomputed_design_hash"] == sweep["design_hash"],
        "code_hash_matches_freeze": out["recomputed_code_hash"] == freeze["code_hash"],
        "code_hash_matches_sweep": out["recomputed_code_hash"] == sweep["code_hash"],
        "analysis_seed_hash_matches": out["seed_pool_hashes"]["ANALYSIS"]
        == sweep["analysis_seed_hash"],
        "analysis_seeds_identical": out["analysis_seeds_recomputed"] == sweep["analysis_seeds"],
        "n_code_files_matches": out["n_code_files"] == freeze["n_code_files"],
        "pool_hashes_match_run_manifest": out["seed_pool_hashes"]
        == freeze["seed_pool_hashes"],
    }
    out["checks"] = checks

    # Code manifest per-file verification
    import csv

    manifest_mismatch = []
    with open(ROOT / "outputs/provenance/CODE_MANIFEST_V2.csv", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            p = ROOT / row["path"]
            if not p.exists():
                manifest_mismatch.append((row["path"], "MISSING"))
                continue
            if sha256_file(p) != row["sha256"]:
                manifest_mismatch.append((row["path"], "HASH_DIFFERS"))
    out["code_manifest_mismatches"] = manifest_mismatch

    # Output hash verification
    output_mismatch = []
    n_outputs = 0
    with open(ROOT / "outputs/provenance/ANALYSIS_OUTPUT_HASHES.csv", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        cols = reader.fieldnames
        for row in reader:
            n_outputs += 1
            rel = row.get("path") or row.get("file")
            hv = row.get("sha256") or row.get("hash")
            p = ROOT / rel
            if not p.exists():
                output_mismatch.append((rel, "MISSING"))
                continue
            if hv and sha256_file(p) != hv:
                output_mismatch.append((rel, "HASH_DIFFERS"))
    out["output_hash_columns"] = cols
    out["n_outputs_hashed"] = n_outputs
    out["output_hash_mismatches"] = output_mismatch

    print(json.dumps(out, indent=2)[:4000])
    with open("/tmp/sgi_independent_audit/00_hash_verification.json", "w") as fh:
        json.dump(out, fh, indent=2)


if __name__ == "__main__":
    main()
