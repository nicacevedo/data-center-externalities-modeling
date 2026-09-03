#!/usr/bin/env python3
"""Promote v3 to its final freeze only after the clean-room gate passes."""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


FC3 = Path(__file__).resolve().parents[1]
REPO = FC3.parent
OUT = FC3 / "outputs"
FROZEN = "da7fd6f55e1aef5216ceabe80bfc3e31265f7927"
HASH_CSV = OUT / "provenance/FINAL_V3_FILE_HASHES.csv"
HASH_JSON = OUT / "provenance/FINAL_V3_FILE_HASHES.json"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def main() -> None:
    clean_path = OUT / "reproducibility/CLEANROOM_FINAL_STATUS.json"
    dependency_path = OUT / "provenance/V3_DEPENDENCY_MANIFEST.json"
    clean = json.loads(clean_path.read_text())
    dependencies = json.loads(dependency_path.read_text())
    if clean.get("CLEANROOM_FINAL_STATUS") != "PASS":
        raise SystemExit("freeze gate failed: CLEANROOM_FINAL_STATUS is not PASS")
    if clean.get("CLEAN_V2_REPRODUCIBILITY") != "PASS":
        raise SystemExit("freeze gate failed: CLEAN_V2_REPRODUCIBILITY is not PASS")
    if dependencies.get("status") != "PASS":
        raise SystemExit("freeze gate failed: V3 dependency audit is not PASS")

    claims_path = OUT / "FINAL_CLAIMS_LEDGER.json"
    claims = json.loads(claims_path.read_text())
    claims["CLEAN_V2_REPRODUCIBILITY"] = "PASS"
    claims["CLEANROOM_FINAL_STATUS"] = "PASS"
    claims["FOREST_CITY_V3_FINAL_FREEZE"] = True
    claims["STOP_MODEL_EXPANSION"] = True
    existing = {row["Claim"] for row in claims["claims"]}
    additions = [
        {"Claim": "CLEAN_V2_REPRODUCIBILITY", "Status": "PASS", "Evidence class": "REPRODUCIBILITY", "Notes": "clean da7fd6f checkout, generated ignored intermediate, committed v2 guards"},
        {"Claim": "CLEANROOM_FINAL_STATUS", "Status": "PASS", "Evidence class": "REPRODUCIBILITY", "Notes": "clean replay, v3 guards, and material-output comparison passed"},
    ]
    claims["claims"].extend(row for row in additions if row["Claim"] not in existing)
    claims_path.write_text(json.dumps(claims, indent=2, sort_keys=True) + "\n")

    ledger_md = OUT / "FINAL_CLAIMS_LEDGER.md"
    ledger_text = ledger_md.read_text()
    marker = "\n## Final reproducibility gate\n"
    if marker not in ledger_text:
        ledger_text += (
            marker
            + "\n- `CLEAN_V2_REPRODUCIBILITY = PASS`\n"
            + "- `CLEANROOM_FINAL_STATUS = PASS`\n"
            + "- `FOREST_CITY_V3_FINAL_FREEZE = TRUE`\n"
            + "- `STOP_MODEL_EXPANSION = TRUE`\n"
        )
        ledger_md.write_text(ledger_text)

    report_path = OUT / "FOREST_CITY_V3_REPORT.md"
    report = report_path.read_text()
    report_marker = "\n## Final reproducibility and freeze\n"
    if report_marker not in report:
        report += (
            report_marker
            + "\nThe clean checkout at the exact frozen dependency commit regenerated required intermediates, passed the committed v2 guards and v3 guards, and matched every material development output by exact hash or declared numerical tolerance.\n\n"
            + "`CLEAN_V2_REPRODUCIBILITY = PASS`  \n"
            + "`CLEANROOM_FINAL_STATUS = PASS`  \n"
            + "`FOREST_CITY_V3_FINAL_FREEZE = TRUE`  \n"
            + "`STOP_MODEL_EXPANSION = TRUE`\n"
        )
        report_path.write_text(report)

    main_head = git("rev-parse", "HEAD")
    origin_main = git("rev-parse", "origin/main")
    dependency_manifest_sha = sha(dependency_path)
    cleanroom_manifest_sha = sha(clean_path)
    freeze = {
        "FOREST_CITY_V3_FINAL_FREEZE": True,
        "STOP_MODEL_EXPANSION": True,
        "STOP": True,
        "MODEL_CALIBRATED": "NO",
        "QUANTITATIVE_PHYSICS_TRANSFER": "NOT_VALIDATED",
        "FACILITY_EFFECTIVE_DELTA_T": "UNIDENTIFIED",
        "CLEAN_V2_REPRODUCIBILITY": "PASS",
        "CLEANROOM_FINAL_STATUS": "PASS",
        "frozen_dependency_commit": FROZEN,
        "v2_dependency_access": f"GIT_BLOB_ONLY:{FROZEN}",
        "development_HEAD": main_head,
        "cached_origin_main": origin_main,
        "dependency_manifest_sha256": dependency_manifest_sha,
        "cleanroom_status_sha256": cleanroom_manifest_sha,
        "main_timestamp_set_sha256": "3456a8c519da1212310083b87dcc7f9fd2b0a834502284cc5c4a9af01e2cd65e",
        "finalized_utc": datetime.now(timezone.utc).isoformat(),
        "external_action": "Acquire a named-period air-side commissioning package (TAB/BMS CFM + SAT/RAT + OA/RA or mixed-air state + matched heat/load boundary), cooling-water meter package, and controller sequence/runtime evidence.",
    }
    (OUT / "FOREST_CITY_V3_FREEZE.json").write_text(json.dumps(freeze, indent=2, sort_keys=True) + "\n")

    excluded = {HASH_CSV.resolve(), HASH_JSON.resolve()}
    rows = []
    for path in sorted(p for p in FC3.rglob("*") if p.is_file()):
        if path.resolve() in excluded or "__pycache__" in path.parts:
            continue
        rows.append({"relative_path": str(path.relative_to(FC3)), "sha256": sha(path), "bytes": path.stat().st_size})
    HASH_CSV.parent.mkdir(parents=True, exist_ok=True)
    with HASH_CSV.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["relative_path", "sha256", "bytes"])
        writer.writeheader(); writer.writerows(rows)
    HASH_JSON.write_text(json.dumps({
        "scope": "all Forest City v3 files except this CSV/JSON manifest pair and __pycache__",
        "n_files": len(rows),
        "files": rows,
    }, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"FOREST_CITY_V3_FINAL_FREEZE": True, "n_hashed_files": len(rows)}, indent=2))


if __name__ == "__main__":
    main()
