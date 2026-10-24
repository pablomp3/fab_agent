from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from benchmarks.evaluator.echo_transport import (
    ExperimentalEchoTransport,
    offline_engine_factory,
    offline_mapping_factory,
)
from src.analyze import analyze_csv
from src.core.types import Evidence, EvidenceKind
from src.tools.tavily_search import (
    TavilyError,
    TavilyReference,
    build_tavily_query,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"


class FakeTavily:
    def __init__(
        self,
        references: tuple[TavilyReference, ...] = (),
        error: TavilyError | None = None,
    ) -> None:
        self.references = references
        self.error = error
        self.calls: list[str] = []

    def search(
        self, query: str, max_results: int = 3
    ) -> tuple[TavilyReference, ...]:
        self.calls.append(query)
        if self.error is not None:
            raise self.error
        return self.references[:max_results]


def _run(filename: str, search: FakeTavily):
    transport = ExperimentalEchoTransport()
    return analyze_csv(
        SAMPLES / filename,
        "demo sample",
        engine_factory=offline_engine_factory(transport),
        mapping_factory=offline_mapping_factory(transport),
        tavily_search=search,
    )


class TavilyQueryTests(unittest.TestCase):
    def test_query_uses_signal_names_and_excludes_values(self) -> None:
        evidence = (
            Evidence(
                evidence_id="EV_x",
                kind=EvidenceKind.SENSOR_ANOMALY,
                signal="FLOWCOOLPRESSURE",
                statistic="robust_z_max",
                value=12345.678,
                unit="kPa",
                window=(1, 10),
                provenance="test",
                computed_by="test",
                summary="a value that must not be sent",
            ),
        )
        query = build_tavily_query(evidence, "flowcool fault")
        self.assertIn("FLOWCOOLPRESSURE", query)
        self.assertNotIn("12345", query)
        self.assertNotIn("kPa", query)


class TavilyAttachmentTests(unittest.TestCase):
    def test_supported_run_does_not_search(self) -> None:
        search = FakeTavily()
        result = _run("flowcool_supported.csv", search)
        self.assertEqual(result.external_search_status, "not_needed")
        self.assertEqual(search.calls, [])

    def test_inconclusive_run_attaches_sources_without_changing_gate(self) -> None:
        search = FakeTavily(
            (
                TavilyReference(
                    title="Cooling loop troubleshooting",
                    url="https://example.com/cooling",
                    snippet="Check the coolant loop.",
                ),
            )
        )
        result = _run("flowcool_inconclusive.csv", search)
        self.assertEqual(result.external_search_status, "completed")
        self.assertEqual(result.external_search_count, 1)
        self.assertEqual(len(result.output.external_sources), 1)
        self.assertEqual(
            result.output.external_sources[0].url,
            "https://example.com/cooling",
        )
        self.assertTrue(search.calls)
        self.assertIn("flowcool", search.calls[0].lower())

    def test_tavily_failure_is_sanitized_and_does_not_change_verdict(self) -> None:
        search = FakeTavily(error=TavilyError("secret upstream detail"))
        result = _run("flowcool_inconclusive.csv", search)
        self.assertEqual(result.external_search_status, "unavailable")
        self.assertEqual(result.output.external_sources, [])
        self.assertEqual(result.suggested_next_action.value, "COLLECT_MORE_DATA")

    def test_no_key_is_reported_without_a_network_call(self) -> None:
        with patch.dict("os.environ", {"TAVILY_API_KEY": ""}):
            transport = ExperimentalEchoTransport()
            result = analyze_csv(
                SAMPLES / "flowcool_inconclusive.csv",
                "demo sample",
                engine_factory=offline_engine_factory(transport),
                mapping_factory=offline_mapping_factory(transport),
            )
        self.assertEqual(result.external_search_status, "not_configured")


if __name__ == "__main__":
    unittest.main()
