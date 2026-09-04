#!/usr/bin/env python3
"""Run the deterministic Andhra Pradesh planning preflight build."""

from pathlib import Path
import sys


MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE / "src"))

from build_preflight import module_hash_manifest, run_build  # noqa: E402


if __name__ == "__main__":
    repository = MODULE.parents[1]
    run_build(repository)
    module_hash_manifest(MODULE)
