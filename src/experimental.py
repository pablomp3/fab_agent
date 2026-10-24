from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from src.action_guidance import action_explanation, default_action_for
from src.agents.mapping_request import (
    DEFAULT_MAPPING_MAX_TOKENS,
    MappingEngine,
    MappingEnvelope,
    MappingValidationError,
    ValidatedMapping,
    create_mapping_engine,
    validate_mapping,
)
from src.agents.model_transport import ModelIntegrationError
from src.agents.rca_engine import create_rca_engine
from src.config_types import CandidateConfig
from src.config_writer import (
    DEFAULT_EXPERIMENTAL_THRESHOLD,
    EXPERIMENTAL_HYPOTHESIS_CLASS,
    EXPERIMENTAL_THRESHOLD_SOURCE,
    draft_relations_yaml,
)
from src.core.column_profile import (
    ColumnProfile,
    MalformedCsvError,
    profile_columns,
    usable_candidates,
)
from src.core.constraints import ConstraintRule
from src.core.duckdb_exec import extract_evidence
from src.core.evidence import PayloadTooLarge
from src.core.progress import (
    STAGE_DUCKDB,
    STAGE_GATE,
    STAGE_MAPPING,
    STAGE_MODEL,
    STAGE_PYTHON,
    STAGE_READ,
    STAGE_TRIAGE,
    ProgressCallback,
    report,
)
from src.core.sufficiency import PredicateConfig
from src.core.types import (
    AnalysisOutcome,
    Confidence,
    Evidence,
    Predicate,
    SignalSpec,
    SuggestedAction,
)
from src.dossier import (
    DEFAULT_MODELS_CONFIG,
    MAX_ENGINEER_NOTE_CHARS,
    EngineFactory,
    HypothesisGenerator,
)
from src.schemas.models import RCAOutputModel, RootCauseCategory

EXPERIMENTAL_COMPUTED_BY = "experimental_mapping@v1"
EXPERIMENTAL_PROVENANCE_TAG = "unverified_mapping"


class MappingProposer(Protocol):
    def propose_mapping(
        self,
        candidates: tuple[ColumnProfile, ...],
        *,
        max_tokens: int = DEFAULT_MAPPING_MAX_TOKENS,
    ) -> MappingEnvelope: ...


MappingFactory = Callable[[], MappingProposer]


@dataclass(frozen=True, slots=True)
class ExperimentalResult:
    csv_path: str
    engineer_note: str
    outcome: AnalysisOutcome
    detail: str | None
    candidates: tuple[ColumnProfile, ...]
    mapping: ValidatedMapping | None
    evidence: tuple[Evidence, ...]
    output: RCAOutputModel
    draft_yaml: str | None = None

    @property
    def analysis_performed(self) -> bool:
        return self.output.analysis_performed

    @property
    def model_called(self) -> bool:
        return self.output.model_called


def _fail_output(
    outcome: AnalysisOutcome,
    detail: str,
    *,
    analysis_performed: bool,
    model_called: bool,
) -> RCAOutputModel:
    action = default_action_for(outcome)
    return RCAOutputModel(
        outcome=outcome,
        analysis_performed=analysis_performed,
        model_called=model_called,
        suggested_next_action=action,
        explanation=action_explanation(action),
        confidence=Confidence.INSUFFICIENT,
        required_next_checks=[detail],
    )


def _live_mapping_factory() -> MappingEngine:
    return create_mapping_engine(DEFAULT_MODELS_CONFIG)


def _live_engine_factory(
    predicates: PredicateConfig,
    rules: Mapping[str, ConstraintRule],
) -> HypothesisGenerator:
    return create_rca_engine(predicates, rules, config_path=DEFAULT_MODELS_CONFIG)


def _result(
    path: Path,
    note: str,
    outcome: AnalysisOutcome,
    detail: str | None,
    *,
    candidates: tuple[ColumnProfile, ...] = (),
    mapping: ValidatedMapping | None = None,
    evidence: tuple[Evidence, ...] = (),
    output: RCAOutputModel | None = None,
    draft_yaml: str | None = None,
    analysis_performed: bool = False,
    model_called: bool = False,
) -> ExperimentalResult:
    resolved_output = (
        output
        if output is not None
        else _fail_output(
            outcome,
            detail or "Experimental run stopped before a result.",
            analysis_performed=analysis_performed,
            model_called=model_called,
        )
    )
    return ExperimentalResult(
        str(path),
        note,
        outcome,
        detail,
        candidates,
        mapping,
        evidence,
        resolved_output,
        draft_yaml,
    )


def analyze_experimental(
    csv_path: str | Path,
    note: str | None = None,
    *,
    engine_factory: EngineFactory = _live_engine_factory,
    mapping_factory: MappingFactory = _live_mapping_factory,
    max_tokens: int = DEFAULT_MAPPING_MAX_TOKENS,
    progress: ProgressCallback | None = None,
) -> ExperimentalResult:
    """Low-integration experimental triage: propose an unverified mapping, then scan.

    This runs automatically as the fallback when no configured schema matches
    (via ``analyze_csv``) and can also be called directly. It sends only column
    names, inferred types, and bounded summary statistics, validates every
    proposed column in Python, marks all evidence ``unverified_mapping``, and
    emits no physical root-cause claim. The safe ``analyze_dossier`` path is
    unchanged.
    """
    path = Path(csv_path)
    bounded_note = (note or "")[:MAX_ENGINEER_NOTE_CHARS]
    report(progress, STAGE_READ, "running")
    if not path.is_file():
        report(progress, STAGE_READ, "failed")
        detail = "Input CSV is not readable; review the export path."
        return _result(
            path,
            bounded_note,
            AnalysisOutcome.INPUT_UNREADABLE,
            detail,
            analysis_performed=False,
            model_called=False,
        )
    if path.stat().st_size == 0:
        report(progress, STAGE_READ, "failed")
        detail = "The file has no header or readings; provide a non-empty export."
        return _result(
            path,
            bounded_note,
            AnalysisOutcome.NO_DATA_ROWS,
            detail,
            analysis_performed=False,
            model_called=False,
        )
    try:
        profiles = profile_columns(path)
    except MalformedCsvError:
        report(progress, STAGE_READ, "failed")
        detail = (
            "The file is not readable as a CSV (encoding or delimiter problem); "
            "re-export it as a UTF-8 CSV."
        )
        return _result(
            path,
            bounded_note,
            AnalysisOutcome.INPUT_MALFORMED,
            detail,
            analysis_performed=False,
            model_called=False,
        )
    if not profiles or profiles[0].row_count == 0:
        report(progress, STAGE_READ, "failed")
        detail = "The file has a header but no readings; nothing to triage."
        return _result(
            path,
            bounded_note,
            AnalysisOutcome.NO_DATA_ROWS,
            detail,
            candidates=profiles,
            analysis_performed=False,
            model_called=False,
        )
    report(progress, STAGE_READ, "done")
    report(progress, STAGE_TRIAGE, "running")
    candidates = usable_candidates(profiles)
    if not candidates:
        report(progress, STAGE_TRIAGE, "failed")
        detail = (
            "No usable numeric, non-constant columns were found; "
            "nothing to triage in experimental mode."
        )
        return _result(
            path,
            bounded_note,
            AnalysisOutcome.NO_USABLE_NUMERIC_COLUMNS,
            detail,
            candidates=candidates,
        )
    report(progress, STAGE_TRIAGE, "done")
    report(progress, STAGE_MAPPING, "running")
    try:
        proposer = mapping_factory()
        envelope = proposer.propose_mapping(candidates, max_tokens=max_tokens)
    except PayloadTooLarge:
        report(progress, STAGE_MAPPING, "failed")
        detail = (
            "Candidate summary exceeded the mapping request budget; "
            "reduce the column count."
        )
        return _result(
            path,
            bounded_note,
            AnalysisOutcome.EVIDENCE_TOO_LARGE,
            detail,
            candidates=candidates,
        )
    except ModelIntegrationError as exc:
        report(progress, STAGE_MAPPING, "failed")
        detail = f"Mapping model call failed ({exc.category.value})."
        return _result(
            path,
            bounded_note,
            AnalysisOutcome.MODEL_REJECTED,
            detail,
            candidates=candidates,
            analysis_performed=True,
            model_called=True,
        )
    try:
        mapping = validate_mapping(envelope, candidates)
    except MappingValidationError as exc:
        report(progress, STAGE_MAPPING, "failed")
        detail = f"mapping_rejected: {exc}"
        return _result(
            path,
            bounded_note,
            AnalysisOutcome.EXPERIMENTAL_MAPPING_REJECTED,
            detail,
            candidates=candidates,
            analysis_performed=True,
            model_called=True,
        )
    report(progress, STAGE_MAPPING, "done")
    signals = tuple(
        SignalSpec(
            name=item.column,
            unit=None,
            robust_z_threshold=DEFAULT_EXPERIMENTAL_THRESHOLD,
            threshold_source=EXPERIMENTAL_THRESHOLD_SOURCE,
        )
        for item in mapping.signals
    )
    report(progress, STAGE_DUCKDB, "running")
    evidence = extract_evidence(
        path,
        signals,
        computed_by=EXPERIMENTAL_COMPUTED_BY,
        provenance_tag=EXPERIMENTAL_PROVENANCE_TAG,
    )
    report(progress, STAGE_DUCKDB, "done")
    report(progress, STAGE_PYTHON, "running")
    report(progress, STAGE_PYTHON, "done")
    primaries = frozenset(item.primary for item in mapping.relationships) or frozenset(
        item.column for item in mapping.signals
    )
    corroboration = (
        frozenset(
            column for item in mapping.relationships for column in item.corroborating
        )
        - primaries
    )
    engine = engine_factory(
        PredicateConfig(
            primary_signals=primaries,
            corroboration_signals=corroboration,
        ),
        {
            EXPERIMENTAL_HYPOTHESIS_CLASS: ConstraintRule(
                require_all=frozenset({Predicate.HAS_PRIMARY_SIGNAL_ANOMALY})
            )
        },
    )
    candidate = CandidateConfig(
        claim="Experimental unverified mapping draft",
        hypothesis_class=EXPERIMENTAL_HYPOTHESIS_CLASS,
        cited_signals=tuple(item.column for item in mapping.signals),
        root_cause=RootCauseCategory.UNKNOWN,
        failure_mode="Not claimed; the mapping is unverified.",
        mechanism="Not claimed; the mapping is unverified.",
    )
    report(progress, STAGE_MODEL, "running")
    try:
        output = engine.generate_hypotheses(
            evidence,
            context=bounded_note,
            max_tokens=max_tokens,
            candidate=candidate,
        )
    except PayloadTooLarge:
        report(progress, STAGE_MODEL, "failed")
        report(progress, STAGE_GATE, "failed")
        detail = (
            "Scoped evidence exceeded the model request budget; "
            "narrow the experimental mapping."
        )
        return _result(
            path,
            bounded_note,
            AnalysisOutcome.EVIDENCE_TOO_LARGE,
            detail,
            candidates=candidates,
            mapping=mapping,
            evidence=evidence,
            analysis_performed=True,
            model_called=True,
        )
    report(
        progress,
        STAGE_MODEL,
        "done" if output.model_called else "skipped",
    )
    report(progress, STAGE_GATE, "done")
    output = output.model_copy(
        update={
            "outcome": AnalysisOutcome.EXPERIMENTAL_UNVERIFIED_MAPPING,
            "suggested_next_action": SuggestedAction.REVIEW_DRAFT_MAPPING,
            "explanation": action_explanation(
                SuggestedAction.REVIEW_DRAFT_MAPPING
            ),
        }
    )
    return _result(
        path,
        bounded_note,
        AnalysisOutcome.EXPERIMENTAL_UNVERIFIED_MAPPING,
        None,
        candidates=candidates,
        mapping=mapping,
        evidence=evidence,
        output=output,
        draft_yaml=draft_relations_yaml(mapping),
    )
