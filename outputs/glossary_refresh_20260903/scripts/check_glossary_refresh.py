#!/usr/bin/env python3
"""Validate and freeze the advisor-glossary reporting refresh.

This is a reporting-integrity check. It reads canonical/frozen artifacts and
the compiled glossary; it does not run, fit, tune, or promote any model.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "outputs" / "glossary_refresh_20260903"
GLOSSARY = REPO / "main_documents" / "glossary"
TEX = GLOSSARY / "Network_Based_Data_Center_Glossary.tex"
PDF = TEX.with_suffix(".pdf")
LOG = TEX.with_suffix(".log")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def remove_macro_spans(text: str, macro: str) -> str:
    """Remove balanced ``\\macro{...}`` spans, including nested braces."""
    token = "\\" + macro + "{"
    while token in text:
        start = text.index(token)
        i = start + len(token)
        depth = 1
        while i < len(text) and depth:
            if text[i] == "{" and (i == 0 or text[i - 1] != "\\"):
                depth += 1
            elif text[i] == "}" and (i == 0 or text[i - 1] != "\\"):
                depth -= 1
            i += 1
        if depth:
            raise AssertionError(f"unbalanced {token} span")
        text = text[:start] + text[i:]
    return text


def main() -> None:
    checks: list[dict[str, object]] = []

    def check(name: str, condition: bool, detail: str) -> None:
        checks.append({"check": name, "pass": bool(condition), "detail": detail})
        if not condition:
            raise AssertionError(f"{name}: {detail}")

    branch = git("branch", "--show-current")
    head = git("rev-parse", "HEAD")
    origin_main = git("rev-parse", "origin/main")
    status = git("status", "--short").splitlines()
    check("branch", branch == "main", branch)
    check("head_equals_origin_main", head == origin_main, f"HEAD={head}; origin/main={origin_main}")
    master_clean = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "main_documents/master.tex"], cwd=REPO
    ).returncode == 0
    check("master_tex_untouched", master_clean, "git diff --quiet HEAD -- main_documents/master.tex")

    comparison = pd.read_csv(OUT / "REGISTRY_REPRODUCTION_COMPARISON.csv")
    check("registries_byte_identical", comparison.byte_identical.astype(bool).all(), comparison.to_json(orient="records"))
    coverage = json.loads((OUT / "COVERAGE_PROVENANCE_SUMMARY.json").read_text(encoding="utf-8"))
    check("registry_counts", [coverage[k] for k in ["source_count", "quantity_count", "method_model_count"]] == [50, 82, 26], "50 sources; 82 quantities; 26 methods/models")
    check("city_partial_years", coverage["city_service"]["partial_years"] == [2012, 2015, 2026], str(coverage["city_service"]["partial_years"]))
    check("weather_complete", coverage["weather"]["finite_driver_hours"] == coverage["weather"]["unique_local_hours"] == 122736, "122,736/122,736 finite required-driver hours")
    check("groundwater_not_fitted", coverage["pumping_gwis"]["response_model_fitted"] is False, "pumping->groundwater response remains NOT IDENTIFIED")

    city = json.loads((OUT / "CITY_SERVICE_VALIDATION_STATUS.json").read_text(encoding="utf-8"))
    check("city_validation_gate", city["gate"] == "PASS" and city["n"] == 120, f"gate={city['gate']}; n={city['n']}")
    check("seasonal_persistence_wins", city["best_mae_m3"] < city["graybox_mae_m3"], f"{city['best_mae_m3']:.6f} < {city['graybox_mae_m3']:.6f}")
    check("graybox_shape_signal", city["graybox_shape_share_corr"] > 0, f"r={city['graybox_shape_share_corr']:.9f}")

    ext = pd.read_csv(OUT / "tables" / "external_validation_synthesis.csv").set_index("evidence_stream")
    expected_statuses = {
        "M100": "CLOSED / FROZEN; limitations",
        "Frontier": "CLOSED",
        "Lei--Masanet": "PARTIAL / CLOSED; adapter blocked",
        "NLR/ESIF facility overhead": "PARTIAL / CLOSED",
        "Forest City v3": "Qualitative PARTIAL; quantitative NOT VALIDATED",
        "Modern AI IT-power layer": "FROZEN / BOUNDED; node uncertainty",
    }
    check("external_statuses", ext.final_status.to_dict() == expected_statuses, json.dumps(ext.final_status.to_dict(), sort_keys=True))

    junit = ET.parse(OUT / "FOCUSED_TEST_RESULTS.xml").getroot()
    suites = [junit] if junit.tag == "testsuite" else list(junit.findall("testsuite"))
    tests = sum(int(x.attrib.get("tests", 0)) for x in suites)
    failures = sum(int(x.attrib.get("failures", 0)) + int(x.attrib.get("errors", 0)) for x in suites)
    check("focused_tests", tests == 39 and failures == 0, f"{tests} passed; {failures} failures/errors")

    tex = TEX.read_text(encoding="utf-8")
    active = remove_macro_spans(tex, "oldtxt")
    stale_patterns = {
        "Baseline v1": r"Prineville Public-Data Baseline v1",
        "old registry counts": r"\\newcommand\{\\(?:SourceCount|QuantityCount|ModelCount)\}\{\\oldtxt\{(?:44|76|18)\}",
        "no monthly campus meter": r"no monthly campus meter",
        "Masanet still running": r"(?:Masanet|Lei--Masanet).*?(?:currently running|validation running|gate now running)",
        "Frontier QC pending/running": r"Frontier.*?(?:QC pending|correction is running)",
        "conditional Masanet promotion": r"If .*?Masanet.*?passes",
        "modern AI no result": r"modern AI.*?no result yet",
    }
    stale_rows = []
    for label, pattern in stale_patterns.items():
        total_hits = len(re.findall(pattern, tex, flags=re.IGNORECASE | re.DOTALL))
        active_hits = len(re.findall(pattern, active, flags=re.IGNORECASE | re.DOTALL))
        stale_rows.append({"phrase_class": label, "all_source_hits": total_hits, "active_after_oldtxt_removed": active_hits, "disposition": "PASS" if active_hits == 0 else "FAIL"})
    check("stale_language_active_hits", all(r["active_after_oldtxt_removed"] == 0 for r in stale_rows), json.dumps(stale_rows))
    with (OUT / "STALE_LANGUAGE_AUDIT.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=stale_rows[0].keys())
        w.writeheader()
        w.writerows(stale_rows)

    required_active = [
        "Prineville Public-Data Baseline v2",
        "All-source monthly campus withdrawal",
        "not total Meta campus withdrawal",
        "PARTIAL / closed",
        "quantitative transfer is NOT\\_VALIDATED",
        "FROZEN_BOUNDED_WITH_EXPLICIT_NODE_UNCERTAINTY",
        "site-water/source accounting",
        "groundwater response",
        "M_0",
        "M_1",
    ]
    check("required_current_language", all(x in active for x in required_active), "; ".join(required_active))

    log = LOG.read_text(encoding="utf-8")
    check("latex_fatal_free", "Fatal error" not in log and "Undefined control sequence" not in log, "compiled PDF has no fatal/undefined-control error")
    check("latex_crossrefs_resolved", "Label(s) may have changed" not in log and "undefined references" not in log.lower(), "two-pass cross-references resolved")
    overfull = [float(x) for x in re.findall(r"Overfull \\hbox \(([0-9.]+)pt too wide\)", log)]
    page_match = re.search(r"Output written on .*?\((\d+) pages,", log)
    pdf_pages = int(page_match.group(1)) if page_match else 0
    check("latex_overfull_bounded", max(overfull, default=0.0) < 8.0, f"max={max(overfull, default=0.0):.5f} pt")
    check("pdf_page_count_parsed", pdf_pages > 0, f"pages={pdf_pages}")
    check("pdf_present", PDF.exists() and PDF.stat().st_size > 1_000_000, f"{PDF.stat().st_size} bytes")

    protected = {
        REPO / "Meta_Prineville_Oregon_v3" / "outputs" / "pipeline_report" / "figures" / "fig02_observed_ground_truth.png": "2a6fd479c8140158fba9b80c5c465f6868b636a08b5b0cf6e0256a5eb68d2801",
        REPO / "Meta_Prineville_Oregon_v3" / "outputs" / "pipeline_report" / "figures" / "fig03_water_model_accuracy.png": "77d0f8cc43394ad3bd5e9f7724ec216b39451ee87d46af97632aa3b84e9fc36f",
        REPO / "Meta_Prineville_Oregon_v3" / "outputs" / "pipeline_report" / "figures" / "fig_advisor_gwis_estimation_candidates.png": "99960ad6a0e466397bbb065c776c0a76117cdb77e0e7b52ada6d00e91f3a97d6",
    }
    protected_rows = []
    for path, before_hash in protected.items():
        after_hash = sha256(path)
        protected_rows.append({"path": path.relative_to(REPO).as_posix(), "before_sha256": before_hash, "after_sha256": after_hash, "unchanged": before_hash == after_hash})
    check("protected_figures_unchanged", all(r["unchanged"] for r in protected_rows), json.dumps(protected_rows))
    pd.DataFrame(protected_rows).to_csv(OUT / "PROTECTED_FIGURE_HASH_COMPARISON.csv", index=False)

    frozen_paths = [
        REPO / "other_sources" / "m100" / "results" / "suitability_2021_v3_closure" / "final_status.json",
        REPO / "other_sources" / "masanet" / "results" / "followup_v1" / "FRONTIER_CLOSURE_STATUS.json",
        REPO / "other_sources" / "masanet" / "results" / "final_repro_v2" / "FINAL_MASANET_STATUS.json",
        REPO / "other_sources" / "nlr_esif_fullstack" / "facility_overhead" / "analysis" / "FINAL_ESIF_FACILITY_OVERHEAD_STATUS.json",
        REPO / "Meta_Forest_City_North_Carolina_v3" / "outputs" / "FOREST_CITY_V3_FREEZE.json",
        REPO / "other_sources" / "it_power" / "analysis" / "FINAL_IT_POWER_STATUS.json",
    ]
    pd.DataFrame([{"path": p.relative_to(REPO).as_posix(), "sha256": sha256(p)} for p in frozen_paths]).to_csv(OUT / "FROZEN_STATUS_HASHES.csv", index=False)

    artifact_paths = [
        TEX,
        PDF,
        OUT / "figures" / "fig01_data_coverage_provenance.png",
        OUT / "figures" / "fig01_data_coverage_provenance.pdf",
        OUT / "figures" / "fig04_city_service_validation.png",
        OUT / "figures" / "fig04_city_service_validation.pdf",
        OUT / "tables" / "city_service_validation_metrics.csv",
        OUT / "tables" / "city_water_boundary_accounting.csv",
        OUT / "tables" / "city_water_boundary_reconciliation_diagnostic.csv",
        OUT / "tables" / "external_validation_synthesis.csv",
        OUT / "registries" / "data_source_inventory.csv",
        OUT / "registries" / "model_quantity_registry.csv",
        OUT / "registries" / "model_registry.csv",
    ]
    pd.DataFrame([{"path": p.relative_to(REPO).as_posix(), "sha256": sha256(p), "bytes": p.stat().st_size} for p in artifact_paths]).to_csv(OUT / "FINAL_ARTIFACT_HASHES.csv", index=False)

    final = {
        "status": "PASS",
        "reporting_only": True,
        "scientific_models_refit": False,
        "branch": branch,
        "head": head,
        "origin_main": origin_main,
        "git_status_after": status,
        "checks_passed": len(checks),
        "checks_failed": 0,
        "focused_tests_passed": tests,
        "pdf_pages": pdf_pages,
        "tex_sha256": sha256(TEX),
        "pdf_sha256": sha256(PDF),
        "max_overfull_hbox_pt": max(overfull, default=0.0),
    }
    (OUT / "GLOSSARY_REFRESH_FINAL_STATUS.json").write_text(json.dumps(final, indent=2), encoding="utf-8")
    pd.DataFrame(checks).to_csv(OUT / "GLOSSARY_REFRESH_CHECKS.csv", index=False)

    audit = f"""# Advisor glossary refresh audit

Status: **PASS**  
Mode: reporting-only; no scientific model fit, search, tuning, or promotion  
Branch / HEAD / origin-main: `{branch}` / `{head}` / `{origin_main}`

## Canonical registry and coverage state

- 50 Prineville source products, 82 quantities, and 26 methods/models; all three regenerated registries are byte-identical to the canonical outputs.
- Meta annual withdrawal: 11 reported annual values, 2014--2024.
- City WATER-COMM + ADD'L WATER service: 163 observed meter months, 2012-12 through 2026-07; 2012, 2015, and 2026 are partial years. This is an observed customer-service component, not total monthly Meta/campus withdrawal.
- Canonical weather: 122,736 unique local hours, 2011--2024, with KS39 -> KRDM -> bias-adjusted KBDN hierarchy and all required drivers finite.
- OWRD pumping: 1,751 rows across 14 accepted reporting groups, 2009-10 through 2025-09. GWIS: 812 rows, 800 numeric BLS, 796 state-model-eligible. Pumping-to-groundwater response remains NOT IDENTIFIED.
- EIA-930 PACW: 83,320 rows (2015-07 through 2024-12); FERC historical backcast: 70,120 rows (2011-01 through 2019-01). These are regional, not campus, boundaries.
- Registry discrepancy retained explicitly: all-source monthly campus withdrawal is a coverage/reporting concept but not a distinct row in the current 82-row quantity registry; `Q_W_WITH` is annual.

## Frozen City-service validation

- Identical common support: n=120 months across ten complete years within 2014--2024; incomplete 2015 excluded.
- Seasonal persistence: MAE {city['best_mae_m3']:,.1f} m3; RMSE {city['best_rmse_m3']:,.1f} m3.
- Gray-box evaporation candidate: MAE {city['graybox_mae_m3']:,.1f} m3.
- Gray-box normalized seasonal-shape correlation: r={city['graybox_shape_share_corr']:.3f}; observed JJA share range {city['observed_summer_share_range'][0]:.3f}--{city['observed_summer_share_range'][1]:.3f}, gray-box {city['graybox_summer_share_range'][0]:.3f}--{city['graybox_summer_share_range'][1]:.3f}.
- Conclusion reproduced: the strongest simple baseline has lower error; the gray-box retains seasonal-shape signal but overconcentrates water in summer.

## Water-boundary and external-status controls

- Service + bulk is reported only as `diagnostic only -- not an identified campus mass balance`.
- WELL METER FOR SEW vs OWRD direct POD identity remains unresolved; no proximity/name/correlation-based source or master/submeter inference is made.
- Frozen status synthesis: M100 CLOSED/FROZEN; Frontier CLOSED; Lei--Masanet PARTIAL/CLOSED with adapter blocked; ESIF PARTIAL/CLOSED; Forest City qualitative PARTIAL and quantitative NOT VALIDATED; modern AI IT-power exact disposition `FROZEN_BOUNDED_WITH_EXPLICIT_NODE_UNCERTAINTY`.
- Critical path is site-water/source accounting -> groundwater forcing -> groundwater response -> M0-vs-M1 decision replay.

## Document and integrity checks

- Focused canonical tests: {tests} passed.
- LaTeX compiled twice; {pdf_pages}-page PDF; no fatal error, undefined control sequence, unresolved cross-reference, or overfull box >=8 pt.
- Stale active wording audit: PASS. Historical wording remains only in blue-struck `oldtxt` spans.
- Frozen annual ground-truth, protected annual-water holdout, and GWIS candidate-well figures are hash-identical before/after.
- `main_documents/master.tex` is untouched. The pre-existing dirty submodule is preserved.
"""
    (OUT / "GLOSSARY_REFRESH_AUDIT.md").write_text(audit, encoding="utf-8")
    print(json.dumps(final, indent=2))


if __name__ == "__main__":
    main()
