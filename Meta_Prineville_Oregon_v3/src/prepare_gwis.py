"""Parse local OWRD GWIS exports without double-counting duplicate files.

Does not compute hydraulic head from land-surface elevation, split combined
OWRD pumping groups, or map wells by name/proximity.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
GWIS_RAW = ROOT / "data" / "raw" / "gwis_data_new"

SITE_PREFIX = "gw_site"
LEVEL_PREFIX = "gw_measured_water_level"
CONSTRUCTION_PREFIX = "gw_well_construction"
HISTORY_PREFIX = "gw_well_construction_history"
LITHOLOGY_PREFIX = "gw_lithology"
IDENTITY_PREFIX = "gw_other_identity"
RIGHTS_PREFIX = "gw_water_rights"

UNMAPPED_VITESSE_REPORTS = {64500, 64845}


def gwis_txt_files(root: Path | None = None) -> list[Path]:
    base = root or GWIS_RAW
    if not base.exists():
        return []
    return sorted(p for p in base.rglob("*.txt") if p.is_file())


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hash_inventory(files: list[Path] | None = None) -> pd.DataFrame:
    rows = []
    for p in files if files is not None else gwis_txt_files():
        rel = p.as_posix()
        try:
            rel = p.resolve().relative_to(ROOT.resolve()).as_posix()
        except ValueError:
            pass
        rows.append(
            {
                "source_file": rel,
                "filename": p.name,
                "sha256": file_sha256(p),
                "nbytes": p.stat().st_size,
                "table_prefix": _table_prefix(p.name),
            }
        )
    return pd.DataFrame(rows)


def _table_prefix(name: str) -> str:
    stem = re.sub(r"\s*\(\d+\)\s*$", "", Path(name).stem)
    return stem


def duplicate_file_groups(inv: pd.DataFrame) -> list[list[str]]:
    groups = []
    if inv.empty:
        return groups
    for _, g in inv.groupby("sha256"):
        if len(g) > 1:
            groups.append(sorted(g["filename"].tolist()))
    return groups


def _read_table(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep="\t", dtype=str)
    rel = path.name
    try:
        rel = path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        rel = path.as_posix()
    df["_source_file"] = rel
    df["_source_filename"] = path.name
    df["_sha256"] = file_sha256(path)
    return df


def load_all_tables(prefix: str, files: list[Path] | None = None) -> pd.DataFrame:
    """Load every file for a table prefix, including byte-identical copies."""
    hits = []
    for p in files if files is not None else gwis_txt_files():
        if _table_prefix(p.name) == prefix:
            hits.append(p)
    if not hits:
        return pd.DataFrame()
    return pd.concat([_read_table(p) for p in hits], ignore_index=True)


def id_digits(value) -> str:
    s = re.sub(r"[^0-9]", "", str(value or ""))
    if not s:
        return ""
    return s.lstrip("0") or s


def _first_non_null(series: pd.Series):
    s = series.dropna()
    s = s[s.astype(str).str.strip().ne("")]
    if s.empty:
        return pd.NA
    return s.iloc[0]


def dedupe_sites(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return raw
    rows = []
    for site_id, g in raw.groupby("gw_site_id", sort=False):
        row = {c: _first_non_null(g[c]) for c in g.columns if not c.startswith("_")}
        row["source_files"] = ";".join(sorted(set(g["_source_file"].astype(str))))
        row["n_raw_export_rows"] = len(g)
        rows.append(row)
    return pd.DataFrame(rows)


def dedupe_levels(raw: pd.DataFrame) -> pd.DataFrame:
    """Unique observations by GWIS measurement ID; preserve every raw filename."""
    if raw.empty:
        return raw
    rows = []
    for mid, g in raw.groupby("gw_measured_water_level_id", sort=False):
        row = {c: _first_non_null(g[c]) for c in g.columns if not c.startswith("_")}
        row["source_files"] = ";".join(sorted(set(g["_source_file"].astype(str))))
        row["n_raw_export_rows"] = len(g)
        rows.append(row)
    out = pd.DataFrame(rows)
    if out["gw_measured_water_level_id"].duplicated().any():
        raise ValueError("GWIS measurement IDs are not unique after provenance merge")
    return out


def open_interval_bounds(construction: pd.DataFrame) -> pd.DataFrame:
    if construction.empty:
        return pd.DataFrame(
            columns=["gw_site_id", "open_interval_top_ft", "open_interval_bottom_ft", "n_open_intervals"]
        )
    oi = construction[construction["feature_type"].astype(str).eq("Open Interval")].copy()
    oi["start_depth_ft"] = pd.to_numeric(oi["start_depth_ft"], errors="coerce")
    oi["end_depth_ft"] = pd.to_numeric(oi["end_depth_ft"], errors="coerce")
    g = oi.groupby("gw_site_id", as_index=False).agg(
        open_interval_top_ft=("start_depth_ft", "min"),
        open_interval_bottom_ft=("end_depth_ft", "max"),
        n_open_intervals=("gw_well_construction_id", "nunique"),
    )
    return g


def history_summary(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame()
    hist = history.copy()
    hist["_complete"] = pd.to_datetime(hist["complete_date"], errors="coerce")
    hist = hist.sort_values(["gw_site_id", "_complete"], na_position="last")
    keep = []
    for site_id, g in hist.groupby("gw_site_id", sort=False):
        last = g.iloc[-1]
        keep.append(
            {
                "gw_site_id": site_id,
                "owner_name": last.get("owner_name", pd.NA),
                "completed_depth_ft": pd.to_numeric(last.get("completed_depth"), errors="coerce"),
                "complete_date": last.get("complete_date", pd.NA),
                "construction_aquifer": last.get("aquifer_description")
                if pd.notna(last.get("aquifer_description"))
                else last.get("aquifer"),
                "aquifer_usgs_local_description": last.get("aquifer_usgs_local_description", pd.NA),
                "history_source_files": ";".join(sorted(set(g["_source_file"].astype(str)))),
            }
        )
    return pd.DataFrame(keep)


def compile_gwis_bundle(root: Path | None = None) -> dict[str, pd.DataFrame]:
    files = gwis_txt_files(root)
    inv = hash_inventory(files)
    sites = dedupe_sites(load_all_tables(SITE_PREFIX, files))
    levels = dedupe_levels(load_all_tables(LEVEL_PREFIX, files))
    construction_raw = load_all_tables(CONSTRUCTION_PREFIX, files)
    construction = pd.DataFrame()
    if not construction_raw.empty:
        parts = []
        for cid, g in construction_raw.groupby("gw_well_construction_id", sort=False):
            row = {c: _first_non_null(g[c]) for c in g.columns if not c.startswith("_")}
            row["source_files"] = ";".join(sorted(set(g["_source_file"].astype(str))))
            parts.append(row)
        construction = pd.DataFrame(parts)
    history = load_all_tables(HISTORY_PREFIX, files)
    hist_sum = history_summary(history) if not history.empty else pd.DataFrame()
    if not sites.empty and not hist_sum.empty:
        sites = sites.merge(
            hist_sum[
                [
                    "gw_site_id",
                    "owner_name",
                    "completed_depth_ft",
                    "complete_date",
                    "construction_aquifer",
                    "aquifer_usgs_local_description",
                ]
            ],
            on="gw_site_id",
            how="left",
        )
    lithology = load_all_tables(LITHOLOGY_PREFIX, files)
    identity = load_all_tables(IDENTITY_PREFIX, files)
    rights = load_all_tables(RIGHTS_PREFIX, files)
    return {
        "file_inventory": inv,
        "sites": sites,
        "levels": levels,
        "construction": construction,
        "history": hist_sum,
        "history_raw": history,
        "lithology": lithology,
        "identity": identity,
        "water_rights": rights,
        "open_intervals": open_interval_bounds(construction),
    }


def inventory_match_keys(inv_row: dict) -> set[str]:
    keys = set()
    for field in ("well_log_id", "owrd_wl_id", "well_tag"):
        d = id_digits(inv_row.get(field, ""))
        if d:
            keys.add(d)
    return keys


def gwis_match_keys(site_row: pd.Series) -> set[str]:
    keys = set()
    for field in ("gw_well_tag_nbr", "gw_logid"):
        d = id_digits(site_row.get(field, ""))
        if d:
            keys.add(d)
    return keys


def match_gwis_to_inventory(sites: pd.DataFrame, inventory_rows: list[dict]) -> pd.DataFrame:
    """Map GWIS sites to inventory nodes only on official identifier digit cores."""
    inv_keys: list[tuple[str, set[str], dict]] = []
    for row in inventory_rows:
        keys = inventory_match_keys(row)
        inv_keys.append((row["well_node_id"], keys, row))

    records = []
    used_nodes: dict[str, str] = {}
    for _, site in sites.iterrows():
        site_keys = gwis_match_keys(site)
        hits = []
        for node_id, keys, row in inv_keys:
            if site_keys and keys and site_keys & keys:
                hits.append((node_id, sorted(site_keys & keys), row))
        owner = str(site.get("owner_name", "") or "")
        if len(hits) == 1:
            node_id, shared, row = hits[0]
            if node_id in used_nodes and used_nodes[node_id] != str(site["gw_site_id"]):
                raise ValueError(f"inventory node {node_id} matched multiple GWIS sites")
            used_nodes[node_id] = str(site["gw_site_id"])
            status = "confirmed_official_id"
            notes = f"shared_id_digits={','.join(shared)}"
        elif len(hits) > 1:
            status = "candidate_unresolved"
            node_id = ""
            notes = "ambiguous official-id intersection: " + ";".join(h[0] for h in hits)
        else:
            status = "candidate_unresolved"
            node_id = ""
            notes = "no official well/tag/log ID intersection with existing inventory"
            if "vitesse" in owner.lower():
                notes += (
                    "; Vitesse-named GWIS well is not mapped to reports "
                    f"{sorted(UNMAPPED_VITESSE_REPORTS)} without an exact identifier match"
                )
        records.append(
            {
                "gw_site_id": str(site["gw_site_id"]),
                "gw_logid": site.get("gw_logid", ""),
                "gw_well_tag_nbr": site.get("gw_well_tag_nbr", ""),
                "well_node_id": node_id,
                "identity_status": status,
                "owner_name": owner,
                "match_notes": notes,
            }
        )
    return pd.DataFrame(records)
