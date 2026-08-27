#!/usr/bin/env python3
"""Final storage audit. Deletes remaining certified tars only after re-checking files."""

from __future__ import annotations

from pathlib import Path

from m100_2021_common import (
    ARCHIVES_DIR,
    EXPECTED_MONTHS,
    POOL_M100,
    PROCESSED_DIR,
    RESULTS_DIR,
    SCRATCH_M100,
    archive_path,
    load_status,
)
from cleanup_m100_month import cleanup_month


def du(path: Path) -> str:
    import subprocess
    if not path.exists():
        return "missing"
    out = subprocess.run(["du", "-sh", str(path)], capture_output=True, text=True)
    return out.stdout.strip() or "0"


def main():
    lines = []
    lines.append("M100 2021 storage final report")
    lines.append(f"POOL raw: {du(ARCHIVES_DIR)}")
    lines.append(f"POOL processed: {du(PROCESSED_DIR)}")
    lines.append(f"SCRATCH: {du(SCRATCH_M100)}")
    for month in EXPECTED_MONTHS:
        st = load_status(month)
        tar = archive_path(month)
        lines.append(
            f"{month} cert={st.get('certification')} tar_exists={tar.exists()} "
            f"delete_allowed={st.get('raw_deletion_allowed')} archive_status={st.get('archive_status')}"
        )
        if st.get("certification") == "PASS" and st.get("raw_deletion_allowed") and tar.exists():
            cleanup_month(month)
    # stale scratch
    for p in (SCRATCH_M100 / "tmp").glob("*"):
        if p.is_dir():
            import shutil
            shutil.rmtree(p, ignore_errors=True)
    lines.append(f"POOL raw after: {du(ARCHIVES_DIR)}")
    lines.append(f"POOL processed after: {du(PROCESSED_DIR)}")
    out = RESULTS_DIR / "storage_final_report.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    print(out.read_text())


if __name__ == "__main__":
    main()
