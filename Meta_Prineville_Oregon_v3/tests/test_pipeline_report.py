"""Registry completeness and report-artifact checks for the audit layer."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pipeline_report_catalog import (  # noqa: E402
    MODEL_CLASSES,
    PROVENANCE_CLASSES,
    REQUIRED_GLOSSARY_QUANTITY_IDS,
    model_registry,
    quantity_registry,
    source_inventory,
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
