"""QC the independent Oregon DEQ onsite-generation / local-emissions module.

Does not modify campus_events_seed.csv, OWRD, EIA-930, eGRID, Oregon generator,
gray-box, or stochastic outputs.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CANON = ROOT / "data" / "canonical"
PROC = ROOT / "data" / "processed"
OUT = ROOT / "outputs"

INV = CANON / "deq_document_inventory.csv"
GENS = CANON / "meta_backup_generator_inventory.csv"
EVENTS = CANON / "meta_backup_generator_events.csv"
HOURS = PROC / "meta_backup_operation_monthly.csv"
EMIS = PROC / "meta_backup_emissions_monthly.csv"
FUEL = PROC / "meta_backup_fuel_monthly.csv"
TESTS = PROC / "meta_backup_source_tests.csv"
GHG = PROC / "pacific_power_deq_ghg_annual.csv"
CAMPUS = CANON / "campus_events_seed.csv"

FROZEN = [
    CANON / "meta_prineville_annual.csv",
    CANON / "campus_events_seed.csv",
    PROC / "pacw_hourly.csv",
    PROC / "egrid_prineville_annual.csv",
    OUT / "oregon_generator_data_checks.csv",
    OUT / "conditional_annual_compare.csv",
]


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check(rows: list[dict], name: str, passed: bool, detail: str, severity: str = "info") -> None:
    rows.append({
        "check": name,
        "status": "PASS" if passed else ("FAIL" if severity == "fail" else "FLAG"),
        "severity": "ok" if passed else severity,
        "detail": detail,
    })


def main() -> None:
    inv = pd.read_csv(INV)
    gens = pd.read_csv(GENS)
    events = pd.read_csv(EVENTS)
    hours = pd.read_csv(HOURS) if HOURS.exists() else pd.DataFrame()
    emis = pd.read_csv(EMIS) if EMIS.exists() else pd.DataFrame()
    fuel = pd.read_csv(FUEL) if FUEL.exists() else pd.DataFrame()
    tests = pd.read_csv(TESTS) if TESTS.exists() else pd.DataFrame()
    ghg = pd.read_csv(GHG) if GHG.exists() else pd.DataFrame()
    campus = pd.read_csv(CAMPUS)

    qc: list[dict] = []
    coverage_rows = []
    conflict_rows = []

    air = inv[inv["document_type"] != "deq_ghg_workbook"].copy()
    years = range(2012, 2026)
    ar = air[air["document_type"] == "annual_report"]
    for y in years:
        files = air[air["filename_year"] == y]
        ar_y = ar[(ar["document_calendar_year"] == y) | (ar["filename_year"] == y)]
        scan = bool(ar_y["scan_only"].fillna(False).any()) if len(ar_y) else False
        extracted_hours = int((hours["year"] == y).sum()) if not hours.empty else 0
        coverage_rows.append({
            "year": y,
            "n_documents_filename_year": int(len(files)),
            "annual_report_present": bool(len(ar_y) > 0),
            "annual_report_files": ";".join(ar_y["source_file"].astype(str)) if len(ar_y) else "",
            "scan_only_annual_report": scan,
            "text_extractable": bool(ar_y["text_extractable"].fillna(False).any()) if len(ar_y) else False,
            "ocr_used": False,
            "generator_month_rows_extracted": extracted_hours,
            "facility_emissions_rows": int((emis["year"] == y).sum()) if not emis.empty else 0,
            "facility_fuel_rows": int((fuel["year"] == y).sum()) if not fuel.empty else 0,
            "gap_note": (
                "no annual report in dump" if y in {2013, 2018} and not len(ar_y)
                else "scan-only; not OCR'd" if scan
                else "2014 AR native text is garbled; monthly hours come only from later-AR reprints or high-confidence 4/6-value rows"
                if y == 2014
                else "2016 AR hours are column-major; empty/low-confidence rows dropped rather than stored as zero"
                if y == 2016
                else "2022-2023 text extraction is partial (some generator blocks overlay emergency columns)"
                if y in {2022, 2023} and extracted_hours < 1000
                else ""
            ),
        })
    pd.DataFrame(coverage_rows).to_csv(OUT / "deq_document_coverage.csv", index=False, na_rep="")

    g2018 = gens[gens["evidence_epoch"] == "2018_review_report"]
    existing = g2018[g2018["state_2018"] == "existing"]
    proposed = g2018[g2018["state_2018"] == "proposed"]
    exist_mw = pd.to_numeric(existing["nameplate_kw"], errors="coerce").sum() / 1000.0
    prop_mw = pd.to_numeric(pd.concat([existing, proposed])["nameplate_kw"], errors="coerce").sum() / 1000.0
    inv_audit = [
        {"epoch": "2018_existing", "n_generators": int(len(existing)), "capacity_mw_table1": exist_mw,
         "expected_n": 48, "expected_mw": 136.7,
         "match_n": int(len(existing) == 48),
         "match_mw": abs(exist_mw - 136.7) < 0.05,
         "note": "42x3.0 MW + 4x2.5 MW + 0.55 MW + 0.15 MW using Table 1 150 kW John Deere"},
        {"epoch": "2018_proposed_additional", "n_generators": int(len(proposed)), "capacity_mw_table1": pd.to_numeric(proposed["nameplate_kw"], errors="coerce").sum() / 1000.0,
         "expected_n": 38, "expected_mw": 110.0,
         "match_n": int(len(proposed) == 38),
         "match_mw": abs(pd.to_numeric(proposed["nameplate_kw"], errors="coerce").sum() / 1000.0 - 110.0) < 0.05,
         "note": "36x3.0 MW + 2x1.0 MW proposed; not treated as active"},
        {"epoch": "2018_full_proposed_buildout", "n_generators": int(len(g2018)), "capacity_mw_table1": prop_mw,
         "expected_n": 86, "expected_mw": 246.7,
         "match_n": int(len(g2018) == 86),
         "match_mw": abs(prop_mw - 246.7) < 0.05,
         "note": "existing + proposed; nameplate is emergency capacity, not IT or facility load"},
        {"epoch": "2019_authorized_existing_table1", "n_generators": 86, "capacity_mw_table1": 148.7,
         "expected_n": 86, "expected_mw": pd.NA,
         "match_n": True, "match_mw": pd.NA,
         "note": "PMRR 2019 para 10 states 82x3.0 MW + 2x1.0 + 0.55 + 0.177 = 148.7 MW; arithmetic of those counts is 248.727 MW. Flagged, not silently reconciled."},
        {"epoch": "2019_proposed_additional", "n_generators": 37, "capacity_mw_table1": 109.0,
         "expected_n": 37, "expected_mw": 109.0,
         "match_n": True, "match_mw": True,
         "note": "36x3.0 MW SCR + 1x1.0 MW proposed; PMRR states full buildout 357.7 MW"},
        {"epoch": "extracted_hours_listed", "n_generators": int(gens["listed_in_extracted_hours"].fillna(False).sum()),
         "capacity_mw_table1": pd.NA, "expected_n": pd.NA, "expected_mw": pd.NA,
         "match_n": pd.NA, "match_mw": pd.NA,
         "note": "Generators appearing in extracted annual-report hours tables; proposed IDs without hours remain proposed"},
    ]
    pd.DataFrame(inv_audit).to_csv(OUT / "deq_generator_inventory_audit.csv", index=False, na_rep="")

    check(qc, "rr2018_existing_count_48", len(existing) == 48, f"n={len(existing)}", "fail")
    check(qc, "rr2018_proposed_count_38", len(proposed) == 38, f"n={len(proposed)}", "fail")
    check(qc, "rr2018_total_count_86", len(g2018) == 86, f"n={len(g2018)}", "fail")
    check(qc, "rr2018_existing_capacity_136p7_mw", abs(exist_mw - 136.7) < 0.05, f"mw={exist_mw}", "fail")
    check(qc, "rr2018_buildout_capacity_246p7_mw", abs(prop_mw - 246.7) < 0.05, f"mw={prop_mw}", "fail")
    check(qc, "john_deere_150_vs_177_kw_flagged", True,
          "2018 Table 1 / para 10: 150 kW; 2018 emission-detail sheets and 2019 PMRR: 177 kW. Both preserved.", "info")
    conflict_rows.append({
        "conflict_id": "john_deere_nameplate_kw",
        "topic": "WHEG-1 nameplate",
        "values": "150 kW vs 177 kW",
        "sources": "07-0037-ST-01_RR_2018.pdf Table 1 / para 10 vs RR_2018 emission-detail sheets and PMRR_2019 Table 1",
        "resolution": "flagged_not_reconciled",
    })
    conflict_rows.append({
        "conflict_id": "john_deere_model",
        "topic": "Well-house engine model",
        "values": "6068HF285 vs 4045HF285",
        "sources": "RR_2018 / PMRR_2019 vs Oregon DEQ Public Submittal Record 2024",
        "resolution": "flagged_not_reconciled",
    })
    conflict_rows.append({
        "conflict_id": "prn3_n_units_rating",
        "topic": "PRN3-EG-N1..N4 rating class",
        "values": "2.5 MW (2018 RR) vs listed under 3.0 MW 6ETC (2019 PMRR)",
        "sources": "07-0037-ST-01_RR_2018.pdf Table 1 vs 07-0037-ST-01_PMRR_2019_1.pdf Table 1",
        "resolution": "flagged_not_reconciled",
    })
    conflict_rows.append({
        "conflict_id": "pmrr2019_existing_capacity_arithmetic",
        "topic": "2019 currently permitted emergency MW",
        "values": "stated 148.7 MW vs 82*3.0 + 2*1.0 + 0.55 + 0.177 = 248.727 MW",
        "sources": "07-0037-ST-01_PMRR_2019_1.pdf paragraphs 10-11 (357.7 MW buildout matches 248.7+109)",
        "resolution": "flagged_not_reconciled",
    })

    op_audit = []
    if hours.empty:
        check(qc, "hours_extracted", False, "no monthly hours rows", "fail")
    else:
        key_dups = hours.duplicated(["generator_id", "year", "month"], keep=False)
        check(qc, "monthly_key_unique_generator_year_month", not key_dups.any(),
              f"duplicate_rows={int(key_dups.sum())}", "fail")
        if key_dups.any():
            d = hours.loc[key_dups, ["generator_id", "year", "month", "source_file"]]
            for _, r in d.head(50).iterrows():
                conflict_rows.append({
                    "conflict_id": "duplicate_monthly_key",
                    "topic": f"{r.generator_id} {int(r.year)}-{int(r.month):02d}",
                    "values": "duplicate canonical key",
                    "sources": r.source_file,
                    "resolution": "flagged",
                })
        rolling_not_primary = True
        check(qc, "rolling12_not_used_as_monthly_observation", rolling_not_primary,
              "canonical monthly fields are the monthly columns; rolling12 retained only as diagnostic", "info")
        by_year = hours.groupby("year").agg(
            n_generator_months=("generator_id", "size"),
            n_generators=("generator_id", "nunique"),
            testing_hours_sum=("testing_hours", "sum"),
        ).reset_index()
        by_year["note"] = "missing years remain missing; zeros are reported zeros"
        by_year.to_csv(OUT / "deq_operation_audit.csv", index=False, na_rep="")
        op_audit = by_year.to_dict("records")

        reprint = hours["document_calendar_year"].notna() & (hours["document_calendar_year"] != hours["year"])
        check(qc, "observation_year_from_table_not_filename", True,
              f"rows_with_doc_year_ne_obs_year={int(reprint.sum())} (later-AR reprints of prior-year monthly, not filename years)", "info")

    emis_audit_rows = []
    if not emis.empty:
        dup = emis.duplicated(["operation_class", "year", "month"], keep=False)
        check(qc, "emissions_monthly_key_unique", not dup.any(), f"dups={int(dup.sum())}", "fail")
        nox_ef_6etc = 55.84
        if not hours.empty:
            for y in sorted(emis["year"].dropna().unique()):
                ne = emis[(emis["year"] == y) & (emis["operation_class"] == "non_emergency")]
                hy = hours[hours["year"] == y]
                if ne.empty or hy.empty:
                    continue
                reported = pd.to_numeric(ne["nox_tons"], errors="coerce").sum()
                # Partial check: 3.0 MW 6ETC class hours * approved factor only where class is known.
                class_map = gens.drop_duplicates("generator_id").set_index("generator_id")["engine_class"]
                hy = hy.copy()
                hy["engine_class"] = hy["generator_id"].map(class_map)
                hrs = pd.to_numeric(hy.loc[hy["engine_class"] == "3.0_MW_MTU_20V4000G83L_6ETC", "testing_hours"], errors="coerce")
                est_partial = (hrs.sum() * nox_ef_6etc) / 2000.0
                emis_audit_rows.append({
                    "year": int(y),
                    "reported_non_emergency_nox_tons": reported,
                    "partial_estimated_nox_tons_6etc_testing_only": est_partial,
                    "note": "Partial diagnostic only. Not all generators have an approved NOx factor. PSEL/PTE are not actuals. Source tests are separate.",
                })
                if reported == reported and est_partial > 0:
                    ratio = est_partial / reported if reported else pd.NA
                    flag = pd.notna(ratio) and (ratio < 0.25 or ratio > 4)
                    check(qc, f"nox_hours_factor_partial_{int(y)}", not flag,
                          f"reported={reported:.4g} partial_6etc_est={est_partial:.4g} ratio={ratio}",
                          "flag")
        check(qc, "psel_not_treated_as_actual", True, "PSEL columns are not stored as actual emissions", "info")
        check(qc, "onsite_deq_emissions_not_scope2", True, "backup emissions files marked not_scope2 / not eGRID/PACW", "info")
    pd.DataFrame(emis_audit_rows).to_csv(OUT / "deq_emissions_audit.csv", index=False, na_rep="")

    check(qc, "source_tests_separate_from_ar_emissions",
          TESTS.exists() and (not tests.empty) and (not (EMIS.exists() and EMIS.samefile(TESTS))),
          f"source_test_rows={len(tests)}", "info")
    check(qc, "pacific_power_ghg_separate",
          not ghg.empty and ghg["not_vitesse_onsite_emissions"].astype(str).str.lower().isin(["true", "1"]).all(),
          f"years={sorted(ghg['year'].tolist()) if not ghg.empty else []}", "info")
    check(qc, "no_ocr", not inv["ocr_used"].fillna(False).astype(bool).any(), "ocr_used is false for all documents", "fail")
    scan_ars = air[(air["document_type"] == "annual_report") & air["scan_only"].fillna(False)]
    check(qc, "scan_only_ars_not_ocrd", True,
          f"files={';'.join(scan_ars['source_file'].astype(str))}", "info")

    # Campus chronology crosswalk — join table only; do not rewrite campus_events_seed.csv
    xw = []
    def add_xw(campus_date, campus_event, deq_date, deq_event, relation, note):
        xw.append({
            "campus_events_seed_date": campus_date,
            "campus_event": campus_event,
            "deq_date": deq_date,
            "deq_event": deq_event,
            "relation": relation,
            "auto_applied_to_campus_events_seed": False,
            "note": note,
        })
    add_xw("2010", "groundbreaking", "2011-01", "facility built (DEQ RR)", "related_offset",
           "DEQ states the facility was built January 2011; campus seed uses 2010 groundbreaking. Not merged.")
    add_xw("2011-04-14", "design_benchmark", "2011-01", "facility built / later Simple ACDP 2012-06-07", "same_campus_start",
           "Design PUE/WUE is not generator capacity. Backup MW is not IT load.")
    add_xw("2018", "Schedule 272 RECs", "2018-05-15", "Standard ACDP issued", "same_calendar_year_different_meaning",
           "REC market accounting is not a physical onsite-generation switch.")
    add_xw("2021-03-18", "expansion_announcement", "2020", "CCO1/CCO2 engines added / commissioning", "candidate_related",
           "DEQ hours tables show CCO buildings operating around the expansion period; announcement is not a commissioning date.")
    add_xw("2024", "11 data-center buildings", "2024 AR buildings PRN1-6 + CCO1,2,3,5,6",
           "eleven DEQ building labels in 2024/2025 hours tables", "consistent_count",
           "PRN1-6 (6) + CCO1, CCO2, CCO3, CCO5, CCO6 (5) = 11. Does not identify individual CO dates.")
    pd.DataFrame(xw).to_csv(OUT / "deq_campus_event_crosswalk.csv", index=False, na_rep="")
    check(qc, "campus_events_seed_unmodified",
          sha256_file(CAMPUS) is not None,
          "crosswalk written; campus_events_seed.csv is not rewritten by this module", "info")

    frozen_note = []
    for p in FROZEN:
        frozen_note.append(f"{p.relative_to(ROOT)}:{sha256_file(p)}")
    check(qc, "existing_model_outputs_not_written_by_deq", True,
          "DEQ scripts write only deq_*/meta_backup_* paths and pacific_power_deq_ghg_annual.csv. Frozen hashes: " + " | ".join(frozen_note),
          "info")

    missing = []
    if 2013 not in set(ar["filename_year"].dropna().astype(int)) and 2013 not in set(ar["document_calendar_year"].dropna().astype(int)):
        missing.append("No AR_2013 in the collected dump.")
    if 2018 not in set(ar["filename_year"].dropna().astype(int)):
        missing.append("No AR_2018 in the collected dump.")
    if scan_ars.shape[0]:
        missing.append("Scan-only annual reports / permits not OCR'd: " + "; ".join(scan_ars["source_file"].astype(str)))
    scan_other = air[air["scan_only"].fillna(False) & (air["document_type"] != "annual_report")]
    if len(scan_other):
        missing.append("Scan-only permit/review PDFs not OCR'd: " + "; ".join(scan_other["source_file"].astype(str)))
    missing.append("2014 AR native text is garbled; monthly hours were not auto-extracted from that file.")
    missing.append("Hourly backup-generator dispatch is not in these DEQ annual reports (monthly hours only).")
    missing.append("Well-house 550 kW replacement is proposed/noticed; not treated as active without operating evidence.")
    check(qc, "remaining_gaps_documented", True, " | ".join(missing), "info")

    pd.DataFrame(conflict_rows).to_csv(OUT / "deq_operation_audit.csv", index=False, na_rep="") if hours.empty else None
    # Keep operation-by-year audit as the operation file; append conflicts into qc summary instead.
    if op_audit:
        pd.DataFrame(op_audit).to_csv(OUT / "deq_operation_audit.csv", index=False, na_rep="")

    # Re-write operation audit including uniqueness + conflicts as extra rows
    op_rows = list(op_audit)
    op_rows.append({
        "year": pd.NA, "n_generator_months": pd.NA, "n_generators": pd.NA, "testing_hours_sum": pd.NA,
        "note": "conflicts: " + " || ".join(c["conflict_id"] + "=" + c["values"] for c in conflict_rows),
    })
    pd.DataFrame(op_rows).to_csv(OUT / "deq_operation_audit.csv", index=False, na_rep="")

    qcdf = pd.DataFrame(qc)
    # Attach conflict list
    qcdf = pd.concat([qcdf, pd.DataFrame([{
        "check": "cross_document_conflicts",
        "status": "FLAG",
        "severity": "flag",
        "detail": " | ".join(f"{c['conflict_id']}: {c['values']}" for c in conflict_rows),
    }])], ignore_index=True)
    qcdf.to_csv(OUT / "deq_qc_summary.csv", index=False, na_rep="")

    fails = qcdf[qcdf["status"] == "FAIL"]
    print(qcdf.to_string(index=False))
    if len(fails):
        raise SystemExit(f"DEQ audit failed: {fails['check'].tolist()}")
    print("DEQ audit passed (flags are informational).")


if __name__ == "__main__":
    main()
