from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from src.core.types import (
    AnalysisOutcome,
    Confidence,
    EvidenceKind,
    SuggestedAction,
    Verdict,
)


class RootCauseCategory(StrEnum):
    EQUIPMENT_FAULT = "equipment_fault"
    PROCESS_DRIFT = "process_drift"
    UPSTREAM_PROCESS = "upstream_process"
    MATERIAL_ISSUE = "material_issue"
    INSTRUMENTATION_FAULT = "instrumentation_fault"
    UNKNOWN = "unknown"


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    evidence_id: str
    kind: EvidenceKind
    signal: str | None
    statistic: str | None
    value: float | None
    unit: str | None
    window: tuple[int, int] | None
    window_basis: str | None
    provenance: str
    computed_by: str
    summary: str


class ModelNarrative(BaseModel):
    """The model's explanation, shown separately and never used as the gate.

    ``unresolved_citations`` are evidence IDs the model cited that Python could
    not resolve. They are kept for transparency and are not part of the gated
    conclusion.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    claim: str
    root_cause: RootCauseCategory
    failure_mode: str
    mechanism: str
    hypothesis_class: str
    cited_evidence: list[str] = Field(default_factory=list)
    unresolved_citations: list[str] = Field(default_factory=list)


class HypothesisModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    claim: str
    root_cause: RootCauseCategory
    failure_mode: str
    mechanism: str
    hypothesis_class: str
    cited_evidence: list[str] = Field(default_factory=list)
    status: Verdict
    veto_reason: str | None = None
    # Present when the model returned a usable proposal. The narrative is
    # explanatory only; ``claim``/``status`` above come from the configuration
    # and the Python gate.
    model_narrative: ModelNarrative | None = None


class ExternalSourceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    url: str
    why_consulted: str


class RCAOutputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    # The outcome names the route (Python-owned); the suggested action is the
    # typed, fail-closed recommendation. ``analysis_performed`` and
    # ``model_called`` are explicit so a UI never has to infer the route.
    outcome: AnalysisOutcome = AnalysisOutcome.NO_PROPOSALS
    analysis_performed: bool = False
    model_called: bool = False
    suggested_next_action: SuggestedAction = SuggestedAction.ESCALATE_TO_ENGINEER
    explanation: str = ""
    confidence: Confidence
    hypotheses: list[HypothesisModel] = Field(default_factory=list)
    required_next_checks: list[str] = Field(default_factory=list)
    prohibited_actions_detected: list[str] = Field(default_factory=list)
    external_sources: list[ExternalSourceModel] = Field(default_factory=list)
