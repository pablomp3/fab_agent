from __future__ import annotations

from pathlib import Path
from typing import cast

import duckdb

from src.core.evidence import make_evidence_id
from src.core.types import Evidence, EvidenceKind, SignalSpec

_MAD_NORMALIZATION = 0.6744897501960817


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _missing_evidence(
    spec: SignalSpec,
    provenance: str,
    *,
    computed_by: str,
    provenance_tag: str | None,
) -> Evidence:
    kind = EvidenceKind.MISSING_CHANNEL
    if spec.threshold_source is not None:
        provenance = f"{provenance} source={spec.threshold_source}"
    if provenance_tag is not None:
        provenance = f"{provenance} tag={provenance_tag}"
    return Evidence(
        evidence_id=make_evidence_id(f"{kind.value}\0{spec.name}\0{provenance}"),
        kind=kind,
        signal=spec.name,
        statistic=None,
        value=None,
        unit=spec.unit,
        window=None,
        provenance=provenance,
        computed_by=computed_by,
        summary=f"{spec.name}: channel is missing from the input.",
    )


def _query_for(signals: tuple[SignalSpec, ...]) -> str:
    casts = ",\n".join(
        f"try_cast({_quote_identifier(spec.name)} AS DOUBLE) AS value_{index}"
        for index, spec in enumerate(signals)
    )
    projections = " UNION ALL ".join(
        "SELECT row_num, "
        + _quote_literal(spec.name)
        + f" AS signal, value_{index} AS value FROM source"
        for index, spec in enumerate(signals)
    )
    return f"""
        WITH source AS MATERIALIZED (
            SELECT row_number() OVER () AS row_num, {casts}
            FROM read_csv_auto(?)
        ),
        long_values AS MATERIALIZED ({projections}),
        centers AS (
            SELECT signal, approx_quantile(value, 0.5) AS center,
                   min(value) AS low_value, max(value) AS high_value
            FROM long_values WHERE value IS NOT NULL GROUP BY signal
        ),
        scales AS (
            SELECT long_values.signal, centers.center, centers.low_value,
                   centers.high_value,
                   approx_quantile(
                       abs(long_values.value - centers.center), 0.5
                   ) AS mad
            FROM long_values
            JOIN centers USING (signal)
            WHERE long_values.value IS NOT NULL
            GROUP BY long_values.signal, centers.center,
                     centers.low_value, centers.high_value
        ),
        scored AS (
            SELECT long_values.row_num, long_values.signal, long_values.value,
                   CASE
                     WHEN scales.mad = 0
                       AND scales.low_value = scales.high_value THEN 0.0
                     WHEN scales.mad = 0 THEN NULL
                     ELSE {_MAD_NORMALIZATION} *
                          abs(long_values.value - scales.center) / scales.mad
                   END AS robust_z
            FROM long_values JOIN scales USING (signal)
        )
        SELECT signal, count(value), max(robust_z), min(row_num), max(row_num)
        FROM scored GROUP BY signal
    """


def extract_evidence(
    csv_path: str | Path,
    signals: tuple[SignalSpec, ...],
    *,
    computed_by: str = "duckdb_approx_robust_mad_zscore@v1",
    provenance_tag: str | None = None,
) -> tuple[Evidence, ...]:
    """Scan all declared channels and emit one bounded record per channel.

    ``computed_by`` and ``provenance_tag`` let the experimental mapping path
    mark its records as an unverified, model-proposed mapping. The safe path
    keeps the defaults and is unchanged.
    """
    path = Path(csv_path)
    source = str(path)
    if len({spec.name for spec in signals}) != len(signals):
        raise ValueError("declared signal names must be unique")
    if not path.is_file():
        return tuple(
            _missing_evidence(
                spec,
                source,
                computed_by=computed_by,
                provenance_tag=provenance_tag,
            )
            for spec in signals
        )
    if not signals:
        return ()

    connection = duckdb.connect(database=":memory:")
    try:
        describe_rows = cast(
            list[tuple[object, ...]],
            connection.execute(
                "DESCRIBE SELECT * FROM read_csv_auto(?)", [str(path)]
            ).fetchall(),
        )
        columns = {str(row[0]) for row in describe_rows}
        missing = tuple(spec for spec in signals if spec.name not in columns)
        present = tuple(spec for spec in signals if spec.name in columns)
        summaries: dict[str, tuple[int, float | None, int, int]] = {}
        if present:
            rows = cast(
                list[tuple[object, ...]],
                connection.execute(_query_for(present), [str(path)]).fetchall(),
            )
            for row in rows:
                name = str(row[0])
                count = int(cast(int, row[1]))
                max_z = None if row[2] is None else float(cast(float, row[2]))
                first = int(cast(int, row[3]))
                last = int(cast(int, row[4]))
                summaries[name] = (count, max_z, first, last)
    finally:
        connection.close()

    output: list[Evidence] = []
    for spec in signals:
        if spec in missing:
            output.append(
                _missing_evidence(
                    spec, source, computed_by=computed_by, provenance_tag=provenance_tag
                )
            )
            continue
        summary_data = summaries.get(spec.name)
        if summary_data is None or summary_data[0] == 0:
            output.append(
                _missing_evidence(
                    spec, source, computed_by=computed_by, provenance_tag=provenance_tag
                )
            )
            continue
        count, max_z, first, last = summary_data
        if spec.robust_z_threshold is None or max_z is None:
            kind = EvidenceKind.NOT_EVALUATED
        elif max_z > spec.robust_z_threshold:
            kind = EvidenceKind.SENSOR_ANOMALY
        else:
            kind = EvidenceKind.SENSOR_NOMINAL
        provenance = f"{source} rows {first}-{last} ({count} observations)"
        if spec.threshold_source is not None:
            provenance = f"{provenance} source={spec.threshold_source}"
        if provenance_tag is not None:
            provenance = f"{provenance} tag={provenance_tag}"
        score_text = "unavailable" if max_z is None else f"{max_z:.6g}"
        summary = f"{spec.name}: approximate maximum robust MAD z-score {score_text}."
        output.append(
            Evidence(
                evidence_id=make_evidence_id(
                    f"{kind.value}\0{spec.name}\0{provenance}"
                ),
                kind=kind,
                signal=spec.name,
                statistic="approx_robust_z_max",
                value=max_z,
                unit=spec.unit,
                window=(first, last),
                provenance=provenance,
                computed_by=computed_by,
                summary=summary,
                window_basis=f"row:{source}",
            )
        )
    return tuple(output)
