from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from hashlib import sha256

from src.core.types import Evidence


class PayloadTooLarge(ValueError):
    """Raised when the evidence summary exceeds its configured byte budget."""

    def __init__(
        self,
        message: str,
        *,
        actual_bytes: int | None = None,
        limit_bytes: int | None = None,
    ) -> None:
        super().__init__(message)
        self.actual_bytes = actual_bytes
        self.limit_bytes = limit_bytes


class EvidenceStore:
    def __init__(self, evidence: Iterable[Evidence] = ()) -> None:
        self._by_id: dict[str, Evidence] = {}
        for item in evidence:
            existing = self._by_id.get(item.evidence_id)
            if existing is not None and existing != item:
                raise ValueError(f"duplicate evidence id: {item.evidence_id}")
            self._by_id[item.evidence_id] = item

    def __iter__(self) -> Iterator[Evidence]:
        return iter(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)

    def resolve_all(
        self, evidence_ids: Iterable[str]
    ) -> tuple[tuple[Evidence, ...], tuple[str, ...]]:
        resolved: list[Evidence] = []
        unresolved: list[str] = []
        for evidence_id in evidence_ids:
            item = self._by_id.get(evidence_id)
            if item is None:
                unresolved.append(evidence_id)
            else:
                resolved.append(item)
        return tuple(resolved), tuple(unresolved)


def make_evidence_id(identity: str) -> str:
    digest = sha256(identity.encode("utf-8")).hexdigest()[:16].upper()
    return f"EV_{digest}"


def build_llm_payload(store: EvidenceStore, max_bytes: int = 2048) -> str:
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    items = [
        {
            "evidence_id": item.evidence_id,
            "kind": item.kind.value,
            "signal": item.signal,
            "statistic": item.statistic,
            "value": item.value,
            "unit": item.unit,
            "window": item.window,
            "provenance": item.provenance,
            "computed_by": item.computed_by,
            "summary": item.summary,
        }
        for item in store
    ]
    payload = json.dumps({"evidence": items}, ensure_ascii=False, separators=(",", ":"))
    actual_bytes = len(payload.encode("utf-8"))
    if actual_bytes > max_bytes:
        raise PayloadTooLarge(
            f"evidence payload is {actual_bytes} bytes; limit is {max_bytes}",
            actual_bytes=actual_bytes,
            limit_bytes=max_bytes,
        )
    return payload
