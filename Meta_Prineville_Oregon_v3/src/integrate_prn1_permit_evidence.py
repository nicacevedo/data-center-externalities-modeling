"""Integrate the local strictly-valuable PRN1 permit package into existing tables.

Reuses campus_permit_evidence.csv / campus_permit_events.csv (no second event
subsystem). Structured quantitative facts go to
data/canonical/facility/prn1_addition_facts.csv.

Does not infer MW from amp/circuit counts, does not choose an exact addition
area, and does not modify gray-box or water-holdout numerics.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "data" / "raw" / "prineville_strictly_valuable_permits_v2"
EVIDENCE = ROOT / "data" / "canonical" / "campus_permit_evidence.csv"
EVENTS = ROOT / "data" / "canonical" / "campus_permit_events.csv"
BUILDINGS = ROOT / "data" / "manual_templates" / "campus_buildings.csv"
FACTS = ROOT / "data" / "canonical" / "facility" / "prn1_addition_facts.csv"

PERMIT_IDS = [
    "217-21-003723-STR",
    "217-21-003727-ELEC",
    "217-21-003731-PLM",
    "217-21-003734-MECH",
    "217-24-000066-MECH",
    "217-22-000286-ELEC",
    "217-22-000289-MECH",
]
PERMIT_ID_SET = set(PERMIT_IDS)

ADDRESS = "735 SW CONNECT WAY, PRINEVILLE OR 97754"
PARCEL = "1515010001102"
PROVENANCE = "reported_permit_document_evidence"

AREA_LOW = 82273
AREA_HIGH = 82736
AREA_PROXY = 82700

INSPECTION_RE = re.compile(
    r"Inspection Type:\s*(.*?)\s*"
    r"Inspection Result:\s*(.*?)\s*"
    r"Inspection Date:\s*(.*?)\s*"
    r"Inspector:",
    re.S,
)
DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def _iso_date(text: str) -> str | None:
    m = DATE_RE.search(str(text or ""))
    if not m:
        return None
    month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"{year:04d}-{month:02d}-{day:02d}"


def _clean(text: str) -> str:
    return " ".join(str(text or "").split())


def parse_inspections(pdf_path: Path) -> dict:
    doc = pymupdf.open(pdf_path)
    text = "\n".join(page.get_text() or "" for page in doc)
    n_pages = doc.page_count
    doc.close()
    rows = []
    for m in INSPECTION_RE.finditer(text):
        itype = _clean(m.group(1))
        result = _clean(m.group(2))
        date = _iso_date(m.group(3))
        rows.append({"inspection_type": itype, "result": result, "date": date})
    dated = [r for r in rows if r["date"]]
    dates = sorted({r["date"] for r in dated})
    finals = [
        r
        for r in dated
        if r["result"].lower() == "approved"
        and "final" in r["inspection_type"].lower()
    ]
    final = None
    if finals:
        finals_sorted = sorted(finals, key=lambda r: r["date"])
        final = finals_sorted[-1]
    return {
        "text": text,
        "n_pages": n_pages,
        "n_inspections": len(rows),
        "first_date": dates[0] if dates else "",
        "last_date": dates[-1] if dates else "",
        "final_date": final["date"] if final else "",
        "final_type": final["inspection_type"] if final else "",
        "final_result": final["result"] if final else "",
        "inspections": rows,
    }


def _package_files() -> dict[str, Path]:
    files = {}
    for p in PACKAGE.iterdir():
        if p.is_file():
            files[p.name] = p
    missing_pdfs = [
        "217-21-003723-STR__PRN1_Addition_Structural_GenYard_ChillerPad_Final.pdf",
        "217-21-003727-ELEC__PRN1_Addition_Electrical_MV_Substation_UPS_PDU_Transformer_Final.pdf",
        "217-21-003731-PLM__PRN1_Addition_Plumbing_WaterService_Sewer_Backflow_Final.pdf",
        "217-21-003734-MECH__PRN1_Addition_Mechanical_ChilledWater_CRAH_Chiller_Final.pdf",
        "217-24-000066-MECH__PRN1_Chiller_Addition_Operational_Final_2024.pdf",
        "217-22-000286-ELEC__PRN1_Phase2_Electrical_DataHalls_MSB_RPP_2024-2026.pdf",
        "217-22-000289-MECH__PRN1_Retrofit_Fans_CRAC_Refrigerant_2024-2026_Final.pdf",
        "217-21-003727-ELEC__Record_Detail_Area_Amperage_Circuit_Counts.png",
        "217-21-003734-MECH__Record_Detail_Area_Heating_Cooling_for_IT.png",
        "217-21-003731-PLM__Record_Detail_Area_Plumbing_Footage_Revision.png",
        "area_reconciliation.csv",
        "manifest.csv",
        "README.txt",
    ]
    for name in missing_pdfs:
        if name not in files:
            raise FileNotFoundError(f"Missing local permit package file: {PACKAGE / name}")
    return files


def _area_table() -> pd.DataFrame:
    z = pd.read_csv(PACKAGE / "area_reconciliation.csv")
    values = (
        z["stated_area_number"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .pipe(pd.to_numeric, errors="coerce")
        .dropna()
        .astype(int)
        .tolist()
    )
    if sorted(values) != [AREA_LOW, 82723, AREA_HIGH]:
        raise ValueError(f"Unexpected area_reconciliation values: {values}")
    return z


def _quality_note(extra: str) -> str:
    return (
        f"provenance_class={PROVENANCE}. Source package data/raw/prineville_strictly_valuable_permits_v2/. "
        "Do not convert amp/circuit counts to MW. Do not convert pipe diameter to consumption. "
        "PRN1 addition area is an unresolved ~82.7k-ft² range (82,273 / 82,723 / 82,736); "
        "exact_final_area is missing. Evidence is PRN1-scoped; not campus-wide cooling architecture, "
        "WUE, cooling-tower type, or IT MW. Not used to retune gray-box or 2023–2024 water holdout. "
        + extra
    )


def _evidence_rows(parsed: dict[str, dict]) -> list[dict]:
    str_p = parsed["217-21-003723-STR"]
    elec_p = parsed["217-21-003727-ELEC"]
    plm_p = parsed["217-21-003731-PLM"]
    mech_p = parsed["217-21-003734-MECH"]
    chiller_p = parsed["217-24-000066-MECH"]
    p2_p = parsed["217-22-000286-ELEC"]
    retro_p = parsed["217-22-000289-MECH"]
    common = {
        "address": ADDRESS,
        "parcel": PARCEL,
        "owner": "VITESSE LLC, 1 HACKER WAY, MENLO PARK, CA, 94025-1456",
        "opened_date": "",
        "opened_date_is_issue_proxy": 0,
        "expiration_date": "",
        "sqft": "",
        "electrical_capacity_mw_if_stated": "",
    }
    rows = [
        {
            **common,
            "permit_id": "217-21-003723-STR",
            "source_filename": "217-21-003723-STR__PRN1_Addition_Structural_GenYard_ChillerPad_Final.pdf",
            "building_id": "prn1_addition",
            "project_scope": "PRN1 addition structural: gen-yard/cable-bus/equipment foundations and chiller housekeeping pad",
            "permit_type": "Commercial Structural",
            "record_status": "Finaled",
            "applicant": "Environmental Systems Design",
            "final_or_co_date": str_p["final_date"],
            "final_event_type": str_p["final_type"],
            "final_result": str_p["final_result"],
            "model_use": "prn1_addition_commissioning_anchor",
            "relevance": "high",
            "inspection_count": str_p["n_inspections"],
            "inspection_first_date": str_p["first_date"],
            "inspection_last_date": str_p["last_date"],
            "key_milestones": f"Final Building approved {str_p['final_date']}; gen-yard/cable-bus foundations; chiller housekeeping pad.",
            "electrical_or_power_evidence": "Gen-yard/cable-bus/equipment foundations; no MW stated.",
            "cooling_system_description": "Chiller housekeeping pad at PRN1; heat-rejection type not stated.",
            "water_or_plumbing_evidence": "",
            "source_record": "Crook County Inspection Summary Report PDF in prineville_strictly_valuable_permits_v2: 217-21-003723-STR__PRN1_Addition_Structural_GenYard_ChillerPad_Final.pdf",
            "quality_note": _quality_note("Final Building 2024-02-20."),
        },
        {
            **common,
            "permit_id": "217-21-003727-ELEC",
            "source_filename": "217-21-003727-ELEC__PRN1_Addition_Electrical_MV_Substation_UPS_PDU_Transformer_Final.pdf",
            "building_id": "prn1_addition",
            "project_scope": "PRN1 addition electrical: MV/substation, UPS, PDU, MSB, transformer, rack busbars",
            "permit_type": "Commercial Electrical",
            "record_status": "Finaled",
            "applicant": "Hays, Scott",
            "final_or_co_date": elec_p["final_date"],
            "final_event_type": elec_p["final_type"],
            "final_result": elec_p["final_result"],
            "model_use": "prn1_addition_electrical_architecture",
            "relevance": "very_high",
            "inspection_count": elec_p["n_inspections"],
            "inspection_first_date": elec_p["first_date"],
            "inspection_last_date": elec_p["last_date"],
            "key_milestones": (
                f"Final Electrical approved {elec_p['final_date']}; "
                "record-detail screenshot reports 2×200 A, 93×400 A, 43×600 A, 37×>1000 A, 422 branch circuits."
            ),
            "electrical_or_power_evidence": (
                "MV/substation, UPS, PDU, MSB, transformer, rack busbars. "
                "Record detail: 2×200 A; 93×400 A; 43×600 A; 37×>1000 A; 422 branch circuits. "
                "electrical_capacity_mw = missing. Do not sum current ratings to MW."
            ),
            "cooling_system_description": "CRAH galleries referenced in electrical inspections; not a cooling-capacity rating.",
            "water_or_plumbing_evidence": "",
            "source_record": (
                "Crook County Inspection Summary Report PDF plus record-detail screenshot in "
                "prineville_strictly_valuable_permits_v2: "
                "217-21-003727-ELEC__PRN1_Addition_Electrical_MV_Substation_UPS_PDU_Transformer_Final.pdf; "
                "217-21-003727-ELEC__Record_Detail_Area_Amperage_Circuit_Counts.png"
            ),
            "quality_note": _quality_note("Final Electrical 2024-02-13. Area 82,273 is one of three conflicting trade values."),
        },
        {
            **common,
            "permit_id": "217-21-003731-PLM",
            "source_filename": "217-21-003731-PLM__PRN1_Addition_Plumbing_WaterService_Sewer_Backflow_Final.pdf",
            "building_id": "prn1_addition",
            "project_scope": "PRN1 addition plumbing: domestic-water service/meter, sanitary sewer, backflow in filter/mechanical rooms",
            "permit_type": "Commercial Plumbing",
            "record_status": "Finaled",
            "applicant": "Hays, Scott",
            "final_or_co_date": plm_p["final_date"],
            "final_event_type": plm_p["final_type"],
            "final_result": plm_p["final_result"],
            "model_use": "prn1_addition_plumbing_topology",
            "relevance": "high",
            "inspection_count": plm_p["n_inspections"],
            "inspection_first_date": plm_p["first_date"],
            "inspection_last_date": plm_p["last_date"],
            "key_milestones": (
                f"Final Plumbing approved {plm_p['final_date']}; "
                "record detail reports 82,723 area-like value and 2022-12-23 footage/fixture revision."
            ),
            "electrical_or_power_evidence": "",
            "cooling_system_description": "Mechanical/filter-room plumbing/backflow; not cooling-water consumption.",
            "water_or_plumbing_evidence": (
                "4-in domestic water service/meter; 6-in sanitary sewer; backflows in filter/mechanical rooms. "
                "Pipe diameter is topology evidence only, not consumption."
            ),
            "source_record": (
                "Crook County Inspection Summary Report PDF plus record-detail screenshot in "
                "prineville_strictly_valuable_permits_v2: "
                "217-21-003731-PLM__PRN1_Addition_Plumbing_WaterService_Sewer_Backflow_Final.pdf; "
                "217-21-003731-PLM__Record_Detail_Area_Plumbing_Footage_Revision.png"
            ),
            "quality_note": _quality_note("Final Plumbing 2024-02-22. Area 82,723 is one of three conflicting trade values."),
        },
        {
            **common,
            "permit_id": "217-21-003734-MECH",
            "source_filename": "217-21-003734-MECH__PRN1_Addition_Mechanical_ChilledWater_CRAH_Chiller_Final.pdf",
            "building_id": "prn1_addition",
            "project_scope": "PRN1 addition mechanical: heating/cooling for personnel and IT; chilled-water, CRAH, chiller",
            "permit_type": "Commercial Mechanical",
            "record_status": "Finaled",
            "applicant": "TEMP CONTROL MECHANICAL CORPORATION",
            "final_or_co_date": mech_p["final_date"],
            "final_event_type": mech_p["final_type"],
            "final_result": mech_p["final_result"],
            "model_use": "prn1_addition_cooling_architecture_epoch",
            "relevance": "very_high",
            "inspection_count": mech_p["n_inspections"],
            "inspection_first_date": mech_p["first_date"],
            "inspection_last_date": mech_p["last_date"],
            "key_milestones": (
                "Chilled-water hydronic test 2023-09-21 (CRAH/chiller connections not yet final); "
                "final walk before TCO 2023-12-11; "
                f"Final Mechanical approved {mech_p['final_date']}."
            ),
            "electrical_or_power_evidence": "",
            "cooling_system_description": (
                "Explicit heating/cooling for personnel and IT. Chilled-water system, CRAH connections, "
                "chiller infrastructure. PRN1 addition only. Heat-rejection type, cooling-tower use, "
                "cooling-water consumption, and WUE are not stated."
            ),
            "water_or_plumbing_evidence": "Hydronic chilled-water piping tests; not a consumption series.",
            "source_record": (
                "Crook County Inspection Summary Report PDF plus record-detail screenshot in "
                "prineville_strictly_valuable_permits_v2: "
                "217-21-003734-MECH__PRN1_Addition_Mechanical_ChilledWater_CRAH_Chiller_Final.pdf; "
                "217-21-003734-MECH__Record_Detail_Area_Heating_Cooling_for_IT.png"
            ),
            "quality_note": _quality_note(
                "Final Mechanical 2024-02-13. Area 82,736 is one of three conflicting trade values. "
                "Late-2023 commissioning/testing → early-2024 post-addition PRN1 state. "
                "Not used as a gray-box cooling-regime breakpoint."
            ),
        },
        {
            **common,
            "permit_id": "217-24-000066-MECH",
            "source_filename": "217-24-000066-MECH__PRN1_Chiller_Addition_Operational_Final_2024.pdf",
            "building_id": "prn1_chiller_addition",
            "project_scope": "Additional chiller added to PRN1; inspector recorded unit operational 2024-02-02",
            "permit_type": "Commercial Mechanical",
            "record_status": "Finaled",
            "applicant": "Sorenson, Aaron",
            "owner": "VITESSE LLC, 1601 WILLOW RD, MENLO PARK, CA, 94025",
            "final_or_co_date": chiller_p["final_date"],
            "final_event_type": chiller_p["final_type"],
            "final_result": chiller_p["final_result"],
            "model_use": "prn1_2024_technology_change_event",
            "relevance": "very_high",
            "inspection_count": chiller_p["n_inspections"],
            "inspection_first_date": chiller_p["first_date"],
            "inspection_last_date": chiller_p["last_date"],
            "key_milestones": "Chiller operational 2024-02-02; Final Mechanical for roof chiller 2024-02-13.",
            "electrical_or_power_evidence": "",
            "cooling_system_description": (
                "Additional chiller on roof of PRN1 recorded operational 2024-02-02. "
                "Heat-rejection type and capacity not stated."
            ),
            "water_or_plumbing_evidence": "",
            "source_record": "Crook County Inspection Summary Report PDF in prineville_strictly_valuable_permits_v2: 217-24-000066-MECH__PRN1_Chiller_Addition_Operational_Final_2024.pdf",
            "quality_note": _quality_note("High-confidence 2024 PRN1 chiller operational event. Not used to retune holdout water."),
        },
        {
            **common,
            "permit_id": "217-22-000286-ELEC",
            "source_filename": "217-22-000286-ELEC__PRN1_Phase2_Electrical_DataHalls_MSB_RPP_2024-2026.pdf",
            "building_id": "prn1_phase2_electrical",
            "project_scope": "PRN1 Phase 2 data-hall electrical rough-ins; later MSB/RPP; final pending in this report",
            "permit_type": "Commercial Electrical",
            "record_status": "Final pending",
            "applicant": "ROSENDIN ELECTRIC INC",
            "final_or_co_date": "",
            "final_event_type": "4999 Final Electrical",
            "final_result": "Pending",
            "model_use": "prn1_phase2_ongoing_flag",
            "relevance": "high",
            "inspection_count": p2_p["n_inspections"],
            "inspection_first_date": p2_p["first_date"],
            "inspection_last_date": p2_p["last_date"],
            "key_milestones": "2024 data-hall/ER/penthouse conduit rough-ins approved; Final Electrical pending. Do not backcast 2025-26 equipment.",
            "electrical_or_power_evidence": "Phase 2 data-hall electrical rough-ins; MSB/RPP referenced in later work. No MW stated.",
            "cooling_system_description": "",
            "water_or_plumbing_evidence": "",
            "source_record": "Crook County Inspection Summary Report PDF in prineville_strictly_valuable_permits_v2: 217-22-000286-ELEC__PRN1_Phase2_Electrical_DataHalls_MSB_RPP_2024-2026.pdf",
            "quality_note": _quality_note("Final still pending. Flag 2024 as ongoing Phase 2; do not backcast later equipment."),
        },
        {
            **common,
            "permit_id": "217-22-000289-MECH",
            "source_filename": "217-22-000289-MECH__PRN1_Retrofit_Fans_CRAC_Refrigerant_2024-2026_Final.pdf",
            "building_id": "prn1_retrofit_fans_crac",
            "project_scope": "PRN1 exhaust/transfer-fan and penthouse work (2024); CRAC/refrigerant work mainly 2025-26",
            "permit_type": "Commercial Mechanical",
            "record_status": "Finaled",
            "applicant": "SOUTHLAND INDUSTRIES, INC.",
            "final_or_co_date": retro_p["final_date"],
            "final_event_type": retro_p["final_type"],
            "final_result": retro_p["final_result"],
            "model_use": "prn1_retrofit_chronology_do_not_backcast",
            "relevance": "high",
            "inspection_count": retro_p["n_inspections"],
            "inspection_first_date": retro_p["first_date"],
            "inspection_last_date": retro_p["last_date"],
            "key_milestones": f"2024 exhaust/transfer-fan and penthouse work; 2025 CRAC/refrigerant work; Final Mechanical {retro_p['final_date']}.",
            "electrical_or_power_evidence": "",
            "cooling_system_description": "Exhaust/transfer fans (2024) and later CRAC/refrigerant work (2025-26). Do not backcast CRAC state onto 2023–2024.",
            "water_or_plumbing_evidence": "",
            "source_record": "Crook County Inspection Summary Report PDF in prineville_strictly_valuable_permits_v2: 217-22-000289-MECH__PRN1_Retrofit_Fans_CRAC_Refrigerant_2024-2026_Final.pdf",
            "quality_note": _quality_note("CRAC state is mainly 2025-26. Do not backcast onto the 2023–2024 holdout."),
        },
    ]
    return rows


def _event_rows() -> list[dict]:
    return [
        {
            "date": "2022-12-23",
            "date_precision": "day",
            "event_type": "plumbing_revision",
            "event": "PRN1 addition plumbing record revised to add footage and fixtures; one of three ~82.7k area-like trade values (82,723).",
            "source_id": "217-21-003731-PLM",
            "model_use": "area corroboration only; exact sqft unresolved",
            "confidence": "high",
        },
        {
            "date": "2023-09-21",
            "date_precision": "day",
            "event_type": "mechanical_commissioning_test",
            "event": "PRN1 core chilled-water hydronic test excluding chillers and CRAH units; inspector notes final CRAH/chiller connections to be in-service tested at commissioning.",
            "source_id": "217-21-003734-MECH",
            "model_use": "late-2023 PRN1 commissioning evidence; not a gray-box breakpoint",
            "confidence": "high",
        },
        {
            "date": "2023-12-11",
            "date_precision": "day",
            "event_type": "mechanical_pre_tco_walk",
            "event": "PRN1 addition mechanical final walk before TCO recorded.",
            "source_id": "217-21-003734-MECH",
            "model_use": "late-2023 PRN1 commissioning evidence; not a gray-box breakpoint",
            "confidence": "high",
        },
        {
            "date": "2024-02-02",
            "date_precision": "day",
            "event_type": "chiller_operational",
            "event": "Inspector recorded additional chiller added to PRN1 as operational, with final connections made to the unit.",
            "source_id": "217-24-000066-MECH",
            "model_use": "early-2024 PRN1 post-addition technology event; not holdout tuning",
            "confidence": "very_high",
        },
        {
            "date": "2024-02-13",
            "date_precision": "day",
            "event_type": "electrical_final",
            "event": "PRN1 addition received approved Final Electrical (MV/substation/UPS/PDU/transformer/rack busbar scope).",
            "source_id": "217-21-003727-ELEC",
            "model_use": "early-2024 PRN1 post-addition facility state; electrical_capacity_mw missing",
            "confidence": "very_high",
        },
        {
            "date": "2024-02-13",
            "date_precision": "day",
            "event_type": "mechanical_final",
            "event": "PRN1 addition received approved Final Mechanical (chilled-water/CRAH/chiller; heating/cooling for personnel and IT).",
            "source_id": "217-21-003734-MECH",
            "model_use": "early-2024 PRN1 post-addition facility state; not a gray-box breakpoint",
            "confidence": "very_high",
        },
        {
            "date": "2024-02-13",
            "date_precision": "day",
            "event_type": "mechanical_final",
            "event": "Final Mechanical approved for the additional chiller on the roof of PRN1.",
            "source_id": "217-24-000066-MECH",
            "model_use": "early-2024 PRN1 post-addition technology event; not holdout tuning",
            "confidence": "very_high",
        },
        {
            "date": "2024-02-20",
            "date_precision": "day",
            "event_type": "building_final",
            "event": "PRN1 addition received approved Final Building (structural gen-yard/cable-bus/chiller-pad scope).",
            "source_id": "217-21-003723-STR",
            "model_use": "early-2024 PRN1 post-addition facility state",
            "confidence": "very_high",
        },
        {
            "date": "2024-02-22",
            "date_precision": "day",
            "event_type": "plumbing_final",
            "event": "PRN1 addition received approved Final Plumbing (domestic-water service/meter, sanitary sewer, mechanical/filter-room backflow).",
            "source_id": "217-21-003731-PLM",
            "model_use": "early-2024 PRN1 post-addition facility state; pipe size is not consumption",
            "confidence": "very_high",
        },
        {
            "date": "2024-03-14",
            "date_precision": "day",
            "event_type": "phase2_electrical_rough_in",
            "event": "PRN1 Phase 2 electrical rough-in inspections underway (data halls); Final Electrical still pending. Do not backcast later MSB/RPP equipment.",
            "source_id": "217-22-000286-ELEC",
            "model_use": "2024 ongoing Phase 2 flag; not a completed capacity epoch",
            "confidence": "high",
        },
        {
            "date": "2026-08-12",
            "date_precision": "day",
            "event_type": "mechanical_final",
            "event": "PRN1 retrofit fans/CRAC/refrigerant permit received approved Final Mechanical; CRAC state is mainly 2025-26 and must not be backcast onto 2023-2024.",
            "source_id": "217-22-000289-MECH",
            "model_use": "retrofit chronology; do not backcast",
            "confidence": "high",
        },
    ]


def _fact_rows() -> list[dict]:
    base = {
        "scope_building": "PRN1",
        "provenance_class": PROVENANCE,
        "confidence": "high",
    }
    return [
        {
            **base,
            "fact_id": "prn1_addition_area_proxy_ft2",
            "permit_id": "217-21-003727-ELEC;217-21-003731-PLM;217-21-003734-MECH",
            "event_date": "",
            "source_file": (
                "217-21-003727-ELEC__Record_Detail_Area_Amperage_Circuit_Counts.png;"
                "217-21-003731-PLM__Record_Detail_Area_Plumbing_Footage_Revision.png;"
                "217-21-003734-MECH__Record_Detail_Area_Heating_Cooling_for_IT.png;"
                "area_reconciliation.csv"
            ),
            "page_or_screenshot": "record_detail_screenshots; area_reconciliation.csv",
            "evidence_type": "reported_area_range",
            "quantity_name": "addition_area_proxy_ft2",
            "value_low": AREA_LOW,
            "value_high": AREA_HIGH,
            "value_proxy": AREA_PROXY,
            "value_exact": "",
            "unit": "ft2_or_area_like_as_reported",
            "status": "range_unresolved",
            "interpretation_note": (
                "Three trade records report 82,273 / 82,723 / 82,736. Store conservatively as "
                "~82.7k addition_area_proxy_ft2. exact_final_area is missing/unresolved; "
                "parent structural record 217-21-003723-STR does not reconcile a single value."
            ),
        },
        {
            **base,
            "fact_id": "prn1_exact_final_area",
            "permit_id": "217-21-003723-STR;217-21-003727-ELEC;217-21-003731-PLM;217-21-003734-MECH",
            "event_date": "",
            "source_file": "area_reconciliation.csv;README.txt",
            "page_or_screenshot": "package reconciliation rule",
            "evidence_type": "unresolved_quantity",
            "quantity_name": "exact_final_area",
            "value_low": "",
            "value_high": "",
            "value_proxy": "",
            "value_exact": "",
            "unit": "ft2",
            "status": "missing",
            "interpretation_note": "No authoritative structural source in the local package resolves the 82,273 vs 82,723 vs 82,736 discrepancy.",
        },
        {
            **base,
            "fact_id": "prn1_heating_cooling_personnel_and_it",
            "permit_id": "217-21-003734-MECH",
            "event_date": "",
            "source_file": "217-21-003734-MECH__Record_Detail_Area_Heating_Cooling_for_IT.png",
            "page_or_screenshot": "217-21-003734-MECH record detail",
            "evidence_type": "mechanical_scope",
            "quantity_name": "heating_cooling_for_personnel_and_it",
            "value_low": "",
            "value_high": "",
            "value_proxy": "",
            "value_exact": "true",
            "unit": "boolean_documented",
            "status": "documented",
            "interpretation_note": "Explicit PRN1 mechanical scope. Do not infer campus-wide cooling architecture, cooling towers, WUE, or IT MW.",
        },
        {
            **base,
            "fact_id": "prn1_chilled_water_crah_chiller",
            "permit_id": "217-21-003734-MECH",
            "event_date": "2023-09-21",
            "source_file": "217-21-003734-MECH__PRN1_Addition_Mechanical_ChilledWater_CRAH_Chiller_Final.pdf",
            "page_or_screenshot": "page 2 hydronic test / CRAH / chiller comments",
            "evidence_type": "mechanical_scope",
            "quantity_name": "chilled_water_crah_chiller_infrastructure",
            "value_low": "",
            "value_high": "",
            "value_proxy": "",
            "value_exact": "documented",
            "unit": "presence",
            "status": "documented",
            "interpretation_note": "Chilled-water system, CRAH connections, and chiller infrastructure at PRN1. Heat-rejection type not stated.",
        },
        {
            **base,
            "fact_id": "prn1_late_2023_commissioning",
            "permit_id": "217-21-003734-MECH",
            "event_date": "2023-12-11",
            "source_file": "217-21-003734-MECH__PRN1_Addition_Mechanical_ChilledWater_CRAH_Chiller_Final.pdf",
            "page_or_screenshot": "final walk before TCO 2023-12-11; hydronic test 2023-09-21",
            "evidence_type": "commissioning_chronology",
            "quantity_name": "late_2023_commissioning_testing",
            "value_low": "",
            "value_high": "",
            "value_proxy": "",
            "value_exact": "documented",
            "unit": "presence",
            "status": "documented",
            "interpretation_note": "Late-2023 commissioning/testing at PRN1. Not used as a gray-box or water-holdout breakpoint.",
        },
        {
            **base,
            "fact_id": "prn1_additional_chiller_operational_2024_02_02",
            "permit_id": "217-24-000066-MECH",
            "event_date": "2024-02-02",
            "source_file": "217-24-000066-MECH__PRN1_Chiller_Addition_Operational_Final_2024.pdf",
            "page_or_screenshot": "page 1",
            "evidence_type": "commissioning_chronology",
            "quantity_name": "additional_chiller_operational",
            "value_low": "",
            "value_high": "",
            "value_proxy": "",
            "value_exact": "true",
            "unit": "boolean_documented",
            "status": "documented",
            "confidence": "very_high",
            "interpretation_note": "Inspector: chiller added to PRN1 is operational and final connections are made. Capacity/heat-rejection type not stated.",
        },
        {
            **base,
            "fact_id": "prn1_february_2024_finals",
            "permit_id": "217-21-003723-STR;217-21-003727-ELEC;217-21-003731-PLM;217-21-003734-MECH;217-24-000066-MECH",
            "event_date": "2024-02-22",
            "source_file": (
                "217-21-003727-ELEC__PRN1_Addition_Electrical_MV_Substation_UPS_PDU_Transformer_Final.pdf;"
                "217-21-003734-MECH__PRN1_Addition_Mechanical_ChilledWater_CRAH_Chiller_Final.pdf;"
                "217-21-003723-STR__PRN1_Addition_Structural_GenYard_ChillerPad_Final.pdf;"
                "217-21-003731-PLM__PRN1_Addition_Plumbing_WaterService_Sewer_Backflow_Final.pdf"
            ),
            "page_or_screenshot": "approved Final Electrical/Mechanical 2024-02-13; Final Building 2024-02-20; Final Plumbing 2024-02-22",
            "evidence_type": "commissioning_chronology",
            "quantity_name": "february_2024_trade_finals",
            "value_low": "",
            "value_high": "",
            "value_proxy": "",
            "value_exact": "documented",
            "unit": "presence",
            "status": "documented",
            "confidence": "very_high",
            "interpretation_note": "Early-2024 post-addition PRN1 facility state. Interpretation/scenario evidence, not holdout tuning.",
        },
        {
            **base,
            "fact_id": "prn1_branch_n_200a",
            "permit_id": "217-21-003727-ELEC",
            "event_date": "",
            "source_file": "217-21-003727-ELEC__Record_Detail_Area_Amperage_Circuit_Counts.png",
            "page_or_screenshot": "217-21-003727-ELEC record detail",
            "evidence_type": "electrical_distribution_count",
            "quantity_name": "n_circuits_200A",
            "value_low": 2,
            "value_high": 2,
            "value_proxy": 2,
            "value_exact": 2,
            "unit": "count",
            "status": "documented",
            "interpretation_note": "Do not sum current ratings or convert to MW.",
        },
        {
            **base,
            "fact_id": "prn1_branch_n_400a",
            "permit_id": "217-21-003727-ELEC",
            "event_date": "",
            "source_file": "217-21-003727-ELEC__Record_Detail_Area_Amperage_Circuit_Counts.png",
            "page_or_screenshot": "217-21-003727-ELEC record detail",
            "evidence_type": "electrical_distribution_count",
            "quantity_name": "n_circuits_400A",
            "value_low": 93,
            "value_high": 93,
            "value_proxy": 93,
            "value_exact": 93,
            "unit": "count",
            "status": "documented",
            "interpretation_note": "Do not sum current ratings or convert to MW.",
        },
        {
            **base,
            "fact_id": "prn1_branch_n_600a",
            "permit_id": "217-21-003727-ELEC",
            "event_date": "",
            "source_file": "217-21-003727-ELEC__Record_Detail_Area_Amperage_Circuit_Counts.png",
            "page_or_screenshot": "217-21-003727-ELEC record detail",
            "evidence_type": "electrical_distribution_count",
            "quantity_name": "n_circuits_600A",
            "value_low": 43,
            "value_high": 43,
            "value_proxy": 43,
            "value_exact": 43,
            "unit": "count",
            "status": "documented",
            "interpretation_note": "Do not sum current ratings or convert to MW.",
        },
        {
            **base,
            "fact_id": "prn1_branch_n_gt_1000a",
            "permit_id": "217-21-003727-ELEC",
            "event_date": "",
            "source_file": "217-21-003727-ELEC__Record_Detail_Area_Amperage_Circuit_Counts.png",
            "page_or_screenshot": "217-21-003727-ELEC record detail",
            "evidence_type": "electrical_distribution_count",
            "quantity_name": "n_circuits_gt_1000A",
            "value_low": 37,
            "value_high": 37,
            "value_proxy": 37,
            "value_exact": 37,
            "unit": "count",
            "status": "documented",
            "interpretation_note": "Do not sum current ratings or convert to MW.",
        },
        {
            **base,
            "fact_id": "prn1_n_branch_circuits",
            "permit_id": "217-21-003727-ELEC",
            "event_date": "",
            "source_file": "217-21-003727-ELEC__Record_Detail_Area_Amperage_Circuit_Counts.png",
            "page_or_screenshot": "217-21-003727-ELEC record detail",
            "evidence_type": "electrical_distribution_count",
            "quantity_name": "n_branch_circuits",
            "value_low": 422,
            "value_high": 422,
            "value_proxy": 422,
            "value_exact": 422,
            "unit": "count",
            "status": "documented",
            "interpretation_note": "Do not convert circuit counts to MW.",
        },
        {
            **base,
            "fact_id": "prn1_electrical_capacity_mw",
            "permit_id": "217-21-003727-ELEC",
            "event_date": "",
            "source_file": "217-21-003727-ELEC__Record_Detail_Area_Amperage_Circuit_Counts.png;217-21-003727-ELEC__PRN1_Addition_Electrical_MV_Substation_UPS_PDU_Transformer_Final.pdf",
            "page_or_screenshot": "inspection summary + record detail",
            "evidence_type": "unresolved_quantity",
            "quantity_name": "electrical_capacity_mw",
            "value_low": "",
            "value_high": "",
            "value_proxy": "",
            "value_exact": "",
            "unit": "MW",
            "status": "missing",
            "interpretation_note": "No load calculation, one-line, or equipment kVA/MW rating is in the local package.",
        },
        {
            **base,
            "fact_id": "prn1_plumbing_topology",
            "permit_id": "217-21-003731-PLM",
            "event_date": "2024-02-22",
            "source_file": "217-21-003731-PLM__PRN1_Addition_Plumbing_WaterService_Sewer_Backflow_Final.pdf",
            "page_or_screenshot": "inspection summary / Final Plumbing",
            "evidence_type": "plumbing_topology",
            "quantity_name": "domestic_water_meter_backflow_sanitary_sewer",
            "value_low": "",
            "value_high": "",
            "value_proxy": "",
            "value_exact": "documented",
            "unit": "presence",
            "status": "documented",
            "interpretation_note": "Domestic-water service, meter/backflow, sanitary sewer, mechanical/filter-room plumbing. Do not convert pipe diameter into water consumption.",
        },
    ]


def _building_rows(parsed: dict[str, dict]) -> list[dict]:
    rows = []
    specs = [
        (
            "prn1_addition",
            "217-21-003723-STR",
            parsed["217-21-003723-STR"],
            "",
            "Chiller housekeeping pad at PRN1; heat-rejection type not stated.",
            "PRN1 addition structural gen-yard/cable-bus/chiller-pad. First inspection date is issue_date proxy because ePermitting Opened date is not in this package. sqft and electrical_capacity_mw_if_stated left blank: area is an unresolved ~82.7k range, not an exact structural value.",
        ),
        (
            "prn1_addition",
            "217-21-003727-ELEC",
            parsed["217-21-003727-ELEC"],
            "",
            "",
            "PRN1 addition electrical architecture. Circuit counts are in the facts table; electrical_capacity_mw_if_stated left blank. Do not convert amps to MW.",
        ),
        (
            "prn1_addition",
            "217-21-003731-PLM",
            parsed["217-21-003731-PLM"],
            "",
            "Mechanical/filter-room plumbing/backflow; pipe size is not consumption.",
            "PRN1 addition plumbing topology only. sqft left blank because exact area is unresolved.",
        ),
        (
            "prn1_addition",
            "217-21-003734-MECH",
            parsed["217-21-003734-MECH"],
            "",
            "PRN1 addition: heating/cooling for personnel and IT; chilled-water, CRAH, chiller. Not campus-wide; not used to retune gray-box.",
            "Late-2023 commissioning → early-2024 post-addition PRN1 state. Not a 2023–2024 water-holdout breakpoint.",
        ),
        (
            "prn1_chiller_addition",
            "217-24-000066-MECH",
            parsed["217-24-000066-MECH"],
            "",
            "Additional PRN1 roof chiller recorded operational 2024-02-02.",
            "High-confidence 2024 technology-change event. Not used to retune water holdout.",
        ),
        (
            "prn1_retrofit_fans_crac",
            "217-22-000289-MECH",
            parsed["217-22-000289-MECH"],
            "",
            "2024 exhaust/transfer fans; CRAC/refrigerant mainly 2025-26. Do not backcast.",
            "Final Mechanical 2026-08-12. Do not backcast CRAC state onto 2023–2024.",
        ),
    ]
    for building_id, permit_id, p, sqft, cooling, extra in specs:
        if not p["final_date"] or not p["first_date"]:
            continue
        rows.append(
            {
                "building_id": building_id,
                "permit_id": permit_id,
                "issue_date": p["first_date"],
                "final_or_co_date": p["final_date"],
                "sqft": sqft,
                "electrical_capacity_mw_if_stated": "",
                "cooling_system_description": cooling,
                "source_record": f"Crook County Inspection Summary Report PDF in prineville_strictly_valuable_permits_v2 (permit {permit_id})",
                "quality_note": _quality_note(extra),
            }
        )
    return rows


def _upsert(existing: pd.DataFrame, new_rows: list[dict], key: str) -> pd.DataFrame:
    new = pd.DataFrame(new_rows)
    new = new.reindex(columns=list(existing.columns))
    keep = existing[~existing[key].astype(str).isin(set(new[key].astype(str)))].copy()
    out = pd.concat([keep, new], ignore_index=True)
    return out


def main() -> None:
    if not PACKAGE.is_dir():
        raise FileNotFoundError(f"Permit package not found: {PACKAGE}")
    files = _package_files()
    _area_table()

    parsed = {}
    pdf_map = {
        "217-21-003723-STR": "217-21-003723-STR__PRN1_Addition_Structural_GenYard_ChillerPad_Final.pdf",
        "217-21-003727-ELEC": "217-21-003727-ELEC__PRN1_Addition_Electrical_MV_Substation_UPS_PDU_Transformer_Final.pdf",
        "217-21-003731-PLM": "217-21-003731-PLM__PRN1_Addition_Plumbing_WaterService_Sewer_Backflow_Final.pdf",
        "217-21-003734-MECH": "217-21-003734-MECH__PRN1_Addition_Mechanical_ChilledWater_CRAH_Chiller_Final.pdf",
        "217-24-000066-MECH": "217-24-000066-MECH__PRN1_Chiller_Addition_Operational_Final_2024.pdf",
        "217-22-000286-ELEC": "217-22-000286-ELEC__PRN1_Phase2_Electrical_DataHalls_MSB_RPP_2024-2026.pdf",
        "217-22-000289-MECH": "217-22-000289-MECH__PRN1_Retrofit_Fans_CRAC_Refrigerant_2024-2026_Final.pdf",
    }
    for pid, fname in pdf_map.items():
        parsed[pid] = parse_inspections(files[fname])

    expected_finals = {
        "217-21-003723-STR": "2024-02-20",
        "217-21-003727-ELEC": "2024-02-13",
        "217-21-003731-PLM": "2024-02-22",
        "217-21-003734-MECH": "2024-02-13",
        "217-24-000066-MECH": "2024-02-13",
        "217-22-000289-MECH": "2026-08-12",
    }
    for pid, day in expected_finals.items():
        if parsed[pid]["final_date"] != day:
            raise AssertionError(f"{pid} expected final {day}, parsed {parsed[pid]['final_date']}")
    if parsed["217-22-000286-ELEC"]["final_date"]:
        raise AssertionError("Phase 2 electrical final should remain pending/unresolved")

    evidence = pd.read_csv(EVIDENCE)
    events = pd.read_csv(EVENTS)
    buildings = pd.read_csv(BUILDINGS)
    evidence = _upsert(evidence, _evidence_rows(parsed), "permit_id")
    buildings = _upsert(buildings, _building_rows(parsed), "permit_id")
    events = events[~events["source_id"].astype(str).isin(PERMIT_ID_SET)].copy()
    events = pd.concat([events, pd.DataFrame(_event_rows())], ignore_index=True)

    FACTS.parent.mkdir(parents=True, exist_ok=True)
    facts = pd.DataFrame(_fact_rows())
    evidence.to_csv(EVIDENCE, index=False)
    events.to_csv(EVENTS, index=False)
    buildings.to_csv(BUILDINGS, index=False)
    facts.to_csv(FACTS, index=False)

    mw_nonnull = int(pd.to_numeric(facts.loc[facts.quantity_name.eq("electrical_capacity_mw"), "value_exact"], errors="coerce").notna().sum())
    if mw_nonnull:
        raise AssertionError("electrical_capacity_mw must remain missing")
    area_exact = facts.loc[facts.quantity_name.eq("exact_final_area"), "status"].iloc[0]
    if area_exact != "missing":
        raise AssertionError("exact_final_area must remain missing")

    print("PASS: PRN1 strictly-valuable permit evidence integrated.")
    print(f"  package: {PACKAGE.relative_to(ROOT)}")
    print(f"  evidence permits now: {len(evidence)}")
    print(f"  chronology events now: {len(events)}")
    print(f"  model-facing buildings now: {len(buildings)}")
    print(f"  facility facts: {FACTS.relative_to(ROOT)} ({len(facts)} rows)")
    print("  addition_area_proxy_ft2 ≈ 82.7k; exact_final_area = missing")
    print("  electrical_capacity_mw = missing (circuit counts not converted)")


if __name__ == "__main__":
    main()
