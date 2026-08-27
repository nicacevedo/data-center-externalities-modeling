#!/usr/bin/env python3
"""Qualify complete months from the metric inventory. No tar extraction."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

from m100_2021_common import (
    CATALOG_DIR,
    LOGICS_POWER_KW,
    RESULTS_DIR,
    VERTIV_CONTINUOUS,
    WEATHER_METRICS,
    hive_ym,
    save_status,
    schneider_suffix,
)


SCHNEIDER_NEED = {
    "Temp_mandata", "Temp_ritorno", "Portata_attiva", "Delta_temp",
    "Out_pid_pompe", "Set_temperatura", "Pos_valvola1", "Pos_valvola_2",
    "Start_impianto",
}


def _has(inv, month, plugin_substr, metrics) -> bool:
    sub = inv.loc[inv["month"].eq(month) & inv["plugin"].astype(str).str.contains(plugin_substr, case=False, na=False)]
    have = set(sub["metric"].astype(str))
    return any(m in have for m in metrics)


def _schneider_has(inv, month) -> bool:
    sub = inv.loc[inv["month"].eq(month) & inv["plugin"].astype(str).str.contains("schneider", case=False, na=False)]
    suffixes = {schneider_suffix(m) for m in sub["metric"].astype(str)}
    return bool(SCHNEIDER_NEED & suffixes)


def _gpu_direct(inv, month) -> bool:
    sub = inv.loc[inv["month"].eq(month)]
    names = sub["metric"].astype(str)
    util = names.str.contains(r"Gpu\d+_gpu_utilization", case=False, regex=True).any()
    pwr = names.str.contains(r"Gpu\d+_power_usage", case=False, regex=True).any()
    tmp = names.str.contains(r"Gpu\d+_gpu_temp", case=False, regex=True).any()
    return bool(util and pwr and tmp)


def qualify(inv: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for month in sorted(inv["month"].dropna().unique()):
        plugins = sorted(inv.loc[inv.month.eq(month), "plugin"].astype(str).unique())
        elec = _has(inv, month, "logics", LOGICS_POWER_KW)
        ict = _has(inv, month, "logics", ["Tot_ict"])
        cool_p = _has(inv, month, "logics", ["Tot_cdz", "Tot_chiller", "Tot_qpompe"])
        liquid = _schneider_has(inv, month)
        air = _has(inv, month, "vertiv", VERTIV_CONTINUOUS[:4])
        weather = _has(inv, month, "weather", WEATHER_METRICS)
        node_p = _has(inv, month, "ipmi", ["total_power"])
        gpu = _gpu_direct(inv, month)
        classes = []
        if elec and ict:
            classes.append("electrical-qualified")
        if liquid:
            classes.append("thermal-qualified")
        if air or weather:
            classes.append("air-weather-qualified")
        if elec and ict and liquid and (air or weather):
            classes.append("full-facility-qualified")
        if node_p:
            classes.append("node-bridge-qualified")
        if gpu:
            classes.append("GPU-validation-qualified")
        row = {
            "month": month,
            "plugins": "|".join(plugins),
            "facility_total_power": elec,
            "facility_it_power": ict,
            "cooling_component_power": cool_p,
            "liquid_flow_temp": liquid,
            "air_cooling": air,
            "weather": weather,
            "node_total_power": node_p,
            "direct_gpu_power_util": gpu,
            "classes": "|".join(classes) if classes else "none",
            "run_node_aggregation": bool(node_p and (ict or gpu)),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def write_metadata(inv: pd.DataFrame) -> Path:
    meta = (
        inv.groupby(["plugin", "metric"], as_index=False)
        .agg(n_months=("month", "nunique"), total_member_bytes=("member_size", "sum"))
        .sort_values(["plugin", "metric"])
    )
    path = CATALOG_DIR / "m100_metric_metadata.csv"
    meta.to_csv(path, index=False)
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path,
                        default=CATALOG_DIR / "m100_2021_metric_inventory.csv")
    args = parser.parse_args()
    if not args.inventory.exists():
        raise SystemExit(f"missing inventory {args.inventory}")
    inv = pd.read_csv(args.inventory)
    q = qualify(inv)
    out_dir = RESULTS_DIR / "tables"
    out_dir.mkdir(parents=True, exist_ok=True)
    q.to_csv(out_dir / "month_qualification.csv", index=False)
    write_metadata(inv)
    print(q[["month", "classes", "run_node_aggregation"]].to_string(index=False))


if __name__ == "__main__":
    main()
