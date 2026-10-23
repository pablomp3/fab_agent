from __future__ import annotations

import unittest
from pathlib import Path

from benchmarks.evaluator.echo_transport import (
    ExperimentalEchoTransport,
    offline_engine_factory,
    offline_mapping_factory,
)
from src.analyze import analyze_csv
from src.core.types import AnalysisOutcome, SuggestedAction, Verdict

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"


def _run(filename: str):
    transport = ExperimentalEchoTransport()
    return analyze_csv(
        SAMPLES / filename,
        "demo sample",
        engine_factory=offline_engine_factory(transport),
        mapping_factory=offline_mapping_factory(transport),
    )


class DemoSampleTests(unittest.TestCase):
    def test_supported_flowcool_sample_uses_the_safe_path(self) -> None:
        result = _run("flowcool_supported.csv")
        self.assertEqual(result.mode, "safe")
        self.assertIs(result.outcome, AnalysisOutcome.ANALYSIS_SUPPORTED)
        self.assertIs(
            result.suggested_next_action, SuggestedAction.INSPECT_COMPONENT
        )
        self.assertIs(result.output.hypotheses[0].status, Verdict.SUPPORTED)

    def test_flat_flowcool_sample_abstains(self) -> None:
        result = _run("flowcool_inconclusive.csv")
        self.assertEqual(result.mode, "safe")
        self.assertIs(result.outcome, AnalysisOutcome.ANALYSIS_INCONCLUSIVE)
        self.assertIs(
            result.suggested_next_action, SuggestedAction.COLLECT_MORE_DATA
        )
        self.assertIs(result.output.hypotheses[0].status, Verdict.INSUFFICIENT)
        self.assertTrue(result.output.required_next_checks)

    def test_rf_contradiction_sample_is_vetoed(self) -> None:
        result = _run("rf_contradiction.csv")
        self.assertEqual(result.mode, "safe")
        self.assertIs(result.outcome, AnalysisOutcome.ANALYSIS_CONTRADICTED)
        self.assertIs(
            result.suggested_next_action, SuggestedAction.REVIEW_CONTRADICTION
        )
        self.assertIs(result.output.hypotheses[0].status, Verdict.VETOED)

    def test_unknown_tool_sample_reaches_the_experimental_arc(self) -> None:
        result = _run("unknown_tool.csv")
        self.assertEqual(result.mode, "experimental")
        self.assertIs(
            result.outcome, AnalysisOutcome.EXPERIMENTAL_UNVERIFIED_MAPPING
        )
        self.assertIs(
            result.suggested_next_action, SuggestedAction.REVIEW_DRAFT_MAPPING
        )
        self.assertIsNotNone(result.mapping)
        self.assertIsNotNone(result.draft_yaml)
        for evidence in result.evidence:
            self.assertIn("unverified_mapping", evidence.provenance)


if __name__ == "__main__":
    unittest.main()
