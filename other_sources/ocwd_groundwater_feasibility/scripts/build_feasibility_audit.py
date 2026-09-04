#!/usr/bin/env python3
"""Build a non-fitting OCWD groundwater data-feasibility audit."""

from __future__ import annotations

import json
import os
import platform
import sys
import urllib.parse
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pymupdf
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.audit_utils import (  # noqa: E402
    geometry_rings,
    point_in_geometry,
    read_usgs_rdb,
    records_from_ckan_json,
    sha256_file,
    write_json,
    write_markdown_table,
)

RAW = ROOT / "data" / "raw"
DERIVED = ROOT / "data" / "derived"
TABLES = ROOT / "outputs" / "tables"
FIGURES = ROOT / "outputs" / "figures"
PROVENANCE = ROOT / "outputs" / "provenance"
FEASIBILITY = ROOT / "outputs" / "feasibility"
ACCESSED_DATE = "2026-09-03"

EVIDENCE = {
    "OBSERVED",
    "REPORTED_MEASURED",
    "DERIVED_FROM_MEASUREMENTS",
    "ESTIMATED",
    "MODELED",
    "REFERENCE_MODEL",
}

DWR_PERIODIC_PACKAGE_URL = (
    "https://data.cnra.ca.gov/api/3/action/package_show?"
    "id=periodic-groundwater-level-measurements"
)
DWR_BASIN_PACKAGE_URL = (
    "https://data.cnra.ca.gov/api/3/action/package_show?id=i08-b118-ca-groundwaterbasins"
)
DWR_CONTINUOUS_PACKAGE_URL = (
    "https://data.cnra.ca.gov/api/3/action/package_show?"
    "id=continuous-groundwater-level-measurements"
)
DWR_WCR_PACKAGE_URL = (
    "https://data.cnra.ca.gov/api/3/action/package_show?id=well-completion-reports"
)
WCR_MAIN = "8da7b93b-4e69-495d-9caa-335691a1896b"
WCR_RESOURCES = {
    "wcr": WCR_MAIN,
    "well_numbers": "85b91c71-d8b4-44b0-8fb3-fe1fe5327ca8",
    "geologic_freeform": "def8769a-c9a1-4cf7-9522-2588f20f2f39",
    "geologic_quickpick": "35a622d6-58e5-406a-a034-a17012132fc5",
    "geologic_uscs": "8762f589-156d-499d-9a06-3a7db1ebe34d",
    "casing": "93fddfef-8c92-4ea1-b6c8-980997bb5fb8",
    "borehole": "735030c5-3d4f-428f-a5c7-c258cacdc307",
    "pdf_links": "bff565b3-b3b4-4727-b10b-e09e0012ec3b",
}


def wcr_query(name: str) -> str:
    if name == "wcr":
        return f'SELECT * FROM "{WCR_MAIN}" WHERE "COUNTYNAME"=\'Orange\' ORDER BY "_id"'
    id_ = WCR_RESOURCES[name]
    child_key = "WCRNumber" if name == "pdf_links" else "WCRNUMBER"
    return (
        f'SELECT c.* FROM "{id_}" c JOIN "{WCR_MAIN}" w '
        f'ON c."{child_key}"=w."WCRNUMBER" '
        'WHERE w."COUNTYNAME"=\'Orange\' ORDER BY c."_id"'
    )


def wcr_url(name: str) -> str:
    return (
        "https://data.cnra.ca.gov/api/3/action/datastore_search_sql?sql="
        + urllib.parse.quote(wcr_query(name), safe="")
    )


RAW_CATALOG: dict[str, dict[str, str]] = {
    "dwr_periodic_groundwater_levels_package.json": {
        "source_id": "DWR_PERIODIC_METADATA",
        "agency": "California Department of Water Resources",
        "title": "Periodic Groundwater Level Measurements metadata",
        "source_type": "dataset_metadata",
        "url": DWR_PERIODIC_PACKAGE_URL,
        "temporal_coverage": "1900-present (dataset statement)",
        "spatial_resolution": "station",
        "temporal_resolution": "periodic; some daily/weekly/monthly",
        "machine": "true",
        "class": "OBSERVED",
        "use": "source schema and provenance",
        "validation": "independence and QA audit",
        "limitations": "metadata is not the measurement table",
    },
    "dwr/dwr_placeholder": {},
}

# The placeholder keeps the catalog declaration readable; it is removed immediately.
RAW_CATALOG.pop("dwr/dwr_placeholder")


def add_raw(
    path: str,
    source_id: str,
    agency: str,
    title: str,
    source_type: str,
    url: str,
    temporal: str,
    spatial: str,
    resolution: str,
    machine: bool,
    evidence_class: str,
    intended_use: str,
    validation_use: str,
    limitations: str,
) -> None:
    RAW_CATALOG[path] = {
        "source_id": source_id,
        "agency": agency,
        "title": title,
        "source_type": source_type,
        "url": url,
        "temporal_coverage": temporal,
        "spatial_resolution": spatial,
        "temporal_resolution": resolution,
        "machine": str(machine).lower(),
        "class": evidence_class,
        "use": intended_use,
        "validation": validation_use,
        "limitations": limitations,
    }


add_raw(
    "dwr_bulletin118_basins_package.json", "DWR_B118_METADATA", "California Department of Water Resources",
    "Bulletin 118 California Groundwater Basins metadata", "dataset_metadata", DWR_BASIN_PACKAGE_URL,
    "current official release", "basin polygon", "versioned release", True, "REFERENCE_MODEL",
    "boundary provenance", "spatial inclusion audit", "official delineation, not a groundwater-state measurement",
)
add_raw(
    "dwr_continuous_groundwater_levels_package.json", "DWR_CONTINUOUS_METADATA", "California Department of Water Resources",
    "Continuous Groundwater Level Measurements metadata", "dataset_metadata", DWR_CONTINUOUS_PACKAGE_URL,
    "current official release", "listed counties", "15-minute to hourly source cadence", True, "OBSERVED",
    "geographic eligibility audit", "negative-result guard", "current county list excludes Orange County",
)
add_raw(
    "dwr_well_completion_reports_package.json", "DWR_WCR_METADATA", "California Department of Water Resources",
    "Well Completion Reports metadata", "dataset_metadata", DWR_WCR_PACKAGE_URL,
    "historical-present", "well/report", "event/report", True, "REPORTED_MEASURED",
    "construction-table provenance", "supplementary vertical evidence", "known missing, duplicate, and inaccurate fields; many approximate PLSS coordinates",
)
add_raw(
    "dwr/periodic_gwl_bulkdatadownload.zip", "DWR_PERIODIC_BULK", "California Department of Water Resources",
    "Periodic Groundwater Level Measurements bulk tables", "zip_csv",
    "https://data.cnra.ca.gov/dataset/dd9b15f5-6d08-4d8c-bace-37dc761a9c08/resource/c51e0af9-5980-4aa3-8965-e9ea494ad468/download/periodic_gwl_bulkdatadownload.zip",
    "1900-present", "station", "measurement timestamp", True, "OBSERVED",
    "Basin 8-001 head and station coverage", "future held-out state observations", "cooperating-agency observations require origin audit; QA varies",
)
add_raw(
    "dwr/bulletin118_groundwater_basins.geojson", "DWR_B118_GEOJSON", "California Department of Water Resources",
    "Bulletin 118 California Groundwater Basins GeoJSON", "geojson",
    "https://gis.data.cnra.ca.gov/api/download/v1/items/49807a1fbc584631bdf88d9ca71dd083/geojson?layers=0",
    "current official release", "basin polygon", "versioned release", True, "REFERENCE_MODEL",
    "select Basin 8-001 and spatially join stations", "spatial coverage audit", "CRS84 GeoJSON; boundary is an authoritative reference geometry",
)

for key in WCR_RESOURCES:
    add_raw(
        f"dwr/wcr_orange_{key}.json", f"DWR_WCR_ORANGE_{key.upper()}", "California Department of Water Resources",
        f"Well Completion Reports — Orange County {key.replace('_', ' ')}", "CKAN_DataStore_JSON", wcr_url(key),
        "historical-present", "Orange County report/well", "event/report", True, "REPORTED_MEASURED",
        "supplementary construction and hydrostratigraphy evidence", "screen/construction metadata only",
        "not limited to Basin 8-001; no fuzzy matching; WCR approximate coordinates never replace station coordinates",
    )

OCWD = "Orange County Water District"
OCWD_ITEMS = [
    ("ocwd/basin_model_appendix_b.pdf", "OCWD_BASIN_MODEL_APPENDIX_B", "Basin Model and Talbert Model Update / Appendix B", "report_pdf", "https://www.ocwd.com/wp-content/uploads/appendix-b.pdf", "1990-2011 discussion", "basin/model layer", "monthly inputs documented", "REFERENCE_MODEL", "document WRMS/model-input provenance", "not empirical ground truth", "documents model and input existence; does not release raw WRMS or model package"),
    ("ocwd/groundwater_management_plan_2004.pdf", "OCWD_GWMP_2004", "2004 Groundwater Management Plan", "report_pdf", "https://www.ocwd.com/wp-content/uploads/2004_03XX_OCWD-GWMP-2004.pdf", "historical-2004", "basin/well", "monthly reporting documented", "REPORTED_MEASURED", "document monitoring and WRMS provenance", "supports data-existence audit", "documentation is not the raw records"),
    ("ocwd/groundwater_location_maps_page.html", "OCWD_LOCATION_MAPS", "Groundwater and location maps", "web_page", "https://www.ocwd.com/what-we-do/groundwater-management/groundwater-location-maps/", "current and archived maps", "basin/aquifer system", "annual or map-specific", "REPORTED_MEASURED", "monitoring-network and aquifer-system inventory", "spatial context only", "maps are not raw monitoring time series"),
    ("ocwd/basin_8_001_alternative_2022_update.pdf", "OCWD_BASIN_ALTERNATIVE_2022", "Basin 8-001 Alternative 2022 Update", "report_pdf", "https://www.ocwd.com/wp-content/uploads/basin-8-1-alternative-draft-2022-update.pdf", "through 2021", "basin/facility/well", "monthly Water Resources Summary documented", "DERIVED_FROM_MEASUREMENTS", "monitoring and recharge-accounting provenance", "data-schema evidence", "mixes measured, calculated, and estimated quantities"),
    ("ocwd/groundwater_supplies_page.html", "OCWD_WATER_RESOURCES_INDEX", "Groundwater supplies and Water Resources Reports index", "web_page", "https://www.ocwd.com/what-we-do/groundwater-management/groundwater-supplies/", "current reports", "basin", "monthly", "DERIVED_FROM_MEASUREMENTS", "report index and accounting definitions", "provenance audit", "index is not a raw time series"),
    ("ocwd/groundwater_recharge_report_2009_2010.pdf", "OCWD_RECHARGE_2009_2010", "2009-2010 Report on Groundwater Recharge", "report_pdf", "https://www.ocwd.com/wp-content/uploads/09-10annualrechargereport_all.pdf", "2009-07 to 2010-06 with historical context", "recharge facility", "monthly", "DERIVED_FROM_MEASUREMENTS", "historic facility/source/accounting schema", "future forcing provenance", "percolation and storage are calculated from measured flows/levels; some inputs estimated"),
    ("ocwd/mbi_centennial_park_2020.html", "OCWD_MBI_2020", "Mid-Basin Injection Centennial Park Project in Operation", "web_page", "https://www.ocwd.com/news-events/newsletter/2020/april-2020/mid-basin-injection-centennial-park-project-in-operation/", "2015-2020 milestones", "injection facility", "event month", "REPORTED_MEASURED", "intervention event dates", "future response validation event", "operational dates do not provide forcing volumes or response series"),
    ("ocwd/gwrs_annual_report_2023.pdf", "OCWD_GWRS_2023", "2023 GWRS Annual Report", "report_pdf", "https://www.ocwd.com/wp-content/uploads/2023-GWRS-Annual-Report.pdf", "2023", "injection and monitoring wells", "annual report; well metadata", "REPORTED_MEASURED", "MBI well/screen/aquifer metadata", "future intervention monitoring design", "report is not the underlying time series"),
    ("ocwd/water_issues_committee_20260311.pdf", "OCWD_WIC_20260311", "Water Issues Committee packet, 2026-03-11", "report_pdf", "https://www.ocwd.com/wp-content/uploads/WIC_20260311.pdf", "2026", "MBI system", "meeting packet", "REPORTED_MEASURED", "current MBI system/map inventory", "intervention context", "meeting packet is not the underlying injection data"),
]
for item in OCWD_ITEMS:
    add_raw(item[0], item[1], OCWD, item[2], item[3], item[4], item[5], item[6], item[7], True, item[8], item[9], item[10], item[11])

for month, url_name in [("2025_07", "WRR-July-2025.pdf"), ("2026_01", "WRR_2026_01.pdf"), ("2026_07", "WRR_2026_07.pdf")]:
    add_raw(
        f"ocwd/water_resources_report_{month}.pdf", f"OCWD_WRR_{month}", OCWD,
        f"Water Resources Report {month.replace('_', '-')}", "report_pdf",
        f"https://www.ocwd.com/wp-content/uploads/{url_name}", month.replace("_", "-"), "basin/recharge system",
        "monthly", False, "DERIVED_FROM_MEASUREMENTS", "recent accounting schema sample",
        "not independent groundwater-state validation", "preliminary report; mixes measured/reported, calculated, and estimated components",
    )

add_raw("usgs/USGS_11074000_site.rdb", "USGS_11074000_SITE", "U.S. Geological Survey", "Santa Ana River below Prado Dam site metadata", "NWIS_RDB", "https://waterservices.usgs.gov/nwis/site/?format=rdb&sites=11074000&siteOutput=expanded&siteStatus=all", "station record", "gage", "static metadata", True, "OBSERVED", "river forcing metadata", "external observed forcing", "site timezone is PST with daylight-saving flag; coordinate datum retained")
add_raw("usgs/USGS_11074000_discharge_daily.rdb", "USGS_11074000_DAILY", "U.S. Geological Survey", "Santa Ana River below Prado Dam daily discharge", "NWIS_RDB", "https://waterservices.usgs.gov/nwis/dv/?format=rdb&sites=11074000&startDT=1900-01-01&endDT=2026-09-03&parameterCd=00060&siteStatus=all", "1940-present", "gage", "daily", True, "OBSERVED", "river forcing coverage", "external observed forcing", "estimated/provisional qualifiers retained")
add_raw("usgs/USGS_11074000_discharge_instantaneous_recent.rdb", "USGS_11074000_IV_RECENT", "U.S. Geological Survey", "Santa Ana River below Prado Dam recent instantaneous discharge", "NWIS_RDB", "https://waterservices.usgs.gov/nwis/iv/?format=rdb&sites=11074000&startDT=2026-08-01&endDT=2026-09-03&parameterCd=00060&siteStatus=all", "2026-08-01 to 2026-09-03", "gage", "15-minute", True, "OBSERVED", "timezone/QA schema demonstration", "external observed forcing", "recent slice only; provisional values expected")
add_raw("llnl/osti_15013774_page.html", "DOE_OSTI_15013774_METADATA", "U.S. Department of Energy / OSTI", "LLNL Forebay isotope tracer report metadata", "web_page", "https://www.osti.gov/biblio/15013774", "1995-2001 study", "Forebay tracer network", "experiment", True, "OBSERVED", "tracer provenance", "independent physical propagation validation", "study observations are sparse experiments, not routine forcing/state time series")
add_raw("llnl/llnl_forebay_isotope_tracer_final_report.pdf", "LLNL_TRACER_FINAL", "Lawrence Livermore National Laboratory / U.S. Department of Energy", "Final report on isotope tracer investigations in the Forebay", "technical_report_pdf", "https://www.osti.gov/servlets/purl/15013774", "1995-2001", "recharge basin to monitoring/production well", "experiment", False, "OBSERVED", "explicit tracer travel quantities", "future independent physical connectivity/travel validation", "published experimental summaries; no graph-pixel digitization")
add_raw("journal/repeat_kraemer_basin_tracer_study_2014.pdf", "CLARK_ET_AL_2014_TRACER", "Peer-reviewed study (OCWD and University of California authors)", "Investigation of Groundwater Flow Variations near a Recharge Pond with Repeat Deliberate Tracer Experiments", "journal_pdf", "https://mdpi-res.com/d_attachment/water/water-06-01826/article_deploy/water-06-01826.pdf", "1998 and 2008 experiments", "Kraemer Basin to wells", "experiment", False, "OBSERVED", "repeat tracer travel quantities", "future physical propagation validation", "reported table values only; origin is not independent of OCWD participation")

SGMA_ITEMS = [
    ("sgma/basin_8_001_alternative_periodic_evaluation_page.html", "CA_SGMA_8_001_PORTAL", "California DWR SGMA Portal", "https://sgma.water.ca.gov/portal/alternative/periodiceval/preview/10", "portal_page"),
    ("sgma/coastal_plain_statement_of_findings.pdf", "DWR_SGMA_FINDINGS", "DWR Statement of Findings: Coastal Plain of Orange County Alternative", "https://water.ca.gov/-/media/DWR-Website/Web-Pages/Programs/Groundwater-Management/Sustainable-Groundwater-Management/Alternatives/Files/10year/CoastalPlain/02_CoastalPlain_Statement_of_Findings.pdf", "report_pdf"),
    ("sgma/coastal_plain_staff_report.pdf", "DWR_SGMA_STAFF_REPORT", "DWR Alternative Assessment Staff Report", "https://water.ca.gov/-/media/DWR-Website/Web-Pages/Programs/Groundwater-Management/Sustainable-Groundwater-Management/Alternatives/Files/10year/CoastalPlain/03_CoastalPlain_Staff_Report.pdf", "report_pdf"),
]
for path, source_id, title, url, kind in SGMA_ITEMS:
    add_raw(path, source_id, "California Department of Water Resources", title, kind, url, "alternative review period", "Basin 8-001", "plan/review", kind == "portal_page", "REFERENCE_MODEL", "management-plan provenance", "scope confirmation", "management assessment is not a groundwater observation")

SECONDARY_ITEMS = [
    ("ocsan_epa/ocsan_annual_reports_page.html", "OCSAN_REPORT_INDEX", "Orange County Sanitation District", "OC San reports index", "https://ocsan.gov/annual-reports/", "web_page"),
    ("ocsan_epa/ocsan_pretreatment_annual_report_fy2024_2025.pdf", "OCSAN_PRETREATMENT_2025", "Orange County Sanitation District", "Resource Protection Division Annual Report FY 2024-2025", "https://ocsan.gov/wp-content/uploads/2025/10/OC_San_Pretreatment_Annual_Report_FY_2024_2025_Final.pdf", "report_pdf"),
    ("ocsan_epa/epa_CA0110604_page.html", "EPA_CA0110604_PAGE", "U.S. Environmental Protection Agency", "NPDES permit CA0110604 page", "https://www.epa.gov/npdes-permits/CA0110604", "web_page"),
    ("ocsan_epa/CA0110604_R8_2021_0010_permit.pdf", "EPA_CA0110604_PERMIT", "U.S. Environmental Protection Agency / California Water Boards", "Joint EPA/State NPDES Permit CA0110604", "https://www.epa.gov/system/files/documents/2021-07/r8-2021-0010-ca0110604-oc-sanitation-district-2021-06-23.pdf", "permit_pdf"),
    ("ocsan_epa/epa_icis_npdes_dmr_download_page.html", "EPA_ICIS_DMR_DOWNLOAD", "U.S. Environmental Protection Agency", "ICIS-NPDES permit limit and DMR datasets", "https://echo.epa.gov/tools/data-downloads/icis-npdes-dmr-and-limit-data-set", "web_page"),
    ("ocsan_epa/epa_icis_npdes_search_guide.html", "EPA_ICIS_GUIDE", "U.S. Environmental Protection Agency", "ICIS-NPDES search user guide", "https://www.epa.gov/enviro/icis-npdes-search-user-guide", "web_page"),
]
for path, source_id, agency, title, url, kind in SECONDARY_ITEMS:
    add_raw(path, source_id, agency, title, kind, url, "varies/current", "wastewater facility or permit", "annual/permit/reporting", kind == "web_page", "REPORTED_MEASURED", "secondary wastewater inventory only", "not used to decide groundwater feasibility", "aggregate/permit data do not provide groundwater pumping or head forcing")


def ensure_directories() -> None:
    for directory in (DERIVED, TABLES, FIGURES, PROVENANCE, FEASIBILITY):
        directory.mkdir(parents=True, exist_ok=True)


def build_raw_manifest_and_registry() -> pd.DataFrame:
    raw_files = sorted(p for p in RAW.rglob("*") if p.is_file() and p.name != ".gitkeep")
    unregistered = [p.relative_to(RAW).as_posix() for p in raw_files if p.relative_to(RAW).as_posix() not in RAW_CATALOG]
    missing = [path for path in RAW_CATALOG if not (RAW / path).is_file()]
    if unregistered or missing:
        raise RuntimeError(f"Raw provenance mismatch: unregistered={unregistered}; missing={missing}")
    rows = []
    registry_rows = []
    for path in raw_files:
        rel = path.relative_to(RAW).as_posix()
        meta = RAW_CATALOG[rel]
        digest = sha256_file(path)
        accessed = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        rows.append({
            "local_path": rel,
            "source_id": meta["source_id"],
            "official_url": meta["url"],
            "accessed_at": accessed,
            "bytes": path.stat().st_size,
            "sha256": digest,
        })
        registry_rows.append({
            "source_id": meta["source_id"],
            "agency": meta["agency"],
            "title": meta["title"],
            "source_type": meta["source_type"],
            "official_url": meta["url"],
            "accessed_at": accessed,
            "temporal_coverage": meta["temporal_coverage"],
            "spatial_resolution": meta["spatial_resolution"],
            "temporal_resolution": meta["temporal_resolution"],
            "raw_machine_readable": meta["machine"],
            "measurement_class": meta["class"],
            "intended_use": meta["use"],
            "validation_use": meta["validation"],
            "limitations": meta["limitations"],
            "sha256": digest,
        })
    manifest = pd.DataFrame(rows)
    manifest.to_csv(PROVENANCE / "RAW_DOWNLOAD_HASH_MANIFEST.csv", index=False)
    write_json(PROVENANCE / "RAW_DOWNLOAD_HASH_MANIFEST.json", rows)
    registry = pd.DataFrame(registry_rows).sort_values("source_id")
    if not set(registry["measurement_class"]).issubset(EVIDENCE):
        raise RuntimeError("Source registry contains an invalid evidence class")
    registry.to_csv(ROOT / "sources" / "source_registry.csv", index=False)
    (ROOT / "sources" / "source_registry.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "sources": registry.to_dict(orient="records")}, sort_keys=False)
    )
    return manifest


def select_basin() -> tuple[dict, dict]:
    collection = json.loads((RAW / "dwr" / "bulletin118_groundwater_basins.geojson").read_text())
    matches = [
        feature for feature in collection["features"]
        if feature["properties"].get("Basin_Subbasin_Number") == "8-001"
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one Basin 8-001 feature, found {len(matches)}")
    feature = matches[0]
    derived = {
        "type": "FeatureCollection",
        "name": "DWR Bulletin 118 Basin 8-001",
        "crs": collection.get("crs", {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}}),
        "features": [feature],
    }
    write_json(DERIVED / "DWR_BASIN_8_001.geojson", derived)
    write_json(PROVENANCE / "BASIN_GEOMETRY_PROVENANCE.json", {
        "basin_id": "8-001",
        "basin_name": feature["properties"].get("Basin_Name"),
        "source_crs": collection.get("crs"),
        "derived_crs": derived["crs"],
        "station_coordinate_reference": "NAD83 per DWR periodic station data dictionary",
        "join_coordinate_note": "Point-in-polygon in geographic longitude/latitude; no manual digitization and no WCR coordinate substitution.",
        "source_sha256": sha256_file(RAW / "dwr" / "bulletin118_groundwater_basins.geojson"),
        "derived_sha256": sha256_file(DERIVED / "DWR_BASIN_8_001.geojson"),
    })
    return feature, derived


def classify_origin(collector: str, reporter: str) -> tuple[str, str]:
    combined = f"{collector} {reporter}".lower()
    if "orange county water district" in combined or "ocwd" in combined:
        return "OCWD_ORIGIN_REPUBLISHED_BY_DWR", "collector or reporter explicitly identifies OCWD"
    collector_lower = str(collector).lower()
    if (
        "department of water resources" in collector_lower
        or "u.s. geological survey" in collector_lower
        or "united states geological survey" in collector_lower
        or "usgs" in collector_lower
    ):
        return "INDEPENDENT_AGENCY_OBSERVATION", "collector explicitly identifies DWR or USGS"
    return "UNKNOWN_ORIGIN", "metadata do not support an OCWD-origin or independent-agency determination"


def rolling_intersection_counts(heads: pd.DataFrame, window_years: int) -> pd.DataFrame:
    usable = heads.loc[heads["usable_head"], ["site_code", "measurement_datetime_pst"]].dropna()
    usable = usable.assign(year=usable["measurement_datetime_pst"].dt.year)
    by_year = {int(year): set(group["site_code"]) for year, group in usable.groupby("year")}
    if not by_year:
        return pd.DataFrame(columns=["start_year", "end_year", "n_wells_observed_each_year"])
    rows = []
    for start in range(min(by_year), max(by_year) - window_years + 2):
        years = range(start, start + window_years)
        shared = set.intersection(*(by_year.get(year, set()) for year in years))
        rows.append({"start_year": start, "end_year": start + window_years - 1, "n_wells_observed_each_year": len(shared)})
    return pd.DataFrame(rows)


def build_dwr_periodic(feature: dict) -> dict[str, object]:
    bulk = RAW / "dwr" / "periodic_gwl_bulkdatadownload.zip"
    with zipfile.ZipFile(bulk) as archive:
        stations = pd.read_csv(archive.open("stations.csv"), dtype=str, keep_default_na=False)
        perforations = pd.read_csv(archive.open("perforations.csv"), dtype=str, keep_default_na=False)
        station_dictionary = archive.read("DataDictionary_stations.csv")
        measurement_dictionary = archive.read("DataDictionary_measurements.csv")
        perforation_dictionary = archive.read("DataDictionary_perforations.csv")
        metadata = archive.read("metadata.txt")
    for name, content in [
        ("DWR_PERIODIC_STATION_DATA_DICTIONARY.csv", station_dictionary),
        ("DWR_PERIODIC_MEASUREMENT_DATA_DICTIONARY.csv", measurement_dictionary),
        ("DWR_PERIODIC_PERFORATION_DATA_DICTIONARY.csv", perforation_dictionary),
        ("DWR_PERIODIC_METADATA.txt", metadata),
    ]:
        (PROVENANCE / name).write_bytes(content)

    stations["latitude_numeric"] = pd.to_numeric(stations["latitude"], errors="coerce")
    stations["longitude_numeric"] = pd.to_numeric(stations["longitude"], errors="coerce")
    stations["inside_basin_8_001"] = [
        point_in_geometry(lon, lat, feature["geometry"])
        for lon, lat in zip(stations["longitude_numeric"], stations["latitude_numeric"])
    ]
    stations["official_basin_code_8_001"] = stations["basin_code"].eq("8-001")
    basin_stations = stations.loc[stations["inside_basin_8_001"]].copy()
    site_codes = set(basin_stations["site_code"])

    selected_chunks = []
    with zipfile.ZipFile(bulk) as archive:
        for chunk in pd.read_csv(
            archive.open("measurements.csv"), dtype=str, keep_default_na=False,
            chunksize=400_000, low_memory=False,
        ):
            selected = chunk.loc[chunk["site_code"].isin(site_codes)].copy()
            if not selected.empty:
                selected_chunks.append(selected)
    heads = pd.concat(selected_chunks, ignore_index=True) if selected_chunks else pd.DataFrame()
    heads["measurement_datetime_pst"] = pd.to_datetime(heads["msmt_date"], errors="coerce")
    heads["groundwater_elevation_ft_navd88"] = pd.to_numeric(heads["gwe"], errors="coerce")
    heads["depth_to_groundwater_ft_bgs"] = pd.to_numeric(heads["gse_gwe"], errors="coerce")
    heads["usable_head"] = (
        heads["groundwater_elevation_ft_navd88"].notna()
        & heads["measurement_datetime_pst"].notna()
        & heads["wlm_qa_desc"].isin(["", "Good"])
    )
    heads["timestamp_basis"] = "Pacific Standard Time per DWR data dictionary"
    heads["evidence_class"] = "OBSERVED"

    basin_perforations = perforations.loc[perforations["site_code"].isin(site_codes)].copy()
    basin_perforations["top_perforation_ft_bgs"] = pd.to_numeric(basin_perforations["top_prf_int"], errors="coerce")
    basin_perforations["bottom_perforation_ft_bgs"] = pd.to_numeric(basin_perforations["bot_prf_int"], errors="coerce")
    basin_perforations["evidence_class"] = "REPORTED_MEASURED"

    usable = heads.loc[heads["usable_head"]].copy()
    stats_rows = []
    for site_code, all_group in heads.groupby("site_code", sort=False):
        group = usable.loc[usable["site_code"].eq(site_code)].sort_values("measurement_datetime_pst")
        dates = pd.Series(group["measurement_datetime_pst"].dropna().unique()).sort_values()
        intervals = dates.diff().dt.total_seconds().div(86400).dropna()
        earliest = dates.min() if len(dates) else pd.NaT
        latest = dates.max() if len(dates) else pd.NaT
        def count_le(days: int) -> int:
            return int(intervals.le(days).sum())
        def share_le(days: int) -> float:
            return float(intervals.le(days).mean()) if len(intervals) else np.nan
        stats_rows.append({
            "site_code": site_code,
            "earliest_observation": earliest,
            "latest_observation": latest,
            "n_all_records": len(all_group),
            "n_observations": len(group),
            "n_distinct_observation_times": len(dates),
            "n_intervals": len(intervals),
            "median_measurement_interval_days": intervals.median() if len(intervals) else np.nan,
            "largest_gap_days": intervals.max() if len(intervals) else np.nan,
            "intervals_le_45_days": count_le(45),
            "share_intervals_le_45_days": share_le(45),
            "intervals_le_90_days": count_le(90),
            "share_intervals_le_90_days": share_le(90),
            "intervals_le_180_days": count_le(180),
            "share_intervals_le_180_days": share_le(180),
            "span_years": (latest - earliest).total_seconds() / (365.2425 * 86400) if len(dates) >= 2 else 0.0,
            "overlaps_1990_11_to_1999_11": bool(((dates >= pd.Timestamp("1990-11-01")) & (dates <= pd.Timestamp("1999-11-30"))).any()) if len(dates) else False,
            "overlaps_2008_plus": bool((dates >= pd.Timestamp("2008-01-01")).any()) if len(dates) else False,
            "collecting_entities": "; ".join(sorted(x for x in group["coop_org_name"].unique() if x)),
            "submitting_entities": "; ".join(sorted(x for x in group["wlm_org_name"].unique() if x)),
        })
    stats = pd.DataFrame(stats_rows)
    perf_counts = basin_perforations.groupby("site_code").size().rename("n_perforation_intervals")
    well_master = basin_stations.merge(stats, on="site_code", how="left").merge(perf_counts, on="site_code", how="left")
    well_master["n_perforation_intervals"] = well_master["n_perforation_intervals"].fillna(0).astype(int)
    well_master["has_perforation_metadata"] = well_master["n_perforation_intervals"].gt(0)
    well_master["has_datum_or_elevation_metadata"] = (
        well_master["gse"].ne("") | well_master["rpe"].ne("")
    )
    well_master["coordinate_source"] = "DWR periodic station table"
    well_master["coordinate_datum"] = "NAD83 per data dictionary"
    well_master["elevation_datum"] = "NAVD88 per data dictionary"

    independence_rows = []
    for row in heads.itertuples(index=False):
        classification, rationale = classify_origin(row.coop_org_name, row.wlm_org_name)
        independence_rows.append({
            "site_code": row.site_code,
            "measurement_datetime": row.msmt_date,
            "reporting_organization": row.wlm_org_name,
            "collecting_organization": row.coop_org_name,
            "dwr_source": row.source,
            "usable_head": row.usable_head,
            "independence_class": classification,
            "rationale": rationale,
            "count_as_distinct_sensor_record": True,
            "do_not_duplicate_against_ocwd": classification == "OCWD_ORIGIN_REPUBLISHED_BY_DWR",
        })
    independence = pd.DataFrame(independence_rows)

    well_master.to_parquet(DERIVED / "DWR_OCWD_WELL_MASTER.parquet", index=False)
    heads.to_parquet(DERIVED / "DWR_OCWD_HEAD_OBSERVATIONS.parquet", index=False)
    basin_perforations.to_parquet(DERIVED / "DWR_OCWD_PERFORATIONS.parquet", index=False)
    independence.to_csv(TABLES / "OBSERVATION_INDEPENDENCE_LEDGER.csv", index=False)

    monthly = usable.assign(month=usable["measurement_datetime_pst"].dt.to_period("M").astype(str)).groupby("month").agg(
        n_observations=("site_code", "size"), n_wells=("site_code", "nunique")
    ).reset_index()
    annual = usable.assign(year=usable["measurement_datetime_pst"].dt.year).groupby("year").agg(
        n_observations=("site_code", "size"), n_wells=("site_code", "nunique")
    ).reset_index()
    monthly.to_csv(TABLES / "DWR_OCWD_MONTHLY_HEAD_COVERAGE.csv", index=False)
    annual.to_csv(TABLES / "DWR_OCWD_ANNUAL_HEAD_COVERAGE.csv", index=False)
    if len(monthly):
        monthly_indexed = monthly.assign(period=pd.PeriodIndex(monthly["month"], freq="M")).set_index("period")[["n_observations", "n_wells"]]
        full_months = monthly_indexed.reindex(pd.period_range(monthly_indexed.index.min(), monthly_indexed.index.max(), freq="M"), fill_value=0)
        threshold_met = full_months["n_wells"].ge(50)
        run_id = threshold_met.ne(threshold_met.shift()).cumsum()
        common_runs = []
        for _, group in full_months.loc[threshold_met].groupby(run_id[threshold_met]):
            common_runs.append({
                "start_month": str(group.index.min()),
                "end_month": str(group.index.max()),
                "consecutive_months": int(len(group)),
                "minimum_wells_in_month": int(group["n_wells"].min()),
                "median_wells_in_month": float(group["n_wells"].median()),
            })
        common_runs_frame = pd.DataFrame(common_runs).sort_values("consecutive_months", ascending=False)
    else:
        common_runs_frame = pd.DataFrame(columns=["start_month", "end_month", "consecutive_months", "minimum_wells_in_month", "median_wells_in_month"])
    common_runs_frame.to_csv(TABLES / "DWR_OCWD_MONTHLY_COMMON_SUPPORT_RUNS.csv", index=False)
    rolling5 = rolling_intersection_counts(heads, 5)
    rolling10 = rolling_intersection_counts(heads, 10)
    rolling5.assign(window_years=5).to_csv(TABLES / "DWR_OCWD_ROLLING_5Y_COMMON_SUPPORT.csv", index=False)
    rolling10.assign(window_years=10).to_csv(TABLES / "DWR_OCWD_ROLLING_10Y_COMMON_SUPPORT.csv", index=False)

    entity = usable.groupby(["coop_org_name", "wlm_org_name"], dropna=False).agg(
        n_observations=("site_code", "size"), n_stations=("site_code", "nunique"),
        earliest=("measurement_datetime_pst", "min"), latest=("measurement_datetime_pst", "max"),
    ).reset_index().sort_values(["n_stations", "n_observations"], ascending=False)
    entity.to_csv(TABLES / "DWR_OCWD_COVERAGE_BY_COLLECTING_ENTITY.csv", index=False)
    stats.sort_values("largest_gap_days", ascending=False).head(100).to_csv(TABLES / "DWR_OCWD_IMPORTANT_TEMPORAL_GAPS.csv", index=False)

    source_counts = heads["source"].value_counts(dropna=False).to_dict()
    usable_independence_counts = independence.loc[independence["usable_head"], "independence_class"].value_counts().to_dict()
    longest_run = common_runs_frame.iloc[0].to_dict() if len(common_runs_frame) else {}
    summary = {
        "basin_id": "8-001",
        "basin_name": feature["properties"].get("Basin_Name"),
        "spatial_join_method": "point-in-polygon against official DWR Bulletin 118 GeoJSON",
        "n_dwr_stations_inside": int(len(well_master)),
        "n_with_usable_head_observations": int(well_master["n_observations"].fillna(0).gt(0).sum()),
        "n_with_at_least_24_observations": int(well_master["n_observations"].fillna(0).ge(24).sum()),
        "n_with_at_least_60_observations": int(well_master["n_observations"].fillna(0).ge(60).sum()),
        "n_spanning_at_least_5_years": int(well_master["span_years"].fillna(0).ge(5).sum()),
        "n_spanning_at_least_10_years": int(well_master["span_years"].fillna(0).ge(10).sum()),
        "n_overlapping_1990_11_to_1999_11": int(well_master["overlaps_1990_11_to_1999_11"].fillna(False).sum()),
        "n_overlapping_2008_plus": int(well_master["overlaps_2008_plus"].fillna(False).sum()),
        "n_with_perforation_metadata": int(well_master["has_perforation_metadata"].sum()),
        "share_with_perforation_metadata": float(well_master["has_perforation_metadata"].mean()),
        "n_head_records_all_qa": int(len(heads)),
        "n_usable_head_observations": int(heads["usable_head"].sum()),
        "earliest_usable_observation": usable["measurement_datetime_pst"].min(),
        "latest_usable_observation": usable["measurement_datetime_pst"].max(),
        "median_of_well_median_intervals_days": float(well_master.loc[well_master["n_observations"].fillna(0).gt(1), "median_measurement_interval_days"].median()),
        "maximum_observed_gap_days": float(well_master["largest_gap_days"].max()),
        "max_wells_observed_in_every_year_of_a_5y_window": int(rolling5["n_wells_observed_each_year"].max()) if len(rolling5) else 0,
        "best_5y_window": (rolling5.loc[rolling5["n_wells_observed_each_year"].idxmax(), ["start_year", "end_year"]].astype(int).tolist() if len(rolling5) else []),
        "max_wells_observed_in_every_year_of_a_10y_window": int(rolling10["n_wells_observed_each_year"].max()) if len(rolling10) else 0,
        "best_10y_window": (rolling10.loc[rolling10["n_wells_observed_each_year"].idxmax(), ["start_year", "end_year"]].astype(int).tolist() if len(rolling10) else []),
        "n_station_official_code_vs_spatial_join_mismatches": int((well_master["official_basin_code_8_001"] != well_master["inside_basin_8_001"]).sum()),
        "dwr_measurement_source_counts": {str(k): int(v) for k, v in source_counts.items()},
        "usable_head_independence_counts": {str(k): int(v) for k, v in usable_independence_counts.items()},
        "n_months_with_at_least_50_observed_wells": int(monthly["n_wells"].ge(50).sum()),
        "longest_consecutive_monthly_support_run_at_50_wells": longest_run,
        "no_interpolation": True,
        "usable_definition": "numeric groundwater elevation and timestamp with QA Good or blank-as-good per DWR dictionary",
    }
    write_json(TABLES / "DWR_OCWD_PUBLIC_COVERAGE_SUMMARY.json", summary)
    write_markdown_table(
        TABLES / "DWR_OCWD_PUBLIC_COVERAGE_SUMMARY.md",
        pd.DataFrame([{"metric": key, "value": value} for key, value in summary.items()]),
        "DWR Basin 8-001 public head-data coverage",
        "Counts are a data-availability audit. Groundwater levels were not interpolated and no wells were selected using model performance.",
    )
    return {"well_master": well_master, "heads": heads, "perforations": basin_perforations, "independence": independence, "monthly": monthly, "annual": annual, "summary": summary}


def normalize_identifier(value: object) -> str:
    return str(value or "").strip().upper().replace(" ", "")


def build_wcr_supplement(well_master: pd.DataFrame) -> pd.DataFrame:
    tables = {name: records_from_ckan_json(RAW / "dwr" / f"wcr_orange_{name}.json") for name in WCR_RESOURCES}
    tables["wcr"].to_parquet(DERIVED / "DWR_WCR_ORANGE_WELL_MASTER.parquet", index=False)
    tables["well_numbers"].to_parquet(DERIVED / "DWR_WCR_ORANGE_WELL_NUMBERS.parquet", index=False)
    tables["casing"].to_parquet(DERIVED / "DWR_WCR_ORANGE_CASING.parquet", index=False)
    tables["borehole"].to_parquet(DERIVED / "DWR_WCR_ORANGE_BOREHOLE.parquet", index=False)
    tables["pdf_links"].to_parquet(DERIVED / "DWR_WCR_ORANGE_REPORT_LINKS.parquet", index=False)
    logs = []
    for name in ("geologic_freeform", "geologic_quickpick", "geologic_uscs"):
        frame = tables[name].copy()
        frame["geologic_log_type"] = name
        logs.append(frame)
    pd.concat(logs, ignore_index=True, sort=False).to_parquet(DERIVED / "DWR_WCR_ORANGE_GEOLOGIC_LOGS.parquet", index=False)

    wcr = tables["wcr"].copy()
    wcr["norm_wcr"] = wcr["WCRNUMBER"].map(normalize_identifier)
    wcr["norm_legacy_log"] = wcr["LEGACYLOGNUMBER"].map(normalize_identifier)
    wcr_groups = {key: group for key, group in wcr.groupby("norm_wcr") if key}
    legacy_groups = {key: group for key, group in wcr.groupby("norm_legacy_log") if key and key != "N/A"}
    numbers = tables["well_numbers"].copy()
    numbers["norm_swn"] = numbers["STATE_WELL_NUMBER"].map(normalize_identifier)
    numbers["norm_wcr"] = numbers["WCRNUMBER"].map(normalize_identifier)
    swn_to_wcr = numbers.groupby("norm_swn")["norm_wcr"].agg(lambda values: sorted(set(x for x in values if x))).to_dict()

    rows = []
    for station in well_master.itertuples(index=False):
        station_wcr = normalize_identifier(getattr(station, "wcr_no", ""))
        station_swn = normalize_identifier(getattr(station, "swn", ""))
        candidates: list[str] = []
        status = "NO_MATCH"
        rationale = "No exact WCR number or unique state-well-number crosswalk."
        if station_wcr and station_wcr in wcr_groups:
            candidates = [station_wcr]
            status = "EXACT_ID" if len(wcr_groups[station_wcr]) == 1 else "AMBIGUOUS"
            rationale = "DWR periodic station WCR number equals DWR WCR identifier." if status == "EXACT_ID" else "Exact identifier returns duplicate WCR master rows."
            selected_group = wcr_groups[station_wcr]
        elif station_wcr and station_wcr in legacy_groups:
            selected_group = legacy_groups[station_wcr]
            candidates = sorted(set(selected_group["norm_wcr"]))
            status = "EXACT_ID" if len(selected_group) == 1 else "AMBIGUOUS"
            rationale = "DWR periodic station WCR number equals the DWR WCR legacy-log identifier." if status == "EXACT_ID" else "Exact legacy-log identifier returns duplicate WCR master rows."
        elif station_swn and station_swn in swn_to_wcr:
            candidates = swn_to_wcr[station_swn]
            candidate_rows = sum(len(wcr_groups.get(candidate, [])) for candidate in candidates)
            if len(candidates) == 1 and candidate_rows == 1:
                status = "HIGH_CONFIDENCE_METADATA_MATCH"
                rationale = "Unique DWR state-well-number crosswalk links the station to one WCR master row."
            else:
                status = "AMBIGUOUS"
                rationale = "State-well-number crosswalk returns multiple WCR candidates or duplicate master rows."
        if status == "EXACT_ID" and station_wcr in legacy_groups and station_wcr not in wcr_groups:
            selected = legacy_groups[station_wcr].iloc[0]
        elif status in {"EXACT_ID", "HIGH_CONFIDENCE_METADATA_MATCH"}:
            selected = wcr_groups[candidates[0]].iloc[0]
        else:
            selected = None
        rows.append({
            "site_code": station.site_code,
            "station_state_well_number": getattr(station, "swn", ""),
            "station_wcr_number": getattr(station, "wcr_no", ""),
            "match_status": status,
            "matched_wcr_number": selected["WCRNUMBER"] if selected is not None else "",
            "match_rationale": rationale,
            "canonical_latitude": station.latitude_numeric,
            "canonical_longitude": station.longitude_numeric,
            "canonical_coordinate_source": "DWR periodic station table",
            "wcr_latitude_supplementary_only": selected.get("DECIMALLATITUDE", "") if selected is not None else "",
            "wcr_longitude_supplementary_only": selected.get("DECIMALLONGITUDE", "") if selected is not None else "",
            "wcr_coordinate_method": selected.get("METHODOFDETERMINATIONLL", "") if selected is not None else "",
            "wcr_coordinate_accuracy": selected.get("LLACCURACY", "") if selected is not None else "",
            "wcr_coordinates_used_as_canonical": False,
            "authoritative_layer_assignment": "",
            "layer_assignment_note": "No Shallow/Principal/Deep assignment from invented depth thresholds; authoritative OCWD/model metadata required.",
        })
    ledger = pd.DataFrame(rows)
    ledger.to_csv(TABLES / "WCR_MATCH_LEDGER.csv", index=False)
    counts = {name: int(len(frame)) for name, frame in tables.items()}
    counts["match_status"] = {str(key): int(value) for key, value in ledger["match_status"].value_counts().items()}
    write_json(TABLES / "WCR_SUPPLEMENT_COVERAGE.json", counts)
    return ledger


def build_continuous_negative_result() -> dict[str, object]:
    package = json.loads((RAW / "dwr_continuous_groundwater_levels_package.json").read_text())["result"]
    notes = " ".join(package.get("notes", "").split())
    counties = ["Butte", "Colusa", "Glenn", "Mendocino", "Modoc", "Sacramento", "San Joaquin", "Shasta", "Siskiyou", "Solano", "Sutter", "Tehama", "Yolo", "Yuba"]
    missing_named = [county for county in counties if county not in notes]
    if missing_named or "Orange County" in notes:
        raise RuntimeError(f"DWR continuous-data geography changed: missing={missing_named}; Orange listed={'Orange County' in notes}")
    result = {
        "DWR_CONTINUOUS_GWL": {
            "status": "EXCLUDED_GEOGRAPHICALLY",
            "reason": "no Orange County stations in current dataset",
            "official_covered_counties": counties,
            "metadata_modified": package.get("metadata_modified"),
            "metadata_sha256": sha256_file(RAW / "dwr_continuous_groundwater_levels_package.json"),
            "large_data_tables_downloaded": False,
        }
    }
    write_json(PROVENANCE / "DWR_CONTINUOUS_GWL_STATUS.json", result)
    return result


def build_usgs_river() -> dict[str, object]:
    site = read_usgs_rdb(RAW / "usgs" / "USGS_11074000_site.rdb")
    daily = read_usgs_rdb(RAW / "usgs" / "USGS_11074000_discharge_daily.rdb")
    recent = read_usgs_rdb(RAW / "usgs" / "USGS_11074000_discharge_instantaneous_recent.rdb")
    value_col = next(column for column in daily if column.endswith("_00060_00003"))
    qa_col = f"{value_col}_cd"
    river = pd.DataFrame({
        "agency": daily["agency_cd"],
        "site_no": daily["site_no"],
        "timestamp": pd.to_datetime(daily["datetime"], errors="coerce"),
        "discharge_cfs": pd.to_numeric(daily[value_col], errors="coerce"),
        "qualification_qa": daily[qa_col],
        "unit": "ft3/s",
        "statistic": "daily mean",
        "site_timezone": site.iloc[0]["tz_cd"],
        "site_observes_daylight_saving": site.iloc[0]["local_time_fg"],
        "coordinate_datum": site.iloc[0]["dec_coord_datum_cd"],
        "elevation_datum": site.iloc[0]["alt_datum_cd"],
        "evidence_class": "OBSERVED",
    })
    iv_value = next(column for column in recent if column.endswith("_00060"))
    iv = pd.DataFrame({
        "agency": recent["agency_cd"],
        "site_no": recent["site_no"],
        "timestamp_local": pd.to_datetime(recent["datetime"], errors="coerce"),
        "timezone": recent["tz_cd"],
        "discharge_cfs": pd.to_numeric(recent[iv_value], errors="coerce"),
        "qualification_qa": recent[f"{iv_value}_cd"],
        "unit": "ft3/s",
        "evidence_class": "OBSERVED",
    })
    river.to_parquet(DERIVED / "USGS_11074000_SANTA_ANA_RIVER_DAILY.parquet", index=False)
    iv.to_parquet(DERIVED / "USGS_11074000_SANTA_ANA_RIVER_IV_RECENT.parquet", index=False)
    summary = {
        "site_no": "11074000",
        "station_name": site.iloc[0]["station_nm"],
        "latitude": float(site.iloc[0]["dec_lat_va"]),
        "longitude": float(site.iloc[0]["dec_long_va"]),
        "coordinate_datum": site.iloc[0]["dec_coord_datum_cd"],
        "gage_elevation": float(site.iloc[0]["alt_va"]),
        "gage_elevation_datum": site.iloc[0]["alt_datum_cd"],
        "timezone": site.iloc[0]["tz_cd"],
        "daylight_saving_flag": site.iloc[0]["local_time_fg"],
        "n_daily_records": int(len(river)),
        "earliest_daily_record": river["timestamp"].min(),
        "latest_daily_record": river["timestamp"].max(),
        "daily_qa_counts": {str(k): int(v) for k, v in river["qualification_qa"].value_counts(dropna=False).items()},
        "n_recent_instantaneous_records": int(len(iv)),
        "external_observed_forcing": True,
    }
    write_json(TABLES / "USGS_11074000_COVERAGE.json", summary)
    return summary


REPORT_FIELDS = {
    "Water Purchases from MWD (excludes In Lieu)": "REPORTED_MEASURED",
    "SAR & Santiago Creek Flows": "DERIVED_FROM_MEASUREMENTS",
    "GWRS Water to Forebay": "REPORTED_MEASURED",
    "GWRS Water to Mid-Basin Injection Wells": "REPORTED_MEASURED",
    "GWRS Water to Talbert Barrier": "REPORTED_MEASURED",
    "Alamitos Barrier Water": "REPORTED_MEASURED",
    "Incidental Recharge (estimated)": "ESTIMATED",
    "Evaporation from Recharge Basins": "ESTIMATED",
    "Total Groundwater Recharge": "DERIVED_FROM_MEASUREMENTS",
    "GROUNDWATER PRODUCTION": "REPORTED_MEASURED",
    "Change in Groundwater Storage": "DERIVED_FROM_MEASUREMENTS",
    "Month-End Water Storage in Recharge Facilities": "DERIVED_FROM_MEASUREMENTS",
    "Water Storage Change in Recharge Facilities": "DERIVED_FROM_MEASUREMENTS",
    "Total Artificial Recharge": "DERIVED_FROM_MEASUREMENTS",
}


def first_numeric_after(text: str, label: str) -> float:
    index = text.find(label)
    if index < 0:
        raise ValueError(f"Missing report field: {label}")
    for line in text[index + len(label):].splitlines():
        token = line.strip().replace(",", "")
        negative = token.startswith("(") and token.endswith(")")
        if negative:
            token = token[1:-1]
        try:
            value = float(token)
            return -value if negative else value
        except ValueError:
            continue
    raise ValueError(f"No numeric value after field: {label}")


def build_recent_water_resources_reports() -> pd.DataFrame:
    rows = []
    for month in ("2025_07", "2026_01", "2026_07"):
        path = RAW / "ocwd" / f"water_resources_report_{month}.pdf"
        document = pymupdf.open(path)
        text = document[0].get_text()
        for field, evidence_class in REPORT_FIELDS.items():
            rows.append({
                "report_month": month.replace("_", "-"),
                "field": field,
                "monthly_value": first_numeric_after(text, field),
                "unit": "acre-feet",
                "measurement_class": evidence_class,
                "source_file": path.relative_to(ROOT).as_posix(),
                "pdf_page": 1,
                "pdf_table_or_section": "WATER RESOURCES SUMMARY — INFLOWS & OUTFLOWS / OTHER KEY INFORMATION",
                "extraction_method": "native PDF text; first monthly value after published field label",
                "independent_validation_allowed": field not in {"Change in Groundwater Storage", "Water Storage Change in Recharge Facilities"},
                "caveat": "Preliminary report; total/accounting fields can include measured, calculated, and estimated components.",
            })
    frame = pd.DataFrame(rows)
    frame.to_csv(TABLES / "OCWD_RECENT_WATER_RESOURCES_REPORT_FIELDS.csv", index=False)
    write_markdown_table(
        TABLES / "OCWD_RECENT_WATER_RESOURCES_REPORT_FIELDS.md", frame,
        "Representative current OCWD monthly Water Resources Report fields",
        "This compact three-report sample demonstrates the accounting schema. It is not a substitute for the requested WRMS time series. Calculated storage change is not independent observed validation.",
    )
    return frame


HISTORICAL_FACILITIES = [
    ("Anaheim Lake", 72, 2260), ("Burris Basin", 120, 2670), ("Conrock Basin", 25, 1070),
    ("Five Coves Basin: Lower", 16, 182), ("Five Coves Basin: Upper", 15, 164),
    ("Foster-Huckleberry Basin", 21, 630), ("Kraemer Basin", 31, 1170),
    ("La Jolla Basin", 6.5, 26), ("Lincoln Basin", 10, 60), ("Little Warner Basin", 11, 225),
    ("Miller Basin", 25, 300), ("Mini-Anaheim Lake", 5, 13), ("Off-River Channel", 89, np.nan),
    ("Olive Basin", 5.8, 122), ("Placentia Basin", 9, 350), ("Raymond Basin", 19, 370),
    ("River View Basin", 3.6, 11), ("Santa Ana River: Imperial Highway to Orangewood Avenue", 291, np.nan),
    ("Santiago Basins", 187, 13720), ("Santiago Creek: Santiago Basins to Hart Park", 2.6, np.nan),
    ("Warner Basin", 70, 2620), ("Weir Pond 1", 6, 28), ("Weir Pond 2", 9, 42),
    ("Weir Pond 3", 14, 160), ("Weir Pond 4", 4, 22),
]

JULY_2009_PERCOLATION = [
    ("River System", 4600, "Average percolation of 74 cfs"),
    ("Desilting System", 87, "estimated based on observations"),
    ("Off-River System", 250, "includes Olive Pit"),
    ("Warner System", 621, "includes Foster-Huckleberry and Conrock basins"),
    ("Anaheim Lake", 2112, "inflow from MWD OC-28 and Warner Basin"),
    ("Mini-Anaheim Lake", 43, "all inflow from MWD OC-28"),
    ("Kraemer Basin", 1626, "inflow from MWD OC-28 and GWRS"),
    ("Miller Basin", 1798, "all inflow from GWRS"),
    ("La Jolla Basin", 0, "no inflow"), ("Placentia Basin", 0, "not in use"),
    ("Raymond Basin", 40, "no inflow"), ("Five Coves Basin", 0, "empty"),
    ("Burris Basin", 61, "no inflow"), ("River View Basin", 0, "not in use"),
    ("Santiago Basins", 1335, "no inflow; recharge of stored water"),
    ("Santiago Creek", 0, "not in use"),
]


def build_historical_recharge_extract() -> None:
    inventory = pd.DataFrame(HISTORICAL_FACILITIES, columns=["facility", "maximum_wetted_area_acres", "maximum_storage_capacity_af"])
    inventory["source_file"] = "data/raw/ocwd/groundwater_recharge_report_2009_2010.pdf"
    inventory["pdf_page"] = 25
    inventory["pdf_table"] = "Table 4-1"
    inventory["measurement_class"] = "REPORTED_MEASURED"
    inventory["note"] = "Facility design/reference attributes; not monthly forcing."
    inventory.to_csv(TABLES / "OCWD_RECHARGE_FACILITY_INVENTORY_2009_2010.csv", index=False)

    percolation = pd.DataFrame(JULY_2009_PERCOLATION, columns=["facility_or_system", "calculated_percolation_af", "reported_remarks"])
    percolation["month"] = "2009-07"
    percolation["measurement_class"] = "DERIVED_FROM_MEASUREMENTS"
    percolation["source_file"] = "data/raw/ocwd/groundwater_recharge_report_2009_2010.pdf"
    percolation["pdf_page"] = 83
    percolation["pdf_table"] = "Forebay Percolation Efficiency Report"
    percolation["extraction_method"] = "native PDF text plus visual spot-check against rendered page"
    percolation["visual_spot_check"] = "PASS"
    percolation.to_csv(TABLES / "OCWD_HISTORICAL_RECHARGE_JULY_2009_PERCOLATION.csv", index=False)

    accounting = pd.DataFrame([
        ("total_inflow", 9878, "DERIVED_FROM_MEASUREMENTS", "contains reported/measured and estimated source components"),
        ("estimated_evaporative_losses", 340, "ESTIMATED", "based on 500 acres of open-water surface"),
        ("storage_change", -3036, "DERIVED_FROM_MEASUREMENTS", "water levels converted through facility storage-elevation relationships"),
        ("calculated_percolation", 12573, "DERIVED_FROM_MEASUREMENTS", "total inflow minus losses and storage change"),
    ], columns=["field", "value_af", "measurement_class", "method_caveat"])
    accounting["month"] = "2009-07"
    accounting["source_file"] = "data/raw/ocwd/groundwater_recharge_report_2009_2010.pdf"
    accounting["pdf_pages"] = "83-84"
    accounting["pdf_tables"] = "Tables 1-3 and Summary; Percolation Basin Monthly Summary"
    accounting["extraction_method"] = "native PDF text plus visual spot-check against rendered pages 83-84"
    accounting["visual_spot_check"] = "PASS"
    accounting.to_csv(TABLES / "OCWD_HISTORICAL_RECHARGE_ACCOUNTING_DIAGNOSTIC.csv", index=False)

    methods = pd.DataFrame([
        ("surface water flows", "flumes, weirs, ultrasonic, propeller, and magnetic flow meters", "REPORTED_MEASURED", 61),
        ("recharge facility water levels", "pressure transducers, air-pressure orifice lines, and staff gages", "OBSERVED", 61),
        ("facility storage", "water level plus digitized topographic storage-elevation relationship", "DERIVED_FROM_MEASUREMENTS", 62),
        ("facility percolation", "storage change with inflow and outflow", "DERIVED_FROM_MEASUREMENTS", 62),
        ("incidental recharge", "estimated by comparing basin water levels/storage", "ESTIMATED", 62),
    ], columns=["quantity", "reported_method", "measurement_class", "pdf_page"])
    methods["source_file"] = "data/raw/ocwd/groundwater_recharge_report_2009_2010.pdf"
    methods.to_csv(TABLES / "OCWD_HISTORICAL_RECHARGE_METHODS.csv", index=False)
    (PROVENANCE / "PDF_EXTRACTION_SPOT_CHECK.md").write_text(
        "# PDF extraction spot-check\n\n"
        "The native-text extract from the OCWD 2009-2010 recharge report was visually checked against rendered PDF pages 83-84. "
        "The July 2009 Forebay report shows total inflow 9,878 acre-feet, total losses 340 acre-feet, storage change -3,036 acre-feet, "
        "and calculated percolation 12,573 acre-feet. Facility rows transcribed to `OCWD_HISTORICAL_RECHARGE_JULY_2009_PERCOLATION.csv` "
        "sum to the published 12,573 acre-feet. Page 84 confirms the reported facility storage/percolation columns and notes where lack of instrumentation requires estimates.\n\n"
        "No OCR or graph-pixel digitization was used.\n"
    )


def build_document_fact_ledger() -> pd.DataFrame:
    rows = [
        ("BASIN_MODEL_TRANSIENT_PERIOD", "November 1990-November 1999", "ocwd/basin_model_appendix_b.pdf", "50", "Appendix B states the nine-year transient period used the then-most-detailed head, production, and recharge data."),
        ("BASIN_MODEL_TEMPORAL_INPUT", "monthly flow and water-level data", "ocwd/basin_model_appendix_b.pdf", "50", "Appendix B reports more than 50 calibration runs using monthly flow and water-level data."),
        ("BASIN_MODEL_TARGET_SCALE", "almost 250 target locations", "ocwd/basin_model_appendix_b.pdf", "50", "Targets were densely distributed and covered all three model layers."),
        ("BASIN_MODEL_PRODUCTION_PROVENANCE", "monthly production extracted from WRMS", "ocwd/basin_model_appendix_b.pdf", "56", "Large-system well pumping was used directly and allocated vertically using screened intervals."),
        ("BASIN_MODEL_RECHARGE_PROVENANCE", "monthly recharge recorded in WRMS from 1990-present", "ocwd/basin_model_appendix_b.pdf", "56", "Documented as based on OCWD Forebay observed percolation measurements and used as model input."),
        ("WRMS_LARGE_WELL_REPORTING", "individual large-well monthly reporting since 1990", "ocwd/groundwater_management_plan_2004.pdf", "14; 60", "Large-capacity well owners report production monthly for each well into WRMS."),
        ("LARGE_WELL_EXTRACTION_SHARE", "about 200 wells account for 97 percent of extraction", "ocwd/groundwater_management_plan_2004.pdf", "14; 60", "Documentation establishes expected WRMS production coverage but is not the raw pumping table."),
        ("MONITORING_SCALE_2004", "more than 1,000 water-level measurement points, mainly monthly or bimonthly", "ocwd/groundwater_management_plan_2004.pdf", "61", "The 2004 plan documents a richer OCWD monitoring system than the public DWR subset necessarily contains."),
        ("AQUIFER_SYSTEMS", "Shallow, Principal, and Deep systems", "ocwd/groundwater_location_maps_page.html", "HTML", "OCWD presents the Basin Model as three separate layers; no depth-threshold reassignment is made here."),
        ("RECHARGE_NETWORK_2022", "25 surface-water facilities with more than 25,000 acre-feet storage", "ocwd/basin_8_001_alternative_2022_update.pdf", "92", "OCWD reports daily tracking and a monthly Water Resources Summary."),
        ("MONTHLY_ACCOUNTING_SCHEMA", "source volumes, estimated percolation, pumping, and estimated storage change", "ocwd/basin_8_001_alternative_2022_update.pdf", "92", "The report explicitly mixes reported/measured, derived, and estimated quantities."),
        ("DWR_CONTINUOUS_GEOGRAPHY", "Orange County absent from covered counties", "dwr_continuous_groundwater_levels_package.json", "metadata", "The separate DWR continuous dataset is excluded geographically; no data table was forced into the audit."),
    ]
    frame = pd.DataFrame(rows, columns=["fact_id", "verified_value", "source_file", "source_page", "interpretation"])
    frame["verification_status"] = "VERIFIED"
    frame.to_csv(TABLES / "CORE_DOCUMENT_FACTS_LEDGER.csv", index=False)
    return frame


def build_mbi_forcing_and_events() -> tuple[pd.DataFrame, pd.DataFrame]:
    injection_values = [
        ("2023-01", 6.26, 193.92, 595.11, 1.68, 5.17),
        ("2023-02", 6.52, 182.52, 560.12, 1.70, 5.21),
        ("2023-03", 5.86, 181.70, 557.62, 1.84, 5.66),
        ("2023-04", 6.33, 189.75, 582.32, 1.29, 3.97),
        ("2023-05", 6.82, 211.40, 648.76, 1.46, 4.47),
        ("2023-06", 6.97, 209.00, 641.40, 1.29, 3.96),
        ("2023-07", 7.04, 218.21, 669.66, 1.28, 3.93),
        ("2023-08", 5.49, 170.04, 521.83, 2.11, 6.48),
        ("2023-09", 7.15, 214.59, 658.55, 1.36, 4.18),
        ("2023-10", 6.98, 216.42, 664.17, 1.29, 3.95),
        ("2023-11", 7.26, 217.81, 668.43, 1.49, 4.58),
        ("2023-12", 6.13, 190.00, 583.09, 1.32, 4.04),
    ]
    forcing = pd.DataFrame(injection_values, columns=["month", "average_daily_injection_mgd", "total_injection_mg", "total_injection_af", "backwash_mg", "backwash_af"])
    forcing["facility_scope"] = "combined MBI-1 through MBI-5 project"
    forcing["measurement_class"] = "REPORTED_MEASURED"
    forcing["source_file"] = "data/raw/ocwd/gwrs_annual_report_2023.pdf"
    forcing["pdf_page"] = 202
    forcing["pdf_table"] = "Table 7-2"
    forcing["caveat"] = "Public table is project-total, not monthly injection by individual well."
    forcing.to_csv(TABLES / "OCWD_MBI_2023_MONTHLY_INJECTION.csv", index=False)
    published_totals = pd.DataFrame([
        ("total_injection_mg", 2395.35, float(forcing["total_injection_mg"].sum())),
        ("total_injection_af", 7351.06, float(forcing["total_injection_af"].sum())),
        ("total_backwash_mg", 18.12, float(forcing["backwash_mg"].sum())),
        ("total_backwash_af", 55.60, float(forcing["backwash_af"].sum())),
    ], columns=["quantity", "published_annual_total", "sum_of_published_rounded_months"])
    published_totals["rounding_difference"] = published_totals["sum_of_published_rounded_months"] - published_totals["published_annual_total"]
    published_totals["source_file"] = "data/raw/ocwd/gwrs_annual_report_2023.pdf"
    published_totals["pdf_page"] = 202
    published_totals["pdf_table"] = "Table 7-2"
    published_totals["evidence_class"] = "REPORTED_MEASURED"
    published_totals["note"] = "Use the published annual total; small differences from summed monthly rows are displayed rounding, not an inferred correction."
    published_totals.to_csv(TABLES / "OCWD_MBI_2023_REPORTED_TOTALS.csv", index=False)

    mbi1_monitors = "SAR-10/1-4; SAR-11/1-3"
    later_monitors = "SAR-12/1-4; SAR-13/1-4 (project-level; nearest-well relation does not imply fastest source)"
    events = []
    for well in ["MBI-1", "MBI-2", "MBI-3", "MBI-4", "MBI-5"]:
        first = well == "MBI-1"
        events.append({
            "event_id": f"{well}_OPERATIONAL_START",
            "start_date": "2015-04" if first else "2020-03-18",
            "date_precision": "MONTH" if first else "DAY",
            "facility_well": well,
            "aquifer": "Principal aquifer",
            "forcing_type": "managed injection of GWRS purified water",
            "monitoring_wells": mbi1_monitors if first else later_monitors,
            "source": "OCWD MBI 2020 operational notice; OCWD 2023 GWRS Annual Report pp. 213, 215",
            "evidence_class": "REPORTED_MEASURED",
            "future_validation_role": "held-out intervention-response timing and spatial propagation, conditional on raw injection and head series",
            "notes": "Event documented only; no response model fitted. Public 2023 report supplies combined monthly project injection, not a complete per-well event forcing history.",
        })
    events_frame = pd.DataFrame(events)
    events_frame.to_csv(TABLES / "EVENT_REGISTRY.csv", index=False)

    monitoring_screens = [
        ("SAR-10/1", "2012-05-10", "MBI-1", "80 ft SE", "590-600", "Upper Rho"),
        ("SAR-10/2", "2012-05-10", "MBI-1", "80 ft SE", "690-710", "Lower Rho"),
        ("SAR-10/3", "2012-05-10", "MBI-1", "80 ft SE", "800-820", "Main 2"),
        ("SAR-10/4", "2012-05-10", "MBI-1", "80 ft SE", "1100-1115", "Main 7"),
        ("SAR-11/1", "2011-11-10", "MBI-1", "650 ft SE", "592-602", "Upper Rho"),
        ("SAR-11/2", "2011-11-10", "MBI-1", "650 ft SE", "675-690", "Lower Rho"),
        ("SAR-11/3", "2011-11-10", "MBI-1", "650 ft SE", "1100-1110", "Main 7"),
        ("SAR-12/1", "2018-01-15", "MBI-2", "1000 ft SE", "605-625", "Lower Rho"),
        ("SAR-12/2", "2018-01-15", "MBI-2", "1000 ft SE", "755-775", "Main 2"),
        ("SAR-12/3", "2018-01-15", "MBI-2", "1000 ft SE", "915-930", "Main 4"),
        ("SAR-12/4", "2018-01-15", "MBI-2", "1000 ft SE", "1045-1055", "Main 7"),
        ("SAR-13/1", "2017-10-30", "MBI-5", "500 ft S", "600-620", "Lower Rho"),
        ("SAR-13/2", "2017-10-30", "MBI-5", "500 ft S", "750-770", "Main 2"),
        ("SAR-13/3", "2017-10-30", "MBI-5", "500 ft S", "910-930", "Main 4"),
        ("SAR-13/4", "2017-10-30", "MBI-5", "500 ft S", "1045-1055", "Main 7"),
    ]
    monitor_frame = pd.DataFrame(monitoring_screens, columns=["monitoring_well", "date_completed", "nearest_injection_well", "reported_distance_direction", "screen_interval_ft_bgs", "authoritative_aquifer_name"])
    monitor_frame["source_file"] = "data/raw/ocwd/gwrs_annual_report_2023.pdf"
    monitor_frame["pdf_page"] = 215
    monitor_frame["pdf_table"] = "Table 8-2"
    monitor_frame["evidence_class"] = "REPORTED_MEASURED"
    monitor_frame["assignment_method"] = "direct OCWD table; no depth-threshold inference"
    monitor_frame["caveat"] = "Nearest injection well is not necessarily the fastest source, per OCWD table note."
    monitor_frame.to_csv(TABLES / "MBI_MONITORING_WELL_SCREEN_REGISTRY.csv", index=False)
    return forcing, events_frame


REPEAT_TRACER_ROWS = [
    ("KBS-3/1", "<100", "44 to 41", "2.7", "4.7", "5.6", "<1.4", "<1.4", "incomplete"),
    ("AM-7", "130", "1 to -4", "10.6", "22.9", "25.4", "8.3", "15.1", "15.3"),
    ("AMD-12/1", "525", "-36 to -42", "16.6", "22.9", "30.5", "", "", ""),
    ("AM-48", "1250", "-20 to -29", "<16.6", "18.7", "25.7", "", "", ""),
    ("AM-8", "1250", "-26 to -31", "20.9", "", ">=37.1 incomplete", "17.7", "23.0", "38.3"),
    ("KBS-1/1", "<100", "4 to 1", "<1.6", "<1.6", "incomplete", "1.4", "1.4", ""),
    ("KB1", "<100", "13 to 7", "1.6", "3.6", "6.0", "2.6", "2.3", "3.7"),
    ("AM-10", "1000", "-3 to -8", "6.6", "20.9", "23.8", "15.1", "23.0", "28.4"),
    ("AMD-11/1", "1260", "-91 to -97", "6.7", "29.1", ">28 incomplete", "", "", ""),
    ("AM-9", "1840", "-26 to -31", "15.7", "26.6", "33.8", "26.4", "39.7", "50.6"),
    ("AM-14", "2630", "-32 to -38", "37.7", "37.7", "incomplete", "45.8", "", "67.9"),
]

LLNL_TRACER_ROWS = [
    ("AM-7", 2112, 57, 107, 167, 37, 19.7, 13), ("AM-8", 4750, 125, 280, 382, 38, 16.9, 12),
    ("SCWC-PLJ2", 6000, 224, 360, 619, 27, 16.6, 10), ("A-26", 8000, 335, 485, 800, 34, 16.6, 10),
    ("OCWD-KB1", 500, 19, 22, 38, 26, 19.2, 13), ("AM-10", 3875, 105, 230, 378, 37, 16.8, 10),
    ("AM-9", 6375, 185, 350, 512, 34, 18.2, 12), ("AM-14", 8875, 322, 512, 800, 28, 17.3, 11),
    ("A-27", 500, 13, 20, 67, 38.5, 18.5, 7.5), ("AM-44", 1500, 62, 91, 138, 24, 16.5, 11),
    ("AMD-10/1", 4000, None, 147, None, None, 27, None), ("AMD-10/2", 4000, None, 313, None, None, 12, None),
    ("AMD-10/3", 4000, None, 427, None, None, 9.4, None), ("AMD-10/4", 4000, None, 620, None, None, 6.5, None),
    ("OCWD-LV1", 1800, 77, 175, None, 23.3, 10.3, None), ("WBS2A/2", 2525, 91, 144, None, 27.7, 17.5, None),
]


def build_tracer_registry() -> pd.DataFrame:
    rows = []
    for well, distance, screen, j_first, j_peak, j_com, o_first, o_peak, o_com in REPEAT_TRACER_ROWS:
        for date, tracer, first, peak, com in [
            ("2008-01", "SF6", j_first, j_peak, j_com),
            ("1998-10", "136Xe", o_first, o_peak, o_com),
        ]:
            if not any([first, peak, com]):
                continue
            rows.append({
                "source_recharge_basin": "Kraemer Basin",
                "target_monitoring_or_production_well": well,
                "experiment_date": date,
                "date_precision": "MONTH",
                "tracer": tracer,
                "first_arrival": first,
                "peak_arrival": peak,
                "center_of_mass_arrival": com,
                "arrival_unit": "weeks",
                "distance": distance,
                "distance_unit": "m; shortest shoreline-to-well distance, not necessarily flow-path length",
                "screen_or_depth": screen,
                "screen_or_depth_unit": "m relative to mean sea level",
                "groundwater_velocity": "",
                "velocity_unit": "",
                "source_citation": "Clark et al. (2014), Water 6:1826-1839, Table 1",
                "source_file": "data/raw/journal/repeat_kraemer_basin_tracer_study_2014.pdf",
                "pdf_page": 10,
                "evidence_class": "OBSERVED",
                "future_validation_role": "independent physical connectivity/travel-response benchmark relative to a future fitted state model",
                "notes": "Published table value; inequalities and incomplete breakthroughs retained; no graph digitization.",
            })
    for well, distance, first, com, last, vmax, vmean, vmin in LLNL_TRACER_ROWS:
        rows.append({
            "source_recharge_basin": "See report flow-path/source grouping; Table 7 does not encode a source column",
            "target_monitoring_or_production_well": well,
            "experiment_date": "1995-2001 program",
            "date_precision": "STUDY_PERIOD",
            "tracer": "SF6 or xenon isotope as specified by report",
            "first_arrival": first if first is not None else "",
            "peak_arrival": "",
            "center_of_mass_arrival": com if com is not None else "",
            "arrival_unit": "days",
            "distance": distance,
            "distance_unit": "ft from recharge source",
            "screen_or_depth": "",
            "screen_or_depth_unit": "",
            "groundwater_velocity": vmean if vmean is not None else "",
            "velocity_unit": "ft/day mean; maximum and minimum retained in notes",
            "source_citation": "Davisson and Woodside (2003), LLNL UCRL-TR-201735, Table 7",
            "source_file": "data/raw/llnl/llnl_forebay_isotope_tracer_final_report.pdf",
            "pdf_page": 102,
            "evidence_class": "OBSERVED",
            "future_validation_role": "independent physical connectivity/travel-response benchmark relative to a future fitted state model",
            "notes": f"Published Table 7 only; last arrival={last}; maximum velocity={vmax}; minimum velocity={vmin}; no graph digitization.",
        })
    frame = pd.DataFrame(rows)
    frame.to_csv(TABLES / "TRACER_VALIDATION_REGISTRY.csv", index=False)
    return frame


def build_frequency_tables(well_master: pd.DataFrame) -> None:
    active = well_master.loc[well_master["n_observations"].fillna(0).gt(0)].copy()
    interval_bins = [-np.inf, 45, 90, 180, 365, 730, np.inf]
    interval_labels = ["<=45", "46-90", "91-180", "181-365", "366-730", ">730"]
    active["median_interval_bin_days"] = pd.cut(active["median_measurement_interval_days"], interval_bins, labels=interval_labels)
    interval_table = active.groupby("median_interval_bin_days", observed=False).size().rename("n_wells").reset_index()
    interval_table["share_of_wells_with_heads"] = interval_table["n_wells"] / len(active) if len(active) else np.nan
    interval_table.to_csv(TABLES / "DWR_OCWD_OBSERVATION_FREQUENCY_DISTRIBUTION.csv", index=False)

    observation_bins = [-np.inf, 1, 5, 12, 23, 59, 119, np.inf]
    observation_labels = ["1", "2-5", "6-12", "13-23", "24-59", "60-119", ">=120"]
    active["observation_count_bin"] = pd.cut(active["n_observations"], observation_bins, labels=observation_labels)
    count_table = active.groupby("observation_count_bin", observed=False).size().rename("n_wells").reset_index()
    count_table["share_of_wells_with_heads"] = count_table["n_wells"] / len(active) if len(active) else np.nan
    count_table.to_csv(TABLES / "DWR_OCWD_OBSERVATION_COUNT_DISTRIBUTION.csv", index=False)


def build_figures(feature: dict, dwr: dict[str, object]) -> None:
    well_master = dwr["well_master"]
    heads = dwr["heads"]
    annual = dwr["annual"]

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(9.2, 7.2))
    for ring in geometry_rings(feature["geometry"]):
        coords = np.asarray(ring)
        ax.plot(coords[:, 0], coords[:, 1], color="#303030", linewidth=1.3, label="DWR Basin 8-001 boundary")
    no_head = well_master.loc[well_master["n_observations"].fillna(0).eq(0)]
    has_head = well_master.loc[well_master["n_observations"].fillna(0).gt(0)]
    ax.scatter(no_head["longitude_numeric"], no_head["latitude_numeric"], s=17, color="#bdbdbd", marker="x", label=f"No usable head (n={len(no_head)})")
    ax.scatter(has_head["longitude_numeric"], has_head["latitude_numeric"], s=20, color="#1769aa", alpha=0.72, edgecolor="none", label=f"At least one usable head (n={len(has_head)})")
    ax.scatter([-117.6453296], [33.88334875], s=55, marker="^", color="#d95f02", label="USGS 11074000 (river forcing)")
    ax.set_xlabel("Longitude (geographic degrees)")
    ax.set_ylabel("Latitude (geographic degrees)")
    ax.set_title("Public DWR periodic groundwater-level station coverage\nBasin 8-001, point-in-polygon audit; no node selection")
    ax.legend(loc="best", fontsize=8, frameon=True)
    ax.set_aspect("equal", adjustable="datalim")
    fig.text(0.01, 0.01, "Evidence: OBSERVED heads; REFERENCE_MODEL boundary. Scope: public data availability, not model fit.", fontsize=8)
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    fig.savefig(FIGURES / "fig01_dwr_basin_head_station_coverage.png", dpi=220)
    fig.savefig(FIGURES / "fig01_dwr_basin_head_station_coverage.pdf")
    plt.close(fig)

    active = well_master.loc[well_master["n_observations"].fillna(0).gt(0)]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    intervals = active["median_measurement_interval_days"].dropna()
    axes[0].hist(intervals.clip(upper=1000), bins=[0, 45, 90, 180, 365, 730, 1000], color="#4477aa", edgecolor="white")
    axes[0].set_xlabel("Per-well median interval (days; >1000 clipped)")
    axes[0].set_ylabel("Wells")
    axes[0].set_title("Observation cadence")
    counts = active["n_observations"].dropna()
    axes[1].hist(np.log10(counts.clip(lower=1)), bins=20, color="#66aa55", edgecolor="white")
    axes[1].set_xlabel("log10 usable observations per well")
    axes[1].set_ylabel("Wells")
    axes[1].set_title("Series size")
    fig.suptitle(f"DWR periodic head-series frequency audit (n={len(active)} wells with usable heads)")
    fig.text(0.01, 0.01, "Evidence: OBSERVED. Usable = numeric head/time with Good or blank-as-good QA. No interpolation.", fontsize=8)
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    fig.savefig(FIGURES / "fig02_dwr_head_observation_frequency.png", dpi=220)
    fig.savefig(FIGURES / "fig02_dwr_head_observation_frequency.pdf")
    plt.close(fig)

    fig, axes = plt.subplots(2, 1, figsize=(11, 6.7), sharex=True)
    axes[0].plot(annual["year"], annual["n_wells"], color="#1769aa", linewidth=1.7)
    axes[0].axvspan(1990.83, 1999.92, color="#e69f00", alpha=0.16, label="documented Basin Model calibration period")
    axes[0].set_ylabel("Unique wells/year")
    axes[0].legend(fontsize=8)
    axes[1].plot(annual["year"], annual["n_observations"], color="#5c8f3a", linewidth=1.5)
    axes[1].set_ylabel("Usable observations/year")
    axes[1].set_xlabel("Calendar year")
    fig.suptitle("DWR periodic public head coverage through time")
    fig.text(0.01, 0.01, "Evidence: OBSERVED public DWR records. Shading is documentary calibration-period context, not a fitted benchmark.", fontsize=8)
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    fig.savefig(FIGURES / "fig03_dwr_head_temporal_coverage.png", dpi=220)
    fig.savefig(FIGURES / "fig03_dwr_head_temporal_coverage.pdf")
    plt.close(fig)

    usable = heads.loc[heads["usable_head"]].copy()
    class_counts = []
    for collector, group in usable.groupby("coop_org_name", dropna=False):
        classifications = group.apply(lambda row: classify_origin(row["coop_org_name"], row["wlm_org_name"])[0], axis=1)
        class_counts.append({"collector": collector or "blank", "n_observations": len(group), "n_wells": group["site_code"].nunique(), "dominant_independence_class": classifications.mode().iloc[0]})
    pd.DataFrame(class_counts).sort_values("n_observations", ascending=False).to_csv(TABLES / "DWR_OCWD_SOURCE_INDEPENDENCE_SUMMARY.csv", index=False)


def build_gap_matrix() -> pd.DataFrame:
    rows = [
        ("well master", "YES", "PARTIAL", "YES", "OBSERVED", "well", "static", "DWR public stations plus Orange WCR supplement", "PARTIAL", "YES", "OCWD IDs/names, owner/producer, activity dates, authoritative coordinates and datum, well role"),
        ("groundwater heads", "YES", "PARTIAL", "YES", "OBSERVED", "well", "irregular periodic", "DWR public subset; full OCWD network documented but not released", "PARTIAL", "YES", "full WRMS series, methods, QA, datum, pumping-status flag, revision history"),
        ("screen intervals", "YES", "PARTIAL", "YES", "REPORTED_MEASURED", "well/casing", "static", "DWR periodic perforations and WCR supplement", "PARTIAL", "YES", "authoritative OCWD screens/casing identity and revisions for material wells"),
        ("aquifer-layer mapping", "YES", "PARTIAL", "NO", "REFERENCE_MODEL", "well/model layer", "static", "explicit for selected MBI wells; basinwide mapping not public", "NO", "YES", "authoritative OCWD aquifer and Basin Model layer assignment by well/screen"),
        ("per-well pumping", "YES", "DOCUMENTATION_ONLY", "NO", "REPORTED_MEASURED", "individual production well", "monthly", "WRMS existence since 1990 documented; raw table absent", "NO", "YES", "well ID, month, volume, unit, metered/reported versus allocated/estimated, QA and revisions, coordinates"),
        ("recharge-facility forcing", "YES", "PARTIAL", "NO", "DERIVED_FROM_MEASUREMENTS", "named basin/facility", "monthly in historical PDF", "2009-10 detailed public report plus recent aggregate reports", "PARTIAL", "YES", "1990-present machine-readable facility inflow/outflow/storage/percolation/source/QA series"),
        ("injection-well forcing", "YES", "PARTIAL", "NO", "REPORTED_MEASURED", "MBI project; individual wells documented", "monthly project total for 2023", "public report has MBI project total, not complete per-well history", "PARTIAL", "YES", "well/casing/date/volume/aquifer zone, operational flags, QA, backwash status, full 1990-present history"),
        ("river forcing", "YES", "YES", "YES", "OBSERVED", "USGS 11074000 gage", "daily plus recent 15-minute", "1940-present daily discharge", "YES", "NO", "none for upstream gage forcing; downstream routing/diversion records still needed for facility forcing"),
        ("monthly basin accounting", "YES", "PARTIAL", "NO", "DERIVED_FROM_MEASUREMENTS", "basin", "monthly", "current PDFs and historical report schema", "PARTIAL", "YES", "machine-readable historical components, definitions, revisions, source shares, and QA"),
        ("storage reference", "YES", "PARTIAL", "NO", "DERIVED_FROM_MEASUREMENTS", "basin", "monthly", "reported calculated storage change", "NO_AS_INDEPENDENT_VALIDATION", "YES", "underlying heads/storage coefficients and calculation version; must not validate against its own pumping/recharge accounting"),
        ("tracer validation", "YES", "YES", "NO", "OBSERVED", "recharge basin to monitoring/production well", "sparse experiments", "LLNL/DOE and peer-reviewed reported travel quantities", "PARTIAL", "YES", "raw sample time series, QA, injection history, contemporary pumping/recharge, and exact screen/coordinate metadata if releasable"),
        ("intervention events", "YES", "YES", "YES", "REPORTED_MEASURED", "MBI well/project", "event date", "MBI-1 April 2015; MBI-2 through MBI-5 March 18 2020", "PARTIAL", "YES", "complete per-well forcing and unaffected/affected monitoring-head histories around events"),
        ("MODFLOW reference package", "CONDITIONAL", "DOCUMENTATION_ONLY", "NO", "REFERENCE_MODEL", "grid/cell/layer", "stress-period", "model design and calibration documented; package absent", "NO", "YES", "discretization, properties, boundaries, stresses, observations/weights/statistics, representative outputs"),
        ("wastewater flows", "NO_CURRENTLY_SECONDARY", "PARTIAL", "PARTIAL", "REPORTED_MEASURED", "OC San plant/permit", "annual public summaries; DMR varies", "OC San reports and EPA ICIS/permit inventory", "NOT_BLOCKING", "NO", "monthly plant-to-GWRS allocation only if a later source-accounting question requires it"),
    ]
    columns = ["data_requirement", "scientifically_required", "currently_public", "raw_machine_readable", "evidence_class", "spatial_resolution", "temporal_resolution", "coverage", "sufficient", "request_required", "exact_missing_fields"]
    frame = pd.DataFrame(rows, columns=columns)
    frame.to_csv(FEASIBILITY / "DATA_REQUIREMENT_GAP_MATRIX.csv", index=False)
    write_markdown_table(
        FEASIBILITY / "DATA_REQUIREMENT_GAP_MATRIX.md", frame,
        "OCWD data-requirement gap matrix",
        "Sufficiency is for future held-out dynamic estimation, not for fitting in this audit. Documentation that a database exists is not treated as public raw data.",
    )
    return frame


def build_gate_assessment(summary: dict[str, object], tracer: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    n_state = int(summary["n_with_usable_head_observations"])
    common5 = int(summary["max_wells_observed_in_every_year_of_a_5y_window"])
    common10 = int(summary["max_wells_observed_in_every_year_of_a_10y_window"])
    monthly_run = summary["longest_consecutive_monthly_support_run_at_50_wells"]
    n_perf = int(summary["n_with_perforation_metadata"])
    g1 = "PASS" if n_state >= 50 else "FAIL"
    g2 = "PASS" if common5 >= 50 and int(monthly_run.get("consecutive_months", 0)) >= 60 else ("PARTIAL" if common5 > 0 else "FAIL")
    g8 = "PASS" if n_state >= 75 and common5 >= 50 else ("PARTIAL" if n_state >= 50 else "FAIL")
    rows = [
        ("G1", "STATE", g1, f"{n_state} public DWR wells have usable head observations; threshold is 50."),
        ("G2", "TEMPORAL", g2, f"Best annual intersection: {common5} wells in every year of a 5-year window and {common10} in every year of a 10-year window. Longest consecutive monthly run with at least 50 observed wells is {monthly_run.get('consecutive_months', 0)} months ({monthly_run.get('start_month', '')} to {monthly_run.get('end_month', '')}); individual cadence remains heterogeneous."),
        ("G3", "PUMPING", "PENDING_REQUEST", "OCWD documents monthly large-well WRMS reporting covering about 97% of extraction, but geocoded per-well raw pumping is not public in this package."),
        ("G4", "RECHARGE", "PARTIAL", "Named-facility 2009-10 recharge and 2023 combined MBI monthly injection are reproducibly extractable, but complete geocoded monthly facility/well forcing is not public."),
        ("G5", "VERTICAL", "PARTIAL" if n_perf > 0 else "FAIL", f"DWR perforations cover {n_perf} basin stations and MBI screens/layers are authoritative for that project; basinwide authoritative aquifer/model-layer mapping is missing."),
        ("G6", "PROVENANCE", "PASS", "The audit distinguishes OBSERVED, REPORTED_MEASURED, DERIVED_FROM_MEASUREMENTS, ESTIMATED, MODELED, and REFERENCE_MODEL quantities."),
        ("G7", "COMMON SUPPORT", "PENDING_REQUEST", "Public heads cannot yet be aligned with absent per-well WRMS pumping and complete facility/well recharge histories."),
        ("G8", "SPATIAL VALIDATION", g8, "Public state locations are counted without performance-based selection; final held-out-well design remains conditional on cadence, vertical identity, and forcing overlap."),
        ("G9", "INDEPENDENT PROPAGATION VALIDATION", "PASS" if len(tracer) and len(events) else "FAIL", f"Registry contains {len(tracer)} published tracer experiment-well records and {len(events)} MBI operational-start events; independence from future model fitting is explicit."),
        ("G10", "REPRODUCIBILITY", "PENDING_REQUEST", "Public DWR/USGS data are machine-readable and report extracts are page-traceable, but required WRMS pumping/recharge tables are not public."),
    ]
    frame = pd.DataFrame(rows, columns=["gate", "name", "status", "evidence"])
    frame.to_csv(FEASIBILITY / "FEASIBILITY_GATES.csv", index=False)
    write_markdown_table(FEASIBILITY / "FEASIBILITY_GATES.md", frame, "Preregistered feasibility-gate results", "Thresholds are research-design gates, not physical laws. No source was selected to force a pass.")
    status = {
        "PUBLIC_DATA_ONLY_STATUS": "PARTIAL",
        "PUBLIC_DATA_ONLY_TIER": "TIER_C",
        "PUBLIC_DATA_ONLY_INTERPRETATION": "Public data support an aggregate water-budget benchmark and useful state/propagation audits, but not a well/facility dynamic benchmark because per-well pumping and complete geocoded recharge/injection forcing are missing.",
        "EXPECTED_STATUS_WITH_OCWD_WRMS": "TIER_A_CANDIDATE",
        "EXPECTED_STATUS_CAVEAT": "Tier A remains conditional on common support, authoritative well/screen/layer identity, QA, and sufficient locations reserved for untouched spatial validation.",
        "gate_results": frame.to_dict(orient="records"),
    }
    write_json(FEASIBILITY / "FINAL_FEASIBILITY_STATUS.json", status)
    return frame


def build_secondary_inventory() -> None:
    manifest = pd.read_csv(PROVENANCE / "RAW_DOWNLOAD_HASH_MANIFEST.csv")
    selected = manifest.loc[manifest["local_path"].str.startswith("ocsan_epa/")]
    lines = [
        "# OC San / EPA secondary data inventory",
        "",
        "Wastewater is deliberately secondary and does not delay the groundwater-feasibility conclusion.",
        "",
        "- OC San's reports index and FY 2024-25 Resource Protection report provide public annual influent/effluent context; they do not identify monthly groundwater pumping or recharge-facility forcing.",
        "- Joint EPA/State permit CA0110604 (Order R8-2021-0010) covers OC San Reclamation Plant No. 1, Treatment Plant No. 2, collection system, and outfalls.",
        "- EPA ECHO publishes ICIS-NPDES permit-limit and Discharge Monitoring Report datasets by fiscal year/jurisdiction; the ICIS guide documents permit and monitoring-data search fields.",
        "- No wastewater hydraulic model or broad DMR extraction was built.",
        "",
        "## Cached authoritative inventory",
        "",
    ]
    for row in selected.itertuples(index=False):
        lines.append(f"- `{row.local_path}` — SHA-256 `{row.sha256}` — {row.official_url}")
    (ROOT / "OCSAN_EPA_DATA_INVENTORY.md").write_text("\n".join(lines) + "\n")


def build_acquisition_ledger(manifest: pd.DataFrame) -> None:
    lines = [
        "# Authoritative raw-acquisition ledger",
        "",
        f"Access date: {ACCESSED_DATE}. Raw files are immutable inputs and are verified by `RAW_DOWNLOAD_HASH_MANIFEST.csv`.",
        "",
        "Acquisition used `curl -L --fail --retry 2` against each `official_url`. DWR WCR tables were retrieved through the official CKAN DataStore SQL API with an exact `COUNTYNAME = 'Orange'` filter and no fuzzy matching. The statewide periodic groundwater ZIP was retained intact; the deterministic build streams and filters its CSV members without extracting or rewriting the raw download.",
        "",
        "| Local raw path | Source ID | Bytes | SHA-256 | Official URL |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for row in manifest.itertuples(index=False):
        lines.append(f"| `{row.local_path}` | {row.source_id} | {row.bytes} | `{row.sha256}` | {row.official_url} |")
    (PROVENANCE / "ACQUISITION_LEDGER.md").write_text("\n".join(lines) + "\n")


def write_environment() -> None:
    write_json(PROVENANCE / "PYTHON_ENVIRONMENT.json", {
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "pandas_version": pd.__version__,
        "numpy_version": np.__version__,
        "pymupdf_version": pymupdf.__version__,
        "matplotlib_version": plt.matplotlib.__version__,
        "command": f"{sys.executable} scripts/build_feasibility_audit.py",
        "working_directory": str(ROOT),
        "groundwater_model_fitted": False,
    })


def write_final_report(summary: dict[str, object], gates: pd.DataFrame, wcr: pd.DataFrame, river: dict[str, object], tracer: pd.DataFrame) -> None:
    gate_lines = "\n".join(f"| {r.gate} {r.name} | {r.status} | {r.evidence} |" for r in gates.itertuples(index=False))
    report = f"""# OCWD groundwater data-feasibility audit

## Decision

`PUBLIC_DATA_ONLY_STATUS = PARTIAL`  
`PUBLIC_DATA_ONLY_TIER = TIER_C`  
`EXPECTED_STATUS_WITH_OCWD_WRMS = TIER_A_CANDIDATE`

The public package does not yet identify the joint state/forcing panel needed for a well/facility-resolution dynamic network benchmark. It does provide substantial public head coverage, an official basin geometry, long USGS river forcing, page-traceable recharge/injection accounting, intervention dates, and physical tracer benchmarks. The binding omission is the non-public WRMS well/facility time series—especially monthly geocoded per-well pumping, complete recharge/injection forcing, and authoritative vertical identity—with common QA and timestamps.

This is a data audit only. No groundwater dynamics, network, A/B matrix, VAR, state-space model, GNN, graphical model, MODFLOW calibration, interpolation, node selection, pumping inference, or optimization was performed.

## Public DWR head coverage

- DWR stations spatially inside Basin 8-001: **{summary['n_dwr_stations_inside']}**.
- Wells with usable head observations: **{summary['n_with_usable_head_observations']}**.
- Wells with at least 24 / 60 observations: **{summary['n_with_at_least_24_observations']} / {summary['n_with_at_least_60_observations']}**.
- Wells spanning at least 5 / 10 years: **{summary['n_spanning_at_least_5_years']} / {summary['n_spanning_at_least_10_years']}**.
- Wells overlapping Nov. 1990-Nov. 1999 / 2008+: **{summary['n_overlapping_1990_11_to_1999_11']} / {summary['n_overlapping_2008_plus']}**.
- Wells with DWR perforation metadata: **{summary['n_with_perforation_metadata']}** ({100*summary['share_with_perforation_metadata']:.1f}%).
- Usable observations: **{summary['n_usable_head_observations']}**, from {summary['earliest_usable_observation']} through {summary['latest_usable_observation']}.
- Median of per-well median intervals: **{summary['median_of_well_median_intervals_days']:.1f} days**; no interpolation.
- Strongest annual intersection: **{summary['max_wells_observed_in_every_year_of_a_5y_window']}** wells in each year of the best five-year window and **{summary['max_wells_observed_in_every_year_of_a_10y_window']}** in each year of the best ten-year window.
- Longest consecutive monthly support with at least 50 observed wells: **{summary['longest_consecutive_monthly_support_run_at_50_wells']['consecutive_months']} months**, {summary['longest_consecutive_monthly_support_run_at_50_wells']['start_month']} through {summary['longest_consecutive_monthly_support_run_at_50_wells']['end_month']}.

The DWR periodic dataset republishes cooperating-agency data. Among usable heads, source-origin classifications are {json.dumps(summary['usable_head_independence_counts'])}. The observation-independence ledger therefore identifies OCWD-origin records, clearly independent DWR/USGS collection, and unknown origin rather than double-counting a DWR copy as a second sensor.

## Supplementary construction and forcing evidence

The Orange-only WCR supplement yields match statuses: {json.dumps({str(k): int(v) for k, v in wcr['match_status'].value_counts().items()})}. WCR coordinates remain supplementary and never replace DWR monitoring-station coordinates. No Shallow/Principal/Deep layer was assigned from a depth threshold.

USGS 11074000 supplies {river['n_daily_records']} daily discharge records from {river['earliest_daily_record']} through {river['latest_daily_record']} with approval/estimate/provisional flags preserved. OCWD's historical recharge report shows facility-level measured-flow and water-level inputs, calculated storage/percolation, and estimated losses. The 2023 GWRS report supplies one year of combined MBI monthly injection, while per-well monthly forcing remains missing.

The tracer registry contains {len(tracer)} experiment-well records transcribed only from explicit LLNL/DOE and peer-reviewed tables. No graph pixels were digitized. These are future physical propagation checks, not targets used to fit this audit.

## Feasibility gates

| Gate | Result | Evidence |
| --- | --- | --- |
{gate_lines}

## Exact blocking data

1. WRMS monthly production by individual well, with coordinates/datum, screens/layers, metered/reported versus allocated/estimated status, QA, revisions, and active dates.
2. Complete monthly or finer managed surface-recharge records by named facility: source, inflow/outflow, storage, calculated percolation, units, QA, and measured/estimated components.
3. Monthly or finer injection by well/casing and aquifer zone, including operational/backwash flags and set/swap/revision history.
4. A common well/facility identity crosswalk tying heads, pumping, screens, OCWD aquifer names, Basin Model layers, coordinates, and activity periods.
5. Raw tracer/intervention supporting series if they are to be used for quantitative held-out response tests.

## Next action

Submit the drafted observational WRMS request in `requests/OCWD_WRMS_DATA_REQUEST.md` first, asking for 1990-01-01 through the latest available records. If volume is prohibitive, request the exact November 1990-November 1999 transient Basin Model calibration dataset. Keep the separate MODFLOW package request secondary: the empirical WRMS observations are the higher-priority gate-closing data.
"""
    (FEASIBILITY / "FINAL_FEASIBILITY_REPORT.md").write_text(report)


def write_output_hashes() -> None:
    candidates = sorted(
        path for base in (DERIVED, TABLES, FIGURES, PROVENANCE, FEASIBILITY, ROOT / "requests")
        for path in base.rglob("*") if path.is_file() and path.name not in {".gitkeep", "OUTPUT_HASHES.csv"}
    )
    rows = [{"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in candidates]
    pd.DataFrame(rows).to_csv(PROVENANCE / "OUTPUT_HASHES.csv", index=False)


def write_package_hashes() -> None:
    destination = PROVENANCE / "PACKAGE_FILE_HASHES.csv"
    files = sorted(path for path in ROOT.rglob("*") if path.is_file() and path.name != ".gitkeep" and path != destination)
    pd.DataFrame([
        {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in files
    ]).to_csv(destination, index=False)


def main() -> None:
    ensure_directories()
    write_environment()
    manifest = build_raw_manifest_and_registry()
    build_acquisition_ledger(manifest)
    feature, _ = select_basin()
    build_continuous_negative_result()
    dwr = build_dwr_periodic(feature)
    wcr = build_wcr_supplement(dwr["well_master"])
    river = build_usgs_river()
    build_recent_water_resources_reports()
    build_historical_recharge_extract()
    build_document_fact_ledger()
    _, events = build_mbi_forcing_and_events()
    tracer = build_tracer_registry()
    build_frequency_tables(dwr["well_master"])
    build_figures(feature, dwr)
    build_gap_matrix()
    gates = build_gate_assessment(dwr["summary"], tracer, events)
    build_secondary_inventory()
    write_final_report(dwr["summary"], gates, wcr, river, tracer)
    write_output_hashes()
    write_package_hashes()
    print(json.dumps({
        "status": "DATA_FEASIBILITY_AUDIT_COMPLETE",
        "public_data_only_status": "PARTIAL",
        "public_data_only_tier": "TIER_C",
        "expected_status_with_ocwd_wrms": "TIER_A_CANDIDATE",
        "dwr_coverage": dwr["summary"],
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
