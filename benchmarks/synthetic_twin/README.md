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
