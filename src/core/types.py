from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum


class EvidenceKind(StrEnum):
    SENSOR_ANOMALY = "SENSOR_ANOMALY"
    SENSOR_NOMINAL = "SENSOR_NOMINAL"
    SPATIAL_FEATURE = "SPATIAL_FEATURE"
    MISSING_CHANNEL = "MISSING_CHANNEL"
    MANUAL_EXCERPT = "MANUAL_EXCERPT"
    VERIFIED_CASE = "VERIFIED_CASE"
    EXTERNAL_SOURCE = "EXTERNAL_SOURCE"
    NOT_EVALUATED = "NOT_EVALUATED"


class Predicate(StrEnum):
    HAS_PRIMARY_SIGNAL_ANOMALY = "has_primary_signal_anomaly"
    HAS_ALL_PRIMARY_SIGNALS_ANOMALY = "has_all_primary_signals_anomaly"
    HAS_CORRELATED_ACTUATOR_RESPONSE = "has_correlated_actuator_response"
    HAS_EXPECTED_SPATIAL_SIGNATURE = "has_expected_spatial_signature"
    HAS_MANUAL_OR_PRIOR_CASE_SUPPORT = "has_manual_or_prior_case_support"
    HAS_INSTRUMENTATION_CONTRADICTION = "has_instrumentation_contradiction"
    HAS_MISSING_REQUIRED_EVIDENCE = "has_missing_required_evidence"
    HAS_CROSS_TOOL_TEMPORAL_PRECEDENCE = "has_cross_tool_temporal_precedence"


class Verdict(StrEnum):
    SUPPORTED = "SUPPORTED"
    INSUFFICIENT = "INSUFFICIENT"
    VETOED = "VETOED"


class SuggestedAction(StrEnum):
    """A typed, Python-owned recommendation for the user's next step.

    This enum is the only representation of an action. There is no free-form
    string field an instruction like "increase RF by 5%" could inhabit, so the
    safe default is structural, not a keyword filter. Every value carries a
    plain-language label and a short explanation in ``src/action_guidance.py``.
    """

    # Input / data-quality actions (before any analysis).
    FIX_INPUT_FILE = "FIX_INPUT_FILE"
    FIX_FILE_FORMAT = "FIX_FILE_FORMAT"
    PROVIDE_MORE_DATA = "PROVIDE_MORE_DATA"
    CHECK_COLUMN_FORMAT = "CHECK_COLUMN_FORMAT"
    AUTHOR_TOOL_CONFIG = "AUTHOR_TOOL_CONFIG"
    # Experimental low-integration mapping actions.
    FIX_COLUMNS_AND_RETRY = "FIX_COLUMNS_AND_RETRY"
    REVIEW_DRAFT_MAPPING = "REVIEW_DRAFT_MAPPING"
    # Evidence-budget and model-call actions.
    REDUCE_CHANNELS = "REDUCE_CHANNELS"
    RETRY_ANALYSIS = "RETRY_ANALYSIS"
    REVIEW_CHANNEL_FINDINGS = "REVIEW_CHANNEL_FINDINGS"
    # Analysis actions (a deterministic verdict was reached).
    COLLECT_MORE_DATA = "COLLECT_MORE_DATA"
    REVIEW_CONTRADICTION = "REVIEW_CONTRADICTION"
    INSPECT_COMPONENT = "INSPECT_COMPONENT"
    CONTINUE_MONITORING = "CONTINUE_MONITORING"
    ESCALATE_TO_ENGINEER = "ESCALATE_TO_ENGINEER"


class Confidence(StrEnum):
    INSUFFICIENT = "INSUFFICIENT"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AnalysisOutcome(StrEnum):
    """What route a run took, kept separate from the suggested next action.

    A single ``SuggestedAction.ESCALATE_TO_ENGINEER`` covers two very different
    realities: a completed analysis that supported or abstained, and a run that
    never reached the model. This enum names the route so the UI never has to
    infer it from a free-form string. It carries no benchmark identifiers and no
    action.
    """

    # Pre-model routes (nothing was analyzed).
    INPUT_UNREADABLE = "INPUT_UNREADABLE"
    INPUT_MALFORMED = "INPUT_MALFORMED"
    NO_DATA_ROWS = "NO_DATA_ROWS"
    NO_MATCHING_TOOL_SCHEMA = "NO_MATCHING_TOOL_SCHEMA"
    NO_USABLE_NUMERIC_COLUMNS = "NO_USABLE_NUMERIC_COLUMNS"
    EVIDENCE_TOO_LARGE = "EVIDENCE_TOO_LARGE"
    # The model ran but its output could not be used.
    MODEL_REJECTED = "MODEL_REJECTED"
    NO_PROPOSALS = "NO_PROPOSALS"
    # The model ran and Python assessed at least one hypothesis.
    ANALYSIS_CONTRADICTED = "ANALYSIS_CONTRADICTED"
    ANALYSIS_SUPPORTED = "ANALYSIS_SUPPORTED"
    ANALYSIS_INCONCLUSIVE = "ANALYSIS_INCONCLUSIVE"
    # Experimental, unverified mapping (never a root-cause claim).
    EXPERIMENTAL_MAPPING_REJECTED = "EXPERIMENTAL_MAPPING_REJECTED"
    EXPERIMENTAL_UNVERIFIED_MAPPING = "EXPERIMENTAL_UNVERIFIED_MAPPING"


@dataclass(frozen=True, slots=True)
class BaselineSpec:
    """Where the normal reference comes from.

    ``lead_in`` uses the first rows of the upload. ``nominal_file`` uses a
    separate, curated export. ``recipe_step`` is accepted by the schema but is
    deliberately not scored yet; callers must fail closed rather than silently
    falling back to the whole upload. A file path is resolved by the loader,
    never by ``src/core``.
    """

    mode: str
    rows: int | None = None
    file: str | None = None
    step_column: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"lead_in", "nominal_file", "recipe_step"}:
            raise ValueError(f"unsupported baseline mode: {self.mode}")
        if self.mode == "lead_in":
            if self.rows is None or self.rows < 1:
                raise ValueError("lead_in baseline requires at least one row")
            if self.file is not None or self.step_column is not None:
                raise ValueError("lead_in baseline cannot set file or step_column")
        elif self.mode == "nominal_file":
            if not self.file:
                raise ValueError("nominal_file baseline requires a file")
            if self.rows is not None or self.step_column is not None:
                raise ValueError("nominal_file baseline cannot set rows or step_column")
        else:
            if not self.step_column:
                raise ValueError("recipe_step baseline requires a step_column")
            if self.rows is not None or self.file is not None:
                raise ValueError("recipe_step baseline cannot set rows or file")


@dataclass(frozen=True, slots=True)
class Coverage:
    """Which declared channels the configured check accounts for.

    ``unexplained`` lists channels with an anomaly outside the check.
    ``unexplained_large`` is the subset at or above the product policy limit;
    it is the subset that can demote a confirmation. The limit itself lives
    outside this generic module.
    """

    explained: tuple[str, ...] = ()
    unexplained: tuple[str, ...] = ()
    unexplained_large: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Evidence:
    evidence_id: str
    kind: EvidenceKind
    signal: str | None
    statistic: str | None
    value: float | None
    unit: str | None
    window: tuple[int, int] | None
    provenance: str
    computed_by: str
    summary: str
    window_basis: str | None = None
    # The calibrated alert threshold this record was judged against, if the
    # configuration declared one. ``None`` means "not configured"; the UI must
    # not substitute a default.
    threshold: float | None = None

    def __post_init__(self) -> None:
        if not self.evidence_id:
            raise ValueError("evidence_id must not be empty")
        if self.value is not None and not math.isfinite(self.value):
            raise ValueError("evidence value must be finite or None")
        if self.window is not None and self.window[0] > self.window[1]:
            raise ValueError("evidence window start must not exceed its end")
        if self.threshold is not None:
            if not math.isfinite(self.threshold):
                raise ValueError("evidence threshold must be finite or None")
            if self.threshold < 0:
                raise ValueError("evidence threshold must be non-negative")


@dataclass(frozen=True, slots=True)
class PredicateSet:
    has_primary_signal_anomaly: bool = False
    has_all_primary_signals_anomaly: bool = False
    has_correlated_actuator_response: bool = False
    has_expected_spatial_signature: bool = False
    has_manual_or_prior_case_support: bool = False
    has_instrumentation_contradiction: bool = False
    has_missing_required_evidence: bool = False
    has_cross_tool_temporal_precedence: bool = False

    def enabled(self, predicate: Predicate) -> bool:
        if predicate is Predicate.HAS_PRIMARY_SIGNAL_ANOMALY:
            return self.has_primary_signal_anomaly
        if predicate is Predicate.HAS_ALL_PRIMARY_SIGNALS_ANOMALY:
            return self.has_all_primary_signals_anomaly
        if predicate is Predicate.HAS_CORRELATED_ACTUATOR_RESPONSE:
            return self.has_correlated_actuator_response
        if predicate is Predicate.HAS_EXPECTED_SPATIAL_SIGNATURE:
            return self.has_expected_spatial_signature
        if predicate is Predicate.HAS_MANUAL_OR_PRIOR_CASE_SUPPORT:
            return self.has_manual_or_prior_case_support
        if predicate is Predicate.HAS_INSTRUMENTATION_CONTRADICTION:
            return self.has_instrumentation_contradiction
        if predicate is Predicate.HAS_MISSING_REQUIRED_EVIDENCE:
            return self.has_missing_required_evidence
        if predicate is Predicate.HAS_CROSS_TOOL_TEMPORAL_PRECEDENCE:
            return self.has_cross_tool_temporal_precedence
        raise ValueError(f"unsupported predicate: {predicate}")


@dataclass(frozen=True, slots=True)
class SignalSpec:
    name: str
    unit: str | None = None
    robust_z_threshold: float | None = None
    threshold_source: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("signal name must not be empty")
        if self.robust_z_threshold is not None:
            if not math.isfinite(self.robust_z_threshold):
                raise ValueError("threshold must be finite or None")
            if self.robust_z_threshold < 0:
                raise ValueError("robust z threshold must be non-negative")
            if not self.threshold_source:
                raise ValueError("a calibrated threshold requires its source")
