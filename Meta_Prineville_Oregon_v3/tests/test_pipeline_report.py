"""Registry completeness and report-artifact checks for the audit layer."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pipeline_report_catalog import (  # noqa: E402
    BOUNDARY_VOCABULARY,
    MODEL_CLASSES,
    PROVENANCE_CLASSES,
    REQUIRED_GLOSSARY_QUANTITY_IDS,
    model_io_edges,
    model_registry,
    parameter_registry,
    quantity_registry,
    source_inventory,
    source_quantity_edges,
    validate_lineage_ids,
)

REPORT = ROOT / "outputs" / "pipeline_report"


def test_source_ids_unique():
    ids = [r["source_id"] for r in source_inventory()]
    assert ids
    assert len(ids) == len(set(ids))


def test_quantity_ids_unique_and_provenance_canonical():
    rows = quantity_registry()
    ids = [r["quantity_id"] for r in rows]
    assert len(ids) == len(set(ids))
    for r in rows:
        assert r["provenance_class"] in PROVENANCE_CLASSES, r["quantity_id"]
        assert r["quantity_id"]
        assert r["quantity"]


def test_required_glossary_quantities_present():
    have = {r["quantity_id"] for r in quantity_registry()}
    missing = [q for q in REQUIRED_GLOSSARY_QUANTITY_IDS if q not in have]
    assert not missing, missing


def test_unavailable_not_given_a_proxy_source():
    for r in quantity_registry():
        if r["provenance_class"] == "unavailable":
            assert r["implementation_status"] in {
                "unavailable",
                "unavailable as the glossary quantity",
            } or r["implementation_status"].startswith("unavailable"), r["quantity_id"]
            assert "not identified" in r["missing_information_limitation"].lower() or r[
                "missing_information_limitation"
            ]


def test_model_ids_unique_and_classes_canonical():
    rows = model_registry()
    ids = [r["model_id"] for r in rows]
    assert len(ids) == len(set(ids))
    for r in rows:
        assert r["model_class"] in MODEL_CLASSES, r["model_id"]
    names = {r["model_id"] for r in rows}
    for required in (
        "M_GRAYBOX",
        "M_ELEC_CLOSURE",
        "M_WATER_SCALE_GLOBAL",
        "M_WATER_ENERGY_NULL",
        "M_STOCHASTIC",
        "M_EGRID_BENCH",
        "M_CHANGEPOINT",
    ):
        assert required in names


def test_electricity_closure_not_labeled_prediction():
    elec = next(r for r in model_registry() if r["model_id"] == "M_ELEC_CLOSURE")
    assert "no" in elec["is_prediction"].lower()
    assert "closure" in elec["is_prediction"].lower() or "closure" in elec["notes"].lower()


def test_required_report_artifacts_if_built():
    """If the report has been generated, required files and labels must exist."""
    inventory = REPORT / "data_source_inventory.csv"
    if not inventory.exists():
        return
    sources = pd.read_csv(inventory)
    qty = pd.read_csv(REPORT / "model_quantity_registry.csv")
    models = pd.read_csv(REPORT / "model_registry.csv")
    score = pd.read_csv(REPORT / "validation_scorecard.csv")
    assert sources["source_id"].is_unique
    assert qty["quantity_id"].is_unique
    assert models["model_id"].is_unique
    assert set(qty["provenance_class"]).issubset(set(PROVENANCE_CLASSES))
    required = [
        REPORT / "data_source_tree.png",
        REPORT / "data_source_tree.mmd",
        REPORT / "model_quantity_dependency.png",
        REPORT / "model_quantity_dependency.mmd",
        REPORT / "figures" / "fig01_data_coverage_provenance.png",
        REPORT / "figures" / "fig02_observed_ground_truth.png",
        REPORT / "figures" / "fig03_water_model_accuracy.png",
        REPORT / "figures" / "fig04_external_water_context.png",
        REPORT / "figures" / "fig05_carbon_benchmark.png",
        REPORT / "figures" / "fig06_graybox_hot_week.png",
        ROOT / "docs" / "PIPELINE_DATA_MODEL_REPORT.md",
    ]
    missing = [p.as_posix() for p in required if not p.exists()]
    assert not missing, missing
    md = (ROOT / "docs" / "PIPELINE_DATA_MODEL_REPORT.md").read_text(encoding="utf-8")
    for heading in (
        "## 1. Pipeline overview",
        "## 2. Data-source tree",
        "## 3. Data coverage",
        "## 4. Model quantity",
        "## 5. Explicit models currently used",
        "## 6. Core equations and assumptions",
        "## 7. Validation and predictive accuracy",
        "## 8. What is observed vs inferred vs scenario",
        "## 9. Quantities still unidentified",
        "## 10. What additional data would resolve each major gap",
    ):
        assert heading in md, heading
    lowered = md.lower()
    assert "not predictive accuracy" in lowered or "closure, not prediction" in lowered
    score_text = score.astype(str).apply(lambda c: c.str.lower()).to_numpy().astype(str)
    assert any("holdout" in cell for cell in score_text.ravel())
    assert len(score) >= 8
    for extra in (
        REPORT / "source_quantity_edges.csv",
        REPORT / "model_io_edges.csv",
        REPORT / "model_parameter_registry.csv",
        REPORT / "water_holdout_baseline_compare.csv",
        REPORT / "graybox_parameter_sensitivity.csv",
        REPORT / "figures" / "fig07_graybox_parameter_sensitivity.png",
    ):
        assert extra.exists(), extra.as_posix()
    assert "methodology/accounting consistency" in md.lower()
    assert "design/assumption consistency" in md.lower() or "falsification check" in md.lower()
    assert "2023–2024 water-model holdout" in md or "2023-2024 water-model holdout" in md.lower()
    # eGRID / PUE must not be classified as independent external validation
    egrid_rows = score[score["model_or_quantity"].astype(str).str.contains("eGRID", case=False)]
    pue_rows = score[score["model_or_quantity"].astype(str).str.contains("PUE", case=False)]
    assert len(egrid_rows) and len(pue_rows)
    assert not egrid_rows["evidence_type"].astype(str).str.contains("independent external", case=False).any()
    assert not pue_rows["evidence_type"].astype(str).str.contains("independent external", case=False).any()
    assert egrid_rows["evidence_type"].astype(str).str.contains("accounting", case=False).any()
    assert pue_rows["evidence_type"].astype(str).str.contains("design|assumption|falsification", case=False, regex=True).any()
    assert "boundary_id" in qty.columns
    assert "accounting_boundary_note" in qty.columns


def test_lineage_edges_reference_canonical_ids_and_no_duplicates():
    validate_lineage_ids()
    sids = {r["source_id"] for r in source_inventory()}
    qids = {r["quantity_id"] for r in quantity_registry()}
    mids = {r["model_id"] for r in model_registry()}
    sq = source_quantity_edges()
    mio = model_io_edges()
    sq_keys = [(e["source_id"], e["quantity_id"], e["role"]) for e in sq]
    mio_keys = [(e["model_id"], e["quantity_id"], e["io_role"]) for e in mio]
    assert len(sq_keys) == len(set(sq_keys))
    assert len(mio_keys) == len(set(mio_keys))
    for e in sq:
        assert e["source_id"] in sids
        assert e["quantity_id"] in qids
        assert e["role"] in {"primary", "context", "calibration_target", "benchmark", "validation"}
    for e in mio:
        assert e["model_id"] in mids
        assert e["quantity_id"] in qids
        assert e["io_role"] in {"input", "target", "output", "benchmark", "validation"}
    assert not any(
        e["model_id"] == "M_WATER_ENERGY_NULL" and e["quantity_id"] == "Q_W_EVAP" for e in mio
    )


def test_implemented_quantities_have_valid_boundary_id():
    for r in quantity_registry():
        assert r["boundary_id"] in BOUNDARY_VOCABULARY, r["quantity_id"]
        if r["provenance_class"] != "unavailable":
            assert r["boundary_id"] != "NOT_IDENTIFIED", r["quantity_id"]
            assert r["accounting_boundary_note"]


def test_parameter_registry_includes_graybox_and_unused_return_air():
    rows = parameter_registry()
    by_name = {(r["model_id"], r["parameter"]): r for r in rows}
    for name in (
        "supply_target_C",
        "return_air_C",
        "evap_effectiveness",
        "server_deltaT_C",
        "dry_air_cp_J_kgK",
        "fan_fraction_of_it",
        "other_facility_fraction_of_it",
        "evap_aux_fraction",
    ):
        assert ("M_GRAYBOX", name) in by_name, name
    unused = by_name[("M_GRAYBOX", "return_air_C")]
    assert unused["status"] == "unused"
    assert unused["used_in_code"] == "no"


def test_validation_terminology_in_scorecard_if_built():
    path = REPORT / "validation_scorecard.csv"
    if not path.exists():
        return
    score = pd.read_csv(path)
    joined = score.astype(str).to_string().lower()
    assert "calibration closure" in joined or "not a prediction" in joined
    assert "structural qa" in joined
    assert "not independent hydrologic validation" in joined
    assert "not meta prediction error" in joined or "boundary/context consistency" in joined
    assert "methodology/accounting consistency" in joined
    assert "design/assumption consistency" in joined or "falsification check" in joined


def test_not_necessary_is_distinct_from_missing_and_figure1_uses_both():
    from pipeline_report_catalog import COVERAGE_STATUSES
    from build_pipeline_report import COLORS

    assert "not_necessary" in COVERAGE_STATUSES
    assert "missing" in COVERAGE_STATUSES
    assert COLORS["not_necessary"] == "#000000"
    assert COLORS["missing"] == "#d9d9d9"
    path = REPORT / "figure1_coverage_status.csv"
    if not path.exists():
        return
    cov = pd.read_csv(path)
    assert set(cov.coverage_status).issubset(set(COVERAGE_STATUSES))
    assert "not_necessary" in set(cov.coverage_status)
    assert "missing" in set(cov.coverage_status)
    eia = cov[cov.series.eq("EIA-930 PACW hourly demand")]
    assert eia.loc[eia.year.isin([2011, 2012, 2013, 2014]), "coverage_status"].eq("not_necessary").all()
    ferc_m = cov[cov.series.eq("FERC PacifiCorp-West monthly")]
    assert ferc_m.loc[ferc_m.year.ge(2019), "coverage_status"].eq("not_necessary").all()
    ferc_h = cov[cov.series.eq("FERC PACW-West hourly proxy")]
    assert ferc_h.loc[ferc_h.year.ge(2019), "coverage_status"].eq("not_necessary").all()
    it = cov[cov.series.eq("Hourly IT telemetry")]
    assert it["coverage_status"].eq("not_necessary").all()
    water = cov[cov.series.eq("Meta water withdrawal")]
    assert water.loc[water.year.isin([2011, 2012, 2013]), "coverage_status"].eq("missing").all()
    meters = cov[cov.series.eq("Monthly Meta water/electricity meters")]
    assert meters["coverage_status"].eq("missing").all()
    s2 = cov[cov.series.eq("Meta location Scope 2")]
    assert s2.loc[s2.year.eq(2011), "coverage_status"].eq("missing").all()
    gw = cov[cov.series.eq("Groundwater head observations")]
    assert not gw.empty
    lv = ROOT / "data" / "processed" / "groundwater" / "groundwater_level_observations.csv"
    if lv.exists():
        levels = pd.read_csv(lv)
        bls = pd.to_numeric(levels["water_level_below_land_surface"], errors="coerce")
        dt = pd.to_datetime(levels["measurement_datetime"], errors="coerce")
        years = set(dt[bls.notna()].dt.year.dropna().astype(int))
        for r in gw.itertuples(index=False):
            expected = "measured" if int(r.year) in years else "missing"
            assert r.coverage_status == expected


def test_full_rebuilds_conditional_before_public_extensions():
    src = (ROOT / "run_prineville.py").read_text(encoding="utf-8")
    start = src.index("def full():")
    end = src.index("\ndef ", start + 1)
    body = src[start:end]
    assert body.index("groundwater_context()") < body.index("conditional()")
    assert body.index("conditional()") < body.index("public_extensions()")
    assert body.index("public_extensions()") < body.index("simulate()")
    assert body.index("simulate()") < body.index("report()")

