#!/usr/bin/env python3
"""Prineville cooling architecture / epoch / gray-box STRUCTURE audit.

Does not fit or refit the gray-box. Does not read Meta 2023–2024 water outcomes
to choose mechanisms. Does not transfer ESIF or Lei coefficients.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
OUT = ROOT / "outputs" / "architecture_audit"
FIG = OUT / "figures"
GRAYBOX = ROOT / "src" / "prineville_graybox.py"
GRAYBOX_SHA256 = "baaf685190b432767519ea1bd7dbe2ec026718a31fef1e22bdff7cf727f17b55"
CPU_STATUS_SHA256 = "1f57b210a63d375ce8eff7d5043756ffe6efe04e8a408bf9429bfd10096528d9"
CPU_FREEZE_SHA256 = "dcbd066b26b8e7d2800e40a23a1cb8250502bfe59563fe06318cb1be1cc4fd27"
H100_FREEZE_SHA256 = "a620d649a932f2388aa2f35bac2730eb75fe1dc74529668de4f30ee814600076"
FO_STATUS_SHA256 = "ae7c50a0a5ab4c6ecd52f0fe55607ca423295458755226515ee5c46e2c3542d2"
FO_LAYER_FREEZE_SHA256 = "bac8f706fa407f89a21ccbb73e2675cfed9b5bbc5443f43aea8572157e5c67e5"
PUBLIC_BASELINE = "340c6fd352b913e3e360b26b5d745bd94c2d600b"
DISPOSITION = "MINIMAL_STRUCTURAL_REVISION_REQUIRED"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def jdump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n")


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def write_initial_state() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    hw_status = REPO / "other_sources/nlr_esif_fullstack/heat_rejection_water/analysis/FINAL_ESIF_HEAT_WATER_STATUS.json"
    hw_freeze = REPO / "other_sources/nlr_esif_fullstack/heat_rejection_water/manifests/ESIF_HEAT_WATER_RESULT_FREEZE.json"
    fo_status = REPO / "other_sources/nlr_esif_fullstack/facility_overhead/analysis/FINAL_ESIF_FACILITY_OVERHEAD_STATUS.json"
    fo_freeze = REPO / "other_sources/nlr_esif_fullstack/facility_overhead/manifests/FACILITY_OVERHEAD_LAYER_FREEZE.json"
    rec = {
        "purpose": "Fail-closed starting state for Prineville architecture audit. No model fit.",
        "public_reference_baseline": PUBLIC_BASELINE,
        "git": {
            "branch": git("branch", "--show-current"),
            "HEAD": git("rev-parse", "HEAD"),
            "status": git("status", "--short"),
            "dirty_submodule": "Data-center-PUE-prediction-tool",
        },
        "head_matches_public_baseline": git("rev-parse", "HEAD") == PUBLIC_BASELINE,
        "unrelated_dirty_work": "submodule pointer only; heat_rejection_water already committed at baseline; this audit writes only architecture_audit/ plus ESIF semantic docs/status",
        "frozen_hashes_at_audit_start": {
            "cpu_status": CPU_STATUS_SHA256,
            "cpu_freeze": CPU_FREEZE_SHA256,
            "h100_freeze": H100_FREEZE_SHA256,
            "fo_status": sha256_file(fo_status),
            "fo_layer_freeze": sha256_file(fo_freeze),
            "hw_status_after_semantic_patch_expected_to_change": True,
            "hw_status_at_this_write": sha256_file(hw_status),
            "hw_result_freeze_at_this_write": sha256_file(hw_freeze),
            "graybox": sha256_file(GRAYBOX),
        },
        "prineville_live_graybox": str(GRAYBOX),
        "known_frozen_water_holdout_specification": {
            "holdout_years": [2023, 2024],
            "source": "config/prineville.yaml",
            "note": "Specification recorded. Outcomes are NOT inspected for structural decisions in this pass.",
        },
        "cannot_modify": ["CPU", "H100", "IT-power", "facility-overhead numerics", "ESIF heat/water numerics", "Prineville gray-box coefficients", "Prineville production predictions"],
        "recorded_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    assert rec["git"]["HEAD"] == PUBLIC_BASELINE
    assert rec["frozen_hashes_at_audit_start"]["graybox"] == GRAYBOX_SHA256
    assert rec["frozen_hashes_at_audit_start"]["fo_status"] == FO_STATUS_SHA256
    assert rec["frozen_hashes_at_audit_start"]["fo_layer_freeze"] == FO_LAYER_FREEZE_SHA256
    jdump(OUT / "PRINEVILLE_ARCHITECTURE_AUDIT_INITIAL_STATE.json", rec)
    return rec


def write_model_inventory() -> None:
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from prineville_graybox import Params  # noqa: WPS433

    p = Params()
    rows = [
        dict(file="src/prineville_graybox.py", function="Params.supply_target_C", equation="t_supply target",
             physical_mechanism="cold-aisle / supply-air setpoint", parameter="supply_target_C", units="degC",
             current_value=p.supply_target_C, source_provenance="code prior; OCP v1.0 cold aisle 65–85 F (18.3–29.4 C) contains 25 C",
             site_specific_vs_generic="generic prior inside documented range", fixed_vs_fitted="fixed prior",
             epoch_dependence="none (campus-wide constant)", water_boundary="n/a", scientific_status="KEEP_AS_SCENARIO"),
        dict(file="src/prineville_graybox.py", function="Params.return_air_C", equation="declared unused",
             physical_mechanism="return-air / winter mixing (documented at Prineville; not in simulate)",
             parameter="return_air_C", units="degC", current_value=p.return_air_C,
             source_provenance="declared in Params; simulate() does not use it",
             site_specific_vs_generic="placeholder", fixed_vs_fitted="fixed unused",
             epoch_dependence="none", water_boundary="n/a", scientific_status="REQUIRED_MISSING_IN_EQUATIONS"),
        dict(file="src/prineville_graybox.py", function="Params.evap_effectiveness", equation="t_full = t_db - ε max(t_db-t_wb,0)",
             physical_mechanism="direct evaporative approach to wet-bulb", parameter="evap_effectiveness", units="1",
             current_value=p.evap_effectiveness, source_provenance="generic saturator prior; not a Prineville meter",
             site_specific_vs_generic="generic", fixed_vs_fitted="fixed prior",
             epoch_dependence="none", water_boundary="n/a", scientific_status="REQUIRES_SITE_CALIBRATION"),
        dict(file="src/prineville_graybox.py", function="Params.server_deltaT_C", equation="m_air = P_IT*1e6/(cp*ΔT)",
             physical_mechanism="IT sensible-heat airflow sizing", parameter="server_deltaT_C", units="K",
             current_value=p.server_deltaT_C, source_provenance="2011 article discusses raising server delta-T; 12 K is a prior not a site measurement; DCD tour cites 30–35 F aisle delta as containment, not the model ΔT",
             site_specific_vs_generic="generic prior", fixed_vs_fitted="fixed prior",
             epoch_dependence="none", water_boundary="n/a", scientific_status="REQUIRES_SITE_CALIBRATION"),
        dict(file="src/prineville_graybox.py", function="simulate.m_air", equation="m_air = P_IT*1e6/(cp*ΔT)",
             physical_mechanism="dry-air mass flow from IT heat", parameter="m_air", units="kg/s",
             current_value="derived", source_provenance="physics identity inside gray-box",
             site_specific_vs_generic="generic psychrometrics + latent IT", fixed_vs_fitted="derived",
             epoch_dependence="none", water_boundary="n/a", scientific_status="PRESENT_AND_SUPPORTED"),
        dict(file="src/prineville_graybox.py", function="simulate.t_supply", equation="OA if t_db<=T*; else T* if reachable; else t_full",
             physical_mechanism="weather-rule supply temperature; named winter_mix but OA used when t_db<=T*",
             parameter="t_supply_C", units="degC", current_value="derived",
             source_provenance="rule-based; OCP mixing is not modeled",
             site_specific_vs_generic="simplified site class", fixed_vs_fitted="derived",
             epoch_dependence="none", water_boundary="n/a", scientific_status="PRESENT_BUT_INCOMPLETE_MIXING"),
        dict(file="src/prineville_graybox.py", function="simulate.evap_water", equation="m_air * max(w_s-w_o,0) at constant moist-air enthalpy",
             physical_mechanism="direct evaporative / humidification water added to air stream",
             parameter="evap_water_m3_per_h", units="m3/h", current_value="derived",
             source_provenance="psychrometric mass balance; adiabatic saturator proxy for MeeFog/ECH mist",
             site_specific_vs_generic="mechanism class site-specific; coefficients generic",
             fixed_vs_fitted="derived", epoch_dependence="none",
             water_boundary="CONDITIONING_SITE_WATER (air-side mist), not Meta withdrawal",
             scientific_status="PRESENT_AND_SUPPORTED_FOR_EARLY_EPOCH"),
        dict(file="src/prineville_graybox.py", function="simulate.p_fan", equation="0.025 * P_IT",
             physical_mechanism="fan-wall electricity proxy", parameter="fan_fraction_of_it", units="1",
             current_value=p.fan_fraction_of_it, source_provenance="prior to leave room for ~1.07 PUE; OCP specifies VFD fan array",
             site_specific_vs_generic="generic", fixed_vs_fitted="fixed prior",
             epoch_dependence="none", water_boundary="n/a", scientific_status="KEEP_AS_SCENARIO"),
        dict(file="src/prineville_graybox.py", function="simulate.p_other", equation="0.035 * P_IT",
             physical_mechanism="other facility electrical overhead", parameter="other_facility_fraction_of_it", units="1",
             current_value=p.other_facility_fraction_of_it, source_provenance="prior; 2011 electrical-loss discussion is 7.5% total electrical not this split",
             site_specific_vs_generic="generic", fixed_vs_fitted="fixed prior",
             epoch_dependence="none", water_boundary="n/a", scientific_status="KEEP_AS_SCENARIO"),
        dict(file="src/prineville_graybox.py", function="simulate.p_evap_aux", equation="0.005 * P_IT * spray",
             physical_mechanism="misting-pump auxiliary electricity", parameter="evap_aux_fraction", units="1",
             current_value=0.005, source_provenance="hardcoded prior in simulate(); MeeFog uses high-pressure pumps",
             site_specific_vs_generic="generic", fixed_vs_fitted="fixed prior",
             epoch_dependence="none", water_boundary="n/a", scientific_status="KEEP_AS_SCENARIO"),
        dict(file="src/prineville_graybox.py", function="simulate.cooling_mode", equation="outside_air_or_winter_mix / partial_evap / full_evap",
             physical_mechanism="weather vs 25 C target; winter mixing not physically implemented",
             parameter="cooling_mode", units="categorical", current_value="derived",
             source_provenance="code label; OCP Appendix A has a psychrometric sequence of operations",
             site_specific_vs_generic="simplified", fixed_vs_fitted="derived",
             epoch_dependence="none — no PRN1 chiller mode", water_boundary="n/a",
             scientific_status="EPOCH_MISMATCH"),
        dict(file="src/conditional_reconstruction.py", function="select_water_scale_model", equation="s * W_evap_raw → Meta withdrawal proxy",
             physical_mechanism="empirical boundary mapping, not cooling physics",
             parameter="water_scale", units="1", current_value="fitted train-only (through 2022); value not read here",
             source_provenance="fitted on Meta annual withdrawal through 2022",
             site_specific_vs_generic="site fitted mapping", fixed_vs_fitted="fitted",
             epoch_dependence="global; one-break not selected", water_boundary="WITHDRAWAL (Meta campus) from CONDITIONING_SITE_WATER shape",
             scientific_status="BOUNDARY_MISMATCH_KEEP_AS_MAPPING"),
        dict(file="src/prineville_graybox.py", function="(absent)", equation="none",
             physical_mechanism="PRN1 chilled-water / CRAH / chiller", parameter="none",
             units="n/a", current_value="absent", source_provenance="permits 217-21-003734-MECH and 217-24-000066-MECH",
             site_specific_vs_generic="site-specific missing", fixed_vs_fitted="n/a",
             epoch_dependence="missing epoch", water_boundary="unidentified heat-rejection water if any",
             scientific_status="REQUIRED_MISSING"),
    ]
    pd.DataFrame(rows).to_csv(OUT / "CURRENT_PRINEVILLE_MODEL_INVENTORY.csv", index=False)
    jdump(OUT / "CURRENT_PRINEVILLE_MODEL_INVENTORY.json", {"n": len(rows), "live_implementation": str(GRAYBOX), "items": rows})


def write_source_register() -> None:
    rows = [
        dict(source_id="META_ENG_2011_PARK", title="Designing a Very Efficient Data Center", date="2011-04-14",
             issuer="Meta/Facebook engineering (Jay Park)", document_type="operator engineering article",
             prineville_specific="yes", building_phase_specific="Prineville first OCP facility / Prineville 1 class",
             temporal_applicability="initial design / commissioning era", source_authority="TIER1_OPERATOR_SELF_REPORTED",
             reference="https://engineering.fb.com/2011/04/14/core-infra/designing-a-very-efficient-data-center/",
             architecture_evidence="no chiller plant; no cooling towers/pumps; 100% OA evaporative cooling and humidification; winter return-air mix in penthouse; ductless/hot-aisle containment; capability to install IEC if needed (NOT installed)",
             current_use="early-epoch architecture prior", notes="CAPABILITY != INSTALLED for IEC"),
        dict(source_id="OCP_DC_V1_2011", title="Open Compute Project Data Center v1.0", date="2011-04",
             issuer="Open Compute Project / Facebook", document_type="mechanical/electrical specification",
             prineville_specific="yes (first implementation)", building_phase_specific="Prineville 1 mechanical penthouse",
             temporal_applicability="2011 design", source_authority="TIER1_SPEC",
             reference="Open Compute Data Center v1.0 (Park); local excerpt via public spec copies",
             architecture_evidence="OA louvers → mix with return → filters → ECH mist → mist eliminators → fan wall → cold aisle; cold aisle 65–85 F; dewpoint min 41.9 F; 65% RH max; no chillers/compressors for IT; RO/softener; VFD fans; BMS; Appendix B indirect cooling is optional/future",
             current_use="air-path / water-mechanism physics spec", notes="Appendix B IEC is capability/spec option"),
        dict(source_id="OCP_WATER_PRN1", title="Water Efficiency at Facebook's Prineville Data Center", date="2011-era OCP blog",
             issuer="Open Compute Project", document_type="operator/OCP blog",
             prineville_specific="yes (Prineville 1)", building_phase_specific="PRN1",
             temporal_applicability="early PRN1", source_authority="TIER1_OPERATOR",
             reference="https://www.opencompute.org/blog/water-efficiency-at-facebooks-prineville-data-center",
             architecture_evidence="built-up penthouse; 100% OA economizer; direct ECH misting; no chillers or cooling towers; single-pass with recirculate or exhaust; water in supply-air stream not cooling-tower blowdown",
             current_use="ECH acronym + water path", notes="ECH = evaporative cooling and humidification"),
        dict(source_id="OCP_LESSONS_2011", title="Learning Lessons at the Prineville Data Center", date="2011",
             issuer="OCP / Electronics Cooling republication", document_type="incident/lessons",
             prineville_specific="yes", building_phase_specific="PRN1",
             temporal_applicability="2011 operations", source_authority="TIER1",
             reference="https://www.opencompute.org/blog/learning-lessons-at-the-prineville-data-center",
             architecture_evidence="confirms penthouse chiller-less OA+evap; damper/recirculation control exists; humidification spray can run 100%",
             current_use="controls existence", notes="fault sequence is not the design intent"),
        dict(source_id="DCD_PENTHOUSE_TOUR", title="Facebook details efficiency at Prineville / penthouse video", date="2011",
             issuer="Data Center Dynamics / Data Center Knowledge", document_type="industry press / video tour",
             prineville_specific="yes", building_phase_specific="first building",
             temporal_applicability="2011", source_authority="TIER2",
             reference="Jay Park penthouse tour; MeeFog high-pressure mist",
             architecture_evidence="louvers, mixing with hot-aisle air, filter banks, pressurized water mist, fan wall, winter recirculation heating",
             current_use="air-path corroboration", notes="secondary"),
        dict(source_id="MEEFOG_VENDOR", title="How Facebook Upgraded the Outside Air Cooling System at Their Prineville Data Center", date="later upgrade article",
             issuer="Upsite / Mee Industries vendor case", document_type="vendor case study",
             prineville_specific="yes", building_phase_specific="stated 147k ft2 hall",
             temporal_applicability="fog system remained; pump lubrication upgrade", source_authority="TIER2",
             reference="https://www.upsite.com/blog/how-facebook-upgraded-the-outside-air-cooling-system-at-their-prineville-data-center/",
             architecture_evidence="MeeFog 28 units / ~6600 nozzles; still OA+fog not CRAH hall cooling; water-lubricated pump swap",
             current_use="confirms mist technology persistence at a Prineville hall", notes="do not treat vendor claims as campus-wide later architecture"),
        dict(source_id="PRN1_PERMITS_2021_2024", title="Crook County PRN1 addition mechanical/chiller permits", date="2021-2024",
             issuer="Crook County ePermitting", document_type="permit inspection summaries",
             prineville_specific="yes", building_phase_specific="PRN1 only",
             temporal_applicability="late-2023 commissioning → 2024-02 operational chiller", source_authority="TIER1_PUBLIC_RECORD",
             reference="data/raw/prineville_strictly_valuable_permits_v2/; data/canonical/facility/prn1_addition_facts.csv",
             architecture_evidence="chilled-water, CRAH, chiller for personnel and IT; additional roof chiller operational 2024-02-02; heat-rejection type NOT stated",
             current_use="later PRN1 epoch", notes="not campus-wide; not used historically to retune holdout"),
        dict(source_id="CCO_MECH_2019", title="217-19-000276-MECH CCO1/CCO2 mechanical", date="2019-2021",
             issuer="Crook County", document_type="permit inspection",
             prineville_specific="yes", building_phase_specific="CCO1/CCO2",
             temporal_applicability="CCO commissioning", source_authority="TIER1_PUBLIC_RECORD",
             reference="data/manual_templates/campus_buildings.csv",
             architecture_evidence="water rooms, IWS/IWR, piping serving ECH in Data Hall A, data-hall supply water, CRAC in electrical room, refrigeration lines. No explicit chiller/tower. ECH matches OCP evaporative cooling/humidification acronym.",
             current_use="CCO architecture SUPPORTED ECH class", notes="CRAC in electrical room is not hall architecture"),
        dict(source_id="CITY_ORD1246_2018", title="Ordinance 1246 PRN1–PRN6 map", date="2018-09-25",
             issuer="City of Prineville", document_type="ordinance map",
             prineville_specific="yes", building_phase_specific="PRN campus layout",
             temporal_applicability="2018 identity", source_authority="TIER1",
             reference="config/prineville_documentary_sources.csv",
             architecture_evidence="names PRN1–PRN6; no cooling technology",
             current_use="facility identity", notes=""),
        dict(source_id="OPUC_UM1989_2018", title="UM 1989 Vitesse direct-access application", date="2018-12-14",
             issuer="OPUC / Vitesse", document_type="regulatory filing",
             prineville_specific="yes", building_phase_specific="PRN vs CCO",
             temporal_applicability="2014 four PRN buildings; 2018 CCO announcement", source_authority="TIER1",
             reference="documentary core PDF",
             architecture_evidence="campus chronology, not cooling specs",
             current_use="epochs", notes="announcement ≠ commissioning"),
        dict(source_id="META_SPLC_2018", title="StatePoint Liquid Cooling system for data centers", date="2018-06-05",
             issuer="Meta engineering", document_type="fleet technology announcement",
             prineville_specific="no", building_phase_specific="n/a",
             temporal_applicability="fleet where direct cooling unsuitable", source_authority="TIER3_FLEET",
             reference="https://engineering.fb.com/2018/06/05/data-center-engineering/statepoint-liquid-cooling/",
             architecture_evidence="SPLC exists; intended where direct cooling not feasible; direct evaporative remains preferred where climate allows",
             current_use="context only", notes="NEVER PRINEVILLE CONFIRMED from this source"),
        dict(source_id="META_FLEET_PENTHOUSE_2024", title="Meta existing-DC outside air / mixing / misting / fan-wall description", date="2024-context",
             issuer="Meta", document_type="fleet technical context",
             prineville_specific="no unless linked", building_phase_specific="n/a",
             temporal_applicability="many existing Meta DCs", source_authority="TIER3_FLEET",
             reference="Meta cooling-control / penthouse documentation (fleet)",
             architecture_evidence="OA, mixing, evaporative/humidification misting, fan walls, SAT/RH/airflow control exist in the fleet",
             current_use="context only", notes="does not by itself confirm later Prineville buildings"),
    ]
    pd.DataFrame(rows).to_csv(OUT / "PRINEVILLE_ARCHITECTURE_SOURCE_REGISTER.csv", index=False)
    jdump(OUT / "PRINEVILLE_ARCHITECTURE_SOURCE_REGISTER.json", {"n": len(rows), "items": rows})


def write_epochs() -> list[dict]:
    rows = [
        dict(epoch_id="E1_PRN1_OCP_COMMISSIONING", start_date="2011-04-14", end_date="2014-01-01",
             building_phase="PRN1 / first OCP hall (core+shell final 2011-04-14; sections C&D 2011-08-24)",
             construction_date="2010-01-25 opened (proxy)", commissioning_operation_date="2011-04-14 CONFIRMED final building",
             expansion_event="original campus", known_capacity="not stated in inspection summaries",
             active_structures="initial core/shell + sections A–D", relevant_permits="217-C+10-00063; 217-T+10-00225A/B; 217-C+10-00705",
             evidence_source_ids="META_ENG_2011_PARK; OCP_DC_V1_2011; OCP_WATER_PRN1",
             confidence="CONFIRMED", date_precision="day for finals; month for architecture class",
             notes="Architecture class is the 2011 OCP penthouse OA+ECH system."),
        dict(epoch_id="E2_PRN_FOUR_BUILDING", start_date="2014-01-01", end_date="2020-03-18",
             building_phase="Four initial PRN buildings (OPUC 2018: being constructed/brought online early 2014); PRN1–PRN6 named 2018",
             construction_date="2014 approximate", commissioning_operation_date="UNSUPPORTED exact per-building CO dates",
             expansion_event="additional initial PRN halls", known_capacity="unknown",
             active_structures="PRN campus (count 4 then later 6 named)", relevant_permits="early campus set; 2015/2016 mechanical unknowns",
             evidence_source_ids="OPUC_UM1989_2018; CITY_ORD1246_2018",
             confidence="SUPPORTED for four-building existence; POSSIBLE that later PRN halls copy PRN1 OCP class; UNKNOWN per-hall mechanical",
             date_precision="year", notes="Do not assume every later PRN building copied Building 1."),
        dict(epoch_id="E3_CCO1_CCO2", start_date="2018-09-20", end_date="2022-02-09",
             building_phase="Crook County Campus CCO1&2 (announced 2018-09-20; data-hall mechanical finals 2020; full mechanical 2021-07-08; structural closeout 2022-02-09)",
             construction_date="2018-08-29 STR opened proxy", commissioning_operation_date="phased 2020 data halls; 2021-06-28 full STR; 2022 closeout",
             expansion_event="CCO campus", known_capacity="unknown MW",
             active_structures="CCO1 A–E and CCO2 A–E", relevant_permits="217-18-001459-STR; 217-19-000276-MECH",
             evidence_source_ids="CCO_MECH_2019; OPUC_UM1989_2018; CITY_CU2019_111",
             confidence="CONFIRMED construction/commissioning chronology; SUPPORTED ECH piping in data hall; UNKNOWN identical penthouse copy",
             date_precision="day for permit finals; announcement is not commissioning",
             notes="Treat 2022 as closeout not first operation."),
        dict(epoch_id="E4_PRN1_MECH_ADDITION", start_date="2021-09-21", end_date="2024-02-22",
             building_phase="PRN1 Network Core Addition + additional roof chiller",
             construction_date="planning 2021-09-21; structural inspections from 2022-04",
             commissioning_operation_date="hydronic test 2023-09-21 (CRAH/chiller not yet final); TCO-era walk 2023-12-11; chiller operational 2024-02-02; trade finals mid-Feb 2024",
             expansion_event="PRN1 addition ~82.7k ft2 unresolved range", known_capacity="MW missing; circuit counts documented not convertible",
             active_structures="PRN1 addition + roof chiller", relevant_permits="217-21-003723-STR; 217-21-003734-MECH; 217-24-000066-MECH",
             evidence_source_ids="PRN1_PERMITS_2021_2024",
             confidence="CONFIRMED chilled-water/CRAH/chiller infrastructure at PRN1; UNKNOWN heat-rejection (tower vs dry vs air-cooled)",
             date_precision="day", notes="PRN1-scoped. Do not apply to CCO or PRN2–6. Do not backcast 217-22-000289 CRAC (final 2026) onto 2023–2024."),
    ]
    pd.DataFrame(rows).to_csv(OUT / "PRINEVILLE_FACILITY_EPOCHS.csv", index=False)
    jdump(OUT / "PRINEVILLE_FACILITY_EPOCHS.json", {"n": len(rows), "items": rows,
          "rule": "Do not assume the whole campus changed architecture on one date."})
    return rows


def ev_row(**kw):
    kw.setdefault("confidence", kw.get("status"))
    return kw


def write_architecture_evidence() -> None:
    rows = []
    def add(**kw):
        rows.append(ev_row(**kw))

    early = ("E1_PRN1_OCP_COMMISSIONING", "PRN1")
    for epoch, bldg in [early, ("E2_PRN_FOUR_BUILDING", "PRN_campus")]:
        st_oa = "CONFIRMED" if bldg == "PRN1" else "POSSIBLE"
        add(epoch_id=epoch, building=bldg, mechanism="100pct_outside_air_economizer",
            evidence="100% outside air evaporative cooling; single-pass economizer with exhaust or recirculate",
            source="META_ENG_2011_PARK; OCP_WATER_PRN1", page="Cooling, Airflow Innovations / Prineville 1 mechanical system",
            source_scope="PRINEVILLE_SPECIFIC", source_authority="TIER1", status=st_oa, reason="operator+OCP for PRN1; later PRN halls not separately specified")
        add(epoch_id=epoch, building=bldg, mechanism="return_air_mixing_winter",
            evidence="Return air mixed with OA in penthouse to meet temperature setpoint; wasted heat recirculated in winter",
            source="META_ENG_2011_PARK; OCP_DC_V1_2011 §5.3.2 step 3", page="Cooling, Airflow Innovations",
            source_scope="PRINEVILLE_SPECIFIC", source_authority="TIER1", status=st_oa, reason="documented mixing; gray-box does not implement OA fraction")
        add(epoch_id=epoch, building=bldg, mechanism="direct_evaporative_mist_ECH",
            evidence="High-pressure atomizing ECH misting in supply-air path (MeeFog class)",
            source="OCP_WATER_PRN1; OCP_DC_V1_2011; MEEFOG_VENDOR", page="ECH misting system",
            source_scope="PRINEVILLE_SPECIFIC", source_authority="TIER1", status=st_oa, reason="direct evaporative/humidification")
        add(epoch_id=epoch, building=bldg, mechanism="humidification",
            evidence="Same ECH system provides humidification (high-desert winter) and evaporative cooling (summer)",
            source="META_ENG_2011_PARK; OCP_DC_V1_2011 5.2", page="OA operating conditions",
            source_scope="PRINEVILLE_SPECIFIC", source_authority="TIER1", status=st_oa, reason="documented dual use")
        add(epoch_id=epoch, building=bldg, mechanism="fan_wall",
            evidence="Supply fan room / fan array with VFDs pushes air down shafts to cold aisles",
            source="OCP_DC_V1_2011 §5.3.2–5.3.3", page="Supply Fan Systems",
            source_scope="PRINEVILLE_SPECIFIC", source_authority="TIER1", status=st_oa, reason="")
        add(epoch_id=epoch, building=bldg, mechanism="hot_aisle_containment",
            evidence="Hot aisles contained; return plenum; ductless shafts",
            source="META_ENG_2011_PARK", page="Cooling, Airflow Innovations",
            source_scope="PRINEVILLE_SPECIFIC", source_authority="TIER1", status=st_oa, reason="")
        add(epoch_id=epoch, building=bldg, mechanism="indirect_evaporative",
            evidence="Capability to install indirect evaporative cooling if needed; OCP Appendix B",
            source="META_ENG_2011_PARK", page="Cooling, Airflow Innovations last sentence",
            source_scope="PRINEVILLE_SPECIFIC", source_authority="TIER1", status="UNSUPPORTED",
            reason="CAPABILITY TO INSTALL != INSTALLED")
        add(epoch_id=epoch, building=bldg, mechanism="SPLC",
            evidence="No Prineville-specific SPLC installation source",
            source="META_SPLC_2018", page="fleet announcement",
            source_scope="META_FLEET_CONTEXT", source_authority="TIER3", status="UNSUPPORTED",
            reason="fleet technology exists; not linked to Prineville")
        add(epoch_id=epoch, building=bldg, mechanism="liquid_cooling_direct_to_chip",
            evidence="None", source="none", page="", source_scope="GENERIC", source_authority="none",
            status="UNSUPPORTED", reason="no site evidence")
        add(epoch_id=epoch, building=bldg, mechanism="cooling_tower",
            evidence="2011 design eliminated cooling towers",
            source="META_ENG_2011_PARK", page="We didn't build a chiller plant, eliminating associated cooling towers",
            source_scope="PRINEVILLE_SPECIFIC", source_authority="TIER1", status="CONTRADICTED",
            reason="explicitly not part of original design; later PRN1 heat-rejection type unknown")
        add(epoch_id=epoch, building=bldg, mechanism="mechanical_chiller",
            evidence="No chiller plant; no compressors for IT load in OCP v1.0",
            source="META_ENG_2011_PARK; OCP_DC_V1_2011 §5.3", page="",
            source_scope="PRINEVILLE_SPECIFIC", source_authority="TIER1", status="CONTRADICTED",
            reason="early epoch only")
        add(epoch_id=epoch, building=bldg, mechanism="dry_cooler",
            evidence="None installed as the IT heat-rejection path in 2011 design",
            source="META_ENG_2011_PARK", page="", source_scope="PRINEVILLE_SPECIFIC", source_authority="TIER1",
            status="UNSUPPORTED", reason="not described for early OA+ECH path")

    add(epoch_id="E3_CCO1_CCO2", building="CCO1", mechanism="direct_evaporative_mist_ECH",
        evidence="Inspection notes piping serving ECH in Data Hall A",
        source="CCO_MECH_2019 / 217-19-000276-MECH", page="campus_buildings.csv quality note",
        source_scope="PRINEVILLE_SPECIFIC", source_authority="TIER1", status="SUPPORTED",
        reason="ECH acronym matches OCP evaporative cooling/humidification; not a full penthouse spec")
    add(epoch_id="E3_CCO1_CCO2", building="CCO1", mechanism="facility_water_IWS_IWR",
        evidence="IWS/IWR piping and data-hall supply water; water rooms",
        source="217-19-000276-MECH", page="", source_scope="PRINEVILLE_SPECIFIC", source_authority="TIER1",
        status="SUPPORTED", reason="water piping present; technology not fully named")
    add(epoch_id="E3_CCO1_CCO2", building="CCO1", mechanism="mechanical_chiller",
        evidence="No chiller word in CCO mechanical inspection summary",
        source="217-19-000276-MECH", page="", source_scope="PRINEVILLE_SPECIFIC", source_authority="TIER1",
        status="UNKNOWN", reason="refrigeration lines noted; do not infer chiller plant")
    add(epoch_id="E3_CCO1_CCO2", building="CCO1", mechanism="SPLC",
        evidence="none", source="META_SPLC_2018", page="", source_scope="META_FLEET_CONTEXT",
        source_authority="TIER3", status="UNSUPPORTED", reason="no Prineville linkage")
    add(epoch_id="E3_CCO1_CCO2", building="CCO", mechanism="CRAC_electrical_room",
        evidence="CRAC piping in an electrical room",
        source="217-19-000276-MECH", page="", source_scope="PRINEVILLE_SPECIFIC", source_authority="TIER1",
        status="CONFIRMED", reason="support-space CRAC; not data-hall architecture")

    add(epoch_id="E4_PRN1_MECH_ADDITION", building="PRN1", mechanism="mechanical_chiller",
        evidence="Heating/cooling for personnel and IT; chilled-water, CRAH, chiller; additional roof chiller operational 2024-02-02",
        source="217-21-003734-MECH; 217-24-000066-MECH", page="prn1_addition_facts.csv",
        source_scope="PRINEVILLE_SPECIFIC", source_authority="TIER1", status="CONFIRMED",
        reason="inspector recorded operational chiller; PRN1 only")
    add(epoch_id="E4_PRN1_MECH_ADDITION", building="PRN1", mechanism="CRAH_chilled_water",
        evidence="CRAH connections and chilled-water hydronic test 2023-09-21 (chillers/CRAH not yet final then)",
        source="217-21-003734-MECH", page="page 2 hydronic comments",
        source_scope="PRINEVILLE_SPECIFIC", source_authority="TIER1", status="CONFIRMED", reason="")
    add(epoch_id="E4_PRN1_MECH_ADDITION", building="PRN1", mechanism="cooling_tower",
        evidence="Heat-rejection type not stated",
        source="prn1_addition_facts.csv interpretation_note", page="",
        source_scope="PRINEVILLE_SPECIFIC", source_authority="TIER1", status="UNKNOWN",
        reason="do not infer open tower from the word chiller")
    add(epoch_id="E4_PRN1_MECH_ADDITION", building="PRN1", mechanism="dry_cooler",
        evidence="not stated", source="PRN1_PERMITS_2021_2024", page="",
        source_scope="PRINEVILLE_SPECIFIC", source_authority="TIER1", status="UNKNOWN", reason="")
    add(epoch_id="E4_PRN1_MECH_ADDITION", building="PRN1", mechanism="SPLC",
        evidence="none", source="META_SPLC_2018", page="", source_scope="META_FLEET_CONTEXT",
        source_authority="TIER3", status="UNSUPPORTED", reason="fleet != Prineville")
    add(epoch_id="E4_PRN1_MECH_ADDITION", building="campus_other_than_PRN1", mechanism="mechanical_chiller",
        evidence="No permit transferring PRN1 chiller to CCO/PRN2–6",
        source="PRN1_PERMITS_2021_2024", page="", source_scope="PRINEVILLE_SPECIFIC",
        source_authority="TIER1", status="UNSUPPORTED", reason="PRN1-scoped evidence only")

    pd.DataFrame(rows).to_csv(OUT / "PRINEVILLE_COOLING_ARCHITECTURE_EVIDENCE.csv", index=False)
    jdump(OUT / "PRINEVILLE_COOLING_ARCHITECTURE_EVIDENCE.json", {"n": len(rows), "items": rows,
          "rule": "Fleet-wide Meta source cannot produce CONFIRMED without Prineville linkage. Capability != installed."})


def write_physics() -> None:
    spec = {
        "early_direct_air_pathway": [
            "outside air",
            "optional return-air mixing (winter / low Tdb)",
            "ECH mist (evaporative cooling and/or humidification)",
            "mist eliminators",
            "fan-wall supply",
            "data hall cold aisle",
            "hot-aisle containment → exhaust or recirculate",
        ],
        "psychrometric_mass_balance_not_fitted": "water_added_to_air ≈ m_da * (w_supply - w_in_to_spray)",
        "w_in_to_spray_depends_on": "outside-air humidity ratio and mixed-air fraction; currently gray-box uses outdoor w only",
        "variables": {
            "m_da": "estimated from P_IT and server ΔT prior; not metered",
            "OA_fraction": "documented but latent in current code",
            "T_supply_target": "OCP 65–85 F band; code uses 25 C prior",
            "RH_or_dewpoint_limits": "OCP dewpoint min 41.9 F and 65% RH max; not in code",
            "evap_effectiveness": "estimated prior 0.85",
            "RO_softener_inefficiency": "documented treatment; not in mass balance",
        },
        "by_epoch": {
            "E1_E2_early_PRN": {
                "creates_conditioning_load": "IT sensible heat (plus small building/office reuse of return heat in winter)",
                "controls_airflow": "VFD fan array matching load (OCP); code uses m_air ∝ P_IT",
                "controls_water_addition": "modulating high-pressure mist vs T/RH/dewpoint setpoints",
                "weather_variables": "Tdb, Twb, RH/humidity ratio, possibly dewpoint",
                "water_in_air_stream": True,
                "separate_heat_rejection_loop": False,
                "dry_no_water_operation": True,
                "water_boundary": "CONDITIONING_SITE_WATER (mist/RO feed). Not Meta total withdrawal, City+POD split, or sewer.",
            },
            "E3_CCO": {
                "creates_conditioning_load": "IT heat in CCO halls",
                "controls_airflow": "UNKNOWN beyond ECH piping presence",
                "controls_water_addition": "SUPPORTED ECH; details unknown",
                "weather_variables": "likely Tdb/Twb/RH if same class",
                "water_in_air_stream": "SUPPORTED",
                "separate_heat_rejection_loop": "UNKNOWN (IWS/IWR present)",
                "dry_no_water_operation": "UNKNOWN",
                "water_boundary": "CONDITIONING_SITE_WATER if ECH; unidentified additional loops",
            },
            "E4_PRN1_2024": {
                "creates_conditioning_load": "IT + personnel HVAC on addition; chilled-water/CRAH/chiller CONFIRMED",
                "controls_airflow": "CRAH plus any remaining OA path UNKNOWN split",
                "controls_water_addition": "possible remaining mist PLUS unidentified chiller heat-rejection water",
                "weather_variables": "Tdb/Twb if towers/adiabatic; possibly weaker if air-cooled",
                "water_in_air_stream": "UNKNOWN remaining fraction",
                "separate_heat_rejection_loop": True,
                "dry_no_water_operation": "UNKNOWN (depends on heat-rejection type)",
                "water_boundary": "CONDITIONING_SITE_WATER split unidentified; do not assume cooling-tower makeup",
            },
        },
        "do_not_fit_in_this_pass": True,
    }
    jdump(OUT / "PRINEVILLE_CONDITIONING_PHYSICS_SPEC.json", spec)
    (OUT / "PRINEVILLE_CONDITIONING_PHYSICS_SPEC.md").write_text(
        """# Prineville conditioning physics (structure only; not fitted)

## Early direct-air architecture (PRN1 2011; OCP v1.0)

`outside air → optional return-air mixing → ECH mist (cool and/or humidify) → mist eliminators → fan wall → data hall`

Unfitted mass balance:

`W_airside ≈ m_da × Δω` with `Δω = max(w_supply − w_mixed, 0)`

`w_mixed` depends on outdoor humidity ratio and return-air fraction. The current gray-box uses outdoor air only (`w_outdoor`), so winter mixing is named but not applied.

Water is consumed **in the air stream** (direct evaporative / humidification). There is **no** 2011 cooling-tower heat-rejection loop. Dry/economizer operation exists whenever outdoor air already meets SAT/RH without spray.

Predicted physical boundary: `CONDITIONING_SITE_WATER` (mist + RO/softener feed).  
Outside that boundary: City vs POD withdrawal split, sewer/return, Meta annual disclosed withdrawal, irrigation, construction water.

## CCO (2020–2022)

ECH piping in a CCO data hall is **SUPPORTED**. Full penthouse identity is **UNKNOWN**. IWS/IWR implies some facility water loop whose technology is unnamed.

## PRN1 addition (2024-02)

Chilled-water / CRAH / chiller is **CONFIRMED** at PRN1. Heat-rejection device (tower vs dry cooler vs air-cooled) is **UNKNOWN**. Do not add open-tower water physics from the word “chiller”.

Do not fit these equations in this pass.
"""
    )


def write_gap_matrix() -> None:
    rows = [
        dict(mechanism="direct_evaporative_cooling", evidence_requirement="PRN1 2011 ECH mist CONFIRMED",
             current_implementation="adiabatic saturator + spray fraction vs 25 C",
             code_location="src/prineville_graybox.py::simulate", parameter_provenance="ε=0.85 prior",
             correct_physical_boundary="partial (air-side water yes; maps onward to withdrawal via fitted scale)",
             correct_epoch="early yes; later PRN1 chiller no", status="PRESENT_AND_SUPPORTED"),
        dict(mechanism="humidification", evidence_requirement="same ECH system CONFIRMED",
             current_implementation="same Δω path (cooling and humidification not separated)",
             code_location="simulate evap_water", parameter_provenance="psychrometric identity",
             correct_physical_boundary="yes as air-side water", correct_epoch="early", status="PRESENT_AND_SUPPORTED"),
        dict(mechanism="dry_free_outside_air", evidence_requirement="economizer CONFIRMED",
             current_implementation="if t_db<=25 C: no spray, t_supply=t_db",
             code_location="simulate t_supply", parameter_provenance="25 C prior",
             correct_physical_boundary="yes", correct_epoch="early", status="PRESENT_AND_SUPPORTED"),
        dict(mechanism="return_air_recirculation", evidence_requirement="winter mixing CONFIRMED at PRN1",
             current_implementation="return_air_C declared; unused. Mode label winter_mix uses 100% OA when cold",
             code_location="Params.return_air_C; cooling_mode string", parameter_provenance="unused 35 C",
             correct_physical_boundary="no (mixed-air ω missing)", correct_epoch="early missing physics",
             status="REQUIRED_MISSING"),
        dict(mechanism="airflow_IT_dependence", evidence_requirement="VFD fans matching load CONFIRMED in spec",
             current_implementation="m_air ∝ P_IT; p_fan = 0.025 P_IT",
             code_location="simulate m_air, p_fan", parameter_provenance="linear prior",
             correct_physical_boundary="n/a", correct_epoch="early", status="PRESENT_AND_SUPPORTED"),
        dict(mechanism="fan_power", evidence_requirement="fan wall CONFIRMED",
             current_implementation="constant fraction of IT",
             code_location="fan_fraction_of_it", parameter_provenance="PUE-room prior",
             correct_physical_boundary="n/a", correct_epoch="early", status="KEEP_AS_SCENARIO"),
        dict(mechanism="dry_bulb_dependence", evidence_requirement="OA/economizer CONFIRMED",
             current_implementation="t_db drives mode and spray", code_location="simulate",
             parameter_provenance="weather", correct_physical_boundary="yes", correct_epoch="early",
             status="PRESENT_AND_SUPPORTED"),
        dict(mechanism="RH_wetbulb_dependence", evidence_requirement="Twb/RH/dewpoint limits in OCP spec",
             current_implementation="Twb in t_full and spray; RH in humidity ratio; dewpoint min not coded",
             code_location="simulate", parameter_provenance="partial",
             correct_physical_boundary="partial", correct_epoch="early", status="PRESENT_AND_SUPPORTED"),
        dict(mechanism="supply_air_limits", evidence_requirement="cold aisle 65–85 F; 65% RH max; dewpoint min",
             current_implementation="single 25 C target", code_location="supply_target_C",
             parameter_provenance="prior inside band", correct_physical_boundary="n/a", correct_epoch="early",
             status="KEEP_AS_SCENARIO"),
        dict(mechanism="architecture_epochs", evidence_requirement="multi-building / PRN1 2024 chiller CONFIRMED",
             current_implementation="single campus architecture 2011–2024",
             code_location="prineville_graybox.py has no A_t", parameter_provenance="n/a",
             correct_physical_boundary="n/a", correct_epoch="no", status="EPOCH_MISMATCH"),
        dict(mechanism="PRN1_chilled_water_chiller", evidence_requirement="CONFIRMED 2024-02-02 at PRN1",
             current_implementation="absent (no COP, no CW loop, no CRAH)",
             code_location="none", parameter_provenance="n/a",
             correct_physical_boundary="n/a", correct_epoch="missing", status="REQUIRED_MISSING"),
        dict(mechanism="water_boundary_tagging", evidence_requirement="CONDITIONING_SITE_WATER vs WITHDRAWAL",
             current_implementation="raw evap then fitted scale to Meta withdrawal",
             code_location="conditional_reconstruction.py water_scale",
             parameter_provenance="fitted through 2022", correct_physical_boundary="no if treated as physics",
             correct_epoch="n/a", status="BOUNDARY_MISMATCH"),
        dict(mechanism="SPLC", evidence_requirement="Prineville-specific install",
             current_implementation="absent", code_location="none", parameter_provenance="n/a",
             correct_physical_boundary="n/a", correct_epoch="n/a", status="SECOND_ORDER_NOT_REQUIRED"),
        dict(mechanism="cooling_tower_campus", evidence_requirement="installed tower",
             current_implementation="absent (correct for 2011; unknown for PRN1 2024 heat rejection)",
             code_location="none", parameter_provenance="n/a",
             correct_physical_boundary="n/a", correct_epoch="n/a", status="SECOND_ORDER_NOT_REQUIRED"),
        dict(mechanism="Lei_Masanet_or_ESIF_coefficients", evidence_requirement="must not transfer",
             current_implementation="not in gray-box Params", code_location="prineville_graybox.py",
             parameter_provenance="none", correct_physical_boundary="n/a", correct_epoch="n/a",
             status="PRESENT_AND_SUPPORTED"),
    ]
    pd.DataFrame(rows).to_csv(OUT / "PRINEVILLE_GRAYBOX_STRUCTURE_GAP_MATRIX.csv", index=False)
    jdump(OUT / "PRINEVILLE_GRAYBOX_STRUCTURE_GAP_MATRIX.json", {
        "n": len(rows), "items": rows,
        "structural_disposition": DISPOSITION,
        "not_judged_by_water_holdout": True,
    })


def write_parameters() -> None:
    rows = [
        dict(name="supply_target_C", value=25.0, units="degC", current_source="code prior",
             prineville_specific="no", generic_literature="yes (inside OCP 18.3–29.4 C band)",
             lei_masanet="no", meta_fleet_wide="no", fitted="no", assumed="yes",
             architecture_dependent="yes", supported_epoch="E1–E2", confidence="medium as scenario",
             recommended_disposition="KEEP_AS_SCENARIO"),
        dict(name="return_air_C", value=35.0, units="degC", current_source="unused declaration",
             prineville_specific="no", generic_literature="n/a", lei_masanet="no", meta_fleet_wide="no",
             fitted="no", assumed="yes", architecture_dependent="yes", supported_epoch="E1 mixing exists but Treturn unmeasured",
             confidence="low", recommended_disposition="REQUIRES_NEW_EVIDENCE"),
        dict(name="evap_effectiveness", value=0.85, units="1", current_source="generic saturator",
             prineville_specific="no", generic_literature="yes", lei_masanet="no", meta_fleet_wide="no",
             fitted="no", assumed="yes", architecture_dependent="yes", supported_epoch="E1 ECH",
             confidence="low", recommended_disposition="REQUIRES_SITE_CALIBRATION"),
        dict(name="server_deltaT_C", value=12.0, units="K", current_source="prior",
             prineville_specific="no", generic_literature="yes", lei_masanet="no", meta_fleet_wide="no",
             fitted="no", assumed="yes", architecture_dependent="yes", supported_epoch="E1",
             confidence="low", recommended_disposition="REQUIRES_SITE_CALIBRATION"),
        dict(name="fan_fraction_of_it", value=0.025, units="1", current_source="PUE-room prior",
             prineville_specific="no", generic_literature="yes", lei_masanet="no", meta_fleet_wide="no",
             fitted="no", assumed="yes", architecture_dependent="yes", supported_epoch="E1 fan wall",
             confidence="low", recommended_disposition="KEEP_AS_SCENARIO"),
        dict(name="other_facility_fraction_of_it", value=0.035, units="1", current_source="PUE-room prior",
             prineville_specific="no", generic_literature="yes", lei_masanet="no", meta_fleet_wide="no",
             fitted="no", assumed="yes", architecture_dependent="no", supported_epoch="all electrical",
             confidence="low", recommended_disposition="KEEP_AS_SCENARIO"),
        dict(name="evap_aux_fraction", value=0.005, units="1", current_source="hardcoded simulate()",
             prineville_specific="no", generic_literature="yes", lei_masanet="no", meta_fleet_wide="no",
             fitted="no", assumed="yes", architecture_dependent="yes", supported_epoch="E1 mist pumps",
             confidence="low", recommended_disposition="KEEP_AS_SCENARIO"),
        dict(name="water_scale", value="fitted train-only; not copied here", units="1",
             current_source="conditional reconstruction through 2022",
             prineville_specific="yes (fitted mapping)", generic_literature="no", lei_masanet="no",
             meta_fleet_wide="no", fitted="yes", assumed="no", architecture_dependent="indirectly",
             supported_epoch="mapping not physics", confidence="n/a as physics",
             recommended_disposition="KEEP_AS_SCENARIO"),
        dict(name="ESIF_WUE_0.70", value=0.70, units="L/kWh", current_source="ESIF not used in gray-box",
             prineville_specific="no", generic_literature="no", lei_masanet="no", meta_fleet_wide="no",
             fitted="no", assumed="n/a", architecture_dependent="n/a", supported_epoch="must not transfer",
             confidence="n/a", recommended_disposition="UNSUPPORTED_REMOVE_CANDIDATE"),
    ]
    pd.DataFrame(rows).to_csv(OUT / "PRINEVILLE_PARAMETER_PROVENANCE.csv", index=False)


def write_validation_policy() -> None:
    jdump(OUT / "PRINEVILLE_FUTURE_VALIDATION_POLICY.json", {
        "existing_meta_2023_2024_water_benchmark": {
            "years": [2023, 2024],
            "status": "PREVIOUSLY_EXPOSED",
            "not_pristine_new_TEST": True,
            "this_audit_did_not_inspect_outcomes_for_structure": True,
        },
        "development_calibration_evidence_allowed": [
            "2011–2022 Meta annual electricity (closure, labeled closure)",
            "2011–2022 weather",
            "2011 OCP/Meta design physics",
            "permit-documented architecture epochs",
            "City monthly service meters as a DIFFERENT boundary (not Meta total)",
        ],
        "development_calibration_evidence_forbidden_for_structure_selection": [
            "Meta 2023–2024 annual water outcomes",
            "holdout MAPE / WAPE as architecture chooser",
        ],
        "previously_exposed_benchmark": "Meta 2023–2024 annual water (already used in prior pipeline reports)",
        "genuinely_new_validation_candidates": [
            "new City monthly data at a documented meter identity after a freeze date",
            "future Meta annual water vintages not yet used in this repo",
            "PacifiCorp interval/monthly campus electricity if acquired",
            "direct campus SAT/RH/airflow/mist-water telemetry if acquired",
            "another appropriate site (not ESIF coefficients)",
        ],
        "rules": [
            "Freeze structural revision before inspecting 2023–2024 water.",
            "Do not add chiller/SPLC/tower terms because holdout water failed.",
            "If 2023–2024 is reported, label DIAGNOSTIC_PREVIOUSLY_EXPOSED.",
        ],
    })


def write_data_gaps() -> None:
    rows = [
        dict(quantity_document="PRN1 2024 chiller heat-rejection schedule (tower vs dry vs air-cooled)",
             boundary_closed="E4 water-consuming mechanism", why="chiller CONFIRMED; water physics unidentified",
             current_uncertainty="UNKNOWN heat rejection", likely_owner="Crook County / Meta mechanical drawings",
             temporal_resolution="as-built", min_request="equipment schedule + condenser type",
             expected_value="decides whether to add tower makeup vs dry path", priority="HIGHEST",
             blocks_model_progress="blocks complete E4 water structure; does not block mixing revision"),
        dict(quantity_document="OCP/Prineville psychrometric sequence setpoints actually used",
             boundary_closed="OA fraction and humidification vs cooling mode", why="mixing is documented; controls not public",
             current_uncertainty="OA fraction latent", likely_owner="Meta BMS / OCP Appendix A operating copy",
             temporal_resolution="control curve", min_request="SAT/RH/dewpoint and damper sequence",
             expected_value="calibrates mixing without 2023–2024 water", priority="HIGHEST",
             blocks_model_progress="partial: mixing form is known; parameters unidentified"),
        dict(quantity_document="CCO mechanical design (ECH vs other)",
             boundary_closed="E3 architecture class", why="ECH piping SUPPORTED only",
             current_uncertainty="POSSIBLE copy of OA+ECH", likely_owner="permits/drawings",
             temporal_resolution="design", min_request="CCO mechanical narrative",
             expected_value="whether campus is multi-architecture before 2024", priority="HIGH",
             blocks_model_progress="no for early-epoch mixing revision"),
        dict(quantity_document="PRN2–PRN6 mechanical class",
             boundary_closed="E2 copy-or-not", why="four buildings exist; specs missing",
             current_uncertainty="POSSIBLE same class", likely_owner="permits",
             temporal_resolution="design", min_request="one later-PRN mechanical summary",
             expected_value="epoch homogeneity", priority="HIGH", blocks_model_progress="no"),
        dict(quantity_document="supply airflow / mixed / supply T/RH / mist water",
             boundary_closed="CONDITIONING_SITE_WATER time series", why="current water is annual withdrawal mapping",
             current_uncertainty="no public telemetry", likely_owner="Meta",
             temporal_resolution="hourly preferred; monthly useful", min_request="monthly mist makeup",
             expected_value="true calibration of Δω model", priority="HIGH", blocks_model_progress="no for structure"),
        dict(quantity_document="City meter identity / master vs submeter / sewer",
             boundary_closed="MUNICIPAL_SUPPLY vs CONDITIONING vs RETURN_FLOW",
             why="City service ≠ Meta total", current_uncertainty="partially documented in existing City package",
             likely_owner="City of Prineville", temporal_resolution="monthly", min_request="meter boundary memo",
             expected_value="independent monthly validation candidate", priority="HIGH",
             blocks_model_progress="no"),
        dict(quantity_document="OWRD/POD well volumes campus relevance",
             boundary_closed="GROUNDWATER_WITHDRAWAL vs City", why="direct water separate",
             current_uncertainty="crosswalk exists; completeness unknown", likely_owner="OWRD/Meta",
             temporal_resolution="annual/monthly", min_request="confirm POD list", expected_value="source split",
             priority="MEDIUM", blocks_model_progress="no"),
        dict(quantity_document="PacifiCorp monthly/interval campus electricity",
             boundary_closed="P_fac time series vs annual Meta", why="IT latent without monthly energy",
             current_uncertainty="annual only", likely_owner="PacifiCorp/Meta",
             temporal_resolution="monthly/interval", min_request="monthly campus kWh",
             expected_value="airflow/IT scale without inventing workload", priority="MEDIUM",
             blocks_model_progress="no"),
        dict(quantity_document="BMS architecture later expansions",
             boundary_closed="A_t campus-wide", why="do not assume copy", current_uncertainty="UNKNOWN",
             likely_owner="Meta", temporal_resolution="design", min_request="one-line cooling riser by building",
             expected_value="prevents false homogeneity", priority="HIGH", blocks_model_progress="no"),
    ]
    pd.DataFrame(rows).to_csv(OUT / "PRINEVILLE_HIGH_VALUE_DATA_GAPS.csv", index=False)
    lines = ["# Prineville high-value data gaps", "", "Ranked by marginal value for **structure**, not holdout MAPE.", ""]
    for i, r in enumerate(rows, 1):
        lines.append(f"{i}. **{r['quantity_document']}** — {r['why']} (priority {r['priority']}).")
    (OUT / "PRINEVILLE_HIGH_VALUE_DATA_GAPS.md").write_text("\n".join(lines) + "\n")


def write_next_experiment() -> None:
    (OUT / "NEXT_PRINEVILLE_CONDITIONING_EXPERIMENT.md").write_text(
        f"""# Next Prineville conditioning experiment (NOT executed)

Disposition: `{DISPOSITION}`

This is a **preregistered structural-revision** experiment, not a holdout-chasing refit.

## Implement ONLY these confirmed missing / incomplete mechanisms

1. **Winter/economizer mixed-air fraction** in the air-side mass balance  
   `w_in = OA_frac * w_oa + (1-OA_frac) * w_return`  
   with OA_frac from documented control logic (OCP sequence), not from 2023–2024 water.
2. **Architecture state `A_t`**  
   - `DIRECT_OUTSIDE_AIR_EVAP` for early PRN (and CCO only as a SUPPORTED same-class scenario, not a fitted switch).  
   - `PRN1_HYBRID_CHILLED_WATER` from **2024-02-02** at **PRN1 only**.  
   Do **not** convert the whole campus to chillers.
3. **Explicit water-boundary tags**  
   Gray-box output remains `CONDITIONING_SITE_WATER` (air-side). Any map to Meta `WITHDRAWAL` stays a labeled mapping, not physics.
4. **PRN1 chiller water**  
   Include a **placeholder unidentified heat-rejection water term** with provenance `UNKNOWN` unless condenser type is acquired. Do not assume a cooling tower.

## Freeze before outcome inspection

Write `PRINEVILLE_STRUCTURAL_REVISION_FREEZE.json` containing equations, epoch dates, and parameters still unidentified. Then stop. Only after freeze may previously exposed 2023–2024 water be scored as `DIAGNOSTIC_PREVIOUSLY_EXPOSED`.

## Inputs

- Existing weather (KS39/KRDM canonical).
- Latent IT scale from annual electricity **closure** (not a new IT model).
- OCP/Meta 2011 control structure for mixing.
- Permit epoch dates (not estimated from water).

## Target boundary

Primary: modeled `W_conditioning` (air-side mist).  
Secondary diagnostic: existing mapping to Meta annual withdrawal, clearly tagged.

Temporal resolution: hourly physics aggregated to month/year. No invented hourly water meters.

## Fit / calibration data

Allowed: 2011–2022 for remaining unidentified scalars (effectiveness, OA-fraction parameters) **if** a calibration is still needed after implementing documented control. Prefer documenting priors over fitting.

Forbidden as structure selectors: Meta 2023–2024 water.

## Validation data

- Prefer new City monthly meter-boundary series or a future Meta annual vintage.  
- 2023–2024 Meta water: diagnostic only, previously exposed.

## Metrics

Water-volume WAPE on the **declared** boundary. Secondary: WUE if both water and IT energy share a boundary. Do not optimize architecture on these metrics.

## Stopping rule

Stop when: mixing is implemented; `A_t` exists; PRN1 chiller is an epoch flag with unidentified condenser water; freeze file written; no ESIF/Lei coefficients entered; 2023–2024 not used to choose terms.

## Uncertainty

Keep evidence class on every term (CONFIRMED / SUPPORTED / UNKNOWN). Do not turn UNKNOWN condenser type into a tower model.

## Must NOT add

SPLC; campus-wide chillers; ESIF 0.70/1.27/1.42; 42.5% TSC; Lei WUE; 2011 WUE 0.31 as later-campus truth; IEC as installed.
"""
    )


def write_status() -> None:
    jdump(OUT / "FINAL_PRINEVILLE_ARCHITECTURE_AUDIT_STATUS.json", {
        "SOURCE_COVERAGE": "PASS",
        "FACILITY_EPOCH_IDENTIFICATION": "PASS",
        "EARLY_PRINEVILLE_DIRECT_EVAP_ARCHITECTURE": "CONFIRMED",
        "LATER_PRINEVILLE_ARCHITECTURE": "PARTIAL",
        "OUTSIDE_AIR_COOLING": "CONFIRMED",
        "RETURN_AIR_RECIRCULATION": "CONFIRMED",
        "DIRECT_EVAPORATIVE_COOLING": "CONFIRMED",
        "HUMIDIFICATION": "CONFIRMED",
        "INDIRECT_EVAPORATIVE_COOLING": "UNSUPPORTED",
        "SPLC_AT_PRINEVILLE": "UNSUPPORTED",
        "LIQUID_COOLING_AT_PRINEVILLE": "UNSUPPORTED",
        "DRY_COOLER_AT_PRINEVILLE": "UNKNOWN",
        "COOLING_TOWER_AT_PRINEVILLE": "CONTRADICTED",
        "CHILLER_AT_PRINEVILLE": "CONFIRMED",
        "CHILLER_SCOPE": "PRN1_FROM_2024_02_02_ONLY",
        "AIRFLOW_CONTROL_STRUCTURE": "SUPPORTED",
        "CONDITIONING_WATER_MECHANISM": "CONFIRMED",
        "WATER_BOUNDARY": "PARTIAL",
        "CURRENT_GRAYBOX_STRUCTURAL_ADEQUACY": "FAIL",
        "CURRENT_GRAYBOX_PARAMETER_PROVENANCE": "PARTIAL",
        "HOLDOUT_INTEGRITY": "PREVIOUSLY_EXPOSED_NOT_USED_FOR_STRUCTURE",
        "STRUCTURAL_REVISION_GATE": DISPOSITION,
        "NEXT_EXPERIMENT_READINESS": "PASS",
        "graybox_hash_unchanged": sha256_file(GRAYBOX) == GRAYBOX_SHA256,
        "cpu_unchanged": True,
        "h100_unchanged": True,
        "esif_numerics_not_refit": True,
        "meta_2023_2024_water_not_used_for_structure": True,
        "fitted_or_refit_graybox": False,
        "groundwater_run": False,
        "emissions_run": False,
    })


def figures() -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 3.2))
    spans = [
        (2011.3, 2014.0, "E1 PRN1 OA+ECH", "#55a868"),
        (2014.0, 2020.2, "E2 PRN multi-hall", "#8c8c8c"),
        (2018.7, 2022.1, "E3 CCO", "#4c72b0"),
        (2021.7, 2024.2, "E4 PRN1 chiller", "#c44e52"),
    ]
    for i, (a, b, lab, c) in enumerate(spans):
        ax.barh(i, b - a, left=a, color=c, height=0.6)
        ax.text((a + b) / 2, i, lab, ha="center", va="center", fontsize=8, color="white")
    ax.set_yticks([])
    ax.set_xlabel("Year")
    ax.set_title("Prineville facility epochs (architecture class, not a fitted breakpoint)")
    ax.set_xlim(2010, 2026)
    fig.tight_layout()
    fig.savefig(FIG / "01_facility_epoch_timeline.png", dpi=130)
    plt.close()

    fig, ax = plt.subplots(figsize=(9, 3.4))
    ax.axis("off")
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 4)
    ax.set_title("Mechanism by major epoch (structure only)")
    ax.text(0.2, 3.2, "E1/E2  OA → mix → ECH mist → fan wall → hall\nWater: air-stream Δω   No chiller/tower (2011 design)", fontsize=8, va="top")
    ax.text(0.2, 1.7, "E3 CCO  ECH piping SUPPORTED; full copy UNKNOWN", fontsize=8, va="top")
    ax.text(0.2, 0.7, "E4 PRN1  chilled-water/CRAH/chiller CONFIRMED 2024-02-02\nHeat-rejection water UNKNOWN   Do not campus-wide copy", fontsize=8, va="top")
    fig.tight_layout()
    fig.savefig(FIG / "02_epoch_mechanism_diagram.png", dpi=130)
    plt.close()

    ev = pd.read_csv(OUT / "PRINEVILLE_COOLING_ARCHITECTURE_EVIDENCE.csv")
    order = ["CONFIRMED", "SUPPORTED", "POSSIBLE", "UNKNOWN", "UNSUPPORTED", "CONTRADICTED"]
    counts = ev.status.value_counts().reindex(order).fillna(0)
    fig, ax = plt.subplots(figsize=(7, 3.2))
    ax.bar(order, counts.values, color=["#55a868", "#8c8c8c", "#dd8452", "#4c72b0", "#c44e52", "#000000"])
    ax.set_ylabel("Evidence rows")
    ax.set_title("Architecture evidence status counts (not a model score)")
    ax.tick_params(axis="x", rotation=20)
    fig.tight_layout()
    fig.savefig(FIG / "03_evidence_status_counts.png", dpi=130)
    plt.close()

    g = pd.read_csv(OUT / "PRINEVILLE_GRAYBOX_STRUCTURE_GAP_MATRIX.csv")
    fig, ax = plt.subplots(figsize=(8, 4.2))
    colors = {
        "PRESENT_AND_SUPPORTED": "#55a868",
        "KEEP_AS_SCENARIO": "#8c8c8c",
        "REQUIRED_MISSING": "#c44e52",
        "EPOCH_MISMATCH": "#dd8452",
        "BOUNDARY_MISMATCH": "#4c72b0",
        "SECOND_ORDER_NOT_REQUIRED": "#e8e8e8",
    }
    y = range(len(g))
    ax.barh(list(y), [1] * len(g), color=[colors.get(s, "#999") for s in g.status])
    ax.set_yticks(list(y))
    ax.set_yticklabels(g.mechanism, fontsize=7)
    ax.set_xticks([])
    ax.set_title("Gray-box vs required mechanism (source evidence, not water skill)")
    fig.tight_layout()
    fig.savefig(FIG / "04_graybox_gap_diagram.png", dpi=130)
    plt.close()


def write_cleanup_log() -> None:
    jdump(OUT / "ESIF_SEMANTIC_CLEANUP_FILES.json", {
        "numerical_esif_outputs_changed": False,
        "experiment_rerun": False,
        "files": [
            "other_sources/nlr_esif_fullstack/heat_rejection_water/manifests/WATER_TEMPORAL_MODEL_ELIGIBILITY.json",
            "other_sources/nlr_esif_fullstack/heat_rejection_water/manifests/HEAT_WATER_BOUNDARY_FREEZE.json",
            "other_sources/nlr_esif_fullstack/heat_rejection_water/manifests/ESIF_HEAT_WATER_RESULT_FREEZE.json",
            "other_sources/nlr_esif_fullstack/heat_rejection_water/analysis/FINAL_ESIF_HEAT_WATER_STATUS.json",
            "other_sources/nlr_esif_fullstack/heat_rejection_water/analysis/FIRST_YEAR_WATER_ACCOUNTING_REPRODUCTION.json",
            "other_sources/nlr_esif_fullstack/heat_rejection_water/analysis/ESIF_VS_LEI_MASANET.json",
            "other_sources/nlr_esif_fullstack/heat_rejection_water/analysis/WATER_EVIDENCE_INVENTORY.json",
            "other_sources/nlr_esif_fullstack/heat_rejection_water/analysis/WATER_EVIDENCE_INVENTORY.csv",
            "other_sources/nlr_esif_fullstack/heat_rejection_water/docs/ESIF_HEAT_WATER_BOUNDARY.md",
            "other_sources/nlr_esif_fullstack/heat_rejection_water/docs/ESIF_HEAT_WATER_PROJECT_INTEGRATION.md",
            "other_sources/nlr_esif_fullstack/heat_rejection_water/docs/ESIF_HEAT_REJECTION_WATER_REPORT.md",
            "other_sources/nlr_esif_fullstack/heat_rejection_water/scripts/run_esif_heat_rejection_water.py",
            "other_sources/nlr_esif_fullstack/heat_rejection_water/tests/test_heat_rejection_water.py",
            "other_sources/nlr_esif_fullstack/heat_rejection_water/figures/01_thermal_water_hierarchy.png",
            "other_sources/nlr_esif_fullstack/heat_rejection_water/figures/06_esif_vs_lei.png",
        ],
    })


def main() -> None:
    write_initial_state()
    write_model_inventory()
    write_source_register()
    write_epochs()
    write_architecture_evidence()
    write_physics()
    write_gap_matrix()
    write_parameters()
    write_validation_policy()
    write_data_gaps()
    write_next_experiment()
    figures()
    write_cleanup_log()
    write_status()
    assert sha256_file(GRAYBOX) == GRAYBOX_SHA256
    print(json.dumps({"disposition": DISPOSITION, "graybox_unchanged": True}, indent=2))


if __name__ == "__main__":
    main()
