from __future__ import annotations

import json
import unittest
from dataclasses import replace

from src.agents.differential_request import (
    CAUSE_SCHEMA_NAME,
    CHALLENGE_SCHEMA_NAME,
    CauseEnvelope,
    ChallengeProposal,
    CheckPrompt,
    build_cause_request,
    build_challenge_request,
    validate_causes,
    validate_challenge,
)
from src.agents.model_transport import CompletionResponse, FailureCategory
from src.agents.rca_engine import RCAEngine
from src.analyze import RunResult
from src.config_types import CandidateConfig, ScenarioConfig
from src.core.constraints import ConstraintRule
from src.core.evidence import EvidenceStore
from src.core.sufficiency import PredicateConfig
from src.core.types import (
    AnalysisOutcome,
    Confidence,
    Evidence,
    EvidenceKind,
    Predicate,
    SuggestedAction,
    Verdict,
)
from src.model_config import ModelRoute
from src.schemas.models import (
    ChallengeStatus,
    DifferentialEntryModel,
    RCAOutputModel,
    RootCauseCategory,
)
from src.ui import presentation


def _evidence(
    kind: EvidenceKind, signal: str, evidence_id: str, value: float | None = None
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        kind=kind,
        signal=signal,
        statistic="robust_z_max",
        value=(
            value
            if value is not None
            else (5.0 if kind is EvidenceKind.SENSOR_ANOMALY else 0.1)
        ),
        unit=None,
        window=(1, 10),
        provenance="fixture rows 1-10",
        computed_by="robust_mad_zscore@v1",
        summary="fixture evidence",
        window_basis="row:fixture",
    )


def _scenario(
    claim: str,
    primary: tuple[str, ...],
    stay_normal: tuple[str, ...] = (),
    *,
    action: SuggestedAction = SuggestedAction.INSPECT_COMPONENT,
) -> ScenarioConfig:
    rule = ConstraintRule(
        require_all=frozenset({Predicate.HAS_ALL_PRIMARY_SIGNALS_ANOMALY}),
        forbid_any=frozenset({Predicate.HAS_MISSING_REQUIRED_EVIDENCE}),
        veto_if_any=(
            frozenset({Predicate.HAS_INSTRUMENTATION_CONTRADICTION})
            if stay_normal
            else frozenset()
        ),
    )
    return ScenarioConfig(
        signals=(),
        predicate_config=PredicateConfig(
            primary_signals=frozenset(primary),
            corroboration_signals=frozenset(stay_normal),
        ),
        rules={"equipment_fault": rule},
        candidate=CandidateConfig(
            claim=claim,
            hypothesis_class="equipment_fault",
            cited_signals=primary + stay_normal,
            root_cause=RootCauseCategory.EQUIPMENT_FAULT,
            failure_mode="Fixture failure mode.",
            mechanism="Fixture mechanism.",
        ),
        supported_action=action,
    )


def _with_scope_signal(scenario: ScenarioConfig, signal: str) -> ScenarioConfig:
    """Declare an extra signal as part of the model scope without making it primary."""
    predicate_config = replace(
        scenario.predicate_config,
        temporal_precedence_pairs=(("a", signal),),
    )
    candidate = replace(
        scenario.candidate,
        cited_signals=(*scenario.candidate.cited_signals, signal),
    )
    return replace(
        scenario, predicate_config=predicate_config, candidate=candidate
    )


def _route() -> ModelRoute:
    return ModelRoute(
        role="SYNTHESIS",
        model="fixture/model-v1",
        base_url="https://models.example/v1",
        api_key_env="TEST_MODEL_API_KEY",
        timeout_seconds=5.0,
    )


class ScriptedTransport:
    def __init__(
        self,
        *,
        causes: dict[str, object] | None = None,
        challenge: dict[str, object] | None = None,
        bad_causes: bool = False,
        bad_challenge: bool = False,
    ) -> None:
        self.causes: dict[str, object] = (
            causes if causes is not None else {"possible_causes": []}
        )
        self.challenge = challenge
        self.bad_causes = bad_causes
        self.bad_challenge = bad_challenge
        self.calls = 0

    def list_models(self, route: ModelRoute, api_key: str) -> tuple[str, ...]:
        return (route.model,)

    def complete(
        self, route: ModelRoute, api_key: str, body: bytes
    ) -> CompletionResponse:
        self.calls += 1
        request = json.loads(body)
        name = request["response_format"]["json_schema"]["name"]
        if name == CAUSE_SCHEMA_NAME:
            if self.bad_causes:
                return CompletionResponse("not json", "stop")
            return CompletionResponse(json.dumps(self.causes), "stop")
        if name == CHALLENGE_SCHEMA_NAME:
            if self.bad_challenge:
                return CompletionResponse("not json", "stop")
            if self.challenge is None:
                return CompletionResponse(
                    json.dumps(
                        {
                            "challenge": "fixture challenge",
                            "evidence": ["EV_A"],
                            "expected": "a unusual",
                        }
                    ),
                    "stop",
                )
            return CompletionResponse(json.dumps(self.challenge), "stop")
        raise AssertionError(f"unexpected schema {name}")


def _engine(transport: ScriptedTransport) -> RCAEngine:
    return RCAEngine(
        _route(),
        PredicateConfig(),
        {},
        "test-token",
        transport,
    )


class DifferentialEngineTests(unittest.TestCase):
    def test_all_checks_are_assessed_and_headline_prefers_support(self) -> None:
        transport = ScriptedTransport(
            causes={
                "possible_causes": [
                    {
                        "check": "one",
                        "title": "Fixture one",
                        "why": "a moved",
                        "evidence": ["EV_A"],
                    }
                ]
            }
        )
        engine = _engine(transport)
        scenarios = {
            "one": _scenario("One", ("a",)),
            "two": _scenario("Two", ("b", "c")),
        }
        evidence = (
            _evidence(EvidenceKind.SENSOR_ANOMALY, "a", "EV_A"),
            _evidence(EvidenceKind.SENSOR_ANOMALY, "b", "EV_B"),
            _evidence(EvidenceKind.SENSOR_ANOMALY, "c", "EV_C"),
        )

        result = engine.assess_checks(evidence, scenarios, preferred_check="one")

        self.assertEqual(len(result.differential), 2)
        self.assertEqual(result.headline_check, "two")
        self.assertEqual(result.alternative_count, 1)
        self.assertIs(result.outcome, AnalysisOutcome.ANALYSIS_SUPPORTED)
        self.assertEqual(result.hypotheses[0].claim, "Two")
        self.assertEqual(transport.calls, 2)  # cause finder + one challenge
        self.assertIsNotNone(result.challenge)
        assert result.challenge is not None
        self.assertIs(result.challenge.status, ChallengeStatus.CHECKED)

    def test_model_proposed_new_cause_is_needs_review_without_a_check(self) -> None:
        transport = ScriptedTransport(
            causes={
                "possible_causes": [
                    {
                        "check": "new",
                        "title": "Possible leak",
                        "why": "The flow channel settled high.",
                        "evidence": ["EV_A"],
                    }
                ]
            }
        )
        engine = _engine(transport)
        scenarios = {"known": _scenario("Known check", ("a",))}
        evidence = (_evidence(EvidenceKind.SENSOR_NOMINAL, "a", "EV_A"),)

        result = engine.assess_checks(evidence, scenarios, preferred_check="known")

        self.assertIs(result.outcome, AnalysisOutcome.ANALYSIS_INCONCLUSIVE)
        self.assertIs(
            result.suggested_next_action, SuggestedAction.ESCALATE_TO_ENGINEER
        )
        proposed = [item for item in result.differential if item.proposed_by_model]
        self.assertEqual(len(proposed), 1)
        self.assertIs(proposed[0].status, Verdict.INSUFFICIENT)
        self.assertEqual(proposed[0].title, "Possible leak")
        self.assertTrue(
            any(
                "no saved check" in item.lower()
                for item in result.required_next_checks
            )
        )

    def test_failed_challenge_downgrades_the_confirmed_check(self) -> None:
        transport = ScriptedTransport(
            causes={
                "possible_causes": [
                    {
                        "check": "coolant",
                        "title": "Coolant loop fault",
                        "why": "The primary channel moved.",
                        "evidence": ["EV_A"],
                    }
                ]
            },
            challenge={
                "challenge": "If this were real, the second channel would settle.",
                "evidence": ["EV_B"],
                "expected": "b normal",
            },
        )
        engine = _engine(transport)
        scenarios = {
            "coolant": _with_scope_signal(
                _scenario("Coolant loop fault", ("a",)), "b"
            )
        }
        evidence = (
            _evidence(EvidenceKind.SENSOR_ANOMALY, "a", "EV_A"),
            _evidence(EvidenceKind.SENSOR_ANOMALY, "b", "EV_B"),
        )

        result = engine.assess_checks(evidence, scenarios, preferred_check="coolant")

        self.assertIs(result.outcome, AnalysisOutcome.ANALYSIS_INCONCLUSIVE)
        self.assertIs(
            result.suggested_next_action, SuggestedAction.ESCALATE_TO_ENGINEER
        )
        self.assertIs(result.hypotheses[0].status, Verdict.INSUFFICIENT)
        assert result.challenge is not None
        self.assertIs(result.challenge.status, ChallengeStatus.DISCONFIRMED)
        self.assertTrue(result.challenge.downgraded)
        self.assertTrue(result.differential[0].challenge_failed)

    def test_met_challenge_keeps_the_confirmed_result(self) -> None:
        transport = ScriptedTransport(
            causes={
                "possible_causes": [
                    {
                        "check": "coolant",
                        "title": "Coolant loop fault",
                        "why": "The primary channel moved.",
                        "evidence": ["EV_A"],
                    }
                ]
            },
            challenge={
                "challenge": "The companion signal should be unusual.",
                "evidence": ["EV_C"],
                "expected": "c unusual",
            },
        )
        engine = _engine(transport)
        scenarios = {
            "coolant": _with_scope_signal(
                _scenario("Coolant loop fault", ("a",)), "c"
            )
        }
        evidence = (
            _evidence(EvidenceKind.SENSOR_ANOMALY, "a", "EV_A"),
            _evidence(EvidenceKind.SENSOR_ANOMALY, "c", "EV_C"),
        )

        result = engine.assess_checks(evidence, scenarios)

        self.assertIs(result.outcome, AnalysisOutcome.ANALYSIS_SUPPORTED)
        self.assertIs(result.hypotheses[0].status, Verdict.SUPPORTED)
        assert result.challenge is not None
        self.assertIs(result.challenge.status, ChallengeStatus.CHECKED)
        self.assertFalse(result.challenge.downgraded)

    def test_failed_model_call_still_returns_the_deterministic_result(self) -> None:
        transport = ScriptedTransport(bad_causes=True, bad_challenge=True)
        engine = _engine(transport)
        scenarios = {"coolant": _scenario("Coolant loop fault", ("a",))}
        evidence = (_evidence(EvidenceKind.SENSOR_ANOMALY, "a", "EV_A"),)

        result = engine.assess_checks(evidence, scenarios)

        self.assertIs(result.outcome, AnalysisOutcome.ANALYSIS_SUPPORTED)
        self.assertIs(result.hypotheses[0].status, Verdict.SUPPORTED)
        self.assertIs(result.suggested_next_action, SuggestedAction.INSPECT_COMPONENT)
        self.assertTrue(result.model_called)
        self.assertIs(engine.last_failure_category, FailureCategory.SCHEMA_VALIDATION)
        assert result.challenge is not None
        self.assertIs(result.challenge.status, ChallengeStatus.UNAVAILABLE)

    def test_unresolved_challenge_evidence_is_discarded(self) -> None:
        transport = ScriptedTransport(
            causes={
                "possible_causes": [
                    {
                        "check": "coolant",
                        "title": "Coolant loop fault",
                        "why": "The primary channel moved.",
                        "evidence": ["EV_A"],
                    }
                ]
            },
            challenge={
                "challenge": "Invented citation",
                "evidence": ["EV_INVENTED"],
                "expected": "b unusual",
            },
        )
        engine = _engine(transport)
        scenarios = {
            "coolant": _with_scope_signal(
                _scenario("Coolant loop fault", ("a",)), "b"
            )
        }
        evidence = (
            _evidence(EvidenceKind.SENSOR_ANOMALY, "a", "EV_A"),
            _evidence(EvidenceKind.SENSOR_NOMINAL, "b", "EV_B"),
        )

        result = engine.assess_checks(evidence, scenarios)

        self.assertIs(result.outcome, AnalysisOutcome.ANALYSIS_SUPPORTED)
        assert result.challenge is not None
        self.assertIs(result.challenge.status, ChallengeStatus.UNAVAILABLE)
        self.assertFalse(result.challenge.downgraded)

    def test_unresolved_cause_evidence_is_discarded(self) -> None:
        transport = ScriptedTransport(
            causes={
                "possible_causes": [
                    {
                        "check": "coolant",
                        "title": "Coolant loop fault",
                        "why": "The primary channel moved.",
                        "evidence": ["EV_INVENTED"],
                    }
                ]
            }
        )
        engine = _engine(transport)
        scenarios = {"coolant": _scenario("Coolant loop fault", ("a",))}
        evidence = (_evidence(EvidenceKind.SENSOR_ANOMALY, "a", "EV_A"),)

        result = engine.assess_checks(evidence, scenarios)

        self.assertIs(result.outcome, AnalysisOutcome.ANALYSIS_SUPPORTED)
        self.assertIsNone(result.hypotheses[0].model_narrative)
        self.assertTrue(
            any("unresolved evidence" in item for item in result.required_next_checks)
        )


class DifferentialRequestTests(unittest.TestCase):
    def test_cause_request_uses_saved_check_ids_and_new(self) -> None:
        body = build_cause_request(
            "fixture/model-v1",
            (_evidence(EvidenceKind.SENSOR_ANOMALY, "a", "EV_A"),),
            (CheckPrompt("coolant", "Coolant loop fault", ("a",), ("b",)),),
        )
        request = json.loads(body)
        self.assertEqual(
            request["response_format"]["json_schema"]["name"], CAUSE_SCHEMA_NAME
        )
        schema = request["response_format"]["json_schema"]["schema"]
        item = schema["properties"]["possible_causes"]["items"]
        self.assertEqual(item["properties"]["check"]["enum"], ["coolant", "new"])
        self.assertEqual(item["required"], ["check", "title", "why", "evidence"])
        self.assertIn("checks", json.loads(request["messages"][1]["content"]))

    def test_challenge_request_requires_an_exact_signal_expectation(self) -> None:
        body = build_challenge_request(
            "fixture/model-v1",
            (_evidence(EvidenceKind.SENSOR_ANOMALY, "a", "EV_A"),),
            CheckPrompt("coolant", "Coolant loop fault", ("a",), ()),
        )
        request = json.loads(body)
        self.assertEqual(
            request["response_format"]["json_schema"]["name"], CHALLENGE_SCHEMA_NAME
        )
        schema = request["response_format"]["json_schema"]["schema"]
        self.assertEqual(
            schema["required"], ["challenge", "evidence", "expected"]
        )
        self.assertIn("unusual", request["messages"][0]["content"])

    def test_cause_validation_discards_unknown_check_and_unresolved_id(self) -> None:
        evidence = (_evidence(EvidenceKind.SENSOR_ANOMALY, "a", "EV_A"),)
        store = EvidenceStore(evidence)
        envelope = CauseEnvelope.model_validate(
            {
                "possible_causes": [
                    {
                        "check": "unknown",
                        "title": "Unknown",
                        "why": "no",
                        "evidence": ["EV_A"],
                    },
                    {
                        "check": "coolant",
                        "title": "Coolant",
                        "why": "yes",
                        "evidence": ["EV_INVENTED"],
                    },
                    {
                        "check": "coolant",
                        "title": "Coolant",
                        "why": "yes",
                        "evidence": ["EV_A"],
                    },
                ]
            }
        )
        causes, discarded = validate_causes(
            envelope, frozenset({"coolant"}), store
        )
        self.assertEqual(discarded, 2)
        self.assertEqual(len(causes), 1)
        self.assertEqual(causes[0].check, "coolant")

    def test_challenge_validation_parses_both_expectations(self) -> None:
        evidence = (
            _evidence(EvidenceKind.SENSOR_ANOMALY, "a", "EV_A"),
            _evidence(EvidenceKind.SENSOR_NOMINAL, "b", "EV_B"),
        )
        store = EvidenceStore(evidence)
        unusual = ChallengeProposal.model_validate(
            {
                "challenge": "c",
                "evidence": ["EV_A"],
                "expected": "a unusual",
            }
        )
        nominal = ChallengeProposal.model_validate(
            {
                "challenge": "c",
                "evidence": ["EV_B"],
                "expected": "b normal",
            }
        )
        bad = ChallengeProposal.model_validate(
            {
                "challenge": "c",
                "evidence": ["EV_A"],
                "expected": "a sideways",
            }
        )
        unusual_result = validate_challenge(unusual, evidence, store)
        nominal_result = validate_challenge(nominal, evidence, store)
        assert unusual_result is not None
        assert nominal_result is not None
        self.assertTrue(unusual_result.expectation_met)
        self.assertTrue(nominal_result.expectation_met)
        self.assertIsNone(validate_challenge(bad, evidence, store))


class DifferentialPresentationTests(unittest.TestCase):
    def test_proposed_cause_without_saved_check_is_needs_review(self) -> None:
        output = RCAOutputModel(
            outcome=AnalysisOutcome.ANALYSIS_INCONCLUSIVE,
            analysis_performed=True,
            model_called=True,
            suggested_next_action=SuggestedAction.ESCALATE_TO_ENGINEER,
            explanation="",
            confidence=Confidence.INSUFFICIENT,
            hypotheses=[],
            differential=[
                DifferentialEntryModel(
                    check="new",
                    title="Possible leak",
                    root_cause=RootCauseCategory.UNKNOWN,
                    status=Verdict.INSUFFICIENT,
                    evidence_for=["EV_A"],
                    action=SuggestedAction.ESCALATE_TO_ENGINEER,
                    reason="unverified",
                    proposed_by_model=True,
                )
            ],
        )
        result = RunResult(
            csv_path="fixture.csv",
            engineer_note="",
            mode="safe",
            fallback_used=False,
            outcome=AnalysisOutcome.ANALYSIS_INCONCLUSIVE,
            suggested_next_action=SuggestedAction.ESCALATE_TO_ENGINEER,
            explanation="",
            detail=None,
            analysis_performed=True,
            model_called=True,
            selection=None,
            mapping=None,
            evidence=(_evidence(EvidenceKind.SENSOR_ANOMALY, "a", "EV_A"),),
            output=output,
        )

        self.assertEqual(presentation.result_word(result), "Needs Review")
        card = presentation.answer_card(result)
        self.assertIn("Possible leak", card.headline)
        self.assertEqual(card.confidence_label, "Needs Review")


if __name__ == "__main__":
    unittest.main()
