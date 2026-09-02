#!/usr/bin/env python3
"""Download-once public Forest City sources. Hash once. Parse once. No re-fetch if present."""
from __future__ import annotations

import csv
import json
import sys
import time
import urllib.request
from pathlib import Path

FC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FC / "src"))
from hashes import sha256_file, write_json  # noqa: E402
from paths import RAW_DASHBOARD, RAW_EMISSIONS, RAW_LWSP, RAW_PERMITS, RAW_SOURCES, RAW_SUSTAINABILITY, RAW_WEATHER  # noqa: E402

UA = "Mozilla/5.0 (research; Forest City public-data validation; academic)"
TIMEOUT = 60

SOURCES = [
    {
        "source_id": "META_FC_OPENING_2012_04_19",
        "title": "Our Data Center Opens in Forest City, N.C.",
        "issuer": "Meta / Facebook Data Centers",
        "publication_date": "2012-04-19",
        "url": "https://datacenters.atmeta.com/2012/04/facebook-data-center-opens-in-forest-city-n-c/",
        "filename": "meta_fc_opening_2012.html",
        "source_tier": "PRIMARY_OPERATOR",
        "site_scope": "FOREST_CITY_CAMPUS",
        "building_scope": "Building 1 confirmed online; Building 2 expected later 2012",
        "temporal_scope": "2012-04-19",
        "quantity": "operational status",
        "measurement_boundary": "campus announcement",
        "design_vs_observed": "OBSERVED_OPENING",
        "limitations": "Does not report PUE/WUE, DeltaT, or controller setpoints.",
    },
    {
        "source_id": "META_FC_OPENING_NEWSROOM_2012",
        "title": "Facebook Data Center Opens in Forest City, N.C.",
        "issuer": "Meta Newsroom",
        "publication_date": "2012-04-19",
        "url": "https://about.fb.com/news/2012/04/facebook-data-center-opens-in-forest-city-n-c/",
        "filename": "meta_fc_opening_newsroom_2012.html",
        "source_tier": "PRIMARY_OPERATOR",
        "site_scope": "FOREST_CITY_CAMPUS",
        "building_scope": "Building 1 / Building 2",
        "temporal_scope": "2012-04-19",
        "quantity": "operational status",
        "measurement_boundary": "campus announcement",
        "design_vs_observed": "OBSERVED_OPENING",
        "limitations": "Same facts as Data Centers post; no engineering setpoints.",
    },
    {
        "source_id": "MAGUIRE_2011_OCP_REFLECTIONS",
        "title": "Reflections on the Open Compute Summit",
        "issuer": "Engineering at Meta (Yael Maguire)",
        "publication_date": "2011-06-22",
        "url": "https://engineering.fb.com/2011/06/22/core-infra/reflections-on-the-open-compute-summit/",
        "filename": "maguire_2011_ocp_reflections.html",
        "source_tier": "PRIMARY_OPERATOR",
        "site_scope": "FOREST_CITY_PLANNED_VS_PRN1",
        "building_scope": "Forest City design intent vs first-phase Prineville",
        "temporal_scope": "2011 planned operation",
        "quantity": "85F inlet; 90% RH; 25F->35F DeltaT; 45% less AHU hardware",
        "measurement_boundary": "server inlet / cold-to-hot aisle DESIGN",
        "design_vs_observed": "DESIGN_SPEC_PLANNED",
        "limitations": "Planned Forest City operation as of 2011; not as-operated BMS. DeltaT is IT/server aisle rise, not proven facility effective ΔT.",
    },
    {
        "source_id": "OCP_2013_HOT_HUMID",
        "title": "Cooling an OCP Data Center in a Hot and Humid Climate",
        "issuer": "Open Compute Project / Facebook (leed)",
        "publication_date": "2013-08-07",
        "url": "https://www.opencompute.org/blog/cooling-an-ocp-data-center-in-a-hot-and-humid-climate",
        "filename": "ocp_2013_hot_humid_climate.html",
        "source_tier": "PRIMARY_OPERATOR",
        "site_scope": "FOREST_CITY",
        "building_scope": "operating Forest City (2012 summer)",
        "temporal_scope": "summer 2012; 2012-06-25 and 2012-07-01 events",
        "quantity": "85F/90%RH envelope; DX installed unused; mixing; evaporative; PUE 1.07 summer",
        "measurement_boundary": "operator-observed outdoor/indoor behavior; PUE seasonal",
        "design_vs_observed": "OPERATOR_OBSERVED",
        "limitations": "Blog, not BMS extract. Event DB/RH are outdoor snapshots. PUE 1.07 is seasonal, not WUE. Rutherfordton weather ~6 miles used for design analysis, not necessarily this blog's event sensors.",
    },
    {
        "source_id": "OCP_2012_PUE_WUE_DASHBOARD",
        "title": "A new way to report PUE and WUE",
        "issuer": "Open Compute Project / Facebook",
        "publication_date": "2012-08-16",
        "url": "https://www.opencompute.org/blog/a-new-way-to-report-pue-and-wue",
        "filename": "ocp_2012_pue_wue_report.html",
        "source_tier": "PRIMARY_OPERATOR",
        "site_scope": "PRINEVILLE_AND_FOREST_CITY",
        "building_scope": "public dashboard sites",
        "temporal_scope": "2012 dashboard launch",
        "quantity": "PUE, WUE, outside T, outside humidity; 24h and 1-year views",
        "measurement_boundary": "see post for WUE/PUE definitions; not recovered here until dashboard freeze",
        "design_vs_observed": "OBSERVED_DASHBOARD_PRODUCT",
        "limitations": "Describes dashboard product; raw time series not in this HTML.",
    },
    {
        "source_id": "DPR_FOREST_CITY_PROJECT",
        "title": "Facebook Forest City Data Center",
        "issuer": "DPR Construction",
        "publication_date": "undated_project_page",
        "url": "https://www.dpr.com/projects/forest-city-data-center",
        "filename": "dpr_forest_city_project.html",
        "source_tier": "ENGINEERING_CONSTRUCTION",
        "site_scope": "FOREST_CITY_CAMPUS",
        "building_scope": "two 370000-sqft buildings; four data suites; 25000-sqft penthouse each",
        "temporal_scope": "original campus construction",
        "quantity": "area, suite count, penthouse, evaporative cooling, on-site substation",
        "measurement_boundary": "construction/design description",
        "design_vs_observed": "DESIGN_CONSTRUCTION",
        "limitations": "Does not identify later buildings; square feet are construction figures not measured load.",
    },
    {
        "source_id": "DPR_BUILDING_COMMUNITY_BLOG",
        "title": "Building Community along with Facebook Open…",
        "issuer": "DPR Construction",
        "publication_date": "contemporaneous_construction",
        "url": "https://www.dpr.com/media/blog/building-community-along-with-facebook",
        "filename": "dpr_building_community.html",
        "source_tier": "ENGINEERING_CONSTRUCTION",
        "site_scope": "FOREST_CITY_AND_PRINEVILLE",
        "building_scope": "FC one-story + 125000-sqft mechanical penthouse; four halls",
        "temporal_scope": "construction of original FC building",
        "quantity": "370000-plus sqft; 125000 sqft penthouse; four halls",
        "measurement_boundary": "construction",
        "design_vs_observed": "DESIGN_CONSTRUCTION",
        "limitations": "125000 sqft penthouse is 5x 25000; consistent with four suites. Not a later-campus inventory.",
    },
    {
        "source_id": "ENR_2013_GREEN_LIKES",
        "title": "Facebook Data Center Earns Many Green 'Likes'",
        "issuer": "ENR",
        "publication_date": "2013-11-04",
        "url": "https://www.enr.com/articles/12162-facebook-data-center-earns-many-green-likes",
        "filename": "enr_2013_green_likes.html",
        "source_tier": "SECONDARY_ENGINEERING",
        "site_scope": "FOREST_CITY",
        "building_scope": "354000-sqft; four suites; Munters evaporative; municipal water UV",
        "temporal_scope": "original building as constructed",
        "quantity": "airflow path; mixing; Munters; DX not detailed here",
        "measurement_boundary": "construction journalism",
        "design_vs_observed": "DESIGN_CONSTRUCTION",
        "limitations": "354k vs DPR 370k discrepancy preserved. Not BMS.",
    },
    {
        "source_id": "DCK_2013_SERVERS_HOTTER",
        "title": "Facebook Servers Get Hotter, But Run Fine in the South",
        "issuer": "Data Center Knowledge",
        "publication_date": "2013-08-07",
        "url": "https://www.datacenterknowledge.com/servers/facebook-servers-get-hotter-but-run-fine-in-the-south",
        "filename": "dck_2013_servers_hotter.html",
        "source_tier": "SECONDARY_CORROBORATION",
        "site_scope": "FOREST_CITY",
        "building_scope": "operating 2012 summer",
        "temporal_scope": "summer 2012",
        "quantity": "102F; DX unused; 85F/90%RH; misting",
        "measurement_boundary": "operator quotes",
        "design_vs_observed": "OPERATOR_OBSERVED_VIA_PRESS",
        "limitations": "Secondary; quotes OCP/Lee post.",
    },
    {
        "source_id": "DCK_2011_85_COLD_AISLE",
        "title": "Facebook: 85 Degrees in the 'Cold' Aisle",
        "issuer": "Data Center Knowledge",
        "publication_date": "2011-06",
        "url": "https://www.datacenterknowledge.com/hyperscalers/facebook-85-degrees-in-the-cold-aisle",
        "filename": "dck_2011_85_cold_aisle.html",
        "source_tier": "SECONDARY_CORROBORATION",
        "site_scope": "FOREST_CITY_PLANNED",
        "building_scope": "planned vs PRN1",
        "temporal_scope": "2011",
        "quantity": "85F; 90%RH; 35F DeltaT; 45% less AHU; hot aisle 120F interpretation",
        "measurement_boundary": "quotes Maguire; DCK interprets 35F as cold-to-hot aisle",
        "design_vs_observed": "DESIGN_SPEC_VIA_PRESS",
        "limitations": "120F is DCK inference from 85+35, not a measured AHU ΔT.",
    },
    {
        "source_id": "ITNEWS_MCCAMMON_FC",
        "title": "Running Facebook's Forest City data centre",
        "issuer": "iTnews / Keven McCammon",
        "publication_date": "circa_2013",
        "url": "https://www.itnews.com.au/news/running-facebooks-forest-city-data-centre-330872",
        "filename": "itnews_mccammon_forest_city.html",
        "source_tier": "OPERATOR_INTERVIEW",
        "site_scope": "FOREST_CITY",
        "building_scope": "operating campus",
        "temporal_scope": "second hottest NC summer; later membrane vs misters",
        "quantity": "DX/chillers unused that summer; membrane later water efficiency",
        "measurement_boundary": "qualitative operations",
        "design_vs_observed": "OPERATOR_OBSERVED",
        "limitations": "Membrane retrofit timing vs 2012 misting is not a 2012 controller parameter. Do not fit.",
    },
    {
        "source_id": "AIWIRE_2014_COLD_STORAGE",
        "title": "Open Compute in Full Bloom: Facebook North Carolina Datacenter",
        "issuer": "EnterpriseTech / AIwire",
        "publication_date": "2014-04-22",
        "url": "https://www.hpcwire.com/aiwire/2014/04/22/open-compute-full-bloom-facebook-north-carolina-datacenter/",
        "filename": "aiwire_2014_cold_storage.html",
        "source_tier": "SECONDARY_SITE_TOUR",
        "site_scope": "FOREST_CITY_CAMPUS",
        "building_scope": "B1 and B3 ~350k; B2 pad; B4 cold storage 90k / 3 halls",
        "temporal_scope": "2014 tour",
        "quantity": "building identities and areas; cold storage architecture",
        "measurement_boundary": "journalism/tour",
        "design_vs_observed": "OBSERVED_CAMPUS_TOUR",
        "limitations": "Building numbering (B2 empty pad, B3 as second large hall) must not be overwritten by later marketing names without evidence.",
    },
    {
        "source_id": "ENR_2014_FRC4",
        "title": "Facebook's Latest North Carolina Data Center Goes for Gold",
        "issuer": "ENR",
        "publication_date": "2014-11-03",
        "url": "https://www.enr.com/articles/12214-facebooks-latest-north-carolina-data-center-goes-for-gold",
        "filename": "enr_2014_frc4.html",
        "source_tier": "SECONDARY_ENGINEERING",
        "site_scope": "FOREST_CITY",
        "building_scope": "FRC4 cold storage; third FB facility by DPR/Fortis",
        "temporal_scope": "2014",
        "quantity": "three 25000-sqft halls; 14 AHUs; LEED Gold seek",
        "measurement_boundary": "construction award writeup",
        "design_vs_observed": "DESIGN_CONSTRUCTION",
        "limitations": "Does not give CFM or DeltaT. Permit-level capacities are not measured load.",
    },
    {
        "source_id": "CHARLOTTE_OBSERVER_COLD_STORAGE",
        "title": "A peek inside the N.C. data center where your old Facebook photos go to sleep",
        "issuer": "Charlotte Observer",
        "publication_date": "2014",
        "url": "https://www.charlotteobserver.com/news/local/article9113354.html",
        "filename": "charlotte_observer_cold_storage.html",
        "source_tier": "SECONDARY_SITE_TOUR",
        "site_scope": "FOREST_CITY",
        "building_scope": "original ~350k opened 2012; second same size; cold storage 90k",
        "temporal_scope": "2014 media tour",
        "quantity": "160-acre campus; cold storage energy-saving disks",
        "measurement_boundary": "press tour",
        "design_vs_observed": "OBSERVED_CAMPUS_TOUR",
        "limitations": "Paywall possible; qualitative.",
    },
    {
        "source_id": "META_FC_FACTSHEET_2025",
        "title": "Meta's Forest City Data Center",
        "issuer": "Meta Data Centers",
        "publication_date": "2025-02",
        "url": "https://datacenters.atmeta.com/wp-content/uploads/2025/02/Meta_s-Forest-City-Data-Center.pdf",
        "filename": "meta_forest_city_factsheet_2025.pdf",
        "source_tier": "PRIMARY_OPERATOR_COMMUNITY",
        "site_scope": "FOREST_CITY_CAMPUS",
        "building_scope": "current campus marketing",
        "temporal_scope": "circa 2025",
        "quantity": "renewable matching; water-efficiency qualitative; 310 MW NC renewables",
        "measurement_boundary": "community factsheet not EDI",
        "design_vs_observed": "OPERATOR_CLAIM_QUALITATIVE",
        "limitations": "No 2012 controller parameters. Do not treat later campus as 2012 Building 1.",
    },
    {
        "source_id": "META_EDI_2025",
        "title": "Meta 2025 Environmental Data Index (FY2024)",
        "issuer": "Meta Sustainability",
        "publication_date": "2025-10",
        "url": "https://sustainability.atmeta.com/wp-content/uploads/2025/10/Meta_2025-Environmental-Data-Index.pdf",
        "filename": "Meta_2025-Environmental-Data-Index.pdf",
        "dest": "sustainability",
        "source_tier": "PRIMARY_OPERATOR_DISCLOSURE",
        "site_scope": "FOREST_CITY_FACILITY_ROW",
        "building_scope": "whole-site as reported by Meta; architecture mix unidentified",
        "temporal_scope": "2020-2024",
        "quantity": "electricity MWh; water withdrawal ML; location-based Scope 2 tCO2e",
        "measurement_boundary": "Meta site reporting; not ISO WUE",
        "design_vs_observed": "REPORTED_ANNUAL",
        "limitations": "Site total; later years include unidentified later buildings/cold storage. 2020 electricity rounded. Do not fit 2012 controller to these.",
    },
    {
        "source_id": "TOWN_FC_WATER_TREATMENT",
        "title": "Water Treatment | Town of Forest City, NC",
        "issuer": "Town of Forest City",
        "publication_date": "undated_page",
        "url": "https://www.townofforestcity.com/water-treatment",
        "filename": "town_forest_city_water_treatment.html",
        "source_tier": "GOVERNMENT",
        "site_scope": "MUNICIPAL_PWS",
        "building_scope": "Town WTP not Meta",
        "temporal_scope": "current page",
        "quantity": "PWSID NC01-81-010; Second Broad River source",
        "measurement_boundary": "municipal raw/finished water",
        "design_vs_observed": "SYSTEM_DESCRIPTION",
        "limitations": "Not Meta customer meter. Do not call municipal production Meta consumption.",
    },
    {
        "source_id": "NC_LWSP_FC_2023",
        "title": "NC DWR Local Water Supply Plan Forest City 2023",
        "issuer": "NC Division of Water Resources",
        "publication_date": "2023",
        "url": "https://www.ncwater.org/wudc/app/lwsp/report.php?pwsid=01-81-010&year=2023",
        "filename": "lwsp_01-81-010_2023.html",
        "dest": "lwsp",
        "source_tier": "GOVERNMENT",
        "site_scope": "FOREST_CITY_PWS_01-81-010",
        "building_scope": "municipal",
        "temporal_scope": "2023",
        "quantity": "raw withdrawal; WTP 8 MGD; metered raw and finished; Second Broad River",
        "measurement_boundary": "municipal LWSP",
        "design_vs_observed": "REPORTED_MUNICIPAL",
        "limitations": "Industrial demand is municipal class, not proven Meta-only.",
    },
    {
        "source_id": "TOWN_FC_PERMIT_PORTAL",
        "title": "Town of Forest City NC Public Permit Portal",
        "issuer": "Town of Forest City",
        "publication_date": "current",
        "url": "https://twn-forestcity-nc.smartgovcommunity.com/Public/Home",
        "filename": "town_permit_portal_home.html",
        "dest": "permits",
        "source_tier": "GOVERNMENT",
        "site_scope": "TOWN",
        "building_scope": "portal",
        "temporal_scope": "public portal",
        "quantity": "permit access path",
        "measurement_boundary": "public records index",
        "design_vs_observed": "PORTAL",
        "limitations": "Detailed drawings may require login or in-person request. Do not invent permit numbers.",
    },
    {
        "source_id": "FBPUEWUE_DASHBOARD_LIVE",
        "title": "Facebook PUE/WUE dashboard (fbpuewue.com)",
        "issuer": "Facebook (historical public dashboard)",
        "publication_date": "2012-2014",
        "url": "https://www.fbpuewue.com/forestcity",
        "filename": "fbpuewue_forestcity_live.html",
        "dest": "dashboard",
        "source_tier": "PRIMARY_OPERATOR_DASHBOARD",
        "site_scope": "FOREST_CITY",
        "building_scope": "dashboard site",
        "temporal_scope": "historical public",
        "quantity": "PUE WUE T RH",
        "measurement_boundary": "UNIDENTIFIED_UNTIL_RECOVERY",
        "design_vs_observed": "OBSERVED_IF_RECOVERED",
        "limitations": "Live site likely dead; Wayback attempted separately.",
    },
]


def dest_dir(spec: dict) -> Path:
    d = spec.get("dest", "sources")
    return {
        "sources": RAW_SOURCES,
        "sustainability": RAW_SUSTAINABILITY,
        "lwsp": RAW_LWSP,
        "permits": RAW_PERMITS,
        "dashboard": RAW_DASHBOARD,
        "emissions": RAW_EMISSIONS,
        "weather": RAW_WEATHER,
    }[d]


def fetch(url: str, dest: Path) -> tuple[str, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return "cached", sha256_file(dest)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read()
            dest.write_bytes(data)
            return "downloaded", sha256_file(dest)
    except Exception as e:
        dest.with_suffix(dest.suffix + ".error.txt").write_text(f"{url}\n{type(e).__name__}: {e}\n")
        return f"error:{type(e).__name__}", ""


def extra_lwsp_years() -> None:
    for y in range(2010, 2025):
        url = f"https://www.ncwater.org/wudc/app/lwsp/report.php?pwsid=01-81-010&year={y}"
        dest = RAW_LWSP / f"lwsp_01-81-010_{y}.html"
        status, _ = fetch(url, dest)
        print(f"LWSP {y}: {status}")
        time.sleep(0.15)


def extra_edi() -> None:
    extras = [
        ("https://sustainability.atmeta.com/wp-content/uploads/2024/08/Meta-2024-Environmental-Data-Index.pdf", "Meta_2024-Environmental-Data-Index.pdf"),
        ("https://sustainability.atmeta.com/wp-content/uploads/2023/07/Meta-2023-Environmental-Data-Index.pdf", "Meta_2023-Environmental-Data-Index.pdf"),
        ("https://sustainability.atmeta.com/wp-content/uploads/2022/06/2022-Environmental-Data-Index.pdf", "Meta_2022-Environmental-Data-Index.pdf"),
        ("https://sustainability.atmeta.com/wp-content/uploads/2021/06/Meta-2021-Environmental-Data-Index.pdf", "Meta_2021-Environmental-Data-Index.pdf"),
        ("https://sustainability.fb.com/wp-content/uploads/2021/06/2021-Environmental-Data-Index.pdf", "Meta_2021-EDI-alt.pdf"),
        ("https://sustainability.atmeta.com/wp-content/uploads/2024/08/Meta-2024-Sustainability-Report.pdf", "Meta_2024-Sustainability-Report.pdf"),
        ("https://engineering.fb.com/2012/08/15/data-center-engineering/a-new-way-to-report-pue-and-wue/", "meta_eng_2012_pue_wue.html"),
        ("https://code.facebook.com/posts/272417392924843/open-sourcing-pue-wue-dashboards/", "meta_opensource_pue_wue.html"),
        ("https://github.com/facebookarchive/pue-dashboard", "github_pue_dashboard.html"),
        ("https://github.com/facebookarchive", "github_facebookarchive.html"),
        ("https://web.archive.org/cdx/search/cdx?url=fbpuewue.com/*&output=json&fl=timestamp,original,statuscode,mimetype,length&limit=200", "wayback_cdx_fbpuewue.json"),
        ("https://web.archive.org/cdx/search/cdx?url=www.fbpuewue.com/forestcity&output=json&fl=timestamp,original,statuscode,mimetype,length&limit=100", "wayback_cdx_forestcity.json"),
        ("https://web.archive.org/cdx/search/cdx?url=www.facebook.com/ForestCityDataCenter/*&output=json&limit=50", "wayback_cdx_fb_page.json"),
        ("https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv", "isd-history.csv"),
        ("https://www.ncei.noaa.gov/pub/data/noaa/isd-history.txt", "isd-history.txt"),
        ("https://twn-forestcity-nc.smartgovcommunity.com/ApplicationPublic/ApplicationHome", "permit_application_home.html"),
        ("https://datacenters.atmeta.com/wp-content/uploads/2025/02/Meta_s-Forest-City-Data-Center.pdf", "meta_fc_factsheet.pdf"),
        ("https://www.opencompute.org/wiki/Open_Compute_Project_Data_Center_v1.0", "ocp_dc_v1_wiki.html"),
    ]
    for url, name in extras:
        if name.endswith(".csv") or name.endswith(".txt"):
            dest = RAW_WEATHER / name if "isd" in name else RAW_SOURCES / name
            if "isd" in name:
                dest = RAW_WEATHER / name
            elif "wayback" in name:
                dest = RAW_DASHBOARD / name
            else:
                dest = RAW_SOURCES / name
        elif "wayback" in name or "github" in name or "pue" in name.lower() and "edi" not in name.lower():
            dest = RAW_DASHBOARD / name if ("wayback" in name or "pue" in name.lower() or "github" in name) else RAW_SOURCES / name
            if name.endswith(".pdf") and "factsheet" in name:
                dest = RAW_SOURCES / name
            elif name.endswith(".pdf"):
                dest = RAW_SUSTAINABILITY / name
            elif "isd" in name:
                dest = RAW_WEATHER / name
            elif "wayback" in name or "github" in name or "pue" in name.lower():
                dest = RAW_DASHBOARD / name
            else:
                dest = RAW_SOURCES / name
        else:
            dest = RAW_SUSTAINABILITY / name if name.endswith(".pdf") and "EDI" in name or "Environmental" in name or "Sustainability" in name else RAW_SOURCES / name
            if name.endswith(".pdf") and ("EDI" in name or "Environmental" in name or "Sustainability" in name or "Index" in name):
                dest = RAW_SUSTAINABILITY / name
            elif "isd" in name:
                dest = RAW_WEATHER / name
            elif "wayback" in name or "pue" in name.lower() or "github" in name:
                dest = RAW_DASHBOARD / name
            elif name.endswith(".pdf"):
                dest = RAW_SUSTAINABILITY / name if "Meta_" in name else RAW_SOURCES / name
        status, _ = fetch(url, dest)
        print(f"EXTRA {name}: {status}")
        time.sleep(0.2)


def write_register(rows: list[dict]) -> None:
    path = FC / "config" / "forest_city_source_register.csv"
    fields = [
        "source_id", "title", "issuer", "publication_date", "url", "local_path",
        "sha256", "download_status", "bytes", "source_tier", "site_scope",
        "building_scope", "temporal_scope", "quantity", "measurement_boundary",
        "design_vs_observed", "limitations",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})
    write_json(FC / "outputs" / "source_audit" / "SOURCE_HASHES.json", rows)


def main() -> None:
    rows = []
    for spec in SOURCES:
        dest = dest_dir(spec) / spec["filename"]
        status, digest = fetch(spec["url"], dest)
        print(f"{spec['source_id']}: {status}")
        rec = dict(spec)
        rec["local_path"] = str(dest)
        rec["sha256"] = digest
        rec["download_status"] = status
        rec["bytes"] = dest.stat().st_size if dest.exists() else 0
        rec.pop("filename", None)
        rec.pop("dest", None)
        rows.append(rec)
        time.sleep(0.1)
    extra_lwsp_years()
    extra_edi()
    # hash any extra files into audit
    extras = []
    for folder in (RAW_SOURCES, RAW_SUSTAINABILITY, RAW_LWSP, RAW_DASHBOARD, RAW_WEATHER, RAW_PERMITS):
        for p in sorted(folder.rglob("*")):
            if p.is_file() and not p.name.endswith(".error.txt"):
                extras.append({"path": str(p), "sha256": sha256_file(p), "bytes": p.stat().st_size})
    write_json(FC / "outputs" / "source_audit" / "ALL_DOWNLOADED_FILE_HASHES.json", extras)
    write_register(rows)
    print(f"register rows={len(rows)} files={len(extras)}")


if __name__ == "__main__":
    main()
