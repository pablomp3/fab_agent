from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path

from pydantic import ValidationError

from src.action_guidance import action_explanation, default_action_for
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
from src.config_types import CandidateConfig
from src.core.constraints import ConstraintRule
from src.core.evidence import EvidenceStore, PayloadTooLarge
from src.core.pipeline import Candidate, CandidateAssessment, assess_candidate
from src.core.sufficiency import PredicateConfig
from src.core.types import (
    AnalysisOutcome,
    Confidence,
    Evidence,
    SuggestedAction,
    Verdict,
)
from src.model_config import ModelRoute, load_api_key, load_model_route
from src.schemas.models import (
    HypothesisModel,
    ModelNarrative,
    RCAOutputModel,
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
        checks.append(
            "The configured candidate did not meet every required predicate; "
            "collect or verify the missing channels."
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
        )
        status = assessment.constraints.verdict
        if missing_signals and status is not Verdict.VETOED:
            # A configured channel with no evidence means the candidate is not
            # fully assessed, even if the remaining citations look sufficient.
            status = Verdict.INSUFFICIENT
        if status is Verdict.VETOED:
            outcome = AnalysisOutcome.ANALYSIS_CONTRADICTED
        elif status is Verdict.SUPPORTED:
            outcome = AnalysisOutcome.ANALYSIS_SUPPORTED
        else:
            outcome = AnalysisOutcome.ANALYSIS_INCONCLUSIVE
        action = (
            supported_action
            if outcome is AnalysisOutcome.ANALYSIS_SUPPORTED
            else default_action_for(outcome)
        )
        hypothesis = HypothesisModel(
            claim=candidate.claim,
            root_cause=candidate.root_cause,
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
        self._last_failure_category = None
        self._last_finish_reason = None
        self._last_validation_details = None
        self._last_outcome = None
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
            _LOGGER.warning(
                "Model request rejected; category=%s", FailureCategory.SIZE
            )
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
            narrative = _select_model_narrative(
                proposals.hypotheses, candidate, store
            )
            return self._gate_candidate(
                evidence,
                candidate,
                supported_action,
                narrative=narrative,
            )

        hypotheses: list[HypothesisModel] = []
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
            )
            hypotheses.append(
                HypothesisModel(
                    claim=proposal.claim,
                    root_cause=proposal.root_cause,
                    failure_mode=proposal.failure_mode,
                    mechanism=proposal.mechanism,
                    hypothesis_class=proposal.hypothesis_class,
                    cited_evidence=proposal.cited_evidence,
                    status=assessment.constraints.verdict,
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
        action = (
            supported_action
            if outcome is AnalysisOutcome.ANALYSIS_SUPPORTED
            else default_action_for(outcome)
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
