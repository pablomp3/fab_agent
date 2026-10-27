"""Optional, bounded Tavily search for external troubleshooting references.

Tavily is a bonus integration, not a dependency of the verdict. The search is
only attempted for an inconclusive or experimental run, it sends signal names
and a short configured claim (never raw telemetry values or the engineer note),
and the returned URLs are displayed as external references. They are not
evidence and cannot change a Python-gated conclusion.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Protocol, cast
from urllib.error import URLError
from urllib.request import Request, urlopen

from src.core.types import Evidence, EvidenceKind

TAVILY_ENDPOINT = "https://api.tavily.com/search"
TAVILY_API_KEY_ENV = "TAVILY_API_KEY"
_MAX_RESULTS = 3
_MAX_RESPONSE_BYTES = 128_000


class TavilyError(RuntimeError):
    """Raised for a sanitized Tavily transport or response failure."""


@dataclass(frozen=True, slots=True)
class TavilyReference:
    title: str
    url: str
    snippet: str


class TavilySearch(Protocol):
    def search(
        self, query: str, max_results: int = _MAX_RESULTS
    ) -> tuple[TavilyReference, ...]: ...


def _mapping(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    raw = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in raw):
        return None
    return cast(dict[str, object], value)


class TavilyClient:
    """Minimal JSON client for the Tavily search endpoint."""

    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str = TAVILY_ENDPOINT,
        timeout_seconds: float = 15.0,
    ) -> None:
        if not api_key.strip():
            raise TavilyError("Tavily API key is empty")
        if not endpoint.startswith("https://"):
            raise TavilyError("Tavily endpoint must use HTTPS")
        self._api_key = api_key.strip()
        self._endpoint = endpoint
        self._timeout_seconds = timeout_seconds

    def search(
        self, query: str, max_results: int = _MAX_RESULTS
    ) -> tuple[TavilyReference, ...]:
        bounded_query = query.strip()
        if not bounded_query:
            raise TavilyError("Tavily query is empty")
        if isinstance(max_results, bool) or not 1 <= max_results <= _MAX_RESULTS:
            raise TavilyError(f"max_results must be between 1 and {_MAX_RESULTS}")
        body = json.dumps(
            {
                "api_key": self._api_key,
                "query": bounded_query,
                "search_depth": "basic",
                "max_results": max_results,
                "include_answer": False,
                "include_raw_content": False,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            self._endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                content = response.read(_MAX_RESPONSE_BYTES + 1)
        except (OSError, URLError) as exc:
            raise TavilyError("Tavily request failed") from exc
        if len(content) > _MAX_RESPONSE_BYTES:
            raise TavilyError("Tavily response exceeded its size limit")
        try:
            payload: object = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TavilyError("Tavily returned invalid JSON") from exc
        data = _mapping(payload)
        if data is None or not isinstance(data.get("results"), list):
            raise TavilyError("Tavily response has an invalid shape")
        references: list[TavilyReference] = []
        for item_obj in cast(list[object], data["results"]):
            item = _mapping(item_obj)
            if item is None:
                continue
            url = item.get("url")
            title = item.get("title")
            snippet = item.get("content")
            if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                continue
            references.append(
                TavilyReference(
                    title=title.strip() if isinstance(title, str) else url,
                    url=url,
                    snippet=snippet.strip() if isinstance(snippet, str) else "",
                )
            )
            if len(references) >= max_results:
                break
        return tuple(references)


def build_tavily_query(evidence: tuple[Evidence, ...], configured_claim: str) -> str:
    """Build a bounded query from anomaly signal names and a configured claim.

    Raw values, units, windows, and the engineer note are intentionally
    excluded. The query is only a retrieval hint, not evidence.
    """
    signals: list[str] = []
    for item in evidence:
        if item.kind is not EvidenceKind.SENSOR_ANOMALY or not item.signal:
            continue
        if item.signal not in signals:
            signals.append(item.signal)
        if len(signals) >= 3:
            break
    subject = " ".join(signals) if signals else configured_claim.strip()
    if not subject:
        subject = "semiconductor tool anomaly"
    return f"semiconductor manufacturing troubleshooting {subject}"


def tavily_client_from_environment(
    environment: dict[str, str] | None = None,
) -> TavilySearch | None:
    """Return a client only when the server has a configured key."""
    selected = os.environ if environment is None else environment
    api_key = selected.get(TAVILY_API_KEY_ENV, "").strip()
    if not api_key:
        return None
    return TavilyClient(api_key)


__all__ = [
    "TAVILY_API_KEY_ENV",
    "TavilyClient",
    "TavilyError",
    "TavilyReference",
    "TavilySearch",
    "build_tavily_query",
    "tavily_client_from_environment",
]
