from __future__ import annotations

import hashlib
import json
import ast
import unittest
from pathlib import Path

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_EVIDENCE = {
    "OBSERVED",
    "REPORTED_MEASURED",
    "DERIVED_FROM_MEASUREMENTS",
    "ESTIMATED",
    "MODELED",
    "REFERENCE_MODEL",
}


class ScientificGuardTests(unittest.TestCase):
    def test_no_learned_groundwater_model_code(self) -> None:
        forbidden_modules = {"sklearn", "statsmodels", "torch", "torch_geometric", "tensorflow", "pymc"}
        for folder in (ROOT / "src", ROOT / "scripts"):
            for path in folder.rglob("*.py"):
                tree = ast.parse(path.read_text())
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        roots = {alias.name.split(".")[0] for alias in node.names}
                        self.assertFalse(roots & forbidden_modules, f"Learned-model import in {path}: {roots & forbidden_modules}")
                    if isinstance(node, ast.ImportFrom) and node.module:
                        self.assertNotIn(node.module.split(".")[0], forbidden_modules, f"Learned-model import in {path}: {node.module}")
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                        self.assertNotIn(node.func.attr, {"fit", "fit_predict", "interpolate"}, f"Forbidden fitting/interpolation call in {path}")

    def test_heads_are_not_interpolated(self) -> None:
        for folder in (ROOT / "src", ROOT / "scripts"):
            for path in folder.rglob("*.py"):
                self.assertNotIn("interpolate(", path.read_text(), f"Interpolation call found in {path}")
        heads = pd.read_parquet(ROOT / "data/derived/DWR_OCWD_HEAD_OBSERVATIONS.parquet")
        self.assertNotIn("interpolated", heads.columns)

    def test_continuous_dataset_is_excluded_geographically(self) -> None:
        payload = json.loads((ROOT / "outputs/provenance/DWR_CONTINUOUS_GWL_STATUS.json").read_text())
        status = payload["DWR_CONTINUOUS_GWL"]
        self.assertEqual(status["status"], "EXCLUDED_GEOGRAPHICALLY")
        self.assertEqual(status["reason"], "no Orange County stations in current dataset")
        self.assertNotIn("Orange", status["official_covered_counties"])
        self.assertFalse(status["large_data_tables_downloaded"])

    def test_wcr_coordinates_never_replace_station_coordinates(self) -> None:
        ledger = pd.read_csv(ROOT / "outputs/tables/WCR_MATCH_LEDGER.csv")
        self.assertFalse(ledger["wcr_coordinates_used_as_canonical"].astype(bool).any())
        self.assertTrue(ledger["canonical_coordinate_source"].eq("DWR periodic station table").all())
        self.assertTrue(set(ledger["match_status"]).issubset({"EXACT_ID", "HIGH_CONFIDENCE_METADATA_MATCH", "AMBIGUOUS", "NO_MATCH"}))

    def test_estimated_recharge_is_not_observed(self) -> None:
        reports = pd.read_csv(ROOT / "outputs/tables/OCWD_RECENT_WATER_RESOURCES_REPORT_FIELDS.csv")
        incidental = reports.loc[reports["field"].eq("Incidental Recharge (estimated)")]
        self.assertTrue(incidental["measurement_class"].eq("ESTIMATED").all())

    def test_calculated_storage_is_not_independent_validation(self) -> None:
        reports = pd.read_csv(ROOT / "outputs/tables/OCWD_RECENT_WATER_RESOURCES_REPORT_FIELDS.csv")
        storage = reports.loc[reports["field"].eq("Change in Groundwater Storage")]
        self.assertTrue(storage["measurement_class"].eq("DERIVED_FROM_MEASUREMENTS").all())
        self.assertFalse(storage["independent_validation_allowed"].astype(bool).any())

    def test_modflow_is_reference_not_ground_truth(self) -> None:
        gap = pd.read_csv(ROOT / "outputs/feasibility/DATA_REQUIREMENT_GAP_MATRIX.csv")
        row = gap.loc[gap["data_requirement"].eq("MODFLOW reference package")].iloc[0]
        self.assertEqual(row["evidence_class"], "REFERENCE_MODEL")
        request = (ROOT / "requests/OCWD_BASIN_MODEL_REQUEST.md").read_text()
        self.assertIn("will not be treated as empirical ground truth", request)

    def test_republished_observations_are_not_double_counted_as_independent(self) -> None:
        ledger = pd.read_csv(ROOT / "outputs/tables/OBSERVATION_INDEPENDENCE_LEDGER.csv")
        republished = ledger.loc[ledger["independence_class"].eq("OCWD_ORIGIN_REPUBLISHED_BY_DWR")]
        if len(republished):
            self.assertTrue(republished["do_not_duplicate_against_ocwd"].astype(bool).all())
        self.assertTrue(set(ledger["independence_class"]).issubset({"INDEPENDENT_AGENCY_OBSERVATION", "OCWD_ORIGIN_REPUBLISHED_BY_DWR", "UNKNOWN_ORIGIN"}))

    def test_no_invented_depth_threshold_layer_assignment(self) -> None:
        ledger = pd.read_csv(ROOT / "outputs/tables/WCR_MATCH_LEDGER.csv", keep_default_na=False)
        self.assertTrue(ledger["authoritative_layer_assignment"].eq("").all())
        mbi = pd.read_csv(ROOT / "outputs/tables/MBI_MONITORING_WELL_SCREEN_REGISTRY.csv")
        self.assertTrue(mbi["assignment_method"].str.contains("direct OCWD table").all())

    def test_every_raw_download_has_url_date_and_valid_hash(self) -> None:
        manifest = pd.read_csv(ROOT / "outputs/provenance/RAW_DOWNLOAD_HASH_MANIFEST.csv")
        raw_files = sorted(path.relative_to(ROOT / "data/raw").as_posix() for path in (ROOT / "data/raw").rglob("*") if path.is_file() and path.name != ".gitkeep")
        self.assertEqual(sorted(manifest["local_path"].tolist()), raw_files)
        for row in manifest.itertuples(index=False):
            self.assertTrue(str(row.official_url).startswith("https://"))
            self.assertTrue(str(row.accessed_at))
            digest = hashlib.sha256((ROOT / "data/raw" / row.local_path).read_bytes()).hexdigest()
            self.assertEqual(digest, row.sha256)

    def test_pdf_extracts_have_page_and_table_provenance(self) -> None:
        paths = [
            ROOT / "outputs/tables/OCWD_HISTORICAL_RECHARGE_JULY_2009_PERCOLATION.csv",
            ROOT / "outputs/tables/OCWD_HISTORICAL_RECHARGE_ACCOUNTING_DIAGNOSTIC.csv",
            ROOT / "outputs/tables/TRACER_VALIDATION_REGISTRY.csv",
            ROOT / "outputs/tables/OCWD_MBI_2023_MONTHLY_INJECTION.csv",
            ROOT / "outputs/tables/OCWD_MBI_2023_REPORTED_TOTALS.csv",
        ]
        for path in paths:
            frame = pd.read_csv(path)
            self.assertTrue(any(column in frame.columns for column in ("pdf_page", "pdf_pages")))
            self.assertTrue(any(column in frame.columns for column in ("pdf_table", "pdf_tables", "source_citation")))

    def test_historical_recharge_accounting_reconciles(self) -> None:
        percolation = pd.read_csv(ROOT / "outputs/tables/OCWD_HISTORICAL_RECHARGE_JULY_2009_PERCOLATION.csv")
        accounting = pd.read_csv(ROOT / "outputs/tables/OCWD_HISTORICAL_RECHARGE_ACCOUNTING_DIAGNOSTIC.csv")
        self.assertAlmostEqual(percolation["calculated_percolation_af"].sum(), 12573.0)
        self.assertEqual(float(accounting.loc[accounting["field"].eq("calculated_percolation"), "value_af"].iloc[0]), 12573.0)

    def test_current_report_key_values_are_exact(self) -> None:
        reports = pd.read_csv(ROOT / "outputs/tables/OCWD_RECENT_WATER_RESOURCES_REPORT_FIELDS.csv")
        july = reports.loc[reports["report_month"].eq("2026-07")].set_index("field")
        self.assertEqual(float(july.loc["GROUNDWATER PRODUCTION", "monthly_value"]), 28759.0)
        self.assertEqual(float(july.loc["GWRS Water to Mid-Basin Injection Wells", "monthly_value"]), 492.0)
        self.assertEqual(float(july.loc["Change in Groundwater Storage", "monthly_value"]), -10184.0)
        self.assertEqual(float(july.loc["Incidental Recharge (estimated)", "monthly_value"]), 700.0)

    def test_mbi_published_totals_preserve_rounding_difference(self) -> None:
        totals = pd.read_csv(ROOT / "outputs/tables/OCWD_MBI_2023_REPORTED_TOTALS.csv").set_index("quantity")
        self.assertEqual(float(totals.loc["total_injection_mg", "published_annual_total"]), 2395.35)
        self.assertEqual(float(totals.loc["total_injection_af", "published_annual_total"]), 7351.06)
        self.assertEqual(float(totals.loc["total_backwash_mg", "published_annual_total"]), 18.12)
        self.assertEqual(float(totals.loc["total_backwash_af", "published_annual_total"]), 55.60)
        self.assertTrue(totals["rounding_difference"].abs().le(0.011).all())

    def test_evidence_taxonomy_is_exact(self) -> None:
        config = yaml.safe_load((ROOT / "config/evidence_classes.yaml").read_text())
        self.assertEqual(set(config["allowed_evidence_classes"]), ALLOWED_EVIDENCE)
        registry = pd.read_csv(ROOT / "sources/source_registry.csv")
        self.assertTrue(set(registry["measurement_class"]).issubset(ALLOWED_EVIDENCE))

    def test_gate_and_tier_statuses_are_explicit(self) -> None:
        status = json.loads((ROOT / "outputs/feasibility/FINAL_FEASIBILITY_STATUS.json").read_text())
        self.assertIn(status["PUBLIC_DATA_ONLY_TIER"], {"TIER_A", "TIER_B", "TIER_C"})
        self.assertEqual(status["EXPECTED_STATUS_WITH_OCWD_WRMS"], "TIER_A_CANDIDATE")
        gate_results = {row["gate"]: row["status"] for row in status["gate_results"]}
        self.assertEqual(set(gate_results), {f"G{i}" for i in range(1, 11)})
        self.assertTrue(set(gate_results.values()).issubset({"PASS", "PARTIAL", "FAIL", "PENDING_REQUEST"}))


if __name__ == "__main__":
    unittest.main()
