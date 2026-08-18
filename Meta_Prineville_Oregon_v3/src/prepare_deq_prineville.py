"""Prepare Oregon DEQ Vitesse/Meta Prineville onsite-generation evidence.

Independent of OWRD, EIA-930, eGRID, Oregon CAMPD/EIA, gray-box, and stochastic
logic. Raw files under data/raw/deq_air/ are never modified.

Observation year/month come from table tokens, not filenames. Rolling 12-month
totals are stored only as diagnostics and are never used as monthly operations.
Missing values stay missing. Scan-only pages are not OCR'd.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import fitz
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_AIR = ROOT / "data" / "raw" / "deq_air"
CANON = ROOT / "data" / "canonical"
PROC = ROOT / "data" / "processed"

OUT_INV = CANON / "deq_document_inventory.csv"
OUT_GENS = CANON / "meta_backup_generator_inventory.csv"
OUT_EVENTS = CANON / "meta_backup_generator_events.csv"
OUT_HOURS = PROC / "meta_backup_operation_monthly.csv"
OUT_EMIS = PROC / "meta_backup_emissions_monthly.csv"
OUT_FUEL = PROC / "meta_backup_fuel_monthly.csv"
OUT_TESTS = PROC / "meta_backup_source_tests.csv"

MONTH_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
MONTH_RE = re.compile(
    r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[-\s./]*(\d{2}|20\d{2})$",
    re.I,
)
NUM_RE = re.compile(r"^[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[Ee][+-]?\d+)?$")
BUILDING_RE = re.compile(r"^building:?\s*(.+)$", re.I)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def classify_document(name: str) -> str:
    n = name.upper()
    if "PUBLIC SUBMITTAL" in n:
        return "public_submittal_record"
    if "_ATEI_" in n:
        return "air_toxics_emissions_inventory"
    if "_PMRR_" in n:
        return "permit_modification_review_report"
    if "_PM_" in n:
        return "permit_modification"
    if "_RR_" in n:
        return "review_report"
    if "_AR_" in n or "ANNUAL REPORT" in n:
        return "annual_report"
    if re.search(r"_P_\d{4}", n):
        return "permit"
    return "other"


def filename_year(name: str) -> int | None:
    m = re.search(
        r"(?:_AR_|_RR_|_P_|_PM_|_PMRR_|_ATEI_|RY|Record )(\d{4})",
        name,
        re.I,
    )
    if m:
        return int(m.group(1))
    if "2024 Annual Report" in name:
        return 2024
    return None


def infer_calendar_year(name: str, text: str) -> int | None:
    fy = filename_year(name)
    head = text[:8000]
    # Annual-report observation year is the reporting year in the title/filename,
    # not the submission stamp (the 2012 AR was received in February 2014).
    if classify_document(name) == "annual_report":
        # Filename/title year is the reporting year. Table month tokens remain
        # the observation year/month (a 2012 AR may still contain Jan-13 cells).
        if fy is not None:
            return fy
        for pat in [
            r"RY\s*(20\d{2})",
            r"Calendar Year\s+(20\d{2})",
            r"(20\d{2})\s+ANNUAL REPORT",
        ]:
            m = re.search(pat, head, re.I)
            if m:
                return int(m.group(1))
        return fy
    m = re.search(r"issued on\s+[A-Za-z]+\s+\d+,\s+(20\d{2})", head, re.I)
    if m:
        return int(m.group(1))
    return fy


def parse_number(token: str) -> float | None:
    t = token.strip().replace(",", "")
    t = t.replace(" ", "")
    if t in {"()", "O", "o"}:
        t = "0"
    t = re.sub(r"^[O](?=\d|\.)", "0", t)
    if not NUM_RE.match(t):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def is_number_token(token: str) -> bool:
    return parse_number(token) is not None


def parse_month_token(token: str) -> tuple[int, int] | None:
    t = re.sub(r"\s+", "", token.strip())
    t = t.replace("Oec", "Dec").replace("oec", "Dec")
    m = MONTH_RE.match(t)
    if not m:
        return None
    month = MONTH_ABBR[m.group(1).lower()]
    yy = m.group(2)
    year = int(yy) if len(yy) == 4 else 2000 + int(yy)
    return year, month


def normalize_generator_id(raw: str, building: str | None = None) -> str | None:
    if raw is None:
        return None
    original = re.sub(r"\s+", " ", str(raw).strip())
    if not original:
        return None
    u = original.upper()
    if re.search(r"WELL\s*HOUSE|WHEG|PRNWHE", u):
        return "WHEG-1"
    if re.search(r"STANDBY|4EG-SB|PRN4A\b", u):
        return "PRN4-EG-STANDBY"

    spaced = re.fullmatch(
        r"(PRN\d+|CCO\d+)\s+(R|\d+R|\d+|N\d+|A\d+)",
        u,
    )
    if spaced:
        bldg, unit = spaced.group(1), spaced.group(2)
        if unit == "R":
            unit = "1R"
        elif unit.isdigit():
            unit = f"{int(unit):02d}"
        return f"{bldg}-EG-{unit}"

    s = re.sub(r"\s+", "", u).replace(":", "")
    s = re.sub(r"^PRNL", "PRN1", s)
    s = re.sub(r"^CCOL", "CCO1", s)
    s = re.sub(r"^PRNS(?=EG|-|$)", "PRN5", s)
    s = re.sub(r"^CCOS(?=EG|-|$)", "CCO5", s)

    m = re.fullmatch(r"(\d)EG-?(N?\d+R?|SB|STANDBY|A\d+)", s)
    if m:
        bmap = {"1": "PRN1", "2": "PRN2", "3": "PRN3", "4": "PRN4", "5": "PRN5", "6": "PRN6"}
        bldg = bmap[m.group(1)]
        unit = m.group(2)
        if unit in {"SB", "STANDBY"}:
            return "PRN4-EG-STANDBY"
        if unit.isdigit():
            unit = f"{int(unit):02d}"
        return f"{bldg}-EG-{unit}"

    if s in {"OEG-A1", "PRNOEG-A1", "PRNOEGA1"}:
        return "OEG-A1"
    if s in {"OEG-A2", "PRNOEG-A2", "PRNOEGA2"}:
        return "OEG-A2"
    if s in {"CCO0EG-A1", "CCO0-EG-A1"}:
        return "CCO0-EG-A1"

    m = re.fullmatch(r"(PRN\d+|CCO\d+|CCO0)-?EG-?(.+)", s)
    if m:
        bldg, unit = m.group(1), m.group(2)
        if unit in {"SB", "STANDBY", "STANDBYGENERATOR"}:
            return "PRN4-EG-STANDBY"
        if unit.isdigit():
            unit = f"{int(unit):02d}"
        return f"{bldg}-EG-{unit}"

    m = re.fullmatch(r"EG-?(.+)", s)
    if m and building:
        b = re.sub(r"\s+", "", building.upper())
        b = b.replace("PRNL", "PRN1").replace("CCOL", "CCO1").replace("PRNS", "PRN5").replace("CCOS", "CCO5")
        if b in {"WELL", "WELLHOUSE"}:
            return "WHEG-1"
        return normalize_generator_id(f"{b}EG-{m.group(1)}")
    return None


def valid_generator_id(gid: str | None) -> bool:
    if not gid:
        return False
    return bool(re.fullmatch(
        r"(?:PRN[1-6]|CCO[0-6])-EG-(?:\d{2}|[12]R|N[1-4]|A[12]|STANDBY)|WHEG-1|OEG-A[12]",
        gid,
    ))


def expand_seq(bldg: str, items: list) -> list[str]:
    out = []
    for item in items:
        if isinstance(item, tuple):
            a, b = item
            for i in range(a, b + 1):
                out.append(f"{bldg}-EG-{i:02d}")
        else:
            out.append(f"{bldg}-EG-{item}")
    return out


def prn_block(n: int, include_n: bool = False) -> list[str]:
    items: list = [(1, 3), (5, 10), (12, 14), "1R", "2R"]
    if include_n:
        items = [(1, 3), (5, 10), (12, 14), "N1", "N2", "N3", "N4", "1R", "2R"]
    return expand_seq(f"PRN{n}", items)


def cco_block(n: int) -> list[str]:
    return expand_seq(f"CCO{n}", [(1, 3), (5, 10), (12, 14), "N1", "N2", "N3", "N4", "1R", "2R"])


def inventory_2018() -> list[dict]:
    rows = []
    existing_3d = expand_seq("PRN1", [(1, 12), "1R", "2R"]) + expand_seq("PRN2", [(1, 12), "1R", "2R"])
    existing_6etc = expand_seq("PRN3", [(1, 3), (5, 10), (12, 14), "1R", "2R"])
    existing_25 = [f"PRN3-EG-N{i}" for i in range(1, 5)]
    proposed_6etc = prn_block(5, include_n=True) + prn_block(6, include_n=True)
    assert len(existing_3d) == 28
    assert len(existing_6etc) == 14
    assert len(existing_25) == 4
    assert len(proposed_6etc) == 36

    def add(ids, cls, model, kw, state, permit_prefix):
        for gid in ids:
            unit = gid.split("-EG-")[-1] if "-EG-" in gid else gid
            if gid == "WHEG-1":
                permit_id = "WHEG-1"
            elif gid == "PRN4-EG-STANDBY":
                permit_id = "4EG-SB"
            elif gid.startswith("OEG-"):
                permit_id = gid
            else:
                bnum = gid.split("-")[0].replace("PRN", "").replace("CCO", "")
                permit_id = f"{bnum}EG-{unit}"
            rows.append({
                "generator_id": gid,
                "permit_emission_point_id": permit_id,
                "building": gid.split("-")[0] if gid not in {"WHEG-1", "OEG-A1", "OEG-A2"} else (
                    "Well House" if gid == "WHEG-1" else "OEG"
                ),
                "engine_class": cls,
                "model": model,
                "nameplate_kw": kw,
                "nameplate_kw_alt": 177 if gid == "WHEG-1" else pd.NA,
                "state_2018": state,
                "evidence_epoch": "2018_review_report",
                "source_file": "07-0037-ST-01_RR_2018.pdf",
                "source_table": "Table 1",
                "never_it_capacity": True,
            })

    add(existing_3d, "3.0_MW_MTU_20V4000G83L_3D", "MTU 20V4000G83L 3D (3000-XC6DT2)", 3000, "existing", "1EG")
    add(existing_6etc, "3.0_MW_MTU_20V4000G83L_6ETC", "MTU 20V4000G83L 6ETC (DS3000)", 3000, "existing", "3EG")
    add(existing_25, "2.5_MW_MTU_20V4000G43_6ETC", "MTU 20V4000G43 6ETC (DS2500)", 2500, "existing", "3EG")
    add(["PRN4-EG-STANDBY"], "550_kW_Caterpillar", "Caterpillar", 550, "existing", "4EG")
    add(["WHEG-1"], "John_Deere", "John Deere 6068HF285", 150, "existing", "WHEG")
    add(proposed_6etc, "3.0_MW_MTU_20V4000G83L_6ETC", "MTU 20V4000G83L 6ETC (DS3000)", 3000, "proposed", "5EG")
    add(["OEG-A1", "OEG-A2"], "1.0_MW_MTU_16V2000_G86S", "MTU 16V2000 G86S", 1000, "proposed", "OEG")
    return rows


def inventory_2019_rows() -> list[dict]:
    rows = []
    existing_3d = expand_seq("PRN1", [(1, 12), "1R", "2R"]) + expand_seq("PRN2", [(1, 12), "1R", "2R"])
    existing_6etc = (
        expand_seq("PRN3", [(1, 3), (5, 10), (12, 14), "N1", "N2", "N3", "N4", "1R", "2R"])
        + prn_block(5, include_n=True)
        + prn_block(6, include_n=True)
    )
    proposed_scr = cco_block(1) + cco_block(2)
    assert len(existing_3d) == 28
    assert len(existing_6etc) == 54
    assert len(proposed_scr) == 36

    def add(ids, cls, model, kw, state):
        for gid in ids:
            rows.append({
                "generator_id": gid,
                "permit_emission_point_id": gid.replace("-EG-", "EG-").replace("PRN", "").replace("CCO", "CCO") if False else gid,
                "building": gid.split("-")[0],
                "engine_class": cls,
                "model": model,
                "nameplate_kw": kw,
                "nameplate_kw_alt": pd.NA,
                "state_2018": pd.NA,
                "evidence_epoch": "2019_permit_modification_review",
                "source_file": "07-0037-ST-01_PMRR_2019_1.pdf",
                "source_table": "Table 1",
                "never_it_capacity": True,
                "state_2019": state,
            })

    add(existing_3d, "3.0_MW_MTU_20V4000G83L_3D", "MTU 20V4000G83L 3D (3000-XC6DT2)", 3000, "authorized_existing")
    add(existing_6etc, "3.0_MW_MTU_20V4000G83L_6ETC", "MTU 20V4000G83L 6ETC (DS3000)", 3000, "authorized_existing")
    add(proposed_scr, "3.0_MW_MTU_20V4000G83L_6ETC_SCR", "MTU 20V4000G83L 6ETC with SCR", 3000, "proposed")
    add(["OEG-A1", "OEG-A2"], "1.0_MW_MTU_16V2000_G86S", "MTU 16V2000 G86S", 1000, "authorized_existing")
    add(["CCO0-EG-A1"], "1.0_MW_MTU_16V2000_G86S", "MTU 16V2000 G86S", 1000, "proposed")
    add(["PRN4-EG-STANDBY"], "550_kW_Caterpillar", "Caterpillar", 550, "authorized_existing")
    add(["WHEG-1"], "John_Deere", "John Deere 6068HF285", 177, "authorized_existing")
    for r in rows:
        if r["generator_id"] == "WHEG-1":
            r["nameplate_kw_alt"] = 150
        if r["generator_id"].startswith("PRN3-EG-N"):
            r["nameplate_kw_alt"] = 2500
            r["rating_conflict_note"] = "2018 RR classed PRN3-EG-N1..N4 as 2.5 MW; 2019 PMRR lists them under 3.0 MW 6ETC"
    return rows


def source_test_rows() -> list[dict]:
    common = {
        "source_file": "07-0037-ST-01_RR_2018.pdf",
        "extraction_method": "text_extracted",
        "confidence": "high",
        "units": "lb/hr",
        "record_type": "source_test",
        "not_annual_report_emissions": True,
    }
    tests = [
        ("Table 7", 12, "PRN1-EG-07", "2013-10-01", 90, "NOx", 37.90, 37.20, 36.90, 37.33, 37.90),
        ("Table 7", 12, "PRN1-EG-07", "2013-10-01", 90, "CO", 7.60, 7.50, 7.60, 7.57, 7.60),
        ("Table 8", 13, "PRN1-EG-06", "2015-10-20", 92, "NOx", 35.37, 35.86, 36.57, 35.93, 36.57),
        ("Table 8", 13, "PRN1-EG-06", "2015-10-20", 92, "CO", 9.48, 6.67, 6.91, 7.69, 9.48),
        ("Table 9", 13, "PRN1-EG-06", "2016-09-27", 95, "NOx", 41.17, 37.16, 41.64, 39.99, 41.64),
        ("Table 9", 13, "PRN1-EG-06", "2016-09-27", 95, "CO", 7.50, 7.31, 7.66, 7.49, 7.66),
        ("Table 10", 13, "PRN1-EG-07", "2016-09-27", 93, "NOx", 42.66, 43.54, 44.35, 43.52, 44.35),
        ("Table 10", 13, "PRN1-EG-07", "2016-09-27", 93, "CO", 7.33, 7.39, 7.39, 7.37, 7.39),
        ("Table 11", 13, "PRN3-EG-06", "2017-03-30", 100, "NOx", 46.47, 49.68, 50.76, 48.97, 50.76),
        ("Table 11", 13, "PRN3-EG-06", "2017-03-30", 100, "CO", 6.80, 7.46, 7.66, 7.31, 7.66),
        ("Table 13", 14, "PRN3-EG-N1", "2017-03-30", 99, "NOx", 48.47, 48.55, 50.78, 49.27, 50.78),
        ("Table 13", 14, "PRN3-EG-N1", "2017-03-30", 99, "CO", 2.95, 3.03, 3.23, 3.07, 3.23),
    ]
    rows = []
    for table, page, gid, date, load, pol, r1, r2, r3, avg, mx in tests:
        rows.append({
            **common,
            "table_id": table,
            "page": page,
            "generator_id": gid,
            "test_date": date,
            "engine_load_pct": load,
            "pollutant": pol,
            "run_1": r1,
            "run_2": r2,
            "run_3": r3,
            "average": avg,
            "maximum": mx,
            "approved_factor": pd.NA,
            "approved_factor_note": pd.NA,
        })
    rows.append({
        **common,
        "table_id": "Table 12 / para 44",
        "page": 13,
        "generator_id": pd.NA,
        "test_date": pd.NA,
        "engine_load_pct": pd.NA,
        "pollutant": "NOx",
        "run_1": pd.NA, "run_2": pd.NA, "run_3": pd.NA, "average": pd.NA, "maximum": pd.NA,
        "approved_factor": 55.84,
        "approved_factor_note": "DEQ-approved NOx EF for 3.0 MW MTU 20V4000G83L 6ETC = 110% of max test run (3EG-06)",
        "record_type": "approved_emission_factor",
        "engine_class": "3.0_MW_MTU_20V4000G83L_6ETC",
    })
    rows.append({
        **common,
        "table_id": "Table 14 / para 44",
        "page": 14,
        "generator_id": pd.NA,
        "test_date": pd.NA,
        "engine_load_pct": pd.NA,
        "pollutant": "NOx",
        "run_1": pd.NA, "run_2": pd.NA, "run_3": pd.NA, "average": pd.NA, "maximum": pd.NA,
        "approved_factor": 55.86,
        "approved_factor_note": "DEQ-approved NOx EF for 2.5 MW MTU 20V4000G43 6ETC = 110% of max test run (3EG-N1)",
        "record_type": "approved_emission_factor",
        "engine_class": "2.5_MW_MTU_20V4000G43_6ETC",
    })
    return rows


def interpret_hour_values(nums: list[float], calendar_year: int | None) -> dict:
    out = {
        "testing_hours": pd.NA,
        "emergency_hours": pd.NA,
        "demand_response_hours": pd.NA,
        "testing_hours_rolling12": pd.NA,
        "emergency_hours_rolling12": pd.NA,
        "demand_response_hours_rolling12": pd.NA,
        "n_values_read": len(nums),
    }
    testing_first = calendar_year is not None and calendar_year >= 2020
    if len(nums) >= 6:
        if testing_first:
            out["testing_hours"], out["testing_hours_rolling12"] = nums[0], nums[1]
            out["emergency_hours"], out["emergency_hours_rolling12"] = nums[2], nums[3]
            out["demand_response_hours"], out["demand_response_hours_rolling12"] = nums[4], nums[5]
        else:
            out["emergency_hours"], out["emergency_hours_rolling12"] = nums[0], nums[1]
            out["testing_hours"], out["testing_hours_rolling12"] = nums[2], nums[3]
            out["demand_response_hours"], out["demand_response_hours_rolling12"] = nums[4], nums[5]
    elif len(nums) == 4:
        if testing_first:
            out["testing_hours"], out["testing_hours_rolling12"] = nums[0], nums[1]
            out["emergency_hours"], out["emergency_hours_rolling12"] = nums[2], nums[3]
        else:
            out["emergency_hours"], out["emergency_hours_rolling12"] = nums[0], nums[1]
            out["testing_hours"], out["testing_hours_rolling12"] = nums[2], nums[3]
    elif len(nums) == 2:
        out["testing_hours"], out["testing_hours_rolling12"] = nums[0], nums[1]
    elif len(nums) == 1:
        out["testing_hours"] = nums[0]
    return out


def looks_like_generator_header(line: str) -> str | None:
    s = line.strip()
    if re.match(r"^generator:?\s*", s, re.I):
        return s.split(":", 1)[-1].strip() if ":" in s else s
    gid = normalize_generator_id(s)
    if valid_generator_id(gid):
        return s
    if re.match(r"^(PRN|CCO)\d", s, re.I) and re.search(r"EG", s, re.I):
        return s
    return None


def parse_hours_from_pages(
    pages: list[tuple[int, str]],
    source_file: str,
    document_calendar_year: int | None,
    extraction_method: str = "text_extracted",
) -> list[dict]:
    rows: list[dict] = []
    building = None
    generator = None
    pending_label = None

    def flush_block():
        return

    for page_num, text in pages:
        lines = [ln.strip() for ln in text.splitlines()]
        i = 0
        while i < len(lines):
            line = lines[i]
            if re.search(r"Emissions Summary|Fuel Consumption Summary|Testing and Readines Emission|PSEL\s*=", line, re.I):
                generator = None
                pending_label = None
                i += 1
                continue
            bm = BUILDING_RE.match(line)
            if bm:
                building = bm.group(1).strip().split()[0]
                building = building.replace("PRNl", "PRN1").replace("CCOl", "CCO1")
                i += 1
                continue
            if line.lower().startswith("generator:"):
                pending_label = line.split(":", 1)[1].strip()
                nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
                cand = normalize_generator_id(nxt, building) if nxt else None
                if valid_generator_id(cand):
                    generator = cand
                    i += 2
                    continue
                cand = normalize_generator_id(pending_label, building)
                if valid_generator_id(cand):
                    generator = cand
                i += 1
                continue
            header = looks_like_generator_header(line)
            if header and not MONTH_RE.match(re.sub(r"\s+", "", line)):
                cand = normalize_generator_id(header, building)
                if valid_generator_id(cand):
                    generator = cand
                    i += 1
                    continue

            month_tok = parse_month_token(line)
            if month_tok and generator:
                year, month = month_tok
                nums: list[float] = []
                j = i + 1
                while j < len(lines) and len(nums) < 6:
                    nxt = lines[j].strip()
                    if not nxt:
                        j += 1
                        continue
                    if parse_month_token(nxt) or looks_like_generator_header(nxt) or BUILDING_RE.match(nxt):
                        break
                    if nxt.lower() in {"month", "notes", "page"} or nxt.lower().startswith("table"):
                        break
                    n = parse_number(nxt)
                    if n is None:
                        break
                    nums.append(n)
                    j += 1
                vals = interpret_hour_values(nums, document_calendar_year)
                rows.append({
                    "generator_id": generator,
                    "building": building,
                    "year": year,
                    "month": month,
                    "source_file": source_file,
                    "page": page_num,
                    "document_calendar_year": document_calendar_year,
                    "extraction_method": extraction_method,
                    "confidence": "high" if vals["n_values_read"] in {2, 4, 6} else "low",
                    **vals,
                })
                i = j
                continue
            i += 1
    return rows


def parse_hours_2017_number_stream(pages: list[tuple[int, str]], source_file: str) -> list[dict]:
    """2017 tables list months once, then generator id + 12*(4 or 6) numbers."""
    rows = []
    for page_num, text in pages:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        months = []
        for ln in lines:
            mt = parse_month_token(ln)
            if mt and mt not in months:
                months.append(mt)
            if len(months) >= 12:
                break
        if len(months) < 12:
            continue
        months = months[:12]
        i = 0
        while i < len(lines):
            cand = normalize_generator_id(lines[i], None)
            if not valid_generator_id(cand):
                i += 1
                continue
            nums = []
            j = i + 1
            while j < len(lines) and len(nums) < 72:
                if valid_generator_id(normalize_generator_id(lines[j], None)):
                    break
                n = parse_number(lines[j])
                if n is None:
                    if parse_month_token(lines[j]):
                        j += 1
                        continue
                    break
                nums.append(n)
                j += 1
            width = 6 if len(nums) >= 72 else 4 if len(nums) >= 48 else 0
            if width:
                for k, (year, month) in enumerate(months):
                    chunk = nums[k * width:(k + 1) * width]
                    if len(chunk) < width:
                        break
                    vals = interpret_hour_values(chunk, 2017)
                    rows.append({
                        "generator_id": cand,
                        "building": cand.split("-")[0],
                        "year": year,
                        "month": month,
                        "source_file": source_file,
                        "page": page_num,
                        "document_calendar_year": 2017,
                        "extraction_method": "text_extracted",
                        "confidence": "high",
                        **vals,
                    })
            i = j if j > i else i + 1
    return rows


def parse_facility_summary(pages: list[tuple[int, str]], source_file: str, calendar_year: int | None, kind: str) -> list[dict]:
    rows = []
    want = {
        "non_emergency_emissions": r"Non-Emergency Operations Emissions|Testing and Readines",
        "emergency_emissions": r"Emergency Operations Emissions Summary",
        "fuel": r"Fuel Consumption Summary",
    }[kind]
    active = False
    event_note = None
    for page_num, text in pages:
        if re.search(want, text, re.I):
            active = True
        if not active:
            continue
        lines = [ln.strip() for ln in text.splitlines()]
        i = 0
        while i < len(lines):
            mt = parse_month_token(lines[i])
            if not mt:
                i += 1
                continue
            year, month = mt
            nums = []
            j = i + 1
            extra = None
            while j < len(lines) and len(nums) < 14:
                nxt = lines[j].strip()
                if not nxt:
                    j += 1
                    continue
                if parse_month_token(nxt):
                    break
                if nxt.lower().startswith("maximum") or nxt.lower().startswith("psel") or nxt.lower().startswith("notes"):
                    break
                n = parse_number(nxt)
                if n is None:
                    if kind == "emergency_emissions" and extra is None and re.search(r"outage|emergenc|none", nxt, re.I):
                        extra = nxt
                        j += 1
                        continue
                    break
                nums.append(n)
                j += 1
            if kind == "fuel" and len(nums) >= 2:
                rows.append({
                    "year": year, "month": month, "source_file": source_file, "page": page_num,
                    "document_calendar_year": calendar_year,
                    "fuel_gal": nums[0], "fuel_gal_rolling12": nums[1],
                    "extraction_method": "text_extracted",
                    "scope": "facility_all_emergency_engines",
                    "not_scope2": True,
                })
            elif kind != "fuel" and len(nums) >= 12:
                rec = {
                    "year": year, "month": month, "source_file": source_file, "page": page_num,
                    "document_calendar_year": calendar_year,
                    "operation_class": "non_emergency" if kind == "non_emergency_emissions" else "emergency",
                    "pm_tons": nums[0], "pm_tons_rolling12": nums[1],
                    "so2_tons": nums[2], "so2_tons_rolling12": nums[3],
                    "nox_tons": nums[4], "nox_tons_rolling12": nums[5],
                    "co_tons": nums[6], "co_tons_rolling12": nums[7],
                    "voc_tons": nums[8], "voc_tons_rolling12": nums[9],
                    "co2e_tons": nums[10], "co2e_tons_rolling12": nums[11],
                    "emergency_event_note": extra if kind == "emergency_emissions" else pd.NA,
                    "extraction_method": "text_extracted",
                    "psel_is_not_actual": True,
                    "not_scope2": True,
                    "not_source_test": True,
                    "units": "short_tons",
                }
                rows.append(rec)
            i = j if j > i else i + 1
        if re.search(r"Fuel Consumption Summary", text, re.I) and kind != "fuel":
            active = False
    return rows


def collapse_monthly(df: pd.DataFrame, value_cols: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return df, pd.DataFrame()
    work = df.copy()
    work["pref"] = 2
    same_year = work["document_calendar_year"].notna() & (work["document_calendar_year"] == work["year"])
    work.loc[same_year, "pref"] = 0
    next_year = work["document_calendar_year"].notna() & (work["document_calendar_year"] == work["year"] + 1)
    work.loc[next_year & ~same_year, "pref"] = 1
    work = work.sort_values(["generator_id", "year", "month", "pref", "source_file"])
    conflicts = []
    keep_idx = []
    for key, grp in work.groupby(["generator_id", "year", "month"], dropna=False):
        best_pref = grp["pref"].min()
        cand = grp[grp["pref"] == best_pref]
        keep_idx.append(cand.index[0])
        if len(cand) > 1:
            for col in value_cols:
                vals = cand[col].dropna().unique()
                if len(vals) > 1:
                    conflicts.append({
                        "generator_id": key[0], "year": key[1], "month": key[2],
                        "field": col, "values": ";".join(str(v) for v in vals),
                        "source_files": ";".join(cand["source_file"].astype(str)),
                        "issue": "conflicting_source_vintages",
                    })
                    break
    unique = work.loc[keep_idx].drop(columns=["pref"])
    return unique, pd.DataFrame(conflicts)


def build_events() -> list[dict]:
    return [
        {"date": "2011-01", "date_precision": "month", "event_type": "facility_built",
         "event": "Vitesse Prineville facility built January 2011 (DEQ review reports).",
         "source_file": "07-0037-ST-01_RR_2018.pdf", "page": 3, "generator_id": pd.NA,
         "state": pd.NA, "model_use": "campus_start_onsite_generation_context", "confidence": "high"},
        {"date": "2012-06-07", "date_precision": "day", "event_type": "permit_issued",
         "event": "Simple ACDP issued June 7, 2012.",
         "source_file": "07-0037-ST-01_RR_2018.pdf", "page": 3, "generator_id": pd.NA,
         "state": "authorized", "model_use": "permit_epoch", "confidence": "high"},
        {"date": "2018-05-15", "date_precision": "day", "event_type": "permit_issued",
         "event": "Standard ACDP issued May 15, 2018.",
         "source_file": "07-0037-ST-01_PMRR_2019_1.pdf", "page": 3, "generator_id": pd.NA,
         "state": "authorized", "model_use": "permit_epoch", "confidence": "high"},
        {"date": "2018-06-11", "date_precision": "day", "event_type": "replacement_approved",
         "event": "DEQ approved replacement of four permitted engines (cited in 2019 PMRR).",
         "source_file": "07-0037-ST-01_PMRR_2019_1.pdf", "page": 3, "generator_id": pd.NA,
         "state": "replacement_authorized", "model_use": "inventory_change", "confidence": "high"},
        {"date": "2018-08-24", "date_precision": "day", "event_type": "permit_application",
         "event": "Application 30244: 37 additional emergency generators proposed.",
         "source_file": "07-0037-ST-01_PMRR_2019_1.pdf", "page": 3, "generator_id": pd.NA,
         "state": "proposed", "model_use": "do_not_treat_as_active", "confidence": "high"},
        {"date": "2019-10-10", "date_precision": "day", "event_type": "addition_approved",
         "event": "ODEQ approval referenced for engines later listed as added in the 2020 annual report.",
         "source_file": "07-0037-ST-01_AR_2020.pdf", "page": 2, "generator_id": pd.NA,
         "state": "authorized", "model_use": "inventory_change", "confidence": "medium"},
        {"date": "2020-11-30", "date_precision": "day", "event_type": "permit_issued",
         "event": "Revised ACDP issued November 30, 2020 (2020 AR cover letter).",
         "source_file": "07-0037-ST-01_AR_2020.pdf", "page": 2, "generator_id": pd.NA,
         "state": "authorized", "model_use": "permit_epoch", "confidence": "high"},
        {"date": "2020", "date_precision": "year", "event_type": "commissioning",
         "event": "2020 AR lists CCO1/CCO2 engines added under Condition 6.1.b; engines not yet installed were omitted from hours tables.",
         "source_file": "07-0037-ST-01_AR_2020.pdf", "page": 2, "generator_id": pd.NA,
         "state": "commissioning", "model_use": "active_only_if_listed_in_hours_tables", "confidence": "high"},
        {"date": "2022-12-12", "date_precision": "day", "event_type": "permit_issued",
         "event": "Standard ACDP issued December 12, 2022 (cited by 2024 PMRR).",
         "source_file": "07-0037-ST-01_PMRR_2024_1.pdf", "page": 3, "generator_id": pd.NA,
         "state": "authorized", "model_use": "permit_epoch", "confidence": "high"},
        {"date": "2024-03", "date_precision": "month", "event_type": "retirement",
         "event": "Well House PRNWHE-G1 / WHEG-1 decommissioned March 2024.",
         "source_file": "Oregon DEQ - Public Submittal Record 2024.pdf", "page": 2,
         "generator_id": "WHEG-1", "state": "retired", "model_use": "inventory_change", "confidence": "high"},
        {"date": "2024-03-25", "date_precision": "day", "event_type": "replacement_proposed",
         "event": "Type 1 Notice of Construction to replace 177-kW Well House generator with a 550-kW generator. Replacement is not treated as active without operating evidence.",
         "source_file": "Oregon DEQ - Public Submittal Record 2024.pdf", "page": 2,
         "generator_id": "WHEG-1", "state": "proposed_replacement", "model_use": "do_not_treat_as_active", "confidence": "high"},
        {"date": "2024", "date_precision": "year", "event_type": "commissioning",
         "event": "Public submittal states engines at CCO6 completed commissioning.",
         "source_file": "Oregon DEQ - Public Submittal Record 2024.pdf", "page": 2,
         "generator_id": pd.NA, "state": "commissioning_complete", "model_use": "building_epoch", "confidence": "high"},
        {"date": "2024", "date_precision": "year", "event_type": "permit_modification",
         "event": "2024 simple technical modification: SCR 10% load NOx EF 12.11 lb/hr with 40 min/hr testing cap; renewable diesel ASTM D975 allowed; model typo 16V2000G86S -> 20V4000G94S.",
         "source_file": "07-0037-ST-01_PMRR_2024_1.pdf", "page": 3,
         "generator_id": pd.NA, "state": "authorized", "model_use": "emission_factor_epoch", "confidence": "high"},
    ]


def pdf_inventory() -> tuple[pd.DataFrame, dict[str, list[tuple[int, str]]]]:
    recs = []
    texts: dict[str, list[tuple[int, str]]] = {}
    for path in sorted(RAW_AIR.glob("*.pdf")):
        doc = fitz.open(path)
        page_texts = []
        chars = 0
        for i, page in enumerate(doc):
            t = page.get_text("text") or ""
            page_texts.append((i + 1, t))
            chars += len(t)
        doc.close()
        full = "\n".join(t for _, t in page_texts)
        dtype = classify_document(path.name)
        recs.append({
            "source_file": path.name,
            "relative_path": str(path.relative_to(ROOT)),
            "sha256": sha256_file(path),
            "n_pages": len(page_texts),
            "extractable_chars": chars,
            "text_extractable": chars > 0,
            "scan_only": chars == 0,
            "document_type": dtype,
            "filename_year": filename_year(path.name),
            "document_calendar_year": infer_calendar_year(path.name, full) if chars else filename_year(path.name),
            "permit_number": "07-0037-ST-01",
            "facility_name": "Vitesse, LLC (Meta/Facebook Prineville)",
            "extraction_status": (
                "scan_only_not_ocrd" if chars == 0
                else "text_extractable"
            ),
            "ocr_used": False,
        })
        texts[path.name] = page_texts
    return pd.DataFrame(recs), texts


def keep_hour_row(row: dict) -> bool:
    if not valid_generator_id(row.get("generator_id")):
        return False
    n = int(row.get("n_values_read") or 0)
    if n == 0:
        return False
    doc_year = row.get("document_calendar_year")
    if doc_year is not None and int(doc_year) >= 2020:
        return n in {2, 4, 6} and row.get("confidence") == "high"
    return n in {4, 6}


def hours_for_file(name: str, pages: list[tuple[int, str]], inv_row: pd.Series) -> list[dict]:
    if inv_row["scan_only"] or inv_row["document_type"] != "annual_report":
        return []
    year = inv_row["document_calendar_year"]
    rows: list[dict] = []
    if name == "07-0037-ST-01_AR_2017.pdf":
        rows = parse_hours_2017_number_stream(pages, name)
    if not rows:
        rows = parse_hours_from_pages(pages, name, year)
    return [r for r in rows if keep_hour_row(r)]


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, na_rep="")


def main() -> None:
    if not RAW_AIR.exists():
        raise FileNotFoundError(RAW_AIR)
    inv, texts = pdf_inventory()
    write_csv(inv, OUT_INV)

    hour_rows: list[dict] = []
    emis_rows: list[dict] = []
    fuel_rows: list[dict] = []
    for _, rec in inv.iterrows():
        pages = texts[rec["source_file"]]
        hour_rows.extend(hours_for_file(rec["source_file"], pages, rec))
        if rec["scan_only"] or rec["document_type"] != "annual_report":
            continue
        year = rec["document_calendar_year"]
        # 2012-2016 native layouts are column-jumbled; do not store misaligned
        # PSEL/summary numbers as actual emissions or fuel.
        if pd.notna(year) and int(year) >= 2020:
            emis_rows.extend(parse_facility_summary(pages, rec["source_file"], year, "non_emergency_emissions"))
            emis_rows.extend(parse_facility_summary(pages, rec["source_file"], year, "emergency_emissions"))
            fuel_rows.extend(parse_facility_summary(pages, rec["source_file"], year, "fuel"))

    hours_v = pd.DataFrame(hour_rows)
    if not hours_v.empty:
        hours_unique, _ = collapse_monthly(
            hours_v,
            ["testing_hours", "emergency_hours", "demand_response_hours"],
        )
        hours_unique["total_reported_hours"] = pd.to_numeric(hours_unique["testing_hours"], errors="coerce").fillna(0) * 0
        # Do not convert missing to zero: total is NA unless at least one component is present.
        t = pd.to_numeric(hours_unique["testing_hours"], errors="coerce")
        e = pd.to_numeric(hours_unique["emergency_hours"], errors="coerce")
        d = pd.to_numeric(hours_unique["demand_response_hours"], errors="coerce")
        hours_unique["total_reported_hours"] = t.add(e, fill_value=0).add(d, fill_value=0)
        hours_unique.loc[t.isna() & e.isna() & d.isna(), "total_reported_hours"] = pd.NA
        hours_unique["rolling12_not_used_as_monthly"] = True
        hours_unique["not_it_or_facility_load"] = True
        hours_out = hours_unique.sort_values(["generator_id", "year", "month", "source_file"])
    else:
        hours_out = hours_v
    write_csv(hours_out, OUT_HOURS)

    emis = pd.DataFrame(emis_rows)
    if not emis.empty:
        emis["pref"] = 2
        same = emis["document_calendar_year"].notna() & (emis["document_calendar_year"] == emis["year"])
        emis.loc[same, "pref"] = 0
        emis = emis.sort_values(["operation_class", "year", "month", "pref", "source_file"])
        emis = emis.drop_duplicates(["operation_class", "year", "month"], keep="first").drop(columns=["pref"])
    write_csv(emis, OUT_EMIS)

    fuel = pd.DataFrame(fuel_rows)
    if not fuel.empty:
        fuel["pref"] = 2
        same = fuel["document_calendar_year"].notna() & (fuel["document_calendar_year"] == fuel["year"])
        fuel.loc[same, "pref"] = 0
        fuel = fuel.sort_values(["year", "month", "pref", "source_file"])
        fuel = fuel.drop_duplicates(["year", "month"], keep="first").drop(columns=["pref"])
    write_csv(fuel, OUT_FUEL)

    write_csv(pd.DataFrame(source_test_rows()), OUT_TESTS)

    g2018 = pd.DataFrame(inventory_2018())
    g2019 = pd.DataFrame(inventory_2019_rows())
    listed = set(hours_out["generator_id"].dropna()) if not hours_out.empty else set()
    first_year = (
        hours_out.groupby("generator_id")["year"].min().to_dict() if not hours_out.empty else {}
    )
    last_year = (
        hours_out.groupby("generator_id")["year"].max().to_dict() if not hours_out.empty else {}
    )
    pos_hours = set()
    if not hours_out.empty:
        tot = pd.to_numeric(hours_out["total_reported_hours"], errors="coerce")
        pos_hours = set(hours_out.loc[tot.fillna(0) > 0, "generator_id"])

    base = pd.concat([g2018, g2019], ignore_index=True, sort=False)
    # One canonical row per generator_id, preserving 2018 as inventory backbone.
    canon = g2018.copy()
    extra_ids = sorted((set(g2019["generator_id"]) | listed) - set(canon["generator_id"]))
    extra_rows = []
    g2019_ix = g2019.drop_duplicates("generator_id").set_index("generator_id")
    for gid in extra_ids:
        if gid in g2019_ix.index:
            extra_rows.append({**g2019_ix.loc[gid].to_dict(), "generator_id": gid})
        else:
            extra_rows.append({
                "generator_id": gid,
                "permit_emission_point_id": gid,
                "building": gid.split("-")[0] if gid != "WHEG-1" else "Well House",
                "engine_class": pd.NA,
                "model": pd.NA,
                "nameplate_kw": pd.NA,
                "nameplate_kw_alt": pd.NA,
                "state_2018": "not_in_2018_table",
                "evidence_epoch": "annual_report_hours_table",
                "source_file": pd.NA,
                "source_table": pd.NA,
                "never_it_capacity": True,
            })
    if extra_rows:
        canon = pd.concat([canon, pd.DataFrame(extra_rows)], ignore_index=True, sort=False)

    def latest_state(row):
        gid = row["generator_id"]
        if gid == "WHEG-1":
            return "retired"
        if gid in pos_hours:
            return "active"
        if gid in listed:
            return "installed_listed"
        st2018 = row.get("state_2018")
        if st2018 == "proposed":
            return "proposed"
        st2019 = row.get("state_2019")
        if st2019 == "proposed":
            return "proposed"
        if st2019 == "authorized_existing" or st2018 == "existing":
            return "authorized"
        return "unknown"

    if "state_2019" not in canon.columns:
        canon["state_2019"] = pd.NA
    s2019 = g2019.drop_duplicates("generator_id").set_index("generator_id")["state_2019"]
    canon["state_2019"] = canon["generator_id"].map(s2019)
    canon["first_hours_year"] = canon["generator_id"].map(first_year)
    canon["latest_hours_year"] = canon["generator_id"].map(last_year)
    canon["listed_in_extracted_hours"] = canon["generator_id"].isin(listed)
    canon["latest_state"] = canon.apply(latest_state, axis=1)
    canon["nameplate_is_not_it_or_facility_load"] = True
    canon["proposed_not_assumed_active"] = canon["latest_state"].eq("proposed")
    write_csv(canon.sort_values(["building", "generator_id"]), OUT_GENS)
    write_csv(pd.DataFrame(build_events()), OUT_EVENTS)

    print(f"Wrote {OUT_INV.relative_to(ROOT)} rows={len(inv)}")
    print(f"Wrote {OUT_GENS.relative_to(ROOT)} rows={len(canon)}")
    print(f"Wrote {OUT_EVENTS.relative_to(ROOT)}")
    print(f"Wrote {OUT_HOURS.relative_to(ROOT)} rows={len(hours_out)}")
    print(f"Wrote {OUT_EMIS.relative_to(ROOT)} rows={len(emis)}")
    print(f"Wrote {OUT_FUEL.relative_to(ROOT)} rows={len(fuel)}")
    print(f"Wrote {OUT_TESTS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
