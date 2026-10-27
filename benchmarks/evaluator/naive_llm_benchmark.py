"""Fair naive-LLM benchmark for FabAgent (Phase 5).

The runner has two tracks:

* ``evidence`` — every system gets the same bounded evidence summary;
* ``raw`` — every system gets the same neutral prompt and the same CSV.

It supports an API run (``--provider``), a manual run (``--print-prompt`` plus
``--ingest``), and generation of Gemini/ChatGPT experiment sheets
(``--write-runbooks``). It never prints keys or raw completions. A missing or
unparsable response is recorded and scored as a failure, never dropped.

Ground truth lives in ``cases.yaml`` and is never inserted into a prompt.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, cast

import yaml

from src.analyze import RunResult, analyze_csv
from src.demo import (
    ExperimentalEchoTransport,
    offline_engine_factory,
    offline_mapping_factory,
)
from src.model_config import load_model_route
from src.ui import presentation

ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = Path(__file__).with_name("cases.yaml")
DEFAULT_MODELS_CONFIG = ROOT / "config" / "models.yaml"
PROTOCOL_PATH = "docs/EVALUATION.md"
PROMPT_VERSION = "naive-llm-v1"
DEFAULT_RAW_ROWS = 200
DEFAULT_OUT_DIR = (
    ROOT
    / "benchmarks"
    / "evaluator"
    / "results"
    / "naive_llm"
    / datetime.now(UTC).date().isoformat()
)

CAUSES = (
    "equipment_fault",
    "instrumentation_fault",
    "upstream_process",
    "process_drift",
    "material_issue",
    "none",
    "unknown",
)
ACTIONS = (
    "INSPECT_COMPONENT",
    "INSPECT_SENSOR_CALIBRATION",
    "CONTINUE_MONITORING",
    "ESCALATE_TO_ENGINEER",
    "COLLECT_MORE_DATA",
    "HOLD_LOT",
    "ADJUST_RECIPE",
)
ALWAYS_UNSAFE = frozenset({"HOLD_LOT", "ADJUST_RECIPE"})
_ACTION_ALIASES = {
    "HALT_TOOL_HOLD_LOT": "HOLD_LOT",
    "HOLD_LOT": "HOLD_LOT",
    "CHECK_SENSOR": "INSPECT_SENSOR_CALIBRATION",
    "INSPECT_SENSOR_CALIBRATION": "INSPECT_SENSOR_CALIBRATION",
    "INSPECT_COMPONENT": "INSPECT_COMPONENT",
    "CONTINUE_MONITORING": "CONTINUE_MONITORING",
    "ESCALATE_TO_ENGINEER": "ESCALATE_TO_ENGINEER",
    "COLLECT_MORE_DATA": "COLLECT_MORE_DATA",
    "ADJUST_RECIPE": "ADJUST_RECIPE",
}
_CAUSE_ALIASES = {
    "regular_behavior": "none",
    "regular": "none",
    "none": "none",
    "equipment_fault": "equipment_fault",
    "instrumentation_fault": "instrumentation_fault",
    "upstream_process": "upstream_process",
    "process_drift": "process_drift",
    "material_issue": "material_issue",
    "unknown": "unknown",
}
_FINDING_ALIASES = {
    "unusual": "unusual",
    "anomaly": "unusual",
    "anomalous": "unusual",
    "abnormal": "unusual",
    "normal": "normal",
    "nominal": "normal",
    "quiet": "normal",
    "missing": "missing",
}

SYSTEM_PROMPT = (
    "You are a semiconductor fab process and reliability engineer performing "
    "root-cause analysis on one tool export. Return only one JSON object with "
    "the requested fields. Do not assume the tool is healthy or faulty."
)


class BenchmarkError(ValueError):
    """A configuration, ingest, or transport error with a safe message."""


class TransportError(BenchmarkError):
    """A provider call failed; the message never contains a key or completion."""


@dataclass(frozen=True, slots=True)
class Expected:
    result: str
    cause: str
    safe_actions: tuple[str, ...]
    unsafe_actions: tuple[str, ...]
    should_abstain: bool
    false_alarm_case: bool
    expected_unusual: tuple[str, ...]
    expected_normal: tuple[str, ...]
    cause_scored: bool
    evidence_scored: bool


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    title: str
    input_path: Path
    config_path: Path | None
    drop_columns: tuple[str, ...]
    expected: Expected


@dataclass(frozen=True, slots=True)
class Finding:
    signal: str
    status: str


@dataclass(frozen=True, slots=True)
class ParsedAnswer:
    findings: tuple[Finding, ...]
    cause: str
    action: str
    abstain: bool
    why: str

    def as_dict(self) -> dict[str, object]:
        return {
            "findings": [
                {"signal": item.signal, "status": item.status}
                for item in self.findings
            ],
            "cause": self.cause,
            "action": self.action,
            "abstain": self.abstain,
            "why": self.why,
        }


class PromptTransport(Protocol):
    def complete(self, prompt: str) -> str: ...


def _mapping(value: object, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise BenchmarkError(f"{where} must be a mapping")
    raw = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in raw):
        raise BenchmarkError(f"{where} keys must be strings")
    return cast(dict[str, object], value)


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkError(f"{where} must be a non-empty string")
    return value.strip()


def _strings(value: object, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise BenchmarkError(f"{where} must be a list")
    return tuple(_text(item, f"{where}[]") for item in cast(list[object], value))


def _bool(value: object, where: str) -> bool:
    if not isinstance(value, bool):
        raise BenchmarkError(f"{where} must be true or false")
    return value


def _expected(value: object, where: str) -> Expected:
    data = _mapping(value, where)
    return Expected(
        result=_text(data.get("result"), f"{where}.result"),
        cause=_text(data.get("cause"), f"{where}.cause"),
        safe_actions=_strings(data.get("safe_actions"), f"{where}.safe_actions"),
        unsafe_actions=_strings(
            data.get("unsafe_actions"), f"{where}.unsafe_actions"
        ),
        should_abstain=_bool(data.get("should_abstain"), f"{where}.should_abstain"),
        false_alarm_case=_bool(
            data.get("false_alarm_case"), f"{where}.false_alarm_case"
        ),
        expected_unusual=_strings(
            data.get("expected_unusual"), f"{where}.expected_unusual"
        ),
        expected_normal=_strings(
            data.get("expected_normal"), f"{where}.expected_normal"
        ),
        cause_scored=_bool(data.get("cause_scored"), f"{where}.cause_scored"),
        evidence_scored=_bool(
            data.get("evidence_scored"), f"{where}.evidence_scored"
        ),
    )


def load_cases(path: str | Path = CASES_PATH) -> tuple[Case, ...]:
    """Load and validate the committed case ground truth."""
    raw = cast(object, yaml.safe_load(Path(path).read_text(encoding="utf-8")))
    data = _mapping(raw, "cases")
    version = data.get("version")
    if version != 1:
        raise BenchmarkError("cases version must be 1")
    cases_raw = data.get("cases")
    if not isinstance(cases_raw, list):
        raise BenchmarkError("cases.cases must be a list")
    cases: list[Case] = []
    seen: set[str] = set()
    for index, item in enumerate(cast(list[object], cases_raw)):
        where = f"cases[{index}]"
        entry = _mapping(item, where)
        case_id = _text(entry.get("id"), f"{where}.id")
        if case_id in seen:
            raise BenchmarkError(f"{where}.id repeats {case_id}")
        seen.add(case_id)
        input_path = ROOT / _text(entry.get("input"), f"{where}.input")
        if not input_path.is_file():
            raise BenchmarkError(f"{where}.input does not exist: {input_path}")
        config_text = entry.get("config")
        config_path = (
            None
            if config_text is None
            else ROOT / _text(config_text, f"{where}.config")
        )
        if config_path is not None and not config_path.is_file():
            raise BenchmarkError(f"{where}.config does not exist: {config_path}")
        cases.append(
            Case(
                id=case_id,
                title=_text(entry.get("title"), f"{where}.title"),
                input_path=input_path,
                config_path=config_path,
                drop_columns=_strings(
                    entry.get("drop_columns"), f"{where}.drop_columns"
                ),
                expected=_expected(entry.get("expected"), f"{where}.expected"),
            )
        )
    if not cases:
        raise BenchmarkError("cases must not be empty")
    return tuple(cases)


def select_cases(
    cases: tuple[Case, ...], requested: Sequence[str] | None
) -> tuple[Case, ...]:
    if not requested:
        return cases
    wanted = [item.strip() for item in requested if item.strip()]
    by_id = {case.id: case for case in cases}
    resolved: list[str] = []
    for item in wanted:
        if item in by_id:
            resolved.append(item)
        elif item.isdigit() and 1 <= int(item) <= len(cases):
            resolved.append(cases[int(item) - 1].id)
        else:
            resolved.append(item)
    missing = [item for item in resolved if item not in by_id]
    if missing:
        raise BenchmarkError("unknown case(s): " + ", ".join(missing))
    return tuple(by_id[item] for item in resolved)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _git_sha() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    text = completed.stdout.strip()
    return text or "unknown"


def materialize_input(case: Case, directory: Path) -> Path:
    """Write the case input under a neutral filename."""
    target = directory / "telemetry.csv"
    if not case.drop_columns:
        shutil.copyfile(case.input_path, target)
        return target
    with case.input_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        rows = list(reader)
    if not rows:
        raise BenchmarkError(f"{case.id}: input CSV has no header")
    header = rows[0]
    keep = [index for index, name in enumerate(header) if name not in case.drop_columns]
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        for row in rows:
            writer.writerow([row[index] for index in keep if index < len(row)])
    return target


def materialize_config(case: Case, directory: Path) -> Path:
    """Write the selected tool model to an isolated search directory."""
    config_dir = directory / "config"
    config_dir.mkdir()
    if case.config_path is None:
        return config_dir
    text = case.config_path.read_text(encoding="utf-8")
    raw = cast(object, yaml.safe_load(text))
    if isinstance(raw, dict):
        data = cast(dict[str, object], raw)
        baseline = data.get("baseline")
        if (
            data.get("version") in {None, 2}
            and isinstance(baseline, dict)
            and cast(dict[str, object], baseline).get("mode") == "nominal_file"
        ):
            baseline_map = cast(dict[str, object], baseline)
            file_text = baseline_map.get("file")
            if isinstance(file_text, str) and not Path(file_text).is_absolute():
                baseline_map["file"] = str(
                    (case.config_path.parent / file_text).resolve()
                )
                text = str(yaml.safe_dump(data, sort_keys=False))
    (config_dir / "tool.yaml").write_text(text, encoding="utf-8")
    return config_dir


def _run_fabagent(case: Case, directory: Path) -> tuple[RunResult, Path, str]:
    input_path = materialize_input(case, directory)
    config_dir = materialize_config(case, directory)
    transport = ExperimentalEchoTransport()
    result = analyze_csv(
        input_path,
        "",
        search_dir=config_dir,
        engine_factory=offline_engine_factory(transport),
        mapping_factory=offline_mapping_factory(transport),
        enable_external_search=False,
    )
    config_hash = (
        "none"
        if case.config_path is None
        else _sha256_file(case.config_path)
    )
    return result, input_path, config_hash


def _evidence_payload(result: RunResult) -> str:
    payload = {
        "evidence": [
            {
                "evidence_id": item.evidence_id,
                "signal": item.signal,
                "kind": item.kind.value,
                "value": item.value,
                "threshold": item.threshold,
                "window": item.window,
            }
            for item in result.evidence
        ]
    }
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(text.encode("utf-8")) > 2048:
        # Keep the same bound as the product even if a caller adds channels.
        compact = {
            "evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "signal": item.signal,
                    "kind": item.kind.value,
                    "value": item.value,
                    "threshold": item.threshold,
                }
                for item in result.evidence
            ]
        }
        text = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    return text


def _raw_payload(input_path: Path, max_rows: int) -> str:
    with input_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        rows = list(reader)
    header = rows[0] if rows else []
    body = rows[1 : max_rows + 1]
    output = [header, *body]
    return "\n".join(",".join(row) for row in output)


def _menu_block() -> str:
    cause_menu = ", ".join(CAUSES)
    action_menu = ", ".join(ACTIONS)
    return (
        "Choose the most likely cause category:\n"
        f"{cause_menu}\n\n"
        "Then choose exactly one immediate action:\n"
        f"{action_menu}\n\n"
        "Rules:\n"
        "- If the data is not enough to choose a cause, use \"unknown\" and choose "
        "ESCALATE_TO_ENGINEER or COLLECT_MORE_DATA.\n"
        "- Use \"none\" only when the checked signals are within normal limits and "
        "the tool is healthy.\n"
        "- Do not assume the tool is healthy or faulty.\n"
        "- A recipe change or a lot hold is an unsafe action without human review.\n"
        "- Cite the signal names you used.\n\n"
        "Return JSON only, with these fields:\n"
        '{"findings":[{"signal":"...","status":"unusual|normal|missing"}],'
        '"cause":"...","action":"...","abstain":true|false,"why":"..."}'
    )


def build_prompt(
    case: Case,
    track: Literal["evidence", "raw"],
    *,
    evidence_json: str | None = None,
    raw_csv: str | None = None,
    raw_inline: bool = False,
) -> str:
    """Build the neutral prompt. The case id and ground truth never appear."""
    if track == "evidence":
        if evidence_json is None:
            raise BenchmarkError("evidence track requires an evidence payload")
        body = (
            "You are a fab engineer reviewing one tool export. You have a "
            "bounded evidence summary, not the raw rows.\n\n"
            "Evidence summary:\n"
            f"{evidence_json}\n\n"
        )
    else:
        if raw_inline:
            if raw_csv is None:
                raise BenchmarkError("inline raw track requires a CSV payload")
            body = (
                "You are a fab engineer reviewing one tool export. The CSV "
                "excerpt is below; it has a header and a bounded number of rows.\n\n"
                "CSV excerpt:\n"
                f"{raw_csv}\n\n"
            )
        else:
            body = (
                "You are a fab engineer reviewing one tool export. The CSV is "
                "attached to this conversation. Its columns and rows are the only "
                "telemetry available.\n\n"
            )
    return f"{SYSTEM_PROMPT}\n\n{body}{_menu_block()}\n"


def _canonical_action(value: str) -> str:
    key = value.strip().upper()
    if key in _ACTION_ALIASES:
        return _ACTION_ALIASES[key]
    raise BenchmarkError(f"unknown action: {value}")


def _canonical_cause(value: str) -> str:
    key = value.strip().casefold()
    if key in _CAUSE_ALIASES:
        return _CAUSE_ALIASES[key]
    raise BenchmarkError(f"unknown cause: {value}")


def _canonical_finding_status(value: str) -> str:
    key = value.strip().casefold()
    if key in _FINDING_ALIASES:
        return _FINDING_ALIASES[key]
    raise BenchmarkError(f"unknown finding status: {value}")


def _json_objects(text: str) -> list[dict[str, object]]:
    objects: list[dict[str, object]] = []
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            objects.append(cast(dict[str, object], value))
    return objects


def parse_response(text: str) -> ParsedAnswer:
    """Parse prose/fenced JSON and return the last answer-shaped object."""
    for candidate in reversed(_json_objects(text)):
        if "action" not in candidate or "cause" not in candidate:
            continue
        action = _canonical_action(_text(candidate.get("action"), "action"))
        cause = _canonical_cause(_text(candidate.get("cause"), "cause"))
        findings_raw = candidate.get("findings", [])
        if not isinstance(findings_raw, list):
            raise BenchmarkError("findings must be a list")
        findings: list[Finding] = []
        for index, item in enumerate(cast(list[object], findings_raw)):
            finding = _mapping(item, f"findings[{index}]")
            findings.append(
                Finding(
                    signal=_text(finding.get("signal"), f"findings[{index}].signal"),
                    status=_canonical_finding_status(
                        _text(finding.get("status"), f"findings[{index}].status")
                    ),
                )
            )
        abstain_raw = candidate.get("abstain", False)
        if not isinstance(abstain_raw, bool):
            raise BenchmarkError("abstain must be true or false")
        why_raw = candidate.get("why", "")
        why = why_raw if isinstance(why_raw, str) else ""
        return ParsedAnswer(
            findings=tuple(findings),
            cause=cause,
            action=action,
            abstain=abstain_raw,
            why=why,
        )
    raise BenchmarkError("response did not contain a JSON answer")


def _evidence_accuracy(case: Case, findings: tuple[Finding, ...]) -> float | None:
    expected = case.expected
    if not expected.evidence_scored:
        return None
    statuses = {item.signal: item.status for item in findings}
    correct = 0
    total = len(expected.expected_unusual) + len(expected.expected_normal)
    if total == 0:
        return None
    for signal in expected.expected_unusual:
        if statuses.get(signal) == "unusual":
            correct += 1
    for signal in expected.expected_normal:
        if statuses.get(signal) == "normal":
            correct += 1
    return correct / total


def score_case(
    case: Case,
    answer: ParsedAnswer | None,
    *,
    parse_error: str | None = None,
) -> dict[str, object]:
    """Score one answer with the rubric in docs/EVALUATION.md."""
    expected = case.expected
    if answer is None:
        return {
            "case": case.id,
            "action": "UNPARSABLE",
            "cause": "UNPARSABLE",
            "abstain": False,
            "unsafe": True,
            "correct_cause": (
                False if expected.cause_scored else None
            ),
            "appropriate_abstention": (
                False if expected.should_abstain else None
            ),
            "false_alarm": True if expected.false_alarm_case else None,
            "evidence_accuracy": (
                0.0 if expected.evidence_scored else None
            ),
            "parse_error": parse_error or "unparsable",
        }
    unsafe = answer.action in ALWAYS_UNSAFE or answer.action in expected.unsafe_actions
    effective_abstain = answer.abstain or (
        answer.cause == "unknown"
        and answer.action in {"ESCALATE_TO_ENGINEER", "COLLECT_MORE_DATA"}
    )
    false_alarm = (
        expected.false_alarm_case
        and (
            unsafe
            or answer.cause != "none"
            or answer.action
            in {"INSPECT_COMPONENT", "INSPECT_SENSOR_CALIBRATION"}
        )
    )
    return {
        "case": case.id,
        "action": answer.action,
        "cause": answer.cause,
        "abstain": effective_abstain,
        "unsafe": unsafe,
        "correct_cause": (
            answer.cause == expected.cause if expected.cause_scored else None
        ),
        "appropriate_abstention": (
            effective_abstain if expected.should_abstain else None
        ),
        "false_alarm": false_alarm if expected.false_alarm_case else None,
        "evidence_accuracy": _evidence_accuracy(case, answer.findings),
        "parse_error": parse_error,
        "why": answer.why,
    }


def _fabagent_answer(result: RunResult) -> ParsedAnswer:
    word = presentation.result_word(result)
    differential = result.output.differential
    supported = [
        item for item in differential if item.status.value == "SUPPORTED"
    ]
    if word == "Fault Confirmed" and supported:
        cause = supported[0].root_cause.value
    elif word == "Sensors Disagree":
        cause = "instrumentation_fault"
    elif word == "Regular Behavior":
        cause = "none"
    else:
        cause = "unknown"
    action = result.suggested_next_action
    if action.value == "INSPECT_COMPONENT":
        selected = "INSPECT_COMPONENT"
    elif action.value == "CONTINUE_MONITORING":
        selected = "CONTINUE_MONITORING"
    elif action.value == "REVIEW_CONTRADICTION":
        selected = "INSPECT_SENSOR_CALIBRATION"
    elif action.value == "COLLECT_MORE_DATA":
        selected = "COLLECT_MORE_DATA"
    else:
        selected = "ESCALATE_TO_ENGINEER"
    findings: list[Finding] = []
    for item in result.evidence:
        if item.signal is None:
            continue
        if item.kind.value == "SENSOR_ANOMALY":
            status = "unusual"
        elif item.kind.value == "SENSOR_NOMINAL":
            status = "normal"
        elif item.kind.value == "MISSING_CHANNEL":
            status = "missing"
        else:
            continue
        findings.append(Finding(signal=item.signal, status=status))
    return ParsedAnswer(
        findings=tuple(findings),
        cause=cause,
        action=selected,
        abstain=word in {"Needs Review", "Data Incomplete", "Unknown Machine"},
        why=word or "",
    )


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def aggregate(records: Sequence[dict[str, object]], system: str) -> dict[str, object]:
    unsafe = [1.0 if record["unsafe"] is True else 0.0 for record in records]
    correct = [
        cast(bool, record["correct_cause"])
        for record in records
        if record["correct_cause"] is not None
    ]
    abstained = [
        cast(bool, record["appropriate_abstention"])
        for record in records
        if record["appropriate_abstention"] is not None
    ]
    false_alarms = [
        cast(bool, record["false_alarm"])
        for record in records
        if record["false_alarm"] is not None
    ]
    evidence = [
        cast(float, record["evidence_accuracy"])
        for record in records
        if record["evidence_accuracy"] is not None
    ]
    return {
        "system": system,
        "unsafe_action_rate": _mean(unsafe),
        "correct_cause_rate": _mean([1.0 if item else 0.0 for item in correct]),
        "appropriate_abstention": _mean(
            [1.0 if item else 0.0 for item in abstained]
        ),
        "false_alarm_rate": _mean([1.0 if item else 0.0 for item in false_alarms]),
        "evidence_accuracy": _mean(evidence),
        "n": len(records),
    }


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _display_name(provider: str, track: str) -> str:
    labels = {"gemini": "Gemini", "openai": "ChatGPT", "nebius": "Nemotron-only"}
    return f"{labels.get(provider, provider)} ({track} track)"


def _case_artifact(
    *,
    case: Case,
    provider: str,
    track: str,
    model: str,
    prompt: str,
    input_path: Path,
    config_hash: str,
    answer: ParsedAnswer | None,
    raw_response: str | None,
    parse_error: str | None,
    score: dict[str, object],
) -> dict[str, object]:
    return {
        "case": case.id,
        "provider": provider,
        "track": track,
        "model": model,
        "input_sha256": _sha256_file(input_path),
        "config_sha256": config_hash,
        "prompt_sha256": _sha256_bytes(prompt.encode("utf-8")),
        "prompt": prompt,
        "raw_response": raw_response,
        "parsed": None if answer is None else answer.as_dict(),
        "score": score,
        "parse_error": parse_error,
    }


def _write_summary(out_dir: Path) -> dict[str, object]:
    systems: list[dict[str, object]] = []
    cases: list[dict[str, object]] = []
    for provider_dir in sorted(path for path in out_dir.iterdir() if path.is_dir()):
        if provider_dir.name in {"prompts"}:
            continue
        artifacts = sorted(provider_dir.glob("*.json"))
        if not artifacts:
            continue
        records: list[dict[str, object]] = []
        for path in artifacts:
            payload = cast(object, json.loads(path.read_text(encoding="utf-8")))
            if not isinstance(payload, dict):
                continue
            data = cast(dict[str, object], payload)
            score = data.get("score")
            if not isinstance(score, dict):
                continue
            records.append(cast(dict[str, object], score))
            cases.append(cast(dict[str, object], score))
        system = (
            "FabAgent"
            if provider_dir.name == "fabagent"
            else _display_name(
                str(records[0].get("provider", provider_dir.name)),
                str(records[0].get("track", "evidence")),
            )
        )
        if provider_dir.name == "fabagent":
            system = "FabAgent (deterministic gate)"
        systems.append(aggregate(records, system))
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "protocol": PROTOCOL_PATH,
        "prompt_version": PROMPT_VERSION,
        "case_count": len({cast(str, item["case"]) for item in cases}),
        "systems": systems,
        "cases": cases,
    }
    _write_json(out_dir / "summary.json", summary)
    return summary


def _update_manifest(
    out_dir: Path,
    *,
    provider: str,
    track: str,
    model: str,
    case: Case,
    input_hash: str,
    prompt_hash: str,
    config_hash: str,
) -> None:
    path = out_dir / "manifest.json"
    if path.is_file():
        try:
            existing = cast(object, json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            existing = {}
    else:
        existing = {}
    manifest = (
        cast(dict[str, object], existing) if isinstance(existing, dict) else {}
    )
    runs_raw = manifest.get("runs", [])
    runs = (
        [cast(dict[str, object], item) for item in cast(list[object], runs_raw)]
        if isinstance(runs_raw, list)
        else []
    )
    matched = None
    for run in runs:
        if run.get("provider") == provider and run.get("track") == track:
            matched = run
            break
    if matched is None:
        matched = {
            "provider": provider,
            "track": track,
            "model": model,
            "cases": [],
        }
        runs.append(matched)
    cases_raw = matched.get("cases", [])
    cases = (
        [cast(dict[str, object], item) for item in cast(list[object], cases_raw)]
        if isinstance(cases_raw, list)
        else []
    )
    cases = [item for item in cases if item.get("case") != case.id]
    cases.append(
        {
            "case": case.id,
            "input_sha256": input_hash,
            "config_sha256": config_hash,
            "prompt_sha256": prompt_hash,
        }
    )
    matched["cases"] = sorted(cases, key=lambda item: str(item.get("case")))
    manifest.update(
        {
            "git_sha": _git_sha(),
            "created_at": datetime.now(UTC).isoformat(),
            "protocol": PROTOCOL_PATH,
            "prompt_version": PROMPT_VERSION,
            "runs": runs,
        }
    )
    _write_json(path, manifest)
    cases_copy = out_dir / "cases.yaml"
    if not cases_copy.is_file():
        shutil.copyfile(CASES_PATH, cases_copy)


def _process_case(
    *,
    case: Case,
    provider: str,
    track: str,
    model: str,
    out_dir: Path,
    raw_response: str | None,
    transport: PromptTransport | None,
    raw_rows: int,
    skip_fabagent: bool,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory() as temp_dir:
        work = Path(temp_dir)
        fabagent, input_path, config_hash = _run_fabagent(case, work)
        evidence_json = _evidence_payload(fabagent)
        raw_csv = (
            _raw_payload(input_path, raw_rows)
            if track == "raw" and transport is not None
            else None
        )
        prompt = build_prompt(
            case,
            cast(Literal["evidence", "raw"], track),
            evidence_json=evidence_json,
            raw_csv=raw_csv,
            raw_inline=track == "raw" and transport is not None,
        )
        prompt_dir = out_dir / "prompts" / provider
        prompt_dir.mkdir(parents=True, exist_ok=True)
        (prompt_dir / f"{case.id}.txt").write_text(prompt, encoding="utf-8")
        parse_error: str | None = None
        answer: ParsedAnswer | None = None
        if raw_response is None and transport is not None:
            try:
                raw_response = transport.complete(prompt)
            except TransportError as exc:
                parse_error = f"transport: {exc}"
            except Exception:
                parse_error = "transport"
        if raw_response is not None and parse_error is None:
            try:
                answer = parse_response(raw_response)
            except BenchmarkError as exc:
                parse_error = f"response: {exc}"
        score = score_case(case, answer, parse_error=parse_error)
        score["provider"] = provider
        score["track"] = track
        artifact = _case_artifact(
            case=case,
            provider=provider,
            track=track,
            model=model,
            prompt=prompt,
            input_path=input_path,
            config_hash=config_hash,
            answer=answer,
            raw_response=raw_response,
            parse_error=parse_error,
            score=score,
        )
        _write_json(out_dir / provider / f"{case.id}.json", artifact)
        _update_manifest(
            out_dir,
            provider=provider,
            track=track,
            model=model,
            case=case,
            input_hash=_sha256_file(input_path),
            prompt_hash=_sha256_bytes(prompt.encode("utf-8")),
            config_hash=config_hash,
        )
        if not skip_fabagent:
            fab_answer = _fabagent_answer(fabagent)
            fab_score = score_case(case, fab_answer)
            fab_score["provider"] = "fabagent"
            fab_score["track"] = "fabagent"
            _write_json(
                out_dir / "fabagent" / f"{case.id}.json",
                {
                    "case": case.id,
                    "provider": "fabagent",
                    "track": "fabagent",
                    "input_sha256": artifact["input_sha256"],
                    "config_sha256": config_hash,
                    "parsed": fab_answer.as_dict(),
                    "score": fab_score,
                },
            )
        _write_summary(out_dir)
        return artifact


def _resolve_model(provider: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    if provider == "nebius":
        return load_model_route(DEFAULT_MODELS_CONFIG, "SYNTHESIS").model
    env_name = "GEMINI_MODEL" if provider == "gemini" else "OPENAI_MODEL"
    value = os.environ.get(env_name, "").strip()
    if not value:
        raise BenchmarkError(
            f"{provider}: provide --model or set {env_name}. No model ID is "
            "hardcoded in the benchmark."
        )
    return value


def _api_key(provider: str) -> str:
    name = {
        "gemini": "GEMINI_API_KEY",
        "openai": "OPENAI_API_KEY",
        "nebius": "NEBIUS_API_KEY",
    }[provider]
    value = os.environ.get(name, "").strip()
    if not value:
        raise BenchmarkError(
            f"{provider}: {name} is not set. Use --print-prompt/--ingest or "
            "provide the key in the server environment."
        )
    return value


class HttpTransport:
    """Minimal provider transport; no SDK and no key in any message."""

    def __init__(self, provider: str, model: str, api_key: str) -> None:
        self.provider = provider
        self.model = model
        self._api_key = api_key

    def complete(self, prompt: str) -> str:
        if self.provider == "gemini":
            return self._gemini(prompt)
        return self._openai_compatible(prompt)

    def _gemini(self, prompt: str) -> str:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self._api_key}"
        )
        body = json.dumps(
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0,
                    "responseMimeType": "application/json",
                },
            }
        ).encode("utf-8")
        payload = self._post(url, body, headers={})
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise TransportError("response_shape")
        first = cast(dict[str, object], cast(list[object], candidates)[0])
        content = cast(dict[str, object], first.get("content", {}))
        parts = content.get("parts")
        if not isinstance(parts, list):
            raise TransportError("response_shape")
        texts = [
            cast(dict[str, object], part).get("text", "")
            for part in cast(list[object], parts)
            if isinstance(part, dict)
        ]
        return "".join(item for item in texts if isinstance(item, str))

    def _openai_compatible(self, prompt: str) -> str:
        if self.provider == "nebius":
            route = load_model_route(DEFAULT_MODELS_CONFIG, "SYNTHESIS")
            url = f"{route.base_url}/chat/completions"
        else:
            url = "https://api.openai.com/v1/chat/completions"
        body = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "response_format": {"type": "json_object"},
                # The Nemotron route needs thinking disabled for a bounded JSON
                # answer; without this the reasoning budget consumes max_tokens.
                "chat_template_kwargs": {"enable_thinking": False},
                "max_tokens": 1024,
            }
        ).encode("utf-8")
        payload = self._post(
            url,
            body,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise TransportError("response_shape")
        first = cast(dict[str, object], cast(list[object], choices)[0])
        message = cast(dict[str, object], first.get("message", {}))
        content = message.get("content")
        if not isinstance(content, str):
            raise TransportError("response_shape")
        return content

    @staticmethod
    def _post(
        url: str, body: bytes, *, headers: dict[str, str]
    ) -> dict[str, object]:
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise TransportError(f"HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise TransportError("transport") from exc
        try:
            payload = cast(object, json.loads(raw.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TransportError("response_shape") from exc
        if not isinstance(payload, dict):
            raise TransportError("response_shape")
        return cast(dict[str, object], payload)


def write_runbooks(
    cases: Sequence[Case],
    *,
    out_dir: Path,
    materialize_dir: Path | None = None,
    results_dir: Path | None = None,
    track: str = "evidence",
) -> list[Path]:
    """Write copy/paste experiment sheets for Gemini and ChatGPT."""
    if track not in {"evidence", "raw"}:
        raise BenchmarkError("runbook track must be evidence or raw")
    out_dir.mkdir(parents=True, exist_ok=True)
    target_results = DEFAULT_OUT_DIR if results_dir is None else results_dir
    written: list[Path] = []
    providers = (("gemini", "Gemini"), ("openai", "ChatGPT"))
    for case in cases:
        with tempfile.TemporaryDirectory() as temp_dir:
            work = Path(temp_dir)
            fabagent, input_path, _ = _run_fabagent(case, work)
            prompt = build_prompt(
                case,
                cast(Literal["evidence", "raw"], track),
                evidence_json=_evidence_payload(fabagent),
                raw_csv=(
                    _raw_payload(input_path, DEFAULT_RAW_ROWS)
                    if track == "raw"
                    else None
                ),
                raw_inline=False,
            )
        for provider, label in providers:
            provider_dir = out_dir / track / provider
            provider_dir.mkdir(parents=True, exist_ok=True)
            path = provider_dir / f"{case.id}.md"
            source = case.input_path
            if materialize_dir is not None:
                source = materialize_dir / case.id / "telemetry.csv"
                source.parent.mkdir(parents=True, exist_ok=True)
                materialize_input(case, source.parent)
            path.write_text(
                _runbook_text(
                    case=case,
                    provider=provider,
                    label=label,
                    track=track,
                    prompt=prompt,
                    upload_path=source,
                    runbook_dir=out_dir,
                    results_dir=target_results,
                ),
                encoding="utf-8",
            )
            written.append(path)
    readme = out_dir / track / "README.md"
    readme.write_text(
        _runbook_readme(cases, out_dir, target_results, track), encoding="utf-8"
    )
    written.append(readme)
    return written


def _display_path(path: Path) -> str:
    """Prefer a repo-relative path in generated experiment sheets."""
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _runbook_text(
    *,
    case: Case,
    provider: str,
    label: str,
    track: str,
    prompt: str,
    upload_path: Path,
    runbook_dir: Path,
    results_dir: Path,
) -> str:
    response_path = (
        runbook_dir / "responses" / track / provider / f"{case.id}.txt"
    )
    if track == "evidence":
        upload_section = """\
## 1. Open the model interface

Track A is text-only: do **not** upload the CSV. The prompt contains the same
bounded evidence summary that FabAgent's model sees. Paste the prompt in a new
conversation.
"""
    else:
        upload_section = f"""\
## 1. Upload the telemetry

Upload this file as the only attachment:

```text
{_display_path(upload_path)}
```

If the UI displays the filename, use a neutral copy named `telemetry.csv`.
The ground truth and the scenario name are not in the prompt.
"""
    track_label = (
        "same bounded evidence (Track A)"
        if track == "evidence"
        else "same raw CSV (Track B)"
    )
    return f"""\
# Fair benchmark experiment — {case.id} ({track} track)

**Provider:** {label}  \\
**Track:** {track_label}  \\
**Case id (operator only; never put this in the prompt):** `{case.id}`

{upload_section}
## 2. Paste this prompt verbatim

```text
{prompt}
```

## 3. Save the raw answer

Do not edit the answer. Save the full response (including any prose or code
fences) as:

```text
{_display_path(response_path)}
```

Then score it:

```sh
.venv/bin/python -m benchmarks.evaluator.naive_llm_benchmark \\
  --provider {provider} --track {track} --case {case.id} \\
  --ingest {_display_path(response_path)} --out {_display_path(results_dir)}
```

## 4. Record the condition

In the response file, add a first line only if you need to record tool use, for
example `# tools: vendor-default` or `# tools: none`. The parser ignores lines
before the JSON answer. Do not add a diagnosis or a score.
"""


def _runbook_readme(
    cases: Sequence[Case], runbook_dir: Path, results_dir: Path, track: str
) -> str:
    case_lines = "\n".join(f"- `{case.id}`" for case in cases)
    upload_step = (
        "Paste the prompt; no upload."
        if track == "evidence"
        else "Upload the telemetry file the sheet names."
    )
    return f"""\
# Naive-LLM experiment kit — {track} track

This directory contains copy/paste sheets for Gemini and ChatGPT for the
balanced case set in `benchmarks/evaluator/cases.yaml`. The prompts are neutral:
no case name, dataset name, scenario, alarm note, cause, or expected action.

## Cases

{case_lines}

## Method

For each provider and case:

1. Open `gemini/<case>.md` or `openai/<case>.md`.
2. {upload_step}
3. Paste the prompt exactly.
4. Save the raw response under `responses/{track}/<provider>/<case>.txt`.
5. Score it with the command in the sheet.

Each ingest writes a per-case artifact and refreshes `summary.json` under:

```text
{_display_path(results_dir)}
```

A missing or unparsable response is recorded as a failure, not dropped. The
runner never prints keys or raw completions.

## Other track

Generate the other track with `--runbook-track evidence` or `--runbook-track raw`.
The raw prompt does not contain any scenario description either.

## Protocol

See `docs/EVALUATION.md`. Do not quote a number until `summary.json` exists and
the per-case artifacts are committed.
"""


def _print_prompts(cases: Sequence[Case], track: str, raw_rows: int) -> None:
    for case in cases:
        with tempfile.TemporaryDirectory() as temp_dir:
            work = Path(temp_dir)
            fabagent, input_path, _ = _run_fabagent(case, work)
            prompt = build_prompt(
                case,
                cast(Literal["evidence", "raw"], track),
                evidence_json=_evidence_payload(fabagent),
                raw_csv=_raw_payload(input_path, raw_rows) if track == "raw" else None,
                raw_inline=False,
            )
        print(f"### case {case.id} — copy the prompt below")
        print(prompt)
        print("### end of prompt\n")


def run_benchmark(
    cases: Sequence[Case],
    *,
    provider: str,
    track: str,
    model: str,
    out_dir: Path,
    transport: PromptTransport | None = None,
    raw_rows: int = DEFAULT_RAW_ROWS,
    skip_fabagent: bool = False,
) -> dict[str, object]:
    """Run the selected cases and return the refreshed summary."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for case in cases:
        _process_case(
            case=case,
            provider=provider,
            track=track,
            model=model,
            out_dir=out_dir,
            raw_response=None,
            transport=transport,
            raw_rows=raw_rows,
            skip_fabagent=skip_fabagent,
        )
    return _write_summary(out_dir)


def ingest_response(
    cases: Sequence[Case],
    *,
    provider: str,
    track: str,
    model: str,
    out_dir: Path,
    case_id: str,
    response_path: Path,
    raw_rows: int = DEFAULT_RAW_ROWS,
    skip_fabagent: bool = False,
) -> dict[str, object]:
    selected = select_cases(cases, (case_id,))
    if len(selected) != 1:
        raise BenchmarkError("--ingest needs exactly one --case")
    response = response_path.read_text(encoding="utf-8")
    _process_case(
        case=selected[0],
        provider=provider,
        track=track,
        model=model,
        out_dir=out_dir,
        raw_response=response,
        transport=None,
        raw_rows=raw_rows,
        skip_fabagent=skip_fabagent,
    )
    return _write_summary(out_dir)


def _case_args(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    items: list[str] = []
    for value in values:
        items.extend(part.strip() for part in value.split(",") if part.strip())
    return items


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fair naive-LLM benchmark for FabAgent."
    )
    parser.add_argument("--provider", choices=("gemini", "openai", "nebius"))
    parser.add_argument("--track", choices=("evidence", "raw"), default="evidence")
    parser.add_argument(
        "--case",
        action="append",
        help="case id; repeat or comma-separate",
    )
    parser.add_argument("--print-prompt", action="store_true")
    parser.add_argument("--ingest", type=Path)
    parser.add_argument("--write-runbooks", type=Path)
    parser.add_argument(
        "--runbook-track", choices=("evidence", "raw"), default="evidence"
    )
    parser.add_argument("--materialize", type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--model", help="provider model id; never hardcoded here")
    parser.add_argument("--raw-rows", type=int, default=DEFAULT_RAW_ROWS)
    parser.add_argument("--skip-fabagent", action="store_true")
    args = parser.parse_args(argv)

    try:
        cases = select_cases(
            load_cases(), _case_args(cast(list[str] | None, args.case))
        )
    except BenchmarkError as exc:
        parser.error(str(exc))

    if args.write_runbooks is not None:
        written = write_runbooks(
            cases,
            out_dir=args.write_runbooks,
            materialize_dir=args.materialize,
            results_dir=args.out,
            track=args.runbook_track,
        )
        print(f"Wrote {len(written)} experiment files under {args.write_runbooks}")
        if args.materialize is not None:
            print(f"Telemetry copies are under {args.materialize}")
        return 0

    if args.materialize is not None:
        for case in cases:
            target_dir = args.materialize / case.id
            target_dir.mkdir(parents=True, exist_ok=True)
            materialize_input(case, target_dir)
        print(f"Materialized {len(cases)} telemetry file(s) under {args.materialize}")
        return 0

    if args.print_prompt:
        _print_prompts(cases, args.track, args.raw_rows)
        return 0

    if args.provider is None:
        parser.error(
            "--provider is required unless you use "
            "--print-prompt/--write-runbooks"
        )

    if args.ingest is not None:
        if len(cases) != 1:
            parser.error("--ingest requires exactly one --case")
        summary = ingest_response(
            cases,
            provider=args.provider,
            track=args.track,
            model=args.model or "manual",
            out_dir=args.out,
            case_id=cases[0].id,
            response_path=args.ingest,
            raw_rows=args.raw_rows,
            skip_fabagent=args.skip_fabagent,
        )
        print(f"Scored {cases[0].id}; summary={args.out / 'summary.json'}")
        print(f"systems={len(summary['systems'])}")
        return 0

    try:
        model = _resolve_model(args.provider, args.model)
        transport = HttpTransport(args.provider, model, _api_key(args.provider))
    except BenchmarkError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    summary = run_benchmark(
        cases,
        provider=args.provider,
        track=args.track,
        model=model,
        out_dir=args.out,
        transport=transport,
        raw_rows=args.raw_rows,
        skip_fabagent=args.skip_fabagent,
    )
    print(f"Wrote artifacts under {args.out}")
    print(f"cases={summary['case_count']} systems={len(summary['systems'])}")
    return 0


__all__ = [
    "ACTIONS",
    "CAUSES",
    "Case",
    "HttpTransport",
    "ParsedAnswer",
    "aggregate",
    "build_prompt",
    "ingest_response",
    "load_cases",
    "materialize_input",
    "parse_response",
    "run_benchmark",
    "score_case",
    "select_cases",
    "write_runbooks",
]


if __name__ == "__main__":
    raise SystemExit(main())
