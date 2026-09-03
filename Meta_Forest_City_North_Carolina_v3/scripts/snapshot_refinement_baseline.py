#!/usr/bin/env python3
"""One-time, pre-refinement snapshot of the committed Forest City v3 package."""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


FC3 = Path(__file__).resolve().parents[1]
REPO = FC3.parent
OUT = FC3 / "outputs" / "refinement_baseline"
SELF = Path(__file__).resolve()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=REPO, text=True, capture_output=True, check=check
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in sorted(FC3.rglob("*")):
        if not path.is_file() or OUT in path.parents or path.resolve() == SELF:
            continue
        rel = path.relative_to(REPO).as_posix()
        tracked = git("ls-files", "--error-unmatch", "--", rel, check=False).returncode == 0
        rows.append(
            {
                "relative_path": path.relative_to(FC3).as_posix(),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
                "tracked_at_HEAD": tracked,
            }
        )

    output_rows = [row for row in rows if row["relative_path"].startswith("outputs/")]
    with (OUT / "CURRENT_V3_OUTPUT_HASHES.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]))
        writer.writeheader()
        writer.writerows(output_rows)

    head = git("rev-parse", "HEAD").stdout.strip()
    origin = git("rev-parse", "origin/main").stdout.strip()
    manifest = {
        "snapshot_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "all files present under v3 before refinement; snapshot artifacts and this one-time snapshot script excluded",
        "HEAD": head,
        "origin_main_local_tracking_ref": origin,
        "v3_git_tree": git("rev-parse", "HEAD:Meta_Forest_City_North_Carolina_v3").stdout.strip(),
        "git_status_before": git("status", "--short").stdout,
        "origin_fetch": {
            "attempted": True,
            "success": False,
            "stderr": "git@ssh.github.com: Permission denied (publickey); remote-tracking ref could not be refreshed",
        },
        "n_files": len(rows),
        "n_output_files": len(output_rows),
        "files": rows,
    }
    (OUT / "CURRENT_V3_TREE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    shutil.copyfile(FC3 / "outputs" / "FOREST_CITY_V3_REPORT.md", OUT / "CURRENT_V3_REPORT_BEFORE.md")
    shutil.copyfile(FC3 / "outputs" / "FINAL_CLAIMS_LEDGER.md", OUT / "CURRENT_V3_CLAIMS_BEFORE.md")
    print(json.dumps({"n_files": len(rows), "n_output_files": len(output_rows), "HEAD": head}, indent=2))


if __name__ == "__main__":
    main()
