from __future__ import annotations

import json
import unittest

from src.agents.model_transport import (
    CompletionResponse,
    FailureCategory,
)
from src.agents.proposal_request import MAX_EVIDENCE_BYTES, evidence_summary_bytes
from src.agents.rca_engine import RCAEngine
from src.config_types import CandidateConfig
from src.core.constraints import ConstraintRule
from src.core.evidence import PayloadTooLarge
from src.core.sufficiency import PredicateConfig
from src.core.types import (
    AnalysisOutcome,
    Evidence,
    EvidenceKind,
    Predicate,
    SuggestedAction,
    Verdict,
)
from src.model_config import ModelRoute
from src.schemas.models import RootCauseCategory


class FakeTransport:
    def __init__(self, response: str, finish_reason: str = "stop") -> None:
        self.response = response
        self.finish_reason = finish_reason
        self.available_models: tuple[str, ...] = ("fixture/model-v1",)
        self.request_body: bytes | None = None
        self.preflight_role: str | None = None

    def list_models(self, route: ModelRoute, api_key: str) -> tuple[str, ...]:
        if api_key != "test-token":
            raise AssertionError("preflight did not receive the configured token")
        self.preflight_role = route.role
        return self.available_models

    def complete(
        self, route: ModelRoute, api_key: str, body: bytes
    ) -> CompletionResponse:
        if api_key != "test-token":
            raise AssertionError("completion did not receive the configured token")
        self.request_body = body
        return CompletionResponse(self.response, self.finish_reason)


def make_route(model: str = "fixture/model-v1") -> ModelRoute:
    return ModelRoute(
        role="SYNTHESIS",
        model=model,
        base_url="https://models.example/v1",
        api_key_env="TEST_MODEL_API_KEY",
        timeout_seconds=5.0,
    )


def make_evidence(kind: EvidenceKind, signal: str, name: str) -> Evidence:
    return Evidence(
        evidence_id=name,
        kind=kind,
        signal=signal,
        statistic="robust_z_max",
        value=5.0 if kind is EvidenceKind.SENSOR_ANOMALY else 0.0,
        unit=None,
        window=(1, 10),
        provenance="/private/fab/raw.csv rows 1-10",
        computed_by="robust_mad_zscore@v1",
        summary="RAW_TELEMETRY_DO_NOT_SEND",
        window_basis="row:fixture",
    )


def proposal_response(citations: list[str]) -> str:
    return json.dumps(
        {
            "hypotheses": [
                {
                    "claim": "Possible isolated sensor fault",
                    "root_cause": "instrumentation_fault",
                    "failure_mode": "isolated_sensor_failure",
                    "mechanism": "sensor_or_daq_fault",
                    "hypothesis_class": "equipment_fault",
                    "cited_evidence": citations,
                }
            ]
        }
    )


class RcaEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.anomaly = make_evidence(
            EvidenceKind.SENSOR_ANOMALY, "sensor", "EV_ANOMALY"
        )
        self.nominal = make_evidence(EvidenceKind.SENSOR_NOMINAL, "probe", "EV_PROBE")
        self.predicate_config = PredicateConfig(
            primary_signals=frozenset({"sensor"}),
            corroboration_signals=frozenset({"probe"}),
        )
        self.rules = {
            "equipment_fault": ConstraintRule(
                require_all=frozenset({Predicate.HAS_PRIMARY_SIGNAL_ANOMALY}),
                veto_if_any=frozenset({Predicate.HAS_INSTRUMENTATION_CONTRADICTION}),
            )
        }

    def test_model_proposals_are_rechecked_and_action_is_python_owned(
        self,
    ) -> None:
        transport = FakeTransport(proposal_response(["EV_ANOMALY"]))
        engine = RCAEngine(
            make_route(), self.predicate_config, self.rules, "test-token", transport
        )

        result = engine.generate_hypotheses((self.anomaly, self.nominal))

        self.assertEqual(transport.preflight_role, "SYNTHESIS")
        self.assertEqual(result.hypotheses[0].status, Verdict.VETOED)
        self.assertEqual(
            result.suggested_next_action, SuggestedAction.REVIEW_CONTRADICTION
        )
        self.assertIs(result.outcome, AnalysisOutcome.ANALYSIS_CONTRADICTED)
        self.assertTrue(result.analysis_performed)
        self.assertTrue(result.model_called)
        self.assertIs(engine.last_outcome, AnalysisOutcome.ANALYSIS_CONTRADICTED)
        self.assertNotIn("HOLD_LOT", result.model_dump_json())
        self.assertIsNotNone(transport.request_body)
        assert transport.request_body is not None
        self.assertLessEqual(len(transport.request_body), 2048)
        self.assertNotIn(b"/private/fab/raw.csv", transport.request_body)
        self.assertNotIn(b"RAW_TELEMETRY_DO_NOT_SEND", transport.request_body)
        self.assertIn(b"EV_ANOMALY", transport.request_body)
        request = json.loads(transport.request_body)
        self.assertEqual(request["max_tokens"], 256)
        self.assertEqual(request["response_format"]["type"], "json_schema")
        self.assertEqual(request["chat_template_kwargs"], {"enable_thinking": False})
        schema_format = request["response_format"]["json_schema"]
        self.assertTrue(schema_format["strict"])
        self.assertEqual(schema_format["name"], "fabagent_proposals")
        schema = schema_format["schema"]
        self.assertEqual(schema["required"], ["hypotheses"])
        self.assertFalse(schema["additionalProperties"])
        proposal_schema = schema["properties"]["hypotheses"]["items"]
        self.assertFalse(proposal_schema["additionalProperties"])
        self.assertEqual(
            proposal_schema["properties"]["hypothesis_class"]["enum"],
            ["equipment_fault"],
        )
        self.assertEqual(
            set(proposal_schema["required"]),
            {
                "claim",
                "root_cause",
                "failure_mode",
                "mechanism",
                "hypothesis_class",
                "cited_evidence",
            },
        )
        self.assertIsNone(engine.last_failure_category)
        self.assertNotIn("guided_json", request)

    def test_system_prompt_frames_rca_task_within_payload_limit(self) -> None:
        transport = FakeTransport(proposal_response(["EV_ANOMALY"]))
        engine = RCAEngine(
            make_route(), self.predicate_config, self.rules, "test-token", transport
        )

        engine.generate_hypotheses((self.anomaly, self.nominal))

        assert transport.request_body is not None
        self.assertLessEqual(len(transport.request_body), 2048)
        request = json.loads(transport.request_body)
        system_prompt = request["messages"][0]["content"]
        self.assertIn("root-cause", system_prompt)
        self.assertIn("SENSOR_ANOMALY", system_prompt)
        self.assertIn("evidence_id", system_prompt)

    def test_unresolved_citation_is_insufficient_even_if_claim_is_plausible(
        self,
    ) -> None:
        transport = FakeTransport(proposal_response(["EV_INVENTED"]))
        engine = RCAEngine(
            make_route(), self.predicate_config, self.rules, "test-token", transport
        )

        result = engine.generate_hypotheses((self.anomaly, self.nominal))

        self.assertEqual(result.hypotheses[0].status, Verdict.INSUFFICIENT)
        self.assertEqual(
            result.suggested_next_action, SuggestedAction.COLLECT_MORE_DATA
        )
        self.assertIs(result.outcome, AnalysisOutcome.ANALYSIS_INCONCLUSIVE)

    def test_supported_candidate_still_cannot_select_operational_action(
        self,
    ) -> None:
        response = json.dumps(
            {
                "hypotheses": [
                    {
                        "claim": "Equipment fault candidate",
                        "root_cause": "equipment_fault",
                        "failure_mode": "sensor_failure",
                        "mechanism": "sensor drift",
                        "hypothesis_class": "equipment_fault",
                        "cited_evidence": ["EV_ANOMALY"],
                    }
                ]
            }
        )
        transport = FakeTransport(response)
        engine = RCAEngine(
            make_route(),
            PredicateConfig(primary_signals=frozenset({"sensor"})),
            {
                "equipment_fault": ConstraintRule(
                    require_all=frozenset({Predicate.HAS_PRIMARY_SIGNAL_ANOMALY})
                )
            },
            "test-token",
            transport,
        )

        result = engine.generate_hypotheses((self.anomaly,))

        self.assertEqual(result.hypotheses[0].status, Verdict.SUPPORTED)
        self.assertEqual(
            result.suggested_next_action, SuggestedAction.ESCALATE_TO_ENGINEER
        )
        self.assertIs(result.outcome, AnalysisOutcome.ANALYSIS_SUPPORTED)

    def test_configured_candidate_is_the_gated_conclusion(self) -> None:
        transport = FakeTransport(proposal_response(["EV_ANOMALY"]))
        engine = RCAEngine(
            make_route(),
            self.predicate_config,
            {
                "equipment_fault": ConstraintRule(
                    require_all=frozenset({Predicate.HAS_PRIMARY_SIGNAL_ANOMALY})
                )
            },
            "test-token",
            transport,
        )
        configured = CandidateConfig(
            claim="Configured RF arc",
            hypothesis_class="equipment_fault",
            cited_signals=("sensor", "probe"),
            root_cause=RootCauseCategory.EQUIPMENT_FAULT,
            failure_mode="Configured failure mode",
            mechanism="Configured mechanism",
        )

        result = engine.generate_hypotheses(
            (self.anomaly, self.nominal), candidate=configured
        )

        hypothesis = result.hypotheses[0]
        self.assertEqual(hypothesis.claim, configured.claim)
        self.assertEqual(hypothesis.root_cause, RootCauseCategory.EQUIPMENT_FAULT)
        self.assertEqual(hypothesis.failure_mode, configured.failure_mode)
        self.assertIs(hypothesis.status, Verdict.SUPPORTED)
        self.assertIs(result.outcome, AnalysisOutcome.ANALYSIS_SUPPORTED)
        self.assertIsNotNone(hypothesis.model_narrative)
        assert hypothesis.model_narrative is not None
        self.assertEqual(
            hypothesis.model_narrative.claim, "Possible isolated sensor fault"
        )
        self.assertEqual(hypothesis.cited_evidence, ["EV_ANOMALY", "EV_PROBE"])

    def test_missing_configured_channel_forces_inconclusive(self) -> None:
        transport = FakeTransport(proposal_response(["EV_ANOMALY"]))
        engine = RCAEngine(
            make_route(),
            self.predicate_config,
            {
                "equipment_fault": ConstraintRule(
                    require_all=frozenset({Predicate.HAS_PRIMARY_SIGNAL_ANOMALY})
                )
            },
            "test-token",
            transport,
        )
        configured = CandidateConfig(
            claim="Configured candidate",
            hypothesis_class="equipment_fault",
            cited_signals=("sensor", "not_in_export"),
        )

        result = engine.generate_hypotheses((self.anomaly,), candidate=configured)

        self.assertIs(result.hypotheses[0].status, Verdict.INSUFFICIENT)
        self.assertIs(result.outcome, AnalysisOutcome.ANALYSIS_INCONCLUSIVE)
        self.assertEqual(
            result.suggested_next_action, SuggestedAction.COLLECT_MORE_DATA
        )
        self.assertTrue(
            any("not_in_export" in item for item in result.required_next_checks)
        )

    def test_model_failure_still_applies_the_deterministic_gate(self) -> None:
        transport = FakeTransport("not json")
        engine = RCAEngine(
            make_route(),
            self.predicate_config,
            {
                "equipment_fault": ConstraintRule(
                    require_all=frozenset({Predicate.HAS_PRIMARY_SIGNAL_ANOMALY})
                )
            },
            "test-token",
            transport,
        )
        configured = CandidateConfig(
            claim="Configured candidate",
            hypothesis_class="equipment_fault",
            cited_signals=("sensor",),
        )

        result = engine.generate_hypotheses((self.anomaly,), candidate=configured)

        self.assertIs(result.outcome, AnalysisOutcome.ANALYSIS_SUPPORTED)
        self.assertIs(result.hypotheses[0].status, Verdict.SUPPORTED)
        self.assertIsNone(result.hypotheses[0].model_narrative)
        self.assertIs(engine.last_failure_category, FailureCategory.SCHEMA_VALIDATION)
        self.assertTrue(
            any("schema_validation" in item for item in result.required_next_checks)
        )

    def test_empty_proposals_route_to_no_proposals(self) -> None:
        transport = FakeTransport(json.dumps({"hypotheses": []}))
        engine = RCAEngine(
            make_route(), self.predicate_config, self.rules, "test-token", transport
        )

        result = engine.generate_hypotheses((self.anomaly,))

        self.assertEqual(result.hypotheses, [])
        self.assertIs(result.outcome, AnalysisOutcome.NO_PROPOSALS)
        self.assertTrue(result.analysis_performed)
        self.assertTrue(result.model_called)
        self.assertEqual(
            result.suggested_next_action, SuggestedAction.REVIEW_CHANNEL_FINDINGS
        )

    def test_invalid_completion_routes_to_model_rejected(self) -> None:
        transport = FakeTransport("not json at all")
        engine = RCAEngine(
            make_route(), self.predicate_config, self.rules, "test-token", transport
        )

        result = engine.generate_hypotheses((self.anomaly,))

        self.assertIs(result.outcome, AnalysisOutcome.MODEL_REJECTED)
        self.assertTrue(result.analysis_performed)
        self.assertTrue(result.model_called)
        self.assertEqual(result.suggested_next_action, SuggestedAction.RETRY_ANALYSIS)

    def test_veto_priority_outranks_support(self) -> None:
        response = json.dumps(
            {
                "hypotheses": [
                    {
                        "claim": "Supported branch",
                        "root_cause": "equipment_fault",
                        "failure_mode": "a",
                        "mechanism": "b",
                        "hypothesis_class": "equipment_fault",
                        "cited_evidence": ["EV_ANOMALY"],
                    },
                    {
                        "claim": "Vetoed branch",
                        "root_cause": "instrumentation_fault",
                        "failure_mode": "c",
                        "mechanism": "d",
                        "hypothesis_class": "instrumentation_fault",
                        "cited_evidence": ["EV_ANOMALY"],
                    },
                ]
            }
        )
        transport = FakeTransport(response)
        engine = RCAEngine(
            make_route(),
            PredicateConfig(
                primary_signals=frozenset({"sensor"}),
                corroboration_signals=frozenset({"probe"}),
            ),
            {
                "equipment_fault": ConstraintRule(
                    require_all=frozenset({Predicate.HAS_PRIMARY_SIGNAL_ANOMALY})
                ),
                "instrumentation_fault": ConstraintRule(
                    require_all=frozenset({Predicate.HAS_PRIMARY_SIGNAL_ANOMALY}),
                    veto_if_any=frozenset(
                        {Predicate.HAS_INSTRUMENTATION_CONTRADICTION}
                    ),
                ),
            },
            "test-token",
            transport,
        )

        result = engine.generate_hypotheses((self.anomaly, self.nominal))

        statuses = {item.status for item in result.hypotheses}
        self.assertEqual(statuses, {Verdict.SUPPORTED, Verdict.VETOED})
        self.assertIs(result.outcome, AnalysisOutcome.ANALYSIS_CONTRADICTED)

    def test_diagnostic_output_cap_can_be_raised_without_changing_default(self) -> None:
        transport = FakeTransport(proposal_response(["EV_ANOMALY"]))
        engine = RCAEngine(
            make_route(), self.predicate_config, self.rules, "test-token", transport
        )

        engine.generate_hypotheses((self.anomaly, self.nominal), max_tokens=768)

        assert transport.request_body is not None
        request = json.loads(transport.request_body)
        self.assertEqual(request["max_tokens"], 768)

    def test_engine_rejects_unavailable_model_during_preflight(self) -> None:
        transport = FakeTransport(proposal_response(["EV_ANOMALY"]))
        transport.available_models = ("some/other-model",)

        with self.assertRaisesRegex(RuntimeError, "SYNTHESIS"):
            RCAEngine(
                make_route(),
                self.predicate_config,
                self.rules,
                "test-token",
                transport,
            )

    def test_oversized_request_fails_closed_without_completion_call(self) -> None:
        transport = FakeTransport(proposal_response(["EV_ANOMALY"]))
        evidence = tuple(
            make_evidence(EvidenceKind.SENSOR_NOMINAL, f"sensor_{index}", f"EV_{index}")
            for index in range(30)
        )
        engine = RCAEngine(
            make_route(), self.predicate_config, self.rules, "test-token", transport
        )

        with self.assertRaises(PayloadTooLarge):
            engine.generate_hypotheses(evidence)
        self.assertIsNone(transport.request_body)
        self.assertIs(engine.last_failure_category, FailureCategory.SIZE)
        self.assertIs(engine.last_outcome, AnalysisOutcome.EVIDENCE_TOO_LARGE)

    def test_evidence_budget_is_separate_from_whole_request_size(self) -> None:
        transport = FakeTransport(proposal_response(["EV_ANOMALY"]))
        engine = RCAEngine(
            make_route(), self.predicate_config, self.rules, "test-token", transport
        )
        evidence = (self.anomaly, self.nominal) + tuple(
            make_evidence(EvidenceKind.SENSOR_NOMINAL, f"sensor_{index}", f"EV_{index}")
            for index in range(8)
        )

        engine.generate_hypotheses(evidence)

        assert transport.request_body is not None
        # The whole HTTP request exceeds 2 KB because of the fixed prompt and
        # strict schema, but the evidence itself stays within the 2 KB budget.
        self.assertGreater(len(transport.request_body), MAX_EVIDENCE_BYTES)
        self.assertLessEqual(evidence_summary_bytes(evidence), MAX_EVIDENCE_BYTES)
        self.assertIsNone(engine.last_failure_category)


if __name__ == "__main__":
    unittest.main()
