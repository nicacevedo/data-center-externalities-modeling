"""Scientific and reproducibility guards for OCWD GW-1C."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
GW1A = REPO / "other_sources/ocwd_groundwater_gw1_preflight"
FEAS = REPO / "other_sources/ocwd_groundwater_feasibility"
GW1B = REPO / "other_sources/ocwd_groundwater_gw1b"
sys.path.insert(0, str(ROOT))

from src.gw1c import (  # noqa: E402
    BASELINE_COMMIT,
    B1_FEATURES,
    CLIMATE_FEATURES,
    MODEL_FEATURES,
    PRADO_FEATURES,
    sha256_file,
    tree_snapshot,
)


class GW1CGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.status = json.loads((ROOT / "outputs/FINAL_GW1C_STATUS.json").read_text())
        cls.transitions = pd.read_parquet(ROOT / "data/derived/GW1C_TRANSITIONS.parquet")
        cls.features = pd.read_parquet(ROOT / "data/derived/GW1C_CLIMATE_FEATURES.parquet")
        cls.predictions = pd.read_parquet(ROOT / "data/derived/GW1C_PRIMARY_TEST_PREDICTIONS.parquet")
        cls.fit_samples = pd.read_parquet(ROOT / "data/derived/GW1C_FIT_SAMPLE_LEDGER.parquet")
        cls.audit = pd.read_csv(ROOT / "outputs/tables/GW1C_FITTED_MODEL_AUDIT.csv")

    def test_01_frozen_parent_modules_are_unchanged(self) -> None:
        start = json.loads((ROOT / "outputs/provenance/FROZEN_PARENT_INTEGRITY_START.json").read_text())
        end = json.loads((ROOT / "outputs/provenance/FROZEN_PARENT_INTEGRITY_END.json").read_text())
        self.assertEqual(start["status"], "PASS")
        self.assertEqual(end["status"], "PASS")
        self.assertTrue(end["matches_start_snapshot"])
        for label, parent in [("feasibility", FEAS), ("gw1a", GW1A)]:
            current_sha, current_files = tree_snapshot(parent)
            self.assertEqual(start["parents"][label]["current_tree_sha256"], current_sha)
            self.assertEqual(start["parents"][label]["files"], current_files)
            diff = subprocess.run(["git", "diff", "--quiet", BASELINE_COMMIT, "--", parent.relative_to(REPO)], cwd=REPO)
            self.assertEqual(diff.returncode, 0)

    def test_02_material_dependency_hashes_are_exact(self) -> None:
        manifest = pd.read_csv(ROOT / "outputs/provenance/GW1C_DEPENDENCY_MANIFEST.csv")
        self.assertTrue(manifest["worktree_matches_frozen"].astype(bool).all())
        self.assertEqual(set(manifest["baseline_commit"]), {BASELINE_COMMIT})
        for row in manifest.itertuples(index=False):
            path = REPO / row.path
            self.assertTrue(path.exists(), row.path)
            self.assertEqual(sha256_file(path), row.worktree_sha256, row.path)

    def test_03_b1_reproduction_passes_before_climate(self) -> None:
        gate = json.loads((ROOT / "outputs/provenance/B1_REPRODUCTION.json").read_text())
        self.assertEqual(gate["status"], "PASS")
        self.assertTrue(gate["must_pass_before_climate_modeling"])
        prediction_differences = [r["difference"] for r in gate["comparisons"] if r["metric"] == "prediction_max_abs_difference_ft"]
        self.assertEqual(prediction_differences, [0.0, 0.0])
        self.assertEqual(gate["model_features"], B1_FEATURES)

    def test_04_frozen_spatial_folds_and_temporal_splits_are_reused(self) -> None:
        manifest = pd.read_csv(ROOT / "outputs/provenance/GW1C_DEPENDENCY_MANIFEST.csv")
        fold_row = manifest.loc[manifest["logical_input"].eq("gw1a_spatial_folds")].iloc[0]
        self.assertEqual(fold_row.worktree_sha256, sha256_file(GW1A / "config/SPATIAL_FOLDS.csv"))
        self.assertEqual(set(self.fit_samples["temporal_split"]), {"TRAIN"})
        self.assertLessEqual(pd.to_datetime(self.fit_samples["target_month"]).max(), pd.Timestamp("1996-09-01"))
        self.assertGreaterEqual(pd.to_datetime(self.predictions["target_month"]).min(), pd.Timestamp("1997-11-01"))

    def test_05_no_head_is_interpolated_or_changed(self) -> None:
        frozen = pd.read_parquet(GW1A / "data/derived/HEAD_TRANSITIONS.parquet")
        joined = self.transitions[["transition_id", "t_prev", "t_target", "h_prev", "h_target", "delta_h"]].merge(
            frozen[["transition_id", "t_prev", "t_target", "h_prev", "h_target", "delta_h"]],
            on="transition_id", suffixes=("_gw1c", "_gw1a"), validate="one_to_one",
        )
        self.assertEqual(len(joined), len(frozen))
        for column in ["h_prev", "h_target", "delta_h"]:
            self.assertTrue(np.array_equal(joined[f"{column}_gw1c"].to_numpy(), joined[f"{column}_gw1a"].to_numpy()))
        self.assertTrue((pd.to_datetime(joined["t_prev_gw1c"]) == pd.to_datetime(joined["t_prev_gw1a"])).all())
        self.assertTrue((pd.to_datetime(joined["t_target_gw1c"]) == pd.to_datetime(joined["t_target_gw1a"])).all())

    def test_06_climate_features_and_lag_windows_are_frozen(self) -> None:
        protocol = yaml.safe_load((ROOT / "config/analysis_protocol.yaml").read_text())
        self.assertEqual(protocol["climate_features"]["fixed_order"], CLIMATE_FEATURES)
        self.assertEqual(protocol["climate_features"]["alternative_lag_search"], "prohibited")
        complete = self.features.loc[self.features["climate_feature_complete"]].copy()
        origin = pd.to_datetime(complete["origin_date"])
        target = pd.to_datetime(complete["target_date"])
        self.assertTrue((pd.to_datetime(complete["interval_start_date"]) == origin + pd.Timedelta(days=1)).all())
        self.assertTrue((pd.to_datetime(complete["interval_end_date"]) == target).all())
        self.assertTrue((pd.to_datetime(complete["pre30_start_date"]) == origin - pd.Timedelta(days=30)).all())
        self.assertTrue((pd.to_datetime(complete["pre30_end_date"]) == origin - pd.Timedelta(days=1)).all())
        self.assertTrue((pd.to_datetime(complete["pre90_start_date"]) == origin - pd.Timedelta(days=90)).all())
        self.assertTrue((pd.to_datetime(complete["pre90_end_date"]) == origin - pd.Timedelta(days=1)).all())
        self.assertTrue((complete["pre30_observed_pr_days"] == 30).all())
        self.assertTrue((complete["pre90_observed_et0_days"] == 90).all())

    def test_07_grid_mapping_uses_coordinates_and_availability_only(self) -> None:
        crosswalk = pd.read_csv(ROOT / "data/derived/WELL_GRIDMET_CELL_CROSSWALK.csv")
        self.assertFalse(crosswalk["groundwater_outcomes_used"].astype(bool).any())
        self.assertEqual(set(crosswalk["mapping_inputs"]), {"well_latitude|well_longitude|fixed_grid_coordinates"})
        daily = pd.read_parquet(ROOT / "data/derived/GRIDMET_OCWD_DAILY.parquet")
        selected = daily.loc[daily["cell_id"].isin(set(crosswalk["cell_id"]))]
        self.assertFalse(selected[["pr_mm", "pet_mm"]].isna().any().any())

    def test_08_raw_climate_sources_are_url_date_and_hash_traced(self) -> None:
        manifest = pd.read_csv(ROOT / "outputs/provenance/GRIDMET_RAW_DOWNLOAD_MANIFEST.csv")
        self.assertEqual(len(manifest), 20)
        self.assertTrue(manifest["url"].str.startswith("https://tds-proxy.nkn.uidaho.edu/thredds/dodsC/MET/").all())
        self.assertTrue(manifest["accessed_at_utc"].notna().all())
        self.assertTrue(manifest["sha256"].str.fullmatch(r"[0-9a-f]{64}").all())
        for row in manifest.itertuples(index=False):
            path = ROOT / row.path
            self.assertEqual(path.stat().st_size, int(row.bytes))
            self.assertEqual(sha256_file(path), row.sha256)

    def test_09_only_train_enters_fitting_and_scaling(self) -> None:
        self.assertEqual(set(self.audit["fit_split"]), {"TRAIN"})
        self.assertFalse(self.audit["validation_used"].astype(bool).any())
        self.assertFalse(self.audit["test_used"].astype(bool).any())
        self.assertEqual(set(self.audit["hyperparameter_search"]), {"NONE"})
        self.assertTrue((self.audit["standardized_design_condition_number"] < 1e8).all())
        self.assertEqual(set(self.audit["model"]), {"B1", "B1C", "B1CH"})
        allowed = {"INTERCEPT", *MODEL_FEATURES["B1"], *MODEL_FEATURES["B1C"], *MODEL_FEATURES["B1CH"]}
        self.assertTrue(set(self.audit["feature"]).issubset(allowed))

    def test_10_prado_definition_and_role_are_preserved(self) -> None:
        protocol = yaml.safe_load((ROOT / "config/analysis_protocol.yaml").read_text())
        self.assertEqual(protocol["prado_features"]["fixed_order"], PRADO_FEATURES)
        self.assertEqual(protocol["prado_features"]["role"], "PUBLIC_BACKGROUND_HYDROLOGY_NOT_MANAGED_RECHARGE")
        self.assertEqual(self.status["PRADO_AFTER_CLIMATE_SKILL"], "NONE")
        self.assertEqual(self.status["GW1B_BACKGROUND_MODEL"], "B1C")

    def test_11_no_pumping_network_or_reserved_asset_enters_models(self) -> None:
        lower_features = [x.lower() for x in self.audit["feature"]]
        for word in ["pump", "recharge", "tracer", "mbi", "network", "neighbor"]:
            self.assertFalse(any(word in feature for feature in lower_features), word)
        self.assertEqual(self.status["reserved_external_validation"]["tracer"], "RESERVED_NOT_USED")
        self.assertIn("B7", self.status["modeling_not_run"])
        source = (ROOT / "src/gw1c.py").read_text().lower()
        for forbidden in ["import networkx", "import torch", "import tensorflow", "import flopy", "xgboost", "lightgbm"]:
            self.assertNotIn(forbidden, source)

    def test_12_claims_are_oos_and_use_well_bootstrap(self) -> None:
        comparisons = pd.read_csv(ROOT / "outputs/metrics/GW1C_INCREMENTAL_COMPARISONS_BOOTSTRAP.csv")
        self.assertEqual(set(comparisons["resampling_unit"]), {"well"})
        self.assertEqual(set(comparisons["bootstrap_resamples"]), {1000})
        self.assertEqual(set(comparisons["regime"]), {"T1_TEMPORAL_OOS", "T2_SPATIOTEMPORAL_OOS"})
        self.assertEqual(self.status["CLIMATE_INCREMENTAL_SKILL"], "PARTIAL")

    def test_13_gw1b_is_waiting_and_protocol_is_frozen(self) -> None:
        waiting = json.loads((GW1B / "outputs/FINAL_GW1B_STATUS.json").read_text())
        protocol = yaml.safe_load((GW1B / "config/GW1B_PROTOCOL_AMENDMENT_20260904.yaml").read_text())
        self.assertEqual(waiting["GW1B_DATA_STATUS"], "WAITING_FOR_WRMS")
        self.assertEqual(waiting["models_fit_in_GW1B"], [])
        self.assertEqual(protocol["background_model"]["frozen_definition"], "B1C")
        self.assertEqual(protocol["primary_contrasts"]["network_added_value"], "B7_minus_B6")


if __name__ == "__main__":
    unittest.main()

