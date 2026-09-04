"""Scientific guards for the pre-registered OCWD GW-1A benchmark."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.cluster import KMeans


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
FEAS = REPO / "other_sources" / "ocwd_groundwater_feasibility"
sys.path.insert(0, str(ROOT))

from src.gw1a import (  # noqa: E402
    FROZEN_COMMIT,
    INDEPENDENT_ORIGIN,
    MODEL_FEATURES,
    OCWD_ORIGIN,
    SEED,
    deterministic_tree_snapshot,
    sha256_file,
)


class GW1AGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.transitions = pd.read_parquet(ROOT / "data/derived/HEAD_TRANSITIONS.parquet")
        for col in ["t_prev", "t_target", "target_month", "interval_max_source_date", "antecedent_30d_max_source_date"]:
            cls.transitions[col] = pd.to_datetime(cls.transitions[col])
        cls.fit_samples = pd.read_parquet(ROOT / "data/derived/FIT_SAMPLE_LEDGER.parquet")
        cls.predictions = pd.read_parquet(ROOT / "data/derived/PRIMARY_TEST_PREDICTIONS.parquet")
        cls.status = json.loads((ROOT / "outputs/FINAL_GW1A_STATUS.json").read_text())

    def test_01_frozen_feasibility_package_is_byte_identical(self) -> None:
        integrity = json.loads((ROOT / "outputs/provenance/SOURCE_FEASIBILITY_PACKAGE_INTEGRITY.json").read_text())
        tree_sha, current_files = deterministic_tree_snapshot(FEAS)
        self.assertEqual(integrity["current_tree_sha256"], tree_sha)
        self.assertEqual(integrity["files"], current_files)
        self.assertEqual(integrity["frozen_commit"], FROZEN_COMMIT)
        self.assertEqual(integrity["status"], "PASS")
        diff = subprocess.run(
            ["git", "diff", "--quiet", FROZEN_COMMIT, "--", "other_sources/ocwd_groundwater_feasibility"],
            cwd=REPO,
        )
        self.assertEqual(diff.returncode, 0)

    def test_02_dependency_hashes_cannot_drift_silently(self) -> None:
        manifest = pd.read_csv(ROOT / "outputs/provenance/GW1A_DEPENDENCY_MANIFEST.csv")
        self.assertTrue(manifest["worktree_matches_frozen"].astype(bool).all())
        for row in manifest.itertuples(index=False):
            path = REPO / row.path
            self.assertTrue(path.exists(), row.path)
            self.assertEqual(sha256_file(path), row.worktree_sha256, row.path)
            expected = row.frozen_blob_sha256 if bool(row.tracked_at_frozen_commit) else row.recorded_package_sha256
            self.assertEqual(row.worktree_sha256, expected, row.path)

    def test_03_dense_window_and_holdouts_are_exactly_frozen(self) -> None:
        window = json.loads((ROOT / "outputs/cohorts/PRIMARY_WINDOW.json").read_text())
        self.assertEqual((window["primary_start_month"], window["primary_end_month"], window["n_consecutive_months"]), ("1991-10-01", "1998-11-01", 86))
        self.assertGreaterEqual(window["minimum_monthly_wells"], 50)
        self.assertFalse(window["date_selection_used_prediction_accuracy"])
        split = json.loads((ROOT / "outputs/protocol/TEMPORAL_SPLIT.json").read_text())
        self.assertEqual((split["TRAIN"]["n_months"], split["VALIDATION"]["n_months"], split["TEST"]["n_months"]), (60, 13, 13))
        self.assertEqual(split["TRAIN"]["end"], "1996-09-01")
        self.assertEqual(split["VALIDATION"]["start"], "1996-10-01")
        self.assertEqual(split["TEST"]["start"], "1997-11-01")

    def test_04_monthly_matrix_retains_missing_and_matches_observed_medians(self) -> None:
        matrix = pd.read_parquet(ROOT / "data/derived/MONTHLY_HEAD_MATRIX.parquet")
        mask = pd.read_parquet(ROOT / "data/derived/MONTHLY_OBSERVATION_MASK.parquet")
        self.assertEqual(matrix.shape, mask.shape)
        self.assertTrue(np.array_equal(matrix["site_code"].to_numpy(), mask["site_code"].to_numpy()))
        month_cols = [c for c in matrix.columns if c != "site_code"]
        self.assertTrue(np.array_equal(matrix[month_cols].notna().to_numpy(), mask[month_cols].to_numpy(dtype=bool)))
        self.assertGreater(matrix[month_cols].isna().sum().sum(), 0)

        heads = pd.read_parquet(FEAS / "data/derived/DWR_OCWD_HEAD_OBSERVATIONS.parquet")
        dt = pd.to_datetime(heads["measurement_datetime_pst"])
        observed = heads.loc[
            heads["usable_head"].astype(bool) & dt.between("1991-10-01", "1998-11-30 23:59:59")
        ].copy()
        observed["month"] = dt.loc[observed.index].dt.strftime("%Y-%m")
        medians = observed.groupby(["site_code", "month"], as_index=False)["groundwater_elevation_ft_navd88"].median().rename(columns={"groundwater_elevation_ft_navd88": "expected"})
        long = matrix.melt(id_vars="site_code", var_name="month", value_name="actual").dropna(subset=["actual"])
        checked = long.merge(medians, on=["site_code", "month"], how="outer", validate="one_to_one")
        self.assertFalse(checked[["actual", "expected"]].isna().any().any())
        self.assertTrue(np.allclose(checked["actual"], checked["expected"], rtol=0, atol=1e-12))

    def test_05_transition_targets_are_observed_not_interpolated(self) -> None:
        heads = pd.read_parquet(FEAS / "data/derived/DWR_OCWD_HEAD_OBSERVATIONS.parquet")
        heads = heads.loc[heads["usable_head"].astype(bool)].copy()
        heads["measurement_datetime"] = pd.to_datetime(heads["measurement_datetime_pst"])
        exact = heads.groupby(["site_code", "measurement_datetime"], as_index=False)["groundwater_elevation_ft_navd88"].median()
        target = self.transitions[["transition_id", "site_code", "t_target", "h_target"]].merge(
            exact, left_on=["site_code", "t_target"], right_on=["site_code", "measurement_datetime"], validate="many_to_one"
        )
        previous = self.transitions[["transition_id", "site_code", "t_prev", "h_prev"]].merge(
            exact, left_on=["site_code", "t_prev"], right_on=["site_code", "measurement_datetime"], validate="many_to_one"
        )
        self.assertEqual(len(target), len(self.transitions))
        self.assertEqual(len(previous), len(self.transitions))
        self.assertTrue(np.allclose(target["h_target"], target["groundwater_elevation_ft_navd88"], rtol=0, atol=1e-12))
        self.assertTrue(np.allclose(previous["h_prev"], previous["groundwater_elevation_ft_navd88"], rtol=0, atol=1e-12))
        self.assertTrue((self.transitions["delta_days"] > 0).all())

    def test_06_test_and_validation_never_enter_fitting_or_scaling(self) -> None:
        self.assertEqual(set(self.fit_samples["temporal_split"]), {"TRAIN"})
        self.assertLessEqual(pd.to_datetime(self.fit_samples["target_month"]).max(), pd.Timestamp("1996-09-01"))
        audit = pd.read_csv(ROOT / "outputs/tables/FITTED_MODEL_AUDIT.csv")
        self.assertEqual(set(audit["fit_split"]), {"TRAIN"})
        self.assertFalse(audit["validation_used"].astype(bool).any())
        self.assertFalse(audit["test_used"].astype(bool).any())
        self.assertEqual(set(audit["hyperparameter_search"]), {"NONE"})
        self.assertGreaterEqual(pd.to_datetime(self.predictions["target_month"]).min(), pd.Timestamp("1997-11-01"))

    def test_07_spatial_folds_use_coordinates_only_and_are_reproducible(self) -> None:
        folds = pd.read_csv(ROOT / "config/SPATIAL_FOLDS.csv").sort_values("site_code").reset_index(drop=True)
        forbidden = {"head", "residual", "skill", "screen", "pumping", "recharge", "outcome"}
        for column in folds.columns:
            self.assertFalse(any(word in column.lower() for word in forbidden), column)
        self.assertEqual(set(folds["fold_inputs"]), {"easting_m|northing_m"})
        km = KMeans(n_clusters=5, random_state=SEED, n_init=50, algorithm="lloyd")
        raw = km.fit_predict(folds[["easting_m", "northing_m"]].to_numpy())
        centers = pd.DataFrame(km.cluster_centers_, columns=["easting_m", "northing_m"])
        order = centers.sort_values(["easting_m", "northing_m"]).index.tolist()
        mapping = {old: i + 1 for i, old in enumerate(order)}
        reproduced = np.asarray([mapping[int(x)] for x in raw])
        self.assertTrue(np.array_equal(reproduced, folds["spatial_fold"].to_numpy()))
        for fit_id, group in self.fit_samples.loc[self.fit_samples["regime"].eq("T2_SPATIOTEMPORAL_OOS")].groupby("fit_id"):
            held = int(str(group["held_out_spatial_fold"].iloc[0]))
            self.assertFalse(group["spatial_fold"].eq(held).any(), fit_id)

    def test_08_independent_agency_observations_never_enter_tuning(self) -> None:
        self.assertEqual(set(self.fit_samples["transition_independence_class"]), {OCWD_ORIGIN})
        self.assertNotIn(INDEPENDENT_ORIGIN, set(self.fit_samples["transition_independence_class"]))
        independent = json.loads((ROOT / "outputs/protocol/INDEPENDENT_AGENCY_HOLDOUT.json").read_text())
        self.assertEqual(independent["primary_le_120_transition_count"], 0)
        self.assertFalse(independent["T3_feasible_within_frozen_primary_window"])
        self.assertIn("NOT_FEASIBLE", self.status["evaluation"]["T3"])

    def test_09_no_future_after_target_hydrologic_value(self) -> None:
        complete = self.transitions.loc[self.transitions["hydrologic_feature_complete"]].copy()
        target_date = complete["t_target"].dt.normalize()
        self.assertTrue((complete["interval_max_source_date"] < target_date).all())
        self.assertTrue((complete["antecedent_30d_max_source_date"] < target_date).all())
        self.assertTrue((complete["antecedent_30d_max_source_date"] == target_date - pd.Timedelta(days=1)).all())
        self.assertTrue((complete["interval_observed_days"] == complete["interval_expected_days"]).all())
        self.assertTrue((complete["antecedent_30d_observed_days"] == 30).all())
        incomplete = self.transitions.loc[self.transitions["gap_le_120_days"] & ~self.transitions["hydrologic_feature_complete"]]
        self.assertEqual(len(incomplete), 58)
        self.assertTrue(incomplete["interval_expected_days"].eq(0).all())
        self.assertTrue(incomplete["interval_observed_days"].eq(0).all())
        self.assertTrue(incomplete["antecedent_30d_observed_days"].eq(30).all())

    def test_10_prado_is_background_hydrology_not_managed_recharge(self) -> None:
        self.assertEqual(set(self.transitions["hydrologic_forcing_role"]), {"PUBLIC_BACKGROUND_HYDROLOGY_NOT_MANAGED_RECHARGE"})
        protocol = yaml.safe_load((ROOT / "config/analysis_protocol.yaml").read_text())
        self.assertEqual(protocol["hydrologic_features"]["role"], "PUBLIC_BACKGROUND_HYDROLOGY_NOT_MANAGED_RECHARGE")

    def test_11_tracer_and_mbi_assets_are_reserved_outside_fitting(self) -> None:
        reserved = json.loads((ROOT / "outputs/protocol/RESERVED_EXTERNAL_VALIDATION.json").read_text())
        self.assertEqual(reserved["status"], "RESERVED_UNTOUCHED_OUTSIDE_FITTING_TUNING_AND_STRUCTURE_SELECTION")
        for field in ["used_for_features", "used_for_fitting", "used_for_tuning", "used_for_model_selection"]:
            self.assertFalse(reserved[field])
        features = set(pd.read_csv(ROOT / "outputs/tables/FITTED_MODEL_AUDIT.csv")["feature"].str.lower())
        self.assertFalse(any("tracer" in x or "mbi" in x for x in features))

    def test_12_no_pumping_or_groundwater_network_model_is_fit(self) -> None:
        audit = pd.read_csv(ROOT / "outputs/tables/FITTED_MODEL_AUDIT.csv")
        self.assertEqual(set(audit["model"]), {"B1", "B2", "B3"})
        allowed = {"INTERCEPT", *MODEL_FEATURES["B1"], *MODEL_FEATURES["B2"], *MODEL_FEATURES["B3"]}
        self.assertTrue(set(audit["feature"]).issubset(allowed))
        self.assertFalse(any("pump" in x.lower() for x in audit["feature"]))
        specs = json.loads((ROOT / "outputs/protocol/B0_B3_MODEL_SPECIFICATIONS.json").read_text())
        self.assertEqual(specs["scope"], "NO_PUMPING_NO_WRMS")
        source = (ROOT / "src/gw1a.py").read_text().lower()
        for forbidden_import in ["import networkx", "import torch", "import tensorflow", "import flopy", "from flopy", "xgboost", "lightgbm"]:
            self.assertNotIn(forbidden_import, source)
        forbidden_outputs = [p for p in ROOT.rglob("*") if p.is_file() and any(x in p.name.lower() for x in ["a_matrix", "b_matrix", "modflow_calibration", "gnn_model"])]
        self.assertEqual(forbidden_outputs, [])

    def test_13_model_ranking_is_out_of_sample_only(self) -> None:
        ranking = pd.read_csv(ROOT / "outputs/tables/OOS_MODEL_RANKING.csv")
        self.assertEqual(set(ranking["ranking_data_split"]), {"TEST_ONLY"})
        self.assertEqual(ranking.iloc[0]["model"], self.status["STRONGEST_NO_PUMPING_BASELINE"])
        audit = json.loads((ROOT / "outputs/protocol/VALIDATION_AND_TEST_NONUSE_AUDIT.json").read_text())
        self.assertFalse(audit["test_used_for_fitting_scaling_or_tuning"])
        self.assertTrue(audit["test_used_for_final_OOS_metrics_and_reporting_only"])

    def test_14_well_level_bootstrap_not_transition_iid(self) -> None:
        for name in ["BOOTSTRAP_DIFFERENCES_VS_PERSISTENCE.csv", "BOOTSTRAP_B3_VS_B2.csv"]:
            frame = pd.read_csv(ROOT / "outputs/tables" / name)
            self.assertEqual(set(frame["resampling_unit"]), {"well"})
            self.assertEqual(set(frame["bootstrap_resamples"]), {1000})
            self.assertTrue({"MAE_skill_ci95_low", "MAE_skill_ci95_high", "RMSE_skill_ci95_low", "RMSE_skill_ci95_high"}.issubset(frame.columns))

    def test_15_gw1b_and_placebos_are_preregistered_but_not_run(self) -> None:
        prereg = yaml.safe_load((ROOT / "GW1B_PREREGISTRATION.yaml").read_text())
        self.assertEqual(list(prereg["ladder"]), ["B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7"])
        self.assertEqual(prereg["primary_comparisons"]["pumping_predictive_information"], "B5_minus_B4")
        self.assertEqual(prereg["primary_comparisons"]["network_added_value"], "B7_minus_B5")
        self.assertEqual(prereg["status"], "FROZEN_BEFORE_WRMS_RECEIPT")
        self.assertFalse(any("placebo" in p.name.lower() and "preregistration" not in p.name.lower() for p in (ROOT / "data").rglob("*") if p.is_file()))

    def test_16_final_status_preserves_identification_limits(self) -> None:
        self.assertEqual(self.status["GW1A_STATUS"], "PASS")
        self.assertEqual(self.status["READY_FOR_GW1B"], "NO_UNTIL_WRMS")
        scientific = self.status["scientific_identification"]
        self.assertEqual(scientific["pumping_response"], "UNIDENTIFIED_WRMS_PUMPING_ABSENT")
        self.assertEqual(scientific["managed_recharge_increment"], "UNIDENTIFIED_WRMS_RECHARGE_ABSENT")
        self.assertEqual(scientific["network_added_value"], "UNIDENTIFIED_NO_NETWORK_ESTIMATED")
        self.assertFalse(scientific["operational_forecast"])


if __name__ == "__main__":
    unittest.main()
