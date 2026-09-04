#!/usr/bin/env python3
"""Perform the single permitted repository-local WRMS delivery check."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
BASELINE = "131657d62712f76acd12dcff461524937ca9fe44"
OUTPUT = ROOT / "outputs/provenance/GW1B_V2_WRMS_AVAILABILITY_CHECK.json"
DATA_SUFFIXES = {".csv", ".tsv", ".xlsx", ".xls", ".parquet", ".zip", ".7z", ".gpkg", ".shp", ".gdb", ".mdb", ".accdb"}
KEYWORDS = {"wrms", "pumping", "production", "injection", "managed_recharge", "extraction"}


if OUTPUT.exists():
    raise SystemExit("V2 WRMS availability check already exists; refusing to poll twice")

all_files = []
candidates = []
for path in sorted(p for p in REPO.rglob("*") if p.is_file()):
    relative = path.relative_to(REPO)
    if ".git" in relative.parts or "__pycache__" in relative.parts:
        continue
    all_files.append(relative.as_posix())
    lowered = relative.as_posix().lower()
    looks_like_data = path.suffix.lower() in DATA_SUFFIXES or any(part.lower().endswith(".gdb") for part in relative.parts)
    named_like_delivery = any(keyword in lowered for keyword in KEYWORDS) or "delivery" in lowered
    if not (looks_like_data and named_like_delivery):
        continue
    tracked_at_baseline = subprocess.run(
        ["git", "cat-file", "-e", f"{BASELINE}:{relative.as_posix()}"],
        cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).returncode == 0
    candidates.append({
        "path": relative.as_posix(),
        "bytes": path.stat().st_size,
        "tracked_at_scientific_baseline": tracked_at_baseline,
        "new_delivery_candidate": not tracked_at_baseline,
    })

new_candidates = [row for row in candidates if row["new_delivery_candidate"]]
result = {
    "checked_once_at_utc": datetime.now(timezone.utc).isoformat(),
    "scientific_baseline_commit": BASELINE,
    "scope": str(REPO),
    "method": "one repository-local filename/type scan; no file contents, email, or external accounts inspected",
    "files_seen_excluding_git_and_pycache": len(all_files),
    "data_filename_candidates": candidates,
    "new_delivery_candidates": new_candidates,
    "WRMS_delivery_present": bool(new_candidates),
    "GW1B_DATA_STATUS": "DELIVERY_CANDIDATE_REQUIRES_RAW_PRESERVATION_AND_AUDIT" if new_candidates else "WAITING_FOR_WRMS",
    "synthetic_pumping_created": False,
    "aggregate_public_pumping_substituted": False,
    "inferred_pumping_from_heads": False,
    "MODFLOW_forcing_substituted": False,
}
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(result, indent=2, sort_keys=True))

