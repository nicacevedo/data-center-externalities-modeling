#!/usr/bin/env python3
"""Extract boundary-relevant quotes from user-supplied PDFs. Quotes only; no invented numbers."""
from __future__ import annotations

from pathlib import Path

from common import WORK_ROOT, atomic_write_json, set_threads, utcnow, sha256_file

PAPER_DIR = WORK_ROOT / "external" / "lei_masanet_2022"
RCR_PREPRINT = PAPER_DIR / "Climate-_and_Technology-Specific_PUE_and_WUE_Predi.pdf"
LEI2025 = PAPER_DIR / "qt1vx545q7.pdf"
KARIMI = PAPER_DIR / "ssrn-5131144.pdf"
FRONTIER_PAPER = WORK_ROOT / "external" / "frontier_paper" / "s41597-024-03913-w.pdf"
LBNL_PDF = (
    WORK_ROOT
    / "external"
    / "lbnl_2024"
    / "lbnl-2024-united-states-data-center-energy-usage-report.pdf"
)


def pdf_text(path: Path, max_pages=None) -> str:
    from pypdf import PdfReader

    r = PdfReader(str(path))
    pages = r.pages if max_pages is None else r.pages[:max_pages]
    return "\n".join((p.extract_text() or "") for p in pages)


def grab(text: str, needle: str, window=450, occurrence=0) -> str:
    tl = text.lower()
    start = 0
    idx = -1
    for _ in range(occurrence + 1):
        idx = tl.find(needle.lower(), start)
        if idx < 0:
            return ""
        start = idx + 1
    return " ".join(text[max(0, idx - 90) : idx + window].split())


def main():
    set_threads()
    t2022 = pdf_text(RCR_PREPRINT)
    t2025 = pdf_text(LEI2025) if LEI2025.exists() else ""
    tkar = pdf_text(KARIMI, max_pages=6) if KARIMI.exists() else ""
    tfr = pdf_text(FRONTIER_PAPER) if FRONTIER_PAPER.exists() else ""
    tlbnl = pdf_text(LBNL_PDF, max_pages=45) if LBNL_PDF.exists() else ""

    out = {
        "timestamp_utc": utcnow(),
        "files": {
            "lei_masanet_2022_preprint": {
                "file": str(RCR_PREPRINT),
                "sha256": sha256_file(RCR_PREPRINT),
            },
            "lei_shehabi_2025": {
                "file": str(LEI2025),
                "sha256": sha256_file(LEI2025) if LEI2025.exists() else None,
            },
            "karimi_2025_ssrn": {
                "file": str(KARIMI),
                "sha256": sha256_file(KARIMI) if KARIMI.exists() else None,
            },
            "frontier_paper": {
                "file": str(FRONTIER_PAPER),
                "sha256": sha256_file(FRONTIER_PAPER) if FRONTIER_PAPER.exists() else None,
            },
            "lbnl_2024": {
                "file": str(LBNL_PDF),
                "sha256": sha256_file(LBNL_PDF) if LBNL_PDF.exists() else None,
            },
        },
        "identity": {
            "manuscript_title_in_pdf": "Climate- and Technology-Specific PUE and WUE Predictions for U.S. Data Centers using a Physics-based Approach",
            "published_title": "Climate- and technology-specific PUE and WUE estimations for U.S. data centers using a hybrid statistical and thermodynamics-based approach",
            "doi": "10.1016/j.resconrec.2022.106323",
            "preprint": "10.21203/rs.3.rs-769999/v1",
            "note": (
                "Supplied 2022 PDF is a Research Square / Word-manuscript version, not the Elsevier typeset article. "
                "Equations and WUE definition are usable; demo.ipynb cites Table B.1; this manuscript stores facility-parameter ranges in Table 3. "
                "qt1vx545q7.pdf is NOT the 2022 paper; it is Lei, Lu, Shehabi, and Masanet 2025 RCR 219 (workload water-use review)."
            ),
        },
        "quotes_2022": {
            "PUE_definition": grab(t2022, "PUE is defined as the dimensionless ratio"),
            "WUE_definition": grab(t2022, "which is defined as the ratio"),
            "WUE_units": grab(t2022, "liters per kilowatt-hour"),
            "eq1_onsite_water": grab(t2022, "on-site water use rate"),
            "ct_terms": grab(t2022, "draw -off water"),
            "cycles_of_concentration": grab(t2022, "cycles of concentration"),
            "latin_hypercube": grab(t2022, "Latin hypercube"),
            "code_appendix": grab(t2022, "github.com/nuoaleon/Data"),
            "table3": grab(t2022, "Table 3 summarizes"),
            "not_indirect_nearby": grab(t2022, "indirect water use of DCs"),
        },
        "model_mapping": {
            "W_use_model": (
                "2022 Eq (1): on-site water use rate = CT(evaporated + windage + draw-off) + adiabatic cooling + space humidification. "
                "This is what upstream WUE normalizes by IT electricity."
            ),
            "W_cons": (
                "NOT a separate 2022 output. Evaporation is a component of on-site use. "
                "2025 later review uses 'onsite water consumption' and 'total onsite water use' in the same WUE-site sentence; "
                "that later wording is not used to override 2022 Eq (1) or the code, which include draw-off."
            ),
            "W_discharge_return": (
                "Draw-off/blowdown is included IN 2022 WUE (on-site use), so WUE is makeup-like, not consumption-only."
            ),
            "W_source_withdrawal": (
                "Paper: onsite water use / The Green Grid WUE (Patterson 2011). Source (groundwater vs municipal vs reused) is NOT identified. "
                "2022 text discusses indirect grid water as out of scope for the reported WUE. "
                "2025 review separately notes consumption-vs-withdrawal as a remaining issue for workload-level analysis."
            ),
            "IT_normalization": "PUE = total electricity / IT electricity; WUE = onsite water / IT electricity. Intensity metrics.",
            "stochastic_in_paper": (
                "Latin hypercube sampling of facility parameters (Table 3 uniform ranges), 50 samples per climate-zone × case for annual results. "
                "Distinct from np.random indoor humidity draws in the code."
            ),
            "demo_vector": (
                "demo.ipynb vector is consistent with an LHS/sample from Table 3 ranges (e.g. windage 0.0029 within 0.005–0.5%), "
                "not a rounded typical-design point."
            ),
        },
        "quotes_2025_lineage_review": {
            "note": "Same-author-lineage; not independent validation of 2022. Used only to record later WUE-site language.",
            "WUE_site": grab(t2025, "WUE-site measures") or grab(t2025, "WUE -site measures"),
            "consumption_not_withdrawal": grab(t2025, "not 24 water withdrawals")
            or grab(t2025, "not water withdrawals"),
            "lei_masanet_2022_citation": grab(t2025, "Lei and Masanet, 2022"),
        },
        "quotes_karimi_independent": {
            "note": "Independent modeling study; qualitative triangulation only; not used to retune coefficients.",
            "abstract_energy_water": grab(tkar, "The air-cooled chillers consume"),
            "highlights": grab(tkar, "Adding pre-cooling"),
        },
        "quotes_frontier": {
            "pue": grab(tfr, "Power Usage Effectiveness") or grab(tfr, "PUE"),
            "coolant": grab(tfr, "ethylene") or grab(tfr, "ethylene-glycol") or grab(tfr, "ethylene glycol"),
            "rho_cp": grab(tfr, "1060") or grab(tfr, "3.5"),
            "waste_heat_formula": grab(tfr, "waste heat") ,
        },
        "quotes_lbnl_2024": {
            "note": "Shared Lei/Masanet authorship lineage; taxonomy only; not statistically independent validation.",
            "cooling_table": grab(tlbnl, "Major Cooling Systems Considered")
            or grab(tlbnl, "Direct expansion systems"),
            "air_cooled": grab(tlbnl, "Air-cooled chillers are widely used"),
            "pue_wue_figure": grab(tlbnl, "Simulated PUE and WUE"),
        },
        "companion_2020": {
            "files": [
                str(PAPER_DIR / "lei2020.pdf"),
                str(PAPER_DIR / "Statistical-analysis-for-predicting-location-specific-data-center-PUE.pdf"),
            ],
            "note": "Byte-identical duplicates of Lei and Masanet, Energy 201 (2020) 117556. Prior PUE-only physics model; WUE paper expands it.",
        },
    }
    atomic_write_json(WORK_ROOT / "results" / "paper_boundary_quotes.json", out)
    print("WROTE paper_boundary_quotes.json")


if __name__ == "__main__":
    main()
