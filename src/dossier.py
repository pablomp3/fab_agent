from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from src.action_guidance import action_explanation, default_action_for
from src.agents.differential_request import DEFAULT_CAUSE_MAX_TOKENS
from src.agents.proposal_request import DEFAULT_MAX_TOKENS
from src.agents.rca_engine import create_rca_engine
from src.config_loader import load_relations
from src.config_types import CandidateConfig, ScenarioConfig
from src.core.column_profile import MalformedCsvError
from src.core.constraints import ConstraintRule
from src.core.duckdb_exec import extract_evidence
from src.core.evidence import PayloadTooLarge
from src.core.progress import (
    STAGE_DUCKDB,
    STAGE_GATE,
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
    SignalSpec,
    SuggestedAction,
)
from src.schemas.models import RCAOutputModel
from src.triage import (
    DEFAULT_SEARCH_DIR,
    NoMatchingProfile,
    ProfileSelection,
    inspect_csv,
    select_profile,
)

MAX_ENGINEER_NOTE_CHARS = 1000
DEFAULT_MODELS_CONFIG = Path(__file__).resolve().parents[1] / "config" / "models.yaml"


class HypothesisGenerator(Protocol):
    def generate_hypotheses(
        self,
        evidence: tuple[Evidence, ...],
        *,
        context: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        supported_action: SuggestedAction = SuggestedAction.ESCALATE_TO_ENGINEER,
        candidate: CandidateConfig | None = None,
    ) -> RCAOutputModel: ...


@runtime_checkable
class DifferentialGenerator(Protocol):
    def assess_checks(
        self,
        evidence: tuple[Evidence, ...],
        scenarios: Mapping[str, ScenarioConfig],
        *,
        context: str | None = None,
        max_tokens: int = DEFAULT_CAUSE_MAX_TOKENS,
        preferred_check: str | None = None,
    ) -> RCAOutputModel: ...


EngineFactory = Callable[
    [PredicateConfig, Mapping[str, ConstraintRule]], HypothesisGenerator
]


@dataclass(frozen=True, slots=True)
class DossierResult:
    csv_path: str
    engineer_note: str
    selection: ProfileSelection | None
    evidence: tuple[Evidence, ...]
    output: RCAOutputModel
    outcome: AnalysisOutcome
    detail: str | None = None
    # Human labels authored in the tool model. The UI uses them instead of raw
    # CSV column names; the evidence and gate still use the column names.
    signal_labels: tuple[tuple[str, str], ...] = ()

    @property
    def analysis_performed(self) -> bool:
        return self.output.analysis_performed

    @property
    def model_called(self) -> bool:
        return self.output.model_called


def _fail_closed(
    outcome: AnalysisOutcome,
    detail: str,
    *,
    analysis_performed: bool = False,
    model_called: bool = False,
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


def _fail_result(
    path: Path,
    note: str,
    outcome: AnalysisOutcome,
    detail: str,
) -> DossierResult:
    return DossierResult(
        str(path),
        note,
        None,
        (),
        _fail_closed(outcome, detail),
        outcome,
        detail,
    )


def _live_engine_factory(
    predicates: PredicateConfig,
    rules: Mapping[str, ConstraintRule],
) -> HypothesisGenerator:
    return create_rca_engine(predicates, rules, config_path=DEFAULT_MODELS_CONFIG)


def _scoped_signals(
    scenarios: Mapping[str, ScenarioConfig],
) -> tuple[SignalSpec, ...]:
    """Union every check's scope so all differential rows share one evidence set."""
    signals: list[SignalSpec] = []
    seen: set[str] = set()
    for scenario in scenarios.values():
        for spec in scenario.declared_signals or scenario.signals:
            if spec.name in seen:
                continue
            seen.add(spec.name)
            signals.append(spec)
    return tuple(signals)


def analyze_dossier(
    csv_path: str | Path,
    engineer_note: str,
    *,
    search_dir: str | Path = DEFAULT_SEARCH_DIR,
    engine_factory: EngineFactory = _live_engine_factory,
    max_tokens: int = DEFAULT_CAUSE_MAX_TOKENS,
    progress: ProgressCallback | None = None,
) -> DossierResult:
    """Run the engineer-style flow: header triage, DuckDB evidence, gated model.

    The engineer note is bounded context only. Python still resolves every
    citation and owns the suggested action, so the note cannot change a verdict.
    Unreadable, malformed, empty, unmatched, and oversized inputs all fail
    closed rather than raising into the caller.
    """
    path = Path(csv_path)
    bounded_note = engineer_note[:MAX_ENGINEER_NOTE_CHARS]
    report(progress, STAGE_READ, "running")
    if not path.is_file():
        report(progress, STAGE_READ, "failed")
        detail = "Input CSV is not readable; review the export path."
        return _fail_result(
            path, bounded_note, AnalysisOutcome.INPUT_UNREADABLE, detail
        )
    if path.stat().st_size == 0:
        report(progress, STAGE_READ, "failed")
        detail = "The file has no header or readings; provide a non-empty export."
        return _fail_result(path, bounded_note, AnalysisOutcome.NO_DATA_ROWS, detail)
    try:
        inspection = inspect_csv(path)
    except MalformedCsvError:
        report(progress, STAGE_READ, "failed")
        detail = (
            "The file is not readable as a CSV (encoding or delimiter problem); "
            "re-export it as a UTF-8 CSV."
        )
        return _fail_result(path, bounded_note, AnalysisOutcome.INPUT_MALFORMED, detail)
    if inspection.row_count == 0:
        report(progress, STAGE_READ, "failed")
        detail = "The file has a header but no readings; nothing to check."
        return _fail_result(path, bounded_note, AnalysisOutcome.NO_DATA_ROWS, detail)
    report(progress, STAGE_READ, "done")
    report(progress, STAGE_TRIAGE, "running")
    try:
        selection = select_profile(inspection.headers, engineer_note, search_dir)
    except NoMatchingProfile:
        report(progress, STAGE_TRIAGE, "failed")
        detail = (
            "No configured tool profile matches the uploaded columns; "
            "review the export schema."
        )
        return _fail_result(
            path, bounded_note, AnalysisOutcome.NO_MATCHING_TOOL_SCHEMA, detail
        )
    report(progress, STAGE_TRIAGE, "done")
    relations = load_relations(selection.config_path)
    scenario = relations.scenarios[selection.scenario_name]
    report(progress, STAGE_DUCKDB, "running")
    evidence = extract_evidence(
        path,
        _scoped_signals(relations.scenarios),
        baseline=scenario.baseline,
    )
    report(progress, STAGE_DUCKDB, "done")
    report(progress, STAGE_PYTHON, "running")
    report(progress, STAGE_PYTHON, "done")
    report(progress, STAGE_MODEL, "running")
    engine = engine_factory(scenario.predicate_config, scenario.rules)
    try:
        if isinstance(engine, DifferentialGenerator):
            output = engine.assess_checks(
                evidence,
                relations.scenarios,
                context=bounded_note,
                max_tokens=max_tokens,
                preferred_check=selection.scenario_name,
            )
        else:
            output = engine.generate_hypotheses(
                evidence,
                context=bounded_note,
                max_tokens=max_tokens,
                supported_action=scenario.supported_action,
                candidate=scenario.candidate,
            )
    except PayloadTooLarge:
        report(progress, STAGE_MODEL, "failed")
        report(progress, STAGE_GATE, "failed")
        detail = (
            "Evidence summary exceeded the model request budget; "
            "narrow the channel scope."
        )
        return DossierResult(
            str(path),
            bounded_note,
            selection,
            evidence,
            _fail_closed(AnalysisOutcome.EVIDENCE_TOO_LARGE, detail),
            AnalysisOutcome.EVIDENCE_TOO_LARGE,
            detail,
            signal_labels=tuple(sorted(relations.signal_labels.items())),
        )
    report(
        progress,
        STAGE_MODEL,
        "done" if output.model_called else "skipped",
    )
    report(progress, STAGE_GATE, "done")
    return DossierResult(
        str(path),
        bounded_note,
        selection,
        evidence,
        output,
        output.outcome,
        None,
        signal_labels=tuple(sorted(relations.signal_labels.items())),
    )
