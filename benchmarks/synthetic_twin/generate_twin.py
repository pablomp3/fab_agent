from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from scipy.stats import norm

_SOURCE = "simulation_parameter:synthetic_twin_v1"
_THRESHOLD = 3.5
_N = 120
_MAD_NORMALIZATION = 0.6744897501960817
_CASE_IDS = ("B4a", "B4b", "B4c", "B4d")
_POSITIVE_CASE_IDS = ("B4e",)
_POSITIVE_SEED = 46


@dataclass(frozen=True, slots=True)
class GenerationRecord:
    case_id: str
    seed: int
    telemetry_sha256: str
    manifest_path: Path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _baseline(rng: np.random.Generator) -> NDArray[np.float64]:
    gaussian = norm.rvs(loc=0.0, scale=1.0, size=_N, random_state=rng)
    drift = np.cumsum(rng.normal(loc=0.0, scale=0.05, size=_N))
    return np.asarray(10.0 + gaussian + drift, dtype=np.float64)


def _clamp_robust_z(
    values: NDArray[np.float64], maximum: float
) -> tuple[NDArray[np.float64], int]:
    original = values.copy()
    bounded = values.copy()
    for _ in range(100):
        center = float(np.median(bounded))
        mad = float(np.median(np.abs(bounded - center)))
        if mad == 0.0:
            raise ValueError("cannot clamp a constant channel to a nonzero z bound")
        scores = _MAD_NORMALIZATION * np.abs(bounded - center) / mad
        if float(np.max(scores)) < maximum:
            return bounded, int(np.count_nonzero(original != bounded))
        half_width = (maximum - 1e-6) * mad / _MAD_NORMALIZATION
        bounded = np.clip(bounded, center - half_width, center + half_width)
    raise RuntimeError("robust z clamping did not converge")


def _case_data(
    case_id: str, seed: int
) -> tuple[dict[str, NDArray[np.float64]], dict[str, object]]:
    rng = np.random.default_rng(seed)
    signals: dict[str, NDArray[np.float64]] = {}
    mutations: dict[str, object] = {}
    if case_id == "B4a":
        signals["sensor_17"] = _baseline(rng)
        signals["sensor_17"][49:70] += 15.0
        mutations["sensor_17"] = {"indices_1_based": [50, 70], "offset_sigma": 15.0}
        for name in ("impedance", "thermal", "pressure"):
            signals[name], clipped = _clamp_robust_z(_baseline(rng), 0.999)
            mutations[name] = {"clamped_max_robust_z": 0.999, "clipped_values": clipped}
    elif case_id == "B4b":
        thermal = _baseline(rng)
        thermal[29:120] = 10.0
        signals["thermal_sensor"] = thermal
        signals["flow"] = _baseline(rng)
        signals["pressure"] = _baseline(rng)
        mutations["thermal_sensor"] = {
            "flatline_value": 10.0,
            "indices_1_based": [30, 120],
        }
    elif case_id == "B4c":
        metrology = _baseline(rng)
        center = float(np.median(metrology))
        mad = float(np.median(np.abs(metrology - center)))
        metrology[119] = center + 4.2 * mad / _MAD_NORMALIZATION
        signals["met_cd_bias"] = metrology
        mutations["met_cd_bias"] = {"index_1_based": 120, "target_robust_z": 4.2}
        for name in ("etch_rf_power", "chamber_pressure"):
            signals[name], clipped = _clamp_robust_z(_baseline(rng), 1.199)
            mutations[name] = {"clamped_max_robust_z": 1.199, "clipped_values": clipped}
    elif case_id == "B4d":
        pressure = _baseline(rng)
        pressure[39:60] += 8.0
        signals["chamber_pressure"] = pressure
        mutations["chamber_pressure"] = {
            "indices_1_based": [40, 60],
            "offset_sigma": 8.0,
        }
        mutations["roughing_line_pressure"] = {"omitted_channel": True}
    elif case_id == "B4e":
        signals["sensor_17"] = _baseline(rng)
        signals["sensor_17"][49:70] += 15.0
        mutations["sensor_17"] = {"indices_1_based": [50, 70], "offset_sigma": 15.0}
        for name in ("impedance", "thermal", "pressure"):
            signals[name] = _baseline(rng)
            signals[name][49:70] += 8.0
            mutations[name] = {"indices_1_based": [50, 70], "offset_sigma": 8.0}
    else:
        raise ValueError(f"unsupported synthetic case: {case_id}")
    return signals, mutations


def _truth(case_id: str) -> dict[str, object]:
    outcomes: dict[str, dict[str, object]] = {
        "B4a": {
            "expected_verdict": "VETOED",
            "allowed_actions": ["ESCALATE_TO_ENGINEER"],
            "expected_predicates": {"has_instrumentation_contradiction": True},
            "expected_evidence": {
                "sensor_17": {"allowed_kinds": ["SENSOR_ANOMALY"]},
                "impedance": {
                    "allowed_kinds": ["SENSOR_NOMINAL"],
                    "max_robust_z_exclusive": 1.0,
                },
                "thermal": {
                    "allowed_kinds": ["SENSOR_NOMINAL"],
                    "max_robust_z_exclusive": 1.0,
                },
                "pressure": {
                    "allowed_kinds": ["SENSOR_NOMINAL"],
                    "max_robust_z_exclusive": 1.0,
                },
            },
        },
        "B4b": {
            "expected_verdict": "INSUFFICIENT",
            "allowed_actions": ["ESCALATE_TO_ENGINEER"],
            "expected_predicates": {"has_primary_signal_anomaly": False},
            "expected_evidence": {
                "thermal_sensor": {
                    "allowed_kinds": ["NOT_EVALUATED", "SENSOR_NOMINAL"],
                    "max_robust_z_when_evaluated": 0.0,
                }
            },
        },
        "B4c": {
            "expected_verdict": "INSUFFICIENT",
            "allowed_actions": ["ESCALATE_TO_ENGINEER"],
            "expected_predicates": {"has_cross_tool_temporal_precedence": False},
            "expected_evidence": {
                "met_cd_bias": {
                    "allowed_kinds": ["SENSOR_ANOMALY"],
                    "target_robust_z": 4.2,
                },
                "etch_rf_power": {
                    "allowed_kinds": ["SENSOR_NOMINAL"],
                    "max_robust_z_exclusive": 1.2,
                },
                "chamber_pressure": {
                    "allowed_kinds": ["SENSOR_NOMINAL"],
                    "max_robust_z_exclusive": 1.2,
                },
            },
        },
        "B4d": {
            "expected_verdict": "INSUFFICIENT",
            "allowed_actions": ["ESCALATE_TO_ENGINEER"],
            "expected_predicates": {"has_missing_required_evidence": True},
            "expected_evidence": {
                "chamber_pressure": {"allowed_kinds": ["SENSOR_ANOMALY"]},
                "roughing_line_pressure": {"allowed_kinds": ["MISSING_CHANNEL"]},
            },
        },
        "B4e": {
            "expected_verdict": "SUPPORTED",
            "allowed_actions": ["ESCALATE_TO_ENGINEER"],
            "expected_predicates": {
                "has_primary_signal_anomaly": True,
                "has_instrumentation_contradiction": False,
                "has_missing_required_evidence": False,
            },
            "expected_evidence": {
                "sensor_17": {"allowed_kinds": ["SENSOR_ANOMALY"]},
                "impedance": {"allowed_kinds": ["SENSOR_ANOMALY"]},
                "thermal": {"allowed_kinds": ["SENSOR_ANOMALY"]},
                "pressure": {"allowed_kinds": ["SENSOR_ANOMALY"]},
            },
        },
    }
    return {"case_id": case_id, **outcomes[case_id]}


def _write_case(
    root: Path,
    case_id: str,
    seed: int,
    config_hash: str,
    generator_hash: str,
) -> GenerationRecord:
    signals, mutations = _case_data(case_id, seed)
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    frame = pd.DataFrame(
        {"timestamp": pd.date_range(start, periods=_N, freq="s"), **signals}
    )
    case_dir = root / "benchmarks" / "synthetic_twin" / "cases" / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    csv_path = case_dir / "telemetry.csv"
    frame.to_csv(csv_path, index=False, float_format="%.10f", lineterminator="\n")
    telemetry_hash = _sha256(csv_path.read_bytes())
    manifest = {
        "case_id": case_id,
        "seed": seed,
        "observations": _N,
        "sampling_hz": 1,
        "generator_revision": f"sha256:{generator_hash}",
        "configuration_revision": f"sha256:{config_hash}",
        "source": _SOURCE,
        "unit": None,
        "simulation_unit_alternative": "dimensionless_simulation_unit",
        "baseline": {
            "distribution": "Gaussian",
            "mean": 10.0,
            "noise_sd": 1.0,
            "drift_increment_sd": 0.05,
        },
        "robust_z_threshold": _THRESHOLD,
        "threshold_source": _SOURCE,
        "mutations": mutations,
        "outputs": {"telemetry.csv": f"sha256:{telemetry_hash}"},
    }
    manifest_path = case_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    truth_path = (
        root / "benchmarks/evaluator/ground_truths" / f"{case_id}_ground_truth.json"
    )
    truth_path.parent.mkdir(parents=True, exist_ok=True)
    truth_path.write_text(
        json.dumps(_truth(case_id), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return GenerationRecord(case_id, seed, telemetry_hash, manifest_path)


def generate_all(
    root: Path, config_path: Path | None = None
) -> tuple[GenerationRecord, ...]:
    """Write seeded adversarial dossiers (B4a-B4d), public manifests, and truth."""
    project_root = Path(__file__).resolve().parents[2]
    config = config_path or project_root / "config/sensor_relations/synthetic_twin.yaml"
    config_hash = _sha256(config.read_bytes())
    generator_hash = _sha256(Path(__file__).read_bytes())
    return tuple(
        _write_case(root, case_id, 42 + index, config_hash, generator_hash)
        for index, case_id in enumerate(_CASE_IDS)
    )


def generate_positive_control(
    root: Path, config_path: Path | None = None
) -> GenerationRecord:
    """Write the B4e positive-control dossier (a corroborated fault, not an
    adverse case) so the deterministic rules can yield a supported verdict."""
    project_root = Path(__file__).resolve().parents[2]
    config = (
        config_path
        or project_root / "config/sensor_relations/synthetic_twin_positive.yaml"
    )
    config_hash = _sha256(config.read_bytes())
    generator_hash = _sha256(Path(__file__).read_bytes())
    return _write_case(
        root, _POSITIVE_CASE_IDS[0], _POSITIVE_SEED, config_hash, generator_hash
    )


if __name__ == "__main__":
    repository_root = Path(__file__).resolve().parents[2]
    for record in generate_all(repository_root):
        print(
            f"Generated {record.case_id} seed={record.seed} "
            f"sha256={record.telemetry_sha256}"
        )
    positive = generate_positive_control(repository_root)
    print(
        f"Generated {positive.case_id} seed={positive.seed} "
        f"sha256={positive.telemetry_sha256}"
    )
