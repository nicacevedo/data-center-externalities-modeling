#!/usr/bin/env python3
"""Aggregate partition preflight JSON files. Does not mutate science."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_common import MAN, atomic_write_json, utcnow  # noqa: E402

CANDIDATES = [
    "sched_mit_sloan_batch",
    "sched_mit_sloan_batch_r8",
    "ou_sloan_batch",
    "mit_normal",
    "local_masanet_lei",
    "local_dc_externalities",
]


def main():
    recs = []
    for p in sorted(MAN.glob("preflight_*.json")):
        recs.append(json.loads(p.read_text()))
    ref = None
    for r in recs:
        if r.get("status") == "PASS" and r.get("tag") in ("sched_mit_sloan_batch", "local_masanet_lei"):
            ref = r
            break
    if ref is None:
        ref = next((r for r in recs if r.get("status") == "PASS"), None)
    validated = []
    rejected = []
    for r in recs:
        if r.get("status") != "PASS":
            rejected.append({"tag": r.get("tag"), "reason": r.get("error"), "partition": r.get("partition")})
            continue
        if ref and abs(r["pue"] - ref["pue"]) < 1e-10 and abs(r["wue"] - ref["wue"]) < 1e-10:
            if r.get("versions", {}).get("scipy") != ref.get("versions", {}).get("scipy"):
                rejected.append({"tag": r.get("tag"), "reason": "scipy version mismatch", "scipy": r["versions"]["scipy"]})
                continue
            validated.append(r.get("tag") or r.get("partition"))
        elif ref:
            rejected.append(
                {
                    "tag": r.get("tag"),
                    "reason": "numerical mismatch vs reference",
                    "pue": r.get("pue"),
                    "ref_pue": ref.get("pue"),
                }
            )
        else:
            validated.append(r.get("tag"))
    # partitions only (not local tags)
    parts = [v for v in validated if v in CANDIDATES and not str(v).startswith("local_")]
    out = {
        "timestamp_utc": utcnow(),
        "reference": None if ref is None else {k: ref.get(k) for k in ("tag", "pue", "wue", "versions", "hostname")},
        "records": recs,
        "validated_partitions": parts,
        "rejected": rejected,
        "dc_externalities_note": (
            "User requested dc_externalities. That env cannot import CoolProp/working sklearn for this model. "
            "Science uses masanet_lei + PYTHONNOUSERSITE=1."
        ),
        "tight_float_tolerance": 1e-10,
    }
    atomic_write_json(MAN / "PARTITION_PREFLIGHT.json", out)
    print(json.dumps({"validated_partitions": parts, "rejected": rejected}, indent=2, default=str))
    if not parts and not any(r.get("status") == "PASS" for r in recs):
        sys.exit(2)


if __name__ == "__main__":
    main()
