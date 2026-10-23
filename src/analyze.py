from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from src.agents.mapping_request import (
    MappingEngine,
    ValidatedMapping,
    create_mapping_engine,
)
from src.agents.proposal_request import DEFAULT_MAX_TOKENS
from src.agents.rca_engine import create_rca_engine
from src.core.constraints import ConstraintRule
from src.core.sufficiency import PredicateConfig
from src.core.types import AnalysisOutcome, Evidence, SuggestedAction
from src.dossier import (
    DEFAULT_MODELS_CONFIG,
    DEFAULT_SEARCH_DIR,
    DossierResult,
    EngineFactory,
    HypothesisGenerator,
    analyze_dossier,
)
from src.experimental import (
    ExperimentalResult,
    MappingFactory,
    analyze_experimental,
)
from src.schemas.models import RCAOutputModel
from src.triage import ProfileSelection

# The safe path is tried first. Only when it has no matching tool schema does
# the flow fall back to the experimental mapping, so an unknown export
# still gets a bounded, clearly labelled first look instead of a dead end.
FALLBACK_OUTCOME = AnalysisOutcome.NO_MATCHING_TOOL_SCHEMA


def _live_engine_factory(
    predicates: PredicateConfig,
    rules: Mapping[str, ConstraintRule],
) -> HypothesisGenerator:
    return create_rca_engine(predicates, rules, config_path=DEFAULT_MODELS_CONFIG)


def _live_mapping_factory() -> MappingEngine:
    return create_mapping_engine(DEFAULT_MODELS_CONFIG)


@dataclass(frozen=True, slots=True)
class RunResult:
    """Unified result of the safe-then-experimental flow."""

    csv_path: str
    engineer_note: str
    mode: str  # "safe" or "experimental"
    fallback_used: bool
    outcome: AnalysisOutcome
    suggested_next_action: SuggestedAction
    explanation: str
    detail: str | None
    analysis_performed: bool
    model_called: bool
    selection: ProfileSelection | None
    mapping: ValidatedMapping | None
    evidence: tuple[Evidence, ...]
    output: RCAOutputModel
    draft_yaml: str | None = None


def _from_dossier(result: DossierResult) -> RunResult:
    return RunResult(
        csv_path=result.csv_path,
        engineer_note=result.engineer_note,
        mode="safe",
        fallback_used=False,
        outcome=result.outcome,
        suggested_next_action=result.output.suggested_next_action,
        explanation=result.output.explanation,
        detail=result.detail,
        analysis_performed=result.analysis_performed,
        model_called=result.model_called,
        selection=result.selection,
        mapping=None,
        evidence=result.evidence,
        output=result.output,
    )


def _from_experimental(result: ExperimentalResult) -> RunResult:
    return RunResult(
        csv_path=result.csv_path,
        engineer_note=result.engineer_note,
        mode="experimental",
        fallback_used=True,
        outcome=result.outcome,
        suggested_next_action=result.output.suggested_next_action,
        explanation=result.output.explanation,
        detail=result.detail,
        analysis_performed=result.analysis_performed,
        model_called=result.model_called,
        selection=None,
        mapping=result.mapping,
        evidence=result.evidence,
        output=result.output,
        draft_yaml=result.draft_yaml,
    )


def analyze_csv(
    csv_path: str | Path,
    engineer_note: str = "",
    *,
    search_dir: str | Path = DEFAULT_SEARCH_DIR,
    engine_factory: EngineFactory | None = None,
    mapping_factory: MappingFactory | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> RunResult:
    """Run the safe path, then fall back to experimental only when no schema matches.

    The deterministic safe path always runs first. The experimental mapping runs
    only for ``NO_MATCHING_TOOL_SCHEMA``; its output stays unverified and it
    never claims a physical root cause.
    """
    active_engine: EngineFactory = (
        engine_factory if engine_factory is not None else _live_engine_factory
    )
    if mapping_factory is None:
        active_mapping: MappingFactory = _live_mapping_factory
    else:
        active_mapping = mapping_factory
    safe = analyze_dossier(
        csv_path,
        engineer_note,
        search_dir=search_dir,
        engine_factory=active_engine,
        max_tokens=max_tokens,
    )
    if safe.outcome is not FALLBACK_OUTCOME:
        return _from_dossier(safe)
    experimental = analyze_experimental(
        csv_path,
        engineer_note,
        engine_factory=active_engine,
        mapping_factory=active_mapping,
        max_tokens=max_tokens,
    )
    return _from_experimental(experimental)


__all__ = ["RunResult", "analyze_csv"]
