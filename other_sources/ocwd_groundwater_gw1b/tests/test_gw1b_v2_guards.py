"""Readiness and scientific guards for frozen GW-1B v2."""

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
sys.path.insert(0, str(ROOT))

from src.gw1b_v2 import (  # noqa: E402
    BASELINE_COMMIT,
    B6_MODEL_FEATURES_BY_LENGTH,
    BC_FEATURES,
    B4_TOTAL_FEATURES,
    B5_PUMPING_FEATURES,
    B6_SPATIAL_FEATURES,
    MODEL_FEATURES,
    PRIMARY_CROSSWALK_CLASSES,
    SPATIAL_LENGTHS_KM,
    S_STAR_REQUIRED_FEATURES,
    WRMSValidationError,
    allocate_monthly_forcing_to_transitions,
    build_common_support,
    normalize_volume,
    proportional_month_exposure,
    sha256_file,
    spatial_identity_placebo,
    temporal_pumping_placebo,
    validate_delivery_tables,
    validate_nested_hierarchy,
    verify_frozen_parents,
    verify_monthly_conservation,
    verify_previous_protocol,
)


def valid_tables() -> dict[str, pd.DataFrame]:
    well = pd.DataFrame({
        "well_id": ["W1"], "well_name": ["Well 1"],
        "easting_m": [400000.0], "northing_m": [3740000.0], "coordinate_crs": ["EPSG:26911"],
        "active_start": ["1990-01-01"], "active_end": ["2000-12-31"],
        "screen_top": [100.0], "screen_bottom": [200.0], "screen_unit": ["ft"],
        "aquifer_id": ["AUTHORITATIVE_A"], "model_layer_id": ["L1"],
        "evidence_class": ["REPORTED_MEASURED"], "qa_flag": ["OK"], "revision_flag": ["CURRENT"],
    })
    pumping = pd.DataFrame({
        "well_id": ["W1", "W1"], "month": ["1995-01-01", "1995-02-01"],
        "volume": [325851.429, 1.0], "volume_unit": ["gallons", "acre_feet"],
        "measurement_class": ["MEASURED_REPORTED", "ALLOCATED"],
        "qa_flag": ["OK", "OK"], "revision_flag": ["CURRENT", "CURRENT"],
    })
    common_location = {
        "easting_m": [401000.0, 401000.0], "northing_m": [3741000.0, 3741000.0],
        "coordinate_crs": ["EPSG:26911", "EPSG:26911"],
        "active_start": ["1990-01-01", "1990-01-01"], "active_end": ["2000-12-31", "2000-12-31"],
        "aquifer_id": ["AUTHORITATIVE_A", "AUTHORITATIVE_A"], "model_layer_id": ["L1", "L1"],
        "qa_flag": ["OK", "OK"], "revision_flag": ["CURRENT", "CURRENT"],
    }
    recharge = pd.DataFrame({
        "facility_id": ["R1", "R1"], "month": ["1995-01-01", "1995-02-01"],
        "volume": [10.0, 11.0], "volume_unit": ["acre_feet", "acre_feet"],
        "measurement_class": ["CALCULATED", "CALCULATED"], **common_location,
    })
    injection = pd.DataFrame({
        "well_id": ["I1", "I1"], "month": ["1995-01-01", "1995-02-01"],
        "volume": [2.0, 3.0], "volume_unit": ["acre_feet", "acre_feet"],
        "measurement_class": ["MEASURED_REPORTED", "MEASURED_REPORTED"], **common_location,
    })
    crosswalk = pd.DataFrame({
        "source_table": ["monthly_pumping", "managed_recharge", "injection", "monthly_pumping"],
        "source_id": ["W1", "R1", "I1", "W_AMBIG"],
        "canonical_id": ["W1", "R1", "I1", ""],
        "match_status": ["EXACT", "HIGH_CONFIDENCE", "EXACT", "AMBIGUOUS"],
        "match_basis": ["agency ID", "agency crosswalk", "agency ID", "insufficient metadata"],
    })
    return {"well_master": well, "monthly_pumping": pumping, "managed_recharge": recharge, "injection": injection, "id_crosswalk": crosswalk}


class GW1BV2Guards(unittest.TestCase):
    def test_01_frozen_parents_and_previous_protocol_are_unchanged(self) -> None:
        integrity = verify_frozen_parents()
        self.assertEqual(integrity["status"], "PASS")
        self.assertEqual(set(integrity["parents"]), {"feasibility", "gw1a", "gw1c"})
        self.assertEqual(verify_previous_protocol()["status"], "PASS")
        for parent in integrity["parents"].values():
            diff = subprocess.run(["git", "diff", "--quiet", BASELINE_COMMIT, "--", parent["path"]], cwd=REPO)
            self.assertEqual(diff.returncode, 0)

    def test_02_protocol_is_strictly_nested_and_B6_retains_B5(self) -> None:
        result = validate_nested_hierarchy()
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(set(MODEL_FEATURES["BC"]) < set(MODEL_FEATURES["B4"]))
        self.assertTrue(set(MODEL_FEATURES["B4"]) < set(MODEL_FEATURES["B5"]))
        for length in SPATIAL_LENGTHS_KM:
            self.assertTrue(set(MODEL_FEATURES["B5"]) < set(B6_MODEL_FEATURES_BY_LENGTH[length]))
            self.assertTrue(set(B4_TOTAL_FEATURES + B5_PUMPING_FEATURES).issubset(B6_MODEL_FEATURES_BY_LENGTH[length]))
            self.assertEqual(len(B6_MODEL_FEATURES_BY_LENGTH[length]), 28)
        self.assertEqual(len(S_STAR_REQUIRED_FEATURES), 46)

    def test_03_climate_and_prado_decisions_are_frozen(self) -> None:
        status = json.loads((REPO / "other_sources/ocwd_groundwater_gw1_climate/outputs/FINAL_GW1C_STATUS.json").read_text())
        protocol = yaml.safe_load((ROOT / "config/GW1B_PROTOCOL_AMENDMENT_20260904_v2.yaml").read_text())
        self.assertEqual(status["GW1B_BACKGROUND_MODEL"], "B1C")
        self.assertEqual(status["PRADO_AFTER_CLIMATE_SKILL"], "NONE")
        self.assertEqual(protocol["background"]["features"], BC_FEATURES)
        self.assertEqual(protocol["background"]["Prado_primary_role"], "EXCLUDED")
        self.assertEqual(protocol["model"]["fit_split"], "TRAIN_ONLY")
        self.assertEqual(protocol["model"]["scaling_split"], "TRAIN_ONLY")
        self.assertEqual(protocol["spatial_exposure"]["selected_on"], "VALIDATION_ONLY")
        self.assertEqual(protocol["spatial_exposure"]["TEST_selection_use"], "prohibited")
        self.assertEqual(protocol["spatial_exposure"]["guessed_layers"], "prohibited")
        self.assertEqual(protocol["network"]["B7_execution"], "prohibited_in_this_task")

    def test_04_schema_validation_preserves_classes_and_excludes_ambiguous(self) -> None:
        validated, audit = validate_delivery_tables(valid_tables())
        self.assertEqual(audit["status"], "PASS")
        self.assertEqual(set(validated["monthly_pumping"]["measurement_class_original"]), {"MEASURED_REPORTED", "ALLOCATED"})
        self.assertEqual(set(validated["primary_id_crosswalk"]["match_status"]), PRIMARY_CROSSWALK_CLASSES)
        self.assertNotIn("AMBIGUOUS", set(validated["primary_id_crosswalk"]["match_status"]))
        self.assertEqual(audit["ambiguous_crosswalk_rows_excluded"], 1)

    def test_05_unit_conversion_is_explicit(self) -> None:
        frame = pd.DataFrame({"volume": [325851.429, 1.0, 1233.48183754752, 1.0], "volume_unit": ["gallons", "acre_feet", "cubic_meters", "million_gallons"]})
        result = normalize_volume(frame)
        self.assertTrue(np.allclose(result["volume_af"].iloc[:3], [1.0, 1.0, 1.0], atol=1e-12))
        self.assertAlmostEqual(result["volume_af"].iloc[3], 1_000_000 / 325851.429)
        self.assertTrue((result["volume_unit_original"] == frame["volume_unit"]).all())

    def test_06_duplicate_missing_negative_coordinate_and_activity_guards(self) -> None:
        cases = []
        duplicate = valid_tables(); duplicate["monthly_pumping"] = pd.concat([duplicate["monthly_pumping"], duplicate["monthly_pumping"].iloc[[0]]]); cases.append(duplicate)
        missing = valid_tables(); missing["monthly_pumping"].loc[0, "well_id"] = ""; cases.append(missing)
        negative = valid_tables(); negative["monthly_pumping"].loc[0, "volume"] = -1; cases.append(negative)
        coordinate = valid_tables(); coordinate["managed_recharge"].loc[1, "easting_m"] += 10; cases.append(coordinate)
        activity = valid_tables(); activity["injection"].loc[1, "active_start"] = "1991-01-01"; cases.append(activity)
        for tables in cases:
            with self.assertRaises(WRMSValidationError):
                validate_delivery_tables(tables)

    def test_07_monthly_overlap_arithmetic_and_conservation(self) -> None:
        monthly = pd.DataFrame({"month": pd.to_datetime(["1995-01-01"]), "volume_af": [310.0], "measurement_class": ["MEASURED_REPORTED"]})
        exposure, complete, classes = proportional_month_exposure(monthly, pd.Timestamp("1995-01-16"), pd.Timestamp("1995-01-31"))
        self.assertTrue(complete)
        self.assertAlmostEqual(exposure, 160.0, places=12)
        self.assertEqual(classes, ["MEASURED_REPORTED"])
        self.assertEqual(verify_monthly_conservation(monthly)["status"], "PASS")
        missing, complete, _ = proportional_month_exposure(monthly, pd.Timestamp("1995-01-01"), pd.Timestamp("1995-02-28"))
        self.assertFalse(complete)
        self.assertTrue(np.isnan(missing))

    def test_08_transition_exposure_is_derived_monthly_not_daily_observed(self) -> None:
        months = pd.date_range("1994-10-01", "1995-02-01", freq="MS")
        monthly = pd.DataFrame({
            "well_id": ["W1"] * len(months), "month": months, "volume_af": [31.0, 30.0, 31.0, 31.0, 28.0],
            "measurement_class": ["MEASURED_REPORTED"] * len(months),
        })
        transition = pd.DataFrame({"transition_id": ["T1"], "t_prev": [pd.Timestamp("1995-01-15")], "t_target": [pd.Timestamp("1995-02-10")]})
        result = allocate_monthly_forcing_to_transitions(monthly, transition, "well_id", "pumping")
        self.assertTrue(result.loc[0, ["interval_complete", "pre30_complete", "pre90_complete"]].all())
        self.assertEqual(result.loc[0, "transition_exposure_class"], "DERIVED_FROM_MONTHLY_VOLUME")
        self.assertFalse(result.loc[0, "daily_measured"])
        self.assertTrue(result.loc[0, "source_measurement_classes_preserved"])

    def test_09_common_support_is_one_sample_for_all_models(self) -> None:
        frame = pd.DataFrame({
            "transition_id": ["T1", "T2", "T3"], "site_code": ["W1", "W2", "W3"],
            "temporal_split": ["TRAIN", "VALIDATION", "TEST"], "spatial_fold": [1, 2, 3],
            "crosswalk_status": ["EXACT", "AMBIGUOUS", "HIGH_CONFIDENCE"],
        })
        for feature in S_STAR_REQUIRED_FEATURES:
            frame[feature] = 1.0
        frame.loc[2, S_STAR_REQUIRED_FEATURES[0]] = np.nan
        sample, summary = build_common_support(frame)
        self.assertEqual(list(sample["transition_id"]), ["T1"])
        self.assertEqual(summary["applies_identically_to"], ["BC", "B4", "B5", "B6"])
        self.assertFalse(summary["model_specific_sample_selection"])

    def test_10_placebos_do_not_cross_splits_or_strata(self) -> None:
        monthly = pd.DataFrame({
            "well_id": ["W1"] * 6,
            "month": pd.to_datetime(["1991-01-01", "1992-01-01", "1993-01-01", "1997-01-01", "1998-01-01", "1999-01-01"]),
            "volume_af": [1, 2, 3, 10, 20, 30],
            "temporal_split": ["TRAIN"] * 3 + ["TEST"] * 3,
        })
        placebo = temporal_pumping_placebo(monthly, 0)
        for split in ["TRAIN", "TEST"]:
            self.assertEqual(sorted(placebo.loc[placebo["temporal_split"] == split, "volume_af"]), sorted(monthly.loc[monthly["temporal_split"] == split, "volume_af"]))
        self.assertFalse(placebo["split_crossing"].any())
        locations = pd.DataFrame({"location_id": ["A", "B", "C", "D"], "easting_m": [1, 2, 100, 200], "northing_m": [3, 4, 300, 400], "layer": ["L1", "L1", "L2", "L2"]})
        spatial = spatial_identity_placebo(locations, 0, "layer")
        for layer in ["L1", "L2"]:
            before = sorted(map(tuple, locations.loc[locations["layer"] == layer, ["easting_m", "northing_m"]].to_numpy()))
            after = sorted(map(tuple, spatial.loc[spatial["layer"] == layer, ["easting_m", "northing_m"]].to_numpy()))
            self.assertEqual(before, after)

    def test_11_WRMS_absence_is_adjudicated_without_substitution(self) -> None:
        disposition = json.loads((ROOT / "outputs/provenance/GW1B_V2_WRMS_CANDIDATE_DISPOSITION.json").read_text())
        self.assertFalse(disposition["WRMS_delivery_present_after_path_adjudication"])
        self.assertEqual(disposition["unresolved_OCWD_WRMS_candidates"], [])
        self.assertFalse(disposition["second_scan_performed"])
        status = json.loads((ROOT / "outputs/v2/FINAL_GW1B_V2_STATUS.json").read_text())
        self.assertEqual(status["GW1B_DATA_STATUS"], "WAITING_FOR_WRMS")
        self.assertFalse(status["scientific_substitutions"]["synthetic_pumping"])
        self.assertFalse(status["scientific_substitutions"]["aggregate_public_pumping"])

    def test_12_no_B7_network_or_reserved_validation_execution(self) -> None:
        status = json.loads((ROOT / "outputs/v2/FINAL_GW1B_V2_STATUS.json").read_text())
        self.assertEqual(status["models_fit"], [])
        self.assertEqual(status["NETWORK_MODEL_JUSTIFICATION"], "UNRESOLVED")
        self.assertEqual(status["reserved_validation"], "UNTOUCHED")
        forbidden_artifacts = [p for p in ROOT.rglob("*") if p.is_file() and any(token in p.name.lower() for token in ["a_matrix", "gnn_model", "b7_predictions", "tracer_fit", "mbi_fit"])]
        self.assertEqual(forbidden_artifacts, [])


if __name__ == "__main__":
    unittest.main()
