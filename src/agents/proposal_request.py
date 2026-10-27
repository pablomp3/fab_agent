from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field

from src.core.evidence import PayloadTooLarge
from src.core.types import Evidence
from src.schemas.models import RootCauseCategory

MAX_EVIDENCE_BYTES = 2048
MAX_REQUEST_BYTES = 8192
MAX_RESPONSE_BYTES = 8192
DEFAULT_MAX_TOKENS = 256
MAX_MAX_TOKENS = 768
SYSTEM_PROMPT = (
    "Semiconductor root-cause analyst. SENSOR_ANOMALY means a signal deviated "
    "above threshold. Propose plausible root-cause hypotheses as JSON per the "
    "schema, citing the evidence_id of every anomaly that supports them. No extra "
    "fields, status, or action. Empty array only if none plausible."
)


class HypothesisProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    claim: str = Field(min_length=1)
    root_cause: RootCauseCategory
    failure_mode: str = Field(min_length=1)
    mechanism: str = Field(min_length=1)
    hypothesis_class: str = Field(min_length=1)
    cited_evidence: list[str] = Field(min_length=1)


class ProposalEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    hypotheses: list[HypothesisProposal]


def _evidence_items(evidence: tuple[Evidence, ...]) -> list[dict[str, object]]:
    return [
        {
            "evidence_id": item.evidence_id,
            "kind": item.kind.value,
            "signal": item.signal,
            "statistic": item.statistic,
            "value": item.value,
            "unit": item.unit,
            "window": item.window,
        }
        for item in evidence
    ]


def evidence_summary_bytes(evidence: tuple[Evidence, ...]) -> int:
    """Size of the evidence-only payload.

    The "<= 2 KB" bound applies to this evidence summary, not to the fixed
    system prompt and strict JSON schema that travel with it in the full HTTP
    request.
    """
    payload = json.dumps(
        {"evidence": _evidence_items(evidence)},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return len(payload.encode("utf-8"))


def build_proposal_request(
    model: str,
    evidence: tuple[Evidence, ...],
    hypothesis_classes: tuple[str, ...],
    max_tokens: int = DEFAULT_MAX_TOKENS,
    context: str | None = None,
) -> bytes:
    if isinstance(max_tokens, bool) or not 1 <= max_tokens <= MAX_MAX_TOKENS:
        raise ValueError(f"max_tokens must be between 1 and {MAX_MAX_TOKENS}")
    evidence_items = _evidence_items(evidence)
    evidence_bytes = evidence_summary_bytes(evidence)
    if evidence_bytes > MAX_EVIDENCE_BYTES:
        raise PayloadTooLarge(
            f"evidence summary is {evidence_bytes} bytes; "
            f"limit is {MAX_EVIDENCE_BYTES}",
            actual_bytes=evidence_bytes,
            limit_bytes=MAX_EVIDENCE_BYTES,
        )
    system_prompt = SYSTEM_PROMPT
    schema = {
        "type": "object",
        "properties": {
            "hypotheses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string"},
                        "root_cause": {
                            "type": "string",
                            "enum": [item.value for item in RootCauseCategory],
                        },
                        "failure_mode": {"type": "string"},
                        "mechanism": {"type": "string"},
                        "hypothesis_class": {
                            "type": "string",
                            "enum": list(hypothesis_classes),
                        },
                        "cited_evidence": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                        },
                    },
                    "required": [
                        "claim",
                        "root_cause",
                        "failure_mode",
                        "mechanism",
                        "hypothesis_class",
                        "cited_evidence",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["hypotheses"],
        "additionalProperties": False,
    }
    user_object: dict[str, object] = {"evidence": evidence_items}
    if context:
        user_object["context"] = context
    user_payload = json.dumps(user_object, ensure_ascii=False, separators=(",", ":"))
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "fabagent_proposals",
                    "strict": True,
                    "schema": schema,
                },
            },
            "chat_template_kwargs": {"enable_thinking": False},
            "temperature": 0,
            "max_tokens": max_tokens,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(body) > MAX_REQUEST_BYTES:
        raise PayloadTooLarge(
            f"model request is {len(body)} bytes; limit is {MAX_REQUEST_BYTES}",
            actual_bytes=len(body),
            limit_bytes=MAX_REQUEST_BYTES,
        )
    return body
