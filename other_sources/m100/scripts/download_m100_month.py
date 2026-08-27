#!/usr/bin/env python3
"""Resume-capable wget download of one 2021 monthly tar into Pool raw staging."""

from __future__ import annotations

import argparse
import os
import subprocess
import time
from pathlib import Path

from m100_2021_common import (
    ARCHIVES_DIR,
    ZENODO,
    archive_path,
    hive_ym,
    save_status,
    zenodo_url,
)


def download_month(month: str) -> dict:
    ARCHIVES_DIR.mkdir(parents=True, exist_ok=True)
    dest = archive_path(month)
    meta = ZENODO[month]
    url = zenodo_url(month)
    official = int(meta["size"])
    if dest.exists() and dest.stat().st_size == official:
        save_status(month, archive_status="complete")
        return {"month": month, "skipped": True, "path": str(dest), "size": official}

    part = dest.with_suffix(dest.suffix + ".part")
    if dest.exists() and dest.stat().st_size != official:
        # resume into the existing file name
        target = dest
    else:
        target = part

    save_status(month, archive_status="incomplete/downloading")
    t0 = time.time()
    cmd = [
        "wget", "-c", "--tries=20", "--timeout=60", "--waitretry=5",
        "--progress=dot:giga",
        "-O", str(target),
        url,
    ]
    print(" ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)
    if target != dest:
        target.replace(dest)
    size = dest.stat().st_size
    ok = size == official
    save_status(
        month,
        archive_status="complete" if ok else "incomplete/downloading",
        failure=None if ok else f"size {size} != official {official}",
        runtime_s=round(time.time() - t0, 1),
    )
    if not ok:
        raise SystemExit(f"{month} size {size} != official {official}")
    return {"month": month, "path": str(dest), "size": size, "elapsed_s": round(time.time() - t0, 1)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--month", required=True)
    args = p.parse_args()
    print(download_month(args.month))


if __name__ == "__main__":
    main()
