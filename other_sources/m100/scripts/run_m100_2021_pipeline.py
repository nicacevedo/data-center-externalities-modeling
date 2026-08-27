#!/usr/bin/env python3
"""Idempotent 2021 M100 suitability pipeline driver.

Discovers currently complete archives and runs only missing stages.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from m100_2021_common import CATALOG_DIR, EXPECTED_MONTHS, ROOT, load_status, save_status


PY = "/home/nacevedo/.conda/envs/dc_externalities/bin/python"


def run(script: str, extra: list[str] | None = None):
    cmd = [PY, str(ROOT / "scripts" / script)] + (extra or [])
    subprocess.run(cmd, check=True, cwd=ROOT)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stage", default="catalog",
                   choices=["catalog", "inventory", "qualify", "process", "node", "analyze", "all"])
    p.add_argument("--month", default=None)
    args = p.parse_args()
    env = {**dict(__import__("os").environ), "PYTHONPATH": str(ROOT / "scripts")}
    import os
    os.environ["PYTHONPATH"] = str(ROOT / "scripts")

    if args.stage in {"catalog", "all"}:
        run("catalog_m100_2021.py")
    if args.stage in {"inventory", "all"}:
        extra = ["--inventory"]
        if args.month:
            extra += ["--month", args.month]
        run("catalog_m100_2021.py", extra)
        run("qualify_m100_2021.py")
    if args.stage == "qualify":
        run("qualify_m100_2021.py")
    if args.stage in {"process", "all"}:
        months = [args.month] if args.month else EXPECTED_MONTHS
        for month in months:
            st = load_status(month)
            if st.get("archive_status") not in {"complete", "complete_unverified"}:
                continue
            if st.get("inventory_status") != "done":
                continue
            if st.get("facility_extraction_status") == "done":
                continue
            try:
                run("process_m100_facility_month.py", ["--month", month])
            except subprocess.CalledProcessError as exc:
                save_status(month, facility_extraction_status="failed", failure=str(exc))
    if args.stage in {"node", "all"}:
        import os
        months = [args.month] if args.month else EXPECTED_MONTHS
        if not os.environ.get("SLURM_JOB_ID"):
            print("Node-hourly extraction should run as a Slurm array, not on the login node:")
            print("  sbatch scripts/run_m100_2021_node_array.sbatch")
        else:
            for month in months:
                st = load_status(month)
                if st.get("archive_status") not in {"complete", "complete_unverified"}:
                    continue
                if st.get("node_extraction_status") == "done":
                    continue
                try:
                    run("process_m100_node_month.py", ["--month", month])
                except subprocess.CalledProcessError as exc:
                    save_status(month, node_extraction_status="failed", failure=str(exc))
    if args.stage in {"analyze", "all"}:
        run("analyze_m100_suitability.py")


if __name__ == "__main__":
    main()
