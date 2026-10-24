# `benchmarks/synthetic_twin/` — Synthetic Fab Twin benchmark

This directory contains the seeded, reproducible Synthetic Fab Twin generator
and the case files it produces. It is separate from `benchmarks/datasets/`, which
holds real public benchmark data (PHM 2018 and TEP).

| Path | Purpose |
|---|---|
| `generate_twin.py` | Deterministic NumPy/pandas generator for B4a–B4e. |
| `GENERATOR_SPEC.md` | Pre-registered parameters and anti-circularity proof. |
| `cases/` | Generated telemetry CSVs and `manifest.json` files (recreated by the generator). |
| `cases/README.md` | Scenario map and explanation of each B4 case. |

Regenerate every synthetic case with:

```sh
python -m benchmarks.synthetic_twin.generate_twin
```

The generated cases are evaluated by
`benchmarks/evaluator/synthetic_abstention_runner.py` (B4a–B4d, zero LLM calls)
and `benchmarks/evaluator/llm_positive_control.py` (B4e, live/offline LLM
control).

## Provenance and pre-registration

The benchmark was committed before any product code existed:

| Commit | Artifact |
|---|---|
| `9683b7c` | `GENERATOR_SPEC.md` and scenario definitions |
| `7f517d6` | Seeded `generate_twin.py` |
| `652afdc` | Generated B4a–B4e telemetry and public manifests |
| `a014ab0` | Product code; benchmark moved to this directory |

The publication commit moved `benchmarks/twin/` to `benchmarks/synthetic_twin/`
and `benchmarks/dossiers/` to `benchmarks/synthetic_twin/cases/`. The telemetry
CSVs and `GENERATOR_SPEC.md` are byte-identical to `652afdc`; the original
commits remain in history. The generator keeps the original
`allowed_dispositions` truth vocabulary. The evaluator maps the pre-registered
`ESCALATE` disposition to the product's typed `ESCALATE_TO_ENGINEER` action, so
the benchmark truth was not rewritten to fit the implementation. B4c's original
allowed set includes `HOLD_LOT`; the product never emits that action.

To inspect the original artifacts directly:

```sh
git show 652afdc:benchmarks/twin/GENERATOR_SPEC.md
git show 652afdc:benchmarks/twin/generate_twin.py
git show 652afdc:benchmarks/dossiers/B4a/manifest.json
```
