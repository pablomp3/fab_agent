from __future__ import annotations

import unittest
from pathlib import Path
from typing import cast

from benchmarks.evaluator.user_story_runner import run_story


def _by_id(report: dict[str, object]) -> dict[str, dict[str, object]]:
    scenarios = cast(list[dict[str, object]], report["scenarios"])
    return {str(item["scenario_id"]): item for item in scenarios}


class UserStoryTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.report = run_story(root, offline=True)
        self.by_id = _by_id(self.report)

    def test_every_scenario_has_a_label_and_explanation(self) -> None:
        for scenario_id, item in self.by_id.items():
            self.assertTrue(str(item["action_label"]).strip(), scenario_id)
            self.assertGreater(
                len(str(item["explanation"]).strip()), 20, scenario_id
            )

    def test_unknown_tools_fall_back_to_experimental(self) -> None:
        for scenario_id in ("unknown_named_tool", "unknown_opaque_tool"):
            item = self.by_id[scenario_id]
            self.assertEqual(item["mode"], "experimental", scenario_id)
            self.assertTrue(item["fallback_used"], scenario_id)
            self.assertEqual(
                item["suggested_next_action"],
                "REVIEW_DRAFT_MAPPING",
                scenario_id,
            )
            self.assertTrue(item["draft_yaml_present"], scenario_id)

    def test_matching_schema_never_calls_the_mapping_model(self) -> None:
        item = self.by_id["known_phm_flowcool"]
        self.assertEqual(item["mode"], "safe")
        self.assertFalse(item["fallback_used"])
        calls = cast(list[dict[str, object]], item["llm_calls"])
        self.assertEqual([call["purpose"] for call in calls], ["hypothesis"])

    def test_data_quality_failures_make_no_model_calls(self) -> None:
        expected = {
            "malformed_csv": "INPUT_MALFORMED",
            "header_only_csv": "NO_DATA_ROWS",
            "missing_file": "INPUT_UNREADABLE",
        }
        for scenario_id, outcome in expected.items():
            item = self.by_id[scenario_id]
            self.assertEqual(item["outcome"], outcome, scenario_id)
            self.assertEqual(item["llm_calls"], [], scenario_id)
            self.assertFalse(item["fallback_used"], scenario_id)

    def test_synthetic_contradiction_recommends_reviewing_the_contradiction(
        self,
    ) -> None:
        item = self.by_id["synthetic_b4a"]
        self.assertEqual(item["outcome"], "ANALYSIS_CONTRADICTED")
        self.assertEqual(
            item["suggested_next_action"], "REVIEW_CONTRADICTION"
        )


if __name__ == "__main__":
    unittest.main()
