#!/usr/bin/env python3
"""Phase 0–1: freeze parent-repo state and hash acquired sources. WORK_ROOT writes only."""
from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import sys
from pathlib import Path

from common import (
    FRONTIER_XLSX,
    LBNL_PDF,
    PARENT_REPO,
    PY,
    UPSTREAM,
    UPSTREAM_COMMIT,
    WORK_ROOT,
    atomic_write_json,
    set_threads,
    sha256_file,
    utcnow,
)

PAPER_DIR = WORK_ROOT / "external" / "lei_masanet_2022"
FRONTIER_PAPER = WORK_ROOT / "external" / "frontier_paper" / "s41597-024-03913-w.pdf"


def _run(cmd, cwd=None, timeout=30):
    try:
        p = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "cmd": cmd,
            "returncode": p.returncode,
            "stdout": (p.stdout or "").strip(),
            "stderr": (p.stderr or "").strip(),
        }
    except Exception as e:
        return {"cmd": cmd, "returncode": None, "error": f"{type(e).__name__}: {e}"}


def _pkg_versions(modnames):
    out = {}
    for name in modnames:
        try:
            mod = __import__(name)
            out[name] = getattr(mod, "__version__", "imported")
        except Exception as e:
            out[name] = f"MISSING: {type(e).__name__}: {e}"
    return out


def artifact(path: Path, **extra):
    rec = {
        "path": str(path),
        "exists": path.exists(),
    }
    if path.exists() and path.is_file():
        rec["file_size_bytes"] = path.stat().st_size
        rec["sha256"] = sha256_file(path)
    rec.update(extra)
    return rec


def main():
    set_threads()
    ts = utcnow()
    git_head = _run(["git", "rev-parse", "HEAD"], cwd=str(PARENT_REPO))
    git_branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(PARENT_REPO))
    git_status = _run(["git", "status", "--short"], cwd=str(PARENT_REPO))
    sinfo = _run(["sinfo", "-s"], timeout=20)
    upstream_head = _run(["git", "rev-parse", "HEAD"], cwd=str(UPSTREAM))
    upstream_log = _run(
        ["git", "log", "-1", "--format=%H %ci %s"], cwd=str(UPSTREAM)
    )
    license_files = list(UPSTREAM.glob("LICENSE*")) + list(UPSTREAM.glob("COPYING*"))
    env_exe = sys.executable
    freeze = {
        "timestamp_utc": ts,
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "parent_repository_absolute_path": str(PARENT_REPO),
        "work_root": str(WORK_ROOT),
        "git_rev_parse_HEAD": git_head.get("stdout"),
        "git_branch": git_branch.get("stdout"),
        "git_status_short": git_status.get("stdout"),
        "git_status_note": (
            "Parent tree is not required to be clean. This freeze records state only. "
            "This run must not modify files outside WORK_ROOT."
        ),
        "python": {
            "executable": env_exe,
            "version": sys.version,
            "expected_masanet_lei": str(PY),
            "using_expected_env": os.path.realpath(env_exe) == os.path.realpath(str(PY))
            or Path(env_exe) == PY,
            "conda_env_name": "masanet_lei",
            "conda_env_prefix": str(PY.parent.parent),
            "packages": _pkg_versions(
                [
                    "numpy",
                    "pandas",
                    "sklearn",
                    "scipy",
                    "CoolProp",
                    "openpyxl",
                    "pyarrow",
                    "matplotlib",
                    "pytest",
                    "pypdf",
                ]
            ),
            "dc_externalities_note": (
                "dc_externalities lacks sklearn and CoolProp; one dedicated env masanet_lei "
                "was created (Python 3.9, sklearn 1.0.2) to load COP pickles trained on 0.22/0.23."
            ),
        },
        "sinfo_snapshot": sinfo.get("stdout"),
        "accessible_cpu_partitions_preference": [
            "sched_mit_sloan_batch",
            "sched_mit_sloan_batch_r8",
            "mit_normal",
            "mit_quicktest (smoke only)",
        ],
        "did_not_read_meta_2023_2024_water_outcomes": True,
        "confirmation": (
            "This run will not inspect or evaluate Meta Prineville 2023–2024 water outcomes, "
            "will not recalibrate the Prineville water model, and will not modify "
            "Meta_Prineville_Oregon_v3, other_sources/m100, or Data-center-PUE-prediction-tool."
        ),
        "upstream_nested_clone": {
            "path": str(UPSTREAM),
            "recorded_commit": UPSTREAM_COMMIT,
            "git_head": upstream_head.get("stdout"),
            "git_log_1": upstream_log.get("stdout"),
            "license_files_found": [str(p) for p in license_files],
            "license_declared": False,
            "handling": "Keep nested; do not copy source into project implementation.",
        },
    }
    atomic_write_json(WORK_ROOT / "manifests" / "BASELINE_FREEZE.json", freeze)

    sources = {
        "timestamp_utc": ts,
        "access_hostname": socket.gethostname(),
        "artifacts": [
            artifact(
                UPSTREAM / "simulation_funs_DC.py",
                canonical_title="Data-Center-Water-footprint public implementation",
                source_provider="GitHub nuoaleon/Data-Center-Water-footprint",
                doi_or_identity="https://github.com/nuoaleon/Data-Center-Water-footprint",
                version=UPSTREAM_COMMIT,
                git_commit=UPSTREAM_COMMIT,
                license="NOT DECLARED in repository (no LICENSE/COPYING file at freeze)",
                intended_role="Trusted nested reference implementation for Lei–Masanet 2022 PUE/WUE",
                independence="model_lineage",
            ),
            artifact(
                UPSTREAM / "demo.ipynb",
                canonical_title="Upstream demonstration notebook",
                source_provider="same GitHub repository",
                doi_or_identity="https://github.com/nuoaleon/Data-Center-Water-footprint",
                version=UPSTREAM_COMMIT,
                git_commit=UPSTREAM_COMMIT,
                license="NOT DECLARED",
                intended_role="Seed-unset reference evaluation of PUE_WUE_WE_Chiller_Colo",
                independence="model_lineage",
            ),
            artifact(
                UPSTREAM / "COP_2.pkl",
                canonical_title="Water-cooled chiller COP Gaussian-process model",
                source_provider="same GitHub repository",
                version=UPSTREAM_COMMIT,
                git_commit=UPSTREAM_COMMIT,
                license="NOT DECLARED",
                intended_role="COP_gp used by water-cooled archetypes",
                independence="model_lineage",
            ),
            artifact(
                UPSTREAM / "COP_AC.pkl",
                canonical_title="Air-cooled chiller COP Gaussian-process model",
                source_provider="same GitHub repository",
                version=UPSTREAM_COMMIT,
                git_commit=UPSTREAM_COMMIT,
                license="NOT DECLARED",
                intended_role="COP_air_gp",
                independence="model_lineage",
            ),
            artifact(
                UPSTREAM / "COP_DX.pkl",
                canonical_title="DX COP Gaussian-process model",
                source_provider="same GitHub repository",
                version=UPSTREAM_COMMIT,
                git_commit=UPSTREAM_COMMIT,
                license="NOT DECLARED",
                intended_role="COP_DX_gp",
                independence="model_lineage",
            ),
            artifact(
                UPSTREAM / "Simulation Results" / "UE.xlsx",
                canonical_title="Bundled climate-zone × case × quantile PUE/WUE table",
                source_provider="same GitHub repository",
                version=UPSTREAM_COMMIT,
                git_commit=UPSTREAM_COMMIT,
                license="NOT DECLARED",
                intended_role="Machine-readable bundled simulation output; not demo-vector comparable",
                independence="model_lineage",
            ),
            artifact(
                PAPER_DIR / "Climate-_and_Technology-Specific_PUE_and_WUE_Predi.pdf",
                canonical_title=(
                    "Climate- and technology-specific PUE and WUE estimations for U.S. data centers "
                    "using a hybrid statistical and thermodynamics-based approach (Lei and Masanet 2022)"
                ),
                source_provider="User-supplied PDF; Research Square preprint rs.3.rs-769999/v1",
                doi_or_identity="10.1016/j.resconrec.2022.106323 (published); preprint 10.21203/rs.3.rs-769999/v1",
                version="Research Square manuscript (PUEWUEArchetypes.docx lineage); not Elsevier typeset",
                license="CC BY 4.0 (preprint header)",
                intended_role="Primary paper for PUE/WUE definitions, Eq. (1) water terms, Table 3 ranges",
                independence="model_lineage",
                note=(
                    "Published title uses 'estimations' / 'hybrid statistical and thermodynamics-based'; "
                    "this PDF title uses 'Predictions' / 'Physics-Based'. Equations and WUE definition are usable."
                ),
            ),
            artifact(
                PAPER_DIR / "lei2020.pdf",
                canonical_title=(
                    "Statistical analysis for predicting location-specific data center PUE and its "
                    "improvement potential (Lei and Masanet, Energy 201, 117556, 2020)"
                ),
                source_provider="User-supplied PDF",
                doi_or_identity="10.1016/j.energy.2020.117556",
                version="typeset Energy article",
                license="Elsevier; not copied into implementation",
                intended_role="Prior PUE-only physics model that the 2022 WUE paper extends",
                independence="model_lineage",
            ),
            artifact(
                PAPER_DIR / "Statistical-analysis-for-predicting-location-specific-data-center-PUE.pdf",
                canonical_title="Byte-identical duplicate of lei2020.pdf",
                source_provider="User-supplied PDF",
                doi_or_identity="10.1016/j.energy.2020.117556",
                version="duplicate file",
                license="Elsevier",
                intended_role="Duplicate of 2020 PUE paper; hashed to confirm identity",
                independence="model_lineage",
            ),
            artifact(
                PAPER_DIR / "qt1vx545q7.pdf",
                canonical_title=(
                    "The water use of data center workloads: A review and assessment of key determinants "
                    "(Lei, Lu, Shehabi, and Masanet, Resources, Conservation and Recycling 219, 108310, 2025)"
                ),
                source_provider="User-supplied eScholarship PDF",
                doi_or_identity="10.1016/j.resconrec.2025.108310; eScholarship qt1vx545q7",
                version="LBNL eScholarship deposit / RCR 219 (2025)",
                license="CC BY 4.0 (eScholarship header)",
                intended_role=(
                    "Later same-lineage review: WUE-site vs WUE-source language; consumption vs withdrawal caveat. "
                    "NOT the 2022 PUE/WUE implementation paper."
                ),
                independence="model_lineage",
            ),
            artifact(
                PAPER_DIR / "ssrn-5131144.pdf",
                canonical_title=(
                    "Energy and Water Dynamics in Data Center Cooling: Insights from a Modeling Study "
                    "in Hot-Arid Climates (Karimi et al., SSRN 5131144, Feb 2025 preprint)"
                ),
                source_provider="User-supplied SSRN preprint",
                doi_or_identity="https://ssrn.com/abstract=5131144",
                version="February 2025 preprint, not peer reviewed",
                license="SSRN preprint; not copied into implementation",
                intended_role=(
                    "Independent (University of Arizona / SRP) qualitative triangulation of energy–water "
                    "cooling tradeoffs in a hot-arid climate. Not used to retune Lei–Masanet."
                ),
                independence="independent_contextual",
            ),
            artifact(
                LBNL_PDF,
                canonical_title="2024 United States Data Center Energy Usage Report (Shehabi et al.)",
                source_provider="LBNL / user-supplied or downloaded PDF",
                doi_or_identity="10.71468/P1WC7Q; LBNL-2001637",
                version="December 2024",
                license="U.S. Government-sponsored report (disclaimer in PDF)",
                intended_role="Cooling-system taxonomy and qualitative PUE/WUE envelopes; shared Lei authorship lineage",
                independence="model_lineage_not_statistically_independent",
            ),
            artifact(
                FRONTIER_PAPER,
                canonical_title="Energy dataset of Frontier supercomputer for waste heat recovery (Sun et al., Scientific Data 11, 1077, 2024)",
                source_provider="Nature Scientific Data PDF",
                doi_or_identity="10.1038/s41597-024-03913-w",
                version="2024 article",
                license="Scientific Data; dataset separately on Figshare",
                intended_role="Documented coolant properties, PUE wording, and column intent for Frontier",
                independence="independent_validation",
            ),
            artifact(
                FRONTIER_XLSX,
                canonical_title="Frontier HPC & Facility Data, Figshare version 4",
                source_provider="Figshare",
                doi_or_identity="10.6084/m9.figshare.24391240.v4",
                version="v4 only",
                license="Not declared inside the xlsx; keep as external dataset",
                intended_role="Independent measured facility for thermal/power accounting structure",
                independence="independent_validation",
                expected_size_note="About 19 MB; sheets include Readme and Frontier2023",
            ),
        ],
    }
    # duplicate check for 2020 PDFs
    p_a = PAPER_DIR / "lei2020.pdf"
    p_b = PAPER_DIR / "Statistical-analysis-for-predicting-location-specific-data-center-PUE.pdf"
    if p_a.exists() and p_b.exists():
        sources["lei2020_duplicate_check"] = {
            "same_sha256": sha256_file(p_a) == sha256_file(p_b),
            "sha256": sha256_file(p_a),
        }
    atomic_write_json(WORK_ROOT / "manifests" / "SOURCES.json", sources)
    print(
        json.dumps(
            {
                "freeze": str(WORK_ROOT / "manifests" / "BASELINE_FREEZE.json"),
                "sources": str(WORK_ROOT / "manifests" / "SOURCES.json"),
                "n_artifacts": len(sources["artifacts"]),
                "head": freeze["git_rev_parse_HEAD"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
