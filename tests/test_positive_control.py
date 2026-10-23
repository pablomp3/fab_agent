from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from benchmarks.evaluator.llm_positive_control import run_stability
from benchmarks.synthetic_twin.generate_twin import generate_positive_control
from src.agents.model_transport import CompletionResponse
from src.config_loader import load_relations
from src.core.duckdb_exec import extract_evidence
from src.core.evidence import EvidenceStore
from src.core.pipeline import Candidate, assess_candidate
from src.core.sufficiency import derive_predicates
from src.core.types import EvidenceKind, Verdict
from src.model_config import ModelRoute

ROOT = Path(__file__).resolve().parents[1]
POSITIVE_CONFIG = ROOT / "config/sensor_relations/synthetic_twin_positive.yaml"


class _AlternatingTransport:
    """Fake transport: odd calls cite the primary anomaly, even calls abstain."""

    def __init__(self) -> None:
        self.calls = 0

    def list_models(self, route: ModelRoute, api_key: str) -> tuple[str, ...]:
        return (route.model,)

    def complete(
        self, route: ModelRoute, api_key: str, body: bytes
    ) -> CompletionResponse:
        self.calls += 1
        payload = json.loads(body)
        evidence = json.loads(payload["messages"][1]["content"])["evidence"]
        if self.calls % 2 == 1:
            content = json.dumps(
                {
                    "hypotheses": [
                        {
                            "claim": "RF Generator Arc",
                            "root_cause": "equipment_fault",
                            "failure_mode": "rf_power_arc",
                            "mechanism": "corroborated reflectometer excursion",
                            "hypothesis_class": "equipment_fault",
                            "cited_evidence": [
                                item["evidence_id"] for item in evidence
                            ],
                        }
                    ]
                }
            )
        else:
            content = json.dumps({"hypotheses": []})
        return CompletionResponse(content, "stop")


class PositiveControlTests(unittest.TestCase):
    def test_b4e_is_reproducible_and_keeps_truth_separate(self) -> None:
        with TemporaryDirectory() as temp_dir:
            first = generate_positive_control(Path(temp_dir) / "first")
            second = generate_positive_control(Path(temp_dir) / "second")
            self.assertEqual(first.case_id, "B4e")
            self.assertEqual(first.seed, 46)
            self.assertEqual(first.telemetry_sha256, second.telemetry_sha256)
            relative = Path("benchmarks/synthetic_twin/cases/B4e/telemetry.csv")
            self.assertEqual(
                (Path(temp_dir) / "first" / relative).read_bytes(),
                (Path(temp_dir) / "second" / relative).read_bytes(),
            )
            truth = (
                Path(temp_dir)
                / "first"
                / "benchmarks/evaluator/ground_truths/B4e_ground_truth.json"
            )
            self.assertTrue(truth.is_file())

    def test_b4e_is_deterministically_supported_when_corroborated(self) -> None:
        with TemporaryDirectory() as temp_dir:
            generate_positive_control(Path(temp_dir))
            scenario = load_relations(POSITIVE_CONFIG).scenarios["B4e"]
            evidence = extract_evidence(
                Path(temp_dir) / "benchmarks/synthetic_twin/cases/B4e/telemetry.csv",
                scenario.signals,
            )
            by_signal = {
                item.signal: item for item in evidence if item.signal is not None
            }
            for signal in ("sensor_17", "impedance", "thermal", "pressure"):
                self.assertIs(by_signal[signal].kind, EvidenceKind.SENSOR_ANOMALY)
            store = EvidenceStore(evidence)
            predicates = derive_predicates(store, scenario.predicate_config)
            self.assertTrue(predicates.has_primary_signal_anomaly)
            self.assertFalse(predicates.has_instrumentation_contradiction)
            self.assertFalse(predicates.has_missing_required_evidence)
            cited = [
                by_signal[signal].evidence_id
                for signal in scenario.candidate.cited_signals
            ]
            candidate = Candidate(
                claim=scenario.candidate.claim,
                hypothesis_class=scenario.candidate.hypothesis_class,
                cited_evidence=tuple(cited),
            )
            assessment = assess_candidate(
                candidate, store, scenario.predicate_config, scenario.rules
            )
            self.assertIs(assessment.constraints.verdict, Verdict.SUPPORTED)

    def test_live_stability_record_counts_each_attempt(self) -> None:
        transport = _AlternatingTransport()
        with TemporaryDirectory() as temp_dir:
            summary, reports = run_stability(
                Path(temp_dir),
                3,
                environment={"NEBIUS_API_KEY": "offline-fixture-key"},
                transport=transport,
            )

        self.assertEqual(summary["attempts"], 3)
        # The configured candidate is gated on every attempt. The alternating
        # transport changes the model narrative, not the Python verdict.
        self.assertEqual(summary["supported_count"], 3)
        self.assertEqual(summary["supported_rate"], 1.0)
        self.assertEqual(summary["mode"], "live")
        self.assertIsInstance(summary["per_attempt"], list)
        self.assertEqual(len(reports), 3)
        self.assertEqual(transport.calls, 3)
        self.assertEqual(
            [bool(report["any_supported"]) for report in reports],
            [True, True, True],
        )
        per_attempt = cast(list[dict[str, object]], summary["per_attempt"])
        self.assertEqual(
            [item["model_narrative_present"] for item in per_attempt],
            [[True], [False], [True]],
        )


if __name__ == "__main__":
    unittest.main()