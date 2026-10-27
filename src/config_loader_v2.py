from __future__ import annotations

import csv
import math
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from src.config_loader import (
    items as _items,
)
from src.config_loader import (
    keys as _keys,
)
from src.config_loader import (
    mapping as _mapping,
)
from src.config_loader import (
    number as _number,
)
from src.config_loader import (
    strings as _strings,
)
from src.config_loader import (
    supported_action as _supported_action,
)
from src.config_loader import (
    text as _text,
)
from src.config_types import CandidateConfig, LoadedRelations, ScenarioConfig
from src.core.constraints import ConstraintRule
from src.core.sufficiency import PredicateConfig
from src.core.types import BaselineSpec, Predicate, SignalSpec
from src.schemas.models import RootCauseCategory

_CHECK_KEYS = {
    "id",
    "label",
    "kind",
    "must_be_unusual",
    "must_stay_normal",
    "corroborated_by",
    "action",
    "advice",
}
_SIGNAL_KEYS = {"name", "label", "unit", "alert_at"}
_BASELINE_KEYS = {"mode", "rows", "file", "step_column"}
_DIRECTIONS = frozenset({"any", "up", "down"})


def _csv_headers(path: Path) -> tuple[str, ...]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            row = next(csv.reader(handle), None)
    except (OSError, csv.Error) as exc:
        raise ValueError(f"baseline file could not be read: {path}") from exc
    if row is None or not row:
        raise ValueError(f"baseline file has no header: {path}")
    return tuple(row)


def _baseline(
    value: object,
    *,
    base_dir: Path,
    declared: frozenset[str],
) -> BaselineSpec:
    data = _mapping(value, "baseline")
    _keys(data, _BASELINE_KEYS, "baseline")
    mode = _text(data.get("mode"), "baseline.mode")
    if mode == "lead_in":
        rows = data.get("rows")
        if isinstance(rows, bool) or not isinstance(rows, int) or rows < 1:
            raise ValueError("baseline.rows must be a positive integer")
        if data.get("file") is not None or data.get("step_column") is not None:
            raise ValueError("baseline.lead_in cannot set file or step_column")
        return BaselineSpec(mode=mode, rows=rows)
    if mode == "nominal_file":
        file_text = _text(data.get("file"), "baseline.file")
        if data.get("rows") is not None or data.get("step_column") is not None:
            raise ValueError("baseline.nominal_file cannot set rows or step_column")
        path = Path(file_text)
        if not path.is_absolute():
            path = (base_dir / path).resolve()
        if not path.is_file():
            raise ValueError(f"baseline.file does not exist: {path}")
        headers = set(_csv_headers(path))
        absent = sorted(declared - headers)
        if absent:
            raise ValueError(
                "baseline.file is missing declared signal(s): " + ", ".join(absent)
            )
        return BaselineSpec(mode=mode, file=str(path))
    if mode == "recipe_step":
        step_column = _text(data.get("step_column"), "baseline.step_column")
        if data.get("rows") is not None or data.get("file") is not None:
            raise ValueError("baseline.recipe_step cannot set rows or file")
        return BaselineSpec(mode=mode, step_column=step_column)
    raise ValueError("baseline.mode must be lead_in, nominal_file, or recipe_step")


def _signal(
    value: object,
    *,
    index: int,
    tool_name: str,
) -> tuple[SignalSpec, str]:
    where = f"signals[{index}]"
    data = _mapping(value, where)
    _keys(data, _SIGNAL_KEYS, where)
    name = _text(data.get("name"), f"{where}.name")
    label = (
        name
        if data.get("label") is None
        else _text(data["label"], f"{where}.label")
    )
    unit = (
        None
        if data.get("unit") is None
        else _text(data["unit"], f"{where}.unit")
    )
    alert_at = _number(data.get("alert_at", 3.5), f"{where}.alert_at")
    if alert_at is not None:
        if not math.isfinite(alert_at) or alert_at <= 0:
            raise ValueError(f"{where}.alert_at must be a positive finite number")
    source = (
        None
        if alert_at is None
        else f"yaml:{tool_name}:{name}:alert_at={alert_at:g}"
    )
    return SignalSpec(name, unit, alert_at, source), label


def _check(
    value: object,
    *,
    index: int,
    declared: Mapping[str, SignalSpec],
) -> tuple[str, ScenarioConfig]:
    where = f"checks[{index}]"
    data = _mapping(value, where)
    _keys(data, _CHECK_KEYS, where)
    check_id = _text(data.get("id"), f"{where}.id")
    if check_id == "new":
        raise ValueError(f"{where}.id is reserved for an unconfigured proposal")
    label = _text(data.get("label"), f"{where}.label")
    kind_text = _text(data.get("kind"), f"{where}.kind")
    try:
        kind = RootCauseCategory(kind_text)
    except ValueError as exc:
        raise ValueError(f"{where}.kind is not a known root-cause category") from exc
    if kind is RootCauseCategory.UNKNOWN:
        raise ValueError(f"{where}.kind must name a specific cause")

    primary: list[str] = []
    for item_index, item in enumerate(
        _items(data.get("must_be_unusual"), f"{where}.must_be_unusual")
    ):
        row_where = f"{where}.must_be_unusual[{item_index}]"
        row = _mapping(item, row_where)
        _keys(row, {"signal", "direction"}, row_where)
        signal = _text(row.get("signal"), f"{row_where}.signal")
        if signal not in declared:
            raise ValueError(f"{row_where} references an undeclared signal")
        if signal in primary:
            raise ValueError(f"{where}.must_be_unusual repeats {signal}")
        direction = _text(row.get("direction", "any"), f"{row_where}.direction")
        if direction not in _DIRECTIONS:
            raise ValueError(f"{row_where}.direction must be any, up, or down")
        primary.append(signal)
    if not primary:
        raise ValueError(f"{where}.must_be_unusual must not be empty")

    stay_normal = list(
        _strings(data.get("must_stay_normal", []), f"{where}.must_stay_normal")
    )
    if len(set(stay_normal)) != len(stay_normal):
        raise ValueError(f"{where}.must_stay_normal repeats a signal")
    for signal in stay_normal:
        if signal not in declared:
            raise ValueError(f"{where} references an undeclared signal")
    overlap = set(primary) & set(stay_normal)
    if overlap:
        raise ValueError(
            f"{where} cannot require and reject the same signal(s): "
            + ", ".join(sorted(overlap))
        )

    corroborated_by = list(
        _strings(data.get("corroborated_by", []), f"{where}.corroborated_by")
    )
    if len(set(corroborated_by)) != len(corroborated_by):
        raise ValueError(f"{where}.corroborated_by repeats a signal")
    for signal in corroborated_by:
        if signal not in declared:
            raise ValueError(f"{where} references an undeclared signal")
    overlap = set(corroborated_by) & set(stay_normal)
    if overlap:
        raise ValueError(
            f"{where} cannot expect a signal to move and stay normal: "
            + ", ".join(sorted(overlap))
        )

    action = _supported_action(data.get("action"), f"{where}.action")
    advice = _text(data.get("advice"), f"{where}.advice")
    hypothesis_class = kind.value
    cited: list[str] = []
    for signal in (*primary, *corroborated_by, *stay_normal):
        if signal not in cited:
            cited.append(signal)
    candidate = CandidateConfig(
        claim=label,
        hypothesis_class=hypothesis_class,
        cited_signals=tuple(cited),
        root_cause=kind,
        failure_mode=f"Configured check: {label}.",
        mechanism=advice,
    )
    rule = ConstraintRule(
        require_all=frozenset({Predicate.HAS_ALL_PRIMARY_SIGNALS_ANOMALY}),
        forbid_any=frozenset({Predicate.HAS_MISSING_REQUIRED_EVIDENCE}),
        veto_if_any=(
            frozenset({Predicate.HAS_INSTRUMENTATION_CONTRADICTION})
            if stay_normal or corroborated_by
            else frozenset()
        ),
    )
    referenced = (
        frozenset(primary) | frozenset(corroborated_by) | frozenset(stay_normal)
    )
    return check_id, ScenarioConfig(
        signals=tuple(
            spec for spec in declared.values() if spec.name in referenced
        ),
        predicate_config=PredicateConfig(
            primary_signals=frozenset(primary),
            corroboration_signals=frozenset(corroborated_by),
            forbidden_anomaly_signals=frozenset(stay_normal),
        ),
        rules={hypothesis_class: rule},
        candidate=candidate,
        supported_action=action,
        baseline=None,
        declared_signals=tuple(declared.values()),
    )


def load_v2_relations(
    data: Mapping[str, object],
    *,
    base_dir: Path,
) -> LoadedRelations:
    """Validate the v2 tool model and translate it into the core contracts."""
    _keys(
        data,
        {"version", "tool", "baseline", "signals", "checks"},
        "configuration",
    )
    version = data.get("version", 2)
    if isinstance(version, bool) or version != 2:
        raise ValueError("tool model version must be 2 or omitted")
    tool = _mapping(data.get("tool"), "tool")
    _keys(tool, {"name", "label", "description"}, "tool")
    tool_name = _text(tool.get("name"), "tool.name")
    _text(tool.get("label"), "tool.label")
    description = (
        tool_name
        if tool.get("description") is None
        else _text(tool["description"], "tool.description")
    )

    parsed_signals: list[SignalSpec] = []
    labels: dict[str, str] = {}
    for index, item in enumerate(_items(data.get("signals"), "signals")):
        spec, label = _signal(item, index=index, tool_name=tool_name)
        if spec.name in labels:
            raise ValueError(f"signals repeats {spec.name}")
        parsed_signals.append(spec)
        labels[spec.name] = label
    if not parsed_signals:
        raise ValueError("signals must not be empty")
    declared = {spec.name: spec for spec in parsed_signals}

    baseline = _baseline(
        data.get("baseline"),
        base_dir=base_dir,
        declared=frozenset(declared),
    )

    scenarios: dict[str, ScenarioConfig] = {}
    for index, item in enumerate(_items(data.get("checks", []), "checks")):
        check_id, scenario = _check(item, index=index, declared=declared)
        if check_id in scenarios:
            raise ValueError(f"checks repeats id {check_id}")
        scenarios[check_id] = ScenarioConfig(
            signals=scenario.signals,
            predicate_config=scenario.predicate_config,
            rules=scenario.rules,
            candidate=scenario.candidate,
            supported_action=scenario.supported_action,
            baseline=baseline,
            declared_signals=scenario.declared_signals,
        )

    return LoadedRelations(
        name=tool_name,
        provenance=description,
        signals=tuple(parsed_signals),
        groups=MappingProxyType({}),
        roles=MappingProxyType({}),
        scenarios=MappingProxyType(scenarios),
        signal_labels=MappingProxyType(labels),
    )
