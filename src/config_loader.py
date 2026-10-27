from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import cast

import yaml

from src.config_types import CandidateConfig, LoadedRelations, ScenarioConfig
from src.core.constraints import ConstraintRule
from src.core.sufficiency import PredicateConfig, SpatialExpectation
from src.core.types import Predicate, SignalSpec, SuggestedAction
from src.schemas.models import RootCauseCategory

_SUPPORTED_ACTION_CHOICES = frozenset(
    {
        SuggestedAction.INSPECT_COMPONENT,
        SuggestedAction.CONTINUE_MONITORING,
        SuggestedAction.ESCALATE_TO_ENGINEER,
    }
)


def _supported_action(value: object, where: str) -> SuggestedAction:
    if value is None:
        return SuggestedAction.ESCALATE_TO_ENGINEER
    text = _text(value, where)
    try:
        action = SuggestedAction(text)
    except ValueError as exc:
        raise ValueError(f"{where} is not a valid action") from exc
    if action not in _SUPPORTED_ACTION_CHOICES:
        raise ValueError(f"{where} is not a supported action for a scenario")
    return action


def _mapping(value: object, where: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be a string-keyed mapping")
    raw = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in raw):
        raise ValueError(f"{where} must be a string-keyed mapping")
    return cast(Mapping[str, object], value)


def _keys(value: Mapping[str, object], allowed: set[str], where: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"{where} has unknown keys: {', '.join(sorted(unknown))}")


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{where} must be a non-empty string")
    return value


def _number(value: object, where: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{where} must be a number or null")
    return float(value)


def _strings(value: object, where: str) -> tuple[str, ...]:
    return tuple(_text(item, where) for item in _items(value, where))


def _items(value: object, where: str) -> tuple[object, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{where} must be a list")
    return tuple(cast(list[object], value))


# Public aliases for the v2 loader. The implementations stay private here so
# the v1 loader keeps one validation vocabulary.
supported_action = _supported_action
mapping = _mapping
keys = _keys
text = _text
number = _number
strings = _strings
items = _items


def _signal(value: object) -> SignalSpec:
    data = _mapping(value, "signal")
    _keys(data, {"name", "unit", "robust_z_threshold", "threshold_source"}, "signal")
    return SignalSpec(
        name=_text(data.get("name"), "signal.name"),
        unit=None if data.get("unit") is None else _text(data["unit"], "signal.unit"),
        robust_z_threshold=_number(data.get("robust_z_threshold"), "signal.threshold"),
        threshold_source=(
            None
            if data.get("threshold_source") is None
            else _text(data["threshold_source"], "signal.threshold_source")
        ),
    )


def _pairs(value: object, where: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list):
        raise ValueError(f"{where} must be a list of two-item lists")
    pairs: list[tuple[str, str]] = []
    for item in cast(list[object], value):
        if not isinstance(item, list):
            raise ValueError(f"{where} entries must have two strings")
        pair = cast(list[object], item)
        if len(pair) != 2:
            raise ValueError(f"{where} entries must have two strings")
        pairs.append((_text(pair[0], where), _text(pair[1], where)))
    return tuple(pairs)


def _predicates(value: object) -> PredicateConfig:
    data = _mapping(value, "predicates")
    names = {
        "primary_signals",
        "corroboration_signals",
        "actuator_pairs",
        "required_evidence_ids",
        "temporal_precedence_pairs",
        "expected_spatial_features",
    }
    _keys(data, names, "predicates")
    spatial: list[SpatialExpectation] = []
    for item in _items(
        data.get("expected_spatial_features", []), "expected_spatial_features"
    ):
        row = _mapping(item, "expected_spatial_features entry")
        _keys(row, {"statistic", "minimum", "maximum", "source"}, "spatial expectation")
        spatial.append(
            SpatialExpectation(
                statistic=_text(row.get("statistic"), "spatial.statistic"),
                minimum=_number(row.get("minimum"), "spatial.minimum"),
                maximum=_number(row.get("maximum"), "spatial.maximum"),
                source=_text(row.get("source"), "spatial.source"),
            )
        )
    return PredicateConfig(
        primary_signals=frozenset(
            _strings(data.get("primary_signals", []), "primary_signals")
        ),
        corroboration_signals=frozenset(
            _strings(data.get("corroboration_signals", []), "corroboration_signals")
        ),
        actuator_pairs=_pairs(data.get("actuator_pairs", []), "actuator_pairs"),
        required_evidence_ids=frozenset(
            _strings(data.get("required_evidence_ids", []), "required_evidence_ids")
        ),
        temporal_precedence_pairs=_pairs(
            data.get("temporal_precedence_pairs", []), "temporal_precedence_pairs"
        ),
        expected_spatial_features=tuple(spatial),
    )


def _rules(value: object) -> Mapping[str, ConstraintRule]:
    data = _mapping(value, "rules")
    parsed: dict[str, ConstraintRule] = {}
    for name, rule_obj in data.items():
        rule = _mapping(rule_obj, f"rules.{name}")
        _keys(rule, {"require_all", "forbid_any", "veto_if_any"}, f"rules.{name}")
        try:
            parsed[name] = ConstraintRule(
                require_all=frozenset(
                    Predicate(item)
                    for item in _strings(rule.get("require_all", []), "require_all")
                ),
                forbid_any=frozenset(
                    Predicate(item)
                    for item in _strings(rule.get("forbid_any", []), "forbid_any")
                ),
                veto_if_any=frozenset(
                    Predicate(item)
                    for item in _strings(rule.get("veto_if_any", []), "veto_if_any")
                ),
            )
        except ValueError as exc:
            raise ValueError(f"rules.{name} contains an unknown predicate") from exc
    return MappingProxyType(parsed)


def _scenario(value: object) -> ScenarioConfig:
    data = _mapping(value, "scenario")
    _keys(
        data,
        {"signals", "predicates", "rules", "candidate", "supported_action"},
        "scenario",
    )
    signals = tuple(
        _signal(item) for item in _items(data.get("signals", []), "signals")
    )
    if not signals or len({item.name for item in signals}) != len(signals):
        raise ValueError("scenario signals must be non-empty and uniquely named")
    candidate_data = _mapping(data.get("candidate"), "candidate")
    _keys(
        candidate_data,
        {
            "claim",
            "hypothesis_class",
            "cited_signals",
            "root_cause",
            "failure_mode",
            "mechanism",
        },
        "candidate",
    )
    root_cause_text = candidate_data.get("root_cause")
    try:
        root_cause = (
            RootCauseCategory.UNKNOWN
            if root_cause_text is None
            else RootCauseCategory(_text(root_cause_text, "candidate.root_cause"))
        )
    except ValueError as exc:
        raise ValueError(
            "candidate.root_cause is not a known root-cause category"
        ) from exc
    candidate = CandidateConfig(
        claim=_text(candidate_data.get("claim"), "candidate.claim"),
        hypothesis_class=_text(
            candidate_data.get("hypothesis_class"), "candidate.hypothesis_class"
        ),
        cited_signals=_strings(
            candidate_data.get("cited_signals"), "candidate.cited_signals"
        ),
        root_cause=root_cause,
        failure_mode=(
            "Not specified by the tool configuration."
            if candidate_data.get("failure_mode") is None
            else _text(candidate_data["failure_mode"], "candidate.failure_mode")
        ),
        mechanism=(
            "Not specified by the tool configuration."
            if candidate_data.get("mechanism") is None
            else _text(candidate_data["mechanism"], "candidate.mechanism")
        ),
    )
    rules = _rules(data.get("rules"))
    if candidate.hypothesis_class not in rules:
        raise ValueError("candidate class has no configured constraint rule")
    signal_names = {item.name for item in signals}
    predicates = _predicates(data.get("predicates", {}))
    referenced = predicates.primary_signals | predicates.corroboration_signals
    referenced |= frozenset(
        name
        for pair in predicates.actuator_pairs + predicates.temporal_precedence_pairs
        for name in pair
    )
    referenced |= frozenset(candidate.cited_signals)
    if not referenced <= signal_names:
        raise ValueError("scenario references an undeclared signal")
    return ScenarioConfig(
        signals,
        predicates,
        rules,
        candidate,
        _supported_action(data.get("supported_action"), "scenario.supported_action"),
    )


def load_relations(path: str | Path) -> LoadedRelations:
    """Load external YAML into immutable core config objects; reject unknown fields."""
    raw = cast(object, yaml.safe_load(Path(path).read_text(encoding="utf-8")))
    data = _mapping(raw, "configuration")
    version = data.get("version")
    # The product schema is v2. A missing version means the current schema;
    # the v1 branch stays only for the internal benchmark fixtures.
    if version is None or version == 2:
        from src.config_loader_v2 import load_v2_relations

        return load_v2_relations(data, base_dir=Path(path).resolve().parent)
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError("tool model version must be 2 or omitted")
    if version != 1:
        raise ValueError("tool model version must be 2 or omitted")
    _keys(
        data,
        {"version", "name", "provenance", "signals", "groups", "roles", "scenarios"},
        "configuration",
    )
    signals = tuple(
        _signal(item) for item in _items(data.get("signals", []), "signals")
    )
    scenarios_raw = _mapping(data.get("scenarios", {}), "scenarios")
    scenarios = {name: _scenario(value) for name, value in scenarios_raw.items()}
    if len({item.name for item in signals}) != len(signals):
        raise ValueError("configuration signals must be uniquely named")
    known = {item.name for item in signals}
    known.update(item.name for case in scenarios.values() for item in case.signals)
    groups = _name_lists(data.get("groups", {}), known, "groups")
    roles = _name_lists(data.get("roles", {}), known, "roles")
    return LoadedRelations(
        name=_text(data.get("name"), "name"),
        provenance=_text(data.get("provenance"), "provenance"),
        signals=signals,
        groups=groups,
        roles=roles,
        scenarios=MappingProxyType(scenarios),
    )


def _name_lists(
    value: object, known: set[str], where: str
) -> Mapping[str, tuple[str, ...]]:
    data = _mapping(value, where)
    parsed = {name: _strings(items, f"{where}.{name}") for name, items in data.items()}
    if any(not set(items) <= known for items in parsed.values()):
        raise ValueError(f"{where} references an undeclared signal")
    return MappingProxyType(parsed)
