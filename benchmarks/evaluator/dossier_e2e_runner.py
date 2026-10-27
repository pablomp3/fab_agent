from __future__ import annotations

import json
import sys
from pathlib import Path

from benchmarks.evaluator.echo_transport import (
    EchoEvidenceTransport,
    offline_engine_factory,
)
from src.agents.differential_request import (
    CheckPrompt,
    build_cause_request,
)
from src.agents.proposal_request import (
    MAX_EVIDENCE_BYTES,
    MAX_REQUEST_BYTES,
    evidence_summary_bytes,
)
from src.config_loader import load_relations
from src.core.evidence import PayloadTooLarge
from src.core.types import Evidence, EvidenceKind
from src.dossier import DossierResult, analyze_dossier
from src.model_config import load_model_route
from src.schemas.models import RCAOutputModel
from src.triage import ProfileSelection

MODELS_CONFIG_NAME = "config/models.yaml"
PROCESSED_CSV = "benchmarks/datasets/phm2018/processed/01_M02_DC_score.csv"
RESULT_NAME = "benchmarks/evaluator/results/e2e_phm_check.json"
OFFLINE_RESULT_NAME = "benchmarks/evaluator/results/e2e_phm_check_offline.json"
SCALING_RESULT_NAME = "benchmarks/evaluator/results/e2e_payload_scaling.json"
ENGINEER_NOTE = (
    "Ion mill alarm during an RF run. Flowcool loop readings look abnormal; "
    "please isolate the cooling subsystem and tell me if a physical cause is supported."
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _hypotheses(output: RCAOutputModel) -> list[dict[str, object]]:
    return [
        {
            "hypothesis_class": item.hypothesis_class,
            "status": item.status.value,
            "root_cause": item.root_cause.value,
            "veto_reason": item.veto_reason,
        }
        for item in output.hypotheses
    ]


def _measure_request(
    evidence: tuple[Evidence, ...],
    checks: tuple[CheckPrompt, ...],
    context: str,
    max_tokens: int,
) -> tuple[int, int | None, bool]:
    models_config = _project_root() / MODELS_CONFIG_NAME
    model = load_model_route(models_config, "SYNTHESIS", {}).model
    evidence_bytes = evidence_summary_bytes(evidence)
    try:
        body = build_cause_request(
            model, evidence, checks, max_tokens, context=context
        )
    except PayloadTooLarge as exc:
        if exc.limit_bytes == MAX_EVIDENCE_BYTES:
            return evidence_bytes, None, False
        return evidence_bytes, exc.actual_bytes, False
    ok = evidence_bytes <= MAX_EVIDENCE_BYTES and len(body) <= MAX_REQUEST_BYTES
    return evidence_bytes, len(body), ok


def _scenario_checks(selection: ProfileSelection) -> tuple[CheckPrompt, ...]:
    relations = load_relations(selection.config_path)
    return tuple(
        CheckPrompt(
            check_id=check_id,
            label=scenario.candidate.claim,
            primary=tuple(sorted(scenario.predicate_config.primary_signals)),
            stay_normal=tuple(
                sorted(scenario.predicate_config.forbidden_anomaly_signals)
            ),
        )
        for check_id, scenario in relations.scenarios.items()
    )


def run_e2e(
    *,
    offline: bool,
    csv_relative: str = PROCESSED_CSV,
    max_tokens: int = 768,
) -> dict[str, object]:
    root = _project_root()
    transport = EchoEvidenceTransport()
    factory = offline_engine_factory(transport) if offline else None
    kwargs = {} if factory is None else {"engine_factory": factory}
    result: DossierResult = analyze_dossier(
        root / csv_relative, ENGINEER_NOTE, max_tokens=max_tokens, **kwargs
    )
    anomalies = [
        item for item in result.evidence if item.kind is EvidenceKind.SENSOR_ANOMALY
    ]
    request_bytes: int | None = None
    evidence_bytes = 0
    payload_ok = False
    if result.selection is not None:
        evidence_bytes, request_bytes, payload_ok = _measure_request(
            result.evidence,
            _scenario_checks(result.selection),
            result.engineer_note,
            max_tokens,
        )
    selection = result.selection
    model = load_model_route(root / MODELS_CONFIG_NAME, "SYNTHESIS", {}).model
    return {
        "gate": "W5.5",
        "case_id": "phm2018_flowcool",
        "mode": "offline" if offline else "live",
        "input": csv_relative,
        "model": model,
        "llm_calls": 0 if offline else 1,
        "selected_config": None if selection is None else selection.config_name,
        "selected_scenario": None if selection is None else selection.scenario_name,
        "signal_coverage": None if selection is None else selection.signal_coverage,
        "engineer_note_chars": len(result.engineer_note),
        "evidence_count": len(result.evidence),
        "anomaly_count": len(anomalies),
        "evidence_bytes": evidence_bytes,
        "evidence_limit_bytes": MAX_EVIDENCE_BYTES,
        "request_bytes": request_bytes,
        "request_limit_bytes": MAX_REQUEST_BYTES,
        "payload_ok": payload_ok,
        "outcome": result.outcome.value,
        "detail": result.detail,
        "analysis_performed": result.analysis_performed,
        "model_called": result.model_called,
        "any_supported": any(
            item.status.value == "SUPPORTED" for item in result.output.hypotheses
        ),
        "confidence": result.output.confidence.value,
        "suggested_next_action": result.output.suggested_next_action.value,
        "required_next_checks": list(result.output.required_next_checks),
        "hypotheses": _hypotheses(result.output),
    }


def _scaling_evidence(channels: int) -> tuple[Evidence, ...]:
    return tuple(
        Evidence(
            evidence_id=f"EV_SCALE_{index:03d}",
            kind=EvidenceKind.SENSOR_NOMINAL,
            signal=f"channel_{index:03d}",
            statistic="approx_robust_z_max",
            value=0.42,
            unit=None,
            window=(1, 1000),
            provenance=f"scaling_probe rows 1-1000 ({1000} observations)",
            computed_by="scaling_probe@v1",
            summary=(
                f"channel_{index:03d}: approximate maximum robust MAD z-score 0.42."
            ),
            window_basis="row:scaling_probe",
        )
        for index in range(channels)
    )


def run_scaling(max_tokens: int = 256) -> dict[str, object]:
    points: list[dict[str, object]] = []
    for channels in (1, 2, 4, 6, 8, 10, 12, 14, 16, 20):
        evidence_bytes, request_bytes, payload_ok = _measure_request(
            _scaling_evidence(channels),
            (
                CheckPrompt(
                    check_id="scale",
                    label="Scaling probe",
                    primary=("channel_000",),
                    stay_normal=(),
                ),
            ),
            "short engineer note",
            max_tokens,
        )
        points.append(
            {
                "channels": channels,
                "evidence_bytes": evidence_bytes,
                "evidence_ok": evidence_bytes <= MAX_EVIDENCE_BYTES,
                "request_bytes": request_bytes,
                "payload_ok": payload_ok,
            }
        )
    return {
        "gate": "W5.5",
        "probe": "single_request_channel_scaling",
        "evidence_limit_bytes": MAX_EVIDENCE_BYTES,
        "request_limit_bytes": MAX_REQUEST_BYTES,
        "max_tokens": max_tokens,
        "points": points,
    }


def main(argv: list[str]) -> int:
    root = _project_root()
    offline = "--live" not in argv
    if "--scaling" in argv:
        report = run_scaling()
        path = root / SCALING_RESULT_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"W5.5 payload scaling written to {path}")
        for point in report["points"]:
            print(
                f"  channels={point['channels']} "
                f"evidence_bytes={point['evidence_bytes']} "
                f"evidence_ok={point['evidence_ok']} "
                f"request_bytes={point['request_bytes']} "
                f"payload_ok={point['payload_ok']}"
            )
        return 0
    report = run_e2e(offline=offline)
    path = root / (OFFLINE_RESULT_NAME if offline else RESULT_NAME)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"W5.5 E2E [{report['mode']}] config={report['selected_config']} "
        f"scenario={report['selected_scenario']} evidence={report['evidence_count']} "
        f"anomalies={report['anomaly_count']} request_bytes={report['request_bytes']} "
        f"payload_ok={report['payload_ok']} "
        f"action={report['suggested_next_action']} "
        f"outcome={report['outcome']} "
        f"any_supported={report['any_supported']}"
    )
    print(f"artifact={path}")
    if report["outcome"] == "INPUT_UNREADABLE":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
