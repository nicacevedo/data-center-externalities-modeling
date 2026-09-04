#!/usr/bin/env python3
"""Freeze the additive GW-1B v2 waiting/readiness artifacts."""

from __future__ import annotations

import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.gw1b_v2 import (  # noqa: E402
    BASELINE_COMMIT,
    CONFIG,
    GW1C_ROOT,
    MODULE_ROOT,
    MODEL_FEATURES,
    PLACEBO_REPLICATES,
    PROVENANCE,
    READINESS,
    REPO_ROOT,
    SPATIAL_LENGTHS_KM,
    V2_OUTPUTS,
    create_dependency_manifest,
    run_git,
    sha256_file,
    validate_nested_hierarchy,
    verify_frozen_parents,
    verify_previous_protocol,
    write_json,
)


def markdown_table(frame: pd.DataFrame) -> str:
    headers = [str(x) for x in frame.columns]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in frame.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(str(x) for x in row) + " |")
    return "\n".join(lines)


def write_preflight(parent_integrity: dict[str, object]) -> None:
    path = PROVENANCE / "GW1B_V2_REPOSITORY_PREFLIGHT.json"
    if path.exists():
        return
    submodule = run_git(["submodule", "status"], check=False)
    write_json(path, {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(REPO_ROOT),
        "branch": run_git(["branch", "--show-current"]).stdout.strip(),
        "HEAD": run_git(["rev-parse", "HEAD"]).stdout.strip(),
        "scientific_baseline_commit": BASELINE_COMMIT,
        "HEAD_matches_baseline": run_git(["rev-parse", "HEAD"]).stdout.strip() == BASELINE_COMMIT,
        "task_start_git_status_short": [" m Data-center-PUE-prediction-tool"],
        "pre_existing_unrelated_dirty_paths": ["Data-center-PUE-prediction-tool"],
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "submodule_status_exit_code": submodule.returncode,
        "submodule_status_stdout": submodule.stdout.splitlines(),
        "submodule_status_stderr": submodule.stderr.strip(),
        "parent_summary": {
            key: {k: v for k, v in value.items() if k != "files"}
            for key, value in parent_integrity["parents"].items()
        },
    })


def protocol_freeze(scan: dict[str, object]) -> dict[str, object]:
    paths = [
        CONFIG / "GW1B_PROTOCOL_AMENDMENT_20260904_v2.yaml",
        MODULE_ROOT / "outputs/protocol/GW1B_PROTOCOL_AMENDMENT_20260904_v2.md",
        CONFIG / "WRMS_INGESTION_CONTRACT_v2.yaml",
    ]
    scan_time = pd.Timestamp(scan["checked_once_at_utc"])
    files = []
    for path in paths:
        modified = pd.Timestamp(path.stat().st_mtime, unit="s", tz="UTC")
        files.append({
            "path": path.relative_to(MODULE_ROOT).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "filesystem_mtime_utc": modified.isoformat(),
            "predates_WRMS_scan": bool(modified < scan_time),
        })
    value = {
        "status": "FROZEN",
        "protocol_id": "OCWD_GW1B_NESTED_MANAGED_FORCING_V2_20260904",
        "scientific_baseline_commit": BASELINE_COMMIT,
        "WRMS_scan_time_utc": scan["checked_once_at_utc"],
        "all_protocol_files_predate_WRMS_scan": all(row["predates_WRMS_scan"] for row in files),
        "files": files,
        "previous_protocol_preserved": verify_previous_protocol(),
        "nested_hierarchy": validate_nested_hierarchy(),
        "scientific_outcomes_inspected_before_freeze": False,
    }
    if not value["all_protocol_files_predate_WRMS_scan"]:
        raise RuntimeError("Protocol files do not predate the WRMS scan")
    write_json(PROVENANCE / "GW1B_V2_PROTOCOL_FREEZE.json", value)
    return value


def pre_wrms_support() -> tuple[dict[str, object], pd.DataFrame]:
    transitions = pd.read_parquet(GW1C_ROOT / "data/derived/GW1C_TRANSITIONS.parquet")
    eligible = transitions.loc[
        transitions["gap_le_120_days"].astype(bool)
        & transitions["hydrologic_feature_complete"].astype(bool)
        & transitions["climate_feature_complete"].astype(bool)
        & transitions["transition_independence_class"].eq("OCWD_ORIGIN_REPUBLISHED_BY_DWR")
    ].copy()
    counts = eligible.groupby(["temporal_split", "spatial_fold"]).size().rename("pre_WRMS_BC_eligible_transitions").reset_index()
    counts.to_csv(READINESS / "S_STAR_PRE_WRMS_BC_SUPPORT_BY_SPLIT_FOLD.csv", index=False)
    value = {
        "S_star_status": "PENDING_WRMS_NOT_CONSTRUCTIBLE",
        "original_GW1C_transition_count": len(transitions),
        "pre_WRMS_BC_eligible_transition_count": len(eligible),
        "pre_WRMS_BC_eligible_wells": eligible["site_code"].nunique(),
        "pre_WRMS_BC_counts_by_split": eligible.groupby("temporal_split").size().to_dict(),
        "pre_WRMS_BC_counts_by_split_and_fold_path": "outputs/readiness/S_STAR_PRE_WRMS_BC_SUPPORT_BY_SPLIT_FOLD.csv",
        "retained_S_star_transition_count": None,
        "retained_S_star_wells": None,
        "S_star_retention_percentage": None,
        "reason": "WRMS pumping/recharge/injection, identity, and spatial features through B6 are absent; missing forcing cannot be interpreted as zero.",
        "frozen_rule": "one common S* for BC/B4/B5/B6 requiring every feature through all B6 scale candidates",
        "period_or_fold_changed": False,
    }
    write_json(READINESS / "S_STAR_SUPPORT_STATUS.json", value)
    return value, counts


def write_readiness() -> dict[str, object]:
    value = {
        "WRMS_INGESTION_READY": "YES",
        "contract": "config/WRMS_INGESTION_CONTRACT_v2.yaml",
        "accepted_tables": ["well_master", "monthly_pumping", "managed_recharge", "injection", "id_crosswalk"],
        "supported_requirements": [
            "well IDs/names and authoritative projected coordinates",
            "individual-well monthly pumping",
            "managed recharge and injection",
            "active dates",
            "screen/perforation and authoritative aquifer/model-layer fields",
            "measurement/evidence classes",
            "QA and revision flags",
            "explicit units",
        ],
        "QA_guards": [
            "unit conversion", "duplicate ID-month", "missing ID", "coordinate conflict",
            "ambiguous crosswalk exclusion", "negative volume", "activity-date conflict",
            "measurement-class preservation", "missing month not zero",
            "monthly-total conservation",
        ],
        "transition_allocation": "proportional calendar-day overlap; DERIVED_FROM_MONTHLY_VOLUME",
        "spatial_exposure_lengths_km": list(SPATIAL_LENGTHS_KM),
        "placebo_replicates_each": PLACEBO_REPLICATES,
        "artificial_data_scope": "tests only",
        "scientific_synthetic_data": False,
        "B4_B5_B6_fitted": False,
        "B7_code_executed": False,
    }
    write_json(READINESS / "WRMS_INGESTION_READINESS.json", value)
    return value


def write_report(status: dict[str, object], counts: pd.DataFrame) -> None:
    report = f"""# Final OCWD GW-1B v2 nested managed-forcing readiness report

## A. Repository state

- Repository: `{REPO_ROOT}`
- Branch / HEAD: `{status['repository']['branch']}` / `{status['repository']['HEAD']}`
- Scientific baseline: `{BASELINE_COMMIT}`
- Task-start dirty state: ` m Data-center-PUE-prediction-tool` only.
- Python: `{status['repository']['python_executable']}` ({status['repository']['python_version']}).
- Git submodule enumeration remains unavailable because `.gitmodules` has no mapping for the existing PUE path; it was not modified.

## B. Parent and prior-protocol integrity

All material artifacts in the feasibility, GW-1A, and GW-1C parents match their exact baseline blobs or their committed package manifests. Start/end tree hashes are identical. The five previously existing GW-1B protocol/report artifacts also retain their recorded baseline SHA-256 values. No reset, clean, merge, rebase, commit, or push occurred.

## C-D. Additive v2 correction and exact hierarchy

The earlier preregistration remains untouched. `GW1B_PROTOCOL_AMENDMENT_20260904_v2.yaml` and its Markdown counterpart add the correction:

```
BC = frozen GW-1C B1C
B4 = BC + Phi(total managed recharge) + Phi(total injection)
B5 = B4 + Phi(total pumping)
B6 = B5 + Phi(spatial pumping) + Phi(spatial managed recharge) + Phi(spatial injection)
```

Therefore `BC ⊂ B4 ⊂ B5 ⊂ B6`; B6 retains every B5 total feature. Primary contrasts are B5−B4 for pumping quantity and B6−B5 for spatial location. The versioned protocol and ingestion contract predate the one WRMS scan; no pumping-response outcomes were inspected.

## E. Common support

One immutable `S*` must be used by BC/B4/B5/B6. It requires every BC, basin-total, identity, coordinate, and spatial feature through all 2/5/10 km B6 candidates. Model-specific samples and period/fold reselection are prohibited.

- Original GW-1C transitions: **{status['support']['original_GW1C_transition_count']}**.
- Pre-WRMS BC-eligible: **{status['support']['pre_WRMS_BC_eligible_transition_count']} transitions / {status['support']['pre_WRMS_BC_eligible_wells']} wells**.
- `S*`: **PENDING / not constructible without WRMS**. Retained rows, wells, retention percentage, and final split/fold counts are not identified; missing forcing is not zero.

Pre-WRMS BC support by split/fold (context only, not `S*`):

{markdown_table(counts)}

## F. Monthly-forcing arithmetic

For monthly `Q_jm`, interval exposure is `sum_m Q_jm × overlap_days((t0,t1],m) / days_in_month(m)`. Pre-30 and pre-90 use identical proportional overlap. Source measurement classes remain separate and every transition feature is `DERIVED_FROM_MONTHLY_VOLUME`, never daily measured. Explicit zero rows are required for active months; missing months are not zero. Full-month conservation is guarded at 1e-12 acre-feet. The month-compatible sensitivity requires both origin and target dates to be calendar month-end.

## G. Spatial exposure

`w_ij(l)=exp(-d_ij/l)` and `E_i,k=sum_j w_ij Q_jk`, using authoritative projected coordinates. Only 2, 5, and 10 km are eligible; one common scale is selected on VALIDATION and shared across the primary spatial family. TEST never selects. Same-layer exposure is sensitivity-only with authoritative layer metadata; layers are not guessed.

## H. Placebos

- Temporal pumping: 100 fixed replicates, permuting across years within production well, calendar month, and TRAIN/VALIDATION/TEST partition. Values never cross splits.
- Spatial: 100 fixed replicates, run only within authoritative aquifer/layer or another defensible stratum.

Each placebo uses the real model's validation procedure; TEST remains untouched for selection.

## I-J. Ingestion readiness and WRMS availability

`WRMS_INGESTION_READY = YES`. The contract accepts a manifest-controlled CSV/Parquet/Excel delivery and guards units, required IDs, duplicate months, coordinate/activity conflicts, negative volumes, evidence classes, crosswalk status, QA/revisions, and allocation conservation.

The single path/type scan initially surfaced four untracked filename matches. Path-only adjudication identified two as Prineville artifacts and two as M100 artifacts. No candidate is OCWD/WRMS; no second scan or content inspection occurred. Thus `GW1B_DATA_STATUS = WAITING_FOR_WRMS`.

## K-L. WRMS gates and S* support

WRMS QA, G3/G4/G5/G7/G10 re-evaluation, and final `S*` counts are `PENDING_WRMS`. This is not a failed empirical result. Aggregate public pumping, synthetic pumping, inferred pumping, and MODFLOW forcing were not substituted.

## M-R. Managed-forcing results and classifications

- B4 managed recharge/injection: `NOT_RUN_WAITING_FOR_WRMS`
- B5 pumping quantity: `NOT_RUN_WAITING_FOR_WRMS`
- Temporal placebo: `NOT_RUN_WAITING_FOR_WRMS`
- B6 spatial forcing: `NOT_RUN_WAITING_FOR_WRMS`
- Spatial placebo: `NOT_RUN_WAITING_FOR_WRMS`
- `PUMPING_PREDICTIVE_VALUE = UNRESOLVED`
- `SPATIAL_FORCING_VALUE = UNRESOLVED`

No scientific figure was created because no WRMS experiment ran.

## S. Network decision

`NETWORK_MODEL_JUSTIFICATION = UNRESOLVED`. B7, a GNN, and an A matrix were not fit. Tracer and MBI evidence remains completely untouched. An earned decision requires future B5/B6 and placebo evidence under this frozen protocol.

## T. Tests, replay, and hashes

The readiness guards cover frozen parents and prior protocol, strict nesting, exact climate/Prado state, ingestion schema, units, duplicate/missing/negative/conflicting records, evidence classes, monthly conservation, `S*`, split-preserving placebos, no substitutions, and no B7 execution. Canonical output hashes and deterministic replay status are under `outputs/provenance/`.

## U. Exact next experiment

On WRMS receipt: preserve and hash raw files before scientific inspection; validate schema, units, QA/revisions, measurement classes, coordinates, active dates, crosswalks, screens/layers, and completeness; re-evaluate G3/G4/G5/G7/G10; construct one `S*`; then execute B4→B5→B6 plus frozen placebos. Stop before B7. Recommend the separate B7 + reserved tracer/MBI experiment only if `NETWORK_MODEL_JUSTIFICATION = EARNED`.
"""
    (V2_OUTPUTS / "FINAL_GW1B_V2_REPORT.md").write_text(report, encoding="utf-8")


def write_hash_manifest() -> pd.DataFrame:
    excluded = {
        "outputs/provenance/GW1B_V2_OUTPUT_HASHES.csv",
        "outputs/provenance/GW1B_V2_OUTPUT_HASHES.json",
        "outputs/provenance/GW1B_V2_DETERMINISTIC_REPLAY_STATUS.json",
    }
    rows = []
    for path in sorted(p for p in MODULE_ROOT.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        relative = path.relative_to(MODULE_ROOT).as_posix()
        if relative in excluded:
            continue
        rows.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    frame = pd.DataFrame(rows)
    frame.to_csv(PROVENANCE / "GW1B_V2_OUTPUT_HASHES.csv", index=False)
    (PROVENANCE / "GW1B_V2_OUTPUT_HASHES.json").write_text(frame.to_json(orient="records", indent=2) + "\n", encoding="utf-8")
    return frame


def freeze() -> dict[str, object]:
    parent_start = verify_frozen_parents()
    write_json(PROVENANCE / "GW1B_V2_FROZEN_PARENT_INTEGRITY_START.json", parent_start)
    write_preflight(parent_start)
    dependencies = create_dependency_manifest()
    scan = json.loads((PROVENANCE / "GW1B_V2_WRMS_AVAILABILITY_CHECK.json").read_text())
    disposition = json.loads((PROVENANCE / "GW1B_V2_WRMS_CANDIDATE_DISPOSITION.json").read_text())
    protocol = protocol_freeze(scan)
    readiness = write_readiness()
    support, counts = pre_wrms_support()
    preflight = json.loads((PROVENANCE / "GW1B_V2_REPOSITORY_PREFLIGHT.json").read_text())
    status = {
        "GW1B_PROTOCOL_V2": "FROZEN",
        "WRMS_INGESTION_READY": "YES",
        "GW1B_DATA_STATUS": "WAITING_FOR_WRMS",
        "GW1B_DATA_GATE": "PENDING_WRMS",
        "scientific_baseline_commit": BASELINE_COMMIT,
        "repository": {
            "repo_root": str(REPO_ROOT), "branch": preflight["branch"], "HEAD": preflight["HEAD"],
            "python_executable": preflight["python_executable"], "python_version": preflight["python_version"],
        },
        "parents": {"status": "PASS", "material_dependencies": len(dependencies)},
        "previous_protocol_preserved": protocol["previous_protocol_preserved"],
        "protocol": {
            "id": protocol["protocol_id"], "status": protocol["status"],
            "all_protocol_files_predate_WRMS_scan": protocol["all_protocol_files_predate_WRMS_scan"],
            "hierarchy": "BC_subset_B4_subset_B5_subset_B6",
            "primary_contrasts": {"pumping_quantity": "B5_minus_B4", "spatial_location": "B6_minus_B5"},
            "common_support": "one_S_star_for_BC_B4_B5_B6",
        },
        "support": support,
        "WRMS_check": {
            "raw_scan_candidate_count": len(scan["new_delivery_candidates"]),
            "false_positive_count": len(disposition["dispositions"]),
            "unresolved_OCWD_WRMS_candidates": disposition["unresolved_OCWD_WRMS_candidates"],
            "second_scan_performed": False,
        },
        "scientific_substitutions": {
            "synthetic_pumping": False, "aggregate_public_pumping": False,
            "pumping_inferred_from_heads": False, "MODFLOW_forcing": False,
        },
        "models_fit": [],
        "results": {
            "MANAGED_RECHARGE_VALUE": "NOT_RUN_WAITING_FOR_WRMS",
            "PUMPING_PREDICTIVE_VALUE": "UNRESOLVED",
            "TEMPORAL_PLACEBO": "NOT_RUN_WAITING_FOR_WRMS",
            "SPATIAL_FORCING_VALUE": "UNRESOLVED",
            "SPATIAL_PLACEBO": "NOT_RUN_WAITING_FOR_WRMS",
        },
        "NETWORK_MODEL_JUSTIFICATION": "UNRESOLVED",
        "B7_executed": False,
        "reserved_validation": "UNTOUCHED",
        "figures_created": [],
        "next_action": "Preserve/hash WRMS delivery, run frozen ingestion QA/gates, build one S*, execute B4-B6/placebos, and stop before B7.",
    }
    write_json(V2_OUTPUTS / "FINAL_GW1B_V2_STATUS.json", status)
    write_report(status, counts)
    parent_end = verify_frozen_parents()
    for label in parent_start["parents"]:
        if parent_start["parents"][label]["current_tree_sha256"] != parent_end["parents"][label]["current_tree_sha256"]:
            raise RuntimeError(f"Frozen parent changed during freeze: {label}")
    parent_end["matches_start_snapshot"] = True
    write_json(PROVENANCE / "GW1B_V2_FROZEN_PARENT_INTEGRITY_END.json", parent_end)
    write_hash_manifest()
    return status


if __name__ == "__main__":
    result = freeze()
    for key in ["GW1B_PROTOCOL_V2", "WRMS_INGESTION_READY", "GW1B_DATA_STATUS", "NETWORK_MODEL_JUSTIFICATION"]:
        print(f"{key}={result[key]}")

