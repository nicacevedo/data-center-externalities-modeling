#!/usr/bin/env python3
"""Delete scratch extracts always; delete Pool raw tar only if certification allows it."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from m100_2021_common import (
    SCRATCH_M100,
    archive_path,
    grain_parquet,
    load_status,
    save_status,
)


def cleanup_month(month: str, allow_raw_delete: bool | None = None) -> dict:
    st = load_status(month)
    report = {"month": month, "deleted": [], "kept": [], "reason": None}
    # scratch leftovers
    for p in SCRATCH_M100.glob(f"tmp/**/m100_{month}_*"):
        shutil.rmtree(p, ignore_errors=True)
        report["deleted"].append(str(p))
    for p in (SCRATCH_M100 / "tmp").glob(f"*m100_{month}*"):
        shutil.rmtree(p, ignore_errors=True)
        report["deleted"].append(str(p))

    allowed = st.get("raw_deletion_allowed") if allow_raw_delete is None else allow_raw_delete
    cert = st.get("certification") or st.get("qc_result")
    tar = archive_path(month)
    if not tar.exists():
        report["reason"] = "no local tar"
        print(report)
        return report
    if cert != "PASS" or not allowed:
        report["kept"].append(str(tar))
        report["reason"] = f"cert={cert} raw_deletion_allowed={allowed}"
        save_status(month, cleanup="tar_retained")
        print(report)
        return report
    # re-verify processed files exist before delete
    products = st.get("processed_products") or []
    missing = [p for p in products if not Path(p).exists()]
    if missing:
        report["kept"].append(str(tar))
        report["reason"] = f"missing processed products {missing[:3]}"
        save_status(month, cleanup="tar_retained_missing_products", failure=report["reason"])
        print(report)
        return report
    tar.unlink()
    report["deleted"].append(str(tar))
    save_status(month, archive_status="deleted_after_cert", cleanup="tar_deleted")
    print(report)
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--month", required=True)
    args = p.parse_args()
    cleanup_month(args.month)


if __name__ == "__main__":
    main()
