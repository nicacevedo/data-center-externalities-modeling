#!/usr/bin/env python3
"""Hash and verify the frozen GW-1B waiting skeleton."""

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {
    "outputs/provenance/GW1B_OUTPUT_HASHES.csv",
    "outputs/provenance/GW1B_OUTPUT_HASHES.json",
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


status = json.loads((ROOT / "outputs/FINAL_GW1B_STATUS.json").read_text())
if status["GW1B_DATA_STATUS"] != "WAITING_FOR_WRMS" or status["models_fit_in_GW1B"]:
    raise SystemExit("GW-1B waiting-state invariant failed")

rows = []
for path in sorted(p for p in ROOT.rglob("*") if p.is_file()):
    rel = path.relative_to(ROOT).as_posix()
    if rel in EXCLUDED or "__pycache__" in rel:
        continue
    rows.append({"path": rel, "bytes": path.stat().st_size, "sha256": digest(path)})

csv_path = ROOT / "outputs/provenance/GW1B_OUTPUT_HASHES.csv"
with csv_path.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=["path", "bytes", "sha256"])
    writer.writeheader()
    writer.writerows(rows)
(ROOT / "outputs/provenance/GW1B_OUTPUT_HASHES.json").write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n")
print(f"GW1B_DATA_STATUS={status['GW1B_DATA_STATUS']} files_hashed={len(rows)}")
