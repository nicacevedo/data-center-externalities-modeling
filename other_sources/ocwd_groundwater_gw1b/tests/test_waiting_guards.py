"""Guards for the GW-1B preregistered waiting state."""

import json
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class GW1BWaitingGuards(unittest.TestCase):
    def test_waiting_status_is_explicit(self) -> None:
        status = json.loads((ROOT / "outputs/FINAL_GW1B_STATUS.json").read_text())
        self.assertEqual(status["GW1B_DATA_STATUS"], "WAITING_FOR_WRMS")
        self.assertFalse(status["WRMS_availability"]["delivery_present"])
        self.assertEqual(status["models_fit_in_GW1B"], [])
        self.assertFalse(status["network_estimated"])

    def test_background_and_contrasts_are_frozen(self) -> None:
        protocol = yaml.safe_load((ROOT / "config/GW1B_PROTOCOL_AMENDMENT_20260904.yaml").read_text())
        self.assertEqual(protocol["status"], "FROZEN_BEFORE_WRMS_RESPONSE_INSPECTION")
        self.assertEqual(protocol["primary_response"], "delta_h")
        self.assertEqual(protocol["background_model"]["frozen_definition"], "B1C")
        self.assertEqual(protocol["primary_contrasts"]["pumping_predictive_value"], "B5_minus_B4")
        self.assertEqual(protocol["primary_contrasts"]["spatial_forcing_value"], "B6_minus_B5")
        self.assertEqual(protocol["primary_contrasts"]["network_added_value"], "B7_minus_B6")

    def test_no_data_or_model_artifacts_exist(self) -> None:
        forbidden_suffixes = {".parquet", ".pkl", ".joblib", ".pt", ".h5"}
        forbidden = [p for p in ROOT.rglob("*") if p.is_file() and p.suffix.lower() in forbidden_suffixes]
        self.assertEqual(forbidden, [])

    def test_no_synthetic_or_aggregate_pumping_substitution(self) -> None:
        audit = json.loads((ROOT / "outputs/provenance/WRMS_AVAILABILITY_CHECK.json").read_text())
        self.assertFalse(audit["WRMS_delivery_present"])
        self.assertFalse(audit["synthetic_pumping_created"])
        self.assertFalse(audit["public_aggregate_pumping_substituted"])

    def test_network_gate_and_reserved_validation(self) -> None:
        protocol = yaml.safe_load((ROOT / "config/GW1B_PROTOCOL_AMENDMENT_20260904.yaml").read_text())
        self.assertEqual(protocol["network_gate"]["on_failure"], "NETWORK_MODEL_JUSTIFICATION_FAIL_AND_DO_NOT_FIT_B7")
        self.assertTrue(protocol["B7"]["free_A_matrix"] == "prohibited" or protocol["B7"]["free_A_matrix"] is False)
        self.assertEqual(protocol["reserved_external_validation"]["use"], "only_after_eligible_B7_is_frozen")


if __name__ == "__main__":
    unittest.main()

