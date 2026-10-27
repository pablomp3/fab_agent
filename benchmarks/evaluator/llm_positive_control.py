from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path

from benchmarks.synthetic_twin.generate_twin import generate_positive_control
from src.agents.model_transport import CompletionResponse, ModelTransport
from src.agents.rca_engine import create_rca_engine
from src.config_loader import load_relations
from src.core.duckdb_exec import extract_evidence
from src.core.types import Verdict
from src.model_config import ModelRoute, load_model_route
from src.schemas.models import RCAOutputModel

POSITIVE_CONFIG_NAME = "benchmarks/evaluator/fixtures/v1/synthetic_twin_positive.yaml"
MODELS_CONFIG_NAME = "config/models.yaml"
RESULT_NAME = "benchmarks/evaluator/results/w4_positive_check.json"
OFFLINE_RESULT_NAME = "benchmarks/evaluator/results/w4_positive_check_offline.json"
STABILITY_RESULT_NAME = "benchmarks/evaluator/results/w4_positive_stability.json"


class _StaticProposalTransport:
    """Offline transport that returns a schema-valid proposal citing IDs."""

    def __init__(self, citations: tuple[str, ...]) -> None:
        self._citations = citations

    def list_models(self, route: ModelRoute, api_key: str) -> tuple[str, ...]:
        return (route.model,)

    def complete(
        self, route: ModelRoute, api_key: str, body: bytes
    ) -> CompletionResponse:
        content = json.dumps(
            {
                "hypotheses": [
                    {
                        "claim": "RF Generator Arc",
                        "root_cause": "equipment_fault",
                        "failure_mode": "rf_power_arc",
                        "mechanism": "reflectometer excursion with corroboration",
                        "hypothesis_class": "equipment_fault",
                        "cited_evidence": list(self._citations),
                    }
                ]
            }
        )
        return CompletionResponse(content, "stop")


def _hypothesis_report(output: RCAOutputModel) -> list[dict[str, object]]:
    return [
        {
            "hypothesis_class": item.hypothesis_class,
            "root_cause": item.root_cause.value,
            "status": item.status.value,
            "veto_reason": item.veto_reason,
            "model_narrative_present": item.model_narrative is not None,
        }
        for item in output.hypotheses
    ]


def run_positive_check(
    root: Path,
    *,
    environment: Mapping[str, str] | None = None,
    transport: ModelTransport | None = None,
    offline: bool = False,
    max_tokens: int = 768,
) -> dict[str, object]:
    """Generate B4e, extract evidence, run the RCA engine, and return a
    sanitized report. Live mode calls the provider; offline mode uses a static
    transport that cites the primary anomaly. Neither mode logs keys or text."""
    project_root = Path(__file__).resolve().parents[2]
    positive_config = project_root / POSITIVE_CONFIG_NAME
    generate_positive_control(root, positive_config)
    scenario = load_relations(positive_config).scenarios["B4e"]
    evidence = extract_evidence(
        root / "benchmarks/synthetic_twin/cases/B4e/telemetry.csv", scenario.signals
    )
    route = load_model_route(
        project_root / MODELS_CONFIG_NAME, "SYNTHESIS", environment
    )

    active_environment = environment
    active_transport: ModelTransport | None = transport
    if offline:
        required = (
            scenario.predicate_config.primary_signals
            | scenario.predicate_config.corroboration_signals
        )
        citations = tuple(
            item.evidence_id for item in evidence if item.signal in required
        )
        active_transport = _StaticProposalTransport(citations)
        active_environment = {"NEBIUS_API_KEY": "offline-fixture-key"}

    engine = create_rca_engine(
        scenario.predicate_config,
        scenario.rules,
        config_path=project_root / MODELS_CONFIG_NAME,
        environment=active_environment,
        transport=active_transport,
    )
    model = engine.generate_hypotheses(
        evidence,
        max_tokens=max_tokens,
        supported_action=scenario.supported_action,
        candidate=scenario.candidate,
    )

    return {
        "gate": "W4",
        "case_id": "B4e",
        "mode": "offline" if offline else "live",
        "model": route.model,
        "provider_base_url": route.base_url,
        "llm_calls": 0 if offline else 1,
        "max_tokens": max_tokens,
        "evidence_count": len(evidence),
        "failure_category": (
            engine.last_failure_category.value
            if engine.last_failure_category is not None
            else None
        ),
        "finish_reason": (
            engine.last_finish_reason.value
            if engine.last_finish_reason is not None
            else None
        ),
        "validation_details": (
            [item.value for item in engine.last_validation_details]
            if engine.last_validation_details is not None
            else None
        ),
        "any_supported": any(
            item.status is Verdict.SUPPORTED for item in model.hypotheses
        ),
        "confidence": model.confidence.value,
        "suggested_next_action": model.suggested_next_action.value,
        "hypotheses": _hypothesis_report(model),
    }


def _attempt_summary(report: dict[str, object]) -> dict[str, object]:
    statuses: list[str] = []
    hypotheses = report["hypotheses"]
    if isinstance(hypotheses, list):
        for item in hypotheses:
            if isinstance(item, dict):
                statuses.append(str(item.get("status")))
    narrative_present: list[bool] = []
    if isinstance(hypotheses, list):
        for item in hypotheses:
            if isinstance(item, dict):
                narrative_present.append(bool(item.get("model_narrative_present")))
    return {
        "any_supported": bool(report["any_supported"]),
        "statuses": statuses,
        "model_narrative_present": narrative_present,
        "failure_category": report["failure_category"],
        "finish_reason": report["finish_reason"],
    }


def run_stability(
    root: Path,
    attempts: int,
    *,
    environment: Mapping[str, str] | None = None,
    transport: ModelTransport | None = None,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Run repeated live B4e attempts and summarize the sanitized outcomes.

    The provider is not deterministic even at zero temperature, so a single
    success is not a stability claim. This records every attempt so any success
    rate traces to a measured artifact."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    reports = [
        run_positive_check(root, environment=environment, transport=transport)
        for _ in range(attempts)
    ]
    attempts_summary = [_attempt_summary(report) for report in reports]
    supported = sum(1 for item in attempts_summary if item["any_supported"])
    summary: dict[str, object] = {
        "gate": "W4",
        "case_id": "B4e",
        "mode": "live",
        "model": reports[0]["model"],
        "attempts": attempts,
        "supported_count": supported,
        "supported_rate": supported / attempts,
        "per_attempt": attempts_summary,
    }
    return summary, reports


def _parse_repeat(argv: list[str]) -> int:
    if "--repeat" not in argv:
        return 1
    index = argv.index("--repeat")
    if index + 1 >= len(argv):
        raise ValueError("--repeat requires an integer argument")
    return int(argv[index + 1])


def main(argv: list[str]) -> int:
    project_root = Path(__file__).resolve().parents[2]
    offline = "--offline" in argv
    repeat = _parse_repeat(argv)
    if repeat > 1:
        if offline:
            print("stability mode requires live calls; omit --offline")
            return 2
        summary, reports = run_stability(project_root, repeat)
        supported_reports = [item for item in reports if item["any_supported"]]
        chosen = supported_reports[-1] if supported_reports else reports[-1]
        result_path = project_root / RESULT_NAME
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(chosen, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        stability_path = project_root / STABILITY_RESULT_NAME
        stability_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(
            f"W4 stability [live] case=B4e attempts={summary['attempts']} "
            f"supported={summary['supported_count']} "
            f"rate={summary['supported_rate']:.2f}"
        )
        return 0
    report = run_positive_check(project_root, offline=offline)
    result_path = project_root / (OFFLINE_RESULT_NAME if offline else RESULT_NAME)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    supported = "SUPPORTED" if report["any_supported"] else "NOT_SUPPORTED"
    print(
        f"W4 positive check [{report['mode']}] case={report['case_id']} "
        f"model={report['model']} any_supported={report['any_supported']} "
        f"verdict={supported} confidence={report['confidence']} "
        f"action={report['suggested_next_action']} "
        f"failure={report['failure_category']} finish={report['finish_reason']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
