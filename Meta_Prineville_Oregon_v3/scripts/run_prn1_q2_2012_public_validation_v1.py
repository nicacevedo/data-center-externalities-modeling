#!/usr/bin/env python3
"""PRN1 Q2-2012 public cross-layer consistency test.

Uses frozen structural-reference-v1 unchanged. Does not fit water, overwrite
public-proxy-v1, or read Meta annual water.
"""
from __future__ import annotations

import csv
import hashlib
import json
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
sys.path.insert(0, str(ROOT / "src"))

from holdout_guard import HoldoutGuard, PROTECTED_RELATIVE  # noqa: E402
from prineville_graybox import Params, simulate_structural_reference_v1  # noqa: E402
from prineville_structural_v1 import ReturnAirSpec  # noqa: E402

OUT = ROOT / "outputs" / "prn1_q2_2012_public_validation_v1"
SRC_DIR = OUT / "source_audit"
WX = OUT / "weather"
FIG = OUT / "figures"
SOURCES = OUT / "sources"
PROXY_FREEZE = ROOT / "outputs/public_proxy_reconstruction_v1/preoutcome/PUBLIC_PROXY_RECONSTRUCTION_FREEZE.json"
KRDM_CSV = ROOT / "data/processed/weather_krdm_hourly.csv"

EXPECTED = {
    "v1_freeze": "decd095f59cc2249eee66d5b94ad30d30a53555eadbec3358bbb9aa80caaa81d",
    "registry": "1f87a1846aa8254c758ab11e3bd9b6f639e6c64bc551c36bcf8201bd65e78604",
    "graybox": "8275ca5bfc23042e3af19b72f2adb260304ac95d692d0b3ecbcb526b020f0609",
    "structural_v1": "f9649c489196cdc3e617f5b28574334aaaace5a94e7ade5ce461f6da22809a6a",
    "cpu_status": "1f57b210a63d375ce8eff7d5043756ffe6efe04e8a408bf9429bfd10096528d9",
    "h100": "a620d649a932f2388aa2f35bac2730eb75fe1dc74529668de4f30ee814600076",
    "esif_hw": "4e01139dd9365f62824ac00ff944468839e7873e47a5cea3df4714854af1b02c",
    "proxy_freeze_file": "1d88ba5c3429d0978e64e9caea9b7b9d2cfe5287bf3fb3c2afbb5b81b0a699e2",
}
OBSERVED_WUE = 0.22  # L/kWh_IT, PUBLIC_PREVIOUSLY_KNOWN_EXTERNAL_BENCHMARK
R_ITHERM = 0.67
R_OCP = 0.75
SPRAY_EVAP = 0.85
TZ = "America/Los_Angeles"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(args: list[str]) -> str:
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    return (r.stdout or r.stderr or "").strip()


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n")


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})


def dump_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n")


def master_hash(paths: list[Path]) -> tuple[str, dict]:
    hashes = {str(p.relative_to(OUT)): sha256_file(p) for p in paths if p.is_file()}
    blob = json.dumps(hashes, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest(), hashes


def stage0_initial_state() -> dict:
    files = {
        "v1_freeze": ROOT / "outputs/structural_revision_v1/PRINEVILLE_STRUCTURAL_REFERENCE_V1_FREEZE.json",
        "registry": ROOT / "config/prineville_architecture_states.yaml",
        "graybox": ROOT / "src/prineville_graybox.py",
        "structural_v1": ROOT / "src/prineville_structural_v1.py",
        "cpu_status": REPO / "other_sources/nlr_esif_fullstack/analysis/FINAL_KESTREL_CPU_STATUS.json",
        "h100": REPO / "other_sources/nlr_esif_fullstack/genai_h100/manifests/H100_COMPUTE_FINAL_FREEZE.json",
        "esif_hw": REPO / "other_sources/nlr_esif_fullstack/heat_rejection_water/manifests/ESIF_HEAT_WATER_RESULT_FREEZE.json",
        "proxy_freeze": PROXY_FREEZE,
    }
    hashes = {k: sha256_file(p) for k, p in files.items()}
    for k in ("v1_freeze", "registry", "graybox", "structural_v1", "cpu_status", "h100", "esif_hw"):
        if hashes[k] != EXPECTED[k]:
            raise RuntimeError(f"Frozen hash mismatch {k}: {hashes[k]}")
    if hashes["proxy_freeze"] != EXPECTED["proxy_freeze_file"]:
        raise RuntimeError(f"public-proxy freeze file hash changed: {hashes['proxy_freeze']}")
    proxy = json.loads(PROXY_FREEZE.read_text())
    state = {
        "pass": "prn1_q2_2012_public_validation_v1",
        "utc": datetime.now(timezone.utc).isoformat(),
        "branch": git(["rev-parse", "--abbrev-ref", "HEAD"]),
        "HEAD": git(["rev-parse", "HEAD"]),
        "requested_baseline": "1ac460f35ef55f787fe53fcf9e45c5a2d1e7914d",
        "git_status_porcelain": git(["status", "--porcelain"]),
        "hashes": hashes,
        "public_proxy_v1_master_hash": proxy.get("master_hash"),
        "public_proxy_v1_not_overwritten": True,
        "canonical_simulate_remains_production_default": True,
        "structural_reference_v1_role": "PHYSICS_ENGINE_ONLY",
        "no_parameter_fitted": True,
        "protected_paths": [str(ROOT / p) for p in PROTECTED_RELATIVE],
        "classification": "PUBLIC_PREVIOUSLY_KNOWN_EXTERNAL_CROSS_LAYER_CONSISTENCY_TEST",
        "not": ["model_fitting", "campus_reconstruction", "pristine_holdout", "as_operated_BMS_validation"],
    }
    write_json(OUT / "INITIAL_STATE.json", state)
    return state


def stage1_corrections() -> dict:
    corr = {
        "does_not_rewrite_public_proxy_v1_freeze": True,
        "public_proxy_v1_freeze_sha256_at_correction": sha256_file(PROXY_FREEZE),
        "corrections": [
            {
                "id": "A_recirculation_topology",
                "previous_claim": "Two feasible topologies: recapture to product tanks OR hypothetical recapture to RO feed (1.392x vapor).",
                "corrected_claim": "RECIRCULATION_TOPOLOGY = PRODUCT_STORAGE_RETURN_CONFIRMED. Hypothetical RO-feed topology removed from the scientific feasible set.",
                "evidence": (
                    "OCP: recaptured water through micron filter and UV then brought back to the RO water storage tanks. "
                    "ITherm Fig. 8 / Sec. V: recapture via polishing skid UV+micron filter piped back into the RO storage tanks."
                ),
                "scientific_consequence": "Steady-state P = E; F = E/r. Makeup is not E/0.85 and not 1.392 E.",
            },
            {
                "id": "B_RO_recovery",
                "previous_claim": "r=0.75 as OCP operator split (with 1.333 topology A).",
                "corrected_claim": "RO_RECOVERY_SOURCE_STATE = DISCREPANT_{0.67,0.75}. Not a probability distribution. Not replaced by a hard 75%.",
                "evidence": (
                    "ITherm 2012 (Facebook-authored, ~May 2012): RO produces ≈67% purified water from input well water. "
                    "OCP blog 2013-08-07: 75% of water brought into the data center used for cooling; 3 of 4 parts of RO water are product."
                ),
                "scientific_consequence": "Evaluate r=0.67 and r=0.75 separately. Dates, denominators, and metering retrofit differ.",
            },
            {
                "id": "C_Q2_2012_scope",
                "previous_claim": "Campus λ unidentified after 2011; Q2-2012 WUE used as public benchmark without restating building scope in the proxy freeze.",
                "corrected_claim": "Q2_2012_BUILDING_SCOPE = PRN1_ONLY.",
                "evidence": "OCP: Prineville 1; second building WUE available next year when that building is online.",
                "scientific_consequence": "This consistency test is building-specific. Do not generalize to PRN2–6 or CCO.",
            },
            {
                "id": "D_operating_chronology",
                "previous_claim": "LOAD_SHARE_EXTREMA activated PRN2 from 2013 and PRN1–4 from 2014 as active buildings.",
                "corrected_claim": "Ontology CONFIRMED_OPERATING / POSSIBLY_OPERATING / NOT_YET_OPERATING. PRN4 completed 2016 (Southland) is NOT hard-activated in 2014.",
                "evidence": "Southland PRN4 completed 2016. OPUC early-2014 four buildings is campus chronology, not confirmed CO for PRN4.",
                "scientific_consequence": "2014 four-building simplex was a heuristic, not confirmed operations.",
            },
            {
                "id": "E_PRN4_capacity",
                "previous_claim": "phase_sum about 4 MW if 2 plus 2.",
                "corrected_claim": "Phase one: one 2 MW hall. Phase two: '2 MW data halls' plural. Hall count not established. Do not collapse to exactly 4 MW.",
                "evidence": "Southland PRN4 project page wording.",
                "scientific_consequence": "PRN4 MW remains interval-censored, not a point.",
            },
            {
                "id": "F_VoI",
                "previous_claim": "normalized_range_reduction values 1.0 / 0.8 / 0.7 treated as measured reductions.",
                "corrected_claim": "Those numbers were expert-priority placeholders. Campus water has no finite identified baseline envelope, so numeric range reduction was not measured.",
                "evidence": "public-proxy PUBLIC_PROXY_ENVELOPE_STATUS campus_total_meaningfully_bounded=false.",
                "scientific_consequence": "Replace with categorical expected_information_value. Numeric reduction only where a finite public interval exists.",
            },
        ],
    }
    write_json(OUT / "PUBLIC_PROXY_V1_CORRECTIONS.json", corr)
    return corr


def stage2_water_cycle() -> dict:
    rows = [
        {
            "source": "OCP_WATER_PRN1_blog",
            "date": "2013-08-07_reporting_Q2_2012",
            "operator_author": "yes_Facebook_OCP",
            "measurement_period": "Q2_2012",
            "water_source": "outdoor_storage_tanks;_not_named_well_vs_city_in_this_post",
            "RO_recovery": 0.75,
            "spray_evap_fraction": 0.85,
            "recapture_destination": "RO_water_storage_tanks_via_micron_filter_and_UV",
            "WUE_value": 0.22,
            "WUE_numerator_definition": "cooling_water_only_excludes_plumbing_offices;_meter_location_not_named",
            "meter_location": "added_after_BMS_retrofit_UNSPECIFIED_vs_RO_feed_vs_product",
            "confidence": "HIGH_for_0.22_and_recapture_path;_MEDIUM_for_r=0.75_denominator",
            "notes": "3 of 4 parts of RO water are product. 25% blown down. Second building not yet online.",
        },
        {
            "source": "ITherm_2012_Frachtenberg_et_al",
            "date": "2012-05_conference;_written_from_2011_operations",
            "operator_author": "yes_Facebook",
            "measurement_period": "operational_data_collected_thus_far_before_full_year;_PUE_summer_2011",
            "water_source": "primary_on_site_well;_secondary_Prineville_municipal",
            "RO_recovery": 0.67,
            "spray_evap_fraction": 0.85,
            "recapture_destination": "RO_storage_tanks_via_polishing_skid_UV_and_micron_filter",
            "WUE_value": 0.31,
            "WUE_numerator_definition": "estimate_of_WUE_from_operational_data;_more_accurate_after_full_year",
            "meter_location": "NOT_SPECIFIED",
            "confidence": "HIGH_for_67pct_well_water_statement_and_recapture;_MEDIUM_for_0.31_as_estimate",
            "notes": "Fig. 8 water flow. 0.31 is EARLY_OPERATOR_ESTIMATE_CONTEXT not a second independent validation of 0.22.",
        },
        {
            "source": "repo_WUE_boundary_crosswalk",
            "date": "prior_pass",
            "operator_author": "derived",
            "measurement_period": "Q2_2012_OCP",
            "water_source": "utility_or_source_into_outdoor_storage_LIKELY",
            "RO_recovery": 0.75,
            "spray_evap_fraction": 0.85,
            "recapture_destination": "RO_tanks",
            "WUE_value": 0.22,
            "WUE_numerator_definition": "F1_LIKELY_YES_if_makeup_meter_after_retrofit;_F4_reject_UNKNOWN_if_meter_upstream",
            "meter_location": "PARTIAL_UNRESOLVED",
            "confidence": "HIGH_as_crosswalk_of_OCP_not_new_measurement",
            "notes": "Do not import Lei coefficients.",
        },
        {
            "source": "Meta_engineering_2011_Park",
            "date": "2011-04-14",
            "operator_author": "yes",
            "measurement_period": "design",
            "water_source": "unspecified",
            "RO_recovery": "",
            "spray_evap_fraction": "",
            "recapture_destination": "",
            "WUE_value": 0.31,
            "WUE_numerator_definition": "DESIGN_LIMIT_not_meter",
            "meter_location": "n/a",
            "confidence": "HIGH_as_design_not_Q2_meter",
            "notes": "Same 0.31 number later appears as ITherm operational estimate; still not Q2-2012 meter.",
        },
        {
            "source": "Green_Grid_WUE_Patterson_2011_via_repo_WATER_BOUNDARY",
            "date": "2011_definition_cited_by_Lei_Masanet_and_OCP",
            "operator_author": "no_standard_not_PRN1_meter",
            "measurement_period": "definition_only",
            "water_source": "typically_source_water_for_humidification_and_cooling",
            "RO_recovery": "",
            "spray_evap_fraction": "",
            "recapture_destination": "",
            "WUE_value": "",
            "WUE_numerator_definition": "onsite_source_water_for_cooling_and_humidification_over_IT;_often_includes_blowdown",
            "meter_location": "NOT_A_PRN1_METER",
            "confidence": "HIGH_as_industry_definition;_does_not_locate_PRN1_Q2_meter",
            "notes": "Compatible with RAW_COOLING_WATER_INPUT if Facebook followed Green Grid source-water WUE; OCP still excludes office/plumbing and does not name the tag.",
        },
        {
            "source": "fbpuewue_dashboard_and_facebookarchive_puewue_API",
            "date": "2013_dashboard_Wayback;_GitHub_boilerplate",
            "operator_author": "yes_Facebook_dashboard_TTM_only",
            "measurement_period": "TTM_end_Mar_2013_not_Q2_2012_hourly",
            "water_source": "unspecified",
            "RO_recovery": "",
            "spray_evap_fraction": "",
            "recapture_destination": "",
            "WUE_value": 0.52,
            "WUE_numerator_definition": "dashboard_TTM_WUE;_not_Q2_2012_0.22;_building_scope_MEDIUM",
            "meter_location": "NOT_NAMED_in_frontend_or_backend_source",
            "confidence": "HIGH_that_no_P_and_ID_or_meter_tag_in_public_API_source",
            "notes": "DASHBOARD_RECOVERY_MANIFEST: no authentic timeseries JSON. TTM 0.52 is later campus-ish, not this test.",
        },
        {
            "source": "ITherm_2012_author_source_archive_bounded",
            "date": "2012-05_PDF_on_frachtenberg.org",
            "operator_author": "yes",
            "measurement_period": "same_as_ITherm_paper",
            "water_source": "Fig8_well_primary_city_secondary",
            "RO_recovery": 0.67,
            "spray_evap_fraction": 0.85,
            "recapture_destination": "Fig8_recapture_to_RO_storage_via_polishing_skid",
            "WUE_value": 0.31,
            "WUE_numerator_definition": "estimate_text_only;_no_raw_flow_table",
            "meter_location": "NOT_IN_ARCHIVE",
            "confidence": "HIGH_that_no_separate_measurement_dump_exists_on_author_page",
            "notes": "Inspected author pubs page for water-cycle/Fig8/RO/WUE materials only. PDF is the archive. No hourly water CSV.",
        },
    ]
    write_csv(SRC_DIR / "WATER_CYCLE_SOURCE_CROSSWALK.csv", rows)

    boundary = {
        "observed_WUE_L_per_kWh_IT": 0.22,
        "building": "PRN1",
        "period": "Q2_2012",
        "excludes": "office_plumbing",
        "status": "PARTIAL_UNRESOLVED",
        "reason": (
            "OCP states cooling-water WUE after adding water metering but does not name the meter "
            "relative to outdoor storage, RO feed, or RO product. ITherm does not name a WUE meter. "
            "Green Grid WUE is typically source water / IT energy, which would include RO reject if "
            "the meter is upstream of RO. OCP's 75% 'used for cooling' vs 25% blowdown language is "
            "compatible with either a raw-input meter (reject included) or a product-side cooling meter "
            "(reject discussed separately). Do not select by closeness to 0.22."
        ),
        "discrete_hypotheses": [
            {
                "id": "RAW_COOLING_WATER_INPUT",
                "meaning": "external raw/well/city water into outdoor storage / RO feed",
                "steady_state": "W_obs = E / r",
                "support": "outdoor tanks; ITherm well+city into outdoor tank; Green Grid source-water convention; OCP 25% blown down discussed as part of water brought into DC",
            },
            {
                "id": "RO_PRODUCT_OR_ECH_MAKEUP",
                "meaning": "net new RO product / ECH makeup after RO (P=E at SS)",
                "steady_state": "W_obs = E",
                "support": "OCP 'used for cooling' as product; recapture already in product tanks so not double-counted",
            },
        ],
        "not_used": ["E/0.85", "1.392_topology", "closest_to_0.22"],
        "confidence": "HIGH_that_boundary_is_unresolved;_HIGH_that_office_water_is_excluded",
        "bounded_search": [
            "repo PRINEVILLE_WUE_BOUNDARY_CROSSWALK.csv/md",
            "OCP Water Efficiency at Facebook's Prineville Data Center (2013-08-07, Q2-2012 0.22)",
            "Frachtenberg et al. ITherm 2012 PDF + author pubs page (water-cycle only)",
            "fbpuewue dashboard Wayback + facebookarchive/puewue frontend/backend (DASHBOARD_RECOVERY_MANIFEST)",
            "Green Grid WUE definition as cited in repo WATER_BOUNDARY.md / Patterson 2011 via Lei-Masanet",
        ],
        "stopped_after_bounded_audit": True,
        "selected_by_closeness_to_0.22": False,
    }
    write_json(OUT / "Q2_2012_WUE_BOUNDARY_STATUS.json", boundary)

    balance = {
        "RECIRCULATION_TOPOLOGY": "PRODUCT_STORAGE_RETURN_CONFIRMED",
        "RO_RECOVERY_SOURCE_STATE": "DISCREPANT_{0.67,0.75}",
        "spray": {"E": "0.85 * S", "R": "0.15 * S"},
        "steady_state": {
            "P + R = S": True,
            "P = E": True,
            "F = E / r": True,
            "not_E_over_0.85": True,
            "not_1.392_topology": True,
        },
        "r_values_evaluated": [0.67, 0.75],
        "r_sources": {"0.67": "ITherm_2012_input_well_water", "0.75": "OCP_2013_RO_product_fraction"},
        "remaining_unknowns": [
            "WUE meter location",
            "which r applies to Q2-2012 operations",
            "as-operated return air",
            "as-operated DeltaT",
            "hourly IT load shape",
        ],
    }
    write_json(OUT / "EARLY_PRN1_CONFIRMED_WATER_BALANCE.json", balance)
    write_json(
        OUT / "RO_RECOVERY_DISCREPANCY.json",
        {
            "RO_RECOVERY_SOURCE_STATE": "DISCREPANT_{0.67,0.75}",
            "not_a_probability_distribution": True,
            "not_replaced_by_hard_75pct": True,
            "candidates": [
                {
                    "r": 0.67,
                    "source": "ITherm_2012_Frachtenberg_et_al",
                    "date": "conference_2012-05;_text_from_2011_operations_before_full_year",
                    "denominator": "input_well_water_to_RO",
                    "wording": "RO process produces approximately 67% purified water from the input well water",
                },
                {
                    "r": 0.75,
                    "source": "OCP_blog_2013-08-07",
                    "date": "published_2013-08-07_reporting_Q2_2012_after_BMS_and_meter_retrofit",
                    "denominator": "water_brought_into_the_data_center_AND_stated_as_3_of_4_parts_of_RO_water_are_product",
                    "wording": "75% of the water brought into the data center is used for cooling (3 out of 4 parts of RO water are used for product); remaining 25% blown down",
                },
            ],
            "classification": {
                "date": "UNRESOLVED_CONTRIBUTOR — ITherm is pre-full-year 2011 ops; OCP is Q2-2012 after metering retrofit",
                "denominator": "POSSIBLE_CONTRIBUTOR — ITherm names well-water RO feed; OCP names water brought into the DC and RO product/reject split",
                "operational_changes": "POSSIBLE_CONTRIBUTOR — RO recovery can change with feed TDS (well vs city blend) and membrane operation; not independently measured here",
                "rounding": "POSSIBLE_MINOR — 67% is already approximate; 3/4 is a round fraction; gap is larger than typical rounding",
            },
            "resolution": "UNRESOLVED. Evaluate r=0.67 and r=0.75 separately. Do not interpolate.",
        },
    )
    itherm_pdf = SOURCES / "frachtenberg12_thermal.pdf"
    write_json(
        SRC_DIR / "SOURCE_HASHES.json",
        {
            "itherm_pdf": sha256_file(itherm_pdf) if itherm_pdf.is_file() else None,
            "itherm_pdf_expected": "bbebc6452cb6c3a8cf0ffa7251c7ceda00176a47bb6f21a76bc9f257798bb0da",
            "public_proxy_freeze_file": sha256_file(PROXY_FREEZE),
            "krdm_hourly_csv": sha256_file(KRDM_CSV),
            "wue_boundary_crosswalk": sha256_file(
                REPO / "other_sources/cooling_technology_proxies/analysis/PRINEVILLE_WUE_BOUNDARY_CROSSWALK.csv"
            ),
        },
    )
    write_json(
        SRC_DIR / "ITHERM_SOURCE_ARCHIVE_BOUNDED_INSPECTION.json",
        {
            "inspected": [
                "https://frachtenberg.org/eitan/pubs/papers/frachtenberg12:thermal.pdf",
                "https://frachtenberg.org/eitan/pubs/",
            ],
            "scope": "water-cycle source material, Figure 8, RO measurements, water meter descriptions, WUE calculations, raw/intermediate water-flow data",
            "not_inspected": "unrelated Frachtenberg papers and non-water ITherm sections beyond locating Fig.8/Sec.V",
            "findings": {
                "Figure_8": "process diagram: well/city -> outdoor storage -> carbon/softener -> RO -> RO storage -> ECH nozzles; recapture from mist eliminator -> polishing skid UV/filters -> RO storage",
                "RO_measurements": "one approximate recovery statement (67% from input well water); no tabulated flows",
                "water_meter_descriptions": "none",
                "WUE_calculations": "0.31 L/kWh estimate from operational data thus far; more accurate after a full year; no worksheet",
                "raw_or_intermediate_water_flow_data": "NOT_FOUND",
            },
            "separate_measurement_archive": False,
        },
    )
    dump_md(
        OUT / "EARLY_PRN1_CONFIRMED_WATER_BALANCE.md",
        """# Early PRN1 confirmed water balance

`RECIRCULATION_TOPOLOGY = PRODUCT_STORAGE_RETURN_CONFIRMED`

OCP and ITherm: unevaporated mist → mist eliminator → micron filter → UV → **RO water storage tanks** (product).

Let `r` be RO recovery (`DISCREPANT_{0.67, 0.75}`), `S` spray, `E` air-stream evaporated water, `R` recapture, `P` new RO product, `F` fresh/raw RO feed.

Source: `E = 0.85 S`, `R = 0.15 S`, `R` returns to product storage.

Steady state: `P + R = S` ⇒ `P = E`.

If the observable is raw RO/fresh input: `F = E / r`.

If the observable is net RO product / ECH makeup: `W_obs = P = E`.

Do **not** use `E/0.85` as makeup. Do **not** use the removed 1.392 RO-feed topology.
""",
    )
    return balance


def stage5_weather() -> pd.DataFrame:
    df = pd.read_csv(KRDM_CSV, parse_dates=["timestamp_utc"])
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    local = df["timestamp_utc"].dt.tz_convert(TZ)
    start = pd.Timestamp("2012-04-01 00:00", tz=TZ)
    end = pd.Timestamp("2012-07-01 00:00", tz=TZ)
    mask = (local >= start) & (local < end)
    q = df.loc[mask].copy()
    q["timestamp_local"] = local.loc[mask]
    expected = pd.date_range(start, pd.Timestamp("2012-06-30 23:00", tz=TZ), freq="h")
    drivers = ["t_db_C", "t_dew_C", "rh_pct", "t_wb_C", "pressure_Pa"]
    for c in drivers:
        q[c] = pd.to_numeric(q[c], errors="coerce")
    usable = q[drivers].notna().all(axis=1)
    qa = {
        "station": "KRDM / 72692024230 / Redmond OR",
        "why_krdm": "ITherm: 50-year weather at Redmond, closest station to Prineville; Facebook thermal-design source.",
        "timezone": TZ,
        "period_local": "2012-04-01 00:00 through 2012-06-30 23:00",
        "n_expected_hours": int(len(expected)),
        "n_file_hours": int(len(q)),
        "n_missing_from_spine": int(len(set(expected) - set(q["timestamp_local"]))),
        "n_duplicate_utc": int(q["timestamp_utc"].duplicated().sum()),
        "n_nonfinite_required_drivers": int((~usable).sum()),
        "gap_fraction": float((~usable).mean()),
        "gap_treatment": "LEAVE_MISSING_DO_NOT_FILL; exclude from quarterly intensity; no KBDN/KS39 fill (13 hours, 0.6%)",
        "pressure_methods": q["pressure_method"].value_counts().to_dict() if "pressure_method" in q else {},
        "pressure_treatment": "use KRDM station pressure_Pa (slp-derived; 25 hours standard-atmosphere fallback already in processed file)",
        "dewpoint_preference": "t_dew_C present; rh_pct already derived consistently in prepare_weather.py",
        "tdb_C_min_max_usable": [float(q.loc[usable, "t_db_C"].min()), float(q.loc[usable, "t_db_C"].max())],
        "source_file": str(KRDM_CSV),
        "source_file_sha256": sha256_file(KRDM_CSV),
        "synthetic_five_point_grid_not_used": True,
        "dst_in_window": False,
        "dst_note": "2012 US spring-forward was 2012-03-11; Q2 has no DST transition. 91*24=2184 local hours.",
        "gap_fill_station": None,
        "filled_hours": [],
    }
    keep = [
        "timestamp_utc",
        "timestamp_local",
        "t_db_C",
        "t_dew_C",
        "rh_pct",
        "t_wb_C",
        "pressure_Pa",
        "pressure_method",
        "tmp_qc",
        "dew_qc",
        "slp_qc",
        "station",
        "provenance",
    ]
    out = q[[c for c in keep if c in q.columns]].copy()
    out["usable_required_drivers"] = usable.to_numpy()
    WX.mkdir(parents=True, exist_ok=True)
    pq = WX / "Q2_2012_KRDM_hourly.parquet"
    out.to_parquet(pq, index=False)
    qa["parquet_sha256"] = sha256_file(pq)
    write_json(WX / "Q2_2012_WEATHER_QA.json", qa)
    return out


def stage6_normalization(weather: pd.DataFrame) -> None:
    dump_md(
        OUT / "NORMALIZATION_PROOF.md",
        r"""# Normalization proof

Frozen v1 airflow: \(m_\mathrm{da} = P_\mathrm{IT}/(c_p\Delta T)\).

Air-stream evaporated water: \(W = m_\mathrm{da}\,\Delta w/\rho_w\).

Conditional on the outdoor state, return-air scenario, and controller (hence on \(\Delta w\)):

\[
\frac{W}{P_\mathrm{IT}} = \frac{\Delta w}{\rho_w\,c_p\,\Delta T}
\]

independent of absolute IT MW. Quarterly WUE is the **IT-energy-weighted** mean of hourly intensity, so scale still cancels, but an unknown hourly load shape that correlates with weather can change the quarter mean. Primary convention: `CONSTANT_NORMALIZED_IT_LOAD`.
""",
    )
    w = weather.loc[weather["usable_required_drivers"]].head(24).copy()
    w = w.rename(columns={"timestamp_local": "_local"})
    phys = w[["timestamp_utc", "t_db_C", "t_wb_C", "rh_pct", "pressure_Pa"]].copy()
    ra = ReturnAirSpec(T_C=35.0, rh_pct=15.0, provenance="DESIGN_REFERENCE_SCENARIO", label="norm")
    rows = []
    ref = None
    for mw in (1.0, 10.0, 40.0):
        out = simulate_structural_reference_v1(phys, mw, Params(server_deltaT_C=12.0), return_air=ra)
        # L/kWh = (m3/h) / MW
        intens = out["air_stream_evaporated_water_m3_h"].to_numpy(float) / mw
        if ref is None:
            ref = intens
        rows.append(
            {
                "p_it_mw": mw,
                "mean_L_per_kWh_IT": float(np.nanmean(intens)),
                "max_abs_diff_vs_1MW": float(np.nanmax(np.abs(intens - ref))),
            }
        )
    write_csv(OUT / "NORMALIZATION_TEST_RESULTS.csv", rows)
    if rows[-1]["max_abs_diff_vs_1MW"] > 1e-9:
        raise RuntimeError("Intensity not invariant to IT MW.")


def _load_weights(tdb: np.ndarray, amplitude: float) -> np.ndarray:
    if amplitude <= 0:
        return np.ones_like(tdb, dtype=float)
    x = (tdb - np.nanmean(tdb)) / (np.nanstd(tdb) + 1e-12)
    w = 1.0 + amplitude * np.clip(x, -1.0, 1.0)
    return np.clip(w, 1.0 - amplitude, 1.0 + amplitude)


def _energy_weighted(intensity: np.ndarray, weights: np.ndarray, usable: np.ndarray) -> float:
    m = usable & np.isfinite(intensity) & np.isfinite(weights)
    if not np.any(m):
        return float("nan")
    return float(np.sum(intensity[m] * weights[m]) / np.sum(weights[m]))


def stage8_prebenchmark_freeze(weather: pd.DataFrame, state: dict) -> dict:
    spec = {
        "structural_reference_v1_sha256": EXPECTED["structural_v1"],
        "v1_freeze_sha256": EXPECTED["v1_freeze"],
        "weather_parquet_sha256": sha256_file(WX / "Q2_2012_KRDM_hourly.parquet"),
        "primary_deltaT_K": 12.0,
        "deltaT_status": "GENERIC_PRIOR_SCENARIO",
        "deltaT_sensitivity_K": [8.0, 16.0],
        "deltaT_sensitivity_status": "SENSITIVITY_NOT_PUBLIC_BOUND",
        "return_air_primary": {
            "T_C": 35.0,
            "rh_pct": 15.0,
            "provenance": "DESIGN_REFERENCE_SCENARIO",
            "label": "RA_DRY_HOT_35C_15RH",
        },
        "return_air_sensitivity": {
            "T_C": 30.0,
            "rh_pct": 20.0,
            "provenance": "DESIGN_REFERENCE_SCENARIO",
            "label": "RA_30C_20RH_SENSITIVITY_NOT_FITTED",
        },
        "evap_thermal_effectiveness": 0.85,
        "evap_thermal_effectiveness_provenance": "GENERIC_PRIOR_SCENARIO_not_spray_fraction",
        "controller": "OCP_DESIGN_SPEC structural-reference-v1",
        "pressure": "KRDM_station_pressure_Pa",
        "RO_source_states": [0.67, 0.75],
        "WUE_boundary_states": ["RAW_COOLING_WATER_INPUT", "RO_PRODUCT_OR_ECH_MAKEUP"],
        "IT_load_primary": "CONSTANT_NORMALIZED_IT_LOAD",
        "IT_load_sensitivity": [
            "AMPLITUDE_0.10_TDB_CORRELATED_LOAD_WEIGHTING_SENSITIVITY_NOT_EMPIRICAL_BOUND",
            "AMPLITUDE_0.25_TDB_CORRELATED_LOAD_WEIGHTING_SENSITIVITY_NOT_EMPIRICAL_BOUND",
        ],
        "missing_weather_rule": "exclude hours with any nonfinite required driver; do not impute",
        "control_infeasibility_treatment": "retain v1 feasibility labels; include finite water hours in the mean; report infeasible fraction",
        "consistency_criteria_predeclared": {
            "CONSISTENT": "0.67 <= obs/pred <= 1.5",
            "PARTIALLY_CONSISTENT": "0.40 <= obs/pred <= 2.5 and not CONSISTENT",
            "INCONSISTENT": "otherwise when pred finite",
            "BOUNDARY_UNRESOLVED_PREVENTS_DECISION": "if unique-boundary claim cannot be made because hypotheses disagree",
        },
        "not_chosen_using_0.22": [
            "deltaT",
            "return_air",
            "r_RO",
            "WUE_boundary",
            "control_mode",
            "load_weights",
        ],
        "HEAD": state["HEAD"],
        "n_weather_hours": int(len(weather)),
        "n_usable_hours": int(weather["usable_required_drivers"].sum()),
    }
    write_json(OUT / "PRN1_Q2_2012_PREBENCHMARK_FREEZE.json", spec)
    return spec


def _run_physics(weather: pd.DataFrame, delta_t: float, ra: ReturnAirSpec) -> pd.DataFrame:
    phys = weather.loc[
        weather["usable_required_drivers"],
        ["timestamp_utc", "t_db_C", "t_wb_C", "rh_pct", "pressure_Pa"],
    ].copy()
    params = Params(server_deltaT_C=delta_t, evap_effectiveness=0.85)
    if hasattr(params, "evap_thermal_effectiveness"):
        params.evap_thermal_effectiveness = 0.85  # type: ignore[attr-defined]
    out = simulate_structural_reference_v1(phys, 1.0, params, return_air=ra)
    out = out.copy()
    out["intensity_L_per_kWh_IT"] = out["air_stream_evaporated_water_m3_h"].astype(float)
    out["deltaT_K"] = delta_t
    out["return_air_label"] = ra.label
    return out


def _status(obs: float, pred: float) -> str:
    if not np.isfinite(pred) or pred == 0:
        return "BOUNDARY_UNRESOLVED_PREVENTS_DECISION" if pred == 0 else "INCONSISTENT"
    ratio = obs / pred
    if 0.67 <= ratio <= 1.5:
        return "CONSISTENT"
    if 0.40 <= ratio <= 2.5:
        return "PARTIALLY_CONSISTENT"
    return "INCONSISTENT"


def stage9_to_11(weather: pd.DataFrame, spec: dict) -> dict:
    ra_p = ReturnAirSpec(
        T_C=spec["return_air_primary"]["T_C"],
        rh_pct=spec["return_air_primary"]["rh_pct"],
        provenance="DESIGN_REFERENCE_SCENARIO",
        label=spec["return_air_primary"]["label"],
    )
    ra_s = ReturnAirSpec(
        T_C=spec["return_air_sensitivity"]["T_C"],
        rh_pct=spec["return_air_sensitivity"]["rh_pct"],
        provenance="DESIGN_REFERENCE_SCENARIO",
        label=spec["return_air_sensitivity"]["label"],
    )
    physics_cases = [
        (12.0, ra_p, "PRIMARY"),
        (12.0, ra_s, "SENSITIVITY_RA"),
        (8.0, ra_p, "SENSITIVITY_DT"),
        (16.0, ra_p, "SENSITIVITY_DT"),
    ]
    hourly_primary = None
    intensity_rows = []
    pred_rows = []
    mode_rows = []

    for dT, ra, kind in physics_cases:
        sim = _run_physics(weather, dT, ra)
        merged = weather.merge(sim, on="timestamp_utc", how="left", suffixes=("", "_sim"))
        intens = merged["intensity_L_per_kWh_IT"].to_numpy(float)
        feas = merged["feasibility"].astype(str).to_numpy()
        usable = merged["usable_required_drivers"].to_numpy() & np.isfinite(intens)
        w_const = np.ones(len(merged))
        q_air = _energy_weighted(intens, w_const, usable)
        if kind == "PRIMARY":
            hourly_primary = merged
            for amp, lab in ((0.0, "CONSTANT_NORMALIZED_IT_LOAD"), (0.10, "TDB_CORR_PM10"), (0.25, "TDB_CORR_PM25")):
                ww = _load_weights(merged["t_db_C"].to_numpy(float), amp)
                q = _energy_weighted(intens, ww, usable)
                intensity_rows.append(
                    {
                        "case": lab if amp else "PRIMARY_12K_RA35",
                        "kind": "PRIMARY" if amp == 0 else "LOAD_WEIGHTING_SENSITIVITY_NOT_EMPIRICAL_BOUND",
                        "deltaT_K": dT,
                        "return_air": ra.label,
                        "air_stream_WUE_L_per_kWh_IT": q,
                        "n_usable": int(usable.sum()),
                        "frac_infeasible": float(np.mean(feas[usable] != "FEASIBLE")) if usable.any() else np.nan,
                    }
                )
        else:
            intensity_rows.append(
                {
                    "case": f"{kind}_dT{dT}_{ra.label}",
                    "kind": kind,
                    "deltaT_K": dT,
                    "return_air": ra.label,
                    "air_stream_WUE_L_per_kWh_IT": q_air,
                    "n_usable": int(usable.sum()),
                    "frac_infeasible": float(np.mean(feas[usable] != "FEASIBLE")) if usable.any() else np.nan,
                }
            )
        if kind == "PRIMARY":
            g = merged.loc[usable]
            for mode, sub in g.groupby("control_mode"):
                mode_rows.append(
                    {
                        "control_mode": mode,
                        "n_hours": int(len(sub)),
                        "fraction_hours": float(len(sub) / len(g)),
                        "mean_intensity_L_per_kWh": float(sub["intensity_L_per_kWh_IT"].mean()),
                        "water_share": float(
                            sub["intensity_L_per_kWh_IT"].sum() / g["intensity_L_per_kWh_IT"].sum()
                        )
                        if g["intensity_L_per_kWh_IT"].sum()
                        else 0.0,
                    }
                )
        pred_rows.append(
            {
                "physics_kind": kind,
                "deltaT_K": dT,
                "return_air": ra.label,
                "r_RO": "",
                "r_source": "n_a_product_equals_E",
                "boundary": "RO_PRODUCT_OR_ECH_MAKEUP",
                "boundary_short": "PRODUCT",
                "predicted_WUE_L_per_kWh_IT": q_air,
                "air_stream_WUE_L_per_kWh_IT": q_air,
            }
        )
        for r, rname in ((R_ITHERM, "r067_ITHERM"), (R_OCP, "r075_OCP")):
            pred_rows.append(
                {
                    "physics_kind": kind,
                    "deltaT_K": dT,
                    "return_air": ra.label,
                    "r_RO": r,
                    "r_source": rname,
                    "boundary": "RAW_COOLING_WATER_INPUT",
                    "boundary_short": "RAW",
                    "predicted_WUE_L_per_kWh_IT": q_air / r,
                    "air_stream_WUE_L_per_kWh_IT": q_air,
                }
            )

    if hourly_primary is None:
        raise RuntimeError("primary hourly missing")
    keep_cols = [
        c
        for c in [
            "timestamp_utc",
            "timestamp_local",
            "t_db_C",
            "t_dew_C",
            "rh_pct",
            "t_wb_C",
            "pressure_Pa",
            "usable_required_drivers",
            "control_mode",
            "feasibility",
            "oa_fraction",
            "t_supply_C",
            "air_stream_evaporated_water_m3_h",
            "intensity_L_per_kWh_IT",
            "primary_control_objective",
        ]
        if c in hourly_primary.columns
    ]
    hourly_path = OUT / "PREBENCHMARK_HOURLY_RESULTS.parquet"
    hourly_primary[keep_cols].to_parquet(hourly_path, index=False)
    write_csv(OUT / "PREBENCHMARK_Q2_INTENSITIES.csv", intensity_rows)
    write_csv(OUT / "PREBENCHMARK_MODE_BREAKDOWN.csv", mode_rows)
    write_csv(OUT / "PREBENCHMARK_OBSERVABLE_WUE_PREDICTIONS.csv", pred_rows)
    primary_air = [r for r in intensity_rows if r["kind"] == "PRIMARY"][0]
    load_vals = [
        r["air_stream_WUE_L_per_kWh_IT"]
        for r in intensity_rows
        if r["kind"] in ("PRIMARY", "LOAD_WEIGHTING_SENSITIVITY_NOT_EMPIRICAL_BOUND")
    ]
    status = {
        "primary_air_stream_WUE_L_per_kWh_IT": primary_air["air_stream_WUE_L_per_kWh_IT"],
        "n_usable": primary_air["n_usable"],
        "frac_infeasible": primary_air["frac_infeasible"],
        "hourly_sha256": sha256_file(hourly_path),
        "predictions_frozen_before_0.22_comparison": True,
        "no_monte_carlo": True,
        "load_weighting_air_stream_min": float(np.nanmin(load_vals)),
        "load_weighting_air_stream_max": float(np.nanmax(load_vals)),
        "load_weighting_relative_span": float(
            (np.nanmax(load_vals) - np.nanmin(load_vals)) / primary_air["air_stream_WUE_L_per_kWh_IT"]
        )
        if primary_air["air_stream_WUE_L_per_kWh_IT"]
        else None,
    }
    write_json(OUT / "PREBENCHMARK_STATUS.json", status)

    # Freeze hashes of prebenchmark artifacts before comparison
    pre_paths = [
        hourly_path,
        OUT / "PREBENCHMARK_Q2_INTENSITIES.csv",
        OUT / "PREBENCHMARK_OBSERVABLE_WUE_PREDICTIONS.csv",
        OUT / "PREBENCHMARK_STATUS.json",
        OUT / "PRN1_Q2_2012_PREBENCHMARK_FREEZE.json",
    ]
    mh, hs = master_hash(pre_paths)
    write_json(OUT / "PREBENCHMARK_OUTPUT_FREEZE.json", {"master_hash": mh, "sha256": hs})

    cons_rows = []
    for row in pred_rows:
        pred = float(row["predicted_WUE_L_per_kWh_IT"])
        gap = OBSERVED_WUE - pred
        rel = gap / OBSERVED_WUE if OBSERVED_WUE else np.nan
        ratio = OBSERVED_WUE / pred if pred else np.nan
        cons_rows.append(
            {
                **row,
                "observed_WUE": OBSERVED_WUE,
                "abs_gap": gap,
                "rel_gap": rel,
                "obs_over_pred": ratio,
                "consistency_status": _status(OBSERVED_WUE, pred),
                "benchmark_class": "PUBLIC_PREVIOUSLY_KNOWN_EXTERNAL_BENCHMARK",
                "selected_as_winner": False,
            }
        )
    write_csv(OUT / "Q2_2012_EXTERNAL_CONSISTENCY_RESULTS.csv", cons_rows)
    primary_cons = [c for c in cons_rows if c["physics_kind"] == "PRIMARY"]
    statuses = {c["consistency_status"] for c in primary_cons}
    overall = (
        "BOUNDARY_UNRESOLVED_PREVENTS_DECISION"
        if len(statuses) > 1
        else next(iter(statuses))
    )
    summary = {
        "overall_unique_boundary_claim": overall,
        "primary_air_stream_WUE": primary_air["air_stream_WUE_L_per_kWh_IT"],
        "observed": OBSERVED_WUE,
        "n_primary_boundary_cases": len(primary_cons),
        "statuses_present": sorted(statuses),
        "no_winner_selected": True,
        "no_retune": True,
        "prebenchmark_output_freeze_hash": mh,
    }
    write_json(OUT / "Q2_2012_EXTERNAL_CONSISTENCY_RESULTS.json", summary)

    freeze_after = json.loads((OUT / "PREBENCHMARK_OUTPUT_FREEZE.json").read_text())
    if freeze_after["master_hash"] != mh:
        raise RuntimeError("benchmark mutated prebenchmark freeze")
    return {"primary_air": primary_air, "cons": cons_rows, "summary": summary, "modes": mode_rows}


def stage12_diagnostics(primary_air: dict, cons: list[dict]) -> None:
    w_air = primary_air["air_stream_WUE_L_per_kWh_IT"]
    rows = [
        {
            "quantity": "water_boundary_factor_implied",
            "value": OBSERVED_WUE / w_air if w_air else np.nan,
            "compare_to": "1.0 if product meter; 1/0.75=1.333 if raw and r=0.75; 1/0.67=1.493 if raw and r=0.67",
            "label": "POSTHOC_DIAGNOSTIC_ONLY",
            "promoted": False,
        },
        {
            "quantity": "DeltaT_implied_if_W_proportional_to_1_over_DT_product_meter",
            "value": 12.0 * w_air / OBSERVED_WUE if OBSERVED_WUE else np.nan,
            "compare_to": "12 K GENERIC_PRIOR; OCP rack CFM unmatched envelope ~6.7–15.8 K",
            "label": "POSTHOC_DIAGNOSTIC_ONLY",
            "promoted": False,
        },
    ]
    write_csv(OUT / "POSTHOC_DIAGNOSTICS.csv", rows)
    write_json(
        OUT / "EARLY_OPERATOR_ESTIMATE_CONTEXT.json",
        {
            "ITherm_WUE_0.31": "EARLY_OPERATOR_ESTIMATE_CONTEXT",
            "not_independent_validation": True,
            "role": "measurement_evolution_meter_retrofit_context",
            "sequence": "2011 design 0.31 (Park) → ITherm estimate 0.31 before full year → OCP metered Q2-2012 0.22 after BMS/meter retrofit",
        },
    )


def stage14_voi() -> None:
    rows = [
        {
            "uncertainty": "WUE_meter_location_raw_vs_product",
            "scope": "early_PRN1_water_accounting",
            "blocking_level": "HARD_FOR_UNIQUE_CONSISTENCY_CLAIM",
            "conditional_dependencies": "none",
            "quantifiable_now": "yes_two_discrete_hypotheses",
            "actual_range_reduction_if_available": "factor_1.00_vs_1.33_vs_1.49_on_air_stream",
            "expected_information_value": "VERY_HIGH",
            "specific_dataset_needed": "Q2-2012 meter P&ID or BMS tag for cooling-water WUE numerator",
        },
        {
            "uncertainty": "RO_recovery_0.67_vs_0.75",
            "scope": "early_PRN1_if_raw_boundary",
            "blocking_level": "HIGH_IF_RAW_METER",
            "conditional_dependencies": "WUE_meter_location",
            "quantifiable_now": "yes_discrepant_pair",
            "actual_range_reduction_if_available": "1/0.67 vs 1/0.75 = 12% relative on F",
            "expected_information_value": "HIGH",
            "specific_dataset_needed": "RO product/reject flow for Q2-2012",
        },
        {
            "uncertainty": "facility_DeltaT_as_operated",
            "scope": "building_physics",
            "blocking_level": "HIGH_FOR_MAGNITUDE",
            "conditional_dependencies": "airflow_or_IT_heat",
            "quantifiable_now": "no_public_numerical_bound",
            "actual_range_reduction_if_available": "NOT_A_FINITE_PUBLIC_INTERVAL",
            "expected_information_value": "HIGH",
            "specific_dataset_needed": "BMS SAT-RAT or supply airflow",
        },
        {
            "uncertainty": "return_air_state",
            "scope": "controller_mixing",
            "blocking_level": "MEDIUM",
            "conditional_dependencies": "mix_regions_A_F_G_H",
            "quantifiable_now": "sensitivity_only",
            "actual_range_reduction_if_available": "see_RA_sensitivity_row_in_intensities",
            "expected_information_value": "MEDIUM",
            "specific_dataset_needed": "return_T_RH",
        },
        {
            "uncertainty": "hourly_IT_load_shape",
            "scope": "quarterly_energy_weighting",
            "blocking_level": "LOW_TO_MEDIUM",
            "conditional_dependencies": "weather_correlation",
            "quantifiable_now": "sensitivity_pm10_pm25",
            "actual_range_reduction_if_available": "see_load_weighting_rows",
            "expected_information_value": "LOW",
            "specific_dataset_needed": "PRN1_IT_kWh_hourly_or_even_daily",
        },
        {
            "uncertainty": "later_campus_architecture_and_lambda",
            "scope": "not_this_test",
            "blocking_level": "OUT_OF_SCOPE_STILL_CAMPUS_BLOCKER",
            "conditional_dependencies": "Q2_PRN1_does_not_identify_later_halls",
            "quantifiable_now": "no",
            "actual_range_reduction_if_available": "campus_envelope_still_not_finite",
            "expected_information_value": "VERY_HIGH_for_campus_not_for_this_Q2_test",
            "specific_dataset_needed": "per-building architecture and IT load",
        },
    ]
    write_csv(OUT / "REVISED_INFORMATION_PRIORITY.csv", rows)


def stage15_figures(weather: pd.DataFrame, cons: list[dict], modes: list[dict]) -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    h = pd.read_parquet(OUT / "PREBENCHMARK_HOURLY_RESULTS.parquet")
    h = h.sort_values("timestamp_utc")
    fig, axes = plt.subplots(3, 1, figsize=(9, 7), sharex=True)
    t = pd.to_datetime(h["timestamp_local"])
    axes[0].plot(t, h["t_db_C"], lw=0.6)
    axes[0].set_ylabel("Tdb °C")
    spray = h["control_mode"].astype(str).str.contains("EVAP|HUMID", case=False)
    axes[1].plot(t, spray.astype(float), lw=0.4, drawstyle="steps-post")
    axes[1].set_ylabel("spray-ish mode")
    axes[2].plot(t, h["intensity_L_per_kWh_IT"], lw=0.6)
    axes[2].set_ylabel("AIR_STREAM L/kWh")
    axes[2].set_xlabel("local time")
    fig.suptitle("Q2-2012 KRDM → v1 control → AIR_STREAM (primary spec)")
    fig.tight_layout()
    fig.savefig(FIG / "fig01_q2_hourly_weather_control_water.png", dpi=140)
    plt.close(fig)

    prim = [c for c in cons if c["physics_kind"] == "PRIMARY"]
    labels = []
    for c in prim:
        if c["boundary_short"] == "PRODUCT":
            labels.append("PRODUCT\nP=E")
        else:
            labels.append(f"RAW\nr={c['r_RO']}")
    vals = [c["predicted_WUE_L_per_kWh_IT"] for c in prim]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(range(len(vals)), vals, color="C0")
    ax.axhline(0.22, color="C3", ls="--", label="observed 0.22")
    ax.set_xticks(range(len(labels)), labels, fontsize=8)
    ax.set_ylabel("predicted cooling-water WUE L/kWh_IT")
    ax.set_title("Predeclared primary physics vs Q2-2012 0.22\n(no winner selected)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG / "fig02_predicted_wue_vs_022.png", dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.axis("off")
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 5)
    boxes = [(0.3, 3.4, "F raw feed"), (3.6, 3.4, "RO  r∈{0.67,0.75}"), (7.0, 3.4, "reject 1-r"),
             (3.6, 1.7, "P=E product"), (0.3, 0.3, "R=0.15S recapture"), (7.0, 0.3, "E=0.85S vapor")]
    for x, y, t in boxes:
        ax.add_patch(plt.Rectangle((x, y), 2.6, 1.0, fill=False))
        ax.text(x + 1.3, y + 0.5, t, ha="center", va="center", fontsize=8)
    ax.set_title("Confirmed: recapture → RO product storage. F=E/r. Not E/0.85.")
    fig.tight_layout()
    fig.savefig(FIG / "fig03_confirmed_mass_balance.png", dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.2))
    names = ["Meter location", "RO r 0.67/0.75", "ΔT as-operated", "Return air", "Load shape", "Later campus"]
    order = [5, 4, 3, 2, 1, 0]
    ax.barh(names[::-1], order)
    ax.set_xlabel("categorical expected information value (rank, not fake range reduction)")
    ax.set_title("Information priority (no 1.0/0.8/0.7 placeholders)")
    fig.tight_layout()
    fig.savefig(FIG / "fig04_information_priority.png", dpi=140)
    plt.close(fig)


def stage16_chain() -> None:
    rows = [
        {"edge": "actual_weather->conditioning_state", "before": "STRUCTURALLY_IDENTIFIED_synthetic_points", "after": "ENGINEERING_BOUNDED_Q2_2012_KRDM_plus_OCP_DESIGN_SPEC", "note": "KRDM actual quarter; 13 hours excluded"},
        {"edge": "conditioning_state->AIR_STREAM_EVAPORATED_WATER", "before": "STRUCTURALLY_IDENTIFIED", "after": "STRUCTURALLY_IDENTIFIED_weather_integrated", "note": "v1 unchanged; intensity independent of MW"},
        {"edge": "air_vapor->early_PRN1_cooling_water_boundary", "before": "SCENARIO_BOUNDED_two_topologies", "after": "STRUCTURALLY_IDENTIFIED_P_equals_E;_SCENARIO_BOUNDED_r_and_meter", "note": "RO-feed topology removed"},
        {"edge": "cooling_water->public_WUE", "before": "UNIDENTIFIED_meter", "after": "SCENARIO_BOUNDED_two_numerator_hypotheses_vs_0.22", "note": "PUBLIC_PREVIOUSLY_KNOWN_EXTERNAL_BENCHMARK; not pristine TEST"},
        {"edge": "later_PRN_CCO", "before": "UNIDENTIFIED", "after": "UNIDENTIFIED_unchanged", "note": "Do not generalize Q2 PRN1"},
    ]
    write_csv(OUT / "CHAIN_CONNECTION_STATUS.csv", rows)
    dump_md(
        OUT / "OPERATING_STATUS_ONTOLOGY.md",
        """# Operating-status ontology (correction)

- CONFIRMED_OPERATING: source gives operational-by / in-service evidence.
- POSSIBLY_OPERATING: construction/chronology allows operation; CO not confirmed.
- NOT_YET_OPERATING: completed/CO later than the date in question.

PRN1 Q2-2012: CONFIRMED_OPERATING (OCP WUE for Prineville 1; second building not yet online).
PRN4 in 2014: NOT hard-activated. Southland completion 2016 ⇒ 2014 is at most POSSIBLY_OPERATING if other sources exist; this pass does not promote 2014 operation.
""",
    )


def main() -> None:
    for d in (OUT, SRC_DIR, WX, FIG, SOURCES):
        d.mkdir(parents=True, exist_ok=True)
    proxy_before = sha256_file(PROXY_FREEZE)
    v1_before = sha256_file(ROOT / "src/prineville_structural_v1.py")
    state = stage0_initial_state()
    with HoldoutGuard(ROOT):
        stage1_corrections()
        stage2_water_cycle()
        weather = stage5_weather()
        stage6_normalization(weather)
        spec = stage8_prebenchmark_freeze(weather, state)
        results = stage9_to_11(weather, spec)
        stage12_diagnostics(results["primary_air"], results["cons"])
        stage14_voi()
        stage15_figures(weather, results["cons"], results["modes"])
        stage16_chain()
    if sha256_file(PROXY_FREEZE) != proxy_before:
        raise RuntimeError("public-proxy freeze mutated")
    if sha256_file(ROOT / "src/prineville_structural_v1.py") != v1_before:
        raise RuntimeError("v1 mutated")
    write_json(
        OUT / "RUN_STATUS.json",
        {
            "complete": True,
            "public_proxy_freeze_unchanged": True,
            "v1_unchanged": True,
            "no_meta_annual_water": True,
            "no_fit": True,
            "overall": results["summary"]["overall_unique_boundary_claim"],
        },
    )
    print("prn1_q2_2012_public_validation_v1 complete")
    print("overall", results["summary"]["overall_unique_boundary_claim"])
    print("air_stream_WUE", results["primary_air"]["air_stream_WUE_L_per_kWh_IT"])


if __name__ == "__main__":
    main()
