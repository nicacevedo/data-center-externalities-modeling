#!/usr/bin/env python3
"""Static registries, taxonomy, priors, validation matrix, status. Local only."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/nacevedo/RA/data-center-externalities-modeling/other_sources/cooling_technology_proxies")
PARENT = Path("/home/nacevedo/RA/data-center-externalities-modeling")


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path):
    if not Path(path).exists():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(cmd, cwd):
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    return (r.stdout or "").strip()


def write_csv(path: Path, rows: list, fieldnames: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def main():
    head = git(["git", "rev-parse", "HEAD"], PARENT)
    branch = git(["git", "rev-parse", "--abbrev-ref", "HEAD"], PARENT)
    status = git(["git", "status", "--short"], PARENT)
    lei_commit = git(["git", "rev-parse", "HEAD"], ROOT / "sources/lei2025/upstream")
    masanet_up = "2cc53bee89b0a61bdad10c02b4d170d7f673e2dc"

    prior = {
        "timestamp_utc": utcnow(),
        "repo_branch": branch,
        "repo_head": head,
        "git_status_short": status,
        "did_not_modify_masanet_workflow": True,
        "did_read_meta_2023_2024_water": False,
        "did_not_rerun_completed_masanet_validation": True,
        "established": {
            "P_fac_equals_P_IT_plus_P_nonIT": "M100 STRONG SUPPORT; used as accounting identity",
            "cooling_depends_on_IT_and_weather": "M100 weather additive STRONG; Frontier IT-load effect on accessory/cooling STRONG; Lei-Masanet climate×technology intensities",
            "PUE_derived_not_independently_sampled": "master.tex and M100 closure",
            "Lei_Masanet_is_intensity_archetype_not_part_load_twin": "masanet FIRST_RUN_SUMMARY / followup_v1; all PUE_WUE_* hard-code Power_IT=1",
            "site_WUE_is_onsite_conditioning_use": "Green Grid / Lei 2022 Eq.1; not groundwater pumping",
            "traditional_Lei_Masanet_limited_for_liquid_AI": "eight air-IT archetypes in 2022 public code; liquid cases appear in Lei 2025 UEs_16cases and LBNL 2024 Table 4.2",
            "modern_liquid_cooling_is_extension_target": True,
            "masanet_annual_v2_in_progress": "other_sources/masanet/docs/final_repro_v2/STATUS_IN_PROGRESS.md; do not contaminate",
            "M100_CLOSED_FROZEN": True,
            "Frontier_energy_not_WUE": True,
        },
        "other_sources_layout": {
            "cooling_technology_proxies": "this module",
            "masanet": "Lei 2022 public simulator reproduction (do not touch)",
            "m100": "measured HPC facility energy benchmark, frozen",
            "it_power": "workload→IT power source audit",
            "exadata": "present",
        },
    }
    (ROOT / "manifests").mkdir(parents=True, exist_ok=True)
    (ROOT / "manifests" / "PRIOR_WORK_RECOVERY.json").write_text(json.dumps(prior, indent=2) + "\n")

    pdfs = {
        "LEI2022_PREPRINT_RS": ROOT / "references/core/Climate-_and_Technology-Specific_PUE_and_WUE_Predi.pdf",
        "LEI2025_USER_PDF": ROOT / "references/core/The water use of data center workloads A review and assessment of key determinants.pdf",
        "LBNL2024_USER_PDF": ROOT / "references/core/lbnl-2024-united-states-data-center-energy-usage-report.pdf",
        "EU_COC_BPG": ROOT / "references/core/best-practice-guide-data-center-design_0.pdf",
    }
    sources = [
        {
            "source_id": "LEI2025_GITHUB",
            "title": "The Water Use of Data Center Workloads — public SI data and code",
            "authors": "Lei, Lu, Shehabi, Masanet",
            "year": 2025,
            "DOI": "10.1016/j.resconrec.2025.108310",
            "URL": "https://github.com/nuoaleon/The-Water-Use-of-Data-Center-Workloads-A-Review-and-Assessment-of-Key-Determinants",
            "local_path": "sources/lei2025/upstream",
            "commit": lei_commit,
            "SHA256": "see file-level hashes in PROVENANCE.json",
            "license": "not stated in README",
            "evidence_class": "SAME_LEI_MASANET_LINEAGE",
            "raw_data_availability": "YES_CSV_XLSX",
            "code_availability": "ANALYSIS_RMD_AND_NOTEBOOK_NOT_HOURLY_SIMULATOR",
            "measured_vs_modeled": "MODELED_annual_scenario_pairs",
            "geography": "US IECC/ASHRAE climate zones (19 labels in UEs including 0A/0B)",
            "climate": "19 zones",
            "temporal_resolution": "annual scenario (50 realizations per subcase×climate)",
            "technologies_covered": "12 cooling labels; liquid subcases 15_1–16_3; dry cooler 17–18",
            "energy_boundary": "PUE = facility electricity / IT electricity",
            "water_boundary": "WUE-site = onsite conditioning water / IT electricity (L/kWh)",
            "independence_lineage": "Same physics lineage as Lei-Masanet 2022 / LBNL 2024 cooling model; not independent validation of that lineage",
            "relevance": "PRIMARY machine-readable joint PUE/WUE proxy",
            "limitations": "Hourly simulator for liquid cases not in this repo; WUE is not withdrawal/groundwater",
            "confidence": "HIGH for source semantics of bundled CSV; MEDIUM as generic truth",
            "source_origin": "GIT_CLONE",
        },
        {
            "source_id": "LEI2025_UES16",
            "title": "UEs_16cases.csv",
            "authors": "Lei et al. 2025 SI",
            "year": 2025,
            "DOI": "10.1016/j.resconrec.2025.108310",
            "URL": "https://github.com/nuoaleon/The-Water-Use-of-Data-Center-Workloads-A-Review-and-Assessment-of-Key-Determinants/blob/main/data/UEs_16cases.csv",
            "local_path": "sources/lei2025/UEs_16cases.csv",
            "commit": lei_commit,
            "SHA256": sha256_file(ROOT / "sources/lei2025/UEs_16cases.csv"),
            "license": "not stated",
            "evidence_class": "SAME_LEI_MASANET_LINEAGE",
            "raw_data_availability": "YES",
            "code_availability": "quantile construction in SI Supporting Code.Rmd",
            "measured_vs_modeled": "MODELED",
            "geography": "US climate zones",
            "climate": "0A–8",
            "temporal_resolution": "annual",
            "technologies_covered": "see taxonomy",
            "energy_boundary": "PUE",
            "water_boundary": "WUE-site",
            "independence_lineage": "Lei-Masanet",
            "relevance": "scenario-level joint observations",
            "limitations": "19000 rows; Case 15/16 pool 3 liquid subtypes",
            "confidence": "HIGH as SI data file",
            "source_origin": "USER_PROVIDED_COPY_IDENTICAL_TO_GIT",
        },
        {
            "source_id": "LEI2025_PAPER_USER_PDF",
            "title": "The water use of data center workloads: A review and assessment of key determinants",
            "authors": "Lei, Lu, Shehabi, Masanet",
            "year": 2025,
            "DOI": "10.1016/j.resconrec.2025.108310",
            "URL": "https://escholarship.org/uc/item/1vx545q7",
            "local_path": str(pdfs["LEI2025_USER_PDF"].relative_to(ROOT)),
            "commit": "",
            "SHA256": sha256_file(pdfs["LEI2025_USER_PDF"]),
            "license": "CC BY 4.0 (eScholarship/OSTI record)",
            "evidence_class": "REVIEW_ONLY plus SAME_LEI_MASANET_LINEAGE simulations",
            "raw_data_availability": "SI GitHub preferred over digitizing figures",
            "code_availability": "GitHub SI",
            "measured_vs_modeled": "MODELED_plus_review",
            "geography": "global discussion; US climate simulations",
            "climate": "19 zones stated in paper",
            "temporal_resolution": "annual averages",
            "technologies_covered": "ten cooling clusters in Fig. 4; liquid includes RDHX/cold-plate/immersion",
            "energy_boundary": "PUE",
            "water_boundary": "WUE-site and WUE-source (grid water) distinguished",
            "independence_lineage": "Lei-Masanet",
            "relevance": "definitions and liquid-cooling qualitative claims",
            "limitations": "User PDF not byte-compared to Elsevier typeset PDF; eScholarship OA PDF exists. Do not silently substitute.",
            "confidence": "HIGH for definitions; MEDIUM for any typeset number not in CSV",
            "source_origin": "USER_PROVIDED_REFERENCE",
        },
        {
            "source_id": "LEI2022_PREPRINT",
            "title": "Climate- and Technology-Specific PUE and WUE Predictions (Research Square preprint rs.3.rs-769999/v1)",
            "authors": "Lei, Masanet",
            "year": 2021,
            "DOI": "10.21203/rs.3.rs-769999/v1",
            "URL": "https://doi.org/10.1016/j.resconrec.2022.106323",
            "local_path": str(pdfs["LEI2022_PREPRINT_RS"].relative_to(ROOT)),
            "commit": masanet_up,
            "SHA256": sha256_file(pdfs["LEI2022_PREPRINT_RS"]),
            "license": "preprint",
            "evidence_class": "SAME_LEI_MASANET_LINEAGE",
            "raw_data_availability": "UE.xlsx in nuoaleon/Data-Center-Water-footprint (masanet tree; not copied here)",
            "code_availability": "simulation_funs_DC.py public clone",
            "measured_vs_modeled": "MODELED",
            "geography": "US",
            "climate": "15 zones in UE.xlsx vs 16 in preprint text",
            "temporal_resolution": "hourly TMY inside model; published table annual 5th/95th",
            "technologies_covered": "10 paper cases / 8 code functions; air-cooled IT",
            "energy_boundary": "PUE",
            "water_boundary": "onsite use WUE",
            "independence_lineage": "Lei-Masanet 2022",
            "relevance": "hourly simulator exists for 2022 air-IT archetypes only",
            "limitations": "User file is preprint not Elsevier 2022 typeset article. Annual envelope reproduction is a separate masanet experiment — not rerun here.",
            "confidence": "HIGH for lineage; PARTIAL for published envelopes (masanet V1 FAIL / V2 running)",
            "source_origin": "USER_PROVIDED_REFERENCE",
        },
        {
            "source_id": "LBNL2024_REPORT",
            "title": "2024 United States Data Center Energy Usage Report",
            "authors": "Shehabi, Smith, Hubbard, Newkirk, Lei, Siddik, Holecek, Koomey, Masanet, Sartor",
            "year": 2024,
            "DOI": "10.2172/2530048",
            "URL": "https://eta.lbl.gov/publications/2024-lbnl-data-center-energy-usage-report",
            "local_path": str(pdfs["LBNL2024_USER_PDF"].relative_to(ROOT)),
            "commit": "",
            "SHA256": sha256_file(pdfs["LBNL2024_USER_PDF"]),
            "license": "US government report",
            "evidence_class": "SAME_LEI_MASANET_LINEAGE",
            "raw_data_availability": "NO public million-simulation CSV found; report cites >1e6 simulations and Fig 4.4 ranges only",
            "code_availability": "NOT FOUND as public hourly simulator for 2024 liquid cases",
            "measured_vs_modeled": "MODELED then industry-adjusted (report text)",
            "geography": "US 965 TMY stations",
            "climate": "CONUS weather stations",
            "temporal_resolution": "annual averages from hourly TMY",
            "technologies_covered": "Table 4.2 nine major systems including liquid+dry and liquid+WE",
            "energy_boundary": "PUE; also UPS/lighting",
            "water_boundary": "WUE (site); report also discusses source WUE",
            "independence_lineage": "Explicitly employs Lei and Masanet 2022/2020 simulation models (Section 4)",
            "relevance": "stock-level PUE/WUE and cooling mix; liquid AI classes",
            "limitations": "Underlying simulation dataset not public; ranges in figures not digitized; industry adjustment means not pure physics output",
            "confidence": "HIGH as authoritative report; LOW as independent empirical validation",
            "source_origin": "USER_PROVIDED_REFERENCE",
        },
        {
            "source_id": "EU_COC_BPG",
            "title": "Best Practice Guide for the EU Code of Conduct on Data Centre Energy Efficiency",
            "authors": "European Commission / JRC (Acton, Bertoldi, et al. depending on edition)",
            "year": "edition in PDF",
            "DOI": "",
            "URL": "https://e3p.jrc.ec.europa.eu/communities/data-centres-code-conduct",
            "local_path": str(pdfs["EU_COC_BPG"].relative_to(ROOT)),
            "commit": "",
            "SHA256": sha256_file(pdfs["EU_COC_BPG"]),
            "license": "EU publication",
            "evidence_class": "ENGINEERING_STANDARD",
            "raw_data_availability": "NO telemetry",
            "code_availability": "NO",
            "measured_vs_modeled": "RECOMMENDED practices",
            "geography": "EU-oriented, globally cited",
            "climate": "not a climate table",
            "temporal_resolution": "n/a",
            "technologies_covered": "air, economizer, liquid cooling practices",
            "energy_boundary": "facility energy efficiency practices",
            "water_boundary": "limited; not a WUE dataset",
            "independence_lineage": "independent of Lei code",
            "relevance": "engineering priors / expected practice, not field WUE",
            "limitations": "not measured PUE/WUE distributions",
            "confidence": "MEDIUM as prior, not validation",
            "source_origin": "USER_PROVIDED_REFERENCE",
        },
        {
            "source_id": "LEI2022_PUBLIC_CODE",
            "title": "nuoaleon/Data-Center-Water-footprint",
            "authors": "Lei",
            "year": 2022,
            "DOI": "10.1016/j.resconrec.2022.106323",
            "URL": "https://github.com/nuoaleon/Data-Center-Water-footprint",
            "local_path": "../masanet/external/Data-Center-Water-footprint (DO NOT COPY INTO THIS MODULE)",
            "commit": masanet_up,
            "SHA256": "",
            "license": "none in clone",
            "evidence_class": "SAME_LEI_MASANET_LINEAGE",
            "raw_data_availability": "UE.xlsx annual 5th/95th",
            "code_availability": "YES hourly Python archetypes (air-IT)",
            "measured_vs_modeled": "MODELED",
            "geography": "US TMY3 representative cities",
            "climate": "15 zones in UE.xlsx",
            "temporal_resolution": "hourly in code; annual in UE.xlsx",
            "technologies_covered": "8 functions; no liquid IT",
            "energy_boundary": "PUE",
            "water_boundary": "onsite WUE components",
            "independence_lineage": "Lei-Masanet 2022",
            "relevance": "only public hourly physical simulator identified",
            "limitations": "annual published envelopes not fully reproduced in masanet V1; V2 running; do not rerun here",
            "confidence": "HIGH as code existence; PARTIAL as published-table match",
            "source_origin": "EXISTING_PROJECT_CLONE",
        },
        {
            "source_id": "M100_FROZEN",
            "title": "CINECA Marconi100 measured facility energy (project closure)",
            "authors": "CINECA / EuroHPC public traces as used in this project",
            "year": 2021,
            "DOI": "",
            "URL": "",
            "local_path": "../m100 (frozen)",
            "commit": "",
            "SHA256": "",
            "license": "",
            "evidence_class": "MEASURED_INDEPENDENT",
            "raw_data_availability": "processed in m100 module",
            "code_availability": "n/a",
            "measured_vs_modeled": "MEASURED energy",
            "geography": "Italy",
            "climate": "site",
            "temporal_resolution": "hourly",
            "technologies_covered": "HPC facility cooling; not generic DC catalog",
            "energy_boundary": "facility IT + cooling + aux meters",
            "water_boundary": "UNSUPPORTED",
            "independence_lineage": "independent of Lei",
            "relevance": "structure P_fac=P_IT+P_cool+P_aux; weather additive; PUE derived",
            "limitations": "coefficients not transferable; no WUE",
            "confidence": "HIGH for structure, UNSUPPORTED for WUE",
            "source_origin": "EXISTING_PROJECT",
        },
        {
            "source_id": "FRONTIER_ORNL",
            "title": "Frontier HPC & Facility Data (ORNL)",
            "authors": "ORNL",
            "year": 2023,
            "DOI": "",
            "URL": "",
            "local_path": "../masanet/external/frontier (do not modify)",
            "commit": "",
            "SHA256": "",
            "license": "",
            "evidence_class": "MEASURED_INDEPENDENT",
            "raw_data_availability": "xlsx in masanet tree",
            "code_availability": "n/a",
            "measured_vs_modeled": "MEASURED energy/thermal",
            "geography": "Oak Ridge, TN",
            "climate": "4A-class humid subtropical (site)",
            "temporal_resolution": "10-minute / hourly aggregates",
            "technologies_covered": "direct liquid-cooled supercomputer + facility loops",
            "energy_boundary": "compute vs facility PUE reconstruction",
            "water_boundary": "NOT a site WUE meter in the public extract used here",
            "independence_lineage": "independent of Lei",
            "relevance": "liquid IT heat capture energy behavior; not Lei WUE validation",
            "limitations": "one site; thermal check is published-formula; no conditioning-water time series used",
            "confidence": "HIGH for IT-load effect on accessory power; UNSUPPORTED for WUE",
            "source_origin": "EXISTING_PROJECT",
        },
        {
            "source_id": "META_ENGINEERING_2011",
            "title": "Designing a Very Efficient Data Center",
            "authors": "Meta/Facebook engineering",
            "year": 2011,
            "DOI": "",
            "URL": "https://engineering.fb.com/2011/04/14/core-infra/designing-a-very-efficient-data-center/",
            "local_path": "cited via Meta_Prineville_Oregon_v3/SOURCE_INSTRUCTIONS.md",
            "commit": "",
            "SHA256": "",
            "license": "",
            "evidence_class": "OPERATOR_SELF_REPORTED",
            "raw_data_availability": "design point only",
            "code_availability": "n/a",
            "measured_vs_modeled": "DESIGN / SELF_REPORTED",
            "geography": "Prineville, OR",
            "climate": "5B high desert (IECC)",
            "temporal_resolution": "design point",
            "technologies_covered": "100% outside-air evaporative cooling; no chiller; no cooling tower",
            "energy_boundary": "stated full-load PUE 1.07",
            "water_boundary": "stated WUE 0.31 L/kWh (design, not 2023-2024 measured water)",
            "independence_lineage": "operator; not Lei",
            "relevance": "Prineville initial-epoch identification",
            "limitations": "Do not propagate to later buildings; do not use 2023-2024 Meta water to choose k",
            "confidence": "HIGH for 2011 design class; LOW for later campus",
            "source_origin": "EXISTING_PROJECT_CANONICAL_CITATION",
        },
        {
            "source_id": "NREL_ESIF_TSC_2018",
            "title": "Thermosyphon Cooler Hybrid System for Water Savings in an Energy-Efficient HPC Data Center",
            "authors": "Carter, Sickinger, et al. (NREL ESIF HPC)",
            "year": 2018,
            "DOI": "",
            "URL": "https://datacenters.lbl.gov/sites/default/files/Thermosyphon%20Cooler%20Hybrid%20System%20for%20Water%20Savings%20Paper.pdf",
            "local_path": "URL_ONLY_not_used_to_fit_proxy",
            "commit": "",
            "SHA256": "",
            "license": "public LBNL/NREL paper",
            "evidence_class": "MEASURED_INDEPENDENT",
            "raw_data_availability": "paper tables; NREL later published ESIF PUE parquet (energy only)",
            "code_availability": "NO",
            "measured_vs_modeled": "MEASURED WUE and PUE at one HPC site with hybrid dry thermosyphon + towers",
            "geography": "Golden, CO",
            "climate": "5B-class high plains",
            "temporal_resolution": "monthly/annual over 24 months",
            "technologies_covered": "thermosyphon hybrid dry cooler + cooling towers + heat recovery; not Lei catalog k",
            "energy_boundary": "facility PUE at ESIF HPC",
            "water_boundary": "onsite WUE including tower evaporation/humidification",
            "independence_lineage": "independent of Lei-Masanet code",
            "relevance": "one of few public measured joint PUE/WUE field results; climate 5B-like",
            "limitations": "one site; heat-recovery first; not a Lei case; do not calibrate UEs to 0.70 L/kWh",
            "confidence": "HIGH as a measured point; LOW as transferable Lei validation",
            "source_origin": "INDEPENDENT_SEARCH",
        },
        {
            "source_id": "NREL_ESIF_PUE_CATALOG",
            "title": "NLR HPC Facility Power Usage Effectiveness (PUE) Data",
            "authors": "NREL/NLR",
            "year": 2024,
            "DOI": "",
            "URL": "https://data.nlr.gov/submissions/300",
            "local_path": "NOT_DOWNLOADED (96MB energy parquet; electricity-only)",
            "commit": "",
            "SHA256": "",
            "license": "NREL data catalog",
            "evidence_class": "MEASURED_INDEPENDENT",
            "raw_data_availability": "YES public parquet/CSV for PUE/cooling_kW — electricity only",
            "code_availability": "n/a",
            "measured_vs_modeled": "MEASURED energy",
            "geography": "Golden, CO",
            "climate": "5B-class",
            "temporal_resolution": "sub-hourly energy",
            "technologies_covered": "ESIF HPC facility",
            "energy_boundary": "IT, cooling, HVAC, pumps, PUE",
            "water_boundary": "NONE in this dataset",
            "independence_lineage": "independent",
            "relevance": "hourly PUE structure possible later; does not validate WUE",
            "limitations": "electricity-only evidence does not validate WUE",
            "confidence": "HIGH energy / UNSUPPORTED water",
            "source_origin": "INDEPENDENT_SEARCH",
        },
        {
            "source_id": "PRN1_PERMITS_2021_2024",
            "title": "Crook County PRN1 mechanical permits (chiller/CRAH)",
            "authors": "Crook County / City of Prineville permit record",
            "year": "2021-2024",
            "DOI": "",
            "URL": "",
            "local_path": "Meta_Prineville_Oregon_v3/data/raw/prineville_strictly_valuable_permits_v2 (not copied)",
            "commit": "",
            "SHA256": "",
            "license": "public record",
            "evidence_class": "OPERATOR_SELF_REPORTED",
            "raw_data_availability": "permit documents in Prineville module",
            "code_availability": "n/a",
            "measured_vs_modeled": "DOCUMENTARY",
            "geography": "Prineville PRN1",
            "climate": "5B",
            "temporal_resolution": "commissioning events",
            "technologies_covered": "chilled-water / CRAH / additional chiller operational 2024-02-02",
            "energy_boundary": "not metered PUE",
            "water_boundary": "not WUE",
            "independence_lineage": "independent of Lei",
            "relevance": "later-epoch mechanical cooling exists at PRN1; multi-scenario campus",
            "limitations": "not used to retune 2023-2024 water holdout; not a quantitative PUE/WUE sample",
            "confidence": "HIGH that mechanical chilled-water equipment was added; LOW mapping to a Lei 2025 case",
            "source_origin": "EXISTING_PROJECT",
        },
    ]
    fields = list(sources[0].keys())
    write_csv(ROOT / "manifests" / "SOURCE_REGISTRY.csv", sources, fields)
    (ROOT / "manifests" / "SOURCE_REGISTRY.json").write_text(json.dumps(sources, indent=2) + "\n")

    prov = {
        "timestamp_utc": utcnow(),
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "repo_head": head,
        "repo_branch": branch,
        "lei2025_git_commit": lei_commit,
        "lei2025_git_url": "https://github.com/nuoaleon/The-Water-Use-of-Data-Center-Workloads-A-Review-and-Assessment-of-Key-Determinants",
        "user_copies_sha256_match_git": True,
        "hashes": {str(p.relative_to(ROOT)): sha256_file(p) for p in [
            ROOT / "sources/lei2025/UEs_16cases.csv",
            ROOT / "sources/lei2025/SPEC_2024.xlsx",
            ROOT / "sources/lei2025/SI Supporting Code.Rmd",
            ROOT / "sources/lei2025/SI Supporting Code 2 (WaterSensitivity).ipynb",
            pdfs["LEI2025_USER_PDF"],
            pdfs["LEI2022_PREPRINT_RS"],
            pdfs["LBNL2024_USER_PDF"],
            pdfs["EU_COC_BPG"],
        ]},
        "python": "masanet_lei for numeric work; did not use HPC",
        "did_not_mutate_upstream_git_or_user_pdfs": True,
        "did_read_meta_2023_2024_water": False,
    }
    (ROOT / "manifests" / "PROVENANCE.json").write_text(json.dumps(prov, indent=2) + "\n")

    # taxonomy
    tax_fields = [
        "tech_id", "source_label", "IT_HEAT_CAPTURE", "HEAT_TRANSPORT", "HEAT_REJECTION",
        "ECONOMIZER", "MECHANICAL_COOLING", "DIRECT_WATER_MECHANISM", "liquid_it",
        "lei2025_cases", "confidence", "notes",
    ]
    tax = [
        {"tech_id": "DX", "source_label": "Direct expansion system", "IT_HEAT_CAPTURE": "air", "HEAT_TRANSPORT": "air", "HEAT_REJECTION": "dry", "ECONOMIZER": "none", "MECHANICAL_COOLING": "DX", "DIRECT_WATER_MECHANISM": "humidification_possible", "liquid_it": "no", "lei2025_cases": "5,11", "confidence": "high", "notes": "CRAC/DX; WUE near-humidification only"},
        {"tech_id": "ACC", "source_label": "Air-cooled chiller", "IT_HEAT_CAPTURE": "air", "HEAT_TRANSPORT": "air", "HEAT_REJECTION": "dry", "ECONOMIZER": "none", "MECHANICAL_COOLING": "air-cooled chiller", "DIRECT_WATER_MECHANISM": "humidification_possible", "liquid_it": "no", "lei2025_cases": "4,10", "confidence": "high", "notes": ""},
        {"tech_id": "WCC", "source_label": "Water-cooled chiller", "IT_HEAT_CAPTURE": "air", "HEAT_TRANSPORT": "air", "HEAT_REJECTION": "evaporative tower", "ECONOMIZER": "none", "MECHANICAL_COOLING": "water-cooled chiller", "DIRECT_WATER_MECHANISM": "cooling tower", "liquid_it": "no", "lei2025_cases": "3,9", "confidence": "high", "notes": "highest typical site WUE"},
        {"tech_id": "AE_ACC", "source_label": "Airside economizer (air-cooled chiller)", "IT_HEAT_CAPTURE": "air", "HEAT_TRANSPORT": "air", "HEAT_REJECTION": "dry", "ECONOMIZER": "airside", "MECHANICAL_COOLING": "air-cooled chiller", "DIRECT_WATER_MECHANISM": "humidification_possible", "liquid_it": "no", "lei2025_cases": "2", "confidence": "high", "notes": "chiller supplemental"},
        {"tech_id": "AE_WCC", "source_label": "Airside economizer (water-cooled chiller)", "IT_HEAT_CAPTURE": "air", "HEAT_TRANSPORT": "air", "HEAT_REJECTION": "evaporative tower", "ECONOMIZER": "airside", "MECHANICAL_COOLING": "water-cooled chiller", "DIRECT_WATER_MECHANISM": "cooling tower", "liquid_it": "no", "lei2025_cases": "1", "confidence": "high", "notes": ""},
        {"tech_id": "AE_AD_ACC", "source_label": "Airside economizer& adiabatic cooling (air-cooled chiller)", "IT_HEAT_CAPTURE": "air", "HEAT_TRANSPORT": "air", "HEAT_REJECTION": "hybrid dry/adiabatic", "ECONOMIZER": "airside", "MECHANICAL_COOLING": "air-cooled chiller", "DIRECT_WATER_MECHANISM": "adiabatic assist", "liquid_it": "no", "lei2025_cases": "0", "confidence": "high", "notes": "Lei 2022 case 6-like"},
        {"tech_id": "AE_AD_WCC", "source_label": "Airside economizer& adiabatic cooling (water-cooled chiller)", "IT_HEAT_CAPTURE": "air", "HEAT_TRANSPORT": "air", "HEAT_REJECTION": "hybrid dry/adiabatic plus tower if chiller", "ECONOMIZER": "airside", "MECHANICAL_COOLING": "water-cooled chiller", "DIRECT_WATER_MECHANISM": "multiple", "liquid_it": "no", "lei2025_cases": "6", "confidence": "high", "notes": "Lei 2022 case 1-like"},
        {"tech_id": "WE_WCC", "source_label": "Waterside economizer (water-cooled chiller)", "IT_HEAT_CAPTURE": "air", "HEAT_TRANSPORT": "liquid loop", "HEAT_REJECTION": "evaporative tower", "ECONOMIZER": "waterside", "MECHANICAL_COOLING": "water-cooled chiller", "DIRECT_WATER_MECHANISM": "cooling tower", "liquid_it": "no", "lei2025_cases": "7,8", "confidence": "high", "notes": "Lei 2022 cases 2/4"},
        {"tech_id": "DRY_ACC", "source_label": "Dry cooler (air-cooled chiller)", "IT_HEAT_CAPTURE": "air", "HEAT_TRANSPORT": "liquid loop", "HEAT_REJECTION": "dry", "ECONOMIZER": "none", "MECHANICAL_COOLING": "air-cooled chiller", "DIRECT_WATER_MECHANISM": "humidification_possible", "liquid_it": "no", "lei2025_cases": "17", "confidence": "high", "notes": "Rmd drops from some figures"},
        {"tech_id": "DRY_AD_ACC", "source_label": "Dry cooler with adiabatic assist (air-cooled chiller)", "IT_HEAT_CAPTURE": "air", "HEAT_TRANSPORT": "liquid loop", "HEAT_REJECTION": "hybrid dry/adiabatic", "ECONOMIZER": "none", "MECHANICAL_COOLING": "air-cooled chiller", "DIRECT_WATER_MECHANISM": "adiabatic assist", "liquid_it": "no", "lei2025_cases": "18", "confidence": "high", "notes": "Rmd drops from some figures"},
        {"tech_id": "LIQ_DRY_AD", "source_label": "IT Liquid cooling: dry cooler with adiabatic assist (air-cooled chiller)", "IT_HEAT_CAPTURE": "rear-door|direct-to-chip|immersion (pooled)", "HEAT_TRANSPORT": "liquid loop", "HEAT_REJECTION": "hybrid dry/adiabatic", "ECONOMIZER": "none", "MECHANICAL_COOLING": "air-cooled chiller", "DIRECT_WATER_MECHANISM": "adiabatic assist", "liquid_it": "yes", "lei2025_cases": "15_1,15_2,15_3", "confidence": "medium", "notes": "Paper: liquid includes RDHX, cold-plate, immersion (SI Fig S6.3). Public CSV does not split those physics; only subcase IDs."},
        {"tech_id": "LIQ_WE_WCC", "source_label": "IT Liquid cooling: waterside economizer (water-cooled chiller)", "IT_HEAT_CAPTURE": "rear-door|direct-to-chip|immersion (pooled)", "HEAT_TRANSPORT": "liquid loop", "HEAT_REJECTION": "evaporative tower", "ECONOMIZER": "waterside", "MECHANICAL_COOLING": "water-cooled chiller", "DIRECT_WATER_MECHANISM": "cooling tower", "liquid_it": "yes", "lei2025_cases": "16_1,16_2,16_3", "confidence": "medium", "notes": "Same pooling limitation"},
    ]
    write_csv(ROOT / "data_processed" / "COOLING_TAXONOMY.csv", tax, tax_fields)

    xw_fields = [
        "lei2022_paper_case", "lei2022_code_function", "lei2025_case", "lei2025_label",
        "lbnl2024_table42", "mapping", "confidence", "rationale", "uncertainty",
    ]
    xw = [
        {"lei2022_paper_case": "1", "lei2022_code_function": "PUE_WUE_AE_Chiller", "lei2025_case": "6", "lei2025_label": "Airside economizer& adiabatic cooling (water-cooled chiller)", "lbnl2024_table42": "Airside economizer & adiabatic cooling (air- or water-cooled chiller)", "mapping": "equivalent", "confidence": "high", "rationale": "Same large-scale AE+adiabatic+WC description", "uncertainty": "size-class ranges differ"},
        {"lei2022_paper_case": "2", "lei2022_code_function": "PUE_WUE_Chiller_Watereconomier", "lei2025_case": "7", "lei2025_label": "Waterside economizer (water-cooled chiller)", "lbnl2024_table42": "Waterside economizer (water-cooled chiller)", "mapping": "equivalent", "confidence": "high", "rationale": "Large-scale WE+WC", "uncertainty": "none material"},
        {"lei2022_paper_case": "3", "lei2022_code_function": "PUE_WUE_AE_Chiller_Colo", "lei2025_case": "1", "lei2025_label": "Airside economizer (water-cooled chiller)", "lbnl2024_table42": "Airside economizer (air- or water-cooled chiller)", "mapping": "approximate", "confidence": "medium", "rationale": "Midsize AE+WC without adiabatic in 2022 Table 2", "uncertainty": "2025 case numbering starts at 0; adiabatic split into cases 0 vs 6"},
        {"lei2022_paper_case": "4", "lei2022_code_function": "PUE_WUE_WE_Chiller_Colo", "lei2025_case": "8", "lei2025_label": "Waterside economizer (water-cooled chiller)", "lbnl2024_table42": "Waterside economizer (water-cooled chiller)", "mapping": "equivalent", "confidence": "medium", "rationale": "Same function family, midsize vs large ranges", "uncertainty": "shared 2025 label with case 7; size in CSV"},
        {"lei2022_paper_case": "5", "lei2022_code_function": "PUE_WUE_Chiller", "lei2025_case": "3", "lei2025_label": "Water-cooled chiller", "lbnl2024_table42": "Water-cooled chiller", "mapping": "equivalent", "confidence": "high", "rationale": "WC no economizer midsize", "uncertainty": "case 9 is small WC"},
        {"lei2022_paper_case": "6", "lei2022_code_function": "PUE_WUE_AE_AIRChiller", "lei2025_case": "0", "lei2025_label": "Airside economizer& adiabatic cooling (air-cooled chiller)", "lbnl2024_table42": "Airside economizer & adiabatic cooling (air- or water-cooled chiller)", "mapping": "equivalent", "confidence": "medium", "rationale": "AE+adiabatic+AC", "uncertainty": "2022 case 6 vs 2025 case 0 numbering"},
        {"lei2022_paper_case": "7", "lei2022_code_function": "PUE_WUE_AIRChiller", "lei2025_case": "4", "lei2025_label": "Air-cooled chiller", "lbnl2024_table42": "Air-cooled chiller", "mapping": "equivalent", "confidence": "high", "rationale": "AC no economizer", "uncertainty": "case 10 small"},
        {"lei2022_paper_case": "10", "lei2022_code_function": "PUE_WUE_DX", "lei2025_case": "5,11", "lei2025_label": "Direct expansion system", "lbnl2024_table42": "not listed as standalone in Table 4.2 excerpt (DX mentioned in intro list)", "mapping": "equivalent", "confidence": "high", "rationale": "DX/CRAC", "uncertainty": "LBNL 2024 Table 4.2 focuses nine major systems; DX still in Lei 2025 CSV"},
        {"lei2022_paper_case": "NA", "lei2022_code_function": "NOT IN 2022 PUBLIC CODE", "lei2025_case": "15_*", "lei2025_label": "IT Liquid cooling: dry cooler with adiabatic assist (air-cooled chiller)", "lbnl2024_table42": "IT liquid cooling: dry cooler with or without adiabatic assist (air cooled chiller)", "mapping": "equivalent_to_lbnl_label", "confidence": "medium", "rationale": "Same LBNL/Lei2025 label; 2022 public code has no liquid IT function", "uncertainty": "RDHX vs cold-plate vs immersion not separately simulated in public CSV"},
        {"lei2022_paper_case": "NA", "lei2022_code_function": "NOT IN 2022 PUBLIC CODE", "lei2025_case": "16_*", "lei2025_label": "IT Liquid cooling: waterside economizer (water-cooled chiller)", "lbnl2024_table42": "IT liquid cooling: waterside economizer (water-cooled chiller)", "mapping": "equivalent_to_lbnl_label", "confidence": "medium", "rationale": "Same", "uncertainty": "subtype pooling"},
        {"lei2022_paper_case": "NA", "lei2022_code_function": "NOT IN 2022 PUBLIC CODE", "lei2025_case": "17,18", "lei2025_label": "Dry cooler (with/without adiabatic assist, air-cooled chiller)", "lbnl2024_table42": "Dry cooler with or without adiabatic assist (air- or water cooled chiller)", "mapping": "approximate", "confidence": "medium", "rationale": "Air-IT dry cooler class added in 2025 CSV", "uncertainty": "LBNL allows air- or water-cooled chiller backup; CSV uses air-cooled chiller"},
    ]
    write_csv(ROOT / "data_processed" / "MASANET_LEI2025_LBNL_CROSSWALK.csv", xw, xw_fields)

    pdf_fields = [
        "source_id", "document", "version", "page", "section", "table_figure_eq",
        "quantity", "value_range", "original_units", "canonical_units", "kind",
        "technology", "facility_climate", "interpretation", "caveats", "confidence",
    ]
    pdf_rows = [
        {"source_id": "LEI2025_PAPER_USER_PDF", "document": "Lei et al. 2025 RCR 219", "version": "user PDF + eScholarship OA record DOI 10.1016/j.resconrec.2025.108310", "page": "SI/GitHub not typeset page", "section": "2.3 / Fig. 4 caption", "table_figure_eq": "Fig. 4 note", "quantity": "PUE and WUE-site are yearly average values", "value_range": "n/a", "original_units": "1 ; L/kWh", "canonical_units": "1 ; L/kWh", "kind": "MODELED", "technology": "all simulated", "facility_climate": "19 climate zones", "interpretation": "CSV rows are annual intensities, not hourly", "caveats": "Do not treat as hourly weather functions", "confidence": "high"},
        {"source_id": "LEI2025_PAPER_USER_PDF", "document": "Lei et al. 2025", "version": "user PDF", "page": "Fig. 4 caption", "section": "3.3", "table_figure_eq": "Fig. 4", "quantity": "IT liquid cooling includes RDHX, cold-plates, immersion", "value_range": "qualitative", "original_units": "n/a", "canonical_units": "n/a", "kind": "MODELED", "technology": "liquid IT", "facility_climate": "pooled", "interpretation": "subtypes exist in SI Fig S6.3; UEs Case 15/16 pool them", "caveats": "cannot identify subtype from PUE/WUE pair alone", "confidence": "high"},
        {"source_id": "LBNL2024_REPORT", "document": "LBNL-2001637 / 2024 US DC Energy Usage Report", "version": "user PDF sha256 791f95fe...", "page": "40-47", "section": "4", "table_figure_eq": "Table 4.2", "quantity": "cooling system catalog", "value_range": "9 major systems", "original_units": "n/a", "canonical_units": "n/a", "kind": "MODELED", "technology": "see taxonomy", "facility_climate": "US stock", "interpretation": "same lineage as Lei 2022; >1e6 simulations; 50 ops scenarios per type", "caveats": "dataset not public; industry-adjusted", "confidence": "high as catalog"},
        {"source_id": "LBNL2024_REPORT", "document": "LBNL 2024", "version": "user PDF", "page": "46-48", "section": "PUE and WUE Results", "table_figure_eq": "Fig 4.6-4.7", "quantity": "US average PUE / site WUE stock", "value_range": "PUE 1.6 (2014) to 1.4 (2023); WUE just over 0.36 L/kWh through 2023; 2028 PUE 1.15-1.35; WUE 0.45-0.48", "original_units": "1 ; L/kWh", "canonical_units": "1 ; L/kWh", "kind": "MODELED", "technology": "stock mix", "facility_climate": "US aggregate", "interpretation": "NOT a facility proxy; mix-weighted", "caveats": "do not use as Prineville PUE/WUE", "confidence": "medium"},
        {"source_id": "LBNL2024_REPORT", "document": "LBNL 2024", "version": "user PDF", "page": "47", "section": "adiabatic WUE caveat", "table_figure_eq": "text near Fig 4.4", "quantity": "hyperscale reported WUE for similar AE+adiabatic systems", "value_range": "0.1-0.3 L/kWh vs lower simulated", "original_units": "L/kWh", "canonical_units": "L/kWh", "kind": "SELF_REPORTED", "technology": "AE+adiabatic", "facility_climate": "unspecified hyperscale", "interpretation": "report acknowledges simulated adiabatic WUE may be low vs operator reports", "caveats": "not used to calibrate this module", "confidence": "low as transferable number"},
        {"source_id": "LBNL2024_REPORT", "document": "LBNL 2024", "version": "user PDF", "page": "41", "section": "Table 4.3", "table_figure_eq": "Table 4.3", "quantity": "AI (IT Liquid Cooling) facility water temperature class", "value_range": "W45", "original_units": "ASHRAE liquid class", "canonical_units": "ASHRAE W45", "kind": "ASSUMED", "technology": "liquid IT AI", "facility_climate": "AI space type", "interpretation": "engineering prior for liquid supply temperature class", "caveats": "assumption in stock model", "confidence": "medium"},
        {"source_id": "LBNL2024_REPORT", "document": "LBNL 2024", "version": "user PDF", "page": "43", "section": "simulations", "table_figure_eq": "text", "quantity": "operational scenarios per space×cooling", "value_range": "50", "original_units": "count", "canonical_units": "count", "kind": "MODELED", "technology": "all LBNL 2024 cooling", "facility_climate": "965 TMY stations", "interpretation": "same 50-LHS style as Lei 2022/2025", "caveats": "microdata not released", "confidence": "high"},
        {"source_id": "META_ENGINEERING_2011", "document": "FB engineering blog 2011-04-14", "version": "as cited in SOURCE_INSTRUCTIONS.md", "page": "n/a", "section": "design", "table_figure_eq": "n/a", "quantity": "full-load PUE; WUE; architecture", "value_range": "PUE 1.07; WUE 0.31 L/kWh; OA evaporative; no chiller/tower", "original_units": "1 ; L/kWh", "canonical_units": "1 ; L/kWh", "kind": "DESIGN_LIMIT", "technology": "airside evaporative OA", "facility_climate": "Prineville 2011 design", "interpretation": "initial epoch identification prior, not 2023-2024 calibration", "caveats": "design not annual telemetry; later PRN1 has chillers", "confidence": "high for 2011 class"},
        {"source_id": "LEI2022_PREPRINT", "document": "Research Square rs.3.rs-769999/v1", "version": "preprint; journal is 10.1016/j.resconrec.2022.106323", "page": "methods", "section": "4.3", "table_figure_eq": "text", "quantity": "practical minima = 5th quantiles of simulation results", "value_range": "n/a", "original_units": "n/a", "canonical_units": "n/a", "kind": "MODELED", "technology": "10 cases", "facility_climate": "IECC zones", "interpretation": "matches UE.xlsx Quantile column; Lei 2025 Rmd uses same 5/95", "caveats": "preprint vs journal typesetting", "confidence": "high"},
    ]
    write_csv(ROOT / "data_processed" / "PDF_PARAMETER_EXTRACTIONS.csv", pdf_rows, pdf_fields)

    eng_fields = ["prior_id", "parameter", "value", "units", "technology", "source_id", "kind", "confidence", "notes"]
    eng = [
        {"prior_id": "E1", "parameter": "ASHRAE_liquid_class_AI", "value": "W45", "units": "ASHRAE class", "technology": "liquid IT", "source_id": "LBNL2024_REPORT", "kind": "ENGINEERING_PRIOR", "confidence": "medium", "notes": "Table 4.3 AI liquid cooling"},
        {"prior_id": "E2", "parameter": "n_lhs_operational_scenarios", "value": "50", "units": "count", "technology": "all lineage models", "source_id": "LBNL2024_REPORT", "kind": "ENGINEERING_PRIOR", "confidence": "high", "notes": "also Lei 2022/2025"},
        {"prior_id": "E3", "parameter": "PUE_definition", "value": "E_fac/E_IT", "units": "1", "technology": "all", "source_id": "LEI2025_PAPER_USER_PDF", "kind": "ENGINEERING_PRIOR", "confidence": "high", "notes": "Green Grid"},
        {"prior_id": "E4", "parameter": "WUE_site_definition", "value": "W_onsite_conditioning/E_IT", "units": "L/kWh", "technology": "all", "source_id": "LEI2025_PAPER_USER_PDF", "kind": "ENGINEERING_PRIOR", "confidence": "high", "notes": "not withdrawal; not groundwater"},
        {"prior_id": "E5", "parameter": "liquid_free_cooling_advantage", "value": "higher coolant T, fewer chiller hours", "units": "qualitative", "technology": "liquid IT", "source_id": "LBNL2024_REPORT", "kind": "ENGINEERING_PRIOR", "confidence": "medium", "notes": "Section 4 liquid text"},
        {"prior_id": "E6", "parameter": "dry_cooler_adiabatic_when", "value": "high DB, low WB", "units": "qualitative", "technology": "dry/adiabatic", "source_id": "LBNL2024_REPORT", "kind": "ENGINEERING_PRIOR", "confidence": "medium", "notes": "Table 4.2 dry cooler paragraph"},
        {"prior_id": "E7", "parameter": "chiller_supplemental_only_in_favorable_climates", "value": "parentheses in system names", "units": "n/a", "technology": "economizer systems", "source_id": "LBNL2024_REPORT", "kind": "ENGINEERING_PRIOR", "confidence": "high", "notes": "Table 4.2 note (1)"},
        {"prior_id": "E8", "parameter": "Prineville_2011_no_chiller_no_tower", "value": "OA evaporative only", "units": "n/a", "technology": "airside evaporative", "source_id": "META_ENGINEERING_2011", "kind": "ENGINEERING_PRIOR", "confidence": "high", "notes": "initial epoch only"},
    ]
    write_csv(ROOT / "data_processed" / "ENGINEERING_PRIORS.csv", eng, eng_fields)

    val_fields = [
        "technology", "source_id", "evidence_class", "variables", "measured_vs_modeled",
        "temporal_resolution", "geography", "climate", "period_n", "energy_boundary",
        "water_boundary", "raw_data_availability", "quantitative_comparison_possible",
        "independence", "quality", "relevance", "limitations", "confidence",
    ]
    val = [
        {"technology": "air-cooled IT / generic P_fac structure", "source_id": "M100_FROZEN", "evidence_class": "MEASURED_INDEPENDENT", "variables": "P_IT, P_cool, P_aux, weather", "measured_vs_modeled": "MEASURED", "temporal_resolution": "hourly", "geography": "IT", "climate": "site", "period_n": "2021 HQ months", "energy_boundary": "facility meters", "water_boundary": "none", "raw_data_availability": "yes in m100", "quantitative_comparison_possible": "NO vs Lei WUE; YES vs P_fac=P_IT+P_nonIT", "independence": "YES", "quality": "high", "relevance": "structure only", "limitations": "not generic PUE; no WUE", "confidence": "high structure / unsupported WUE"},
        {"technology": "direct liquid IT HPC", "source_id": "FRONTIER_ORNL", "evidence_class": "MEASURED_INDEPENDENT", "variables": "P_compute, P_facility, loop T, Q formula", "measured_vs_modeled": "MEASURED", "temporal_resolution": "sub-hourly", "geography": "US-TN", "climate": "4A-like", "period_n": "public extract", "energy_boundary": "facility/compute", "water_boundary": "not used", "raw_data_availability": "xlsx", "quantitative_comparison_possible": "NO vs Lei 2025 WUE; PARTIAL vs liquid energy overhead", "independence": "YES", "quality": "high energy", "relevance": "liquid heat capture energy", "limitations": "one supercomputer; not rear-door vs immersion split", "confidence": "medium for energy, unsupported WUE"},
        {"technology": "all Lei 2025 labels", "source_id": "LEI2025_UES16", "evidence_class": "SAME_LEI_MASANET_LINEAGE", "variables": "PUE,WUE pairs", "measured_vs_modeled": "MODELED", "temporal_resolution": "annual", "geography": "US", "climate": "19 zones", "period_n": "19000", "energy_boundary": "PUE", "water_boundary": "WUE-site", "raw_data_availability": "yes", "quantitative_comparison_possible": "self-consistency only", "independence": "NO vs Lei 2022/LBNL2024", "quality": "high as model output", "relevance": "primary proxy", "limitations": "not field data", "confidence": "n/a as validation of itself"},
        {"technology": "stock mix", "source_id": "LBNL2024_REPORT", "evidence_class": "SAME_LEI_MASANET_LINEAGE", "variables": "aggregate PUE/WUE", "measured_vs_modeled": "MODELED+ADJUSTED", "temporal_resolution": "annual national", "geography": "US", "climate": "965 stations", "period_n": ">1e6 sims not public", "energy_boundary": "PUE", "water_boundary": "WUE-site", "raw_data_availability": "no microdata", "quantitative_comparison_possible": "NO row-level", "independence": "NO", "quality": "authoritative stock", "relevance": "triangulation of labels", "limitations": "industry adjustment", "confidence": "low as independent validation"},
        {"technology": "airside evaporative OA", "source_id": "META_ENGINEERING_2011", "evidence_class": "OPERATOR_SELF_REPORTED", "variables": "design PUE, WUE", "measured_vs_modeled": "DESIGN", "temporal_resolution": "point", "geography": "Prineville", "climate": "5B", "period_n": "1 design", "energy_boundary": "stated PUE", "water_boundary": "stated WUE (not 2023-24 holdout)", "raw_data_availability": "blog", "quantitative_comparison_possible": "only as design prior", "independence": "YES vs Lei code", "quality": "design not meter", "relevance": "Prineville epoch 1", "limitations": "do not calibrate Lei; do not use later Meta water", "confidence": "medium"},
        {"technology": "practices", "source_id": "EU_COC_BPG", "evidence_class": "ENGINEERING_STANDARD", "variables": "recommended designs", "measured_vs_modeled": "RECOMMENDED", "temporal_resolution": "n/a", "geography": "EU", "climate": "n/a", "period_n": "n/a", "energy_boundary": "practices", "water_boundary": "limited", "raw_data_availability": "no", "quantitative_comparison_possible": "NO", "independence": "YES", "quality": "guideline", "relevance": "priors", "limitations": "not a sample of PUE/WUE", "confidence": "low as empirical"},
        {"technology": "hybrid thermosyphon + cooling tower HPC", "source_id": "NREL_ESIF_TSC_2018", "evidence_class": "MEASURED_INDEPENDENT", "variables": "PUE, WUE-site", "measured_vs_modeled": "MEASURED", "temporal_resolution": "monthly/annual 24 months", "geography": "US-CO", "climate": "5B-like", "period_n": "24 months", "energy_boundary": "facility PUE", "water_boundary": "onsite WUE (towers+humidification)", "raw_data_availability": "paper; not row-level makeup CSV", "quantitative_comparison_possible": "PARTIAL vs evaporative/hybrid classes; NOT a Lei case match", "independence": "YES", "quality": "high measured joint energy-water", "relevance": "shows measured WUE 0.70 L/kWh after TSC vs counterfactual 1.27", "limitations": "do not fit Lei; heat-recovery first; one site", "confidence": "high as existence of measured WUE, low as k-specific validation"},
        {"technology": "ESIF HPC energy", "source_id": "NREL_ESIF_PUE_CATALOG", "evidence_class": "MEASURED_INDEPENDENT", "variables": "PUE, cooling_kW, IT_kW", "measured_vs_modeled": "MEASURED", "temporal_resolution": "sub-hourly", "geography": "US-CO", "climate": "5B-like", "period_n": "public extract", "energy_boundary": "facility components", "water_boundary": "none", "raw_data_availability": "yes parquet (not downloaded this pass)", "quantitative_comparison_possible": "NO vs WUE", "independence": "YES", "quality": "high energy", "relevance": "hourly energy later", "limitations": "electricity-only does not validate WUE", "confidence": "high energy / unsupported water"},
    ]
    write_csv(ROOT / "data_processed" / "INDEPENDENT_VALIDATION_MATRIX.csv", val, val_fields)

    # coverage figure data already; write simple coverage csv for figure 5
    cov_rows = []
    for t in tax:
        cov_rows.append({
            "technology": t["source_label"],
            "modeled_lei2025": "yes",
            "hourly_simulator_public": "yes" if t["liquid_it"] == "no" and t["tech_id"] not in ("DRY_ACC", "DRY_AD_ACC") else "no_or_unverified",
            "independent_energy": "M100/Frontier structural only",
            "independent_WUE": "no",
        })
    write_csv(ROOT / "analysis" / "independent_validation_coverage.csv", cov_rows, list(cov_rows[0].keys()))

    prv_fields = ["configuration_id", "period", "technology", "direct_evidence", "indirect_evidence", "alternatives", "confidence", "used_meta_2023_2024_water"]
    prv = [
        {"configuration_id": "PRN_EPOCH1_2011_DESIGN", "period": "initial Prineville design (~2011 commissioning of first halls)", "technology": "100% outside-air evaporative cooling + humidification; no chiller plant; no cooling tower", "direct_evidence": "Meta engineering 2011 article (SOURCE_INSTRUCTIONS META_ENGINEERING_2011)", "indirect_evidence": "project gray-box implements this class; not a measurement", "alternatives": "none for the stated design epoch", "confidence": "HIGH for that design class; not a claim that all later MW use it", "used_meta_2023_2024_water": "NO"},
        {"configuration_id": "PRN1_2021_2024_MECHANICAL", "period": "PRN1 addition; hydronic test 2023-09-21; additional chiller operational 2024-02-02", "technology": "chilled-water / CRAH / chiller present (permit documentary)", "direct_evidence": "Crook County permits 217-21-003734-MECH, 217-24-000066-MECH as catalogued in pipeline_report/figure2_event_timeline.csv", "indirect_evidence": "MANUAL_ACQUISITION.md remaining one-line/chiller schedule gap", "alternatives": "could map approximately to airside+chiller or waterside+chiller Lei cases; not identified", "confidence": "HIGH that mechanical cooling exists at PRN1 by 2024; LOW Lei-case assignment", "used_meta_2023_2024_water": "NO"},
        {"configuration_id": "CAMPUS_MIX_UNRESOLVED", "period": "multi-building campus through 2020s", "technology": "mixture plausible: evaporative OA halls + later mechanical/CHW; liquid IT not identified in public permits reviewed here", "direct_evidence": "insufficient public equipment schedules for campus-wide k", "indirect_evidence": "reclaimed/ASR water infrastructure is source-side, not cooling-architecture identification", "alternatives": "retain multiple technology scenarios; do not pick k by matching Meta WUE", "confidence": "LOW as a single k", "used_meta_2023_2024_water": "NO"},
    ]
    write_csv(ROOT / "analysis" / "PRINEVILLE_COOLING_IDENTIFICATION.csv", prv, prv_fields)

    gap_fields = ["quantity", "identified_by_WUE_site", "public_source", "project_source", "outreach_or_permit", "likely_resolution", "importance_groundwater", "notes"]
    gaps = [
        {"quantity": "onsite conditioning water W_cond / WUE_site", "identified_by_WUE_site": "YES as modeled intensity", "public_source": "Lei 2025 pairs; not site meters", "project_source": "gray-box evaporative index (not makeup)", "outreach_or_permit": "no", "likely_resolution": "annual or hourly modeled", "importance_groundwater": "upstream of bridge", "notes": "this module ends here"},
        {"quantity": "City withdrawal/delivery to campus", "identified_by_WUE_site": "NO", "public_source": "City meters exist in Prineville module (WATER-COMM)", "project_source": "yes — do not treat as WUE", "outreach_or_permit": "package already obtained", "likely_resolution": "monthly", "importance_groundwater": "high for municipal share", "notes": "not cooling-tech calibration"},
        {"quantity": "reclaimed-water share", "identified_by_WUE_site": "NO", "public_source": "city/ASR documents", "project_source": "partial documentary", "outreach_or_permit": "maybe", "likely_resolution": "annual/unknown", "importance_groundwater": "high", "notes": "source allocation Ψ"},
        {"quantity": "direct well / Vitesse POD", "identified_by_WUE_site": "NO", "public_source": "OWRD WUR", "project_source": "yes", "outreach_or_permit": "no for existing exports", "likely_resolution": "monthly water-year", "importance_groundwater": "high", "notes": "not WUE"},
        {"quantity": "sewer/discharge / blowdown destination", "identified_by_WUE_site": "NO (draw-off is inside modeled WUE but not a sewer meter)", "public_source": "SWR METER physical direction unknown", "project_source": "unresolved", "outreach_or_permit": "yes", "likely_resolution": "monthly if obtained", "importance_groundwater": "high for return", "notes": ""},
        {"quantity": "consumption fraction", "identified_by_WUE_site": "NO", "public_source": "Meta defines consumption as withdrawal-discharge or CoC; not used here", "project_source": "not from Lei WUE", "outreach_or_permit": "n/a", "likely_resolution": "annual if disclosed", "importance_groundwater": "medium", "notes": "do not read 2023-24 holdout to fit this module"},
        {"quantity": "source-specific pumping energy", "identified_by_WUE_site": "NO", "public_source": "not in Lei", "project_source": "groundwater module", "outreach_or_permit": "n/a", "likely_resolution": "hourly/monthly", "importance_groundwater": "high", "notes": "outside cooling proxy"},
    ]
    write_csv(ROOT / "analysis" / "WATER_SOURCE_BRIDGE_GAPS.csv", gaps, gap_fields)

    sim = {
        "timestamp_utc": utcnow(),
        "found_hourly_simulator_for_lei2022_air_IT": True,
        "repository": "nuoaleon/Data-Center-Water-footprint",
        "commit": masanet_up,
        "technologies_supported": "eight PUE_WUE_* air-IT functions; no liquid IT",
        "required_inputs": "T, RH, P hourly + Table 3 facility parameters + COP pickles",
        "weather_support": "TMY3 EPW / any hourly T,RH,P",
        "reproducibility_status": "code runs; annual UE.xlsx envelopes PARTIAL/FAIL in masanet V1; V2 running — not rerun here",
        "found_hourly_simulator_for_lei2025_liquid_cases": False,
        "lei2025_repo_contents": "UEs_16cases.csv, SPEC_2024.xlsx, Sobol/SA CSVs, SI Rmd, SALib notebook — analysis of annual pairs and workload water, not the physical hourly engine",
        "other_hourly_models_found_different_lineage": {
            "EnergyPlus_OpenStudio_data_center_prototypes": "LBNL/NREL prototype CRAC and CRAH+chiller models exist; not the Lei liquid-case engine; not used to generate UEs_16cases",
            "NREL_ESIF_PUE_parquet": "measured electricity timeseries, not a simulator",
        },
        "lbnl2024_million_simulation_microdata": "NOT FOUND as public CSV/XLSX",
        "search": [
            "github.com/nuoaleon/The-Water-Use-of-Data-Center-Workloads-A-Review-and-Assessment-of-Key-Determinants",
            "LBNL 2024 report supplements / eScholarship / eta-publications — no microdata CSV located",
            "nuoaleon/Geospatial-assessment-of-water-footprints — XGB surrogates of earlier air-IT cases, not liquid hourly physics",
        ],
        "decision": "RETAIN modern cooling as annual/climate paired proxies. Do not reverse-engineer hourly physics from UEs_16cases.csv. Do not treat EnergyPlus prototypes as Lei 2025 liquid validation.",
        "limitations": "Cannot currently simulate rear-door vs cold-plate vs immersion hourly under Prineville weather from public code.",
    }
    (ROOT / "analysis" / "EXTENDED_SIMULATOR_AVAILABILITY.json").write_text(json.dumps(sim, indent=2) + "\n")

    # patch independence policy
    qc_path = ROOT / "analysis" / "COOLING_PROXY_QC.json"
    qc = json.loads(qc_path.read_text())
    qc["independence_diagnostic"]["PAIRED_SAMPLING_REQUIRED"] = True
    qc["independence_diagnostic"]["policy"] = (
        "Source emits joint (PUE,WUE) pairs. Downstream MUST sample pairs. "
        "Empirical dependence is technology-specific: water-cooled chiller median Pearson ~0.38; "
        "dry-cooler/liquid-dry near 0. Independent marginals produce >10% off-support draws in 17/304 cells "
        "and are forbidden even where correlation is weak."
    )
    qc["independence_diagnostic"]["n_cells_frac_gt_0p10"] = 17
    qc_path.write_text(json.dumps(qc, indent=2) + "\n")

    print(json.dumps({"lei2025_commit": lei_commit, "n_sources": len(sources)}, indent=2))


if __name__ == "__main__":
    main()
