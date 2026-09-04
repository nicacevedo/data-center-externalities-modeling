#!/usr/bin/env python3
"""Deterministic reporting build for the Andhra Pradesh planning preflight.

This module performs data/provenance audits only.  It does not fit a
groundwater model and it does not solve any planning model.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml


BASELINE = "975821ae679713cc6b2bcd984f2d16d4328289a8"
BUILD_TIMESTAMP = "2026-09-04T17:45:16Z"
PARENT_DIRS = (
    "other_sources/ocwd_groundwater_feasibility",
    "other_sources/ocwd_groundwater_gw1_preflight",
    "other_sources/ocwd_groundwater_gw1_climate",
    "other_sources/ocwd_groundwater_gw1b",
)

# Published extent in the CGWB Andhra Pradesh Ground Water Year Book 2024-25.
# This rectangular screen is a plausibility check, not a polygonal spatial join.
AP_ENVELOPE = {
    "latitude_min": 12.0 + 37.0 / 60.0,
    "latitude_max": 19.0 + 9.0 / 60.0,
    "longitude_min": 76.0 + 45.0 / 60.0,
    "longitude_max": 84.0 + 47.0 / 60.0,
}

RAW_SOURCES = {
    "gwl_manual_quarterly_cgwb_ap_1991_2020.csv": {
        "source_id": "NWDP_CGWB_GWL_AP_1991_2020",
        "url": "https://nwdp.nwic.gov.in/dataset/956add67-cba9-41a5-9d5c-96d73db44aef/resource/80fd198a-7d77-412c-87ab-bc6a61f11063/download/gwl_manual_quarterly_cgwb_ap_1991_2020.csv",
        "accessed_at": "2026-09-04T17:40:08Z",
        "expected_sha256": "9f8f48406abd579b10b6379d0177df743f1d427833eae80688576a4d1c9be017",
        "download_note": "Direct official NWDP CSV resource.",
    },
    "gwl_manual_quarterly_cgwb_ap_2021_2025.csv": {
        "source_id": "NWDP_CGWB_GWL_AP_2021_2025",
        "url": "https://nwdp.nwic.gov.in/dataset/956add67-cba9-41a5-9d5c-96d73db44aef/resource/31803a41-1025-4eae-8786-8efe29b1623c/download/gwl_manual_quarterly_cgwb_ap_2021_2025.csv",
        "accessed_at": "2026-09-04T17:40:10Z",
        "expected_sha256": "1bb1399deb6391566ca6ac4bfe1e255fd2a99eb19e32feca0de587839c504dbb",
        "download_note": "Direct official NWDP CSV resource; filename advertises 2021-2025, but downloaded rows end in 2023-08.",
    },
    "cgwb_andhra_pradesh_groundwater_yearbook_2024_25.pdf": {
        "source_id": "CGWB_AP_YEARBOOK_2024_25",
        "url": "https://cgwb.gov.in/cgwbpnm/download/2003",
        "accessed_at": "2026-09-04T17:41:39Z",
        "expected_sha256": "37353014cb7eccb457940fc70db78b2d2b46777b0efcdcbeb6cb3e6dc441d55c",
        "download_note": "Official CGWB publication repository; TLS verification was bypassed because the agency server presented an incomplete certificate chain.",
    },
    "cgwb_dynamic_groundwater_resources_andhra_pradesh_2024.pdf": {
        "source_id": "CGWB_AP_GWRA_2024",
        "url": "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/1748236616187388804file.pdf",
        "accessed_at": "2026-09-04T17:42:39Z",
        "expected_sha256": "d2e3c9d86665f250228c71045ea120709076c72d14b19cb9608a68a9a3b52bbf",
        "download_note": "Official CGWB PDF; TLS verification was bypassed because the agency server presented an incomplete certificate chain.",
    },
    "andhra_pradesh_data_center_policy_4_0_2024_29.pdf": {
        "source_id": "AP_DATA_CENTER_POLICY_4_0",
        "url": "https://apit.ap.gov.in/assets/files/Data%20Center%20Policy%20%284.0%29%202024-29.PDF",
        "accessed_at": "2026-09-04T17:43:26Z",
        "expected_sha256": "63d5fdafcc5fc7aa4e7e90bcd000a57ffcd9a0202f74d30b7a969971c0dd7ae0",
        "download_note": "Official Andhra Pradesh ITE&C policy PDF.",
    },
}

ALLOWED_EVIDENCE_CLASSES = {
    "OBSERVED",
    "REPORTED_MEASURED",
    "DERIVED_FROM_MEASUREMENTS",
    "ESTIMATED",
    "MODELED",
    "REFERENCE_MODEL",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args], cwd=repo, check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parent_dependency_manifest(repo: Path, module: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    status_lines: list[str] = []
    for parent in PARENT_DIRS:
        names = git(repo, "ls-tree", "-r", "--name-only", BASELINE, "--", parent).stdout.decode().splitlines()
        status = git(repo, "status", "--short", "--untracked-files=all", "--", parent).stdout.decode().splitlines()
        status_lines.extend(status)
        for rel in names:
            baseline_bytes = git(repo, "show", f"{BASELINE}:{rel}").stdout
            worktree_path = repo / rel
            worktree_sha = sha256_path(worktree_path) if worktree_path.is_file() else ""
            baseline_sha = sha256_bytes(baseline_bytes)
            rows.append(
                {
                    "parent_module": parent,
                    "path": rel,
                    "baseline_commit": BASELINE,
                    "exists_worktree": worktree_path.is_file(),
                    "baseline_blob_sha256": baseline_sha,
                    "worktree_sha256": worktree_sha,
                    "worktree_matches_baseline": bool(worktree_sha and worktree_sha == baseline_sha),
                }
            )
    out_csv = module / "outputs/provenance/FROZEN_PARENT_DEPENDENCY_MANIFEST.csv"
    write_csv(out_csv, rows, list(rows[0]))
    summary = {
        "baseline_commit": BASELINE,
        "generated_at": BUILD_TIMESTAMP,
        "parent_modules": list(PARENT_DIRS),
        "tracked_files_checked": len(rows),
        "all_tracked_files_match": all(row["worktree_matches_baseline"] for row in rows),
        "parent_status_lines": status_lines,
        "parent_modules_byte_integrity": "PASS"
        if rows and all(row["worktree_matches_baseline"] for row in rows) and not status_lines
        else "FAIL",
    }
    write_json(module / "outputs/provenance/FROZEN_PARENT_DEPENDENCY_MANIFEST.json", summary)
    if summary["parent_modules_byte_integrity"] != "PASS":
        raise RuntimeError("A frozen OCWD parent differs from the requested scientific baseline")
    return summary


def raw_manifest(module: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for filename, metadata in RAW_SOURCES.items():
        path = module / "data/raw" / filename
        actual = sha256_path(path) if path.is_file() else ""
        rows.append(
            {
                "source_id": metadata["source_id"],
                "filename": filename,
                "local_path": str(path.relative_to(module)),
                "official_url": metadata["url"],
                "accessed_at": metadata["accessed_at"],
                "bytes": path.stat().st_size if path.is_file() else 0,
                "sha256": actual,
                "expected_sha256": metadata["expected_sha256"],
                "hash_verified": actual == metadata["expected_sha256"],
                "download_note": metadata["download_note"],
            }
        )
    write_csv(module / "outputs/provenance/RAW_DOWNLOAD_MANIFEST.csv", rows, list(rows[0]))
    write_json(
        module / "outputs/provenance/RAW_DOWNLOAD_MANIFEST.json",
        {
            "generated_at": BUILD_TIMESTAMP,
            "all_hashes_verified": all(row["hash_verified"] for row in rows),
            "files": rows,
        },
    )
    if not all(row["hash_verified"] for row in rows):
        raise RuntimeError("A downloaded raw file is missing or differs from its pinned hash")
    return rows


def source_registry(module: Path) -> list[dict[str, Any]]:
    raw_sha = {v["source_id"]: v["expected_sha256"] for v in RAW_SOURCES.values()}
    rows = [
        {
            "source_id": "REPO_MASTER_NARRATIVE",
            "agency": "Project repository",
            "title": "Canonical project scientific narrative (read-only)",
            "official_url": "repository:main_documents/master.tex",
            "accessed_at": BUILD_TIMESTAMP,
            "temporal_coverage": "current at baseline commit",
            "spatial_resolution": "project-wide",
            "temporal_resolution": "not applicable",
            "raw_download_availability": "repository blob",
            "license_access_restriction": "repository access",
            "intended_use": "M0 semantic audit only",
            "evidence_class": "REFERENCE_MODEL",
            "limitations": "Narrative is not the PSCC implementation, manuscript, inputs, or frozen result.",
            "local_path": "external read-only dependency",
            "sha256": "83231ddc5cbf3b2682eab972da1254490b3e3178f588da027f92c89c4f830a06",
        },
        {
            "source_id": "NWDP_CGWB_GWL_QUARTERLY",
            "agency": "National Water Informatics Centre / Central Ground Water Board",
            "title": "Ground Water Level (Manual - Quarterly), CGWB",
            "official_url": "https://www.nwdp.nwic.gov.in/dataset/gwl-manual-quarterly-central-ground-water-board-department",
            "accessed_at": BUILD_TIMESTAMP,
            "temporal_coverage": "downloaded AP resources: 1994-01-05 to 2023-08-20; advertised resource bands 1991-2020 and 2021-2025",
            "spatial_resolution": "station records; state resource",
            "temporal_resolution": "nominal quarterly manual; some records more frequent",
            "raw_download_availability": "CSV and API; two AP CSVs downloaded",
            "license_access_restriction": "public portal; portal terms apply",
            "intended_use": "groundwater-state coverage and future local estimation feasibility",
            "evidence_class": "OBSERVED",
            "limitations": "No stable station ID, screen/layer, measurement method, or QA flag in downloaded files; substantial coordinate contamination and missing coordinates require source correction.",
            "local_path": "data/raw/gwl_manual_quarterly_cgwb_ap_1991_2020.csv; data/raw/gwl_manual_quarterly_cgwb_ap_2021_2025.csv",
            "sha256": f"{raw_sha['NWDP_CGWB_GWL_AP_1991_2020']};{raw_sha['NWDP_CGWB_GWL_AP_2021_2025']}",
        },
        {
            "source_id": "CGWB_AP_YEARBOOK_2024_25",
            "agency": "Central Ground Water Board",
            "title": "Ground Water Year Book 2024-25, Andhra Pradesh",
            "official_url": "https://cgwb.gov.in/cgwbpnm/publication-detail/2003",
            "accessed_at": BUILD_TIMESTAMP,
            "temporal_coverage": "long-term monitoring since 1969; 2024-25 reporting year",
            "spatial_resolution": "state, district, station-network aggregates",
            "temporal_resolution": "four manual rounds/year; 105 participatory wells described as weekly",
            "raw_download_availability": "PDF downloaded",
            "license_access_restriction": "public agency publication",
            "intended_use": "network counts, cadence, hydrogeology, source-method provenance",
            "evidence_class": "REPORTED_MEASURED",
            "limitations": "The text says 1,473 stations as of March 2025 while table/figure labels say March 2024; no machine-readable station master is included.",
            "local_path": "data/raw/cgwb_andhra_pradesh_groundwater_yearbook_2024_25.pdf",
            "sha256": raw_sha["CGWB_AP_YEARBOOK_2024_25"],
        },
        {
            "source_id": "CGWB_AP_GWRA_2024",
            "agency": "Central Ground Water Board and Andhra Pradesh Ground Water Department",
            "title": "Dynamic Ground Water Resources of Andhra Pradesh State 2024",
            "official_url": RAW_SOURCES["cgwb_dynamic_groundwater_resources_andhra_pradesh_2024.pdf"]["url"],
            "accessed_at": BUILD_TIMESTAMP,
            "temporal_coverage": "base year 2023-24; historical assessments summarized",
            "spatial_resolution": "679 assessment units/mandals; 748 micro-basins; district/state aggregates",
            "temporal_resolution": "annual assessment",
            "raw_download_availability": "PDF downloaded; no canonical tabular export located in this pass",
            "license_access_restriction": "public agency publication",
            "intended_use": "static extraction/recharge baseline and spatial-unit audit",
            "evidence_class": "ESTIMATED",
            "limitations": "GEC-2015/INGRES estimates are not metered monthly pumping or recharge forcing; assessment-unit boundary files and IDs still require acquisition/crosswalk.",
            "local_path": "data/raw/cgwb_dynamic_groundwater_resources_andhra_pradesh_2024.pdf",
            "sha256": raw_sha["CGWB_AP_GWRA_2024"],
        },
        {
            "source_id": "NWDP_CGWB_GWL_TELEMETRY",
            "agency": "National Water Informatics Centre / Central Ground Water Board",
            "title": "Ground Water Level (Telemetry - Hourly/Six Hourly), CGWB",
            "official_url": "https://www.nwdp.nwic.gov.in/en/dataset/ground-water-level-telemetry-hourly-central-ground-water-board-cgwb",
            "accessed_at": BUILD_TIMESTAMP,
            "temporal_coverage": "resource-dependent",
            "spatial_resolution": "telemetry station",
            "temporal_resolution": "hourly/six-hourly",
            "raw_download_availability": "CSV/API generally; no Andhra Pradesh resource was listed in the audited dataset page",
            "license_access_restriction": "public portal; AP access unresolved",
            "intended_use": "potential high-frequency state observations",
            "evidence_class": "OBSERVED",
            "limitations": "Do not infer AP telemetry availability from other-state resources. AP resource requires confirmation or agency access.",
            "local_path": "",
            "sha256": "",
        },
        {
            "source_id": "AP_GW_WATER_AUDIT_TELEMETRY",
            "agency": "Andhra Pradesh Ground Water and Water Audit Department",
            "title": "District departmental descriptions of piezometer/AWLR telemetry",
            "official_url": "https://nandyal.ap.gov.in/ground-water/",
            "accessed_at": BUILD_TIMESTAMP,
            "temporal_coverage": "current description; exact data period not published",
            "spatial_resolution": "departmental network; district/state scope ambiguous",
            "temporal_resolution": "hourly telemetry claimed; monthly manual monitoring also described",
            "raw_download_availability": "not located; dashboard access required",
            "license_access_restriction": "access required",
            "intended_use": "high-frequency data request target",
            "evidence_class": "REPORTED_MEASURED",
            "limitations": "Documentation of telemetry existence is not raw data and does not establish downloadable station coverage.",
            "local_path": "",
            "sha256": "",
        },
        {
            "source_id": "CGWB_NAQUIM_AP",
            "agency": "Central Ground Water Board",
            "title": "National Aquifer Mapping and Management reports for Andhra Pradesh",
            "official_url": "https://cgwb.gov.in/en/aquifer-mapping",
            "accessed_at": BUILD_TIMESTAMP,
            "temporal_coverage": "program initiated 2012; district/urban reports vary",
            "spatial_resolution": "typically 1:50,000; selected areas 1:10,000",
            "temporal_resolution": "reference characterization",
            "raw_download_availability": "PDF reports; machine-readable aquifer polygons/attributes not confirmed",
            "license_access_restriction": "public reports; GIS may require request",
            "intended_use": "authoritative aquifer/layer definitions and hydrogeologic constraints",
            "evidence_class": "REFERENCE_MODEL",
            "limitations": "Report coverage is heterogeneous; never infer well layers from depth thresholds.",
            "local_path": "",
            "sha256": "",
        },
        {
            "source_id": "INDIA_WRIS_NWIC",
            "agency": "National Water Informatics Centre / Central Water Commission",
            "title": "India-WRIS / National Water Data Portal",
            "official_url": "https://nwdp.nwic.gov.in/",
            "accessed_at": BUILD_TIMESTAMP,
            "temporal_coverage": "dataset-dependent",
            "spatial_resolution": "stations, watersheds, sub-basins, administrative units",
            "temporal_resolution": "dataset-dependent",
            "raw_download_availability": "CSV/API for listed datasets",
            "license_access_restriction": "public portal; dataset terms apply",
            "intended_use": "hydrologic boundaries, observations, and canonical identifiers",
            "evidence_class": "OBSERVED",
            "limitations": "Dataset-specific provenance and QA must be retained; portal labels alone do not certify current-state geography.",
            "local_path": "",
            "sha256": "",
        },
        {
            "source_id": "NRSC_BHUVAN",
            "agency": "ISRO National Remote Sensing Centre",
            "title": "Bhuvan thematic, LULC, AET, groundwater-prospect and hydrologic services",
            "official_url": "https://www.nrsc.gov.in/nrscnew/Services_Bhuvan_NaturalResourcesCensus.php",
            "accessed_at": BUILD_TIMESTAMP,
            "temporal_coverage": "product-dependent; LULC 2018-23 and daily AET advertised",
            "spatial_resolution": "product-dependent (10K/50K/250K themes; AET 750 m)",
            "temporal_resolution": "product-dependent",
            "raw_download_availability": "portal/request/OGC service depending product",
            "license_access_restriction": "some downloads require login/request/MOU",
            "intended_use": "land, irrigation, ET, hydrologic-boundary support",
            "evidence_class": "MODELED",
            "limitations": "Remote-sensing products are not well-level groundwater observations or measured abstraction.",
            "local_path": "",
            "sha256": "",
        },
        {
            "source_id": "NASA_GRACE_JPL",
            "agency": "NASA Jet Propulsion Laboratory / PO.DAAC",
            "title": "GRACE and GRACE-FO JPL Mascon RL06.3Mv04",
            "official_url": "https://doi.org/10.5067/TEMSC-3JC634",
            "accessed_at": BUILD_TIMESTAMP,
            "temporal_coverage": "2002-present subject to release latency/gaps",
            "spatial_resolution": "3-degree mascons; gridded presentation approximately 55.66 km",
            "temporal_resolution": "monthly",
            "raw_download_availability": "NetCDF via PO.DAAC",
            "license_access_restriction": "public NASA data; acknowledgment requested",
            "intended_use": "coarse complementary total-water-storage validation",
            "evidence_class": "DERIVED_FROM_MEASUREMENTS",
            "limitations": "Total terrestrial storage is coarse and cannot be labeled or used as local well-scale groundwater head.",
            "local_path": "",
            "sha256": "",
        },
        {
            "source_id": "NASA_MODIS_ET",
            "agency": "NASA LP DAAC / USGS",
            "title": "MOD16A2/A2GF Collection 6.1 evapotranspiration",
            "official_url": "https://lpdaac.usgs.gov/documents/931/MOD16_User_Guide_V61.pdf",
            "accessed_at": BUILD_TIMESTAMP,
            "temporal_coverage": "2000-present, product-dependent",
            "spatial_resolution": "500 m",
            "temporal_resolution": "8-day",
            "raw_download_availability": "HDF/LP DAAC services",
            "license_access_restriction": "public NASA data; Earthdata access may be required",
            "intended_use": "agricultural ET baseline candidate",
            "evidence_class": "MODELED",
            "limitations": "ET algorithm output is not metered irrigation demand or groundwater pumping.",
            "local_path": "",
            "sha256": "",
        },
        {
            "source_id": "DES_AGRICULTURE",
            "agency": "Directorate of Economics and Statistics, Ministry of Agriculture and Farmers Welfare",
            "title": "Area Production Statistics: APY and Land Use Statistics",
            "official_url": "https://aps.dac.gov.in/",
            "accessed_at": BUILD_TIMESTAMP,
            "temporal_coverage": "query-dependent historical annual series",
            "spatial_resolution": "state/district; crop/season",
            "temporal_resolution": "annual/seasonal",
            "raw_download_availability": "query/download portal",
            "license_access_restriction": "public portal",
            "intended_use": "irrigated/cropped area and crop baseline",
            "evidence_class": "REPORTED_MEASURED",
            "limitations": "Does not by itself identify groundwater withdrawal, crop ET, or groundwater dependence at a groundwater node.",
            "local_path": "",
            "sha256": "",
        },
        {
            "source_id": "CENSUS_INDIA",
            "agency": "Office of the Registrar General & Census Commissioner, India",
            "title": "Census of India population and administrative tables",
            "official_url": "https://censusindia.gov.in/census.website/data/census-tables",
            "accessed_at": BUILD_TIMESTAMP,
            "temporal_coverage": "2011 census; newer official census tables not available in this audit",
            "spatial_resolution": "village/town/district depending table",
            "temporal_resolution": "decennial",
            "raw_download_availability": "XLS/CSV/table-dependent",
            "license_access_restriction": "public official tables",
            "intended_use": "municipal population/service baseline",
            "evidence_class": "REPORTED_MEASURED",
            "limitations": "Outdated for present demand and not a municipal abstraction or service-boundary dataset.",
            "local_path": "",
            "sha256": "",
        },
        {
            "source_id": "CPCB_STP_2020",
            "agency": "Central Pollution Control Board",
            "title": "National Inventory of Sewage Treatment Plants (2020 inventory)",
            "official_url": "https://cpcb.nic.in/openpdffile.php?id=UmVwb3J0RmlsZXMvMTIyOF8xNjE1MTk2MzIyX21lZGlhcGhvdG85NTY0LnBkZg%3D%3D",
            "accessed_at": BUILD_TIMESTAMP,
            "temporal_coverage": "2020 inventory",
            "spatial_resolution": "state and facility listings",
            "temporal_resolution": "inventory snapshot",
            "raw_download_availability": "PDF",
            "license_access_restriction": "public agency publication",
            "intended_use": "wastewater generation/treatment/reuse feasibility screening",
            "evidence_class": "REPORTED_MEASURED",
            "limitations": "Statewide and aging; treatment capacity does not equal reusable water available to a candidate site.",
            "local_path": "",
            "sha256": "",
        },
        {
            "source_id": "AP_CDMA_SANITATION",
            "agency": "Andhra Pradesh Commissioner & Director of Municipal Administration",
            "title": "Andhra Pradesh State Sanitation Strategy",
            "official_url": "https://cdma.ap.gov.in/sites/default/files/State%20Sanitation%20Policy%20-%20Andhra%20.pdf",
            "accessed_at": BUILD_TIMESTAMP,
            "temporal_coverage": "policy baseline; current facility status requires update",
            "spatial_resolution": "state/ULB",
            "temporal_resolution": "policy document",
            "raw_download_availability": "PDF",
            "license_access_restriction": "public agency publication",
            "intended_use": "municipal wastewater/reuse policy and request routing",
            "evidence_class": "REFERENCE_MODEL",
            "limitations": "Policy intent is not evidence of current conveyable reuse capacity.",
            "local_path": "",
            "sha256": "",
        },
        {
            "source_id": "AP_DATA_CENTER_POLICY_4_0",
            "agency": "Andhra Pradesh ITE&C Department",
            "title": "Andhra Pradesh Data Center Policy 4.0, 2024-29",
            "official_url": RAW_SOURCES["andhra_pradesh_data_center_policy_4_0_2024_29.pdf"]["url"],
            "accessed_at": BUILD_TIMESTAMP,
            "temporal_coverage": "2024-29 policy period",
            "spatial_resolution": "statewide policy",
            "temporal_resolution": "policy",
            "raw_download_availability": "PDF downloaded",
            "license_access_restriction": "public official policy",
            "intended_use": "candidate-region policy context and infrastructure requirements",
            "evidence_class": "REFERENCE_MODEL",
            "limitations": "The policy target (up to 1 GW) is not a site list, source-water entitlement, or feasible optimization candidate set.",
            "local_path": "data/raw/andhra_pradesh_data_center_policy_4_0_2024_29.pdf",
            "sha256": raw_sha["AP_DATA_CENTER_POLICY_4_0"],
        },
        {
            "source_id": "ADANI_GOOGLE_VIZAG",
            "agency": "Adani Enterprises / Google project announcement",
            "title": "AI data-center campus in Visakhapatnam",
            "official_url": "https://www.adani.com/newsroom/media-releases/adani-and-google-partner-to-build-indias-largest-data-centre-campus-in-visakhapatnam",
            "accessed_at": BUILD_TIMESTAMP,
            "temporal_coverage": "announced 2025; planned 2026-30 investment period",
            "spatial_resolution": "Visakhapatnam; exact parcel/source boundary not supplied in announcement",
            "temporal_resolution": "project announcement",
            "raw_download_availability": "HTML",
            "license_access_restriction": "public company source",
            "intended_use": "documented project-region reference, not full planning candidate set",
            "evidence_class": "REFERENCE_MODEL",
            "limitations": "Company announcement is not an authoritative water-source, grid-interconnection, or groundwater-node crosswalk.",
            "local_path": "",
            "sha256": "",
        },
        {
            "source_id": "CEA_POWER_API",
            "agency": "Central Electricity Authority",
            "title": "CEA data API and power statistics",
            "official_url": "https://cea.nic.in/api-for-central-electricity-authority-data/?lang=en",
            "accessed_at": BUILD_TIMESTAMP,
            "temporal_coverage": "dataset-dependent/current",
            "spatial_resolution": "state/region/plant/transmission, dataset-dependent",
            "temporal_resolution": "monthly/annual, dataset-dependent",
            "raw_download_availability": "API and reports",
            "license_access_restriction": "public official source",
            "intended_use": "power-region, generation, renewable and adequacy baseline",
            "evidence_class": "REPORTED_MEASURED",
            "limitations": "Does not provide the project-specific interconnection queue, deliverability, or PSCC input bundle.",
            "local_path": "",
            "sha256": "",
        },
        {
            "source_id": "APTRANSCO",
            "agency": "Transmission Corporation of Andhra Pradesh",
            "title": "State transmission system information",
            "official_url": "https://aptransco.co.in/",
            "accessed_at": BUILD_TIMESTAMP,
            "temporal_coverage": "current/annual reports, dataset-dependent",
            "spatial_resolution": "substation/transmission network where published",
            "temporal_resolution": "snapshot/annual",
            "raw_download_availability": "reports/maps; canonical machine-readable network not located",
            "license_access_restriction": "public reports; detailed data may require request",
            "intended_use": "candidate-to-power-region/interconnection crosswalk",
            "evidence_class": "REPORTED_MEASURED",
            "limitations": "A service/network map is not proof of feasible data-center interconnection capacity.",
            "local_path": "",
            "sha256": "",
        },
    ]
    assert {row["evidence_class"] for row in rows} <= ALLOWED_EVIDENCE_CLASSES
    fields = list(rows[0])
    write_csv(module / "sources/AP_AUTHORITATIVE_SOURCE_REGISTRY.csv", rows, fields)
    with (module / "sources/AP_AUTHORITATIVE_SOURCE_REGISTRY.yaml").open("w", encoding="utf-8") as handle:
        yaml.safe_dump({"generated_at": BUILD_TIMESTAMP, "sources": rows}, handle, sort_keys=False)
    return rows


def _normalize_text(series: pd.Series) -> pd.Series:
    return series.astype("string").str.upper().str.replace(r"\s+", " ", regex=True).str.strip()


def load_groundwater(module: Path) -> pd.DataFrame:
    frames = []
    for filename in (
        "gwl_manual_quarterly_cgwb_ap_1991_2020.csv",
        "gwl_manual_quarterly_cgwb_ap_2021_2025.csv",
    ):
        frame = pd.read_csv(module / "data/raw" / filename)
        frame["source_file"] = filename
        frames.append(frame)
    raw = pd.concat(frames, ignore_index=True)
    raw["observation_time"] = pd.to_datetime(
        raw["Data Acquisition Time"], dayfirst=True, errors="coerce"
    )
    raw["head_depth_m_bgl"] = pd.to_numeric(
        raw["Groundwater Level Quarterly Manual (meter)"], errors="coerce"
    )
    raw["latitude"] = pd.to_numeric(raw["Latitude"], errors="coerce")
    raw["longitude"] = pd.to_numeric(raw["Longitude"], errors="coerce")
    raw["district_normalized"] = _normalize_text(raw["District"]).replace(
        {"KADAPA": "CUDDAPAH", "SRI POTTI SRIRAMULU NELLORE": "NELLORE"}
    )
    raw["station_name_normalized"] = _normalize_text(raw["Station"])
    raw["agency_normalized"] = _normalize_text(raw["Agency"])
    raw["measurement_class"] = "OBSERVED"
    raw["qa_flag_source"] = "NOT_PROVIDED_IN_DOWNLOADED_CSV"
    raw["numeric_observation"] = raw["observation_time"].notna() & raw["head_depth_m_bgl"].notna()
    raw["current_ap_label_screen"] = raw["district_normalized"].ne("KHAMMAM")
    raw["coordinate_present"] = raw[["latitude", "longitude"]].notna().all(axis=1)
    raw["coordinate_in_published_ap_envelope"] = (
        raw["latitude"].between(AP_ENVELOPE["latitude_min"], AP_ENVELOPE["latitude_max"])
        & raw["longitude"].between(AP_ENVELOPE["longitude_min"], AP_ENVELOPE["longitude_max"])
    )
    raw["spatial_qa_usable"] = (
        raw["numeric_observation"]
        & raw["current_ap_label_screen"]
        & raw["coordinate_in_published_ap_envelope"]
    )
    lat_token = raw["latitude"].round(6).map(lambda x: f"{x:.6f}" if pd.notna(x) else "MISSING")
    lon_token = raw["longitude"].round(6).map(lambda x: f"{x:.6f}" if pd.notna(x) else "MISSING")
    raw["name_key"] = (
        raw["agency_normalized"]
        + "|"
        + raw["district_normalized"]
        + "|"
        + raw["station_name_normalized"]
    )
    raw["series_id"] = raw["name_key"] + "|" + lat_token + "|" + lon_token
    return raw


def groundwater_outputs(module: Path) -> dict[str, Any]:
    raw = load_groundwater(module)
    raw_out = raw[
        [
            "source_file",
            "SlNo",
            "Station",
            "Agency",
            "State LGD Code",
            "State",
            "District LGD Code",
            "District",
            "Tehsil",
            "Block",
            "Village",
            "Basin",
            "RL_MSL",
            "Data Acquisition Time",
            "Groundwater Level Quarterly Manual (meter)",
            "observation_time",
            "head_depth_m_bgl",
            "latitude",
            "longitude",
            "district_normalized",
            "station_name_normalized",
            "agency_normalized",
            "name_key",
            "series_id",
            "measurement_class",
            "qa_flag_source",
            "numeric_observation",
            "current_ap_label_screen",
            "coordinate_present",
            "coordinate_in_published_ap_envelope",
            "spatial_qa_usable",
        ]
    ].copy()
    raw_out.to_parquet(module / "data/derived/AP_CGWB_GROUNDWATER_HEAD_OBSERVATIONS.parquet", index=False)

    usable = raw.loc[raw["spatial_qa_usable"]].copy()
    usable = usable.sort_values(["series_id", "observation_time", "head_depth_m_bgl", "source_file"])

    def station_row(group: pd.DataFrame) -> pd.Series:
        dates = pd.Series(group["observation_time"].drop_duplicates().sort_values().array)
        gaps = dates.diff().dt.total_seconds().div(86400).dropna()
        return pd.Series(
            {
                "station_name": group["Station"].iloc[0],
                "agency": group["Agency"].iloc[0],
                "district": group["district_normalized"].iloc[0],
                "latitude": group["latitude"].iloc[0],
                "longitude": group["longitude"].iloc[0],
                "n_raw_observations": len(group),
                "n_distinct_observation_times": len(dates),
                "earliest_observation": dates.min(),
                "latest_observation": dates.max(),
                "span_years": (dates.max() - dates.min()).days / 365.25 if len(dates) else np.nan,
                "median_interval_days": gaps.median() if len(gaps) else np.nan,
                "largest_gap_days": gaps.max() if len(gaps) else np.nan,
                "intervals_le_45_days": int((gaps <= 45).sum()),
                "intervals_le_90_days": int((gaps <= 90).sum()),
                "intervals_le_180_days": int((gaps <= 180).sum()),
                "qa_flags_available": False,
                "screen_layer_available": False,
                "stable_source_station_id_available": False,
                "measurement_class": "OBSERVED",
            }
        )

    station = usable.groupby("series_id", sort=True, group_keys=False).apply(
        station_row, include_groups=False
    )
    station.index.name = "series_id"
    station = station.reset_index()
    station.to_parquet(module / "data/derived/AP_CGWB_GROUNDWATER_STATION_SUMMARY.parquet", index=False)

    yearly = (
        usable.assign(year=usable["observation_time"].dt.year)
        .groupby("year")
        .agg(
            observations=("head_depth_m_bgl", "size"),
            station_location_series=("series_id", "nunique"),
            distinct_station_name_keys=("name_key", "nunique"),
            districts=("district_normalized", "nunique"),
        )
        .reset_index()
    )
    yearly.to_csv(module / "outputs/tables/AP_GROUNDWATER_YEAR_COVERAGE.csv", index=False)

    monthly = (
        usable.assign(month=usable["observation_time"].dt.to_period("M").astype(str))
        .groupby("month")
        .agg(
            observations=("head_depth_m_bgl", "size"),
            station_location_series=("series_id", "nunique"),
            distinct_station_name_keys=("name_key", "nunique"),
        )
        .reset_index()
    )
    monthly.to_csv(module / "outputs/tables/AP_GROUNDWATER_MONTHLY_COVERAGE.csv", index=False)

    district = (
        usable.groupby("district_normalized")
        .agg(
            observations=("head_depth_m_bgl", "size"),
            station_location_series=("series_id", "nunique"),
            distinct_station_name_keys=("name_key", "nunique"),
            first_observation=("observation_time", "min"),
            last_observation=("observation_time", "max"),
        )
        .reset_index()
        .rename(columns={"district_normalized": "district"})
    )
    district.to_csv(module / "outputs/tables/AP_GROUNDWATER_DISTRICT_COVERAGE.csv", index=False)

    coord_pairs_by_name = (
        usable[["name_key", "latitude", "longitude"]]
        .drop_duplicates()
        .groupby("name_key")
        .size()
    )
    date_conflicts = (
        usable.groupby(["series_id", "observation_time"])["head_depth_m_bgl"].nunique()
    )
    candidate_numeric = raw["numeric_observation"] & raw["current_ap_label_screen"]
    frequency = pd.cut(
        station["median_interval_days"],
        bins=[-np.inf, 45, 90, 180, np.inf],
        labels=["<=45", "46-90", "91-180", ">180"],
        right=True,
    ).astype("string")
    frequency = frequency.fillna("SINGLE_OBSERVATION")
    frequency_counts = Counter(frequency.tolist())

    metrics: dict[str, Any] = {
        "source": "NWDP/CGWB manual quarterly Andhra Pradesh CSV resources",
        "measurement_class": "OBSERVED",
        "no_interpolation": True,
        "raw_rows": int(len(raw)),
        "numeric_rows": int(raw["numeric_observation"].sum()),
        "numeric_rows_excluding_khammam_label": int(candidate_numeric.sum()),
        "numeric_khammam_rows_excluded_as_current_non_ap": int(
            (raw["numeric_observation"] & ~raw["current_ap_label_screen"]).sum()
        ),
        "candidate_rows_missing_coordinates": int(
            (candidate_numeric & ~raw["coordinate_present"]).sum()
        ),
        "candidate_rows_outside_published_ap_coordinate_envelope": int(
            (candidate_numeric & raw["coordinate_present"] & ~raw["coordinate_in_published_ap_envelope"]).sum()
        ),
        "spatial_qa_usable_rows": int(len(usable)),
        "spatial_qa_retention_percent": round(100.0 * len(usable) / candidate_numeric.sum(), 6),
        "distinct_name_keys_lower_bound": int(usable["name_key"].nunique()),
        "station_location_series_upper_bound": int(usable["series_id"].nunique()),
        "name_keys_with_multiple_coordinate_pairs": int((coord_pairs_by_name > 1).sum()),
        "series_date_groups_with_conflicting_values": int((date_conflicts > 1).sum()),
        "first_spatial_qa_usable_observation": usable["observation_time"].min().isoformat(),
        "last_spatial_qa_usable_observation": usable["observation_time"].max().isoformat(),
        "years_with_spatial_qa_usable_observations": int(usable["observation_time"].dt.year.nunique()),
        "district_labels_after_alias_normalization": int(usable["district_normalized"].nunique()),
        "series_with_at_least_24_distinct_times": int((station["n_distinct_observation_times"] >= 24).sum()),
        "series_with_at_least_60_distinct_times": int((station["n_distinct_observation_times"] >= 60).sum()),
        "series_spanning_at_least_5_years": int((station["span_years"] >= 5).sum()),
        "series_spanning_at_least_10_years": int((station["span_years"] >= 10).sum()),
        "median_distinct_observations_per_series": float(station["n_distinct_observation_times"].median()),
        "median_series_span_years": round(float(station["span_years"].median()), 6),
        "median_of_series_median_intervals_days": round(float(station["median_interval_days"].median()), 6),
        "frequency_category_series_counts": dict(sorted(frequency_counts.items())),
        "official_network_count_reported": 1473,
        "official_dug_wells_reported": 676,
        "official_piezometers_reported": 797,
        "official_participatory_weekly_wells_reported": 105,
        "official_primary_manual_cadence": "four rounds/year (May, August, November, January)",
        "official_count_date_discrepancy": "Yearbook prose says March 2025; Table 6.1 and Figure 1.1 say March 2024 for the same 1,473 total.",
        "advertised_2021_2025_resource_actual_last_date": raw.loc[
            raw["source_file"].str.contains("2021_2025"), "observation_time"
        ].max().isoformat(),
        "raw_qa_flags_present": False,
        "raw_screen_layer_fields_present": False,
        "raw_stable_station_id_present": False,
        "public_high_frequency_ap_machine_readable_status": "NOT_LOCATED",
        "dynamic_model_fit_performed": False,
    }
    write_json(module / "outputs/readiness/AP_GROUNDWATER_COVERAGE_STATUS.json", metrics)

    rows = [
        {"metric": key, "value": json.dumps(value, sort_keys=True) if isinstance(value, dict) else value}
        for key, value in metrics.items()
    ]
    write_csv(module / "outputs/tables/AP_GROUNDWATER_COVERAGE_SUMMARY.csv", rows, ["metric", "value"])
    md = [
        "# Andhra Pradesh public groundwater coverage audit",
        "",
        "Evidence class: `OBSERVED` for the downloaded groundwater-level values. No heads were interpolated and no groundwater model was fit.",
        "",
        "| Metric | Result |",
        "|---|---:|",
    ]
    for row in rows:
        md.append(f"| {row['metric']} | {row['value']} |")
    md.extend(
        [
            "",
            "## Identity and geography boundary",
            "",
            "The CSVs provide station names but no stable source station ID. `distinct_name_keys_lower_bound` counts normalized agency + district + name; `station_location_series_upper_bound` additionally distinguishes coordinate pairs. Neither is asserted to be the exact number of physical wells. The official current network count is taken from the CGWB yearbook.",
            "",
            "The coordinate screen uses the published state latitude/longitude envelope only. It is a QA plausibility screen, not a basin/state polygon join. Rows outside it are preserved in the raw and derived observation table and excluded only from spatial-coverage summaries.",
            "",
            "## Blocking limitations",
            "",
            "- No stable station ID, QA flag, measurement-method field, screen interval, or authoritative aquifer/layer is present in the downloaded CSVs.",
            "- The nominal 2021-2025 file ends in August 2023 in the downloaded artifact.",
            "- Thousands of rows have missing or geographically implausible coordinates, including clearly non-Andhra station names labeled as Anantapur.",
            "- Public AP high-frequency telemetry files were not listed in the audited NWDP CGWB telemetry dataset, despite state pages documenting telemetry existence.",
            "- Annual GWRA recharge/extraction estimates do not provide monthly observed forcing for local dynamic estimation.",
        ]
    )
    (module / "outputs/tables/AP_GROUNDWATER_COVERAGE_SUMMARY.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8"
    )

    _coverage_figure(module, usable, yearly, station, frequency)
    return metrics


def _coverage_figure(
    module: Path,
    usable: pd.DataFrame,
    yearly: pd.DataFrame,
    station: pd.DataFrame,
    frequency: pd.Series,
) -> None:
    unique_sites = usable[["series_id", "longitude", "latitude"]].drop_duplicates("series_id")
    fig, axes = plt.subplots(1, 3, figsize=(14.2, 4.6), constrained_layout=True)
    axes[0].scatter(unique_sites["longitude"], unique_sites["latitude"], s=4, alpha=0.45, color="#1f77b4")
    axes[0].set_title("A. Coordinate-plausible public series")
    axes[0].set_xlabel("Longitude (degrees east)")
    axes[0].set_ylabel("Latitude (degrees north)")
    axes[0].text(
        0.02,
        0.02,
        f"n={len(unique_sites):,} station-location series\n(envelope QA, not polygon join)",
        transform=axes[0].transAxes,
        fontsize=8,
        va="bottom",
    )

    axes[1].plot(yearly["year"], yearly["station_location_series"], marker="o", ms=3, lw=1.4, color="#2a6f97")
    axes[1].set_title("B. Series observed by year")
    axes[1].set_xlabel("Year")
    axes[1].set_ylabel("Distinct station-location series")
    axes[1].grid(alpha=0.25)

    order = ["SINGLE_OBSERVATION", "<=45", "46-90", "91-180", ">180"]
    counts = frequency.value_counts().reindex(order, fill_value=0)
    labels = ["single", "≤45", "46–90", "91–180", ">180"]
    axes[2].bar(labels, counts.values, color=["#a6a6a6", "#4c956c", "#80b918", "#f4a261", "#e76f51"])
    axes[2].set_title("C. Median within-series cadence")
    axes[2].set_xlabel("Median interval (days)")
    axes[2].set_ylabel("Station-location series")
    axes[2].tick_params(axis="x", rotation=20)
    for idx, value in enumerate(counts.values):
        axes[2].text(idx, value, f"{int(value):,}", ha="center", va="bottom", fontsize=8)

    fig.suptitle(
        "Andhra Pradesh public CGWB groundwater-head coverage\n"
        "OBSERVED manual measurements; no interpolation; 1996–2023 after coordinate-envelope QA",
        fontsize=12,
    )
    png = module / "outputs/figures/fig01_ap_groundwater_public_coverage.png"
    pdf = module / "outputs/figures/fig01_ap_groundwater_public_coverage.pdf"
    fig.savefig(png, dpi=220, metadata={"Software": "matplotlib; deterministic AP preflight"})
    fixed_dt = datetime(2026, 9, 4, 17, 45, 16, tzinfo=timezone.utc)
    fig.savefig(
        pdf,
        metadata={
            "Title": "Andhra Pradesh public groundwater coverage",
            "Author": "data-center-externalities-modeling",
            "CreationDate": fixed_dt,
            "ModDate": fixed_dt,
        },
    )
    plt.close(fig)


def track_a_status(module: Path) -> dict[str, Any]:
    payload = {
        "checked_once_at": "2026-09-04T17:37:06.846589+00:00",
        "check_scope": "repository-local project/user-provided paths only; no email or external account polling",
        "files_scanned": 5910,
        "ocwd_wrms_term_matches_reviewed": 7,
        "new_delivery_candidates": [],
        "all_matches_were_baseline_scientific_artifacts": True,
        "WRMS_PRESENT": False,
        "TRACK_A_STATUS": "WAITING_FOR_WRMS",
        "TRACK_A_DATA_GATE": "PENDING_DELIVERY",
        "S_STAR": "NOT_CONSTRUCTED_WITHOUT_WRMS",
        "B4_B5_B6_B7": "NOT_RUN",
        "placebos": "NOT_RUN",
        "tracer_mbi_validation": "NOT_TOUCHED",
        "NETWORK_MODEL_JUSTIFICATION": "UNRESOLVED",
    }
    write_json(module / "outputs/readiness/TRACK_A_WRMS_STATUS.json", payload)
    return payload


def module_hash_manifest(module: Path) -> list[dict[str, Any]]:
    excluded = {
        module / "outputs/provenance/MODULE_SHA256_MANIFEST.csv",
        module / "outputs/provenance/MODULE_SHA256_MANIFEST.json",
        # This audit records the manifest hashes, so excluding it avoids a
        # recursive self-reference while retaining every scientific artifact.
        module / "outputs/provenance/DETERMINISTIC_REPLAY_STATUS.json",
    }
    rows = []
    for path in sorted(module.rglob("*")):
        if not path.is_file() or path in excluded:
            continue
        if any(part in {"__pycache__", ".pytest_cache"} for part in path.parts):
            continue
        rows.append(
            {
                "path": str(path.relative_to(module)),
                "bytes": path.stat().st_size,
                "sha256": sha256_path(path),
            }
        )
    write_csv(module / "outputs/provenance/MODULE_SHA256_MANIFEST.csv", rows, list(rows[0]))
    write_json(
        module / "outputs/provenance/MODULE_SHA256_MANIFEST.json",
        {"generated_at": BUILD_TIMESTAMP, "file_count": len(rows), "files": rows},
    )
    return rows


def run_build(repo: Path) -> dict[str, Any]:
    module = repo / "other_sources/andhra_pradesh_planning_preflight"
    for rel in (
        "data/derived",
        "outputs/provenance",
        "outputs/tables",
        "outputs/figures",
        "outputs/readiness",
        "outputs/protocol",
    ):
        (module / rel).mkdir(parents=True, exist_ok=True)
    parent = parent_dependency_manifest(repo, module)
    raw = raw_manifest(module)
    sources = source_registry(module)
    heads = groundwater_outputs(module)
    track_a = track_a_status(module)
    return {
        "parent": parent,
        "raw_files": len(raw),
        "sources": len(sources),
        "groundwater": heads,
        "track_a": track_a,
    }


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[3]
    result = run_build(repo_root)
    print(json.dumps(result, indent=2, sort_keys=True))
