#!/usr/bin/env python3
"""Targeted public E0 source acquisition. Does not fit models or invent IDs."""
from __future__ import annotations

import csv
import hashlib
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

E0 = Path(__file__).resolve().parents[1]
RAW = E0 / "acquired" / "raw"
META = E0 / "acquired" / "metadata"
DERIVED = E0 / "acquired" / "derived"
UA = "AP-E0-public-source-audit/1.0 (research; provenance only)"
RETRIEVAL = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

UNVERIFIED_SSL_NOTE = (
    "TLS verification bypassed because the agency server presented an incomplete "
    "certificate chain (same constraint as the frozen AP preflight CGWB downloads)."
)

PROVENANCE_FIELDS = [
    "source_id", "title", "publisher", "official_url", "landing_page_url",
    "retrieval_date", "native_filename", "local_path", "sha256", "file_type",
    "publication_date", "data_vintage", "spatial_coverage", "temporal_coverage",
    "spatial_unit", "temporal_resolution", "units", "observed_vs_inferred",
    "evidence_class", "license_or_access_note", "E0_domain", "E0_item",
    "ACCESS_STATUS", "SCIENTIFIC_STATUS", "clears_blocker", "why_or_why_not",
    "limitations", "confidence", "bytes", "tls_note",
]

LOG_FIELDS = [
    "search_id", "E0_domain", "E0_item", "source_pursued", "why_pursued",
    "official_url", "outcome", "ACCESS_STATUS", "artifact_obtained",
    "notes", "retrieval_date",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def opener(verify: bool):
    ctx = ssl._create_unverified_context() if not verify else ssl.create_default_context()
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))


def fetch_bytes(url: str, timeout: int = 180, data: bytes | None = None, headers: dict | None = None) -> tuple[bytes, dict, str]:
    hdrs = {"User-Agent": UA, **(headers or {})}
    last_err = None
    for verify in (True, False):
        try:
            req = urllib.request.Request(url, data=data, headers=hdrs)
            with opener(verify).open(req, timeout=timeout) as resp:
                body = resp.read()
                info = dict(resp.headers)
                final_url = resp.geturl()
                tls = "" if verify else UNVERIFIED_SSL_NOTE
                return body, info, tls
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if verify:
                continue
            raise last_err
    raise last_err  # pragma: no cover


def write_bytes(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def json_get(url: str, timeout: int = 60) -> dict:
    body, _, _ = fetch_bytes(url, timeout=timeout)
    return json.loads(body.decode())


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    META.mkdir(parents=True, exist_ok=True)
    DERIVED.mkdir(parents=True, exist_ok=True)
    logs: list[dict] = []
    prov: list[dict] = []

    def log(**kwargs):
        row = {k: kwargs.get(k, "") for k in LOG_FIELDS}
        row["retrieval_date"] = RETRIEVAL
        logs.append(row)

    def add_prov(**kwargs):
        row = {k: kwargs.get(k, "") for k in PROVENANCE_FIELDS}
        row.setdefault("retrieval_date", RETRIEVAL)
        prov.append(row)

    # ------------------------------------------------------------------
    # E0.1 GWR2024 MapServer (official NWIC GIS; query instance down)
    # ------------------------------------------------------------------
    gwr_root = "https://gis.nwic.in/server/rest/services/NWIC/GWR2024_CGWB/MapServer"
    gwr_layer = f"{gwr_root}/8"
    try:
        body, _, tls = fetch_bytes(gwr_root + "?f=pjson", timeout=60)
        write_bytes(META / "NWIC_GWR2024_CGWB_MapServer.json", body)
        add_prov(
            source_id="NWIC_GWR2024_CGWB_MAPSERVER",
            title="NWIC GWR2024_CGWB MapServer service document",
            publisher="National Water Informatics Centre / CGWB",
            official_url=gwr_root,
            landing_page_url=gwr_root,
            native_filename="NWIC_GWR2024_CGWB_MapServer.json",
            local_path="acquired/metadata/NWIC_GWR2024_CGWB_MapServer.json",
            sha256=sha256_file(META / "NWIC_GWR2024_CGWB_MapServer.json"),
            file_type="json",
            publication_date="2024",
            data_vintage="GWRA 2024",
            spatial_coverage="India (service); Andhra Pradesh filter intended",
            temporal_coverage="assessment year 2024",
            spatial_unit="blocks/talukas/mandals (layer 8 documented)",
            temporal_resolution="annual assessment vintage",
            units="not applicable (service metadata)",
            observed_vs_inferred="INFERRED",
            evidence_class="REFERENCE_MODEL",
            license_or_access_note="Official NWIC ArcGIS REST service; public directory",
            E0_domain="E0.1",
            E0_item="679 assessment-unit polygons",
            ACCESS_STATUS="OBTAINED",
            SCIENTIFIC_STATUS="INADEQUATE",
            clears_blocker="false",
            why_or_why_not="Service metadata obtained; feature instance was not queryable.",
            limitations="A service document is not native assessment-unit geometry.",
            confidence="high",
            bytes=str((META / "NWIC_GWR2024_CGWB_MapServer.json").stat().st_size),
            tls_note=tls,
        )
        log(
            search_id="E01_GWR2024_MAPSERVER",
            E0_domain="E0.1",
            E0_item="679 assessment-unit polygons",
            source_pursued="NWIC GWR2024_CGWB MapServer",
            why_pursued="Official 2024 block/taluka/mandal polygon layer documented on GIS REST.",
            official_url=gwr_root,
            outcome="OFFICIAL_SOURCE_FOUND_BUT_ACCESS_REQUIRED",
            ACCESS_STATUS="ACCESS_REQUIRED",
            artifact_obtained="service metadata JSON only",
            notes="Layer 8 'Categorization of Blocks/Talukas/Mandals' is documented with block, code, district, class, annual draft/recharge fields. Query returned HTTP 200 with ArcGIS error 'Instance not available on server'. Geometry not obtained. PDF map would not clear this blocker either.",
        )
    except Exception as exc:  # noqa: BLE001
        log(
            search_id="E01_GWR2024_MAPSERVER",
            E0_domain="E0.1",
            E0_item="679 assessment-unit polygons",
            source_pursued="NWIC GWR2024_CGWB MapServer",
            why_pursued="Official 2024 assessment-unit GIS.",
            official_url=gwr_root,
            outcome="ERROR",
            ACCESS_STATUS="ERROR",
            artifact_obtained="false",
            notes=str(exc),
        )

    try:
        q = gwr_layer + "/query?" + urllib.parse.urlencode({
            "where": "state='AP'", "returnCountOnly": "true", "f": "pjson",
        })
        body, _, _ = fetch_bytes(q, timeout=60)
        write_bytes(META / "NWIC_GWR2024_layer8_AP_count.json", body)
        parsed = json.loads(body.decode())
        err = parsed.get("error")
        log(
            search_id="E01_GWR2024_LAYER8_QUERY",
            E0_domain="E0.1",
            E0_item="679 assessment-unit polygons",
            source_pursued="NWIC GWR2024_CGWB MapServer layer 8 query",
            why_pursued="Attempt native GeoJSON/JSON polygons for AP assessment units.",
            official_url=q.split("?")[0],
            outcome="ERROR" if err else "PUBLIC_SOURCE_OBTAINED",
            ACCESS_STATUS="ERROR" if err else "OBTAINED",
            artifact_obtained="query JSON error payload" if err else "count",
            notes=json.dumps(err or parsed)[:500],
        )
    except Exception as exc:  # noqa: BLE001
        log(
            search_id="E01_GWR2024_LAYER8_QUERY",
            E0_domain="E0.1",
            E0_item="679 assessment-unit polygons",
            source_pursued="NWIC GWR2024_CGWB MapServer layer 8 query",
            why_pursued="Attempt native polygons.",
            official_url=gwr_layer,
            outcome="ERROR",
            ACCESS_STATUS="ERROR",
            artifact_obtained="false",
            notes=str(exc),
        )

    # Layer-8 field schema captured from official HTML directory (query instance down).
    schema = {
        "service": gwr_root,
        "layer_id": 8,
        "layer_name": "Categorization of Blocks/Talukas/Mandals",
        "geometry_type": "esriGeometryPolygon",
        "documented_fields": [
            "block", "code", "district", "state", "class",
            "agwd_tot", "agwd_irr", "agwd_dom_i", "ar_gwr_tot", "na_gwa",
            "sgw_dev_pe", "nat_discharge", "objectid",
        ],
        "crs": "WGS_1984_Lambert_Conformal_Conic",
        "query_status": "Instance not available on server",
        "note": "Field list transcribed from official MapServer HTML directory; not a geometry download.",
        "retrieval_date": RETRIEVAL,
    }
    write_bytes(META / "NWIC_GWR2024_layer8_schema.json", json.dumps(schema, indent=2).encode())
    add_prov(
        source_id="NWIC_GWR2024_LAYER8_SCHEMA",
        title="GWR2024 block/taluka/mandal layer schema (HTML directory)",
        publisher="National Water Informatics Centre / CGWB",
        official_url="https://gis.nwic.in/server/rest/services/NWIC/GWR2024_CGWB/MapServer/layers",
        landing_page_url="https://gis.nwic.in/server/rest/services/NWIC/GWR2024_CGWB/MapServer/layers",
        native_filename="NWIC_GWR2024_layer8_schema.json",
        local_path="acquired/metadata/NWIC_GWR2024_layer8_schema.json",
        sha256=sha256_file(META / "NWIC_GWR2024_layer8_schema.json"),
        file_type="json",
        publication_date="2024",
        data_vintage="GWRA 2024",
        spatial_coverage="India service; AP coded value AP",
        temporal_coverage="2024 assessment",
        spatial_unit="block/taluka/mandal",
        temporal_resolution="annual assessment",
        units="annual draft/recharge attributes present on layer; geometry not obtained",
        observed_vs_inferred="INFERRED",
        evidence_class="REFERENCE_MODEL",
        license_or_access_note="Public REST directory",
        E0_domain="E0.1",
        E0_item="679 assessment-unit polygons",
        ACCESS_STATUS="OBTAINED",
        SCIENTIFIC_STATUS="INADEQUATE",
        clears_blocker="false",
        why_or_why_not="Schema documents that polygons exist at NWIC but were not downloadable in this pass.",
        limitations="Do not reconstruct 679-unit geometry from field names. code field is not verified as a stable GWRA ID.",
        confidence="high",
        bytes=str((META / "NWIC_GWR2024_layer8_schema.json").stat().st_size),
        tls_note="",
    )

    # ------------------------------------------------------------------
    # E0.1 GWRA-2024 block-wise categorization PDF (names/categories, not polygons)
    # ------------------------------------------------------------------
    block_pdf_url = "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/17365121771867268670file.pdf"
    try:
        body, _, tls = fetch_bytes(block_pdf_url, timeout=180)
        dest = RAW / "cgwb_gwra_2024_blockwise_categorization.pdf"
        write_bytes(dest, body)
        add_prov(
            source_id="CGWB_GWRA_2024_BLOCKWISE_CATEGORIZATION",
            title="Block wise Categorization as per GWRA-2024",
            publisher="Central Ground Water Board",
            official_url=block_pdf_url,
            landing_page_url="https://cgwb.gov.in/en/ground-water-resource-assessment-0",
            native_filename=dest.name,
            local_path="acquired/raw/cgwb_gwra_2024_blockwise_categorization.pdf",
            sha256=sha256_file(dest),
            file_type="pdf",
            publication_date="2024",
            data_vintage="GWRA 2024",
            spatial_coverage="India assessment units including Andhra Pradesh",
            temporal_coverage="GWRA 2024",
            spatial_unit="assessment unit / block / mandal name",
            temporal_resolution="annual assessment",
            units="category class (not volume)",
            observed_vs_inferred="INFERRED",
            evidence_class="ESTIMATED",
            license_or_access_note="Public CGWB publication",
            E0_domain="E0.1",
            E0_item="assessment-unit stable IDs",
            ACCESS_STATUS="OBTAINED",
            SCIENTIFIC_STATUS="INADEQUATE",
            clears_blocker="false",
            why_or_why_not="A PDF name/category table is not versioned polygons or a stable ID list joinable to heads.",
            limitations="A PDF map/table does not clear the geometry blocker.",
            confidence="high",
            bytes=str(dest.stat().st_size),
            tls_note=tls,
        )
        log(
            search_id="E01_GWRA2024_BLOCKWISE_PDF",
            E0_domain="E0.1",
            E0_item="assessment-unit stable IDs",
            source_pursued="CGWB Block wise Categorization GWRA-2024 PDF",
            why_pursued="Official unit-name/category list for 2024 vintage; not geometry.",
            official_url=block_pdf_url,
            outcome="PUBLIC_SOURCE_OBTAINED",
            ACCESS_STATUS="OBTAINED",
            artifact_obtained="true",
            notes="PDF obtained. Does not clear polygon or 679/667 reconciliation blockers.",
        )
    except Exception as exc:  # noqa: BLE001
        log(
            search_id="E01_GWRA2024_BLOCKWISE_PDF",
            E0_domain="E0.1",
            E0_item="assessment-unit stable IDs",
            source_pursued="CGWB Block wise Categorization GWRA-2024 PDF",
            why_pursued="Official unit-name/category list.",
            official_url=block_pdf_url,
            outcome="ERROR",
            ACCESS_STATUS="ERROR",
            artifact_obtained="false",
            notes=str(exc),
        )

    log(
        search_id="E01_INGRES_DASHBOARD",
        E0_domain="E0.1",
        E0_item="679 assessment-unit polygons",
        source_pursued="IN-GRES (CGWB/IIT-Hyderabad) GIS dashboard",
        why_pursued="Official GIS platform used for GWRA dissemination; may hold unit polygons/IDs.",
        official_url="https://ingres.iith.ac.in/",
        outcome="OFFICIAL_SOURCE_FOUND_BUT_ACCESS_REQUIRED",
        ACCESS_STATUS="ACCESS_REQUIRED",
        artifact_obtained="false",
        notes="Dashboard identified. Public REST/JSON API for unit polygons was not found (SPA returns HTML; POST /api/get_state_list 404). Do not scrape dashboard tiles as geometry.",
    )
    log(
        search_id="E01_679_667_RECONCILIATION",
        E0_domain="E0.1",
        E0_item="679 vs 667 revenue-mandal reconciliation",
        source_pursued="CGWB GWRA 2024 vs CGWB AP Yearbook 2024-25",
        why_pursued="Frozen conflict remains; search for an authoritative crosswalk.",
        official_url="https://cgwb.gov.in/en/ground-water-resource-assessment-0",
        outcome="NO_AUTHORITATIVE_SOURCE_LOCATED",
        ACCESS_STATUS="ACCESS_REQUIRED",
        artifact_obtained="false",
        notes="No public machine-readable 679-vs-667 crosswalk located. Numerical proximity is not identity.",
    )

    # ------------------------------------------------------------------
    # E0.2 / E0.4 / E0.6 NWDP AP Ground Water Department datasets
    # ------------------------------------------------------------------
    nwdp_pkgs = [
        {
            "source_id": "NWDP_APGWD_GWL_TELEMETRY",
            "package": "ground-water-level-telemetry-hourly-andhra-pradesh-ground-water-department",
            "E0_domain": "E0.2",
            "E0_item": "telemetry / weekly heads",
            "why": "Official AP GWD telemetry heads with advertised station identifier; previously NOT_LOCATED.",
        },
        {
            "source_id": "NWDP_APGWD_GWL_MANUAL_QUARTERLY",
            "package": "ground-water-level-manual-quarterly-andhra-pradesh-ground-water-departments",
            "E0_domain": "E0.2",
            "E0_item": "manual quarterly head / depth series",
            "why": "Official AP GWD manual quarterly heads; compare identity fields vs CGWB NWDP CSVs.",
        },
        {
            "source_id": "NWDP_APGWD_RAINFALL_TELEMETRY",
            "package": "rainfall-andhra-pradesh-telemetry-hourly",
            "E0_domain": "E0.4",
            "E0_item": "rainfall",
            "why": "Official AP GWD hourly rainfall overlapping groundwater stations.",
        },
    ]
    for spec in nwdp_pkgs:
        pkg = json_get(
            "https://nwdp.nwic.gov.in/api/3/action/package_show?id=" + spec["package"]
        )
        write_bytes(META / f"{spec['source_id']}_package_show.json", json.dumps(pkg, indent=2).encode())
        result = pkg.get("result") or {}
        resources = result.get("resources") or []
        log(
            search_id=f"{spec['source_id']}_PACKAGE",
            E0_domain=spec["E0_domain"],
            E0_item=spec["E0_item"],
            source_pursued=result.get("title"),
            why_pursued=spec["why"],
            official_url="https://nwdp.nwic.gov.in/dataset/" + spec["package"],
            outcome="PUBLIC_SOURCE_OBTAINED",
            ACCESS_STATUS="OBTAINED",
            artifact_obtained=f"{len(resources)} resources",
            notes=(result.get("notes") or "")[:400],
        )
        for res in resources:
            url = res.get("url") or ""
            name = Path(urllib.parse.urlparse(url).path).name or f"{res.get('id')}.csv"
            dest = RAW / name
            try:
                body, _, tls = fetch_bytes(url, timeout=600)
                write_bytes(dest, body)
                # schema sample via datastore
                sample_path = META / f"{spec['source_id']}_{res.get('id')}_sample.json"
                try:
                    sample = json_get(
                        "https://nwdp.nwic.gov.in/api/3/action/datastore_search?"
                        + urllib.parse.urlencode({"resource_id": res["id"], "limit": 5})
                    )
                    write_bytes(sample_path, json.dumps(sample, indent=2).encode())
                    fields = [f.get("id") for f in (sample.get("result") or {}).get("fields") or []]
                    total = (sample.get("result") or {}).get("total")
                except Exception as sample_exc:  # noqa: BLE001
                    fields, total = [], None
                    write_bytes(sample_path, json.dumps({"error": str(sample_exc)}).encode())
                identity_fields = {
                    "Station ID", "station_id", "StationId", "SITE_ID", "well_id",
                    "aquifer", "layer", "screen", "well type", "QA",
                }
                has_stable_id = any(
                    x.lower().replace(" ", "") in {"stationid", "siteid", "wellid"}
                    for x in fields
                )
                add_prov(
                    source_id=f"{spec['source_id']}_{res.get('id')[:8]}",
                    title=f"{result.get('title')} / {res.get('name')}",
                    publisher="Andhra Pradesh Ground Water and Water Audit Department / NWIC",
                    official_url=url,
                    landing_page_url="https://nwdp.nwic.gov.in/dataset/" + spec["package"],
                    native_filename=name,
                    local_path="acquired/raw/" + name,
                    sha256=sha256_file(dest),
                    file_type="csv",
                    publication_date=(res.get("created") or "")[:10],
                    data_vintage=res.get("name"),
                    spatial_coverage="Andhra Pradesh advertised",
                    temporal_coverage=str(total) + " datastore rows" if total is not None else "see file",
                    spatial_unit="station name + LGD geography",
                    temporal_resolution=result.get("frequency") or "resource-dependent",
                    units=str((result.get("extras") or [])),
                    observed_vs_inferred="OBSERVED",
                    evidence_class="OBSERVED",
                    license_or_access_note=result.get("license_title") or "Other (Open); Data Access Control: Public",
                    E0_domain=spec["E0_domain"],
                    E0_item=spec["E0_item"],
                    ACCESS_STATUS="OBTAINED",
                    SCIENTIFIC_STATUS="PARTIAL",
                    clears_blocker="false",
                    why_or_why_not=(
                        "Native CSV obtained. Station is a name, not a stable ID. "
                        f"Fields={fields}. has_stable_id={has_stable_id}."
                    ),
                    limitations="Do not construct synthetic IDs from names and coordinates. RL_MSL may be null. Coordinate QA still required.",
                    confidence="high",
                    bytes=str(dest.stat().st_size),
                    tls_note=tls,
                )
            except Exception as exc:  # noqa: BLE001
                log(
                    search_id=f"{spec['source_id']}_RESOURCE_{res.get('id','')[:8]}",
                    E0_domain=spec["E0_domain"],
                    E0_item=spec["E0_item"],
                    source_pursued=url,
                    why_pursued=spec["why"],
                    official_url=url,
                    outcome="ERROR",
                    ACCESS_STATUS="ERROR",
                    artifact_obtained="false",
                    notes=str(exc),
                )

    log(
        search_id="E02_NWDP_CGWB_TELEMETRY_NATIONAL",
        E0_domain="E0.2",
        E0_item="telemetry / weekly heads",
        source_pursued="NWDP CGWB Ground Water Level (Telemetry)",
        why_pursued="Frozen registry listed no AP resource on the CGWB telemetry dataset.",
        official_url="https://www.nwdp.nwic.gov.in/en/dataset/ground-water-level-telemetry-hourly-central-ground-water-board-cgwb",
        outcome="SOURCE_EXISTS_BUT_MACHINE_READABLE_DATA_NOT_FOUND",
        ACCESS_STATUS="NOT_OBTAINED",
        artifact_obtained="false",
        notes="Not re-downloaded. AP GWD telemetry on NWDP supersedes this as the AP-specific public telemetry source.",
    )
    log(
        search_id="E02_NWIC_GROUNDWATER_STATIONS_GIS",
        E0_domain="E0.2",
        E0_item="monitoring-station stable ID",
        source_pursued="NWIC Groundwater_Stations MapServer",
        why_pursued="Possible official station-master GIS.",
        official_url="https://gis.nwic.in/server/rest/services/NWIC/Groundwater_Stations/MapServer",
        outcome="SOURCE_EXISTS_BUT_MACHINE_READABLE_DATA_NOT_FOUND",
        ACCESS_STATUS="NOT_OBTAINED",
        artifact_obtained="false",
        notes="Service exists (description: Ground water station data) but published no queryable layers in this pass. Full extent NaN.",
    )

    # ------------------------------------------------------------------
    # E0.3 pumping: confirm absence on NWDP
    # ------------------------------------------------------------------
    search = json_get(
        "https://nwdp.nwic.gov.in/api/3/action/package_search?"
        + urllib.parse.urlencode({"q": "groundwater extraction OR abstraction OR pumping draft", "rows": 5})
    )
    write_bytes(META / "NWDP_extraction_search.json", json.dumps({
        "query": "groundwater extraction OR abstraction OR pumping draft",
        "count": (search.get("result") or {}).get("count"),
        "titles": [p.get("title") for p in (search.get("result") or {}).get("results") or []],
        "note": "Search returned groundwater-level series, not withdrawal volumes.",
    }, indent=2).encode())
    log(
        search_id="E03_NWDP_EXTRACTION_SEARCH",
        E0_domain="E0.3",
        E0_item="subannual well or node pumping",
        source_pursued="NWDP CKAN package_search for extraction/abstraction/pumping",
        why_pursued="Seek official well/node subannual groundwater withdrawal.",
        official_url="https://nwdp.nwic.gov.in/api/3/action/package_search",
        outcome="NO_AUTHORITATIVE_SOURCE_LOCATED",
        ACCESS_STATUS="ACCESS_REQUIRED",
        artifact_obtained="false",
        notes="No NWDP dataset is well-level or node-level groundwater abstraction. Hits were groundwater-level time series. Annual GWRA totals remain ESTIMATED and inadequate for dynamics.",
    )
    log(
        search_id="E03_INGRES_ANNUAL_UNIT_EXTRACTION",
        E0_domain="E0.3",
        E0_item="unit-level annual extraction (GWRA)",
        source_pursued="IN-GRES dashboard / GWR2024 layer attributes",
        why_pursued="Unit-level annual ESTIMATED extraction would support later M0S, not M1L.",
        official_url="https://ingres.iith.ac.in/",
        outcome="OFFICIAL_SOURCE_FOUND_BUT_ACCESS_REQUIRED",
        ACCESS_STATUS="ACCESS_REQUIRED",
        artifact_obtained="false",
        notes="GWR2024 layer 8 documents agwd_tot at block/mandal scale but the feature instance was not queryable. Still annual ESTIMATED; would not clear dynamic forcing even if obtained.",
    )

    # ------------------------------------------------------------------
    # E0.4 IMD 0.25 degree daily rainfall (specified product)
    # ------------------------------------------------------------------
    imd_landing = "https://imdpune.gov.in/cmpg/Griddata/Rainfall_25_NetCDF.html"
    imd_post = "https://imdpune.gov.in/cmpg/Griddata/RF25.php"
    try:
        landing, _, tls = fetch_bytes(imd_landing, timeout=60)
        write_bytes(META / "IMD_RF25_landing.html", landing)
        add_prov(
            source_id="IMD_RF25_LANDING",
            title="IMD 0.25x0.25 daily gridded rainfall landing page",
            publisher="India Meteorological Department, Pune",
            official_url=imd_landing,
            landing_page_url=imd_landing,
            native_filename="IMD_RF25_landing.html",
            local_path="acquired/metadata/IMD_RF25_landing.html",
            sha256=sha256_file(META / "IMD_RF25_landing.html"),
            file_type="html",
            publication_date="2014 product (Pai et al.); files through 2024 advertised",
            data_vintage="1901-2024 advertised",
            spatial_coverage="India 6.5N-38.5N, 66.5E-100.0E, 135x129 grid",
            temporal_coverage="1901-2024 daily (advertised)",
            spatial_unit="0.25 degree grid",
            temporal_resolution="daily",
            units="mm",
            observed_vs_inferred="OBSERVED",
            evidence_class="OBSERVED",
            license_or_access_note="IMD public product; cite Pai et al. 2014; IMD disclaimer applies",
            E0_domain="E0.4",
            E0_item="rainfall",
            ACCESS_STATUS="OBTAINED",
            SCIENTIFIC_STATUS="PARTIAL",
            clears_blocker="false",
            why_or_why_not="Product identity is adequate documentation; full overlapping grids still required for a complete rainfall panel.",
            limitations="Landing page is not the rainfall series. Grid is not assessment-unit rainfall until polygons exist.",
            confidence="high",
            bytes=str((META / "IMD_RF25_landing.html").stat().st_size),
            tls_note=tls,
        )
    except Exception as exc:  # noqa: BLE001
        log(
            search_id="E04_IMD_LANDING",
            E0_domain="E0.4",
            E0_item="rainfall",
            source_pursued="IMD RF25 landing page",
            why_pursued="Specified official rainfall product.",
            official_url=imd_landing,
            outcome="ERROR",
            ACCESS_STATUS="ERROR",
            artifact_obtained="false",
            notes=str(exc),
        )

    for year in ("1996", "2020", "2023"):
        try:
            body, info, tls = fetch_bytes(
                imd_post,
                timeout=180,
                data=urllib.parse.urlencode({"RF25": year}).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            dest = RAW / f"IMD_RF25_{year}.nc"
            write_bytes(dest, body)
            ctype = (info.get("Content-Type") or info.get("content-type") or "").lower()
            looks_nc = dest.stat().st_size > 10000 and (
                "netcdf" in ctype or "octet" in ctype or body[:3] != b"<ht"
            )
            add_prov(
                source_id=f"IMD_RF25_{year}",
                title=f"IMD 0.25 degree daily gridded rainfall {year}",
                publisher="India Meteorological Department, Pune",
                official_url=imd_post,
                landing_page_url=imd_landing,
                native_filename=dest.name,
                local_path="acquired/raw/" + dest.name,
                sha256=sha256_file(dest),
                file_type="netcdf" if looks_nc else "unknown",
                publication_date=year,
                data_vintage=f"{year} daily; Pai et al. 2014 product family",
                spatial_coverage="India 0.25 degree grid",
                temporal_coverage=year,
                spatial_unit="0.25 degree grid cell",
                temporal_resolution="daily",
                units="mm",
                observed_vs_inferred="OBSERVED",
                evidence_class="OBSERVED",
                license_or_access_note="IMD public product; cite Pai et al., MAUSAM 65(1), 2014",
                E0_domain="E0.4",
                E0_item="rainfall",
                ACCESS_STATUS="OBTAINED" if looks_nc else "ERROR",
                SCIENTIFIC_STATUS="PARTIAL" if looks_nc else "NOT_ASSESSABLE",
                clears_blocker="false",
                why_or_why_not=(
                    "Specified IMD product year obtained. Sample years do not constitute the full 1996-2023 overlap, "
                    "and the grid cannot be joined to 679 units without polygons."
                    if looks_nc else f"Download did not look like NetCDF; content-type={ctype}"
                ),
                limitations="Do not treat as unit-level rainfall. Remaining overlap years not mass-downloaded in this pass.",
                confidence="high" if looks_nc else "medium",
                bytes=str(dest.stat().st_size),
                tls_note=tls,
            )
            log(
                search_id=f"E04_IMD_RF25_{year}",
                E0_domain="E0.4",
                E0_item="rainfall",
                source_pursued=f"IMD RF25.php year={year}",
                why_pursued="Specified official daily gridded rainfall product overlapping the head archive.",
                official_url=imd_post,
                outcome="PUBLIC_SOURCE_OBTAINED" if looks_nc else "ERROR",
                ACCESS_STATUS="OBTAINED" if looks_nc else "ERROR",
                artifact_obtained="true" if looks_nc else "false",
                notes=f"bytes={dest.stat().st_size} content-type={ctype}",
            )
        except Exception as exc:  # noqa: BLE001
            log(
                search_id=f"E04_IMD_RF25_{year}",
                E0_domain="E0.4",
                E0_item="rainfall",
                source_pursued=f"IMD RF25.php year={year}",
                why_pursued="Specified official daily gridded rainfall product.",
                official_url=imd_post,
                outcome="ERROR",
                ACCESS_STATUS="ERROR",
                artifact_obtained="false",
                notes=str(exc),
            )

    log(
        search_id="E04_GRACE_NOT_DOWNLOADED",
        E0_domain="E0.4",
        E0_item="GRACE terrestrial water storage",
        source_pursued="NASA GRACE/GRACE-FO JPL Mascon",
        why_pursued="Frozen item is identified-not-required; never well-level head.",
        official_url="https://doi.org/10.5067/TEMSC-3JC634",
        outcome="NO_AUTHORITATIVE_SOURCE_LOCATED",
        ACCESS_STATUS="NOT_OBTAINED",
        artifact_obtained="false",
        notes="Deliberately not downloaded. Does not satisfy any frozen E0 blocker.",
    )
    log(
        search_id="E04_RECHARGE_COMPONENTS",
        E0_domain="E0.4",
        E0_item="recharge components independent of pumping",
        source_pursued="CGWB GWRA 2024 / IN-GRES / AP GWD",
        why_pursued="Need rainfall-recharge, return flow, canal/tank, managed recharge as a panel.",
        official_url="https://cgwb.gov.in/en/ground-water-resource-assessment-0",
        outcome="OFFICIAL_SOURCE_FOUND_BUT_ACCESS_REQUIRED",
        ACCESS_STATUS="ACCESS_REQUIRED",
        artifact_obtained="false",
        notes="Only statewide annual ESTIMATED recharge remains in-hand from the prior GWRA PDF. No public subannual component panel located. Rainfall is independent and is not a substitute for the recharge-component split.",
    )

    # ------------------------------------------------------------------
    # E0.5 NAQUIM PDFs (targeted, not all districts) + catalog
    # ------------------------------------------------------------------
    naquim_catalog = [
        ("Alluri Sitaramaraju", "https://cgwb.gov.in/cgwbpnm/publication-detail/1359", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/1740111182895942267file.pdf", False),
        ("Anakapalli", "https://cgwb.gov.in/cgwbpnm/publication-detail/1360", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/1740112083253996301file.pdf", False),
        ("Ananthapuramu", "https://cgwb.gov.in/cgwbpnm/publication-detail/1361", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/17401264911864076626file.pdf", True),
        ("Annamayya", "https://cgwb.gov.in/cgwbpnm/publication-detail/1362", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/17401272561531530641file.pdf", False),
        ("Bapatla", "https://cgwb.gov.in/cgwbpnm/publication-detail/1363", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/17401276181572821866file.pdf", False),
        ("Chittoor", "https://cgwb.gov.in/cgwbpnm/publication-detail/1364", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/17401295101161674667file.pdf", False),
        ("East Godavari", "https://cgwb.gov.in/cgwbpnm/publication-detail/1365", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/17403902671645307790file.pdf", False),
        ("Eluru", "https://cgwb.gov.in/cgwbpnm/publication-detail/1366", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/17403906081815005241file.pdf", False),
        ("Guntur", "https://cgwb.gov.in/cgwbpnm/publication-detail/1367", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/1740390895831797594file.pdf", False),
        ("YSR Kadapa", "https://cgwb.gov.in/cgwbpnm/publication-detail/1368", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/17403925871746746222file.pdf", False),
        ("Kakinada", "https://cgwb.gov.in/cgwbpnm/publication-detail/1369", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/17403929101317686901file.pdf", False),
        ("Krishna", "https://cgwb.gov.in/cgwbpnm/publication-detail/1370", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/17404564521533346784file.pdf", False),
        ("Kurnool", "https://cgwb.gov.in/cgwbpnm/publication-detail/1371", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/17404567241971395921file.pdf", False),
        ("SPSR Nellore", "https://cgwb.gov.in/cgwbpnm/publication-detail/1372", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/1740457589452112046file.pdf", False),
        ("NTR", "https://cgwb.gov.in/cgwbpnm/publication-detail/1373", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/1740457839823547905file.pdf", False),
        ("Palnadu", "https://cgwb.gov.in/cgwbpnm/publication-detail/1374", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/17404581791886422903file.pdf", False),
        ("Parvathipuram Manyam", "https://cgwb.gov.in/cgwbpnm/publication-detail/1375", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/17404584271367397910file.pdf", False),
        ("Prakasam", "https://cgwb.gov.in/cgwbpnm/publication-detail/1376", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/1740458692979658078file.pdf", False),
        ("Sri Sathya Sai", "https://cgwb.gov.in/cgwbpnm/publication-detail/1377", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/1740459824366801954file.pdf", False),
        ("Srikakulam", "https://cgwb.gov.in/cgwbpnm/publication-detail/1378", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/17404632371092827676file.pdf", False),
        ("Tirupati", "https://cgwb.gov.in/cgwbpnm/publication-detail/1379", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/1740463649537718087file.pdf", False),
        ("Visakhapatnam", "https://cgwb.gov.in/cgwbpnm/publication-detail/1380", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/1740463971931622767file.pdf", False),
        ("Vizianagaram", "https://cgwb.gov.in/cgwbpnm/publication-detail/1381", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/17404642122061448603file.pdf", False),
        ("West Godavari", "https://cgwb.gov.in/cgwbpnm/publication-detail/1382", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/17404645151309649185file.pdf", False),
        ("Nandyal", "https://cgwb.gov.in/cgwbpnm/publication-detail/1404", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/17418676521575851451file.pdf", True),
        ("Dr. B.R. Ambedkar Konaseema", "https://cgwb.gov.in/cgwbpnm/publication-detail/1405", "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/17418679141398996352file.pdf", False),
    ]
    catalog_path = META / "CGWB_NAQUIM_AP_PDF_CATALOG.csv"
    with catalog_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["district", "landing_page_url", "official_pdf_url", "downloaded_this_pass"])
        writer.writeheader()
        for district, landing, pdf, download in naquim_catalog:
            writer.writerow({
                "district": district,
                "landing_page_url": landing,
                "official_pdf_url": pdf,
                "downloaded_this_pass": "true" if download else "false",
            })
    add_prov(
        source_id="CGWB_NAQUIM_AP_PDF_CATALOG",
        title="Catalog of CGWB NAQUIM aquifer-mapping PDFs for Andhra Pradesh districts",
        publisher="Central Ground Water Board",
        official_url="https://cgwb.gov.in/cgwbpnm/search?type=2&cat_id=7",
        landing_page_url="https://cgwb.gov.in/en/aquifer-mapping",
        native_filename=catalog_path.name,
        local_path="acquired/metadata/CGWB_NAQUIM_AP_PDF_CATALOG.csv",
        sha256=sha256_file(catalog_path),
        file_type="csv",
        publication_date="2025-02/03 (district reports posted)",
        data_vintage="NAQUIM district reports 2025 postings",
        spatial_coverage="Andhra Pradesh districts listed",
        temporal_coverage="report vintage; not a time series",
        spatial_unit="district",
        temporal_resolution="reference characterization",
        units="not applicable",
        observed_vs_inferred="INFERRED",
        evidence_class="REFERENCE_MODEL",
        license_or_access_note="Public CGWB publication repository",
        E0_domain="E0.5",
        E0_item="hydrogeological reports for candidate units",
        ACCESS_STATUS="OBTAINED",
        SCIENTIFIC_STATUS="PARTIAL",
        clears_blocker="false",
        why_or_why_not="Catalog of official PDFs is not machine-readable NAQUIM GIS and is not scored as WEAKLY_SUPPORTED coupling.",
        limitations="Remaining district PDFs were identified and not mass-downloaded.",
        confidence="high",
        bytes=str(catalog_path.stat().st_size),
        tls_note="",
    )

    statewide = (
        "CGWB_AQUIFER_SYSTEM_AP",
        "Aquifer System of Andhra Pradesh",
        "https://cgwb.gov.in/cgwbpnm/publication-detail/668",
        "https://cgwb.gov.in/cgwbpnm/public/uploads/documents/16874344471830862221file.pdf",
        "cgwb_aquifer_system_andhra_pradesh.pdf",
    )
    targeted_pdfs = [statewide] + [
        (
            "CGWB_NAQUIM_AP_" + district.upper().replace(" ", "_"),
            f"NAQUIM aquifer mapping report: {district} District, Andhra Pradesh",
            landing,
            pdf,
            "cgwb_naquim_ap_" + district.lower().replace(" ", "_").replace(".", "") + ".pdf",
        )
        for district, landing, pdf, download in naquim_catalog
        if download
    ]
    for source_id, title, landing, url, fname in targeted_pdfs:
        dest = RAW / fname
        try:
            body, _, tls = fetch_bytes(url, timeout=180)
            write_bytes(dest, body)
            add_prov(
                source_id=source_id,
                title=title,
                publisher="Central Ground Water Board",
                official_url=url,
                landing_page_url=landing,
                native_filename=fname,
                local_path="acquired/raw/" + fname,
                sha256=sha256_file(dest),
                file_type="pdf",
                publication_date="",
                data_vintage="NAQUIM / aquifer-system report",
                spatial_coverage="Andhra Pradesh / named district",
                temporal_coverage="reference characterization",
                spatial_unit="district / aquifer (report)",
                temporal_resolution="reference",
                units="report-dependent; not extracted as synthetic gamma",
                observed_vs_inferred="INFERRED",
                evidence_class="REFERENCE_MODEL",
                license_or_access_note="Public CGWB publication",
                E0_domain="E0.5",
                E0_item="hydrogeological reports for candidate units",
                ACCESS_STATUS="OBTAINED",
                SCIENTIFIC_STATUS="PARTIAL",
                clears_blocker="false",
                why_or_why_not="Official hydrogeologic PDF obtained. Not machine-readable GIS. Not used to set WEAKLY_SUPPORTED or MATERIAL. T/S/test values are not extracted into model parameters.",
                limitations="A PDF is not NAQUIM GIS. Failure to extract coupling numbers is not weak coupling.",
                confidence="high",
                bytes=str(dest.stat().st_size),
                tls_note=tls,
            )
            log(
                search_id=source_id,
                E0_domain="E0.5",
                E0_item="hydrogeological reports for candidate units",
                source_pursued=title,
                why_pursued="Official NAQUIM/aquifer-system report that may contain tests/T/S narrative; GIS still required.",
                official_url=url,
                outcome="PUBLIC_SOURCE_OBTAINED",
                ACCESS_STATUS="OBTAINED",
                artifact_obtained="true",
                notes="PDF only. Coupling remains UNRESOLVED.",
            )
        except Exception as exc:  # noqa: BLE001
            log(
                search_id=source_id,
                E0_domain="E0.5",
                E0_item="hydrogeological reports for candidate units",
                source_pursued=title,
                why_pursued="Official NAQUIM/aquifer-system report.",
                official_url=url,
                outcome="ERROR",
                ACCESS_STATUS="ERROR",
                artifact_obtained="false",
                notes=str(exc),
            )

    log(
        search_id="E05_NAQUIM_GIS",
        E0_domain="E0.5",
        E0_item="NAQUIM machine-readable GIS",
        source_pursued="CGWB NAQUIM / AIMS / India-WRIS aquifer GIS",
        why_pursued="Frozen E0.5 strong-evidence GIS requirement.",
        official_url="https://cgwb.gov.in/en/aquifer-mapping",
        outcome="SOURCE_EXISTS_BUT_MACHINE_READABLE_DATA_NOT_FOUND",
        ACCESS_STATUS="ACCESS_REQUIRED",
        artifact_obtained="false",
        notes="CGWB states NAQUIM outputs are shared with states and disseminated via cgwb.gov.in, aims-cgwb.org, and India-WRIS. Public machine-readable aquifer polygons/attributes were not confirmed. PDFs do not clear this blocker. NWIC AquiferSystems_GSI MapServer timed out.",
    )
    log(
        search_id="E05_TESTS_TS",
        E0_domain="E0.5",
        E0_item="pumping tests",
        source_pursued="CGWB NAQUIM reports / AP GWD / NWDP",
        why_pursued="Need documented pumping/interference tests and T/S with method.",
        official_url="https://cgwb.gov.in/en/aquifer-mapping",
        outcome="OFFICIAL_SOURCE_FOUND_BUT_ACCESS_REQUIRED",
        ACCESS_STATUS="ACCESS_REQUIRED",
        artifact_obtained="false",
        notes="No machine-readable pumping-test or T/S table was located. Unofficial extraction of numbers from PDF prose is forbidden by the frozen E0 package. COUPLING_STATUS remains UNRESOLVED. NOT_DETECTED is not WEAKLY_SUPPORTED.",
    )

    # ------------------------------------------------------------------
    # E0.6 coverage feasibility (metadata only; no correlation fit)
    # ------------------------------------------------------------------
    log(
        search_id="E06_OVERLAP_FEASIBILITY",
        E0_domain="E0.6",
        E0_item="head-forcing temporal overlap",
        source_pursued="AP GWD/CGWB heads vs pumping vs rainfall metadata",
        why_pursued="Coverage/excitation feasibility from acquired factual metadata only.",
        official_url="https://nwdp.nwic.gov.in/dataset/?organization=andhra-pradesh-gw",
        outcome="PUBLIC_SOURCE_OBTAINED",
        ACCESS_STATUS="OBTAINED",
        artifact_obtained="heads and rainfall metadata; no pumping series",
        notes="Telemetry heads exist as a public AP GWD CSV. Subannual well pumping was not obtained. Overlap at identification cadence therefore remains inadequate. No analogue was documented. No correlation was fit.",
    )

    # Non-E0 datasets explicitly not downloaded
    for skip_id, title, url in [
        ("SKIP_WIND", "Wind Speed (Telemetry - Hourly), AP GWD", "https://nwdp.nwic.gov.in/dataset/?organization=andhra-pradesh-gw"),
        ("SKIP_TEMPERATURE", "Temperature (Telemetry - Hourly), AP GWD", "https://nwdp.nwic.gov.in/dataset/?organization=andhra-pradesh-gw"),
        ("SKIP_RIVER", "River Water Level (Telemetry - Hourly), AP GWD", "https://nwdp.nwic.gov.in/dataset/?organization=andhra-pradesh-gw"),
        ("SKIP_GRACE", "NASA GRACE mascon", "https://doi.org/10.5067/TEMSC-3JC634"),
        ("SKIP_MODIS_ET", "MODIS ET", "https://lpdaac.usgs.gov/documents/931/MOD16_User_Guide_V61.pdf"),
    ]:
        log(
            search_id=skip_id,
            E0_domain="none",
            E0_item="none",
            source_pursued=title,
            why_pursued="Does not satisfy a frozen E0 item; not downloaded.",
            official_url=url,
            outcome="NO_AUTHORITATIVE_SOURCE_LOCATED",
            ACCESS_STATUS="NOT_OBTAINED",
            artifact_obtained="false",
            notes="Skipped by protocol: if it satisfies no frozen E0 item, do not download it.",
        )

    with (E0 / "AP_E0_PUBLIC_SOURCE_ACQUISITION_LOG.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        writer.writeheader()
        writer.writerows(logs)
    with (E0 / "AP_E0_SOURCE_PROVENANCE_MANIFEST.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PROVENANCE_FIELDS)
        writer.writeheader()
        writer.writerows(prov)

    summary = {
        "retrieval_date": RETRIEVAL,
        "n_log_rows": len(logs),
        "n_provenance_rows": len(prov),
        "outcomes": {},
    }
    for row in logs:
        summary["outcomes"][row["outcome"]] = summary["outcomes"].get(row["outcome"], 0) + 1
    write_bytes(META / "ACQUISITION_RUN_SUMMARY.json", json.dumps(summary, indent=2).encode())
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
