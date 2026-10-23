from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from src.core.constraints import ConstraintRule
from src.core.sufficiency import PredicateConfig
from src.core.types import SignalSpec, SuggestedAction
from src.schemas.models import RootCauseCategory


@dataclass(frozen=True, slots=True)
class CandidateConfig:
    """The configured conclusion that Python is allowed to assess.

    The claim, class, and root cause are authored in the tool configuration,
    never by the model. The model may add a narrative explanation, but that
    explanation is displayed separately and cannot change this candidate.
    """

    claim: str
    hypothesis_class: str
    cited_signals: tuple[str, ...]
    root_cause: RootCauseCategory = RootCauseCategory.UNKNOWN
    failure_mode: str = "Not specified by the tool configuration."
    mechanism: str = "Not specified by the tool configuration."


@dataclass(frozen=True, slots=True)
class ScenarioConfig:
    signals: tuple[SignalSpec, ...]
    predicate_config: PredicateConfig
    rules: Mapping[str, ConstraintRule]
    candidate: CandidateConfig
    supported_action: SuggestedAction = SuggestedAction.ESCALATE_TO_ENGINEER


@dataclass(frozen=True, slots=True)
class LoadedRelations:
    name: str
    provenance: str
    signals: tuple[SignalSpec, ...]
    groups: Mapping[str, tuple[str, ...]]
    roles: Mapping[str, tuple[str, ...]]
    scenarios: Mapping[str, ScenarioConfig]
