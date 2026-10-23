from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

import duckdb

MAD_NORMALIZATION = 0.6744897501960817
MAX_PROFILE_COLUMNS = 60


class MalformedCsvError(ValueError):
    """Raised when DuckDB cannot parse a CSV export (encoding/delimiter/etc.)."""


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


@dataclass(frozen=True, slots=True)
class ColumnProfile:
    """Bounded, raw-value-free summary of one CSV column.

    Only counts and robust summary statistics leave this record; no telemetry
    value is retained. A column that cannot cast to a number has
    ``numeric_count`` of zero and is not a candidate signal.
    """

    name: str
    declared_type: str
    row_count: int
    numeric_count: int
    minimum: float | None
    median: float | None
    maximum: float | None
    mad: float | None

    @property
    def numeric(self) -> bool:
        return self.numeric_count > 0

    @property
    def null_fraction(self) -> float:
        if self.row_count == 0:
            return 0.0
        return (self.row_count - self.numeric_count) / self.row_count

    @property
    def constant(self) -> bool:
        return self.minimum is None or self.minimum == self.maximum

    @property
    def usable(self) -> bool:
        return self.numeric and not self.constant


def _summary_query(column: str) -> str:
    quoted = _quote_identifier(column)
    return f"""
        WITH vals AS (
            SELECT try_cast({quoted} AS DOUBLE) AS v FROM read_csv_auto(?)
        ),
        filtered AS (SELECT v FROM vals WHERE v IS NOT NULL),
        centers AS (SELECT approx_quantile(v, 0.5) AS med FROM filtered)
        SELECT
            (SELECT count(*) FROM vals) AS total,
            (SELECT count(*) FROM filtered) AS numeric_count,
            (SELECT min(v) FROM filtered) AS low_value,
            (SELECT max(v) FROM filtered) AS high_value,
            (SELECT med FROM centers) AS center,
            (
                SELECT approx_quantile(abs(v - (SELECT med FROM centers)), 0.5)
                FROM filtered
            ) AS mad
    """


def profile_columns(
    csv_path: str | Path, max_columns: int = MAX_PROFILE_COLUMNS
) -> tuple[ColumnProfile, ...]:
    """Profile the first ``max_columns`` columns without loading raw values.

    DuckDB infers each column's declared type; the numeric cast is attempted
    per column so a VARCHAR export with numbers is still a candidate. The
    result is deterministic for a given file.
    """
    path = Path(csv_path)
    result: list[ColumnProfile] = []
    connection = duckdb.connect(database=":memory:")
    try:
        try:
            describe_rows = cast(
                list[tuple[object, ...]],
                connection.execute(
                    "DESCRIBE SELECT * FROM read_csv_auto(?)", [str(path)]
                ).fetchall(),
            )
        except duckdb.Error as exc:
            raise MalformedCsvError(
                f"{path.name} is not readable as a CSV"
            ) from exc
        for row in describe_rows[:max_columns]:
            name = str(row[0])
            declared_type = str(row[1])
            stats = cast(
                list[tuple[object, ...]],
                connection.execute(_summary_query(name), [str(path)]).fetchall(),
            )[0]
            numeric_count = int(cast(int, stats[1]))
            result.append(
                ColumnProfile(
                    name=name,
                    declared_type=declared_type,
                    row_count=int(cast(int, stats[0])),
                    numeric_count=numeric_count,
                    minimum=None if stats[2] is None else float(cast(float, stats[2])),
                    median=None if stats[4] is None else float(cast(float, stats[4])),
                    maximum=None if stats[3] is None else float(cast(float, stats[3])),
                    mad=None if stats[5] is None else float(cast(float, stats[5])),
                )
            )
    finally:
        connection.close()
    return tuple(result)


def usable_candidates(
    profiles: tuple[ColumnProfile, ...],
) -> tuple[ColumnProfile, ...]:
    """Return numeric, non-constant columns in declared order."""
    return tuple(profile for profile in profiles if profile.usable)
