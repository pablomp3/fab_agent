from __future__ import annotations

import unittest
from typing import cast

from benchmarks.evaluator.e2e_suite_runner import default_cases, run_suite


def _case_list(report: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], report["cases"])


class E2ESuiteTests(unittest.TestCase):
    def test_offline_suite_matches_expectations_across_real_and_synthetic(self) -> None:
        report = run_suite(offline=True)

        self.assertGreaterEqual(cast(int, report["case_count"]), 3)
        self.assertTrue(report["all_expectations_matched"], report)
        cases = _case_list(report)
        sources = {item["source"] for item in cases}
        self.assertIn("real_public_benchmark", sources)
        self.assertIn("synthetic_twin", sources)

        for item in cases:
            safe = cast(dict[str, object], item["safe_path"])
            experimental = cast(dict[str, object], item["experimental_path"])
            # No path can recommend an autonomous or recipe-changing action;
            # the experimental path always asks for a human-readable review of
            # its unverified draft mapping.
            self.assertEqual(
                experimental["suggested_next_action"], "REVIEW_DRAFT_MAPPING"
            )
            self.assertIn(
                safe["suggested_next_action"],
                {
                    "COLLECT_MORE_DATA",
                    "CONTINUE_MONITORING",
                    "AUTHOR_TOOL_CONFIG",
                    "REVIEW_CONTRADICTION",
                    "ESCALATE_TO_ENGINEER",
                },
            )
            self.assertEqual(experimental["outcome"], "EXPERIMENTAL_UNVERIFIED_MAPPING")
            self.assertTrue(experimental["analysis_performed"])
            self.assertTrue(experimental["model_called"])
            self.assertTrue(experimental["unverified_tagged"])
            self.assertTrue(experimental["draft_config_valid"])
            self.assertNotIn("HOLD_LOT", str(item))
            self.assertNotIn("UPDATE_RECIPE", str(item))

    def test_default_cases_cover_both_sources(self) -> None:
        cases = default_cases()
        self.assertGreaterEqual(len(cases), 3)
        self.assertTrue(all(case.expectation_note for case in cases))
        self.assertEqual(len({case.case_id for case in cases}), len(cases))


if __name__ == "__main__":
    unittest.main()
