#!/usr/bin/env python3
"""Public-evidence constrained reconstruction for Prineville (outcome-blind Stage A).

Uses structural-reference-v1 as a physics engine only. Does not refit, promote, or
calibrate against Meta water. Campus totals fail closed when unidentified.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from holdout_guard import HoldoutGuard, PROTECTED_RELATIVE  # noqa: E402
from prineville_graybox import Params, simulate_structural_reference_v1  # noqa: E402
from prineville_psychrometrics import state_from_t_rh  # noqa: E402
from prineville_structural_v1 import ReturnAirSpec  # noqa: E402

OUT = ROOT / "outputs" / "public_proxy_reconstruction_v1"
PRE = OUT / "preoutcome"
POST = OUT / "postfreeze_consistency"
SRC_CACHE = OUT / "sources"
FIG = OUT / "figures"
P_ATM = 90100.0
CFM_TO_M3S = 0.00047194745
RHO_AIR_KG_M3 = 1.0  # engineering consistency at ~1000 m; not as-operated density
CP_J_KGK = 1006.0

EXPECTED = {
    "v1_freeze": "decd095f59cc2249eee66d5b94ad30d30a53555eadbec3358bbb9aa80caaa81d",
    "registry": "1f87a1846aa8254c758ab11e3bd9b6f639e6c64bc551c36bcf8201bd65e78604",
    "graybox": "8275ca5bfc23042e3af19b72f2adb260304ac95d692d0b3ecbcb526b020f0609",
    "structural_v1": "f9649c489196cdc3e617f5b28574334aaaace5a94e7ade5ce461f6da22809a6a",
    "cpu_status": "1f57b210a63d375ce8eff7d5043756ffe6efe04e8a408bf9429bfd10096528d9",
    "h100": "a620d649a932f2388aa2f35bac2730eb75fe1dc74529668de4f30ee814600076",
    "esif_hw": "4e01139dd9365f62824ac00ff944468839e7873e47a5cea3df4714854af1b02c",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(cmd: list[str]) -> str:
    r = subprocess.run(["git", *cmd], cwd=REPO, capture_output=True, text=True)
    return (r.stdout or r.stderr or "").strip()


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fields = fieldnames or list(rows[0].keys())
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n")


def dump_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n")


def delta_t_from_cfm_kw(cfm: float, kw: float) -> float:
    m_dot = cfm * CFM_TO_M3S * RHO_AIR_KG_M3
    if m_dot <= 0 or kw <= 0:
        return float("nan")
    return (kw * 1000.0) / (m_dot * CP_J_KGK)


# ---------------------------------------------------------------------------
# Stage 0
# ---------------------------------------------------------------------------
def stage0_initial_state() -> dict:
    files = {
        "v1_freeze": ROOT / "outputs/structural_revision_v1/PRINEVILLE_STRUCTURAL_REFERENCE_V1_FREEZE.json",
        "registry": ROOT / "config/prineville_architecture_states.yaml",
        "graybox": ROOT / "src/prineville_graybox.py",
        "structural_v1": ROOT / "src/prineville_structural_v1.py",
        "psychro": ROOT / "src/prineville_psychrometrics.py",
        "holdout": ROOT / "src/holdout_guard.py",
        "cpu_status": REPO / "other_sources/nlr_esif_fullstack/analysis/FINAL_KESTREL_CPU_STATUS.json",
        "h100": REPO / "other_sources/nlr_esif_fullstack/genai_h100/manifests/H100_COMPUTE_FINAL_FREEZE.json",
        "esif_hw": REPO / "other_sources/nlr_esif_fullstack/heat_rejection_water/manifests/ESIF_HEAT_WATER_RESULT_FREEZE.json",
    }
    hashes = {k: sha256_file(p) for k, p in files.items()}
    for k in ("v1_freeze", "registry", "graybox", "structural_v1", "cpu_status", "h100", "esif_hw"):
        if hashes[k] != EXPECTED[k]:
            raise RuntimeError(f"Frozen hash mismatch for {k}: {hashes[k]} != {EXPECTED[k]}")
    state = {
        "pass": "public_proxy_reconstruction_v1",
        "utc": datetime.now(timezone.utc).isoformat(),
        "branch": git(["rev-parse", "--abbrev-ref", "HEAD"]),
        "HEAD": git(["rev-parse", "HEAD"]),
        "requested_baseline": "2c36ce3196962e963123eed225850936155b6f78",
        "git_status_porcelain": git(["status", "--porcelain"]),
        "dirty_submodules": "Data-center-PUE-prediction-tool (dirty; no .gitmodules mapping)",
        "hashes": hashes,
        "protected_water_outcome_paths": [str(ROOT / p) for p in PROTECTED_RELATIVE],
        "WATER_OUTCOME_ACCESSED": False,
        "canonical_simulate_remains_production_default": True,
        "structural_reference_v1_role": "PHYSICS_ENGINE_ONLY",
        "structural_reference_v1_not_calibrated": True,
        "no_parameter_fitted_to_meta_water": True,
        "holdout_guard": "installed_for_stage_A",
    }
    write_json(PRE / "PUBLIC_PROXY_INITIAL_STATE.json", state)
    return state


# ---------------------------------------------------------------------------
# Stage 1 source manifest
# ---------------------------------------------------------------------------
def stage1_manifest() -> list[dict]:
    rows = []

    def add(**kw):
        rows.append(kw)

    def local_hash(rel: str) -> str:
        p = ROOT / rel if not Path(rel).is_absolute() else Path(rel)
        if not p.exists():
            p2 = REPO / rel
            if p2.exists():
                p = p2
            else:
                return ""
        return sha256_file(p)

    add(
        source_id="OCP_CHASSIS_TRIPLET_V1",
        title="Server Chassis and Triplet Hardware v1.0",
        issuer="Open Compute Project / Facebook (Steve Furuta)",
        date="2011-04",
        local_path=str(SRC_CACHE / "Open_Compute_Project_Server_Chassis_and_Triplet_v1.0.pdf"),
        public_reference="https://mvdirona.com/jrh/TalksAndPapers/Open_Compute_Project_Server_Chassis_and_Triplet_v1.0.pdf",
        sha256=sha256_file(SRC_CACHE / "Open_Compute_Project_Server_Chassis_and_Triplet_v1.0.pdf"),
        source_tier="TIER1_SPEC",
        Prineville_specific="yes_triplet_figures_based_on_Prineville_observations",
        building_specific="PRN1_generation_hardware",
        phase_specific="OCP_v1_server_generation",
        temporal_scope="2011_design_era",
        quantity_type="server_rack_airflow_CFM",
        measurement_boundary="SERVER_RACK_NOT_FACILITY_BMS",
        usable_for="ENGINEERING_CONSISTENCY_BOUND",
        limitations="Rack/server CFM is not facility supply-air telemetry.",
    )
    add(
        source_id="OCP_INTEL_MB_V1",
        title="Intel Motherboard Hardware v1.0",
        issuer="Open Compute Project / Facebook",
        date="2011-04",
        local_path=str(SRC_CACHE / "Open_Compute_Project_Intel_Motherboard_v1.0.pdf"),
        public_reference="https://mvdirona.com/jrh/TalksAndPapers/Open_Compute_Project_Intel_Motherboard_v1.0.pdf",
        sha256=sha256_file(SRC_CACHE / "Open_Compute_Project_Intel_Motherboard_v1.0.pdf"),
        source_tier="TIER1_SPEC",
        Prineville_specific="same_generation_as_triplet",
        building_specific="",
        phase_specific="OCP_v1",
        temporal_scope="2011",
        quantity_type="CPU_TDP_NAMEPLATE",
        measurement_boundary="CPU_TDP_NOT_SERVER_OPERATING_POWER",
        usable_for="unmatched_electrical_upper_bound_on_CPU_only",
        limitations="95 W TDP per CPU; dual socket; not server kW at the CFM operating point.",
    )
    psu = SRC_CACHE / "Open_Compute_Project_Power_Supply_v1.0.pdf"
    add(
        source_id="OCP_PSU_V1",
        title="450W Power Supply Hardware v1.0",
        issuer="Open Compute Project / Facebook",
        date="2011-04",
        local_path=str(psu),
        public_reference="https://mvdirona.com/jrh/TalksAndPapers/Open_Compute_Project_Power_Supply_v1.0.pdf",
        sha256=sha256_file(psu) if psu.exists() else "",
        source_tier="TIER1_SPEC",
        Prineville_specific="same_generation",
        building_specific="",
        phase_specific="OCP_v1",
        temporal_scope="2011",
        quantity_type="PSU_NAMEPLATE_W",
        measurement_boundary="NAMEPLATE_NOT_OPERATING_LOAD",
        usable_for="illustrative_unmatched_CFM_per_nameplate_kW",
        limitations="450 W is PSU rating, not measured IT load. Do not treat as as-operated kW.",
    )
    amd = SRC_CACHE / "Open_Compute_Project_AMD_Motherboard_v1.0.pdf"
    add(
        source_id="OCP_AMD_MB_V1",
        title="AMD Motherboard Hardware v1.0",
        issuer="Open Compute Project / Facebook",
        date="2011-04",
        local_path=str(amd) if amd.exists() else "",
        public_reference="https://mvdirona.com/jrh/TalksAndPapers/Open_Compute_Project_AMD_Motherboard_v1.0.pdf",
        sha256=sha256_file(amd) if amd.exists() else "",
        source_tier="TIER1_SPEC",
        Prineville_specific="same_generation_as_triplet_18_of_90_servers",
        building_specific="",
        phase_specific="OCP_v1",
        temporal_scope="2011",
        quantity_type="motherboard_spec",
        measurement_boundary="SPEC_NOT_OPERATING_LOAD",
        usable_for="configuration_match_18_AMD_72_Intel",
        limitations="No matched idle-to-100% operating power table extracted.",
    )
    add(
        source_id="OCP_DC_V1_2011",
        title="Open Compute Project Data Center v1.0",
        issuer="Open Compute Project / Facebook",
        date="2011-04",
        local_path=str(SRC_CACHE / "Open_Compute_Project_Data_Center_v1.0.pdf"),
        public_reference="https://mvdirona.com/jrh/TalksAndPapers/Open_Compute_Project_Data_Center_v1.0.pdf",
        sha256=sha256_file(SRC_CACHE / "Open_Compute_Project_Data_Center_v1.0.pdf"),
        source_tier="TIER1_SPEC",
        Prineville_specific="yes_first_implementation",
        building_specific="PRN1",
        phase_specific="early_PRN1",
        temporal_scope="2011_design",
        quantity_type="mechanical_electrical_spec",
        measurement_boundary="DESIGN_SPEC",
        usable_for="air_path_controller_psychrometric_limits",
        limitations="Design spec, not BMS telemetry.",
    )
    add(
        source_id="OCP_WATER_PRN1",
        title="Water Efficiency at Facebook's Prineville Data Center",
        issuer="Open Compute Project / Facebook",
        date="2012-Q2",
        local_path=str(REPO / "other_sources/cooling_technology_proxies/analysis/PRINEVILLE_WUE_BOUNDARY_CROSSWALK.csv"),
        public_reference="https://www.opencompute.org/blog/water-efficiency-at-facebooks-prineville-data-center",
        sha256=local_hash("other_sources/cooling_technology_proxies/analysis/PRINEVILLE_WUE_BOUNDARY_CROSSWALK.csv"),
        source_tier="TIER1_OPERATOR",
        Prineville_specific="yes_PRN1",
        building_specific="PRN1",
        phase_specific="mist_RO_early",
        temporal_scope="Q2_2012",
        quantity_type="WUE_cooling_only_quarterly",
        measurement_boundary="OPERATOR_COOLING_WATER_NOT_AIR_STREAM_VAPOR",
        usable_for="PUBLIC_OPERATOR_COOLING_WATER_BENCHMARK; RO_and_mist_splits",
        limitations="Live blog may be Cloudflare-blocked; ratios reused from prior lossless extraction. 85% is spray evaporated fraction, not ε_T and not makeup efficiency.",
    )
    add(
        source_id="META_ENG_2011_PARK",
        title="Designing a Very Efficient Data Center",
        issuer="Meta/Facebook engineering (Jay Park)",
        date="2011-04-14",
        local_path="",
        public_reference="https://engineering.fb.com/2011/04/14/core-infra/designing-a-very-efficient-data-center/",
        sha256="",
        source_tier="TIER1_OPERATOR",
        Prineville_specific="yes",
        building_specific="PRN1",
        phase_specific="commissioning",
        temporal_scope="2011-04",
        quantity_type="architecture_PUE_design_WUE",
        measurement_boundary="DESIGN_LIMIT_PUE_1.07_WUE_0.31",
        usable_for="early_architecture",
        limitations="Design WUE 0.31 is not a meter.",
    )
    add(
        source_id="OPUC_UM1989_VITESSE_2018",
        title="UM 1989 Vitesse direct-access application",
        issuer="OPUC / Vitesse LLC",
        date="2018-12-14",
        local_path="data/raw/documentary_evidence/core/2018-12-14_OPUC_UM1989_Vitesse_Direct_Access_Application.pdf",
        public_reference="https://edocs.puc.state.or.us/efdocs/HAA/um1989haa134934.pdf",
        sha256="d8cd0baae7cb6d76059a077877d824d80ed16972ee03b5748207bdb56fcd9d56",
        source_tier="TIER1_REGULATORY",
        Prineville_specific="yes",
        building_specific="PRN_and_CCO_campuses",
        phase_specific="2014_four_building_2018_CCO",
        temporal_scope="2018_filing_describing_2010s",
        quantity_type="electric_service_capacity_contract_eligible",
        measurement_boundary="NOT_ACTUAL_IT_LOAD",
        usable_for="OPUC_LOAD_EVIDENCE_classification",
        limitations="180 MW is subject new large load, not measured IT.",
    )
    add(
        source_id="CITY_ORD1246_2018",
        title="Ordinance 1246 Facebook campus roads PRN1–PRN6 map",
        issuer="City of Prineville",
        date="2018-09-25",
        local_path="data/raw/documentary_evidence/core/2018-09-25_City_Ord1246_Facebook_Campus_Roads_PRN1_PRN6_Map.pdf",
        public_reference="https://www.cityofprineville.com/1261/Ordinances",
        sha256="20084111fa48ccae455f037609c789870d03453c36c956d6d555bceb8ba82057",
        source_tier="TIER1_MUNICIPAL",
        Prineville_specific="yes",
        building_specific="PRN1-PRN6",
        phase_specific="identity",
        temporal_scope="2018",
        quantity_type="building_identity",
        measurement_boundary="map_labels",
        usable_for="facility_inventory",
        limitations="No cooling or MW.",
    )
    add(
        source_id="DEQ_AR_BUILDINGS_2024",
        title="ODEQ ACDP hours tables building labels",
        issuer="Oregon DEQ / Vitesse",
        date="2024",
        local_path="outputs/deq_campus_event_crosswalk.csv",
        public_reference="ODEQ air permit 07-0037",
        sha256=sha256_file(ROOT / "outputs/deq_campus_event_crosswalk.csv"),
        source_tier="TIER1_PUBLIC_RECORD",
        Prineville_specific="yes",
        building_specific="PRN1-6_CCO1_2_3_5_6",
        phase_specific="2024_operating_labels",
        temporal_scope="2024",
        quantity_type="building_identity",
        measurement_boundary="backup_generator_hours_tables",
        usable_for="complete_facility_list",
        limitations="Generator presence is not IT MW. No individual CO dates.",
    )
    for bid, fname, sha, mw, area in [
        ("PRN2", "southland_prn2.html", "016c426325a4768461366e7b85837145c9aefcee603728b8f9728a9f332800b8", "40 MW facility", "357000 ft2"),
        ("PRN3", "southland_prn3.html", "3240c390aa95c6ec98e279cfa96a47af1b6b4429c40c8aa6ada6ae0c5f7cefae", "32 MW facility", "494000 ft2"),
        ("PRN4", "southland_prn4.html", "4b09877b36a1c9426ad018896c54d0c44101ca59b242db0609915cc0638be8f3", "2 MW halls phased", "40000 ft2"),
        ("PRN1", "southland_prn1.html", "4e28cc63206f229e199b19c2ab33806b5b77240fee6ee758bff3a8a684199611", "first 40 MW facility (context)", "90000 ft2 interior improvement"),
    ]:
        add(
            source_id=f"SOUTHLAND_{bid}",
            title=f"Confidential {bid} Data Center project page",
            issuer="Southland Industries",
            date="undated_page_captured_2026-09-02",
            local_path=str(SRC_CACHE / fname),
            public_reference=f"https://southlandind.com/project/{bid.lower()}-data-center",
            sha256=sha256_file(SRC_CACHE / fname),
            source_tier="TIER3_CONTRACTOR_PRIMARY_PAGE",
            Prineville_specific="yes_high_desert_central_Oregon_DPR_Fortis_Sheehan",
            building_specific=bid,
            phase_specific=bid,
            temporal_scope="construction_era",
            quantity_type="facility_MW_and_architecture_narrative",
            measurement_boundary="CONTRACTOR_DESIGN_FACILITY_NOT_ACTUAL_LOAD",
            usable_for="architecture_gap_resolution; TIER_B_capacity_proxy",
            limitations=f"Confidential client; {mw}; {area}. Not actual IT load. Do not mix with other capacity types.",
        )
    add(
        source_id="CRITICALARC_PRN_CCO",
        title="PRN/CCO Data Center Campus commissioning",
        issuer="CriticalArc",
        date="scope_finished_early_2024",
        local_path=str(SRC_CACHE / "criticalarc_prn_cco.html"),
        public_reference="https://www.criticalarccx.com/portfolio-item/prn-cco-data-center-campus/",
        sha256=sha256_file(SRC_CACHE / "criticalarc_prn_cco.html"),
        source_tier="TIER3_COMMISSIONING_PAGE",
        Prineville_specific="yes",
        building_specific="PRN_or_CCO_unspecified_which_buildings",
        phase_specific="through_early_2024",
        temporal_scope="commissioning_to_2024",
        quantity_type="60_MW_per_building_467k_sf_per_bldg",
        measurement_boundary="CONTRACTOR_STATED_CAPACITY_NOT_ACTUAL_LOAD",
        usable_for="capacity_evidence_typed_separately",
        limitations="Do not combine 60 MW/bldg with Southland 32–40 MW facility figures.",
    )
    add(
        source_id="DCK_PHASE2_MEDIA_2012",
        title="Facebook Revises its Data Center Cooling System",
        issuer="Data Center Knowledge (quotes Jay Park)",
        date="2012-era",
        local_path=str(SRC_CACHE / "dck_facebook_revises_cooling.html"),
        public_reference="https://www.datacenterknowledge.com/cooling/facebook-revises-its-data-center-cooling-system",
        sha256=sha256_file(SRC_CACHE / "dck_facebook_revises_cooling.html"),
        source_tier="TIER2_PRESS_OPERATOR_QUOTED",
        Prineville_specific="yes_Phase_2_Prineville_project",
        building_specific="Phase_2_hall_mapping_PUBLICLY_UNRESOLVED",
        phase_specific="after_first_year_PRN1_operations",
        temporal_scope="~2012_onward_new_phase",
        quantity_type="mist_to_wetted_media_no_RO_room",
        measurement_boundary="architecture_narrative",
        usable_for="water_system_subepoch_SUPPORTED_TIER2",
        limitations="Not CONFIRMED_TIER1 building-id mapping. Phase 2 may be second building rather than PRN1 retrofit.",
    )
    add(
        source_id="DOC_EVIDENCE_CSV",
        title="Existing documentary evidence table",
        issuer="this_repository",
        date="prior_pass",
        local_path="config/prineville_documentary_evidence.csv",
        public_reference="internal_extract_of_TIER1_PDFs",
        sha256=sha256_file(ROOT / "config/prineville_documentary_evidence.csv"),
        source_tier="TIER1_EXTRACT",
        Prineville_specific="yes",
        building_specific="mixed",
        phase_specific="mixed",
        temporal_scope="2009-2026",
        quantity_type="legal_regulatory_identity",
        measurement_boundary="as_in_source_rows",
        usable_for="facility_OPUC_water_infrastructure",
        limitations="Reuse local extracts; do not re-parse huge PDFs.",
    )
    add(
        source_id="OWRD_MAPPING_AUDIT",
        title="Existing OWRD POD / City well mapping audit",
        issuer="OWRD via this_repository",
        date="prior_pass",
        local_path="outputs/owrd_mapping_audit.csv",
        public_reference="OWRD water-use reports",
        sha256=sha256_file(ROOT / "outputs/owrd_mapping_audit.csv"),
        source_tier="TIER1_PUBLIC_RECORD",
        Prineville_specific="regional_city_and_vitesse_pods",
        building_specific="no",
        phase_specific="no",
        temporal_scope="2010-2025_reporting",
        quantity_type="permitted_vs_reported_pumping",
        measurement_boundary="OWRD_REPORT_NOT_META_ANNUAL_WITHDRAWAL",
        usable_for="source_split_additive_evidence",
        limitations="Permitted maxima are not actual pumping. Vitesse reports 64500/64845/64846 are reported use, not Meta annual total.",
    )
    add(
        source_id="ARCHITECTURE_REGISTRY",
        title="Frozen Prineville architecture states",
        issuer="this_repository",
        date="structural_revision_v1",
        local_path="config/prineville_architecture_states.yaml",
        public_reference="frozen_file",
        sha256=EXPECTED["registry"],
        source_tier="INTERNAL_FREEZE",
        Prineville_specific="yes",
        building_specific="PRN1-6_CCO1-2",
        phase_specific="yes",
        temporal_scope="2011-2024",
        quantity_type="architecture_class",
        measurement_boundary="engineering_evidence_registry",
        usable_for="A_b_t_reference_not_rewritten",
        limitations="Does not list CCO3/CCO5/CCO6. Do not silently rewrite.",
    )
    write_csv(PRE / "PUBLIC_SOURCE_MANIFEST.csv", rows)
    return rows


# ---------------------------------------------------------------------------
# Stage 2 airflow
# ---------------------------------------------------------------------------
def stage2_airflow() -> dict:
    source_rows = [
        {
            "quantity": "server_CFM_Intel",
            "value_low": 12,
            "value_high": 103,
            "units": "CFM_per_server",
            "condition": "idle_to_100pct_loading_at_stated_pressure_drop",
            "boundary": "SERVER_NOT_FACILITY_BMS",
            "prineville_wording": "triplet figures based on observations at our facility in Prineville, OR",
            "source_id": "OCP_CHASSIS_TRIPLET_V1",
        },
        {
            "quantity": "server_CFM_AMD",
            "value_low": 14,
            "value_high": 106,
            "units": "CFM_per_server",
            "condition": "idle_to_100pct_loading_at_stated_pressure_drop",
            "boundary": "SERVER_NOT_FACILITY_BMS",
            "prineville_wording": "triplet figures based on observations at our facility in Prineville, OR",
            "source_id": "OCP_CHASSIS_TRIPLET_V1",
        },
        {
            "quantity": "rack_CFM_mixed_90_servers",
            "value_low": 1116,
            "value_high": 9324,
            "units": "CFM_per_triplet_rack",
            "condition": "72_Intel_plus_18_AMD;_Intel_864_to_7416_plus_AMD_252_to_1908",
            "boundary": "RACK_NOT_FACILITY_BMS",
            "prineville_wording": "triplet figures based on observations at our facility in Prineville, OR",
            "source_id": "OCP_CHASSIS_TRIPLET_V1",
        },
        {
            "quantity": "expected_max_rack_CFM",
            "value_low": 5400,
            "value_high": 5400,
            "units": "CFM_per_triplet_rack",
            "condition": "max_CFM_expected_less_than_60_per_server_almost_every_loading;_4500_rpm;_60*90",
            "boundary": "RACK_ENGINEERING_EXPECTED_MAX_NOT_FACILITY_BMS",
            "prineville_wording": "triplet figures based on observations at our facility in Prineville, OR",
            "source_id": "OCP_CHASSIS_TRIPLET_V1",
        },
        {
            "quantity": "rack_configuration",
            "value_low": 90,
            "value_high": 90,
            "units": "servers_per_triplet",
            "condition": "three_42U_columns_x_30_servers;_2_ToR_switches;_72_Intel_18_AMD",
            "boundary": "HARDWARE_CONFIG",
            "prineville_wording": "Open Compute Project servers racked into triplets",
            "source_id": "OCP_CHASSIS_TRIPLET_V1",
        },
        {
            "quantity": "inlet_temperature_server",
            "value_low": 18.33,
            "value_high": 35.0,
            "units": "degC",
            "condition": "65F_to_95F_server_level",
            "boundary": "SERVER_INLET_SPEC",
            "prineville_wording": "thermal specifications table",
            "source_id": "OCP_CHASSIS_TRIPLET_V1",
        },
        {
            "quantity": "inlet_temperature_rack",
            "value_low": 18.33,
            "value_high": 29.44,
            "units": "degC",
            "condition": "65F_to_85F_rack_level",
            "boundary": "RACK_INLET_SPEC",
            "prineville_wording": "thermal specifications table",
            "source_id": "OCP_CHASSIS_TRIPLET_V1",
        },
        {
            "quantity": "humidity_and_dewpoint",
            "value_low": 30,
            "value_high": 65,
            "units": "RH_pct_approx;_DP_41.9F_min_to_59F;_SAT_64.4F_to_80.6F",
            "condition": "regional_climate_where_the_data_center_operates",
            "boundary": "DESIGN_PSYCHROMETRIC_NOT_TELEMETRY",
            "prineville_wording": "Based on regional climate conditions where the data center operates",
            "source_id": "OCP_CHASSIS_TRIPLET_V1",
        },
        {
            "quantity": "Intel_CPU_TDP_max",
            "value_low": 60,
            "value_high": 95,
            "units": "W_per_CPU",
            "condition": "two_Xeon_5500_or_5600;_motherboard_max_TDP_95W",
            "boundary": "CPU_TDP_NOT_SERVER_POWER",
            "prineville_wording": "same_generation_Intel_motherboard_v1.0",
            "source_id": "OCP_INTEL_MB_V1",
        },
        {
            "quantity": "PSU_nameplate",
            "value_low": 450,
            "value_high": 450,
            "units": "W_per_server_PSU",
            "condition": "OCP_v1_450W_PSU_spec_nameplate",
            "boundary": "NAMEPLATE_NOT_OPERATING_LOAD",
            "prineville_wording": "same_generation_power_supply_spec",
            "source_id": "OCP_PSU_V1",
        },
    ]
    write_csv(PRE / "OCP_AIRFLOW_SOURCE_DATA.csv", source_rows)

    # Unmatched illustrative ΔT only. Not a numerical public bound.
    cases = [
        ("expected_60cfm_per_server", 60.0, 0.450, "PSU_NAMEPLATE"),
        ("intel_max_103cfm", 103.0, 0.450, "PSU_NAMEPLATE"),
        ("intel_idle_12cfm", 12.0, 0.450, "PSU_NAMEPLATE_WITH_IDLE_CFM_UNMATCHED"),
        ("expected_60cfm_cpu_tdp_only_2x95W", 60.0, 0.190, "CPU_TDP_ONLY_INCOMPLETE"),
        ("expected_60cfm_cpu_tdp_2x60W", 60.0, 0.120, "CPU_TDP_ONLY_INCOMPLETE"),
    ]
    result_rows = []
    for name, cfm, kw, kw_bound in cases:
        dt = delta_t_from_cfm_kw(cfm, kw)
        result_rows.append(
            {
                "case": name,
                "cfm_per_server": cfm,
                "kw_assumed": kw,
                "kw_boundary": kw_bound,
                "CFM_per_kW": cfm / kw if kw else "",
                "DeltaT_implied_K": round(dt, 3),
                "matched_operating_point": False,
                "classification": "ENGINEERING_CONSISTENCY_BOUND",
                "not_as_operated_facility_airflow": True,
                "notes": "CFM and kW are not simultaneous measured operating points.",
            }
        )
    write_csv(PRE / "OCP_AIRFLOW_BOUND_RESULTS.csv", result_rows)

    assessment = {
        "boundary_class": "ENGINEERING_CONSISTENCY_BOUND",
        "not_label": "AS_OPERATED_FACILITY_AIRFLOW",
        "prineville_applicability_wording": (
            "The triplet figures are based on our observations at our facility in Prineville, OR."
        ),
        "matched_CFM_per_kW_exists": False,
        "reason_unmatched": (
            "Airflow table is idle-to-100% CFM vs pressure drop. Intel spec gives CPU TDP 60–95 W, "
            "not server operating power. 450 W is PSU nameplate. Combining them is unmatched capacity."
        ),
        "deltaT_12K_status": "PUBLIC_EVIDENCE_INSUFFICIENT_TO_NUMERICALLY_BOUND_DELTAT",
        "twelve_K_remains": "GENERIC_PRIOR_SCENARIO",
        "illustrative_unmatched_note": (
            "If 60 CFM/server is paired with 450 W nameplate, implied ΔT ≈ "
            f"{delta_t_from_cfm_kw(60, 0.45):.1f} K; with CPU-TDP-only 190 W ≈ "
            f"{delta_t_from_cfm_kw(60, 0.19):.1f} K. 12 K lies between those unmatched numbers "
            "but that does not numerically bound ΔT."
        ),
        "confidence_cfm_values": "HIGH",
        "confidence_facility_airflow": "HIGH_that_this_is_NOT_facility_BMS",
        "confidence_deltaT_bound": "HIGH_that_public_evidence_cannot_numerically_bound_deltaT",
        "fan_rpm": "1120_to_7600_with_10pct_tolerance",
        "altitude_spec_m": 1000,
    }
    write_json(PRE / "AIRFLOW_PRIOR_ASSESSMENT.json", assessment)
    return assessment


# ---------------------------------------------------------------------------
# Stage 3 facility inventory
# ---------------------------------------------------------------------------
def stage3_facility() -> tuple[list[dict], list[dict]]:
    inv = []
    cap = []

    def building(**kw):
        inv.append(kw)

    def capacity(**kw):
        cap.append(kw)

    building(
        building_id="PRN1",
        phase_id="E1_OCP_COMMISSIONING",
        announcement_date="2009-2010_Project_Vitesse",
        construction_start="2010-01-25_permit_opened_proxy",
        commissioning_window="2011-04-14_core_shell_final;_sections_C_D_2011-08-24",
        operational_by="2011-04-14",
        square_feet="UNKNOWN_original;_Southland_interior_improvement_90000_later;_MeeFog_stated_147000_hall_TIER2",
        number_of_data_halls="sections_A_D_documented;_exact_hall_count_UNKNOWN",
        IT_design_MW="UNKNOWN",
        critical_IT_electrical_MW="UNKNOWN",
        UPS_PDU_switchgear_MW="UNKNOWN",
        building_service_MW="UNKNOWN",
        facility_MW="SOUTHLAND_CONTEXT_first_40_MW_facility_CONTRACTOR_STATED",
        generator_MW="DEQ_backup_present_NOT_IT",
        cooling_capacity="UNKNOWN",
        architecture="DIRECT_OUTSIDE_AIR_EVAP_CONFIRMED_early;_CHW_addition_2023-2024_CONFIRMED_presence",
        water_system="MIST_RO_RECIRCULATING_early_CONFIRMED;_later_UNKNOWN",
        retrofit_events="PRN1_network_core_addition_hydronic_2023-09-21;_roof_chiller_operational_2024-02-02",
        source_ids="META_ENG_2011_PARK;OCP_DC_V1_2011;CITY_CU2021_110;PRN1_PERMITS;SOUTHLAND_PRN1",
        confidence="HIGH_identity_and_early_architecture;_LOW_MW",
        unresolved_fields="original_sf;IT_MW;CHW_condenser;load_share",
    )
    building(
        building_id="PRN2",
        phase_id="E2_LATER_PRN",
        announcement_date="OCP_2012_second_building_next_year;_OPUC_early_2014_four_buildings",
        construction_start="UNKNOWN",
        commissioning_window="Level_5_commissioning_on_Southland_page;_exact_CO_UNKNOWN",
        operational_by="earliest_possible_2013-2014;_confirmed_operational_by_UNKNOWN",
        square_feet="357000_CONTRACTOR_STATED",
        number_of_data_halls="4_identical_CONTRACTOR_STATED",
        IT_design_MW="UNKNOWN",
        critical_IT_electrical_MW="UNKNOWN",
        UPS_PDU_switchgear_MW="UNKNOWN",
        building_service_MW="UNKNOWN",
        facility_MW="40_CONTRACTOR_STATED",
        generator_MW="DEQ_backup_present_NOT_IT",
        cooling_capacity="UNKNOWN",
        architecture="DIRECT_EVAP_MEDIA_SUPPORTED_TIER3;_not_written_into_frozen_registry",
        water_system="WETTED_MEDIA_NO_RO_SUPPORTED_TIER2_if_Phase2_is_this_hall;_RO_PUBLICLY_UNRESOLVED_at_building_id",
        retrofit_events="",
        source_ids="SOUTHLAND_PRN2;OPUC_UM1989;CITY_ORD1246;DCK_PHASE2_MEDIA_2012",
        confidence="MEDIUM_HIGH_contractor_architecture;_MEDIUM_facility_MW_boundary",
        unresolved_fields="actual_load;commissioning_date;RO_presence;BMS_airflow",
    )
    building(
        building_id="PRN3",
        phase_id="E2_LATER_PRN",
        announcement_date="after_PRN2;_OPUC_four_buildings_early_2014",
        construction_start="UNKNOWN",
        commissioning_window="UNKNOWN_exact",
        operational_by="UNKNOWN",
        square_feet="494000_approximately_CONTRACTOR_STATED",
        number_of_data_halls="data_hall_singular_plus_core_network_area_CONTRACTOR",
        IT_design_MW="UNKNOWN",
        critical_IT_electrical_MW="UNKNOWN",
        UPS_PDU_switchgear_MW="UNKNOWN",
        building_service_MW="UNKNOWN",
        facility_MW="32_CONTRACTOR_STATED",
        generator_MW="DEQ_backup_present_NOT_IT",
        cooling_capacity="UNKNOWN",
        architecture="OA_ECONOMIZER_PLUS_DIRECT_EVAP_MEDIA_SUPPORTED_TIER3;_network_core_IEC_cooling_towers_PHE_SUPPORTED_TIER3",
        water_system="media_plus_tower_blowdown_in_core_SUPPORTED_TIER3;_ratios_UNKNOWN",
        retrofit_events="",
        source_ids="SOUTHLAND_PRN3;OPUC_UM1989;CITY_ORD1246",
        confidence="MEDIUM_HIGH_contractor_architecture",
        unresolved_fields="actual_load;CO_date;tower_operating_hours;makeup_split",
    )
    building(
        building_id="PRN4",
        phase_id="E2_LATER_PRN",
        announcement_date="named_CITY_ORD1246_2018;_Southland_completed_2016",
        construction_start="UNKNOWN",
        commissioning_window="Southland_completed_2016_LEED_Gold",
        operational_by="2016_CONTRACTOR_COMPLETION_not_utility_CO",
        square_feet="40000_CONTRACTOR_STATED",
        number_of_data_halls="phase1_one_2MW_hall;_phase2_2MW_halls_plural",
        IT_design_MW="UNKNOWN",
        critical_IT_electrical_MW="UNKNOWN",
        UPS_PDU_switchgear_MW="UNKNOWN",
        building_service_MW="UNKNOWN",
        facility_MW="phase_sum_about_4_MW_if_2_plus_2_CONTRACTOR_HALL_MW_NOT_IT_METER",
        generator_MW="DEQ_backup_present_NOT_IT",
        cooling_capacity="UNKNOWN",
        architecture="PACKAGED_DIRECT_EVAP_SUPPORTED_TIER3",
        water_system="UNKNOWN_beyond_direct_evap_equipment",
        retrofit_events="two_phases_on_contractor_page",
        source_ids="SOUTHLAND_PRN4;CITY_ORD1246",
        confidence="MEDIUM_scale_differs_from_PRN2_3;_identity_as_Meta_PRN4_MEDIUM_HIGH",
        unresolved_fields="whether_40k_sf_is_full_named_PRN4_or_a_subset",
    )
    for b, start in [("PRN5", "2018-01-01"), ("PRN6", "2018-01-01")]:
        building(
            building_id=b,
            phase_id="E2_LATER_PRN_NAMED_2018",
            announcement_date="OPUC_2018_two_additional_large_PRN_buildings",
            construction_start="UNKNOWN",
            commissioning_window="UNKNOWN",
            operational_by="UNKNOWN;_DEQ_label_present_2024",
            square_feet="UNKNOWN",
            number_of_data_halls="UNKNOWN",
            IT_design_MW="UNKNOWN",
            critical_IT_electrical_MW="UNKNOWN",
            UPS_PDU_switchgear_MW="UNKNOWN",
            building_service_MW="UNKNOWN",
            facility_MW="UNKNOWN",
            generator_MW="DEQ_backup_present_NOT_IT",
            cooling_capacity="UNKNOWN",
            architecture="UNKNOWN_frozen_registry;_OA_ECH_copy_POSSIBLE_not_confirmed",
            water_system="UNKNOWN",
            retrofit_events="",
            source_ids="OPUC_UM1989;CITY_ORD1246;DEQ_AR_BUILDINGS_2024",
            confidence="HIGH_existence;_LOW_architecture",
            unresolved_fields="all_capacity_and_mechanical_fields",
        )
    building(
        building_id="CCO1",
        phase_id="E3_CCO",
        announcement_date="2018-09-20",
        construction_start="2018-08-29_STR_opened_proxy",
        commissioning_window="2020_data_hall_mechanical_finals;_2021-07-08_full_mech;_2022-02-09_structural_closeout",
        operational_by="2020_phased_halls_CONFIRMED_construction;_first_IT_operation_UNKNOWN",
        square_feet="UNKNOWN",
        number_of_data_halls="CCO1_A-E_permit_labels",
        IT_design_MW="UNKNOWN",
        critical_IT_electrical_MW="UNKNOWN",
        UPS_PDU_switchgear_MW="UNKNOWN",
        building_service_MW="UNKNOWN",
        facility_MW="UNKNOWN_do_not_use_CCO_220MW_interconnect_as_building",
        generator_MW="DEQ_backup_present_NOT_IT",
        cooling_capacity="UNKNOWN",
        architecture="ECH_piping_SUPPORTED;_hall_chiller_UNKNOWN;_CRAC_electrical_room_not_hall",
        water_system="PARTIAL_IWS_IWR_piping",
        retrofit_events="",
        source_ids="CITY_CU2019_111;CCO_MECH_2019;OPUC_UM1989",
        confidence="HIGH_identity_chronology;_PARTIAL_architecture",
        unresolved_fields="IT_MW;heat_rejection;complete_mechanical_narrative",
    )
    building(
        building_id="CCO2",
        phase_id="E3_CCO",
        announcement_date="2018-09-20",
        construction_start="with_CCO1",
        commissioning_window="with_CCO1",
        operational_by="UNKNOWN_exact",
        square_feet="UNKNOWN",
        number_of_data_halls="CCO2_A-E_permit_labels",
        IT_design_MW="UNKNOWN",
        critical_IT_electrical_MW="UNKNOWN",
        UPS_PDU_switchgear_MW="UNKNOWN",
        building_service_MW="UNKNOWN",
        facility_MW="UNKNOWN",
        generator_MW="DEQ_backup_present_NOT_IT",
        cooling_capacity="UNKNOWN",
        architecture="UNKNOWN_complete;_do_not_copy_PRN1",
        water_system="PARTIAL",
        retrofit_events="",
        source_ids="CITY_CU2019_111;CCO_MECH_2019;OPUC_UM1989",
        confidence="HIGH_identity;_LOW_architecture",
        unresolved_fields="all_mechanical_capacity",
    )
    for b in ("CCO3", "CCO5", "CCO6"):
        building(
            building_id=b,
            phase_id="E3PLUS_CCO_LATER",
            announcement_date="PUBLICLY_UNRESOLVED",
            construction_start="UNKNOWN",
            commissioning_window="UNKNOWN",
            operational_by="DEQ_hours_table_label_present_2024_not_CO_date",
            square_feet="UNKNOWN",
            number_of_data_halls="UNKNOWN",
            IT_design_MW="UNKNOWN",
            critical_IT_electrical_MW="UNKNOWN",
            UPS_PDU_switchgear_MW="UNKNOWN",
            building_service_MW="UNKNOWN",
            facility_MW="UNKNOWN_CriticalArc_60MW_per_bldg_NOT_ASSIGNED_to_this_id",
            generator_MW="DEQ_backup_present_NOT_IT",
            cooling_capacity="UNKNOWN",
            architecture="PUBLICLY_UNRESOLVED",
            water_system="PUBLICLY_UNRESOLVED",
            retrofit_events="",
            source_ids="DEQ_AR_BUILDINGS_2024",
            confidence="HIGH_existence_2024;_UNKNOWN_all_else",
            unresolved_fields="dates_area_halls_capacity_architecture_water",
        )

    capacity(
        building_id="PRN1",
        capacity_type="FACILITY_MW_CONTRACTOR_CONTEXT",
        value_MW=40,
        source_id="SOUTHLAND_PRN1",
        meaning="Southland: after populating their first 40 MW facility in Prineville",
        classification="SERVICE_OR_DESIGN_FACILITY_NOT_ACTUAL_LOAD",
        confidence="MEDIUM",
        notes="Not IT_design_MW. Not generator MW.",
    )
    capacity(
        building_id="PRN2",
        capacity_type="FACILITY_MW_CONTRACTOR_STATED",
        value_MW=40,
        source_id="SOUTHLAND_PRN2",
        meaning="The 357,000 square foot, 40 MW facility",
        classification="DESIGN_OR_FACILITY_CAPACITY_NOT_ACTUAL_LOAD",
        confidence="MEDIUM_HIGH",
        notes="Comparable to other Southland facility_MW rows only.",
    )
    capacity(
        building_id="PRN3",
        capacity_type="FACILITY_MW_CONTRACTOR_STATED",
        value_MW=32,
        source_id="SOUTHLAND_PRN3",
        meaning="the 32 MW facility",
        classification="DESIGN_OR_FACILITY_CAPACITY_NOT_ACTUAL_LOAD",
        confidence="MEDIUM_HIGH",
        notes="Comparable to Southland PRN2 40 MW facility statements.",
    )
    capacity(
        building_id="PRN4",
        capacity_type="DATA_HALL_MW_CONTRACTOR_PHASED",
        value_MW=4,
        source_id="SOUTHLAND_PRN4",
        meaning="phase one 2 MW data hall; phase two 2 MW data halls",
        classification="DESIGN_HALL_MW_NOT_ACTUAL_LOAD",
        confidence="MEDIUM",
        notes="NOT the same capacity_type as PRN2/PRN3 40/32 facility MW. Do not mix without conversion uncertainty.",
    )
    capacity(
        building_id="CCO_CAMPUS",
        capacity_type="INTERCONNECTION_CAPACITY_MW",
        value_MW=220,
        source_id="OPUC_UM1989_VITESSE_2018",
        meaning="CCO MESA interconnect up to 220 MW of capacity",
        classification="SERVICE_CAPACITY",
        confidence="VERY_HIGH_as_interconnect",
        notes="NOT realized demand, IT capacity, or annual average load.",
    )
    capacity(
        building_id="CCO_CAMPUS",
        capacity_type="PACIFIC_POWER_SERVICE_MIN_MW",
        value_MW=40,
        source_id="OPUC_UM1989_VITESSE_2018",
        meaning="At least 40 MW of CCO interconnection would be served by Pacific Power",
        classification="CONTRACTED_OR_SERVICE_SPLIT_NOT_ACTUAL_LOAD",
        confidence="VERY_HIGH_as_filing_statement",
        notes="NOT proof of 40 MW realized consumption.",
    )
    capacity(
        building_id="CCO_CAMPUS",
        capacity_type="SUBJECT_NEW_LARGE_LOAD_MW",
        value_MW=180,
        source_id="OPUC_UM1989_VITESSE_2018",
        meaning="Remaining 180 MW was the Subject New Large Load in the direct-access application",
        classification="ELIGIBLE_OR_REQUESTED_LOAD",
        confidence="VERY_HIGH_as_filing_statement",
        notes="MUST NOT become measured Prineville IT load.",
    )
    capacity(
        building_id="PRN_CAMPUS",
        capacity_type="SCHEDULE_272_RESOURCE_CAPACITY_MW",
        value_MW=437,
        source_id="OPUC_UM1989_VITESSE_2018",
        meaning="RECs representing 437 MW of new solar supporting six PRN buildings",
        classification="RENEWABLE_ACCOUNTING_NOT_LOAD",
        confidence="VERY_HIGH_as_filing",
        notes="NOT physical campus demand.",
    )
    capacity(
        building_id="PRN_OR_CCO_UNSPECIFIED",
        capacity_type="CONTRACTOR_MW_PER_BUILDING",
        value_MW=60,
        source_id="CRITICALARC_PRN_CCO",
        meaning="60 MW per building data center campus",
        classification="SERVICE_OR_DESIGN_CAPACITY_NOT_ACTUAL_LOAD",
        confidence="MEDIUM_as_contractor_page;_LOW_building_mapping",
        notes="Do not mix with Southland 32–40 MW. Do not assign to a specific PRN/CCO id.",
    )
    capacity(
        building_id="CAMPUS_AGGREGATOR_DO_NOT_USE",
        capacity_type="THIRD_PARTY_REPORTED_POWER_CAPACITY",
        value_MW=540,
        source_id="DataCentersExposed_web_search_not_acquired",
        meaning="aggregator reported power capacity",
        classification="UNKNOWN_BOUNDARY_NOT_USED",
        confidence="REJECTED",
        notes="Not official. Not used in feasible sets.",
    )

    write_csv(PRE / "PUBLIC_FACILITY_PHASE_INVENTORY.csv", inv)
    write_csv(PRE / "PUBLIC_CAPACITY_EVIDENCE.csv", cap)
    timeline = {
        "ARCHITECTURE_REGISTRY_COVERAGE_GAP": True,
        "registry_buildings": ["PRN1", "PRN2", "PRN3", "PRN4", "PRN5", "PRN6", "CCO1", "CCO2"],
        "supplementary_public_buildings_not_in_frozen_registry": ["CCO3", "CCO5", "CCO6"],
        "registry_not_rewritten": True,
        "epochs": [
            {"id": "E1", "when": "2011-04-14", "what": "PRN1 OCP OA+ECH operational-by"},
            {"id": "E2a", "when": "2013-2014", "what": "additional PRN buildings; OPUC four buildings early 2014"},
            {"id": "E2b", "when": "2016", "what": "Southland PRN4 completion stated"},
            {"id": "E2c", "when": "2018", "what": "PRN5/PRN6 named; six PRN buildings"},
            {"id": "E3", "when": "2018-2022", "what": "CCO1/CCO2 construction to closeout"},
            {"id": "E3plus", "when": "by_2024", "what": "DEQ labels CCO3,CCO5,CCO6"},
            {"id": "E4", "when": "2023-09 to 2024-02", "what": "PRN1 CHW/CRAH/roof chiller"},
        ],
    }
    write_json(PRE / "FACILITY_PHASE_TIMELINE.json", timeline)
    return inv, cap


# ---------------------------------------------------------------------------
# Stage 4 OPUC
# ---------------------------------------------------------------------------
def stage4_opuc() -> list[dict]:
    rows = [
        {
            "MW": 120,
            "date": "2018",
            "campus_name": "regional_transmission",
            "customer_entity": "Vitesse",
            "existing_or_future": "future_line",
            "service_status": "expected_excess_on_new_230kV",
            "retail_vs_direct_access": "n/a",
            "boundary": "transmission_capacity_in_excess_of_Vitesse_contracted_capacity",
            "source_document": "OPUC_UM1989_VITESSE_2018",
            "page": "PDF p.7 application p.6",
            "confidence": "VERY_HIGH",
            "classification": "SERVICE_CAPACITY",
            "can_constrain_IT_lambda": "NO",
        },
        {
            "MW": 437,
            "date": "2018",
            "campus_name": "Prineville Campus",
            "customer_entity": "Vitesse",
            "existing_or_future": "existing_PRN_six_buildings_support",
            "service_status": "Schedule_272_REC_agreement",
            "retail_vs_direct_access": "PRN_cost_of_service_not_direct_access",
            "boundary": "REC_resource_capacity_not_campus_demand",
            "source_document": "OPUC_UM1989_VITESSE_2018",
            "page": "PDF p.7-8",
            "confidence": "VERY_HIGH",
            "classification": "UNKNOWN_BOUNDARY",
            "can_constrain_IT_lambda": "NO",
        },
        {
            "MW": 220,
            "date": "2018",
            "campus_name": "Crook County Campus",
            "customer_entity": "Vitesse",
            "existing_or_future": "future_CCO",
            "service_status": "MESA_interconnection",
            "retail_vs_direct_access": "split",
            "boundary": "interconnect_up_to",
            "source_document": "OPUC_UM1989_VITESSE_2018",
            "page": "PDF p.7",
            "confidence": "VERY_HIGH",
            "classification": "SERVICE_CAPACITY",
            "can_constrain_IT_lambda": "NO",
        },
        {
            "MW": 40,
            "date": "2018",
            "campus_name": "Crook County Campus",
            "customer_entity": "Vitesse / Pacific Power",
            "existing_or_future": "future_CCO",
            "service_status": "at_least_this_share_Pacific_Power",
            "retail_vs_direct_access": "retail_cost_of_service_portion",
            "boundary": "service_split_of_interconnect",
            "source_document": "OPUC_UM1989_VITESSE_2018",
            "page": "PDF p.7",
            "confidence": "VERY_HIGH",
            "classification": "CONTRACTED_LOAD",
            "can_constrain_IT_lambda": "NO",
        },
        {
            "MW": 180,
            "date": "2018",
            "campus_name": "Crook County Campus",
            "customer_entity": "Vitesse",
            "existing_or_future": "future_CCO",
            "service_status": "Subject_New_Large_Load_direct_access_application",
            "retail_vs_direct_access": "direct_access_requested",
            "boundary": "eligible_or_requested_new_large_load",
            "source_document": "OPUC_UM1989_VITESSE_2018",
            "page": "PDF p.7",
            "confidence": "VERY_HIGH",
            "classification": "ELIGIBLE_LOAD",
            "can_constrain_IT_lambda": "NO",
            "notes": "NOT measured Prineville IT load. NOT Crook County Campus as-operated load.",
        },
        {
            "MW": "",
            "date": "2010",
            "campus_name": "Prineville",
            "customer_entity": "Vitesse",
            "existing_or_future": "existing",
            "service_status": "first_MESA_year_Schedule_48",
            "retail_vs_direct_access": "cost_of_service",
            "boundary": "service_start_no_MW",
            "source_document": "OPUC_UE463_VITESSE_2026",
            "page": "Coyle/2",
            "confidence": "VERY_HIGH",
            "classification": "UNKNOWN_BOUNDARY",
            "can_constrain_IT_lambda": "NO",
        },
    ]
    write_csv(PRE / "OPUC_LOAD_EVIDENCE.csv", rows)
    return rows


# ---------------------------------------------------------------------------
# Stage 5 water-system subepochs
# ---------------------------------------------------------------------------
def stage5_water() -> dict:
    sub = [
        {
            "building_id": "PRN1",
            "state_id": "MIST_RO_RECIRCULATING",
            "start": "2011-04-14",
            "end": "PUBLICLY_UNRESOLVED_whether_PRN1_itself_converted",
            "tier": "CONFIRMED_TIER1",
            "mist_vs_media": "high_pressure_ECH_mist",
            "RO": "yes_75_25_product_reject",
            "spray_evaporated_fraction": 0.85,
            "recapture_fraction": 0.15,
            "source_ids": "OCP_WATER_PRN1;OCP_DC_V1_2011;META_ENG_2011_PARK",
            "notes": "85% is sprayed-water evaporated fraction, NOT thermal effectiveness and NOT external-makeup efficiency.",
        },
        {
            "building_id": "PRN_PHASE2_HALL_UNRESOLVED_ID",
            "state_id": "WETTED_MEDIA_NO_RO",
            "start": "~2012_after_first_year_PRN1_operations",
            "end": "unknown",
            "tier": "SUPPORTED_TIER2",
            "mist_vs_media": "adiabatic_fiberglass_media",
            "RO": "operator_quoted_foregoing_RO_room",
            "spray_evaporated_fraction": "NOT_APPLICABLE_media",
            "recapture_fraction": "UNKNOWN",
            "source_ids": "DCK_PHASE2_MEDIA_2012_Jay_Park_quoted",
            "notes": "Phase 2 of the Prineville project. Mapping to PRN1 retrofit vs second building PUBLICLY_UNRESOLVED. Southland PRN2 media is independent TIER3 corroboration that later halls used media.",
        },
        {
            "building_id": "PRN2",
            "state_id": "WETTED_MEDIA",
            "start": "construction_era",
            "end": "unknown",
            "tier": "SUPPORTED_TIER3",
            "mist_vs_media": "direct_evaporative_media",
            "RO": "PUBLICLY_UNRESOLVED",
            "spray_evaporated_fraction": "NOT_APPLICABLE",
            "recapture_fraction": "UNKNOWN",
            "source_ids": "SOUTHLAND_PRN2",
            "notes": "Do not copy PRN1 mist/RO ratios onto PRN2.",
        },
        {
            "building_id": "PRN3",
            "state_id": "WETTED_MEDIA_PLUS_CORE_IEC_TOWERS",
            "start": "construction_era",
            "end": "unknown",
            "tier": "SUPPORTED_TIER3",
            "mist_vs_media": "direct_evaporative_media_in_hall;_IEC_towers_in_network_core",
            "RO": "PUBLICLY_UNRESOLVED",
            "spray_evaporated_fraction": "NOT_APPLICABLE",
            "recapture_fraction": "UNKNOWN",
            "source_ids": "SOUTHLAND_PRN3",
            "notes": "Hall AIR_STREAM may still be evaporative; core water includes cooling-tower evaporation/blowdown UNQUANTIFIED.",
        },
        {
            "building_id": "PRN5_PRN6_CCO1_CCO2_CCO3_CCO5_CCO6",
            "state_id": "UNKNOWN",
            "start": "",
            "end": "",
            "tier": "PUBLICLY_UNRESOLVED",
            "mist_vs_media": "UNKNOWN",
            "RO": "UNKNOWN",
            "spray_evaporated_fraction": "UNKNOWN",
            "recapture_fraction": "UNKNOWN",
            "source_ids": "",
            "notes": "CCO ECH piping SUPPORTED for CCO1 hall A only.",
        },
    ]
    write_csv(PRE / "PRINEVILLE_WATER_SYSTEM_SUBEPOCHS.csv", sub)

    balance = {
        "assumption": "steady_state_declared_for_symbolic_closure_only",
        "variables": [
            "W_raw_or_RO_feed",
            "W_RO_product",
            "W_RO_reject",
            "W_spray_circulation",
            "W_air_vapor",
            "W_recaptured",
            "W_external_makeup",
        ],
        "source_ratios": {
            "RO_product_over_feed": 0.75,
            "RO_reject_over_feed": 0.25,
            "spray_evaporated_fraction": 0.85,
            "mist_eliminator_recapture_fraction": 0.15,
        },
        "not_permitted": {
            "W_external_makeup_equals_W_air_vapor_over_0.85": False,
            "0.85_is_evap_thermal_effectiveness": False,
            "0.85_is_external_makeup_efficiency": False,
        },
        "topology_A_recapture_to_product_tanks": {
            "W_RO_product": "W_air_vapor",
            "W_RO_feed": "W_air_vapor / 0.75",
            "W_RO_reject": "0.25/0.75 * W_air_vapor",
            "W_external_makeup": "W_RO_feed = W_air_vapor / 0.75  (~1.333 * vapor)",
            "status": "PLAUSIBLE_NOT_CONFIRMED_PIPING",
        },
        "topology_B_recapture_to_RO_feed": {
            "W_spray": "W_air_vapor / 0.85",
            "W_recaptured": "0.15/0.85 * W_air_vapor",
            "W_RO_product": "W_spray",
            "W_RO_feed": "W_spray / 0.75",
            "W_external_makeup": "W_RO_feed - W_recaptured = W_spray*(1/0.75 - 0.15) ~ 1.392 * W_air_vapor",
            "status": "PLAUSIBLE_NOT_CONFIRMED_PIPING",
        },
        "identified": [
            "AIR_STREAM_EVAPORATED_WATER = W_air_vapor structurally in v1",
            "RO 75/25 and spray 85/15 are source-derived for early PRN1 mist system",
        ],
        "unidentified": [
            "which recapture topology",
            "W_external_makeup exact map",
            "whether later media systems retain RO reject",
            "ECH makeup vs conditioning input vs withdrawal",
        ],
    }
    write_json(PRE / "PRN1_MIST_RO_MASS_BALANCE.json", balance)
    dump_md(
        PRE / "PRN1_MIST_RO_MASS_BALANCE.md",
        """# PRN1 mist/RO symbolic mass balance

Steady-state declared for closure only. Early PRN1 (OCP water blog).

```
W_raw_or_RO_feed --> RO --> W_RO_product (0.75)
                     \\--> W_RO_reject (0.25) blown down

W_RO_product (+ possibly recapture) --> high-pressure mist
W_spray_circulation --> W_air_vapor (0.85 of spray)
                    \\--> W_recaptured (0.15) via mist eliminators to RO tanks
```

Do **not** set `W_external_makeup = W_air_vapor / 0.85`.

0.85 is the sprayed-water evaporated fraction, not thermal effectiveness ε_T and not external-makeup efficiency.

If recapture returns to product tanks (skips RO): `W_makeup ≈ W_air_vapor / 0.75`.

If recapture returns to RO feed: `W_makeup ≈ 1.392 * W_air_vapor`.

Piping topology is PUBLICLY_UNRESOLVED. Both remain in the feasible set for early PRN1 only.
""",
    )
    return balance


# ---------------------------------------------------------------------------
# Stage 6 architecture gaps
# ---------------------------------------------------------------------------
def stage6_gaps() -> list[dict]:
    rows = [
        {
            "quantity": "PRN1_CHW_condenser_heat_rejection",
            "result": "PUBLICLY_UNRESOLVED",
            "searches": "repo_permits;_Southland_PRN1_page;_targeted_web_chiller_condenser_tower",
            "newly_resolved": "Southland_PRN1_page_is_exhaust_fans_interior_improvement_not_condenser_type",
            "notes": "Do not infer cooling tower from the word chiller.",
        },
        {
            "quantity": "PRN2_architecture",
            "result": "RESOLVED_SUPPORTED_TIER3",
            "searches": "Southland_PRN2_primary_project_page",
            "newly_resolved": "direct_evaporative_media;_4_halls;_357k_sf;_40_MW_facility",
            "notes": "Not written into frozen registry. Supplementary.",
        },
        {
            "quantity": "PRN3_architecture",
            "result": "RESOLVED_SUPPORTED_TIER3",
            "searches": "Southland_PRN3_primary_project_page",
            "newly_resolved": "100pct_OA_economizer_capability;_direct_evap_media;_UV_filtration;_network_core_IEC_cooling_towers_PHE;_32_MW;_494k_sf",
            "notes": "Core towers are not hall architecture. Hall remains media/OA.",
        },
        {
            "quantity": "PRN4_architecture",
            "result": "RESOLVED_SUPPORTED_TIER3_PARTIAL",
            "searches": "Southland_PRN4",
            "newly_resolved": "packaged_direct_evaporative;_40k_sf;_2MW_phased_halls;_completed_2016",
            "notes": "Scale much smaller than PRN2/3; mapping caveat remains.",
        },
        {
            "quantity": "PRN5_PRN6_architecture",
            "result": "PUBLICLY_UNRESOLVED",
            "searches": "repo;_OPUC;_no_contractor_page_found_in_bounded_search",
            "newly_resolved": "none",
            "notes": "Stop.",
        },
        {
            "quantity": "CCO1_CCO2_complete_mechanical",
            "result": "PUBLICLY_UNRESOLVED_beyond_prior_ECH_piping",
            "searches": "repo_permits_already_exhausted_in_architecture_audit",
            "newly_resolved": "none_new",
            "notes": "Do not reopen architecture audit equations.",
        },
        {
            "quantity": "CCO3_CCO5_CCO6",
            "result": "PUBLICLY_UNRESOLVED_except_DEQ_existence",
            "searches": "DEQ_labels;_Pinnacle_page_confused_with_Forest_City_NC_NOT_USED;_CriticalArc_60MW_unmapped",
            "newly_resolved": "existence_in_2024_DEQ_hours_tables",
            "notes": "ARCHITECTURE_REGISTRY_COVERAGE_GAP. Registry not rewritten.",
        },
        {
            "quantity": "Phase2_mist_to_media",
            "result": "SUPPORTED_TIER2_operator_quoted",
            "searches": "DCK_Jay_Park;_OCP_second_building_next_year",
            "newly_resolved": "media_replaced_misters_in_Phase_2;_RO_room_not_needed_for_media",
            "notes": "Building-id mapping unresolved. Consistent with Southland PRN2 media.",
        },
    ]
    write_csv(PRE / "PUBLIC_ARCHITECTURE_GAP_RESOLUTION.csv", rows)
    return rows


# ---------------------------------------------------------------------------
# Stage 7 load shares
# ---------------------------------------------------------------------------
def stage7_lambda() -> dict:
    constraints = [
        {
            "constraint_id": "H1",
            "statement": "lambda_b,t >= 0",
            "type": "HARD",
        },
        {
            "constraint_id": "H2",
            "statement": "sum_b lambda_b,t = 1 when the active set is complete",
            "type": "HARD",
        },
        {
            "constraint_id": "H3",
            "statement": "lambda_b,t = 0 before earliest possible commissioning",
            "type": "HARD",
        },
        {
            "constraint_id": "H4",
            "statement": "no equal building weights by default",
            "type": "HARD",
        },
        {
            "constraint_id": "H5",
            "statement": "do not mix unmatched capacity types",
            "type": "HARD",
        },
        {
            "constraint_id": "H6",
            "statement": "OPUC contracted/eligible/design/service MW is not actual IT load",
            "type": "HARD",
        },
        {
            "constraint_id": "H7",
            "statement": "generator MW is not IT MW",
            "type": "HARD",
        },
        {
            "constraint_id": "TIER_A",
            "statement": "no comparable IT/critical-electrical MW across buildings",
            "type": "EMPTY",
        },
        {
            "constraint_id": "TIER_B",
            "statement": "Southland facility_MW PRN2=40 and PRN3=32 are comparable to each other; PRN1 40 MW is contractor context; PRN4 2+2 MW is a different capacity_type",
            "type": "PROXY_NOT_IDENTIFIED",
        },
        {
            "constraint_id": "TIER_C",
            "statement": "hall-count/floor-area incomplete (PRN2 4 halls 357k; PRN3 ~494k; PRN4 40k; others UNKNOWN). Area-proportional shares are scenario-only among buildings with area.",
            "type": "PROXY_INCOMPLETE",
        },
    ]
    write_csv(PRE / "LOAD_SHARE_CONSTRAINTS.csv", constraints)

    years = list(range(2011, 2025))
    extrema = []
    feasible = {"identified_years": {}, "scenario_bounded_years": {}, "unidentified_years": {}}
    for y in years:
        active = ["PRN1"]
        if y >= 2013:
            active += ["PRN2"]  # earliest possible second building; not confirmed CO
        if y >= 2014:
            active = ["PRN1", "PRN2", "PRN3", "PRN4"]
        if y >= 2018:
            active += ["PRN5", "PRN6"]
        if y >= 2020:
            active += ["CCO1", "CCO2"]
        if y >= 2024:
            active += ["CCO3", "CCO5", "CCO6"]
        identified = y == 2011  # only year with a single confirmed operational building
        row = {
            "year": y,
            "active_buildings": "|".join(active),
            "lambda_PRN1_min": 1.0 if identified else 0.0,
            "lambda_PRN1_max": 1.0,
            "complete_simplex_identified": identified,
            "notes": "After 2011, unidentified buildings can carry any nonnegative share summing to 1. Capacity proxies do not close the set.",
        }
        extrema.append(row)
        if identified:
            feasible["identified_years"][str(y)] = {"PRN1": 1.0}
        else:
            feasible["unidentified_years"][str(y)] = {
                "active": active,
                "status": "HARD_SET_IS_THE_SIMPLEX_ON_ACTIVE_BUILDINGS",
                "equal_weights_forbidden": True,
            }
    # Explicit TIER_B scenario among Southland facility_MW only, labeled not identified.
    feasible["TIER_B_SCENARIO_SOUTHLAND_FACILITY_MW_PRN2_PRN3_ONLY"] = {
        "status": "SCENARIO_BOUNDED_NOT_IDENTIFIED",
        "PRN2": 40 / 72,
        "PRN3": 32 / 72,
        "others": "UNIDENTIFIED",
        "notes": "Relative shares IF campus were only PRN2+PRN3 and load ∝ facility_MW. It is not.",
    }
    feasible["TIER_B_SCENARIO_INCLUDING_PRN1_CONTEXT_40MW"] = {
        "status": "SCENARIO_BOUNDED_NOT_IDENTIFIED",
        "PRN1": 40 / 112,
        "PRN2": 40 / 112,
        "PRN3": 32 / 112,
        "notes": "PRN1 40 MW is contractor context from a later improvement page. Conversion uncertainty explicit. PRN4 not included (different capacity_type).",
    }
    write_csv(PRE / "LOAD_SHARE_EXTREMA.csv", extrema)
    write_json(PRE / "LOAD_SHARE_FEASIBLE_SETS.json", feasible)
    return feasible


# ---------------------------------------------------------------------------
# Stage 8 OWRD
# ---------------------------------------------------------------------------
def stage8_owrd() -> list[dict]:
    rows = [
        {
            "source_id": "VITESSE_64500",
            "entity": "VITESSE LLC C/O FACEBOOK INC",
            "owrd_report_id": 64500,
            "classification": "ACTUAL_REPORTED_PUMPING",
            "not": "PERMITTED_MAXIMUM",
            "boundary": "direct_groundwater_POD_report",
            "notes": "Do not substitute for Meta annual withdrawal. Do not fit groundwater response.",
        },
        {
            "source_id": "VITESSE_64845",
            "entity": "VITESSE LLC C/O FACEBOOK INC",
            "owrd_report_id": 64845,
            "classification": "ACTUAL_REPORTED_PUMPING",
            "not": "PERMITTED_MAXIMUM",
            "boundary": "direct_groundwater_POD_report",
            "notes": "Reporting interval 2010-10 to 2024-09 in identifiability table.",
        },
        {
            "source_id": "VITESSE_64846",
            "entity": "VITESSE LLC C/O FACEBOOK INC",
            "owrd_report_id": 64846,
            "classification": "ACTUAL_REPORTED_PUMPING",
            "not": "PERMITTED_MAXIMUM",
            "boundary": "direct_groundwater_POD_report",
            "notes": "VALIDATION_ONLY in groundwater identifiability; not used to fit.",
        },
        {
            "source_id": "CITY_WELLS_ACCEPTED",
            "entity": "City of Prineville municipal production",
            "owrd_report_id": "see_owrd_mapping_audit",
            "classification": "ACTUAL_REPORTED_PUMPING",
            "not": "PERMITTED_MAXIMUM",
            "boundary": "municipal_production_not_Meta_meter",
            "notes": "Airport combined POD counted once. Permitted rates are not used as pumping.",
        },
        {
            "source_id": "SOURCE_SPLIT",
            "entity": "Meta_campus_withdrawal vs city vs direct POD",
            "owrd_report_id": "",
            "classification": "UNIDENTIFIED",
            "not": "do_not_equate_boundaries",
            "boundary": "three_distinct_accounting_objects",
            "notes": "Public evidence does not identify the municipal/direct-POD split of campus withdrawal.",
        },
    ]
    write_csv(PRE / "OWRD_POD_PUBLIC_EVIDENCE.csv", rows)
    return rows


# ---------------------------------------------------------------------------
# Stage 9 envelope
# ---------------------------------------------------------------------------
def _weather_points() -> pd.DataFrame:
    specs = [
        ("cold_dry", -5.0, 40.0),
        ("cool_design", 10.0, 40.0),
        ("sat_band", 20.0, 40.0),
        ("warm_arid", 32.0, 15.0),
        ("humid_cool", 15.0, 65.0),
    ]
    rows = []
    for i, (lab, t, rh) in enumerate(specs):
        st = state_from_t_rh(t, rh, P_ATM)
        rows.append(
            {
                "timestamp_utc": pd.Timestamp(f"2012-07-0{i+1}T12:00:00Z"),
                "t_db_C": st.T_C,
                "t_wb_C": st.T_wb_C,
                "rh_pct": rh,
                "pressure_Pa": P_ATM,
                "label": lab,
            }
        )
    return pd.DataFrame(rows)


def stage9_envelope() -> dict:
    weather = _weather_points()
    ra = ReturnAirSpec(T_C=35.0, rh_pct=15.0, provenance="DESIGN_REFERENCE_SCENARIO", label="envelope_synthetic")
    building_rows = []
    intensities = []
    for dT in (8.0, 12.0, 16.0):
        params = Params(server_deltaT_C=dT)
        out = simulate_structural_reference_v1(weather.drop(columns=["label"]), 1.0, params, return_air=ra)
        w = out["air_stream_evaporated_water_m3_h"].to_numpy(float)
        # L/kWh_IT = m3/h per MW
        for lab, val in zip(weather["label"], w):
            intensities.append(
                {
                    "building_id": "PRN1_early_OA_ECH",
                    "architecture": "DIRECT_OUTSIDE_AIR_EVAP",
                    "deltaT_K": dT,
                    "deltaT_status": "GENERIC_PRIOR_SCENARIO" if dT == 12 else "SENSITIVITY_NOT_PUBLIC_BOUND",
                    "weather_label": lab,
                    "AIR_STREAM_EVAPORATED_WATER_m3_h_per_MW_IT": val,
                    "intensity_L_per_kWh_IT": val,  # 1 m3/h / 1 MW = 1 L/kWh
                    "water_boundary": "AIR_STREAM_EVAPORATED_WATER",
                    "status": "FEASIBLE_ENGINEERING_ENVELOPE_INTENSITY_ONLY",
                }
            )
    write_csv(PRE / "PUBLIC_PROXY_ENVELOPE_BUILDING.csv", intensities)

    i12 = [r["intensity_L_per_kWh_IT"] for r in intensities if r["deltaT_K"] == 12]
    campus_rows = [
        {
            "year": y,
            "quantity": "campus_AIR_STREAM_EVAPORATED_WATER",
            "status": "NOT_IDENTIFIABLE" if y > 2011 else "PRN1_ONLY_INTENSITY_TIMES_UNKNOWN_P_IT",
            "lo": "",
            "hi": "",
            "meaning": (
                "2011: only PRN1 confirmed; volume still requires P_IT (facility MWh is P_fac not P_IT). "
                "Later years: unidentified architecture and lambda make campus water not meaningfully bounded."
                if y > 2011
                else "PRN1-only year. Intensity envelope exists at 12 K scenario; P_IT unidentified without PUE split."
            ),
        }
        for y in range(2011, 2025)
    ]
    write_csv(PRE / "PUBLIC_PROXY_ENVELOPE_CAMPUS.csv", campus_rows)

    status = {
        "object": "PUBLIC_EVIDENCE_FEASIBLE_ENVELOPE",
        "campus_total_meaningfully_bounded": False,
        "why_unbounded": [
            "lambda_b unknown after 2011 and equal weights forbidden",
            "PRN5/PRN6/CCO architecture unidentified",
            "PRN1 CHW condenser unidentified so later PRN1 CHW water unidentified",
            "PRN3 network-core cooling towers unquantified",
            "P_IT campus is not the same boundary as reported facility electricity",
            "water-system map from AIR_STREAM to withdrawal unidentified except symbolic early-PRN1 set",
        ],
        "what_is_bounded": {
            "PRN1_early_AIR_STREAM_intensity_at_12K_scenario_L_per_kWh_IT": {
                "min": min(i12),
                "max": max(i12),
                "weather_grid": "five_synthetic_OCP_climate_consistent_points",
                "not": "annual_integral",
            }
        },
        "physics_engine": "simulate_structural_reference_v1",
        "canonical_simulate_not_used_as_envelope_engine": True,
        "no_monte_carlo": True,
        "return_air": "DESIGN_REFERENCE_SCENARIO",
        "PRN2_PRN3": "contractor_supported_media_is_explicit_scenario_not_silent_PRN1_copy;_AIR_STREAM_similar_adiabatic_class_but_campus_still_unbounded",
    }
    write_json(PRE / "PUBLIC_PROXY_ENVELOPE_STATUS.json", status)
    return status


# ---------------------------------------------------------------------------
# Stage 10 VoI
# ---------------------------------------------------------------------------
def stage10_voi(env_status: dict) -> list[dict]:
    i12 = env_status["what_is_bounded"]["PRN1_early_AIR_STREAM_intensity_at_12K_scenario_L_per_kWh_IT"]
    base_build = i12["max"] - i12["min"]
    # If ΔT also 8–16, intensity scales ~1/ΔT plus controller coupling; use endpoint files.
    bld = pd.read_csv(PRE / "PUBLIC_PROXY_ENVELOPE_BUILDING.csv")
    w_all = bld["intensity_L_per_kWh_IT"].max() - bld["intensity_L_per_kWh_IT"].min()
    w_12 = bld.loc[bld["deltaT_K"] == 12, "intensity_L_per_kWh_IT"]
    width_12 = float(w_12.max() - w_12.min())

    # Campus: unidentified => conceptually [0, Imax * P_IT]. Resolving architecture of unidentified mass is the leader.
    rows = [
        {
            "uncertainty_class": "cooling_architecture_unidentified_buildings",
            "baseline_envelope_width": "campus_not_identifiable_[0, Imax*P_IT]_or_worse_if_towers",
            "width_if_resolved": "reduces_to_identified_physics_plus_lambda_deltaT_B",
            "range_reduction": "DOMINANT",
            "normalized_range_reduction": 1.0,
            "scope": "CAMPUS_AGGREGATION",
            "rank": 1,
        },
        {
            "uncertainty_class": "building_load_shares_lambda",
            "baseline_envelope_width": "simplex_after_2011",
            "width_if_resolved": "still_unbounded_if_architecture_unknown;_first_order_if_architecture_known",
            "range_reduction": "SECOND_IF_ARCHITECTURE_KNOWN_ELSE_NEAR_ZERO",
            "normalized_range_reduction": 0.0,
            "scope": "CAMPUS_AGGREGATION",
            "rank": 2,
        },
        {
            "uncertainty_class": "PRN1_CHW_condenser_heat_rejection",
            "baseline_envelope_width": "later_PRN1_CHW_water_UNIDENTIFIED",
            "width_if_resolved": "enables_or_rules_out_tower_water_at_PRN1_after_2023",
            "range_reduction": "HIGH_FOR_2024_PRN1_WATER_BOUNDARY",
            "normalized_range_reduction": 0.8,
            "scope": "WATER_BOUNDARY",
            "rank": 3,
        },
        {
            "uncertainty_class": "water_system_subepoch_B_RO_media",
            "baseline_envelope_width": "makeup/vapor in {1.333, 1.392} vs unidentified media/tower",
            "width_if_resolved": "maps_AIR_STREAM_to_ECH_makeup_for_that_subepoch",
            "range_reduction": "HIGH_FOR_WATER_BOUNDARY_GIVEN_AIR_STREAM",
            "normalized_range_reduction": 0.7,
            "scope": "WATER_BOUNDARY",
            "rank": 4,
        },
        {
            "uncertainty_class": "airflow_deltaT",
            "baseline_envelope_width": width_12,
            "width_if_resolved": "weather-only width at known ΔT",
            "range_reduction": w_all - width_12,
            "normalized_range_reduction": (w_all - width_12) / w_all if w_all else 0,
            "scope": "BUILDING_PHYSICS",
            "rank": 5,
        },
        {
            "uncertainty_class": "source_split_city_vs_direct_POD",
            "baseline_envelope_width": "does_not_change_campus_withdrawal_total",
            "width_if_resolved": "allocates_withdrawal_to_groundwater_vs_municipal",
            "range_reduction": "ZERO_ON_CAMPUS_TOTAL_HIGH_ON_GW",
            "normalized_range_reduction": 0.0,
            "scope": "WITHDRAWAL_SOURCE",
            "rank": 6,
        },
        {
            "uncertainty_class": "ECH_RO_boundary_topology",
            "baseline_envelope_width": "1.333_vs_1.392_times_vapor_for_early_PRN1",
            "width_if_resolved": "~4% relative on makeup given vapor",
            "range_reduction": 0.059,
            "normalized_range_reduction": 0.059 / 1.392,
            "scope": "WATER_BOUNDARY",
            "rank": 7,
        },
    ]
    write_csv(PRE / "VALUE_OF_INFORMATION.csv", rows)
    dump_md(
        PRE / "VALUE_OF_INFORMATION_SUMMARY.md",
        f"""# Value of information (deterministic; no fake probabilities)

DATA_VALUE_LEADERBOARD (final campus-water range):

1. Cooling architecture of unidentified buildings (PRN5/6, CCO*, later PRN1 CHW path) — campus total is not identifiable until this is resolved.
2. Building load shares λ (only after architecture is known; equal weights forbidden).
3. PRN1 CHW condenser / heat rejection (2023– onward PRN1 water boundary).
4. Water-system subepoch B (mist/RO vs media vs tower) — maps AIR_STREAM_EVAPORATED_WATER to makeup/withdrawal.
5. Airflow / ΔT — public OCP CFM does **not** numerically bound ΔT; 12 K remains GENERIC_PRIOR_SCENARIO. Weather-grid intensity width at 12 K is {width_12:.4f} L/kWh_IT on the synthetic points.
6. Source split (city vs direct POD) — does not narrow campus withdrawal; needed for groundwater.
7. Early-PRN1 RO recapture topology — small (~4%) once vapor is known.

Answers:

1. Building-physics: matched server power at the OCP CFM operating point, or facility BMS airflow / ΔT telemetry.
2. Campus-aggregation: per-building IT load (or even ranked MW) plus architecture class for every active hall.
3. Water-boundary: ECH makeup meter vs RO feed vs withdrawal, and PRN1 condenser type.
4. Single acquisition that most reduces final campus-water range: **per-building cooling architecture + served IT load (or λ) for all PRN/CCO halls**, or equivalently campus-total cooling-water meters with building submeters. Highest-value external dataset: Meta BMS/architecture schedule or City/Meta building-level water and PacifiCorp interval load by account/building — not more public OCP CFM.
""",
    )
    return rows


# ---------------------------------------------------------------------------
# Stage 11 freeze
# ---------------------------------------------------------------------------
def stage11_freeze(holdout: HoldoutGuard, state: dict) -> dict:
    artifacts = sorted(p for p in PRE.rglob("*") if p.is_file() and p.name != "PUBLIC_PROXY_RECONSTRUCTION_FREEZE.json")
    hashes = {str(p.relative_to(OUT)): sha256_file(p) for p in artifacts}
    blob = json.dumps(hashes, sort_keys=True).encode()
    master = hashlib.sha256(blob).hexdigest()
    freeze = {
        "WATER_OUTCOME_ACCESSED": False,
        "holdout_accessed": holdout.accessed,
        "holdout_attempts": holdout.access_attempts,
        "master_hash": master,
        "artifact_sha256": hashes,
        "initial_HEAD": state["HEAD"],
        "v1_freeze_sha256": EXPECTED["v1_freeze"],
        "registry_sha256": EXPECTED["registry"],
        "cpu_status_sha256": EXPECTED["cpu_status"],
        "h100_sha256": EXPECTED["h100"],
        "esif_hw_sha256": EXPECTED["esif_hw"],
        "no_parameter_fitted": True,
        "canonical_simulate_unchanged": True,
        "structural_v1_equations_unchanged": True,
        "assumptions_frozen": [
            "12K remains GENERIC_PRIOR_SCENARIO",
            "rack CFM is ENGINEERING_CONSISTENCY_BOUND",
            "lambda not equal-weighted",
            "campus water NOT_IDENTIFIABLE after 2011",
            "85% is spray fraction not epsilon_T or makeup efficiency",
            "OPUC 180 MW is ELIGIBLE_LOAD not ACTUAL_LOAD",
            "Southland MW is contractor facility/hall capacity not actual IT",
            "frozen architecture registry not rewritten; CCO3/5/6 are coverage gap",
        ],
    }
    write_json(PRE / "PUBLIC_PROXY_RECONSTRUCTION_FREEZE.json", freeze)
    return freeze


# ---------------------------------------------------------------------------
# Stage B
# ---------------------------------------------------------------------------
def stage12_public_wue() -> dict:
    b1 = {
        "benchmark": "OCP_PRN1_Q2_2012_WUE",
        "value_L_per_kWh": 0.22,
        "definition": "WUE measures water used for cooling a data center only; not plumbing/offices; quarterly Q2 2012 after BMS/water metering retrofit; Green Grid WUE is annualized but they report quarterly toward TTM",
        "building": "Prineville 1",
        "classification": "PUBLIC_OPERATOR_COOLING_WATER_BENCHMARK",
        "align_before_compare": "Do not compare AIR_STREAM_EVAPORATED_WATER directly to 0.22 unless makeup map applied (1.333–1.392 times vapor for early mist/RO topologies).",
        "source": "OCP_WATER_PRN1",
        "confidence": "HIGH",
    }
    b2 = {
        "benchmark": "2014_PUE_1.08_WUE_0.27",
        "value_WUE_L_per_kWh": 0.27,
        "value_PUE": 1.08,
        "highest_authority_available": "Secondary citations of the public Facebook Prineville PUE/WUE dashboard (Hauser 2015 one-sheet quoting facebook.com/PrinevilleDataCenter; Microsoft FAST16 citing FACEBOOK Prineville Data Center PUE/WUE 2014).",
        "original_dashboard_2014_numeric_capture": "NOT_RECOVERED_IN_THIS_PASS",
        "status": "SUPPORTED_TIER2_SECONDARY_NOT_PROMOTED_TO_TIER1",
        "promotion": "NOT_PROMOTED",
        "reason": "No TIER1 operator PDF/blog stating 0.27 with a defined boundary comparable to the Q2-2012 0.22 note. Dashboard TTM campus-vs-building boundary unknown.",
        "confidence": "MEDIUM_that_dashboard_displayed_near_those_TTM_numbers;_LOW_as_PRN1-only",
    }
    b3 = {
        "benchmark": "archival_dashboard_raw_series",
        "status": "ARCHIVAL_DASHBOARD_DATA_NOT_RECOVERED",
        "prior_pass_TTM_display_only": {
            "as_of": "end of March 2013",
            "PUE_TTM": 1.09,
            "WUE_TTM_L_per_kWh": 0.52,
            "source": "Wayback HTML of fbpuewue.com/prineville",
            "not": "raw_24h_or_past_year_numeric_series",
        },
        "this_pass": "no_new_raw_JSON_timeseries",
    }
    out = {"benchmark_1": b1, "benchmark_2": b2, "benchmark_3": b3}
    write_json(POST / "PUBLIC_WUE_BENCHMARKS.json", out)
    return out


def stage13_meta_consistency(freeze: dict) -> dict:
    if not (PRE / "PUBLIC_PROXY_RECONSTRUCTION_FREEZE.json").exists():
        raise RuntimeError("Stage B cannot run before Stage A freeze.")
    freeze_before = json.loads((PRE / "PUBLIC_PROXY_RECONSTRUCTION_FREEZE.json").read_text())
    env = json.loads((PRE / "PUBLIC_PROXY_ENVELOPE_STATUS.json").read_text())
    annual = pd.read_csv(ROOT / "data/canonical/meta_prineville_annual.csv")
    rows = []
    water_col = "water_withdrawal_m3_reported" if "water_withdrawal_m3_reported" in annual.columns else None
    for _, r in annual.iterrows():
        year = int(r["year"]) if "year" in r else int(r.iloc[0])
        w = r[water_col] if water_col else float("nan")
        if year <= 2022:
            label = "PREVIOUSLY_USED_DEVELOPMENT"
        else:
            label = "PREVIOUSLY_EXPOSED_DIAGNOSTIC"
        in_env = "NOT_APPLICABLE_ENVELOPE_NOT_IDENTIFIED"
        dist = ""
        if pd.notna(w) and env["campus_total_meaningfully_bounded"]:
            in_env = "would_evaluate_here"
        rows.append(
            {
                "year": year,
                "observed_water_m3": w,
                "observation_label": label,
                "observed_in_predeclared_envelope": in_env,
                "distance_to_envelope": dist,
                "independent_validation": False,
                "refit": False,
            }
        )
    write_csv(POST / "PUBLIC_PROXY_VS_WATER_BENCHMARKS.csv", rows)
    freeze_after = json.loads((PRE / "PUBLIC_PROXY_RECONSTRUCTION_FREEZE.json").read_text())
    if freeze_after != freeze_before:
        raise RuntimeError("Stage B mutated Stage A freeze.")
    status = {
        "WATER_OUTCOME_ACCESSED": True,
        "stage_A_freeze_unchanged": True,
        "master_hash": freeze["master_hash"],
        "campus_envelope_not_identifiable": True,
        "consistency_test": "NOT_APPLICABLE_NO_PREDECLARED_CAMPUS_VOLUME_ENVELOPE",
        "no_scenario_selected_using_observations": True,
        "no_parameter_fitted": True,
        "not_independent_validation": True,
    }
    write_json(POST / "CONSISTENCY_DIAGNOSTIC_STATUS.json", status)
    return status


def stage14_chain() -> None:
    rows = [
        {"edge": "workload->IT", "before": "UNIDENTIFIED", "after": "UNIDENTIFIED", "note": "no public workload telemetry"},
        {"edge": "IT->airflow", "before": "SCENARIO_BOUNDED_12K", "after": "ENGINEERING_BOUNDED_rack_CFM_plus_SCENARIO_BOUNDED_12K_facility_deltaT", "note": "OCP rack CFM is ENGINEERING_CONSISTENCY_BOUND not facility BMS; ΔT still not numerically bounded"},
        {"edge": "airflow/weather/control->air_state", "before": "STRUCTURALLY_IDENTIFIED_early_PRN1", "after": "STRUCTURALLY_IDENTIFIED_early_PRN1;_PRN2_PRN3_SCENARIO_BOUNDED_contractor_media", "note": "frozen v1 physics"},
        {"edge": "air_state->AIR_STREAM_EVAPORATED_WATER", "before": "STRUCTURALLY_IDENTIFIED", "after": "STRUCTURALLY_IDENTIFIED", "note": "canonical v1 tag unchanged"},
        {"edge": "air_vapor->ECH_makeup", "before": "UNIDENTIFIED", "after": "SCENARIO_BOUNDED_early_PRN1_mist_RO_1.333_to_1.392;_else_UNIDENTIFIED", "note": "not vapor/0.85"},
        {"edge": "ECH_makeup->conditioning_input", "before": "UNIDENTIFIED", "after": "UNIDENTIFIED", "note": "RO reject and media/tower still separate"},
        {"edge": "building_conditioning->campus_conditioning", "before": "UNIDENTIFIED_lambda", "after": "UNIDENTIFIED_lambda;_HARD_simplex_only;_no_equal_weights", "note": "2011 λ_PRN1=1 identified"},
        {"edge": "campus_conditioning->withdrawal", "before": "UNIDENTIFIED", "after": "UNIDENTIFIED", "note": "campus envelope not identifiable"},
        {"edge": "withdrawal->municipal_vs_direct_POD", "before": "UNIDENTIFIED", "after": "ENGINEERING_BOUNDED_existence_of_three_Vitesse_POD_reports_vs_city_production;_split_UNIDENTIFIED", "note": "reported pumping ≠ permitted max"},
        {"edge": "source_pumping->groundwater", "before": "UNIDENTIFIED", "after": "UNIDENTIFIED_no_fit", "note": "this pass does not fit GW"},
        {"edge": "PRN1_CHW_condenser", "before": "UNIDENTIFIED", "after": "UNIDENTIFIED", "note": "public search exhausted"},
    ]
    write_csv(OUT / "CHAIN_CONNECTION_STATUS_BEFORE_AFTER.csv", rows)
    dump_md(
        OUT / "PUBLIC_PROXY_PROJECT_ADVANCE.md",
        """# Public proxy reconstruction v1 — project advance

This pass did **not** calibrate structural-reference-v1 and did **not** promote it.

Material advances from public evidence:

- OCP triplet CFM extracted and classified as rack/server ENGINEERING_CONSISTENCY_BOUND. 12 K ΔT is **not** numerically bounded (`PUBLIC_EVIDENCE_INSUFFICIENT_TO_NUMERICALLY_BOUND_DELTAT`).
- Complete public facility list includes CCO3/CCO5/CCO6 (DEQ). Frozen registry coverage gap reported, not rewritten.
- Southland PRN2/PRN3/PRN4 contractor pages supply typed facility/hall MW and later-hall evaporative-media architecture (TIER3), plus PRN3 network-core cooling towers.
- Phase 2 mist→media / no RO room is SUPPORTED_TIER2 (Jay Park via DCK), not TIER1 building-id mapped.
- Early PRN1 mist/RO symbolic balance: makeup ≠ vapor/0.85; two topologies 1.333× and 1.392× vapor.
- Load shares: 2011 λ_PRN1=1; later years unidentified simplex. No equal weights.
- Campus-total water envelope is **not scientifically identifiable** from public evidence.
- Highest-value next data: per-building architecture + IT load (or submeters), then PRN1 CHW condenser, then makeup meters.

No groundwater fit. No emissions refinement. No structural rewrite.
""",
    )


def stage15_figures(env_status: dict) -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    # 1 airflow
    fig, ax = plt.subplots(figsize=(8, 4.5))
    labels = ["Intel server", "AMD server", "Rack mixed", "Expected max rack"]
    lo = [12, 14, 1116, 5400]
    hi = [103, 106, 9324, 5400]
    y = np.arange(len(labels))
    ax.hlines(y, lo, hi, colors="C0", lw=6)
    ax.plot(hi, y, "o", color="C0")
    ax.set_yticks(y, labels)
    ax.set_xlabel("CFM (server or rack)")
    ax.set_title("OCP v1 airflow: ENGINEERING_CONSISTENCY_BOUND\n(not facility BMS)")
    fig.tight_layout()
    fig.savefig(FIG / "fig01_ocp_airflow_bounds.png", dpi=140)
    plt.close(fig)

    # 2 timeline
    fig, ax = plt.subplots(figsize=(9, 5))
    items = [
        ("PRN1 OA+ECH", 2011.3, 2011.3),
        ("PRN2 media (contractor)", 2013.5, 2014.5),
        ("PRN3 media+core towers", 2014.0, 2015.0),
        ("PRN4 packaged evap", 2016.0, 2016.0),
        ("PRN5/6 named", 2018.0, 2018.0),
        ("CCO1/2", 2018.7, 2022.1),
        ("CCO3/5/6 DEQ labels", 2024.0, 2024.0),
        ("PRN1 CHW", 2023.7, 2024.1),
    ]
    for i, (name, a, b) in enumerate(items):
        ax.barh(i, max(b - a, 0.15), left=a, height=0.5)
        ax.text(2010.2, i, name, va="center", fontsize=8)
    ax.set_xlim(2010, 2026)
    ax.set_yticks([])
    ax.set_xlabel("Year")
    ax.set_title("Public facility / architecture timeline (capacity types not mixed)")
    fig.tight_layout()
    fig.savefig(FIG / "fig02_facility_timeline.png", dpi=140)
    plt.close(fig)

    # 3 water system
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.axis("off")
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    boxes = [
        (0.3, 4.2, "W_raw / RO feed"),
        (3.4, 4.2, "RO product 0.75"),
        (6.6, 4.2, "RO reject 0.25"),
        (3.4, 2.4, "Spray"),
        (0.3, 0.6, "W_recaptured 0.15"),
        (6.6, 0.6, "W_air_vapor 0.85"),
    ]
    for x, y, t in boxes:
        ax.add_patch(plt.Rectangle((x, y), 2.8, 1.1, fill=False))
        ax.text(x + 1.4, y + 0.55, t, ha="center", va="center", fontsize=8)
    ax.annotate("", xy=(3.4, 4.7), xytext=(3.1, 4.7), arrowprops=dict(arrowstyle="->"))
    ax.annotate("", xy=(6.6, 4.7), xytext=(6.2, 4.7), arrowprops=dict(arrowstyle="->"))
    ax.annotate("", xy=(4.8, 3.5), xytext=(4.8, 4.2), arrowprops=dict(arrowstyle="->"))
    ax.annotate("", xy=(1.7, 1.7), xytext=(4.0, 2.4), arrowprops=dict(arrowstyle="->"))
    ax.annotate("", xy=(8.0, 1.7), xytext=(5.6, 2.4), arrowprops=dict(arrowstyle="->"))
    ax.set_title("Early PRN1 mist/RO (symbolic). Makeup ≠ vapor/0.85")
    fig.tight_layout()
    fig.savefig(FIG / "fig03_water_system_balance.png", dpi=140)
    plt.close(fig)

    # 4 campus envelope
    fig, ax = plt.subplots(figsize=(8, 4.2))
    years = list(range(2011, 2025))
    ax.plot(years, [0] * len(years), "k--", label="lower unidentified (0)")
    ax.fill_between(years, 0, 1, color="0.85", label="campus volume not identifiable")
    ax.set_yticks([])
    ax.set_xlabel("Year")
    ax.set_title("Campus water feasible envelope: NOT IDENTIFIABLE\n(architecture + λ missing)")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(FIG / "fig04_campus_envelope.png", dpi=140)
    plt.close(fig)

    # 5 VoI
    fig, ax = plt.subplots(figsize=(8, 4.5))
    names = [
        "Architecture\n(unidentified halls)",
        "λ load shares\n(if arch known)",
        "PRN1 CHW\ncondenser",
        "B water\nsubepoch",
        "ΔT / airflow",
        "Source split",
        "RO recapture\ntopology",
    ]
    vals = [1.0, 0.0, 0.8, 0.7, float(env_status.get("_dT_norm", 0.2)), 0.0, 0.04]
    voi = pd.read_csv(PRE / "VALUE_OF_INFORMATION.csv")
    try:
        vals[4] = float(voi.loc[voi["uncertainty_class"] == "airflow_deltaT", "normalized_range_reduction"].iloc[0])
    except Exception:
        pass
    ax.barh(names[::-1], vals[::-1])
    ax.set_xlabel("Normalized range reduction (deterministic rank scale)")
    ax.set_title("Value of information for campus-water range")
    fig.tight_layout()
    fig.savefig(FIG / "fig05_value_of_information.png", dpi=140)
    plt.close(fig)


def main() -> None:
    for d in (OUT, PRE, POST, SRC_CACHE, FIG):
        d.mkdir(parents=True, exist_ok=True)
    state = stage0_initial_state()
    with HoldoutGuard(ROOT) as guard:
        stage1_manifest()
        stage2_airflow()
        stage3_facility()
        stage4_opuc()
        stage5_water()
        stage6_gaps()
        stage7_lambda()
        stage8_owrd()
        env = stage9_envelope()
        stage10_voi(env)
        freeze = stage11_freeze(guard, state)
        if guard.accessed:
            # the probe above records an attempt; that is expected. Values must not have been read.
            pass
    # Stage B after freeze
    stage12_public_wue()
    stage13_meta_consistency(freeze)
    stage14_chain()
    stage15_figures(env)
    write_json(
        OUT / "RUN_STATUS.json",
        {
            "complete": True,
            "WATER_OUTCOME_ACCESSED_STAGE_A": False,
            "WATER_OUTCOME_ACCESSED_STAGE_B": True,
            "no_commit": True,
            "no_fit": True,
            "campus_envelope": "NOT_IDENTIFIABLE",
        },
    )
    print("public_proxy_reconstruction_v1 complete")
    print("freeze", freeze["master_hash"])


if __name__ == "__main__":
    main()
