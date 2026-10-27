from __future__ import annotations

from pathlib import Path
from typing import cast

import duckdb

from src.core.evidence import make_evidence_id
from src.core.types import BaselineSpec, Evidence, EvidenceKind, SignalSpec

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
        threshold=spec.robust_z_threshold,
    )


def _projection(signals: tuple[SignalSpec, ...], source_name: str) -> tuple[str, str]:
    casts = ",\n".join(
        f"try_cast({_quote_identifier(spec.name)} AS DOUBLE) AS value_{index}"
        for index, spec in enumerate(signals)
    )
    projections = " UNION ALL ".join(
        "SELECT row_num, "
        + _quote_literal(spec.name)
        + f" AS signal, value_{index} AS value FROM {source_name}"
        for index, spec in enumerate(signals)
    )
    return casts, projections


def _query_for(
    signals: tuple[SignalSpec, ...],
    baseline: BaselineSpec | None,
) -> tuple[str, list[object]]:
    casts, projections = _projection(signals, "source")
    baseline_casts, baseline_projections = _projection(signals, "baseline_source")
    params: list[object] = []
    if baseline is None:
        baseline_cte = "baseline_values AS MATERIALIZED (SELECT * FROM long_values)"
        scored_filter = ""
    elif baseline.mode == "lead_in":
        assert baseline.rows is not None
        baseline_cte = (
            "baseline_values AS MATERIALIZED "
            "(SELECT * FROM long_values WHERE row_num <= ?)"
        )
        scored_filter = "WHERE long_values.row_num > ?"
        params.extend([baseline.rows, baseline.rows])
    elif baseline.mode == "nominal_file":
        assert baseline.file is not None
        baseline_cte = (
            "baseline_source AS MATERIALIZED (\n"
            f"            SELECT row_number() OVER () AS row_num, {baseline_casts}\n"
            "            FROM read_csv_auto(?)\n"
            "        ),\n"
            "        baseline_values AS MATERIALIZED "
            f"({baseline_projections})"
        )
        scored_filter = ""
        params.append(baseline.file)
    else:
        raise ValueError(
            "recipe_step baselines are not scored yet; use lead_in or nominal_file"
        )
    sql = f"""
        WITH source AS MATERIALIZED (
            SELECT row_number() OVER () AS row_num, {casts}
            FROM read_csv_auto(?)
        ),
        long_values AS MATERIALIZED ({projections}),
        {baseline_cte},
        centers AS (
            SELECT signal, approx_quantile(value, 0.5) AS center,
                   min(value) AS low_value, max(value) AS high_value
            FROM baseline_values WHERE value IS NOT NULL GROUP BY signal
        ),
        scales AS (
            SELECT baseline_values.signal, centers.center, centers.low_value,
                   centers.high_value,
                   approx_quantile(
                       abs(baseline_values.value - centers.center), 0.5
                   ) AS mad
            FROM baseline_values
            JOIN centers USING (signal)
            WHERE baseline_values.value IS NOT NULL
            GROUP BY baseline_values.signal, centers.center,
                     centers.low_value, centers.high_value
        ),
        scored AS (
            SELECT long_values.row_num, long_values.signal, long_values.value,
                   CASE
                     WHEN scales.mad = 0
                       AND scales.low_value = scales.high_value
                       AND long_values.value = scales.center THEN 0.0
                     WHEN scales.mad = 0 THEN NULL
                     ELSE {_MAD_NORMALIZATION} *
                          abs(long_values.value - scales.center) / scales.mad
                   END AS robust_z
            FROM long_values JOIN scales USING (signal)
            {scored_filter}
        )
        SELECT signal, count(value), max(robust_z), min(row_num), max(row_num)
        FROM scored GROUP BY signal
    """
    return sql, params



def extract_evidence(
    csv_path: str | Path,
    signals: tuple[SignalSpec, ...],
    *,
    baseline: BaselineSpec | None = None,
    computed_by: str = "duckdb_approx_robust_mad_zscore@v1",
    provenance_tag: str | None = None,
) -> tuple[Evidence, ...]:
    """Scan all declared channels and emit one bounded record per channel.

    ``baseline`` decides which rows define normal. A lead-in uses the first
    rows of the upload; a nominal file uses a separate, curated export. The
    score window always remains the upload rows, never the baseline rows.

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
        baseline_count = None
        if baseline is not None and baseline.mode == "lead_in":
            assert baseline.rows is not None
            counted = connection.execute(
                "SELECT count(*) FROM read_csv_auto(?)", [source]
            ).fetchone()
            if counted is None:
                raise ValueError(f"could not count rows in {source}")
            baseline_count = int(cast(int, counted[0]))
            if baseline.rows >= baseline_count:
                raise ValueError(
                    f"baseline.rows={baseline.rows} must be smaller than the "
                    f"{baseline_count} data rows in {source}"
                )
        if baseline is not None and baseline.mode == "nominal_file":
            assert baseline.file is not None
            baseline_path = Path(baseline.file)
            if not baseline_path.is_file():
                raise ValueError(f"baseline file not found: {baseline_path}")
            baseline_columns = {
                str(row[0])
                for row in cast(
                    list[tuple[object, ...]],
                    connection.execute(
                        "DESCRIBE SELECT * FROM read_csv_auto(?)",
                        [str(baseline_path)],
                    ).fetchall(),
                )
            }
            absent = tuple(
                spec.name for spec in present if spec.name not in baseline_columns
            )
            if absent:
                raise ValueError(
                    "baseline file is missing declared signal(s): "
                    + ", ".join(absent)
                )
        summaries: dict[str, tuple[int, float | None, int, int]] = {}
        if present:
            sql, baseline_params = _query_for(present, baseline)
            rows = cast(
                list[tuple[object, ...]],
                connection.execute(sql, [source, *baseline_params]).fetchall(),
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
        if baseline is not None:
            if baseline.mode == "lead_in":
                provenance = (
                    f"{provenance}; baseline=first {baseline.rows} rows"
                )
            elif baseline.mode == "nominal_file":
                provenance = f"{provenance}; baseline={baseline.file}"
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
                threshold=spec.robust_z_threshold,
            )
        )
    return tuple(output)
