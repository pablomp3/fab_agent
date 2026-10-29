from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from benchmarks.evaluator.echo_transport import (
    ExperimentalEchoTransport,
    offline_engine_factory,
    offline_mapping_factory,
)
from src.analyze import RunResult, analyze_csv
from src.core.types import AnalysisOutcome, SuggestedAction

_PHM_EXPORT = (
    "time,FLOWCOOLFLOWRATE,FLOWCOOLPRESSURE\n"
    "1,10.0,10.0\n2,10.4,10.3\n3,9.8,9.9\n"
    "4,10.2,10.1\n5,9.9,9.8\n6,1000.0,1000.0\n"
)
_UNKNOWN_EXPORT = (
    "a,b,c\n10.0,10.0,10.0\n11.0,11.0,11.0\n10.0,10.0,10.0\n"
    "11.0,11.0,11.0\n10.0,10.0,10.0\n1000.0,11.0,11.0\n"
)


class AnalyzeCsvTests(unittest.TestCase):
    def _run(self, text: str, *, force_experimental: bool = False) -> RunResult:
        transport = ExperimentalEchoTransport()
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "export.csv"
            path.write_text(text, encoding="utf-8")
            return analyze_csv(
                path,
                "flowcool" if "FLOWCOOL" in text else "unknown tool",
                engine_factory=offline_engine_factory(transport),
                mapping_factory=offline_mapping_factory(transport),
                force_experimental=force_experimental,
            )

    def test_matching_schema_stays_on_the_safe_path(self) -> None:
        result = self._run(_PHM_EXPORT)
        self.assertEqual(result.mode, "safe")
        self.assertFalse(result.fallback_used)
        self.assertIs(result.outcome, AnalysisOutcome.ANALYSIS_SUPPORTED)

    def test_force_experimental_bypasses_a_matching_saved_model(self) -> None:
        result = self._run(_PHM_EXPORT, force_experimental=True)
        self.assertEqual(result.mode, "experimental")
        self.assertTrue(result.fallback_used)
        self.assertIsNotNone(result.mapping)

    def test_unknown_schema_falls_back_to_experimental(self) -> None:
        result = self._run(_UNKNOWN_EXPORT)
        self.assertEqual(result.mode, "experimental")
        self.assertTrue(result.fallback_used)
        self.assertIs(
            result.outcome,
            AnalysisOutcome.EXPERIMENTAL_UNVERIFIED_MAPPING,
        )
        self.assertIs(
            result.suggested_next_action,
            SuggestedAction.REVIEW_DRAFT_MAPPING,
        )
        self.assertIsNotNone(result.draft_yaml)

    def test_malformed_file_does_not_fall_back(self) -> None:
        transport = ExperimentalEchoTransport()
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "broken.csv"
            path.write_bytes(b"\x00\x01\xff\xfe,not,a,csv\n\x00\xff")
            result = analyze_csv(
                path,
                "anything",
                engine_factory=offline_engine_factory(transport),
                mapping_factory=offline_mapping_factory(transport),
            )
        self.assertEqual(result.mode, "safe")
        self.assertFalse(result.fallback_used)
        self.assertIs(result.outcome, AnalysisOutcome.INPUT_MALFORMED)
        self.assertIs(result.suggested_next_action, SuggestedAction.FIX_FILE_FORMAT)


if __name__ == "__main__":
    unittest.main()
