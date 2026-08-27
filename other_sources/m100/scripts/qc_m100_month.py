#!/usr/bin/env python3
"""Month QC / certification gate. Does not delete archives."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from m100_2021_common import (
    CATALOG_DIR,
    RESULTS_DIR,
    SCHEMA_VERSION,
    ZENODO,
    archive_path,
    git_commit,
    grain_parquet,
    hive_ym,
    load_status,
    month_calendar,
    save_status,
    zenodo_url,
)


def _ok_parquet(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    try:
        pf = pq.ParquetFile(path)
        n = pf.metadata.num_rows
        if n <= 0:
            return False, "empty"
        return True, f"rows={n}"
    except Exception as exc:
        return False, str(exc)


def certify(month: str) -> dict:
    checks = []
    st = load_status(month)
    qpath = RESULTS_DIR / "tables" / "month_qualification.csv"
    qrow = None
    if qpath.exists():
        q = pd.read_csv(qpath)
        hit = q.loc[q.month.eq(month)]
        if len(hit):
            qrow = hit.iloc[0].to_dict()

    meta = ZENODO[month]
    tar = archive_path(month)
    size_ok = tar.exists() and tar.stat().st_size == int(meta["size"])
    checks.append({"item": "archive_size_matches_zenodo", "pass": bool(size_ok),
                   "detail": f"{tar.stat().st_size if tar.exists() else None} vs {meta['size']}"})
    checks.append({"item": "archive_source_recorded", "pass": True,
                   "detail": f"doi={meta['doi']} url={zenodo_url(month)}"})
    checks.append({"item": "official_checksum_recorded", "pass": True, "detail": f"md5={meta['md5']}"})

    inv = CATALOG_DIR / "inventory" / f"{month}.csv"
    checks.append({"item": "tar_member_inventory_saved", "pass": inv.exists(), "detail": str(inv)})

    def need(grain, flag):
        if qrow is None:
            return False
        return bool(qrow.get(flag))

    required = []
    if qrow is not None:
        if qrow.get("facility_total_power") or qrow.get("facility_it_power"):
            required.append("facility")
        if qrow.get("liquid_flow_temp"):
            required.append("liquid_cooling")
        if qrow.get("air_cooling"):
            required.append("crac")
        if qrow.get("weather"):
            required.append("weather")
        if qrow.get("run_node_aggregation"):
            required.append("node")

    products = []
    for grain in required:
        p = grain_parquet(grain, month)
        ok, detail = _ok_parquet(p)
        schema_ok = False
        schema_p = p.with_suffix(".schema.json")
        if schema_p.exists():
            try:
                schema_ok = json.loads(schema_p.read_text()).get("schema_version") == SCHEMA_VERSION
            except Exception:
                schema_ok = False
        checks.append({"item": f"parquet_opens_{grain}", "pass": ok, "detail": detail})
        checks.append({"item": f"schema_version_{grain}", "pass": schema_ok, "detail": str(schema_p)})
        if ok:
            products.append(str(p))
            cols = pq.ParquetFile(p).schema_arrow.names
            if grain == "facility":
                checks.append({"item": "entity_ids_facility", "pass": "panel" in cols and "device" in cols, "detail": ""})
                checks.append({"item": "power_energy_integrals", "pass": any("energy_kwh" in c for c in cols),
                               "detail": "Tot_energy_kwh" if "Tot_energy_kwh" in cols else ",".join(c for c in cols if "energy" in c)})
            if grain == "liquid_cooling":
                checks.append({"item": "entity_ids_liquid", "pass": "panel" in cols, "detail": ""})
                checks.append({"item": "flow_delta_t_preagg", "pass": "flow_delta_t_mean" in cols,
                               "detail": "mean(flow*delta_T) at source seconds, not mean(flow)*mean(dT)"})
            if grain == "crac":
                checks.append({"item": "entity_ids_crac", "pass": "device" in cols, "detail": ""})
            if grain == "weather":
                cal = month_calendar(month)
                df = pd.read_parquet(p, columns=["timestamp_utc"])
                n_cal = int(len(cal))
                checks.append({"item": "weather_calendar_hours", "pass": len(df) == n_cal,
                               "detail": f"{len(df)} vs {n_cal}"})
            if grain == "node":
                checks.append({"item": "node_coverage", "pass": "total_power_coverage" in cols or "total_power_count" in cols, "detail": ""})

    if required:
        checks.append({"item": "required_grains_present", "pass": all(
            grain_parquet(g, month).exists() for g in required
        ), "detail": ",".join(required)})
    else:
        checks.append({"item": "required_grains_present", "pass": True,
                       "detail": "no facility/node grains required for this month"})

    checks.append({"item": "git_commit_recorded", "pass": True, "detail": git_commit()})
    checks.append({"item": "schema_version_recorded", "pass": True, "detail": SCHEMA_VERSION})

    failed = [c for c in checks if not c["pass"]]
    # Deletion allowed only when every required grain passed and archive size matches.
    allow_delete = (not failed) and bool(required) and size_ok
    result = "PASS" if not failed else "FAIL"
    if not required:
        result = "PASS_PARTIAL"
        allow_delete = False
    out = {
        "month": month,
        "certification": result,
        "raw_deletion_allowed": allow_delete,
        "schema_version": SCHEMA_VERSION,
        "required_grains": required,
        "products": products,
        "failed_checks": [c["item"] for c in failed],
        "checks": checks,
        "zenodo": meta,
        "download_url": zenodo_url(month),
        "archive_name": f"{hive_ym(month)}.tar",
    }
    save_status(
        month,
        qc_status=result,
        qc_result=result,
        certification=result,
        raw_deletion_allowed=allow_delete,
        schema_version=SCHEMA_VERSION,
        failure="; ".join(c["item"] for c in failed) if failed else None,
        processed_products=products,
    )
    print(json.dumps({"month": month, "certification": result,
                      "raw_deletion_allowed": allow_delete,
                      "failed": out["failed_checks"]}, indent=2))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--month", required=True)
    args = p.parse_args()
    certify(args.month)


if __name__ == "__main__":
    main()
