"""Groundwater observation scaffold from repository identities plus local GWIS.

Does not fit a groundwater dynamics model, infer missing heads, convert mixed
vertical datums, split combined OWRD reporting groups, or treat HUC12 as an
aquifer/network node.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_gwis import (  # noqa: E402
    UNMAPPED_VITESSE_REPORTS,
    compile_gwis_bundle,
    match_gwis_to_inventory,
)
from usgs_nwaa_config import pad_huc12

ROOT = Path(__file__).resolve().parents[1]
CANON = ROOT / "data" / "canonical"
CANON_GW = CANON / "groundwater"
PROC_GW = ROOT / "data" / "processed" / "groundwater"
QC = ROOT / "outputs" / "qc"
OUT_GW = ROOT / "outputs" / "groundwater"
PERMITS_PDF = ROOT / "data" / "raw" / "permits_pdfs"

CITY_SOURCES = CANON / "city_water_sources.csv"
OWRD_XWALK = CANON / "prineville_owrd_source_crosswalk.csv"
HUC_XWALK = CANON / "municipal_source_huc12_crosswalk.csv"
DIRECT_REG = CANON / "meta_owrd_direct_sources.csv"
CITY_MODEL = ROOT / "data" / "processed" / "owrd" / "owrd_city_monthly_model_use.csv"
DIRECT_MONTHLY = ROOT / "data" / "processed" / "owrd" / "owrd_meta_direct_monthly_use.csv"
META_ANNUAL = CANON / "meta_prineville_annual.csv"
ASR_TEMPLATE = ROOT / "data" / "manual_templates" / "asr_monthly.csv"

INV_OUT = CANON_GW / "groundwater_well_inventory.csv"
XWALK_OUT = CANON_GW / "water_source_groundwater_crosswalk.csv"
PARAM_OUT = CANON_GW / "hydrogeologic_parameter_inventory.csv"
PUMP_OUT = PROC_GW / "groundwater_pumping_monthly.csv"
LEVEL_OUT = PROC_GW / "groundwater_level_observations.csv"
QA_OUT = QC / "groundwater_context_qa.csv"
FEAS_OUT = OUT_GW / "groundwater_model_feasibility.csv"
GWIS_HASH_OUT = OUT_GW / "gwis_raw_file_hashes.csv"
PDF_SCAN_OUT = OUT_GW / "local_pdf_hydrogeology_scan.csv"

ROLES = (
    "municipal_production",
    "Vitesse_Facebook_direct",
    "ASR",
    "monitoring",
    "other",
    "unknown",
)

ASR_FEASIBILITY_OHA = {"SRC-GC", "SRC-JA"}
BOUNDARY_CITY = "city_municipal_production"
BOUNDARY_DIRECT = "vitesse_facebook_direct_pod"
BOUNDARY_META = "meta_campus_annual_withdrawal"

CATALOGUED_ASR_NAMES = (
    "PrinevilleASR_Application.pdf",
    "PrinevilleASR_Attachments.pdf",
)

PDF_PARAM_KEYWORDS = (
    "transmissivity",
    "storativity",
    "specific yield",
    "hydraulic conductivity",
    "drawdown",
    "aquifer storage",
    "heliport",
    "millican",
    "injection",
    "recovery",
)

PARAM_SEARCH_NAMES = [
    "transmissivity",
    "hydraulic_conductivity",
    "storativity",
    "specific_yield",
    "aquifer_thickness",
    "pumping_test_result",
    "drawdown_recovery",
    "asr_injection_recovery_assumption",
    "monitoring_well_information",
    "model_calibrated_parameter_range",
]


def _mkdirs() -> None:
    for p in (CANON_GW, PROC_GW, QC, OUT_GW):
        p.mkdir(parents=True, exist_ok=True)


def _year_month(ts) -> str:
    t = pd.to_datetime(ts)
    return f"{int(t.year):04d}-{int(t.month):02d}"


def _city_role(oha_id: str, model_use: str) -> str:
    text = f"{oha_id} {model_use}".lower()
    if oha_id in ASR_FEASIBILITY_OHA or "asr feasibility" in text:
        return "ASR"
    return "municipal_production"


def _local_asr_named_pdfs() -> list[str]:
    hits: list[Path] = []
    for folder in (
        ROOT / "data" / "raw",
        ROOT / "data" / "canonical",
        ROOT / "data" / "manual",
        ROOT / "docs",
    ):
        if not folder.exists():
            continue
        for name in CATALOGUED_ASR_NAMES:
            hits.extend(folder.rglob(name))
        hits.extend(folder.rglob("*asr*.pdf"))
        hits.extend(folder.rglob("*ASR*.pdf"))
        hits.extend(folder.rglob("*hydrogeo*.pdf"))
    out = []
    for p in hits:
        try:
            out.append(p.relative_to(ROOT).as_posix())
        except ValueError:
            out.append(str(p))
    return sorted(set(out))


def _permit_pdfs() -> list[Path]:
    if not PERMITS_PDF.exists():
        return []
    return sorted(p for p in PERMITS_PDF.rglob("*.pdf") if p.is_file())


def scan_local_pdfs_for_hydrogeology() -> pd.DataFrame:
    """Machine-readable text scan. No OCR. No inferred numbers."""
    import pymupdf as fitz

    rows = []
    for p in _permit_pdfs():
        try:
            rel = p.relative_to(ROOT).as_posix()
        except ValueError:
            rel = p.as_posix()
        try:
            doc = fitz.open(p)
        except Exception as exc:  # noqa: BLE001
            rows.append(
                {
                    "source_file": rel,
                    "n_pages": np.nan,
                    "extractable_chars": 0,
                    "keyword_hits": "",
                    "status": f"unreadable:{exc}",
                }
            )
            continue
        texts = []
        hits = set()
        for i, page in enumerate(doc, start=1):
            text = page.get_text() or ""
            texts.append(text)
            low = text.lower()
            page_hits = [k for k in PDF_PARAM_KEYWORDS if k in low]
            if page_hits:
                hits.update(f"{k}@p{i}" for k in page_hits)
        doc.close()
        blob = "\n".join(texts)
        rows.append(
            {
                "source_file": rel,
                "n_pages": len(texts),
                "extractable_chars": len(blob),
                "keyword_hits": ";".join(sorted(hits)),
                "status": "scanned_no_asr_hydrogeologic_parameters"
                if not hits
                else "keyword_hit_no_defensible_numeric_extraction",
            }
        )
    named = _local_asr_named_pdfs()
    for name in CATALOGUED_ASR_NAMES:
        present = any(Path(p).name == name for p in named)
        rows.append(
            {
                "source_file": f"catalogued:{name}",
                "n_pages": np.nan,
                "extractable_chars": 0,
                "keyword_hits": "",
                "status": "present_locally" if present else "catalogued_filename_not_found_under_data_raw",
            }
        )
    return pd.DataFrame(rows)


def _base_inventory_rows() -> list[dict]:
    city = pd.read_csv(CITY_SOURCES)
    xw = pd.read_csv(OWRD_XWALK)
    huc = pd.read_csv(HUC_XWALK)
    direct = pd.read_csv(DIRECT_REG)

    xw = xw.copy()
    huc = huc.copy()
    xw["oha_facility_id"] = xw["oha_facility_id"].astype(str)
    huc["source_id"] = huc["source_id"].astype(str)
    city["oha_facility_id"] = city["oha_facility_id"].astype(str)

    xw_idx = xw.set_index("oha_facility_id", drop=False)
    huc_idx = huc.set_index("source_id", drop=False)

    rows = []
    for r in city.itertuples(index=False):
        oha = str(r.oha_facility_id)
        xr = xw_idx.loc[oha] if oha in xw_idx.index else None
        hr = huc_idx.loc[oha] if oha in huc_idx.index else None
        lat = lon = huc12 = None
        coord_source = ""
        mapping_method = "unresolved_missing_coordinates"
        if hr is not None and pd.notna(hr.latitude) and pd.notna(hr.longitude):
            lat = float(hr.latitude)
            lon = float(hr.longitude)
            huc12 = pad_huc12(hr.huc12_id) if pd.notna(hr.huc12_id) else ""
            coord_source = str(hr.match_method) if pd.notna(hr.match_method) else "official_coordinates"
            mapping_method = str(hr.match_method) if pd.notna(hr.match_method) else "official_coordinates"
        notes = [str(r.model_use)]
        if hr is not None and pd.notna(getattr(hr, "unresolved_reason", np.nan)):
            notes.append(str(hr.unresolved_reason))
        if hr is not None and str(getattr(hr, "in_study_geography", "")).lower() in {"false", "0"}:
            notes.append("WBD HUC12 is a location attribute only; not an aquifer/network node.")
        conf = float(xr.confidence) if xr is not None and pd.notna(xr.confidence) else np.nan
        rows.append(
            {
                "well_node_id": oha,
                "source_name": r.source_name,
                "oha_source_id": oha,
                "owrd_report_or_pod_id": (
                    str(xr.accepted_owrd_report_ids)
                    if xr is not None and pd.notna(xr.accepted_owrd_report_ids)
                    else ""
                ),
                "well_log_id": r.well_log if pd.notna(r.well_log) else "",
                "owrd_wl_id": (
                    str(int(xr.owrd_wl_id_known))
                    if xr is not None and pd.notna(xr.owrd_wl_id_known)
                    else ""
                ),
                "latitude": lat,
                "longitude": lon,
                "huc12": huc12 or "",
                "huc12_is_not_aquifer_node": True,
                "well_depth": np.nan,
                "screen_top": np.nan,
                "screen_bottom": np.nan,
                "aquifer_geologic_unit": "",
                "role": _city_role(oha, str(r.model_use)),
                "status": r.status,
                "source_group": r.source_group,
                "coordinate_source": coord_source,
                "mapping_method": mapping_method,
                "mapping_confidence": conf,
                "in_study_geography": (
                    bool(hr.in_study_geography) if hr is not None and pd.notna(hr.in_study_geography) else False
                ),
                "gwis_site_id": "",
                "gwis_logid": "",
                "gwis_well_tag": "",
                "land_surface_elevation": np.nan,
                "elevation_datum": "",
                "identity_status": "unresolved" if mapping_method == "unresolved_missing_coordinates" else "documented",
                "notes": " | ".join(n for n in notes if n and n != "nan"),
            }
        )

    for r in direct.itertuples(index=False):
        rows.append(
            {
                "well_node_id": f"VITESSE:{int(r.report_id)}",
                "source_name": r.canonical_name,
                "oha_source_id": "",
                "owrd_report_or_pod_id": str(int(r.report_id)),
                "well_log_id": r.owrd_well_tag if pd.notna(r.owrd_well_tag) else "",
                "owrd_wl_id": r.owrd_well_id if pd.notna(r.owrd_well_id) else "",
                "latitude": np.nan,
                "longitude": np.nan,
                "huc12": "",
                "huc12_is_not_aquifer_node": True,
                "well_depth": np.nan,
                "screen_top": np.nan,
                "screen_bottom": np.nan,
                "aquifer_geologic_unit": "",
                "role": "Vitesse_Facebook_direct",
                "status": "active",
                "source_group": "Vitesse/Facebook direct POD",
                "coordinate_source": "",
                "mapping_method": "unresolved_missing_coordinates",
                "mapping_confidence": float(r.confidence) if pd.notna(r.confidence) else 1.0,
                "in_study_geography": False,
                "gwis_site_id": "",
                "gwis_logid": "",
                "gwis_well_tag": "",
                "land_surface_elevation": np.nan,
                "elevation_datum": "",
                "identity_status": "unresolved",
                "notes": (
                    f"{r.boundary_note} Official coordinates are not in the pre-GWIS repository; "
                    "TRSQQ/bearing text was not converted to a point."
                ),
            }
        )
    return rows


def _apply_gwis_to_inventory(rows: list[dict], bundle: dict[str, pd.DataFrame]) -> list[dict]:
    sites = bundle["sites"]
    if sites.empty:
        return rows
    matches = match_gwis_to_inventory(sites, rows)
    oi = bundle["open_intervals"]
    oi_idx = oi.set_index("gw_site_id") if not oi.empty else pd.DataFrame()
    site_idx = sites.set_index("gw_site_id", drop=False)
    match_idx = matches.set_index("gw_site_id")

    by_node = {r["well_node_id"]: r for r in rows}
    for site_id, m in match_idx.iterrows():
        site = site_idx.loc[str(site_id)]
        lat = pd.to_numeric(site.get("latitude_dec"), errors="coerce")
        lon = pd.to_numeric(site.get("longitude_dec"), errors="coerce")
        depth = pd.to_numeric(site.get("max_depth"), errors="coerce")
        if pd.isna(depth):
            depth = pd.to_numeric(site.get("completed_depth_ft"), errors="coerce")
        lsd = pd.to_numeric(site.get("lsd_elevation"), errors="coerce")
        datum = site.get("elevation_datum", "") if pd.notna(site.get("elevation_datum", pd.NA)) else ""
        aquifer = ""
        for field in ("aquifer", "construction_aquifer", "aquifer_system"):
            val = site.get(field, pd.NA)
            if pd.notna(val) and str(val).strip() and str(val).lower() != "nan":
                aquifer = str(val).strip()
                break
        top = bottom = np.nan
        if not oi_idx.empty and str(site_id) in oi_idx.index:
            top = oi_idx.loc[str(site_id), "open_interval_top_ft"]
            bottom = oi_idx.loc[str(site_id), "open_interval_bottom_ft"]

        if m.identity_status == "confirmed_official_id" and m.well_node_id:
            r = by_node[m.well_node_id]
            r["gwis_site_id"] = str(site_id)
            r["gwis_logid"] = site.get("gw_logid", "")
            r["gwis_well_tag"] = site.get("gw_well_tag_nbr", "")
            r["identity_status"] = "confirmed_official_id"
            r["mapping_method"] = "official_well_tag_or_log_id"
            r["well_depth"] = depth
            r["screen_top"] = top
            r["screen_bottom"] = bottom
            r["aquifer_geologic_unit"] = aquifer
            r["land_surface_elevation"] = lsd
            r["elevation_datum"] = datum
            if pd.notna(lat) and pd.notna(lon):
                r["latitude"] = float(lat)
                r["longitude"] = float(lon)
                r["coordinate_source"] = "gwis_official_coordinates"
            r["notes"] = (
                f"{r['notes']} | GWIS site {site_id} matched on official well/tag/log ID "
                f"({m.match_notes}). Elevation datum={datum or 'unspecified'}."
            )
            continue

        node = f"GWIS:{site_id}"
        owner = m.owner_name if pd.notna(m.owner_name) else site.get("owner_name", "")
        owner = str(owner).strip()
        if owner.lower() in {"", "nan", "none"}:
            owner = ""
        logid = str(site.get("gw_logid", "") or "").strip()
        source_name = " ".join(x for x in (owner, logid) if x) or node
        by_node[node] = {
            "well_node_id": node,
            "source_name": source_name,
            "oha_source_id": "",
            "owrd_report_or_pod_id": "",
            "well_log_id": site.get("gw_logid", ""),
            "owrd_wl_id": site.get("gw_logid", ""),
            "latitude": float(lat) if pd.notna(lat) else np.nan,
            "longitude": float(lon) if pd.notna(lon) else np.nan,
            "huc12": "",
            "huc12_is_not_aquifer_node": True,
            "well_depth": depth,
            "screen_top": top,
            "screen_bottom": bottom,
            "aquifer_geologic_unit": aquifer,
            "role": "other",
            "status": "gwis_unmatched",
            "source_group": "GWIS unmatched / candidate",
            "coordinate_source": "gwis_official_coordinates" if pd.notna(lat) and pd.notna(lon) else "",
            "mapping_method": "candidate_unresolved",
            "mapping_confidence": np.nan,
            "in_study_geography": False,
            "gwis_site_id": str(site_id),
            "gwis_logid": site.get("gw_logid", ""),
            "gwis_well_tag": site.get("gw_well_tag_nbr", ""),
            "land_surface_elevation": lsd,
            "elevation_datum": datum,
            "identity_status": "candidate_unresolved",
            "notes": m.match_notes,
        }
    return list(by_node.values())


def build_well_inventory(bundle: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    rows = _base_inventory_rows()
    if bundle is not None:
        rows = _apply_gwis_to_inventory(rows, bundle)
    inv = pd.DataFrame(rows)
    if not inv["well_node_id"].is_unique:
        raise ValueError("well_node_id must be unique")
    if not inv["role"].isin(ROLES).all():
        raise ValueError(f"unexpected role values: {sorted(set(inv.role) - set(ROLES))}")
    unresolved = inv["mapping_method"].eq("unresolved_missing_coordinates")
    if inv.loc[unresolved, ["latitude", "longitude"]].notna().any().any():
        raise ValueError("unresolved wells must not have inferred coordinates")
    # Vitesse PODs without an exact GWIS identifier remain unmapped.
    for rid in UNMAPPED_VITESSE_REPORTS:
        node = f"VITESSE:{rid}"
        sub = inv.loc[inv.well_node_id.eq(node)]
        if not sub.empty and sub["gwis_site_id"].astype(str).str.len().gt(0).any():
            if sub["identity_status"].eq("confirmed_official_id").any():
                raise ValueError(f"{node} was mapped without a supporting official ID check")
    return inv


def build_source_crosswalk(inv: pd.DataFrame) -> pd.DataFrame:
    city = pd.read_csv(CITY_SOURCES)
    xw = pd.read_csv(OWRD_XWALK)
    model = pd.read_csv(CITY_MODEL)
    direct = pd.read_csv(DIRECT_REG)

    group_by_source: dict[str, str] = {}
    for key, ids in (
        model[["model_source_key", "canonical_source_ids"]].drop_duplicates().itertuples(index=False)
    ):
        for sid in str(ids).split(";"):
            sid = sid.strip()
            if sid:
                group_by_source[sid] = str(key)

    rows = []
    city_ids = set(city.oha_facility_id.astype(str))
    xw = xw.copy()
    xw["oha_facility_id"] = xw["oha_facility_id"].astype(str)
    xw_idx = xw.set_index("oha_facility_id", drop=False)

    for oha in sorted(city_ids):
        xr = xw_idx.loc[oha] if oha in xw_idx.index else None
        group = group_by_source.get(oha, "")
        split_rule = "do_not_split_combined_pod" if str(group).startswith("COMBINED_ACCEPTED:") else (
            "one_to_one_accepted_group" if group else "no_accepted_pumping_series"
        )
        rows.append(
            {
                "well_node_id": oha,
                "oha_source_id": oha,
                "owrd_report_or_pod_id": (
                    str(xr.accepted_owrd_report_ids)
                    if xr is not None and pd.notna(xr.accepted_owrd_report_ids)
                    else ""
                ),
                "pumping_group_id": group,
                "boundary_id": BOUNDARY_CITY,
                "mapping_status": xr.mapping_status if xr is not None else "",
                "mapping_confidence": float(xr.confidence) if xr is not None and pd.notna(xr.confidence) else np.nan,
                "pumping_allocation_rule": split_rule,
                "huc12_is_not_aquifer_node": True,
                "identity_status": inv.loc[inv.well_node_id.eq(oha), "identity_status"].iloc[0]
                if oha in set(inv.well_node_id)
                else "unresolved",
                "notes": (
                    xr.production_handling
                    if xr is not None and pd.notna(xr.production_handling)
                    else ""
                ),
            }
        )

    for r in direct.itertuples(index=False):
        node = f"VITESSE:{int(r.report_id)}"
        ident = inv.loc[inv.well_node_id.eq(node), "identity_status"]
        rows.append(
            {
                "well_node_id": node,
                "oha_source_id": "",
                "owrd_report_or_pod_id": str(int(r.report_id)),
                "pumping_group_id": node,
                "boundary_id": BOUNDARY_DIRECT,
                "mapping_status": r.mapping_status,
                "mapping_confidence": float(r.confidence) if pd.notna(r.confidence) else 1.0,
                "pumping_allocation_rule": "one_to_one_report_id",
                "huc12_is_not_aquifer_node": True,
                "identity_status": ident.iloc[0] if len(ident) else "unresolved",
                "notes": r.boundary_note,
            }
        )

    extra = inv[~inv.well_node_id.isin({r["well_node_id"] for r in rows})]
    for r in extra.itertuples(index=False):
        rows.append(
            {
                "well_node_id": r.well_node_id,
                "oha_source_id": "",
                "owrd_report_or_pod_id": "",
                "pumping_group_id": "",
                "boundary_id": "",
                "mapping_status": "candidate_unresolved",
                "mapping_confidence": np.nan,
                "pumping_allocation_rule": "no_accepted_pumping_series",
                "huc12_is_not_aquifer_node": True,
                "identity_status": r.identity_status,
                "notes": r.notes,
            }
        )

    out = pd.DataFrame(rows)
    if out.duplicated(["well_node_id", "pumping_group_id", "boundary_id"]).any():
        raise ValueError("crosswalk many-to-many explosion")
    missing = set(out.well_node_id) - set(inv.well_node_id)
    if missing:
        raise ValueError(f"crosswalk nodes not in inventory: {missing}")
    return out


def build_pumping(xwalk: pd.DataFrame) -> pd.DataFrame:
    city = pd.read_csv(CITY_MODEL)
    direct = pd.read_csv(DIRECT_MONTHLY)
    meta = pd.read_csv(META_ANNUAL)

    city_rows = city.copy()
    city_rows["node_or_reporting_group_id"] = city_rows["model_source_key"].astype(str)
    city_rows["year_month"] = city_rows["calendar_month"].map(_year_month)
    city_rows["pump_m3"] = pd.to_numeric(city_rows["volume_m3"], errors="coerce")
    city_rows["boundary_id"] = BOUNDARY_CITY
    city_rows["measurement_or_reporting_method"] = np.where(
        city_rows["zero_reported_flag"].astype(str).str.lower().eq("true"),
        "owrd_reported_zero",
        np.where(
            city_rows["reported_flag"].astype(str).str.lower().eq("true"),
            "owrd_monthly_water_use",
            "owrd_month_present_value_missing",
        ),
    )
    city_rows["mapping_confidence"] = pd.to_numeric(city_rows["mapping_confidence"], errors="coerce")
    city_rows["source_provenance"] = (
        "data/processed/owrd/owrd_city_monthly_model_use.csv; accepted City/Prineville "
        "production groups only; combined PODs are not split across physical wells"
    )
    city_rows["provenance_class"] = "reported"

    direct_rows = direct.copy()
    direct_rows["node_or_reporting_group_id"] = "VITESSE:" + direct_rows["report_id"].astype(int).astype(str)
    direct_rows["year_month"] = direct_rows["calendar_month"].map(_year_month)
    direct_rows["pump_m3"] = pd.to_numeric(direct_rows["volume_m3"], errors="coerce")
    direct_rows["boundary_id"] = BOUNDARY_DIRECT
    method = direct_rows["measurement_method"].fillna("owrd_monthly_water_use").astype(str)
    direct_rows["measurement_or_reporting_method"] = np.where(
        direct_rows["zero_reported_flag"].astype(str).str.lower().eq("true"),
        "owrd_reported_zero; " + method,
        np.where(
            direct_rows["reported_flag"].astype(str).str.lower().eq("true"),
            method,
            "owrd_month_present_value_missing; " + method,
        ),
    )
    direct_rows["mapping_confidence"] = pd.to_numeric(direct_rows["confidence"], errors="coerce")
    direct_rows["source_provenance"] = (
        "data/processed/owrd/owrd_meta_direct_monthly_use.csv; Vitesse/Facebook direct "
        "POD; not total Meta campus withdrawal"
    )
    direct_rows["provenance_class"] = "reported"

    meta_keep = meta[meta["water_withdrawal_m3_reported"].notna()].copy()
    meta_rows = pd.DataFrame(
        {
            "node_or_reporting_group_id": "META_CAMPUS_ANNUAL",
            "year_month": meta_keep["year"].map(lambda y: f"{int(y):04d}-01"),
            "pump_m3": pd.to_numeric(meta_keep["water_withdrawal_m3_reported"], errors="coerce"),
            "boundary_id": BOUNDARY_META,
            "measurement_or_reporting_method": "annual_reported_not_monthly",
            "mapping_confidence": 1.0,
            "source_provenance": (
                "data/canonical/meta_prineville_annual.csv::water_withdrawal_m3_reported; "
                "calendar-year campus total placed on YYYY-01; not a monthly meter and not "
                "allocated to physical wells"
            ),
            "provenance_class": "reported",
        }
    )

    cols = [
        "node_or_reporting_group_id",
        "year_month",
        "pump_m3",
        "boundary_id",
        "measurement_or_reporting_method",
        "mapping_confidence",
        "source_provenance",
        "provenance_class",
    ]
    out = pd.concat(
        [city_rows[cols], direct_rows[cols], meta_rows[cols]],
        ignore_index=True,
    )

    city_sum = float(pd.to_numeric(city["volume_m3"], errors="coerce").fillna(0).sum())
    out_city = float(out.loc[out.boundary_id.eq(BOUNDARY_CITY), "pump_m3"].fillna(0).sum())
    if abs(city_sum - out_city) > 1e-6:
        raise ValueError(f"city pumping totals changed by crosswalk: {city_sum} vs {out_city}")

    direct_sum = float(pd.to_numeric(direct["volume_m3"], errors="coerce").fillna(0).sum())
    out_direct = float(out.loc[out.boundary_id.eq(BOUNDARY_DIRECT), "pump_m3"].fillna(0).sum())
    if abs(direct_sum - out_direct) > 1e-6:
        raise ValueError(f"direct POD pumping totals changed: {direct_sum} vs {out_direct}")

    if len(out.loc[out.boundary_id.eq(BOUNDARY_CITY)]) != len(city):
        raise ValueError("city pumping row count changed (join explosion)")
    if len(out.loc[out.boundary_id.eq(BOUNDARY_DIRECT)]) != len(direct):
        raise ValueError("direct pumping row count changed (join explosion)")

    combined = out["node_or_reporting_group_id"].astype(str).str.startswith("COMBINED_ACCEPTED:")
    if combined.any() and out.loc[combined, "node_or_reporting_group_id"].str.contains(r"^SRC-").any():
        raise ValueError("combined POD split onto physical wells")

    n_group = out.loc[out.boundary_id.eq(BOUNDARY_CITY), "node_or_reporting_group_id"].nunique()
    n_city_keys = city["model_source_key"].nunique()
    if n_group != n_city_keys:
        raise ValueError("city reporting-group cardinality changed")

    _ = xwalk
    return out.sort_values(["boundary_id", "node_or_reporting_group_id", "year_month"]).reset_index(drop=True)


def build_parameter_inventory(inv: pd.DataFrame, pdf_scan: pd.DataFrame) -> pd.DataFrame:
    named = _local_asr_named_pdfs()
    n_permits = int(len(_permit_pdfs()))
    catalog_missing = [
        r.source_file
        for r in pdf_scan.itertuples(index=False)
        if str(r.source_file).startswith("catalogued:")
        and str(r.status) == "catalogued_filename_not_found_under_data_raw"
    ]
    keyword_hits = pdf_scan[pdf_scan["keyword_hits"].astype(str).str.len().gt(0)]
    rows = [
        {
            "parameter": "additional_asr_storage_capacity",
            "value": 260.0,
            "lower_bound": np.nan,
            "upper_bound": np.nan,
            "unit": "million_gallons_per_year",
            "aquifer_location_or_well": "City of Prineville ASR project (application context)",
            "method": "grant_application_statement",
            "source_file": "SOURCE_INSTRUCTIONS.md; src/pipeline_report_catalog.py::OWRD_ASR_2020_APP",
            "source_page_table_section": (
                "secondary citation; catalogued PrinevilleASR_Application.pdf was not found "
                f"under data/raw (including permits_pdfs/; {n_permits} Crook County permit PDFs scanned)"
            ),
            "well_or_aquifer_identity": "City ASR project",
            "measurement_status": "reported_engineering_estimate",
            "provenance_class": "document_context",
            "notes": (
                "Secondary citation of the 2020 OWRD ASR grant application coverage note "
                "('260 MG/y additional storage'). Not a pumping-test measurement and not a "
                "calibrated storage coefficient. Local Crook County permit PDFs were scanned "
                "with machine-readable text extraction and did not contain this value."
            ),
        }
    ]
    for r in inv.itertuples(index=False):
        if pd.notna(r.well_depth):
            rows.append(
                {
                    "parameter": "well_depth",
                    "value": float(r.well_depth),
                    "lower_bound": np.nan,
                    "upper_bound": np.nan,
                    "unit": "ft",
                    "aquifer_location_or_well": r.source_name,
                    "method": "gwis_well_log_max_depth",
                    "source_file": "data/raw/gwis_data_new/",
                    "source_page_table_section": "gw_site.max_depth / gw_well_construction_history",
                    "well_or_aquifer_identity": r.well_node_id,
                    "measurement_status": "reported_measured_gwis",
                    "provenance_class": "reported_measured_gwis",
                    "notes": f"gwis_site_id={r.gwis_site_id}; gwis_logid={r.gwis_logid}",
                }
            )
        if pd.notna(r.screen_top) or pd.notna(r.screen_bottom):
            rows.append(
                {
                    "parameter": "open_interval",
                    "value": np.nan,
                    "lower_bound": r.screen_top,
                    "upper_bound": r.screen_bottom,
                    "unit": "ft_below_land_surface",
                    "aquifer_location_or_well": r.source_name,
                    "method": "gwis_well_construction_open_interval",
                    "source_file": "data/raw/gwis_data_new/",
                    "source_page_table_section": "gw_well_construction.feature_type=Open Interval",
                    "well_or_aquifer_identity": r.well_node_id,
                    "measurement_status": "reported_measured_gwis",
                    "provenance_class": "reported_measured_gwis",
                    "notes": (
                        "Open-interval construction, not a named screen. Multiple intervals "
                        "collapsed to min start / max end. Not aquifer thickness."
                    ),
                }
            )
        if str(r.aquifer_geologic_unit).strip():
            rows.append(
                {
                    "parameter": "aquifer_geologic_unit",
                    "value": np.nan,
                    "lower_bound": np.nan,
                    "upper_bound": np.nan,
                    "unit": "",
                    "aquifer_location_or_well": r.source_name,
                    "method": "gwis_site_or_construction_history",
                    "source_file": "data/raw/gwis_data_new/",
                    "source_page_table_section": "gw_site.aquifer / construction_history.aquifer_description",
                    "well_or_aquifer_identity": r.well_node_id,
                    "measurement_status": "reported_measured_gwis",
                    "provenance_class": "reported_measured_gwis",
                    "notes": str(r.aquifer_geologic_unit),
                }
            )

    unresolved_note = (
        "No defensible numeric extraction from local Crook County permit PDFs "
        f"(n={n_permits}; keyword numeric recovery empty). "
        f"Catalogued ASR application/attachments present locally by filename: {named if named else 'none'}. "
        f"Still missing by catalogued filename: {catalog_missing if catalog_missing else 'none'}. "
        f"Keyword-only hits (not converted to parameters): {len(keyword_hits)}. "
        "Transmissivity, storativity, specific yield, hydraulic conductivity, pumping-test "
        "drawdown/recovery, and ASR injection/recovery quantities remain unresolved. Values are not invented."
    )
    for name in PARAM_SEARCH_NAMES:
        rows.append(
            {
                "parameter": name,
                "value": np.nan,
                "lower_bound": np.nan,
                "upper_bound": np.nan,
                "unit": "",
                "aquifer_location_or_well": "",
                "method": "repository_search_unresolved",
                "source_file": "data/raw/permits_pdfs/; catalogued OWRD_ASR_2020_APP / OWRD_ASR_2020_ATTACH",
                "source_page_table_section": "unresolved",
                "well_or_aquifer_identity": "",
                "measurement_status": "unresolved",
                "provenance_class": "unresolved",
                "notes": unresolved_note,
            }
        )
    return pd.DataFrame(rows)


def build_level_observations(inv: pd.DataFrame, bundle: dict[str, pd.DataFrame]) -> pd.DataFrame:
    levels = bundle["levels"]
    sites = bundle["sites"]
    if levels.empty:
        return pd.DataFrame(
            columns=[
                "observation_key",
                "well_id",
                "well_node_id",
                "gwis_site_id",
                "gwis_logid",
                "measurement_date",
                "measurement_datetime",
                "water_level_below_land_surface",
                "water_surface_elevation_or_head",
                "reference_datum",
                "measurement_method",
                "quality_flag",
                "observation_type",
                "source_page_figure",
                "digitization_uncertainty",
                "source_provenance",
                "provenance_class",
                "notes",
            ]
        )

    site_idx = sites.set_index("gw_site_id", drop=False)
    node_by_site = (
        inv.loc[inv.gwis_site_id.astype(str).str.len().gt(0)]
        .set_index("gwis_site_id")["well_node_id"]
        .to_dict()
    )
    name_by_node = inv.set_index("well_node_id")["source_name"].to_dict()

    bls = pd.to_numeric(levels["waterlevel_ft_below_land_surface"], errors="coerce")
    amsl = pd.to_numeric(levels["waterlevel_ft_above_mean_sea_level"], errors="coerce")
    dt = pd.to_datetime(levels["measured_datetime"], errors="coerce")
    rows = []
    for i, r in levels.iterrows():
        site_id = str(r["gw_site_id"])
        site = site_idx.loc[site_id] if site_id in site_idx.index else None
        datum = ""
        if site is not None and pd.notna(site.get("elevation_datum", pd.NA)):
            datum = str(site.get("elevation_datum"))
        node = node_by_site.get(site_id, f"GWIS:{site_id}")
        head = amsl.loc[i] if pd.notna(amsl.loc[i]) else np.nan
        if pd.notna(head) and not datum:
            # Preserve AMSL as a source field only when GWIS also documents a datum.
            head = np.nan
        notes = (
            "GWIS measured water level. AMSL is the GWIS-reported water-surface elevation "
            "with the site elevation datum; absolute head is not recomputed from BLS+LSD."
        )
        if datum:
            notes += f" Datum={datum}."
        rows.append(
            {
                "observation_key": str(r["gw_measured_water_level_id"]),
                "well_id": name_by_node.get(node, r.get("gw_logid", "")),
                "well_node_id": node,
                "gwis_site_id": site_id,
                "gwis_logid": r.get("gw_logid", ""),
                "measurement_date": dt.loc[i].date().isoformat() if pd.notna(dt.loc[i]) else "",
                "measurement_datetime": dt.loc[i].isoformat() if pd.notna(dt.loc[i]) else "",
                "water_level_below_land_surface": bls.loc[i],
                "water_surface_elevation_or_head": head,
                "reference_datum": datum,
                "land_surface_elevation": pd.to_numeric(
                    r.get("land_surface_elevation"), errors="coerce"
                ),
                "measurement_method": r.get("method_of_water_level_measurement", ""),
                "measurement_status": r.get("measurement_status_desc", ""),
                "source_agency": r.get("measurement_source_organization_desc", "")
                or r.get("measurement_source_owrd_desc", ""),
                "quality_flag": r.get("measurement_status_desc", ""),
                "observation_type": "gwis_measured_water_level",
                "source_page_figure": r.get("source_files", ""),
                "digitization_uncertainty": "",
                "source_raw_files": r.get("source_files", ""),
                "source_provenance": (
                    "OWRD GWIS gw_measured_water_level; duplicate raw exports collapsed by "
                    "gw_measured_water_level_id with all source filenames retained"
                ),
                "provenance_class": "reported_measured_gwis",
                "notes": notes,
            }
        )
    out = pd.DataFrame(rows)
    if out["observation_key"].duplicated().any():
        raise ValueError("processed GWIS observation key is not unique")
    has_head = out["water_surface_elevation_or_head"].notna()
    if has_head.any() and out.loc[has_head, "reference_datum"].astype(str).str.strip().eq("").any():
        raise ValueError("absolute head present without datum")
    return out


def _feasibility_class(
    inv: pd.DataFrame,
    pump: pd.DataFrame,
    params: pd.DataFrame,
    levels: pd.DataFrame,
) -> dict:
    numeric = levels[pd.to_numeric(levels["water_level_below_land_surface"], errors="coerce").notna()].copy()
    n_wells = int(levels["gwis_site_id"].nunique()) if "gwis_site_id" in levels.columns and not levels.empty else 0
    n_numeric = int(len(numeric))
    n_headlike = int(pd.to_numeric(levels.get("water_surface_elevation_or_head"), errors="coerce").notna().sum())
    n_coord = int(inv.latitude.notna().sum())
    n_aq = int(inv["aquifer_geologic_unit"].astype(str).str.strip().ne("").sum())
    recovered = params[params["value"].notna() | params["lower_bound"].notna() | params["notes"].astype(str).str.len().gt(0)]
    n_gwis_params = int(params.provenance_class.eq("reported_measured_gwis").sum())
    n_unresolved_params = int(params.provenance_class.eq("unresolved").sum())
    confirmed = inv[inv.identity_status.eq("confirmed_official_id")]
    candidates = inv[inv.identity_status.eq("candidate_unresolved")]

    numeric["year"] = pd.to_datetime(numeric["measurement_datetime"], errors="coerce").dt.year
    coverage = (
        numeric.groupby(["well_node_id", "year"]).size().reset_index(name="n_obs")
        if not numeric.empty
        else pd.DataFrame(columns=["well_node_id", "year", "n_obs"])
    )

    pump = pump.copy()
    pump["year"] = pd.to_datetime(pump["year_month"] + "-01", errors="coerce").dt.year
    pump_years = set(pump.loc[pump.pump_m3.notna(), "year"].dropna().astype(int))
    head_years = set(numeric["year"].dropna().astype(int))
    overlap_years = sorted(pump_years & head_years)
    overlap_span = f"{overlap_years[0]}-{overlap_years[-1]}" if overlap_years else "none"

    one_to_one = [
        n
        for n in confirmed["well_node_id"].tolist()
        if n not in {"SRC-GA", "SRC-GB"}
    ]

    identity_strength = (
        "Heliport (SRC-GC) and Millican (SRC-JA) match GWIS on well tags L114180 / L108444. "
        "Airport #1/#2 match L105198 / L89932 but OWRD pumping remains COMBINED_ACCEPTED:SRC-GA+SRC-GB. "
        "Vitesse GWIS well tag L105254 / CROO0053878 maps only to report 64846. "
        f"Reports {sorted(UNMAPPED_VITESSE_REPORTS)} are not mapped. "
        f"{len(candidates)} GWIS wells remain candidate_unresolved."
    )

    # Class A requires overlapping pumping and heads sufficient for reduced-order
    # estimation AND defensible physical-well mapping. Combined Airport POD plus
    # missing T/S/Sy keep this at B even with hundreds of heads.
    if n_numeric == 0:
        klass = "C"
        label = "too sparse for estimation; scenario/prior model only"
    else:
        klass = "B"
        label = (
            "measured groundwater heads exist as calibration/validation targets, "
            "but parameter, identity, or overlap limitations prevent credible full estimation"
        )
    reason = (
        f"{n_wells} unique GWIS wells; {n_numeric} numeric BLS observations; "
        f"{n_headlike} GWIS-reported water-surface elevations with documented datum. "
        f"Official coordinates on {n_coord} inventory nodes; aquifer unit populated for {n_aq}. "
        f"Pumping↔head calendar-year overlap: {overlap_span}. "
        f"{identity_strength} "
        f"GWIS-recovered construction/aquifer parameters: {n_gwis_params}. "
        f"Unresolved hydrogeologic parameters (T, K, S, Sy, pumping tests, ASR rates): {n_unresolved_params}. "
        "No reduced-order groundwater dynamics are fitted. Mixed NGVD1929/NAVD1988 datums are not converted."
    )
    return {
        "feasibility_class": klass,
        "label": label,
        "n_unique_gwis_wells": n_wells,
        "n_numeric_level_observations": n_numeric,
        "n_water_surface_elevation_or_headlike": n_headlike,
        "n_wells_with_official_coordinates": n_coord,
        "n_wells_with_aquifer_unit": n_aq,
        "n_confirmed_official_id_matches": int(len(confirmed)),
        "n_candidate_unresolved": int(len(candidates)),
        "n_gwis_construction_or_aquifer_parameters": n_gwis_params,
        "n_unresolved_parameters": n_unresolved_params,
        "n_pumping_head_overlap_years": len(overlap_years),
        "pumping_head_overlap_years": ",".join(str(y) for y in overlap_years),
        "one_to_one_pumping_nodes": ",".join(one_to_one),
        "reason": reason,
        "coverage": coverage,
        "recovered": recovered,
    }


def write_qa(
    inv: pd.DataFrame,
    xwalk: pd.DataFrame,
    pump: pd.DataFrame,
    params: pd.DataFrame,
    levels: pd.DataFrame,
    feas: dict,
    file_inv: pd.DataFrame,
) -> pd.DataFrame:
    n_coord = int(inv.latitude.notna().sum())
    n_numeric_head = int(pd.to_numeric(levels["water_level_below_land_surface"], errors="coerce").notna().sum())
    n_measured_params = int(params.provenance_class.eq("measured_pumping_test").sum())
    n_files = int(len(file_inv))
    n_unique = int(file_inv["sha256"].nunique()) if not file_inv.empty else 0
    extra_dups = n_files - n_unique
    rows = [
        ("n_gwis_raw_txt_files", n_files, "PASS", "local GWIS text exports"),
        ("n_gwis_unique_file_hashes", n_unique, "PASS", "byte-identical copies collapsed for uniqueness"),
        ("n_gwis_duplicate_extra_files", extra_dups, "PASS", "exact duplicate exports retained only in provenance"),
        ("n_well_nodes", len(inv), "PASS", "unique physical/source wells in inventory"),
        ("n_with_official_coordinates", n_coord, "PASS", "official lat/lon only; unresolved remain blank"),
        ("n_unresolved_coordinates", int(inv.latitude.isna().sum()), "PASS", "no inferred coordinates"),
        ("n_huc12_as_aquifer_node", 0, "PASS", "HUC12 stored as location attribute only"),
        ("n_city_pumping_rows", int(pump.boundary_id.eq(BOUNDARY_CITY).sum()), "PASS", "matches accepted OWRD model-use rows"),
        ("n_direct_pumping_rows", int(pump.boundary_id.eq(BOUNDARY_DIRECT).sum()), "PASS", "matches direct POD monthly rows"),
        ("n_meta_annual_pumping_rows", int(pump.boundary_id.eq(BOUNDARY_META).sum()), "PASS", "years with reported Meta water"),
        ("n_unique_gwis_wells", feas["n_unique_gwis_wells"], "PASS", "deduplicated GWIS sites"),
        ("n_numeric_groundwater_level_obs", n_numeric_head, "PASS" if n_numeric_head > 0 else "WARN", "time-indexed GWIS BLS"),
        ("n_headlike_amsl_with_datum", feas["n_water_surface_elevation_or_headlike"], "PASS", "GWIS AMSL preserved with datum"),
        ("n_measured_pumping_test_parameters", n_measured_params, "PASS", "no fabricated pumping-test values"),
        ("n_crosswalk_rows", len(xwalk), "PASS", "inventory nodes including unmatched GWIS candidates"),
        (
            "feasibility_class",
            feas["feasibility_class"],
            "PASS",
            feas["label"],
        ),
    ]
    return pd.DataFrame(rows, columns=["item", "value", "status", "detail"])


def write_diagnostics(
    inv: pd.DataFrame,
    pump: pd.DataFrame,
    levels: pd.DataFrame,
    feas: dict,
) -> None:
    mapped = inv[inv.latitude.notna() & inv.longitude.notna()].copy()
    fig, ax = plt.subplots(figsize=(8.2, 6.4))
    if mapped.empty:
        ax.text(0.5, 0.5, "No official coordinates", ha="center")
    else:
        for role, sub in mapped.groupby("role"):
            ax.scatter(sub.longitude, sub.latitude, s=36, label=role, alpha=0.85)
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.legend(fontsize=8, loc="best")
    n_unres = int(inv.latitude.isna().sum())
    ax.set_title(
        f"Groundwater well/source map (official coordinates only; {n_unres} unresolved omitted)",
        loc="left",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(OUT_GW / "well_source_map.png", dpi=140)
    plt.close(fig)

    years = list(range(2011, 2025))
    wells = inv["well_node_id"].tolist()
    numeric = levels.copy()
    numeric["bls"] = pd.to_numeric(numeric["water_level_below_land_surface"], errors="coerce")
    numeric["dt"] = pd.to_datetime(numeric["measurement_datetime"], errors="coerce")
    numeric = numeric[numeric["bls"].notna() & numeric["dt"].notna()]
    counts = (
        numeric.assign(year=numeric["dt"].dt.year)
        .groupby(["well_node_id", "year"])
        .size()
        .unstack(fill_value=0)
        if not numeric.empty
        else pd.DataFrame()
    )
    Z = np.zeros((len(wells), len(years)))
    for i, w in enumerate(wells):
        for j, y in enumerate(years):
            if not counts.empty and w in counts.index and y in counts.columns:
                Z[i, j] = float(counts.loc[w, y])
    fig, ax = plt.subplots(figsize=(11.5, max(5.5, 0.18 * len(wells) + 1.8)))
    im = ax.imshow(Z, aspect="auto", cmap="Blues", vmin=0)
    ax.set_xticks(range(len(years)))
    ax.set_xticklabels(years, fontsize=8)
    ax.set_yticks(range(len(wells)))
    ax.set_yticklabels(wells, fontsize=6)
    ax.set_title("Groundwater-level observation coverage (numeric GWIS BLS counts)", loc="left")
    ax.set_xlabel("Calendar year")
    fig.colorbar(im, ax=ax, fraction=0.02, pad=0.02, label="n observations")
    fig.tight_layout()
    fig.savefig(OUT_GW / "groundwater_observation_coverage_matrix.png", dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11.0, 5.4))
    plotted = False
    for node, g in numeric.groupby("well_node_id"):
        ax.plot(g["dt"], g["bls"], lw=0.9, marker="o", ms=2, label=str(node)[:28])
        plotted = True
    ax.invert_yaxis()
    ax.set_ylabel("water level below land surface (ft)")
    ax.set_title("GWIS measured groundwater levels (not a fitted head model)", loc="left", fontsize=10)
    if plotted:
        ax.legend(fontsize=6, ncol=2, loc="best")
    fig.tight_layout()
    fig.savefig(OUT_GW / "groundwater_hydrographs.png", dpi=140)
    plt.close(fig)

    dens_rows = []
    for w in wells:
        for y in years:
            n = 0
            if not counts.empty and w in counts.index and y in counts.columns:
                n = int(counts.loc[w, y])
            dens_rows.append({"well_node_id": w, "year": y, "n_numeric_observations": n})
    pd.DataFrame(dens_rows).to_csv(OUT_GW / "observation_density_by_well_year.csv", index=False)

    compat = inv[
        [
            "well_node_id",
            "source_name",
            "role",
            "well_depth",
            "screen_top",
            "screen_bottom",
            "aquifer_geologic_unit",
            "huc12",
            "identity_status",
        ]
    ].copy()
    has_unit = compat["aquifer_geologic_unit"].astype(str).str.strip().ne("")
    compat["depth_aquifer_compatibility"] = np.where(has_unit, "gwis_unit_as_reported", "unknown")
    compat["compatibility_reason"] = np.where(
        has_unit,
        "Aquifer/geologic unit copied from GWIS; HUC12 is not used as an aquifer assignment.",
        "No aquifer unit in GWIS/site history for this node; HUC12 is not used as an aquifer assignment.",
    )
    compat.to_csv(OUT_GW / "well_depth_aquifer_compatibility.csv", index=False)

    def _pump_plot(sub: pd.DataFrame, title: str, path: Path) -> None:
        fig, ax = plt.subplots(figsize=(10.5, 4.6))
        plotted = False
        for node, g in sub.groupby("node_or_reporting_group_id"):
            gg = g.dropna(subset=["pump_m3"]).copy()
            if gg.empty:
                continue
            gg["t"] = pd.to_datetime(gg["year_month"] + "-01")
            ax.plot(gg["t"], gg["pump_m3"], lw=1.1, label=str(node)[:40])
            plotted = True
        ax.set_ylabel("pump_m3")
        ax.set_title(title, loc="left", fontsize=10)
        if plotted:
            ax.legend(fontsize=7, ncol=2, loc="upper left")
        fig.tight_layout()
        fig.savefig(path, dpi=140)
        plt.close(fig)

    _pump_plot(
        pump[pump.boundary_id.eq(BOUNDARY_CITY)],
        "Accepted City/Prineville OWRD production (combined groups not split)",
        OUT_GW / "pumping_history_city.png",
    )
    _pump_plot(
        pump[pump.boundary_id.eq(BOUNDARY_DIRECT)],
        "Vitesse/Facebook direct POD pumping (not total Meta withdrawal)",
        OUT_GW / "pumping_history_direct_pod.png",
    )
    meta_p = pump[pump.boundary_id.eq(BOUNDARY_META)].copy()
    fig, ax = plt.subplots(figsize=(10.5, 3.8))
    if not meta_p.empty:
        meta_p["year"] = meta_p["year_month"].str.slice(0, 4).astype(int)
        ax.bar(meta_p["year"], meta_p["pump_m3"], color="#4C78A8")
    ax.set_title("Meta annual campus withdrawal (annual total on YYYY-01; not monthly meters)", loc="left")
    ax.set_ylabel("m3 / year")
    fig.tight_layout()
    fig.savefig(OUT_GW / "pumping_history_meta_annual.png", dpi=140)
    plt.close(fig)

    one_to_one = [n for n in ("SRC-GC", "SRC-JA", "VITESSE:64846") if n in set(numeric.well_node_id)]
    fig, axes = plt.subplots(max(len(one_to_one), 1), 1, figsize=(10.8, 3.2 * max(len(one_to_one), 1)), sharex=True)
    if max(len(one_to_one), 1) == 1:
        axes = [axes]
    if not one_to_one:
        axes[0].text(
            0.02,
            0.5,
            "No 1:1 pumping–head pairs plotted. Combined Airport POD is not split.",
            transform=axes[0].transAxes,
        )
    for ax, node in zip(axes, one_to_one):
        heads = numeric[numeric.well_node_id.eq(node)]
        ax.plot(heads["dt"], heads["bls"], color="#1d4ed8", lw=0.9, label="GWIS BLS (ft)")
        ax.set_ylabel("BLS ft")
        ax.invert_yaxis()
        ax2 = ax.twinx()
        psub = pump[pump.node_or_reporting_group_id.eq(node)].dropna(subset=["pump_m3"]).copy()
        if not psub.empty:
            psub["t"] = pd.to_datetime(psub["year_month"] + "-01")
            ax2.plot(psub["t"], psub["pump_m3"], color="#b45309", lw=0.9, label="OWRD pump_m3")
            ax2.set_ylabel("pump_m3")
        ax.set_title(f"{node} — alignment only; not a fitted groundwater model", loc="left", fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT_GW / "pumping_vs_head_alignment.png", dpi=140)
    plt.close(fig)

    feas_row = {k: v for k, v in feas.items() if k not in {"coverage", "recovered"}}
    pd.DataFrame([feas_row]).to_csv(FEAS_OUT, index=False)


def run() -> dict[str, Path]:
    _mkdirs()
    bundle = compile_gwis_bundle()
    bundle["file_inventory"].to_csv(GWIS_HASH_OUT, index=False)
    pdf_scan = scan_local_pdfs_for_hydrogeology()
    pdf_scan.to_csv(PDF_SCAN_OUT, index=False)

    inv = build_well_inventory(bundle)
    xwalk = build_source_crosswalk(inv)
    pump = build_pumping(xwalk)
    params = build_parameter_inventory(inv, pdf_scan)
    levels = build_level_observations(inv, bundle)
    feas = _feasibility_class(inv, pump, params, levels)
    qa = write_qa(inv, xwalk, pump, params, levels, feas, bundle["file_inventory"])
    write_diagnostics(inv, pump, levels, feas)

    inv.to_csv(INV_OUT, index=False)
    xwalk.to_csv(XWALK_OUT, index=False)
    params.to_csv(PARAM_OUT, index=False)
    pump.to_csv(PUMP_OUT, index=False)
    levels.to_csv(LEVEL_OUT, index=False)
    qa.to_csv(QA_OUT, index=False)
    return {
        "inventory": INV_OUT,
        "crosswalk": XWALK_OUT,
        "parameters": PARAM_OUT,
        "pumping": PUMP_OUT,
        "levels": LEVEL_OUT,
        "qa": QA_OUT,
        "feasibility": FEAS_OUT,
        "gwis_hashes": GWIS_HASH_OUT,
        "pdf_scan": PDF_SCAN_OUT,
    }


if __name__ == "__main__":
    paths = run()
    for k, p in paths.items():
        print(f"{k}: {p}")
