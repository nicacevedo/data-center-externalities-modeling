#!/usr/bin/env python3
"""Split frozen task IDs across validated partitions and print sbatch commands.

Does not modify TASK_MANIFEST.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_common import MAN, atomic_write_json, utcnow  # noqa: E402

TIME = {
    "sched_mit_sloan_batch": "16:00:00",
    "sched_mit_sloan_batch_r8": "16:00:00",
    "ou_sloan_batch": "20:00:00",
    "mit_normal": "12:00:00",
}


def main():
    pf = json.loads((MAN / "PARTITION_PREFLIGHT.json").read_text())
    parts = [p for p in pf["validated_partitions"] if p in TIME]
    if not parts:
        raise SystemExit("no validated partitions")
    man = json.loads((MAN / "TASK_MANIFEST.json").read_text())
    ids = [t["task_id"] for t in man["tasks"]]
    # prefer idle-heavy partitions first if present
    prefer = ["ou_sloan_batch", "sched_mit_sloan_batch", "sched_mit_sloan_batch_r8", "mit_normal"]
    parts = [p for p in prefer if p in parts] or parts
    buckets = {p: [] for p in parts}
    for i, tid in enumerate(ids):
        buckets[parts[i % len(parts)]].append(tid)
    atomic_write_json(
        MAN / "TASK_SPLIT.json",
        {"timestamp_utc": utcnow(), "partitions": parts, **buckets},
    )
    print(json.dumps({p: len(buckets[p]) for p in parts}, indent=2))


if __name__ == "__main__":
    main()
