#!/usr/bin/env python3
"""Catalog 2021 archives using official Zenodo sizes. Optional tar inventory."""

from __future__ import annotations

import argparse
import os
import time
import tarfile
from pathlib import Path

import pandas as pd

from m100_2021_common import (
    ARCHIVES_DIR,
    CATALOG_DIR,
    EXPECTED_MONTHS,
    STALE_SECONDS,
    WATER_NAME_RE,
    ZENODO,
    archive_path,
    hive_ym,
    metric_from_member,
    plugin_from_member,
    save_status,
    zenodo_url,
)


def _openers(path: Path) -> list[int]:
    pids = []
    try:
        import subprocess
        out = subprocess.run(
            ["lsof", "-t", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        pids = [int(x) for x in out.stdout.split() if x.strip().isdigit()]
    except Exception:
        pass
    return pids


def catalog_archives() -> pd.DataFrame:
    rows = []
    now = time.time()
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    for month in EXPECTED_MONTHS:
        tar_path = archive_path(month)
        meta = ZENODO[month]
        row = {
            "month": month,
            "archive_path": str(tar_path),
            "exists": tar_path.exists(),
            "size_bytes": None,
            "official_size_bytes": meta["size"],
            "official_md5": meta["md5"],
            "zenodo_record": meta["record"],
            "zenodo_doi": meta["doi"],
            "download_url": zenodo_url(month),
            "mtime_unix": None,
            "age_s": None,
            "open_pids": "",
            "tar_tf_ok": None,
            "size_matches_official": None,
            "status": "missing",
            "note": "",
        }
        if not tar_path.exists():
            rows.append(row)
            save_status(month, archive_status="missing")
            continue
        st = tar_path.stat()
        row["size_bytes"] = int(st.st_size)
        row["mtime_unix"] = int(st.st_mtime)
        row["age_s"] = int(now - st.st_mtime)
        pids = _openers(tar_path)
        row["open_pids"] = ",".join(map(str, pids))
        official = int(meta["size"])
        size_ok = int(st.st_size) == official
        row["size_matches_official"] = size_ok
        writing = bool(pids)
        fresh = (now - st.st_mtime) < STALE_SECONDS
        inv_exists = (CATALOG_DIR / "inventory" / f"{month}.csv").exists()
        if writing or (not size_ok and fresh and st.st_size < official):
            row["status"] = "incomplete/downloading"
            row["note"] = f"size {st.st_size} vs official {official}; writer={writing}"
        elif not size_ok:
            row["status"] = "incomplete/downloading"
            row["note"] = f"size {st.st_size} != official {official}"
        elif inv_exists:
            row["status"] = "complete"
            row["tar_tf_ok"] = True
            row["note"] = "size matches Zenodo; inventory present"
        else:
            row["status"] = "complete"
            row["note"] = "size matches Zenodo official file size"
        save_status(month, archive_status=row["status"])
        rows.append(row)
    df = pd.DataFrame(rows)
    df.to_csv(CATALOG_DIR / "m100_2021_archives.csv", index=False)
    return df


def inventory_month(month: str, force: bool = False) -> Path:
    out = CATALOG_DIR / "inventory" / f"{month}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and not force:
        save_status(month, inventory_status="done")
        return out
    tar_path = archive_path(month)
    if not tar_path.exists():
        save_status(month, archive_status="missing", inventory_status="skipped")
        raise FileNotFoundError(tar_path)
    t0 = time.time()
    rows = []
    try:
        with tarfile.open(tar_path, "r:") as tf:
            for m in tf.getmembers():
                if not m.name or m.name.endswith("/"):
                    continue
                plugin = plugin_from_member(m.name)
                metric = metric_from_member(m.name)
                if plugin is None or metric is None:
                    continue
                rows.append({
                    "month": month,
                    "plugin": plugin,
                    "metric": metric,
                    "present": True,
                    "archive_member": m.name,
                    "member_size": int(m.size),
                })
        save_status(month, archive_status="complete", inventory_status="done",
                    runtime_s=round(time.time() - t0, 1), failure=None)
    except tarfile.TarError as exc:
        save_status(month, archive_status="invalid", inventory_status="failed",
                    failure=str(exc), runtime_s=round(time.time() - t0, 1))
        raise
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=["month", "plugin", "metric", "present",
                                   "archive_member", "member_size"])
    else:
        df = df.sort_values(["plugin", "metric", "archive_member"])
    df.to_csv(out, index=False)
    return out


def merge_inventories() -> Path:
    inv_dir = CATALOG_DIR / "inventory"
    frames = []
    if inv_dir.exists():
        for p in sorted(inv_dir.glob("2021-*.csv")):
            frames.append(pd.read_csv(p))
    out = CATALOG_DIR / "m100_2021_metric_inventory.csv"
    if frames:
        pd.concat(frames, ignore_index=True).to_csv(out, index=False)
    else:
        pd.DataFrame(columns=["month", "plugin", "metric", "present",
                              "archive_member", "member_size"]).to_csv(out, index=False)
    return out


def water_audit(inv: pd.DataFrame) -> Path:
    RESULTS = Path(__file__).resolve().parents[1] / "results" / "suitability_2021" / "tables"
    RESULTS.mkdir(parents=True, exist_ok=True)
    hits = inv.loc[inv["metric"].astype(str).str.contains(WATER_NAME_RE, na=False)].copy()
    note_rows = [{
        "finding": "empirical WUE unsupported",
        "evidence": "no documented makeup/withdrawal/consumption metric in complete-month inventory",
        "n_name_hits": int(len(hits)),
    }, {
        "finding": "water withdrawal unsupported",
        "evidence": "Portata_attiva is circulating RDHx loop flow (m3/h x10), not withdrawal",
        "n_name_hits": int(len(hits)),
    }, {
        "finding": "water consumption unsupported",
        "evidence": "official plugin docs do not define a water-meter / makeup series",
        "n_name_hits": int(len(hits)),
    }]
    out = RESULTS / "water_metric_audit.csv"
    if len(hits):
        hits.assign(audit="name_match_only_not_semantics").to_csv(
            RESULTS / "water_metric_name_hits.csv", index=False
        )
    pd.DataFrame(note_rows).to_csv(out, index=False)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", default=None)
    parser.add_argument("--inventory", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    cat = catalog_archives()
    n_complete = int(cat.status.eq("complete").sum())
    n_inc = int(cat.status.eq("incomplete/downloading").sum())
    print(f"catalog rows={len(cat)} complete={n_complete} incomplete={n_inc}")
    if args.inventory and args.month:
        inventory_month(args.month, force=args.force)
        inv_path = merge_inventories()
        inv = pd.read_csv(inv_path)
        water_audit(inv)
        print(f"inventory {args.month} n_members={len(pd.read_csv(CATALOG_DIR / 'inventory' / f'{args.month}.csv'))}")
    elif args.inventory:
        for month, status in zip(cat["month"], cat["status"]):
            if status == "complete":
                try:
                    inventory_month(month, force=args.force)
                except Exception as exc:
                    print(f"FAIL {month}: {exc}")
        merge_inventories()
        inv_path = CATALOG_DIR / "m100_2021_metric_inventory.csv"
        if inv_path.exists():
            water_audit(pd.read_csv(inv_path))


if __name__ == "__main__":
    main()
