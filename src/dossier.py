from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from src.action_guidance import action_explanation, default_action_for
from src.agents.proposal_request import DEFAULT_MAX_TOKENS
from src.agents.rca_engine import create_rca_engine
from src.config_loader import load_relations
from src.config_types import CandidateConfig
from src.core.column_profile import MalformedCsvError
from src.core.constraints import ConstraintRule
from src.core.duckdb_exec import extract_evidence
from src.core.evidence import PayloadTooLarge
from src.core.sufficiency import PredicateConfig
from src.core.types import (
    AnalysisOutcome,
    Confidence,
    Evidence,
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


def analyze_dossier(
    csv_path: str | Path,
    engineer_note: str,
    *,
    search_dir: str | Path = DEFAULT_SEARCH_DIR,
    engine_factory: EngineFactory = _live_engine_factory,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> DossierResult:
    """Run the engineer-style flow: header triage, DuckDB evidence, gated model.

    The engineer note is bounded context only. Python still resolves every
    citation and owns the suggested action, so the note cannot change a verdict.
    Unreadable, malformed, empty, unmatched, and oversized inputs all fail
    closed rather than raising into the caller.
    """
    path = Path(csv_path)
    bounded_note = engineer_note[:MAX_ENGINEER_NOTE_CHARS]
    if not path.is_file():
        detail = "Input CSV is not readable; review the export path."
        return _fail_result(
            path, bounded_note, AnalysisOutcome.INPUT_UNREADABLE, detail
        )
    if path.stat().st_size == 0:
        detail = "The file has no header or readings; provide a non-empty export."
        return _fail_result(path, bounded_note, AnalysisOutcome.NO_DATA_ROWS, detail)
    try:
        inspection = inspect_csv(path)
    except MalformedCsvError:
        detail = (
            "The file is not readable as a CSV (encoding or delimiter problem); "
            "re-export it as a UTF-8 CSV."
        )
        return _fail_result(
            path, bounded_note, AnalysisOutcome.INPUT_MALFORMED, detail
        )
    if inspection.row_count == 0:
        detail = "The file has a header but no readings; nothing to check."
        return _fail_result(path, bounded_note, AnalysisOutcome.NO_DATA_ROWS, detail)
    try:
        selection = select_profile(inspection.headers, engineer_note, search_dir)
    except NoMatchingProfile:
        detail = (
            "No configured tool profile matches the uploaded columns; "
            "review the export schema."
        )
        return _fail_result(
            path, bounded_note, AnalysisOutcome.NO_MATCHING_TOOL_SCHEMA, detail
        )
    relations = load_relations(selection.config_path)
    scenario = relations.scenarios[selection.scenario_name]
    evidence = extract_evidence(path, scenario.signals)
    engine = engine_factory(scenario.predicate_config, scenario.rules)
    try:
        output = engine.generate_hypotheses(
            evidence,
            context=bounded_note,
            max_tokens=max_tokens,
            supported_action=scenario.supported_action,
            candidate=scenario.candidate,
        )
    except PayloadTooLarge:
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
        )
    return DossierResult(
        str(path),
        bounded_note,
        selection,
        evidence,
        output,
        output.outcome,
        None,
    )
