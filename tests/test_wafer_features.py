from __future__ import annotations

import unittest

from src.core.evidence import EvidenceStore, build_llm_payload
from src.core.sufficiency import (
    PredicateConfig,
    SpatialExpectation,
    derive_predicates,
)
from src.core.types import Evidence, EvidenceKind
from src.core.wafer_features import (
    WaferDie,
    WaferFeatureConfig,
    convert_wm_status,
    extract_wafer_features,
)


class WaferFeatureTests(unittest.TestCase):
    def test_status_encoding_is_converted_at_the_boundary(self) -> None:
        self.assertEqual(convert_wm_status(0), 0)
        self.assertEqual(convert_wm_status(1), 1)
        self.assertEqual(convert_wm_status(2), -1)
        with self.assertRaises(ValueError):
            convert_wm_status(3)

    def test_features_are_unitless_and_scale_invariant(self) -> None:
        dies = (
            WaferDie(0.0, 0.0, 1),
            WaferDie(1.0, 0.0, 2),
            WaferDie(0.0, 1.0, 2),
        )
        with self.assertRaises(ValueError):
            WaferFeatureConfig(center_x=0.0, center_y=0.0)
        config = WaferFeatureConfig(
            center_x=0.0,
            center_y=0.0,
            center_source="map coordinate metadata",
        )
        features = extract_wafer_features(dies, config, "map.csv")
        scaled = extract_wafer_features(
            tuple(WaferDie(die.x * 7.0, die.y * 7.0, die.status) for die in dies),
            config,
            "map.csv",
        )
        values = {item.statistic: item.value for item in features}
        scaled_values = {item.statistic: item.value for item in scaled}
        self.assertEqual(values, scaled_values)
        self.assertEqual(values["fail_fraction"], 2.0 / 3.0)
        self.assertIsNone(values["edge_band_concentration"])
        self.assertLessEqual(
            len(build_llm_payload(EvidenceStore(features)).encode("utf-8")), 2048
        )

    def test_edge_band_requires_an_explicit_calibrated_cutoff(self) -> None:
        dies = (
            WaferDie(0.0, 0.0, 1),
            WaferDie(1.0, 0.0, 2),
            WaferDie(0.0, 1.0, 2),
        )
        with self.assertRaises(ValueError):
            WaferFeatureConfig(
                center_x=0.0,
                center_y=0.0,
                center_source="map coordinate metadata",
                edge_band_cutoff=0.5,
            )
        evidence = extract_wafer_features(
            dies,
            WaferFeatureConfig(
                center_x=0.0,
                center_y=0.0,
                center_source="map coordinate metadata",
                edge_band_cutoff=0.5,
                cutoff_source="fixture calibration",
            ),
            "map.csv",
        )
        values = {item.statistic: item.value for item in evidence}
        self.assertEqual(values["edge_band_concentration"], 1.0)

    def test_spatial_feature_needs_calibrated_bounds_to_match_signature(self) -> None:
        feature = Evidence(
            evidence_id="EV_spatial",
            kind=EvidenceKind.SPATIAL_FEATURE,
            signal=None,
            statistic="fail_fraction",
            value=0.75,
            unit=None,
            window=None,
            provenance="map.csv",
            computed_by="test",
            summary="Numeric wafer feature.",
        )
        store = EvidenceStore((feature,))
        self.assertFalse(
            derive_predicates(store, PredicateConfig()).has_expected_spatial_signature
        )
        expected = PredicateConfig(
            expected_spatial_features=(
                SpatialExpectation(
                    "fail_fraction", 0.7, 0.8, "label calibration artifact"
                ),
            )
        )
        self.assertTrue(
            derive_predicates(store, expected).has_expected_spatial_signature
        )
        outside_range = PredicateConfig(
            expected_spatial_features=(
                SpatialExpectation(
                    "fail_fraction", 0.1, 0.2, "label calibration artifact"
                ),
            )
        )
        self.assertFalse(
            derive_predicates(store, outside_range).has_expected_spatial_signature
        )


if __name__ == "__main__":
    unittest.main()
