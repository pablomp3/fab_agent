from __future__ import annotations

import math
from dataclasses import dataclass

from src.core.evidence import make_evidence_id
from src.core.types import Evidence, EvidenceKind
from src.core.wafer_components import max_component_elongation


@dataclass(frozen=True, slots=True)
class WaferDie:
    x: float
    y: float
    status: int

    def __post_init__(self) -> None:
        if not math.isfinite(self.x) or not math.isfinite(self.y):
            raise ValueError("die coordinates must be finite")
        if isinstance(self.status, bool):
            raise ValueError("die status must be an integer")


@dataclass(frozen=True, slots=True)
class WaferFeatureConfig:
    center_x: float | None = None
    center_y: float | None = None
    center_source: str | None = None
    edge_band_cutoff: float | None = None
    cutoff_source: str | None = None

    def __post_init__(self) -> None:
        if (self.center_x is None) != (self.center_y is None):
            raise ValueError("coordinate center requires both x and y")
        if self.center_x is None and self.center_source is not None:
            raise ValueError("coordinate center source requires a center")
        if self.center_x is not None and not self.center_source:
            raise ValueError("coordinate center requires its metadata source")
        if self.center_x is not None and self.center_y is not None:
            if not math.isfinite(self.center_x) or not math.isfinite(self.center_y):
                raise ValueError("coordinate center must be finite")
        if self.edge_band_cutoff is None:
            if self.cutoff_source is not None:
                raise ValueError("cutoff source requires an edge-band cutoff")
        else:
            if not math.isfinite(self.edge_band_cutoff):
                raise ValueError("edge-band cutoff must be finite")
            if not 0.0 <= self.edge_band_cutoff <= 1.0:
                raise ValueError("edge-band cutoff must be between zero and one")
            if not self.cutoff_source:
                raise ValueError("edge-band cutoff requires a calibration source")
            if self.center_x is None:
                raise ValueError("edge-band cutoff requires a coordinate center")


def convert_wm_status(raw_status: int) -> int:
    """Convert WM-811K status values: no die, pass, fail to 0, 1, -1."""
    if isinstance(raw_status, bool):
        raise ValueError("boolean is not a WM status")
    conversion = {0: 0, 1: 1, 2: -1}
    try:
        return conversion[raw_status]
    except KeyError as exc:
        raise ValueError(f"unsupported WM status: {raw_status}") from exc


def extract_wafer_features(
    dies: tuple[WaferDie, ...], config: WaferFeatureConfig, provenance: str
) -> tuple[Evidence, ...]:
    if not provenance:
        raise ValueError("provenance must not be empty")
    converted: list[tuple[WaferDie, int]] = []
    seen: set[tuple[float, float]] = set()
    for die in dies:
        coordinate = (die.x, die.y)
        if coordinate in seen:
            raise ValueError("wafer map contains duplicate die coordinates")
        seen.add(coordinate)
        converted.append((die, convert_wm_status(die.status)))
    usable = [(die, status) for die, status in converted if status != 0]
    if not usable:
        return (_missing_map_evidence(provenance),)

    failures = [die for die, status in usable if status == -1]
    values: dict[str, float | None] = {
        "fail_fraction": len(failures) / len(usable),
        "median_normalized_fail_radius": None,
        "angular_uniformity": _angular_uniformity(failures, config),
        "edge_band_concentration": None,
        "max_component_elongation": max_component_elongation(
            tuple((die.x, die.y) for die, _ in converted),
            tuple((die.x, die.y) for die in failures),
        ),
    }
    fail_radii = _normalized_fail_radii(usable, failures, config)
    if fail_radii is not None:
        if fail_radii:
            values["median_normalized_fail_radius"] = _median(fail_radii)
        if config.edge_band_cutoff is not None:
            if fail_radii:
                edge_failures = sum(
                    radius >= config.edge_band_cutoff for radius in fail_radii
                )
                values["edge_band_concentration"] = edge_failures / len(fail_radii)
            else:
                values["edge_band_concentration"] = None

    return tuple(
        _feature_evidence(statistic, value, provenance, config)
        for statistic, value in values.items()
    )


def _normalized_fail_radii(
    usable: list[tuple[WaferDie, int]],
    failures: list[WaferDie],
    config: WaferFeatureConfig,
) -> list[float] | None:
    if config.center_x is None or config.center_y is None:
        return None
    radius_by_coordinate = {
        (die.x, die.y): math.hypot(die.x - config.center_x, die.y - config.center_y)
        for die, _ in usable
    }
    extent = max(radius_by_coordinate.values(), default=0.0)
    if extent == 0.0:
        normalized = {coordinate: 0.0 for coordinate in radius_by_coordinate}
    else:
        normalized = {
            coordinate: radius / extent
            for coordinate, radius in radius_by_coordinate.items()
        }
    fail_radii = [normalized[(die.x, die.y)] for die in failures]
    return fail_radii


def _angular_uniformity(
    failures: list[WaferDie], config: WaferFeatureConfig
) -> float | None:
    if config.center_x is None or config.center_y is None:
        return None
    angles = [
        math.atan2(die.y - config.center_y, die.x - config.center_x)
        for die in failures
        if (die.x, die.y) != (config.center_x, config.center_y)
    ]
    if len(angles) < 2:
        return None
    mean_cos = sum(math.cos(angle) for angle in angles) / len(angles)
    mean_sin = sum(math.sin(angle) for angle in angles) / len(angles)
    return min(1.0, max(0.0, 1.0 - math.hypot(mean_cos, mean_sin)))


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _feature_evidence(
    statistic: str,
    value: float | None,
    provenance: str,
    config: WaferFeatureConfig,
) -> Evidence:
    kind = (
        EvidenceKind.SPATIAL_FEATURE
        if value is not None
        else EvidenceKind.NOT_EVALUATED
    )
    identity = f"{provenance}:{statistic}:{value!r}"
    summaries = {
        "fail_fraction": (
            "Failed dies / observed pass and fail dies; no-die cells excluded."
        ),
        "median_normalized_fail_radius": (
            "Median failed-die radius / maximum observed pass/fail radius."
        ),
        "angular_uniformity": (
            "Circular spread of failed-die angles; 0 aligned, 1 dispersed."
        ),
        "edge_band_concentration": (
            "Failed dies at or beyond the configured radius fraction / failed dies."
        ),
        "max_component_elongation": (
            "Maximum 8-connected component elongation index; 0 isotropic, 1 linear."
        ),
    }
    summary = summaries[statistic]
    if (
        statistic
        in {
            "median_normalized_fail_radius",
            "angular_uniformity",
            "edge_band_concentration",
        }
        and config.center_source is not None
    ):
        summary += f" Center metadata: {config.center_source}."
    if statistic == "edge_band_concentration" and config.cutoff_source is not None:
        summary += f" Cutoff source: {config.cutoff_source}."
    return Evidence(
        evidence_id=make_evidence_id(identity),
        kind=kind,
        signal=None,
        statistic=statistic,
        value=value,
        unit=None,
        window=None,
        provenance=provenance,
        computed_by="wafer_features@v1",
        summary=f"{summary} It does not identify a physical cause.",
    )


def _missing_map_evidence(provenance: str) -> Evidence:
    return Evidence(
        evidence_id=make_evidence_id(f"{provenance}:wafer-map-missing"),
        kind=EvidenceKind.MISSING_CHANNEL,
        signal="wafer_map",
        statistic=None,
        value=None,
        unit=None,
        window=None,
        provenance=provenance,
        computed_by="wafer_features@v1",
        summary="No pass or fail die coordinates were available.",
    )
