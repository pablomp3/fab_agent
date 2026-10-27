from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path

from pydantic import ValidationError

from src.action_guidance import action_explanation, default_action_for
from src.agents.differential import (
    CheckOutcome,
    action_for,
    assess_check,
    build_differential_entry,
    build_hypothesis,
    build_unconfigured_entry,
    choose_headline,
    configured_scope,
    with_challenge_failure,
)
from src.agents.differential_request import (
    DEFAULT_CAUSE_MAX_TOKENS,
    DEFAULT_CHALLENGE_MAX_TOKENS,
    CauseEnvelope,
    ChallengeProposal,
    CheckPrompt,
    ValidatedCause,
    ValidatedChallenge,
    build_cause_request,
    build_challenge_request,
    validate_causes,
    validate_challenge,
)
from src.agents.model_transport import (
    FailureCategory,
    ModelIntegrationError,
    ModelTransport,
    OpenAICompatibleTransport,
)
from src.agents.proposal_request import (
    DEFAULT_MAX_TOKENS,
    MAX_RESPONSE_BYTES,
    HypothesisProposal,
    ProposalEnvelope,
    build_proposal_request,
)
from src.agents.validation_diagnostics import (
    FinishReasonDetail,
    ValidationDetail,
    sanitized_finish_reason,
    sanitized_validation_details,
)
from src.config_types import CandidateConfig, ScenarioConfig
from src.core.constraints import ConstraintRule
from src.core.evidence import EvidenceStore, PayloadTooLarge
from src.core.pipeline import Candidate, CandidateAssessment, assess_candidate
from src.core.sufficiency import PredicateConfig
from src.core.types import (
    AnalysisOutcome,
    Confidence,
    Evidence,
    EvidenceKind,
    SuggestedAction,
    Verdict,
)
from src.model_config import ModelRoute, load_api_key, load_model_route
from src.policy import COVERAGE_UNEXPLAINED_LARGE_Z
from src.schemas.models import (
    ChallengeModel,
    ChallengeStatus,
    CoverageModel,
    DifferentialEntryModel,
    HypothesisModel,
    ModelNarrative,
    RCAOutputModel,
    RootCauseCategory,
)

_LOGGER = logging.getLogger(__name__)


def _fail_closed() -> RCAOutputModel:
    return RCAOutputModel(
        outcome=AnalysisOutcome.MODEL_REJECTED,
        analysis_performed=True,
        model_called=True,
        suggested_next_action=SuggestedAction.RETRY_ANALYSIS,
        explanation=action_explanation(SuggestedAction.RETRY_ANALYSIS),
        confidence=Confidence.INSUFFICIENT,
        required_next_checks=[
            "Model unavailable or response invalid; review deterministic evidence."
        ],
    )


def _gated_root_cause(
    status: Verdict, root_cause: RootCauseCategory
) -> RootCauseCategory:
    """A contradiction is an instrumentation finding, not the configured cause."""
    return (
        RootCauseCategory.INSTRUMENTATION_FAULT
        if status is Verdict.VETOED
        else root_cause
    )


def _gated_action(
    outcome: AnalysisOutcome,
    supported_action: SuggestedAction,
    evidence: tuple[Evidence, ...],
    *,
    incomplete: bool = False,
) -> SuggestedAction:
    """Pick the Python-owned action; a lone anomaly is never "all normal"."""
    if outcome is AnalysisOutcome.ANALYSIS_SUPPORTED:
        return supported_action
    if outcome is AnalysisOutcome.ANALYSIS_INCONCLUSIVE:
        if incomplete:
            return SuggestedAction.COLLECT_MORE_DATA
        if any(item.kind is EvidenceKind.SENSOR_ANOMALY for item in evidence):
            # Something moved, every declared channel was evaluated, and no
            # configured check explained it. A human should look before more data
            # is collected or the anomaly is ignored.
            return SuggestedAction.ESCALATE_TO_ENGINEER
        # Every checked channel was evaluated and stayed within its limit. There
        # is no fault to inspect and nothing missing; keep watching.
        return SuggestedAction.CONTINUE_MONITORING
    return default_action_for(outcome)


def _candidate_citations(
    candidate: CandidateConfig, evidence: tuple[Evidence, ...]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Resolve configured signal names to the evidence records Python gates on.

    A configured channel that produced no evidence is returned as missing; the
    caller surfaces it as a required next check rather than inventing a record.
    """
    by_signal: dict[str, list[str]] = {}
    for item in evidence:
        if item.signal is not None:
            by_signal.setdefault(item.signal, []).append(item.evidence_id)
    cited: list[str] = []
    missing: list[str] = []
    for signal in candidate.cited_signals:
        evidence_ids = by_signal.get(signal)
        if not evidence_ids:
            missing.append(signal)
            continue
        for evidence_id in evidence_ids:
            if evidence_id not in cited:
                cited.append(evidence_id)
    return tuple(cited), tuple(missing)


def _select_model_narrative(
    proposals: list[HypothesisProposal],
    candidate: CandidateConfig,
    store: EvidenceStore,
) -> ModelNarrative | None:
    """Choose the model proposal that explains the configured candidate.

    The model may propose alternatives. Prefer the proposal with the configured
    class; otherwise use the first proposal so the user still sees the model's
    reasoning, clearly labelled as a narrative rather than the gate.
    """
    matched = [
        item
        for item in proposals
        if item.hypothesis_class == candidate.hypothesis_class
    ]
    chosen = matched[0] if matched else (proposals[0] if proposals else None)
    if chosen is None:
        return None
    _, unresolved = store.resolve_all(tuple(chosen.cited_evidence))
    return ModelNarrative(
        claim=chosen.claim,
        root_cause=chosen.root_cause,
        failure_mode=chosen.failure_mode,
        mechanism=chosen.mechanism,
        hypothesis_class=chosen.hypothesis_class,
        cited_evidence=list(chosen.cited_evidence),
        unresolved_citations=list(unresolved),
    )


def _gated_next_checks(
    candidate: CandidateConfig,
    evidence: tuple[Evidence, ...],
    missing_signals: tuple[str, ...],
    assessment: CandidateAssessment,
    status: Verdict,
    narrative: ModelNarrative | None,
    predicate_config: PredicateConfig,
    failure_note: str | None,
    *,
    challenge_failed: bool = False,
) -> list[str]:
    checks: list[str] = []
    if missing_signals:
        checks.append(
            "No evidence was produced for configured channel(s): "
            + ", ".join(missing_signals)
            + ". Confirm the export includes them."
        )
    present_ids = {item.evidence_id for item in evidence}
    missing_ids = sorted(predicate_config.required_evidence_ids - present_ids)
    if missing_ids:
        checks.append(
            "Required evidence IDs are absent from this run: "
            + ", ".join(missing_ids)
            + "."
        )
    if status is Verdict.VETOED:
        vetoed = ", ".join(item.value for item in assessment.constraints.vetoed)
        checks.append(f"Resolve the contradiction before acting: {vetoed}.")
    elif status is Verdict.INSUFFICIENT:
        if challenge_failed:
            checks.append(
                "The AI challenge check did not support this saved check; review "
                "it before acting."
            )
        elif assessment.constraints.verdict is Verdict.SUPPORTED:
            checks.append(
                "The configured check passed, but large anomalies outside it "
                "prevent a bare confirmation."
            )
        else:
            checks.append(
                "The configured candidate did not meet every required predicate; "
                "collect or verify the missing channels."
            )
    if assessment.coverage.unexplained_large:
        checks.append(
            "Large anomalies outside the configured check: "
            + ", ".join(assessment.coverage.unexplained_large)
            + ". Review them before accepting the result."
        )
    elif assessment.coverage.unexplained:
        checks.append(
            "Other declared channels moved outside the configured check: "
            + ", ".join(assessment.coverage.unexplained)
            + ". Review the pattern."
        )
    if narrative is None:
        checks.append(
            "No model narrative was available; the deterministic gate above is "
            "the result."
        )
    elif narrative.unresolved_citations:
        checks.append(
            "The model cited unresolved evidence IDs ("
            + ", ".join(narrative.unresolved_citations)
            + "); they are shown for review only and are not gate evidence."
        )
    if failure_note:
        checks.append(
            f"Model narrative unavailable ({failure_note}); the deterministic "
            "gate was applied."
        )
    if not checks and status is Verdict.SUPPORTED:
        checks.append(
            f"Have a human confirm the configured candidate: {candidate.claim}."
        )
    return checks


class RCAEngine:
    """Generate proposals, then replace every model judgment with Python gates."""

    def __init__(
        self,
        route: ModelRoute,
        predicate_config: PredicateConfig,
        rules: Mapping[str, ConstraintRule],
        api_key: str,
        transport: ModelTransport | None = None,
    ) -> None:
        if not api_key:
            raise ModelIntegrationError(
                f"{route.role}.api_key_env is empty", FailureCategory.TRANSPORT
            )
        self._route = route
        self._predicate_config = predicate_config
        self._rules = rules
        self._api_key = api_key
        self._transport = (
            OpenAICompatibleTransport() if transport is None else transport
        )
        self._last_failure_category: FailureCategory | None = None
        self._last_finish_reason: FinishReasonDetail | None = None
        self._last_validation_details: tuple[ValidationDetail, ...] | None = None
        self._last_outcome: AnalysisOutcome | None = None
        try:
            model_ids = self._transport.list_models(route, api_key)
        except ModelIntegrationError as exc:
            raise ModelIntegrationError(
                f"{route.role} preflight failed", exc.category
            ) from exc
        if route.model not in model_ids:
            raise ModelIntegrationError(
                f"{route.role}.model is not available from the configured provider",
                FailureCategory.TRANSPORT,
            )

    @property
    def last_failure_category(self) -> FailureCategory | None:
        """Return only a fixed, sanitized category for the latest proposal call."""
        return self._last_failure_category

    @property
    def last_validation_details(self) -> tuple[ValidationDetail, ...] | None:
        """Return allowlisted validation labels, never model text or field names."""
        return self._last_validation_details

    @property
    def last_finish_reason(self) -> FinishReasonDetail | None:
        """Return only a known finish-reason label or the generic other label."""
        return self._last_finish_reason

    @property
    def last_outcome(self) -> AnalysisOutcome | None:
        """Return the route taken by the latest proposal call, if any."""
        return self._last_outcome

    def _record_failure(
        self,
        category: FailureCategory,
        details: tuple[ValidationDetail, ...] | None = None,
        finish_reason: FinishReasonDetail | None = None,
    ) -> None:
        self._last_failure_category = category
        self._last_validation_details = details
        self._last_finish_reason = finish_reason
        self._last_outcome = AnalysisOutcome.MODEL_REJECTED
        if details:
            labels = ",".join(item.value for item in details)
            _LOGGER.warning(
                "Model completion rejected; category=%s validation_detail=%s",
                category.value,
                labels,
            )
        elif finish_reason:
            _LOGGER.warning(
                "Model completion rejected; category=%s finish_detail=%s",
                category.value,
                finish_reason.value,
            )
        else:
            _LOGGER.warning("Model completion rejected; category=%s", category.value)

    def _fail(
        self,
        category: FailureCategory,
        details: tuple[ValidationDetail, ...] | None = None,
        finish_reason: FinishReasonDetail | None = None,
    ) -> RCAOutputModel:
        self._record_failure(category, details, finish_reason)
        return _fail_closed()

    def _gate_candidate(
        self,
        evidence: tuple[Evidence, ...],
        candidate: CandidateConfig,
        supported_action: SuggestedAction,
        *,
        narrative: ModelNarrative | None = None,
        failure_note: str | None = None,
    ) -> RCAOutputModel:
        """Gate the configuration-authored candidate, not the model's claim."""
        citations, missing_signals = _candidate_citations(candidate, evidence)
        assessment = assess_candidate(
            Candidate(
                claim=candidate.claim,
                hypothesis_class=candidate.hypothesis_class,
                cited_evidence=citations,
            ),
            EvidenceStore(evidence),
            self._predicate_config,
            self._rules,
            supported_action,
            large_z=COVERAGE_UNEXPLAINED_LARGE_Z,
        )
        status = assessment.constraints.verdict
        if missing_signals and status is not Verdict.VETOED:
            # A configured channel with no evidence means the candidate is not
            # fully assessed, even if the remaining citations look sufficient.
            status = Verdict.INSUFFICIENT
        if (
            status is Verdict.SUPPORTED
            and assessment.coverage.unexplained_large
        ):
            # A large anomaly outside the check means the confirmation is not
            # broad enough. Python demotes it; the model cannot argue it back.
            status = Verdict.INSUFFICIENT
        if status is Verdict.VETOED:
            outcome = AnalysisOutcome.ANALYSIS_CONTRADICTED
        elif status is Verdict.SUPPORTED:
            outcome = AnalysisOutcome.ANALYSIS_SUPPORTED
        else:
            outcome = AnalysisOutcome.ANALYSIS_INCONCLUSIVE
        action = _gated_action(
            outcome,
            supported_action,
            evidence,
            incomplete=bool(missing_signals or assessment.unresolved_evidence),
        )
        hypothesis = HypothesisModel(
            claim=candidate.claim,
            root_cause=_gated_root_cause(status, candidate.root_cause),
            failure_mode=candidate.failure_mode,
            mechanism=candidate.mechanism,
            hypothesis_class=candidate.hypothesis_class,
            cited_evidence=list(citations),
            status=status,
            veto_reason=(
                ", ".join(item.value for item in assessment.constraints.vetoed)
                if assessment.constraints.vetoed
                else None
            ),
            model_narrative=narrative,
        )
        self._last_outcome = outcome
        return RCAOutputModel(
            outcome=outcome,
            analysis_performed=True,
            model_called=True,
            suggested_next_action=action,
            explanation=action_explanation(action),
            confidence=(
                Confidence.LOW
                if status is Verdict.SUPPORTED
                else Confidence.INSUFFICIENT
            ),
            hypotheses=[hypothesis],
            required_next_checks=_gated_next_checks(
                candidate,
                evidence,
                missing_signals,
                assessment,
                status,
                narrative,
                self._predicate_config,
                failure_note,
            ),
            coverage=CoverageModel(
                explained=list(assessment.coverage.explained),
                unexplained=list(assessment.coverage.unexplained),
                unexplained_large=list(assessment.coverage.unexplained_large),
            ),
        )

    def _reset_diagnostics(self) -> None:
        self._last_failure_category = None
        self._last_finish_reason = None
        self._last_validation_details = None
        self._last_outcome = None

    def _complete(self, body: bytes) -> tuple[str | None, FailureCategory | None]:
        """Run one bounded completion and record only a sanitized failure."""
        try:
            completion = self._transport.complete(self._route, self._api_key, body)
        except ModelIntegrationError as exc:
            self._record_failure(exc.category)
            return None, exc.category
        if completion.finish_reason != "stop":
            category = FailureCategory.FINISH_REASON
            self._record_failure(
                category,
                finish_reason=sanitized_finish_reason(completion.finish_reason),
            )
            return None, category
        if len(completion.content.encode("utf-8")) > MAX_RESPONSE_BYTES:
            self._record_failure(FailureCategory.SIZE)
            return None, FailureCategory.SIZE
        return completion.content, None

    def _parse_causes(self, content: str) -> CauseEnvelope | None:
        try:
            return CauseEnvelope.model_validate_json(content, strict=True)
        except ValidationError as exc:
            self._record_failure(
                FailureCategory.SCHEMA_VALIDATION,
                sanitized_validation_details(exc),
            )
            return None
        except ValueError:
            self._record_failure(
                FailureCategory.SCHEMA_VALIDATION,
                (ValidationDetail.INVALID_VALUE,),
            )
            return None

    def _parse_challenge(self, content: str) -> ChallengeProposal | None:
        try:
            return ChallengeProposal.model_validate_json(content, strict=True)
        except ValidationError as exc:
            self._record_failure(
                FailureCategory.SCHEMA_VALIDATION,
                sanitized_validation_details(exc),
            )
            return None
        except ValueError:
            self._record_failure(
                FailureCategory.SCHEMA_VALIDATION,
                (ValidationDetail.INVALID_VALUE,),
            )
            return None

    @staticmethod
    def _challenge_unavailable(note: str) -> ChallengeModel:
        return ChallengeModel(status=ChallengeStatus.UNAVAILABLE, note=note)

    def _run_challenge(
        self,
        evidence: tuple[Evidence, ...],
        store: EvidenceStore,
        outcome: CheckOutcome,
        max_tokens: int,
    ) -> ChallengeModel:
        candidate = outcome.scenario.candidate
        check = CheckPrompt(
            check_id=outcome.check_id,
            label=candidate.claim,
            primary=tuple(sorted(outcome.scenario.predicate_config.primary_signals)),
            stay_normal=tuple(
                sorted(
                    outcome.scenario.predicate_config.forbidden_anomaly_signals
                )
            ),
        )
        challenge_tokens = max(1, min(max_tokens, DEFAULT_CHALLENGE_MAX_TOKENS))
        try:
            body = build_challenge_request(
                self._route.model,
                evidence,
                check,
                max_tokens=challenge_tokens,
            )
        except PayloadTooLarge:
            return self._challenge_unavailable(
                "The AI challenge request exceeded its budget; the deterministic "
                "result is unchanged."
            )
        content, _ = self._complete(body)
        if content is None:
            return self._challenge_unavailable(
                "The AI challenge call failed; the deterministic result is unchanged."
            )
        proposal = self._parse_challenge(content)
        if proposal is None:
            return self._challenge_unavailable(
                "The AI challenge response could not be validated; it was discarded."
            )
        validated: ValidatedChallenge | None = validate_challenge(
            proposal,
            evidence,
            store,
            primary_signals=outcome.scenario.predicate_config.primary_signals,
        )
        if validated is None:
            return self._challenge_unavailable(
                "The AI challenge cited unresolved evidence or an unrecognised "
                "expectation; it was discarded."
            )
        return ChallengeModel(
            status=(
                ChallengeStatus.CHECKED
                if validated.expectation_met
                else ChallengeStatus.DISCONFIRMED
            ),
            text=validated.text,
            expected=validated.expected,
            cited_evidence=list(validated.cited_evidence),
            target_signal=validated.target_signal,
            expectation_met=validated.expectation_met,
            downgraded=not validated.expectation_met,
        )

    def _cause_prompts(
        self, scenarios: Mapping[str, ScenarioConfig]
    ) -> tuple[CheckPrompt, ...]:
        return tuple(
            CheckPrompt(
                check_id=check_id,
                label=scenario.candidate.claim,
                primary=tuple(sorted(scenario.predicate_config.primary_signals)),
                stay_normal=tuple(
                    sorted(
                        scenario.predicate_config.forbidden_anomaly_signals
                    )
                ),
            )
            for check_id, scenario in scenarios.items()
        )

    @staticmethod
    def _narrative_for_cause(
        cause: ValidatedCause, scenario: ScenarioConfig
    ) -> ModelNarrative:
        candidate = scenario.candidate
        return ModelNarrative(
            claim=cause.title,
            root_cause=candidate.root_cause,
            failure_mode=candidate.failure_mode,
            mechanism=cause.why,
            hypothesis_class=candidate.hypothesis_class,
            cited_evidence=list(cause.cited_evidence),
        )

    @staticmethod
    def _empty_analysis() -> RCAOutputModel:
        action = default_action_for(AnalysisOutcome.NO_PROPOSALS)
        return RCAOutputModel(
            outcome=AnalysisOutcome.NO_PROPOSALS,
            analysis_performed=False,
            model_called=False,
            suggested_next_action=action,
            explanation=action_explanation(action),
            confidence=Confidence.INSUFFICIENT,
            required_next_checks=[
                "No scoped evidence was available to analyze; review the scope."
            ],
        )

    def assess_checks(
        self,
        evidence: tuple[Evidence, ...],
        scenarios: Mapping[str, ScenarioConfig],
        *,
        context: str | None = None,
        max_tokens: int = DEFAULT_CAUSE_MAX_TOKENS,
        preferred_check: str | None = None,
    ) -> RCAOutputModel:
        """Score every saved check, then apply one bounded challenge if confirmed.

        The model may propose a saved check or a new cause. A new cause is never
        actionable; it is rendered as an unverified differential row. A model
        failure leaves the Python assessment intact.
        """
        self._reset_diagnostics()
        if not evidence:
            self._last_outcome = AnalysisOutcome.NO_PROPOSALS
            return self._empty_analysis()

        store = EvidenceStore(evidence)
        failure_note: str | None = None
        discarded = 0
        causes: tuple[ValidatedCause, ...] = ()
        try:
            body = build_cause_request(
                self._route.model,
                evidence,
                self._cause_prompts(scenarios),
                max_tokens=max_tokens,
                context=context,
            )
        except PayloadTooLarge:
            self._last_failure_category = FailureCategory.SIZE
            self._last_outcome = AnalysisOutcome.EVIDENCE_TOO_LARGE
            _LOGGER.warning("Model request rejected; category=%s", FailureCategory.SIZE)
            raise
        content, category = self._complete(body)
        if content is None:
            failure_note = category.value if category is not None else "model_failure"
        else:
            envelope = self._parse_causes(content)
            if envelope is None:
                failure_note = FailureCategory.SCHEMA_VALIDATION.value
            else:
                causes, discarded = validate_causes(
                    envelope, frozenset(scenarios), store
                )

        narratives: dict[str, ModelNarrative] = {}
        unconfigured: list[ValidatedCause] = []
        for cause in causes:
            if cause.is_new:
                unconfigured.append(cause)
            else:
                scenario = scenarios.get(cause.check)
                if scenario is not None:
                    narratives[cause.check] = self._narrative_for_cause(cause, scenario)

        scope = configured_scope(scenarios)
        outcomes = tuple(
            assess_check(
                check_id,
                scenario,
                evidence,
                store,
                narratives.get(check_id),
                coverage_scope=scope,
            )
            for check_id, scenario in scenarios.items()
        )
        headline = choose_headline(outcomes, preferred_check)
        challenge: ChallengeModel | None = None
        challenged_label: str | None = None
        if headline is not None and headline.status is Verdict.SUPPORTED:
            challenged_label = headline.scenario.candidate.claim
            challenge = self._run_challenge(evidence, store, headline, max_tokens)
            if challenge.downgraded:
                failed_id = headline.check_id
                outcomes = tuple(
                    with_challenge_failure(item)
                    if item.check_id == failed_id
                    else item
                    for item in outcomes
                )
                headline = choose_headline(outcomes, preferred_check)

        supported = tuple(item for item in outcomes if item.status is Verdict.SUPPORTED)
        alternative_count = max(0, len(supported) - 1)
        if headline is None:
            outcome = (
                AnalysisOutcome.ANALYSIS_INCONCLUSIVE
                if unconfigured
                else AnalysisOutcome.NO_PROPOSALS
            )
            action = (
                SuggestedAction.ESCALATE_TO_ENGINEER
                if unconfigured
                else default_action_for(outcome)
            )
        elif headline.status is Verdict.SUPPORTED:
            outcome = AnalysisOutcome.ANALYSIS_SUPPORTED
            action = action_for(headline)
        elif headline.status is Verdict.VETOED:
            outcome = AnalysisOutcome.ANALYSIS_CONTRADICTED
            action = action_for(headline)
        else:
            outcome = AnalysisOutcome.ANALYSIS_INCONCLUSIVE
            action = action_for(headline)
            if unconfigured and action is SuggestedAction.CONTINUE_MONITORING:
                action = SuggestedAction.ESCALATE_TO_ENGINEER

        ordered = (
            tuple([headline] + [item for item in outcomes if item is not headline])
            if headline is not None
            else outcomes
        )
        hypotheses = [build_hypothesis(item) for item in ordered]
        differential: list[DifferentialEntryModel] = [
            build_differential_entry(item) for item in ordered
        ]
        differential.extend(build_unconfigured_entry(item) for item in unconfigured)

        checks: list[str] = []
        if headline is not None:
            checks = _gated_next_checks(
                headline.scenario.candidate,
                evidence,
                headline.missing_signals,
                headline.assessment,
                headline.status,
                headline.narrative,
                headline.scenario.predicate_config,
                failure_note,
                challenge_failed=headline.challenge_failed,
            )
        elif failure_note:
            checks.append(
                "No saved check exists and the AI explanation was unavailable; "
                "review the draft mapping."
            )
        else:
            checks.append(
                "No saved check exists for this export; review the draft mapping "
                "before acting on any proposed cause."
            )
        if discarded:
            checks.append(
                "The AI proposed one or more causes with unresolved evidence or an "
                "unknown check; those proposals were discarded."
            )
        if unconfigured:
            titles = ", ".join(item.title for item in unconfigured)
            checks.append(
                "The AI proposed a cause with no saved check: "
                f"{titles}. It stays Needs Review; add and test a saved check to "
                "act on this proposal."
            )
        if (
            challenge is not None
            and challenge.downgraded
            and challenged_label is not None
            and (headline is None or not headline.challenge_failed)
        ):
            checks.append(
                f"The AI challenge check did not support {challenged_label}; "
                "the differential marks it for review."
            )
        if len(supported) > 1:
            checks.append(
                "More than one saved check was confirmed; review the differential "
                "before acting."
            )

        coverage = (
            CoverageModel(
                explained=list(headline.assessment.coverage.explained),
                unexplained=list(headline.assessment.coverage.unexplained),
                unexplained_large=list(
                    headline.assessment.coverage.unexplained_large
                ),
            )
            if headline is not None
            else None
        )
        self._last_outcome = outcome
        return RCAOutputModel(
            outcome=outcome,
            analysis_performed=True,
            model_called=True,
            suggested_next_action=action,
            explanation=action_explanation(action),
            confidence=(
                Confidence.LOW
                if headline is not None and headline.status is Verdict.SUPPORTED
                else Confidence.INSUFFICIENT
            ),
            hypotheses=hypotheses,
            required_next_checks=checks,
            coverage=coverage,
            differential=differential,
            headline_check=None if headline is None else headline.check_id,
            alternative_count=alternative_count,
            challenge=challenge,
        )

    def generate_hypotheses(
        self,
        evidence: tuple[Evidence, ...],
        *,
        context: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        supported_action: SuggestedAction = SuggestedAction.ESCALATE_TO_ENGINEER,
        candidate: CandidateConfig | None = None,
    ) -> RCAOutputModel:
        self._reset_diagnostics()
        if not evidence:
            # Internal guard: a scenario always declares at least one channel.
            # No model call is attempted, so this is not a model rejection.
            self._last_outcome = AnalysisOutcome.NO_PROPOSALS
            action = default_action_for(AnalysisOutcome.NO_PROPOSALS)
            return RCAOutputModel(
                outcome=AnalysisOutcome.NO_PROPOSALS,
                analysis_performed=False,
                model_called=False,
                suggested_next_action=action,
                explanation=action_explanation(action),
                confidence=Confidence.INSUFFICIENT,
                required_next_checks=[
                    "No scoped evidence was available to analyze; review the scope."
                ],
            )

        def failed(
            category: FailureCategory,
            details: tuple[ValidationDetail, ...] | None = None,
            finish_reason: FinishReasonDetail | None = None,
        ) -> RCAOutputModel:
            self._record_failure(category, details, finish_reason)
            if candidate is not None:
                # The deterministic gate does not depend on a model narrative.
                return self._gate_candidate(
                    evidence,
                    candidate,
                    supported_action,
                    failure_note=category.value,
                )
            return _fail_closed()

        effective_context = context
        if candidate is not None:
            configured = (
                f"Configured candidate: {candidate.claim} "
                f"({candidate.hypothesis_class}). Explain it and cite the "
                "evidence that supports or contradicts it."
            )
            effective_context = (
                configured if not context else f"{configured}\n{context}"
            )
        try:
            body = build_proposal_request(
                self._route.model,
                evidence,
                tuple(sorted(self._rules)),
                max_tokens,
                context=effective_context,
            )
        except PayloadTooLarge:
            self._last_failure_category = FailureCategory.SIZE
            self._last_outcome = AnalysisOutcome.EVIDENCE_TOO_LARGE
            _LOGGER.warning("Model request rejected; category=%s", FailureCategory.SIZE)
            raise
        try:
            completion = self._transport.complete(self._route, self._api_key, body)
        except ModelIntegrationError as exc:
            return failed(exc.category)
        if completion.finish_reason != "stop":
            return failed(
                FailureCategory.FINISH_REASON,
                finish_reason=sanitized_finish_reason(completion.finish_reason),
            )
        if len(completion.content.encode("utf-8")) > MAX_RESPONSE_BYTES:
            return failed(FailureCategory.SIZE)
        try:
            proposals = ProposalEnvelope.model_validate_json(
                completion.content, strict=True
            )
        except ValidationError as exc:
            return failed(
                FailureCategory.SCHEMA_VALIDATION,
                sanitized_validation_details(exc),
            )
        except ValueError:
            return failed(
                FailureCategory.SCHEMA_VALIDATION,
                (ValidationDetail.INVALID_VALUE,),
            )

        store = EvidenceStore(evidence)
        if candidate is not None:
            narrative = _select_model_narrative(proposals.hypotheses, candidate, store)
            return self._gate_candidate(
                evidence,
                candidate,
                supported_action,
                narrative=narrative,
            )

        hypotheses: list[HypothesisModel] = []
        any_unresolved = False
        for proposal in proposals.hypotheses:
            proposal_candidate = Candidate(
                claim=proposal.claim,
                hypothesis_class=proposal.hypothesis_class,
                cited_evidence=tuple(proposal.cited_evidence),
            )
            assessment = assess_candidate(
                proposal_candidate,
                store,
                self._predicate_config,
                self._rules,
                supported_action,
                large_z=COVERAGE_UNEXPLAINED_LARGE_Z,
            )
            if assessment.unresolved_evidence:
                any_unresolved = True
            status = assessment.constraints.verdict
            if status is Verdict.SUPPORTED and assessment.coverage.unexplained_large:
                status = Verdict.INSUFFICIENT
            hypotheses.append(
                HypothesisModel(
                    claim=proposal.claim,
                    root_cause=_gated_root_cause(status, proposal.root_cause),
                    failure_mode=proposal.failure_mode,
                    mechanism=proposal.mechanism,
                    hypothesis_class=proposal.hypothesis_class,
                    cited_evidence=proposal.cited_evidence,
                    status=status,
                    veto_reason=(
                        ", ".join(item.value for item in assessment.constraints.vetoed)
                        if assessment.constraints.vetoed
                        else None
                    ),
                )
            )
        if not hypotheses:
            outcome = AnalysisOutcome.NO_PROPOSALS
        elif any(item.status is Verdict.VETOED for item in hypotheses):
            # A hard contradiction is the strongest signal, so it wins the route
            # label over support or inconclusiveness.
            outcome = AnalysisOutcome.ANALYSIS_CONTRADICTED
        elif any(item.status is Verdict.SUPPORTED for item in hypotheses):
            outcome = AnalysisOutcome.ANALYSIS_SUPPORTED
        else:
            outcome = AnalysisOutcome.ANALYSIS_INCONCLUSIVE
        self._last_outcome = outcome
        action = _gated_action(
            outcome, supported_action, evidence, incomplete=any_unresolved
        )
        confidence = (
            Confidence.LOW
            if hypotheses
            and all(item.status is Verdict.SUPPORTED for item in hypotheses)
            else Confidence.INSUFFICIENT
        )
        return RCAOutputModel(
            outcome=outcome,
            analysis_performed=True,
            model_called=True,
            suggested_next_action=action,
            explanation=action_explanation(action),
            confidence=confidence,
            hypotheses=hypotheses,
        )


def create_rca_engine(
    predicate_config: PredicateConfig,
    rules: Mapping[str, ConstraintRule],
    config_path: str | Path = "config/models.yaml",
    environment: Mapping[str, str] | None = None,
    transport: ModelTransport | None = None,
) -> RCAEngine:
    """Load the configured SYNTHESIS route, key, and provider preflight."""
    route = load_model_route(config_path, "SYNTHESIS", environment)
    api_key = load_api_key(route, environment)
    return RCAEngine(route, predicate_config, rules, api_key, transport)
