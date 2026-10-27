from __future__ import annotations

from collections.abc import Sequence
from statistics import median

from src.core.evidence import make_evidence_id
from src.core.types import Evidence, EvidenceKind

_MAD_NORMALIZATION = 0.6744897501960817


def robust_mad_zscores(
    values: Sequence[float | None],
) -> tuple[float | None, ...]:
    present = [value for value in values if value is not None]
    if not present:
        return tuple(None for _ in values)
    center = median(present)
    if all(value == present[0] for value in present):
        return tuple(0.0 if value is not None else None for value in values)
    mad = median([abs(value - center) for value in present])
    if mad == 0:
        return tuple(None for _ in values)
    return tuple(
        None if value is None else _MAD_NORMALIZATION * abs(value - center) / mad
        for value in values
    )


def classify_signal(
    signal: str,
    observations: Sequence[float] | None,
    robust_z_threshold: float | None,
    unit: str | None,
    provenance: str,
    threshold_source: str | None = None,
) -> Evidence:
    if observations is None or not observations:
        kind = EvidenceKind.MISSING_CHANNEL
        max_z = None
        window = None
    else:
        scores = robust_mad_zscores(observations)
        numeric_scores = [score for score in scores if score is not None]
        max_z = max(numeric_scores) if numeric_scores else None
        window = (1, len(observations))
        if robust_z_threshold is not None and not threshold_source:
            raise ValueError("a calibrated threshold requires its source")
        if robust_z_threshold is None or max_z is None:
            kind = EvidenceKind.NOT_EVALUATED
        elif max_z > robust_z_threshold:
            kind = EvidenceKind.SENSOR_ANOMALY
        else:
            kind = EvidenceKind.SENSOR_NOMINAL
    evidence_id = make_evidence_id(f"{kind.value}\0{signal}\0{provenance}")
    if max_z is None:
        summary = f"{signal}: {kind.value.lower().replace('_', ' ')}."
    else:
        summary = f"{signal}: maximum robust MAD z-score {max_z:.6g}."
    return Evidence(
        evidence_id=evidence_id,
        kind=kind,
        signal=signal,
        statistic="robust_z_max" if observations else None,
        value=max_z,
        unit=unit,
        window=window,
        provenance=provenance,
        computed_by="robust_mad_zscore@v1",
        summary=summary,
        window_basis=provenance if window is not None else None,
        threshold=robust_z_threshold,
    )
