from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from benchmarks.evaluator.echo_transport import (
    ExperimentalEchoTransport,
    offline_engine_factory,
    offline_mapping_factory,
)
from src.action_guidance import action_label
from src.analyze import RunResult, analyze_csv
from src.dossier import EngineFactory
from src.experimental import MappingFactory
from src.model_config import load_model_route
from src.schemas.models import RCAOutputModel

MODELS_CONFIG_NAME = "config/models.yaml"
OFFLINE_RESULT_NAME = "benchmarks/evaluator/results/user_story_offline.json"
LIVE_RESULT_NAME = "benchmarks/evaluator/results/user_story_live.json"

PHM_SAMPLE = "benchmarks/datasets/phm2018/sample/M02_DC_01_sample.csv"
B4A_TELEMETRY = "benchmarks/synthetic_twin/cases/B4a/telemetry.csv"


@dataclass(frozen=True, slots=True)
class UserScenario:
    scenario_id: str
    title: str
    trigger: str
    note: str
    path: Path


def _write_rows(path: Path, header: str, rows: list[str]) -> Path:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def _named_export(workdir: Path) -> Path:
    rows = []
    for index in range(40):
        reflect = 900.0 if 20 <= index < 26 else 120.0 + (index % 3)
        pressure = 3.2 + 0.01 * (index % 3)
        coolant = 55.0 + 0.1 * (index % 3)
        rows.append(f"{index},{reflect},{pressure:.2f},{coolant:.2f}")
    return _write_rows(
        workdir / "unknown_named_tool.csv",
        "timestamp,RF_Reflect_Power_W,Chamber_Pressure_Pa,Coolant_Flow_sccm",
        rows,
    )


def _opaque_export(workdir: Path) -> Path:
    rows = []
    for index in range(40):
        a = 1000.0 if 20 <= index < 25 else 10.0 + (index % 3)
        rows.append(f"{a},{10.0 + index % 3},{10.0 + index % 3}")
    return _write_rows(workdir / "opaque_export.csv", "a,b,c", rows)


def build_scenarios(root: Path, workdir: Path) -> tuple[UserScenario, ...]:
    malformed = workdir / "broken.csv"
    malformed.write_bytes(b"\x00\x01\x02\xff\xfe,not,a,csv\n\x00\xff")
    header_only = workdir / "header_only.csv"
    header_only.write_text("time,alpha,beta\n", encoding="utf-8")
    return (
        UserScenario(
            "known_phm_flowcool",
            "Known tool export (schema matches)",
            "User uploads a PHM ion-mill export the fab already has a config for.",
            "Ion mill alarm during an RF run; the flowcool loop looks abnormal.",
            root / PHM_SAMPLE,
        ),
        UserScenario(
            "unknown_named_tool",
            "Unknown tool, readable column names",
            "New tool export; no config matches the headers.",
            "New tool export, no schema configured yet. Please look at the signals.",
            _named_export(workdir),
        ),
        UserScenario(
            "unknown_opaque_tool",
            "Unknown tool, opaque column names",
            "Columns are a/b/c, so only statistics can map them.",
            "Export from a tool with meaningless column names; low-integration look.",
            _opaque_export(workdir),
        ),
        UserScenario(
            "synthetic_b4a",
            "Synthetic adversarial case (contradiction)",
            "Known synthetic scenario with a hard instrumentation contradiction.",
            "Sensor spike on the RF generator; other channels look nominal.",
            root / B4A_TELEMETRY,
        ),
        UserScenario(
            "malformed_csv",
            "Malformed CSV",
            "The file is not parseable.",
            "Please analyze this export.",
            malformed,
        ),
        UserScenario(
            "header_only_csv",
            "Header-only CSV",
            "The file has a header but no readings.",
            "Please analyze this export.",
            header_only,
        ),
        UserScenario(
            "missing_file",
            "Missing file",
            "The path does not exist.",
            "Please analyze this export.",
            workdir / "does-not-exist.csv",
        ),
    )


def _hypotheses(output: RCAOutputModel) -> list[dict[str, object]]:
    return [
        {
            "hypothesis_class": item.hypothesis_class,
            "root_cause": item.root_cause.value,
            "status": item.status.value,
            "cited_evidence": list(item.cited_evidence),
        }
        for item in output.hypotheses
    ]


def _mapping_summary(result: RunResult) -> dict[str, object] | None:
    if result.mapping is None:
        return None
    return {
        "proposed_signals": [
            {
                "column": item.column,
                "role_guess": item.role_guess,
                "unit_guess": item.unit_guess,
            }
            for item in result.mapping.signals
        ],
        "proposed_relationships": [
            {
                "primary": item.primary,
                "corroborating": list(item.corroborating),
            }
            for item in result.mapping.relationships
        ],
    }


def _llm_calls(result: RunResult, model: str) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []
    mapping_rejected = (result.detail or "").startswith("mapping_rejected")
    if result.mode == "experimental":
        if result.model_called:
            calls.append(
                {
                    "purpose": "signal_mapping",
                    "role": "SYNTHESIS",
                    "model": model,
                    "response": _mapping_summary(result),
                    "rejected": mapping_rejected,
                }
            )
        if result.mapping is not None and result.analysis_performed:
            calls.append(
                {
                    "purpose": "hypothesis",
                    "role": "SYNTHESIS",
                    "model": model,
                    "response": {"hypotheses": _hypotheses(result.output)},
                }
            )
    elif result.model_called:
        calls.append(
            {
                "purpose": "hypothesis",
                "role": "SYNTHESIS",
                "model": model,
                "response": {"hypotheses": _hypotheses(result.output)},
            }
        )
    return calls


def _triage_summary(result: RunResult) -> dict[str, object]:
    if result.selection is not None:
        return {
            "result": "matched",
            "config": result.selection.config_name,
            "scenario": result.selection.scenario_name,
            "signal_coverage": result.selection.signal_coverage,
            "matched_signals": list(result.selection.matched_signals),
        }
    if result.fallback_used:
        return {"result": "no_schema_fell_back_to_experimental"}
    return {"result": "no_schema"}


def _scenario_report(
    scenario: UserScenario,
    root: Path,
    *,
    offline: bool,
    max_tokens: int,
) -> dict[str, object]:
    transport = ExperimentalEchoTransport()
    engine_factory: EngineFactory | None = None
    mapping_factory: MappingFactory | None = None
    if offline:
        engine_factory = offline_engine_factory(transport)
        mapping_factory = offline_mapping_factory(transport)
    result = analyze_csv(
        scenario.path,
        scenario.note,
        engine_factory=engine_factory,
        mapping_factory=mapping_factory,
        max_tokens=max_tokens,
    )
    model = load_model_route(root / MODELS_CONFIG_NAME, "SYNTHESIS", {}).model
    return {
        "scenario_id": scenario.scenario_id,
        "title": scenario.title,
        "trigger": scenario.trigger,
        "input": str(scenario.path),
        "engineer_note": scenario.note,
        "mode": result.mode,
        "fallback_used": result.fallback_used,
        "triage": _triage_summary(result),
        "llm_calls": _llm_calls(result, model),
        "outcome": result.outcome.value,
        "suggested_next_action": result.suggested_next_action.value,
        "action_label": action_label(result.suggested_next_action),
        "explanation": result.explanation,
        "detail": result.detail,
        "analysis_performed": result.analysis_performed,
        "model_called": result.model_called,
        "evidence_count": len(result.evidence),
        "anomaly_count": sum(
            1 for item in result.evidence if item.kind.value == "SENSOR_ANOMALY"
        ),
        "hypotheses": _hypotheses(result.output),
        "draft_yaml_present": result.draft_yaml is not None,
        "final_user_result": {
            "outcome": result.outcome.value,
            "action_label": action_label(result.suggested_next_action),
            "explanation": result.explanation,
            "detail": result.detail,
        },
    }


def run_story(
    root: Path,
    *,
    offline: bool,
    max_tokens: int = 768,
) -> dict[str, object]:
    with TemporaryDirectory() as temp_dir:
        scenarios = build_scenarios(root, Path(temp_dir))
        reports = [
            _scenario_report(
                scenario, root, offline=offline, max_tokens=max_tokens
            )
            for scenario in scenarios
        ]
    return {
        "gate": "user-story",
        "mode": "offline" if offline else "live",
        "llm_calls_recorded": sum(len(item["llm_calls"]) for item in reports),
        "scenario_count": len(reports),
        "scenarios": reports,
    }


def _print_report(report: dict[str, object]) -> None:
    print(f"user-story [{report['mode']}] scenarios={report['scenario_count']}")
    for item in cast(list[dict[str, object]], report["scenarios"]):
        print(f"\n=== {item['scenario_id']} — {item['title']}")
        print(f"  trigger: {item['trigger']}")
        print(f"  mode: {item['mode']}  fallback_used={item['fallback_used']}")
        triage = cast(dict[str, object], item["triage"])
        print(f"  triage: {triage['result']}")
        calls = cast(list[dict[str, object]], item["llm_calls"])
        if not calls:
            print("  llm: no call")
        for call in calls:
            print(f"  llm: {call['purpose']} ({call['role']} {call['model']})")
            print(f"       response={json.dumps(call['response'], sort_keys=True)}")
        print(
            f"  outcome: {item['outcome']}  action: "
            f"{item['suggested_next_action']} ({item['action_label']})"
        )
        print(f"  user sees: {item['explanation']}")


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parents[2]
    offline = "--live" not in argv
    report = run_story(root, offline=offline)
    path = root / (OFFLINE_RESULT_NAME if offline else LIVE_RESULT_NAME)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _print_report(report)
    print(f"\nartifact={path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
