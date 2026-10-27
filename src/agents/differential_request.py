"""Bounded cause-finder and challenge requests.

The cause finder may only name a saved check or ``"new"`` and cite evidence IDs
that Python already produced. The challenge check may only ask for one signal
expectation in a fixed, machine-checkable form. Neither response carries a
status, action, root-cause category, or free-form verdict.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from src.agents.proposal_request import (
    MAX_EVIDENCE_BYTES,
    MAX_MAX_TOKENS,
    MAX_REQUEST_BYTES,
    evidence_summary_bytes,
)
from src.core.evidence import EvidenceStore, PayloadTooLarge
from src.core.types import Evidence, EvidenceKind

CAUSE_SCHEMA_NAME = "fabagent_causes"
CHALLENGE_SCHEMA_NAME = "fabagent_challenge"
MAX_CAUSE_PROPOSALS = 5
MAX_UNCONFIGURED_CAUSES = 3
DEFAULT_CAUSE_MAX_TOKENS = 384
DEFAULT_CHALLENGE_MAX_TOKENS = 256

CAUSE_SYSTEM_PROMPT = (
    "Semiconductor cause finder. You are given bounded evidence and the saved "
    "fault checks for this tool. Propose possible causes as JSON per the schema. "
    "Use a saved check id when it matches, or the exact string 'new' when no "
    "saved check matches. Cite only evidence_id values from the payload. Do not "
    "return a root-cause category, failure mode, mechanism, status, or action; "
    "Python owns those. Empty array only if no cause is plausible."
)
CHALLENGE_SYSTEM_PROMPT = (
    "Semiconductor disconfirmation checker. Given one saved check and bounded "
    "evidence, propose one test that could disconfirm the check. Return JSON per "
    "the schema. The 'expected' field must be one of the exact enum values "
    "provided, either '<SIGNAL> unusual' or '<SIGNAL> normal', using a signal "
    "name from the payload. Cite only the exact "
    "evidence_id values from the evidence array; do not use signal names. "
    "Do not return a status or action."
)


class CauseProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    check: str = Field(min_length=1)
    title: str = Field(min_length=1)
    why: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)


class CauseEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    possible_causes: list[CauseProposal] = Field(
        default_factory=list, max_length=MAX_CAUSE_PROPOSALS
    )


class ChallengeProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    challenge: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)
    expected: str = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class CheckPrompt:
    check_id: str
    label: str
    primary: tuple[str, ...]
    stay_normal: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValidatedCause:
    check: str
    title: str
    why: str
    cited_evidence: tuple[str, ...]
    resolved_evidence: tuple[Evidence, ...]

    @property
    def is_new(self) -> bool:
        return self.check == "new"


@dataclass(frozen=True, slots=True)
class ValidatedChallenge:
    text: str
    expected: str
    cited_evidence: tuple[str, ...]
    target_signal: str
    expected_unusual: bool
    expectation_met: bool


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


def _bounded_evidence(evidence: tuple[Evidence, ...]) -> list[dict[str, object]]:
    evidence_bytes = evidence_summary_bytes(evidence)
    if evidence_bytes > MAX_EVIDENCE_BYTES:
        raise PayloadTooLarge(
            f"evidence summary is {evidence_bytes} bytes; "
            f"limit is {MAX_EVIDENCE_BYTES}",
            actual_bytes=evidence_bytes,
            limit_bytes=MAX_EVIDENCE_BYTES,
        )
    return _evidence_items(evidence)


def _request_body(
    model: str,
    *,
    system_prompt: str,
    schema_name: str,
    schema: Mapping[str, object],
    user_object: dict[str, object],
    max_tokens: int,
) -> bytes:
    if isinstance(max_tokens, bool) or not 1 <= max_tokens <= MAX_MAX_TOKENS:
        raise ValueError(f"max_tokens must be between 1 and {MAX_MAX_TOKENS}")
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
                    "name": schema_name,
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


def build_cause_request(
    model: str,
    evidence: tuple[Evidence, ...],
    checks: tuple[CheckPrompt, ...],
    max_tokens: int = DEFAULT_CAUSE_MAX_TOKENS,
    context: str | None = None,
) -> bytes:
    evidence_items = _bounded_evidence(evidence)
    check_items = [
        {
            "id": item.check_id,
            "label": item.label,
            "must_be_unusual": list(item.primary),
            "must_stay_normal": list(item.stay_normal),
        }
        for item in checks
    ]
    check_ids = [item.check_id for item in checks]
    schema = {
        "type": "object",
        "properties": {
            "possible_causes": {
                "type": "array",
                "maxItems": MAX_CAUSE_PROPOSALS,
                "items": {
                    "type": "object",
                    "properties": {
                        "check": {
                            "type": "string",
                            "enum": [*check_ids, "new"],
                        },
                        "title": {"type": "string"},
                        "why": {"type": "string"},
                        "evidence": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                        },
                    },
                    "required": ["check", "title", "why", "evidence"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["possible_causes"],
        "additionalProperties": False,
    }
    user_object: dict[str, object] = {
        "evidence": evidence_items,
        "checks": check_items,
    }
    if context:
        user_object["context"] = context
    return _request_body(
        model,
        system_prompt=CAUSE_SYSTEM_PROMPT,
        schema_name=CAUSE_SCHEMA_NAME,
        schema=schema,
        user_object=user_object,
        max_tokens=max_tokens,
    )


def build_challenge_request(
    model: str,
    evidence: tuple[Evidence, ...],
    check: CheckPrompt,
    max_tokens: int = DEFAULT_CHALLENGE_MAX_TOKENS,
) -> bytes:
    evidence_items = _bounded_evidence(evidence)
    signals = sorted(
        {item.signal for item in evidence if item.signal is not None}
    )
    expected_values = [f"{signal} unusual" for signal in signals]
    expected_values.extend(f"{signal} normal" for signal in signals)
    schema = {
        "type": "object",
        "properties": {
            "challenge": {"type": "string"},
            "evidence": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "expected": {"type": "string", "enum": expected_values},
        },
        "required": ["challenge", "evidence", "expected"],
        "additionalProperties": False,
    }
    user_object: dict[str, object] = {
        "evidence": evidence_items,
        "check": {
            "id": check.check_id,
            "label": check.label,
            "must_be_unusual": list(check.primary),
            "must_stay_normal": list(check.stay_normal),
        },
        "signals": signals,
    }
    return _request_body(
        model,
        system_prompt=CHALLENGE_SYSTEM_PROMPT,
        schema_name=CHALLENGE_SCHEMA_NAME,
        schema=schema,
        user_object=user_object,
        max_tokens=max_tokens,
    )


def validate_causes(
    envelope: CauseEnvelope,
    allowed_check_ids: frozenset[str],
    store: EvidenceStore,
) -> tuple[tuple[ValidatedCause, ...], int]:
    """Keep only causes naming a saved check or ``new`` with resolved evidence."""
    causes: list[ValidatedCause] = []
    discarded = 0
    seen_saved: set[str] = set()
    seen_new: set[str] = set()
    for proposal in envelope.possible_causes:
        if proposal.check != "new" and proposal.check not in allowed_check_ids:
            discarded += 1
            continue
        evidence_ids = tuple(dict.fromkeys(proposal.evidence))
        resolved, unresolved = store.resolve_all(evidence_ids)
        if unresolved or not resolved:
            discarded += 1
            continue
        if proposal.check == "new":
            key = proposal.title.strip().casefold()
            if key in seen_new or len(seen_new) >= MAX_UNCONFIGURED_CAUSES:
                discarded += 1
                continue
            seen_new.add(key)
        else:
            if proposal.check in seen_saved:
                discarded += 1
                continue
            seen_saved.add(proposal.check)
        causes.append(
            ValidatedCause(
                check=proposal.check,
                title=proposal.title,
                why=proposal.why,
                cited_evidence=evidence_ids,
                resolved_evidence=resolved,
            )
        )
    return tuple(causes), discarded


def _parse_expected(
    expected: str, signal_names: tuple[str, ...]
) -> tuple[str, bool] | None:
    text = expected.strip().casefold()
    for signal in sorted(signal_names, key=len, reverse=True):
        prefix = signal.casefold()
        if not text.startswith(prefix):
            continue
        suffix = text[len(prefix) :]
        if suffix and suffix[0] not in " \t:-.":
            continue
        remainder = suffix.strip(" \t:-.")
        if remainder in {"unusual", "anomaly", "anomalous", "abnormal", "moved"}:
            return signal, True
        if remainder in {"normal", "nominal", "quiet", "steady", "unchanged"}:
            return signal, False
    return None


def validate_challenge(
    proposal: ChallengeProposal,
    evidence: tuple[Evidence, ...],
    store: EvidenceStore,
    *,
    primary_signals: frozenset[str] = frozenset(),
) -> ValidatedChallenge | None:
    """Evaluate a challenge expectation against Python evidence.

    A challenge with unresolved evidence, an unknown signal, or an unrecognised
    expectation is discarded. A challenge cannot target a signal that is
    already a required primary signal: predicting that the evidence is normal
    would be a trivial, arbitrary downgrade. It can never upgrade a result.
    """
    evidence_ids = tuple(dict.fromkeys(proposal.evidence))
    _, unresolved = store.resolve_all(evidence_ids)
    if unresolved:
        return None
    signal_names = tuple(
        sorted({item.signal for item in evidence if item.signal is not None})
    )
    parsed = _parse_expected(proposal.expected, signal_names)
    if parsed is None:
        return None
    signal, expected_unusual = parsed
    if signal in primary_signals and not expected_unusual:
        # Predicting that an already-required signal is normal is not a
        # disconfirming test; it would let the model downgrade any confirmed
        # check arbitrarily.
        return None
    records = tuple(item for item in evidence if item.signal == signal)
    if not records:
        return None
    has_anomaly = any(item.kind is EvidenceKind.SENSOR_ANOMALY for item in records)
    has_missing = any(item.kind is EvidenceKind.MISSING_CHANNEL for item in records)
    if has_missing:
        return None
    met = has_anomaly if expected_unusual else not has_anomaly
    return ValidatedChallenge(
        text=proposal.challenge,
        expected=proposal.expected,
        cited_evidence=evidence_ids,
        target_signal=signal,
        expected_unusual=expected_unusual,
        expectation_met=met,
    )
