"""Process-local counters for live model and research calls.

Only real HTTP calls are recorded. The offline fixtures use separate
transports, so a key-free demo does not inflate the counters. The counters are
intentionally process-local: the hosted app shows "this session" and "since
server start" without writing shared state to disk.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True, slots=True)
class UsageCount:
    provider: str
    model: str
    role: str
    calls: int


class UsageTracker:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counts: Counter[tuple[str, str, str]] = Counter()

    def record(self, *, provider: str, model: str, role: str) -> None:
        key = (provider.strip(), model.strip(), role.strip())
        with self._lock:
            self._counts[key] += 1

    def snapshot(self) -> tuple[UsageCount, ...]:
        with self._lock:
            items = sorted(self._counts.items())
        return tuple(
            UsageCount(provider=provider, model=model, role=role, calls=calls)
            for (provider, model, role), calls in items
        )

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()


USAGE = UsageTracker()

__all__ = ["USAGE", "UsageCount", "UsageTracker"]
