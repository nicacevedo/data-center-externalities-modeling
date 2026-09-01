#!/usr/bin/env python3
"""Prineville 2022 envelopes for cases 1–2. Runs only after adapter PASS. No Meta water."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from v2_common import RES, set_threads  # noqa: E402


def main():
    set_threads()
    st = json.loads((RES / "FINAL_MASANET_STATUS.json").read_text())
    if not st.get("proceed_to_prineville"):
        print("blocked: proceed_to_prineville is false")
        (RES / "prineville" / "BLOCKED.json").parent.mkdir(parents=True, exist_ok=True)
        (RES / "prineville" / "BLOCKED.json").write_text(
            json.dumps({"status": "BLOCKED", "reason": "adapter/quantitative gate did not pass"}, indent=2) + "\n"
        )
        sys.exit(0)
    # Reuse V1 runner logic but write under v2 by temporarily not touching FOLLOWUP:
    # implement local copy via followup_prineville functions with patched output dir.
    import followup_prineville as fp
    from instrument_upstream import write_instrumented
    from followup_annual import n_workers
    from common import atomic_write_json, utcnow

    wx = fp.load_prineville_2022()
    write_instrumented()
    workers = n_workers(0)
    outdir = RES / "prineville"
    outdir.mkdir(parents=True, exist_ok=True)
    # monkeypatch FOLLOWUP used for parquet writes
    fp.FOLLOWUP = outdir
    cases = {}
    for case in fp.PRINEVILLE_CASES:
        cases[str(case)] = fp.run_case(case, wx, workers)
    out = {
        "status": "PASS",
        "timestamp_utc": utcnow(),
        "weather_year_local": fp.YEAR,
        "cases": cases,
        "did_read_meta_2023_2024_water": False,
        "question": (
            "Under actual Prineville weather, what facility-energy and onsite-conditioning-water "
            "intensity envelopes do plausible published archetypes imply?"
        ),
        "not": [
            "Meta archetype identification",
            "calibration",
            "model selection",
            "fitting",
            "validation against private/site water",
            "groundwater pumping estimation",
        ],
    }
    atomic_write_json(outdir / "prineville_2022.json", out)
    print(json.dumps({"status": "PASS", "case1": cases["1"], "case2": cases["2"]}, indent=2, default=str))


if __name__ == "__main__":
    main()
