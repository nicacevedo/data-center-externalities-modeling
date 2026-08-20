"""Groundwater / hydrogeology observation scaffold from existing repository data.

Does not fit a groundwater dynamics model, infer missing heads, split combined
OWRD reporting groups, or treat HUC12 as an aquifer/network node.
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
from usgs_nwaa_config import pad_huc12

ROOT = Path(__file__).resolve().parents[1]
CANON = ROOT / "data" / "canonical"
CANON_GW = CANON / "groundwater"
PROC_GW = ROOT / "data" / "processed" / "groundwater"
QC = ROOT / "outputs" / "qc"
OUT_GW = ROOT / "outputs" / "groundwater"

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

PARAM_SEARCH_NAMES = [
    "transmissivity",
    "hydraulic_conductivity",
    "storativity",
    "specific_yield",
    "aquifer_thickness",
    "well_depth",
    "screen_interval",
    "pumping_test_result",
    "drawdown_recovery",
    "aquifer_geologic_unit",
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


def _local_asr_pdfs() -> list[str]:
    hits: list[Path] = []
    for folder in (
        ROOT / "data" / "raw",
        ROOT / "data" / "canonical",
        ROOT / "data" / "manual",
        ROOT / "docs",
    ):
        if not folder.exists():
            continue
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


def build_well_inventory() -> pd.DataFrame:
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
                "notes": (
                    f"{r.boundary_note} Official coordinates are not in the repository; "
                    "TRSQQ/bearing text was not converted to a point."
                ),
            }
        )

    inv = pd.DataFrame(rows)
    if not inv["well_node_id"].is_unique:
        raise ValueError("well_node_id must be unique")
    if not inv["role"].isin(ROLES).all():
        raise ValueError(f"unexpected role values: {sorted(set(inv.role) - set(ROLES))}")
    # Never infer coordinates for unresolved wells.
    unresolved = inv["mapping_method"].eq("unresolved_missing_coordinates")
    if inv.loc[unresolved, ["latitude", "longitude"]].notna().any().any():
        raise ValueError("unresolved wells must not have inferred coordinates")
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
                "notes": (
                    xr.production_handling
                    if xr is not None and pd.notna(xr.production_handling)
                    else ""
                ),
            }
        )

    for r in direct.itertuples(index=False):
        node = f"VITESSE:{int(r.report_id)}"
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
                "notes": r.boundary_note,
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

    # Combined groups must remain combined keys, not physical well IDs.
    combined = out["node_or_reporting_group_id"].astype(str).str.startswith("COMBINED_ACCEPTED:")
    if combined.any() and out.loc[combined, "node_or_reporting_group_id"].str.contains(r"^SRC-").any():
        raise ValueError("combined POD split onto physical wells")

    n_group = out.loc[out.boundary_id.eq(BOUNDARY_CITY), "node_or_reporting_group_id"].nunique()
    n_city_keys = city["model_source_key"].nunique()
    if n_group != n_city_keys:
        raise ValueError("city reporting-group cardinality changed")

    _ = xwalk  # crosswalk is for identity, not a pumping join
    return out.sort_values(["boundary_id", "node_or_reporting_group_id", "year_month"]).reset_index(drop=True)


def build_parameter_inventory() -> pd.DataFrame:
    pdfs = _local_asr_pdfs()
    template_empty = True
    if ASR_TEMPLATE.exists():
        raw = ASR_TEMPLATE.read_text(encoding="utf-8").strip().splitlines()
        template_empty = len(raw) <= 1

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
            "source_page_table_section": "unverified; 2020 application PDF is not present locally",
            "provenance_class": "reported_engineering_estimate",
            "notes": (
                "Secondary citation of the 2020 OWRD ASR grant application coverage note "
                "('260 MG/y additional storage'). Not a pumping-test measurement and not a "
                "calibrated storage coefficient. PDF was not re-read because it is not in the repository."
            ),
        }
    ]
    unresolved_note = (
        "No machine-readable hydrogeologic table is in the repository. "
        f"Local ASR/hydrogeology PDFs found: {pdfs if pdfs else 'none'}. "
        f"asr_monthly.csv template is {'header-only' if template_empty else 'populated'}. "
        "Numeric extraction from 2018 feasibility / 2020 attachments is unresolved; "
        "values are not invented."
    )
    for name in PARAM_SEARCH_NAMES:
        if name == "additional_asr_storage_capacity":
            continue
        rows.append(
            {
                "parameter": name,
                "value": np.nan,
                "lower_bound": np.nan,
                "upper_bound": np.nan,
                "unit": "",
                "aquifer_location_or_well": "",
                "method": "repository_search_unresolved",
                "source_file": (
                    "OWRD_ASR_2020_APP / OWRD_ASR_2020_ATTACH (paths not found locally); "
                    "data/manual_templates/asr_monthly.csv"
                ),
                "source_page_table_section": "unresolved",
                "provenance_class": "unknown",
                "notes": unresolved_note,
            }
        )
    return pd.DataFrame(rows)


def build_level_observations() -> pd.DataFrame:
    """Register hydrograph evidence; do not invent time-indexed heads."""
    rows = [
        {
            "well_id": "Heliport Well (Airport Well #4 / SRC-GC)",
            "well_node_id": "SRC-GC",
            "measurement_date": "",
            "water_level_below_land_surface": np.nan,
            "water_surface_elevation_or_head": np.nan,
            "reference_datum": "",
            "measurement_method": "",
            "quality_flag": "numeric_extraction_unresolved",
            "observation_type": "unresolved_document_hydrograph",
            "source_page_figure": "OWRD_ASR_2020_ATTACH / 2018 feasibility hydrographs (PDF not local)",
            "digitization_uncertainty": "",
            "source_provenance": (
                "SOURCE_INSTRUCTIONS.md §7; pipeline_report_catalog OWRD_ASR_2020_ATTACH. "
                "Documents mention Heliport/Millican hydrographs; no tabulated series in the repo."
            ),
            "provenance_class": "unavailable",
            "notes": "Do not compute absolute hydraulic head. Datum/elevation unknown.",
        },
        {
            "well_id": "Millican Well (Airport Well #3 / SRC-JA)",
            "well_node_id": "SRC-JA",
            "measurement_date": "",
            "water_level_below_land_surface": np.nan,
            "water_surface_elevation_or_head": np.nan,
            "reference_datum": "",
            "measurement_method": "",
            "quality_flag": "numeric_extraction_unresolved",
            "observation_type": "unresolved_document_hydrograph",
            "source_page_figure": "OWRD_ASR_2020_ATTACH / 2018 feasibility hydrographs (PDF not local)",
            "digitization_uncertainty": "",
            "source_provenance": (
                "SOURCE_INSTRUCTIONS.md §7; pipeline_report_catalog OWRD_ASR_2020_ATTACH. "
                "Documents mention Heliport/Millican hydrographs; no tabulated series in the repo."
            ),
            "provenance_class": "unavailable",
            "notes": "Do not compute absolute hydraulic head. Datum/elevation unknown.",
        },
    ]
    out = pd.DataFrame(rows)
    if out["water_surface_elevation_or_head"].notna().any():
        raise ValueError("absolute head present without datum")
    return out


def write_qa(
    inv: pd.DataFrame,
    xwalk: pd.DataFrame,
    pump: pd.DataFrame,
    params: pd.DataFrame,
    levels: pd.DataFrame,
) -> pd.DataFrame:
    n_coord = int(inv.latitude.notna().sum())
    n_numeric_head = int(
        levels["water_level_below_land_surface"].notna().sum()
        + levels["water_surface_elevation_or_head"].notna().sum()
    )
    n_measured_params = int(params.provenance_class.eq("measured_pumping_test").sum())
    rows = [
        ("n_well_nodes", len(inv), "PASS", "unique physical/source wells in inventory"),
        ("n_with_official_coordinates", n_coord, "PASS", "official lat/lon only; unresolved remain blank"),
        ("n_unresolved_coordinates", int(inv.latitude.isna().sum()), "PASS", "no inferred coordinates"),
        ("n_huc12_as_aquifer_node", 0, "PASS", "HUC12 stored as location attribute only"),
        ("n_city_pumping_rows", int(pump.boundary_id.eq(BOUNDARY_CITY).sum()), "PASS", "matches accepted OWRD model-use rows"),
        ("n_direct_pumping_rows", int(pump.boundary_id.eq(BOUNDARY_DIRECT).sum()), "PASS", "matches direct POD monthly rows"),
        ("n_meta_annual_pumping_rows", int(pump.boundary_id.eq(BOUNDARY_META).sum()), "PASS", "years with reported Meta water"),
        ("n_numeric_groundwater_level_obs", n_numeric_head, "PASS" if n_numeric_head == 0 else "WARN", "time-indexed heads recovered"),
        ("n_unresolved_hydrograph_registrations", len(levels), "PASS", "document hydrographs registered, not digitized"),
        ("n_measured_pumping_test_parameters", n_measured_params, "PASS", "no fabricated pumping-test values"),
        ("n_crosswalk_rows", len(xwalk), "PASS", "one row per well node"),
        (
            "feasibility_class",
            "C",
            "PASS",
            "too sparse for estimation; scenario/prior model only (no numeric heads, no aquifer parameters from tests)",
        ),
    ]
    qa = pd.DataFrame(rows, columns=["item", "value", "status", "detail"])
    return qa


def _placeholder_figure(path: Path, title: str, body: str) -> None:
    fig, ax = plt.subplots(figsize=(9.5, 4.2))
    ax.axis("off")
    ax.set_title(title, loc="left")
    ax.text(0.02, 0.55, body, transform=ax.transAxes, va="center", wrap=True, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def write_diagnostics(inv: pd.DataFrame, pump: pd.DataFrame, levels: pd.DataFrame) -> None:
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
    Z = np.full((len(wells), len(years)), np.nan)
    fig, ax = plt.subplots(figsize=(11.5, max(5.5, 0.18 * len(wells) + 1.8)))
    ax.imshow(np.zeros_like(Z), aspect="auto", cmap="Greys", vmin=0, vmax=1, alpha=0.15)
    ax.set_xticks(range(len(years)))
    ax.set_xticklabels(years, fontsize=8)
    ax.set_yticks(range(len(wells)))
    ax.set_yticklabels(wells, fontsize=6)
    ax.set_title("Groundwater-level observation coverage (numeric heads: none recovered)", loc="left")
    ax.set_xlabel("Calendar year")
    fig.tight_layout()
    fig.savefig(OUT_GW / "groundwater_observation_coverage_matrix.png", dpi=140)
    plt.close(fig)

    _placeholder_figure(
        OUT_GW / "groundwater_hydrographs.png",
        "Hydrographs — numeric extraction unresolved",
        "No time-indexed groundwater-level observations were recovered from repository files.\n"
        "ASR/feasibility hydrographs are mentioned for Heliport and Millican wells in the 2018/2020\n"
        "OWRD ASR attachments, but those PDFs are not present locally and were not digitized.",
    )

    dens = pd.DataFrame(
        [{"well_node_id": w, "year": y, "n_numeric_observations": 0} for w in wells for y in years]
    )
    dens.to_csv(OUT_GW / "observation_density_by_well_year.csv", index=False)

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
        ]
    ].copy()
    compat["depth_aquifer_compatibility"] = "unknown"
    compat["compatibility_reason"] = (
        "No well depth, screen interval, or aquifer unit is present in repository inventories; "
        "HUC12 is not used as an aquifer assignment."
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

    n_head = int(levels["water_level_below_land_surface"].notna().sum())
    _placeholder_figure(
        OUT_GW / "pumping_vs_head_alignment.png",
        "Pumping vs groundwater level — not plotted",
        "No physically defensible pumping–head linkage exists: there are "
        f"{n_head} numeric head observations in the repository scaffold.\n"
        "Lag/correlation diagnostics were not computed. This is not a causal statement.",
    )

    feas = pd.DataFrame(
        [
            {
                "feasibility_class": "C",
                "label": "too sparse for estimation; scenario/prior model only",
                "n_numeric_head_observations": n_head,
                "n_wells_with_official_coordinates": int(inv.latitude.notna().sum()),
                "n_measured_pumping_tests": 0,
                "reason": (
                    "No time-indexed groundwater levels were recovered from repository files. "
                    "ASR/feasibility hydrographs are cited in uncopied 2018/2020 PDFs and remain "
                    "numerically unresolved. Well depth, screen interval, transmissivity, "
                    "storativity, and aquifer unit are unavailable except a secondary 260 MG/y "
                    "ASR storage-capacity application statement. Pumping exists at City reporting "
                    "groups and Vitesse PODs, but pumping without heads cannot identify a "
                    "reduced-order dynamic groundwater model. Class A would require a usable "
                    "head network overlapping pumping; class B would require at least sparse "
                    "heads as validation targets."
                ),
            }
        ]
    )
    feas.to_csv(FEAS_OUT, index=False)


def run() -> dict[str, Path]:
    _mkdirs()
    inv = build_well_inventory()
    xwalk = build_source_crosswalk(inv)
    pump = build_pumping(xwalk)
    params = build_parameter_inventory()
    levels = build_level_observations()
    qa = write_qa(inv, xwalk, pump, params, levels)
    write_diagnostics(inv, pump, levels)

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
    }


if __name__ == "__main__":
    paths = run()
    for k, p in paths.items():
        print(f"{k}: {p}")
