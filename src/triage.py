from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import duckdb

from src.config_loader import ScenarioConfig, load_relations
from src.core.column_profile import MalformedCsvError

DEFAULT_SEARCH_DIR = Path(__file__).resolve().parents[1] / "config" / "sensor_relations"
MIN_MATCHED_SIGNALS = 2
MIN_SIGNAL_COVERAGE = 0.5
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class NoMatchingProfile(LookupError):
    """Raised when no declared tool profile matches the supplied columns."""


@dataclass(frozen=True, slots=True)
class CsvInspection:
    headers: tuple[str, ...]
    row_count: int


@dataclass(frozen=True, slots=True)
class ProfileSelection:
    config_path: Path
    config_name: str
    scenario_name: str
    matched_signals: tuple[str, ...]
    signal_coverage: float


def _describe(csv_path: str | Path) -> tuple[str, ...]:
    connection = duckdb.connect(database=":memory:")
    try:
        rows = connection.execute(
            "DESCRIBE SELECT * FROM read_csv_auto(?)", [str(csv_path)]
        ).fetchall()
    except duckdb.Error as exc:
        raise MalformedCsvError(
            f"{Path(csv_path).name} is not readable as a CSV"
        ) from exc
    finally:
        connection.close()
    return tuple(str(row[0]) for row in rows)


def read_csv_headers(csv_path: str | Path) -> tuple[str, ...]:
    """Return the input columns without loading the file body."""
    return _describe(csv_path)


def inspect_csv(csv_path: str | Path) -> CsvInspection:
    """Return the header and a bounded row count, or fail as malformed.

    A file that DuckDB cannot parse raises :class:`MalformedCsvError`; the
    caller maps that to the ``INPUT_MALFORMED`` route rather than crashing.
    """
    headers = _describe(csv_path)
    connection = duckdb.connect(database=":memory:")
    try:
        counted = connection.execute(
            "SELECT count(*) FROM read_csv_auto(?)", [str(csv_path)]
        ).fetchone()
    except duckdb.Error as exc:
        raise MalformedCsvError(
            f"{Path(csv_path).name} is not readable as a CSV"
        ) from exc
    finally:
        connection.close()
    row_count = 0 if counted is None else int(counted[0])
    return CsvInspection(headers=headers, row_count=row_count)


def _normalized(text: str) -> str:
    return text.strip().casefold()


def _tokens(text: str) -> frozenset[str]:
    return frozenset(_TOKEN_PATTERN.findall(text.casefold()))


def _scenario_rank(
    scenario: ScenarioConfig,
    text_tokens: frozenset[str],
    header_set: set[str],
) -> tuple[float, float, int, int, int, tuple[str, ...]]:
    primary_names = [signal.name for signal in scenario.signals]
    primary_matched = tuple(
        name for name in primary_names if _normalized(name) in header_set
    )
    primary_coverage = (
        len(primary_matched) / len(primary_names) if primary_names else 0.0
    )
    declared = scenario.declared_signals or scenario.signals
    declared_names = [signal.name for signal in declared]
    matched = tuple(
        name for name in declared_names if _normalized(name) in header_set
    )
    coverage = len(matched) / len(declared_names) if declared_names else 0.0
    keyword_overlap = len(_tokens(scenario.candidate.claim) & text_tokens)
    return (
        primary_coverage,
        coverage,
        len(matched),
        keyword_overlap,
        len(primary_matched),
        primary_matched,
    )


def select_profile(
    headers: Iterable[str],
    engineer_text: str,
    search_dir: str | Path = DEFAULT_SEARCH_DIR,
) -> ProfileSelection:
    """Choose the declared scenario whose signals best match the input columns.

    Selection is deterministic: the highest signal coverage wins, then keyword
    overlap with the scenario claim, then the config/scenario name. A config
    with no declared scenario is not runnable and is skipped. No match is a
    fail-closed condition for the caller.
    """
    header_set = {_normalized(item) for item in headers}
    text_tokens = _tokens(engineer_text)
    best_rank: tuple[float, float, int, int, int, str, str] | None = None
    best_selection: ProfileSelection | None = None
    for config_path in sorted(Path(search_dir).glob("*.yaml")):
        relations = load_relations(config_path)
        for scenario_name in sorted(relations.scenarios):
            scenario = relations.scenarios[scenario_name]
            (
                primary_coverage,
                coverage,
                matched_count,
                keyword_overlap,
                primary_matched_count,
                matched,
            ) = _scenario_rank(scenario, text_tokens, header_set)
            if matched_count < MIN_MATCHED_SIGNALS or coverage < MIN_SIGNAL_COVERAGE:
                continue
            rank = (
                primary_coverage,
                coverage,
                matched_count,
                keyword_overlap,
                primary_matched_count,
                relations.name,
                scenario_name,
            )
            if best_rank is None or rank > best_rank:
                best_rank = rank
                best_selection = ProfileSelection(
                    config_path=config_path,
                    config_name=relations.name,
                    scenario_name=scenario_name,
                    matched_signals=matched,
                    signal_coverage=coverage,
                )
    if best_selection is None:
        raise NoMatchingProfile(
            "no configured tool profile matches the supplied columns"
        )
    return best_selection
