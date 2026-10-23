from __future__ import annotations

import json
import unittest

from src.agents.model_transport import (
    CompletionResponse,
    FailureCategory,
    ModelIntegrationError,
)
from src.agents.rca_engine import RCAEngine
from src.agents.validation_diagnostics import FinishReasonDetail, ValidationDetail
from src.core.constraints import ConstraintRule
from src.core.sufficiency import PredicateConfig
from src.core.types import Evidence, EvidenceKind, Predicate, SuggestedAction
from src.model_config import ModelRoute


class FakeTransport:
    def __init__(self, content: str, finish_reason: str = "stop") -> None:
        self.content = content
        self.finish_reason = finish_reason
        self.error: ModelIntegrationError | None = None

    def list_models(self, route: ModelRoute, api_key: str) -> tuple[str, ...]:
        return (route.model,)

    def complete(
        self, route: ModelRoute, api_key: str, body: bytes
    ) -> CompletionResponse:
        if self.error is not None:
            raise self.error
        return CompletionResponse(self.content, self.finish_reason)


def _engine(transport: FakeTransport) -> tuple[RCAEngine, tuple[Evidence, ...]]:
    route = ModelRoute(
        "SYNTHESIS", "fixture/model-v1", "https://models.example/v1", "TOKEN", 5.0
    )
    evidence = Evidence(
        evidence_id="EV_SYNTHETIC",
        kind=EvidenceKind.SENSOR_ANOMALY,
        signal="sensor",
        statistic="robust_z_max",
        value=5.0,
        unit=None,
        window=(1, 10),
        provenance="synthetic fixture",
        computed_by="robust_mad_zscore@v1",
        summary="synthetic summary",
        window_basis="row:fixture",
    )
    engine = RCAEngine(
        route,
        PredicateConfig(primary_signals=frozenset({"sensor"})),
        {
            "equipment_fault": ConstraintRule(
                require_all=frozenset({Predicate.HAS_PRIMARY_SIGNAL_ANOMALY})
            )
        },
        "test-token",
        transport,
    )
    return engine, (evidence,)


class RcaDiagnosticsTests(unittest.TestCase):
    def test_schema_details_are_allowlisted_and_omit_raw_output(self) -> None:
        marker = "MODEL_TEXT_SENTINEL"
        response = json.dumps(
            {
                "disposition": "HOLD_LOT",
                "hypotheses": [
                    {
                        "claim": marker,
                        "root_cause": "ROOT_CATEGORY_SENTINEL",
                        "status": "SUPPORTED",
                    }
                ],
            }
        )
        engine, evidence = _engine(FakeTransport(response))

        with self.assertLogs("src.agents.rca_engine", level="WARNING") as captured:
            output = engine.generate_hypotheses(evidence)

        self.assertEqual(
            output.suggested_next_action, SuggestedAction.RETRY_ANALYSIS
        )
        self.assertEqual(output.hypotheses, [])
        self.assertIs(engine.last_failure_category, FailureCategory.SCHEMA_VALIDATION)
        self.assertIsNotNone(engine.last_validation_details)
        assert engine.last_validation_details is not None
        self.assertIn(ValidationDetail.MISSING_FIELD, engine.last_validation_details)
        self.assertIn(ValidationDetail.EXTRA_FIELD, engine.last_validation_details)
        self.assertIn(ValidationDetail.INVALID_ENUM, engine.last_validation_details)
        logged = " ".join(captured.output)
        self.assertNotIn(marker, logged)
        self.assertNotIn("ROOT_CATEGORY_SENTINEL", logged)
        self.assertNotIn("HOLD_LOT", logged)
        self.assertNotIn("SUPPORTED", logged)
        self.assertNotIn("disposition", logged)

    def test_malformed_json_detail_does_not_include_content(self) -> None:
        marker = "MODEL_TEXT_SENTINEL"
        engine, evidence = _engine(FakeTransport(f"not-json {marker}"))

        with self.assertLogs("src.agents.rca_engine", level="WARNING") as captured:
            output = engine.generate_hypotheses(evidence)

        self.assertEqual(
            output.suggested_next_action, SuggestedAction.RETRY_ANALYSIS
        )
        self.assertEqual(
            engine.last_validation_details, (ValidationDetail.MALFORMED_JSON,)
        )
        self.assertNotIn(marker, " ".join(captured.output))

    def test_finish_reason_failure_is_categorized_and_fails_closed(self) -> None:
        engine, evidence = _engine(FakeTransport("{}", finish_reason="length"))

        output = engine.generate_hypotheses(evidence)

        self.assertEqual(
            output.suggested_next_action, SuggestedAction.RETRY_ANALYSIS
        )
        self.assertEqual(output.hypotheses, [])
        self.assertIs(engine.last_failure_category, FailureCategory.FINISH_REASON)
        self.assertIs(engine.last_finish_reason, FinishReasonDetail.LENGTH)
        self.assertIsNone(engine.last_validation_details)

    def test_unknown_finish_reason_is_logged_as_generic_label(self) -> None:
        marker = "PRIVATE_PROVIDER_REASON"
        engine, evidence = _engine(FakeTransport("{}", finish_reason=marker))

        with self.assertLogs("src.agents.rca_engine", level="WARNING") as captured:
            output = engine.generate_hypotheses(evidence)

        self.assertEqual(
            output.suggested_next_action, SuggestedAction.RETRY_ANALYSIS
        )
        self.assertIs(engine.last_finish_reason, FinishReasonDetail.OTHER)
        logged = " ".join(captured.output)
        self.assertIn("finish_detail=other", logged)
        self.assertNotIn(marker, logged)

    def test_transport_error_text_is_not_logged(self) -> None:
        transport = FakeTransport("")
        transport.error = ModelIntegrationError(
            "SYNTHETIC_PROVIDER_TEXT test-token", FailureCategory.TRANSPORT
        )
        engine, evidence = _engine(transport)

        with self.assertLogs("src.agents.rca_engine", level="WARNING") as captured:
            output = engine.generate_hypotheses(evidence)

        self.assertEqual(
            output.suggested_next_action, SuggestedAction.RETRY_ANALYSIS
        )
        self.assertIs(engine.last_failure_category, FailureCategory.TRANSPORT)
        logged = " ".join(captured.output)
        self.assertNotIn("SYNTHETIC_PROVIDER_TEXT", logged)
        self.assertNotIn("test-token", logged)

    def test_oversized_response_is_categorized_without_logging_content(self) -> None:
        marker = "MODEL_TEXT_SENTINEL"
        engine, evidence = _engine(FakeTransport(marker * 2000))

        with self.assertLogs("src.agents.rca_engine", level="WARNING") as captured:
            output = engine.generate_hypotheses(evidence)

        self.assertEqual(
            output.suggested_next_action, SuggestedAction.RETRY_ANALYSIS
        )
        self.assertIs(engine.last_failure_category, FailureCategory.SIZE)
        self.assertNotIn(marker, " ".join(captured.output))


if __name__ == "__main__":
    unittest.main()
