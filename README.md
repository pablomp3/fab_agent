# FabAgent

An evidence-gated troubleshooting copilot for semiconductor manufacturing. The
goal is to help a process engineer move from "something looks wrong" to a
traceable, reviewable next step — without inventing physics or taking unsafe
actions.

> **Scope of this repository today:** the **Synthetic Fab Twin** benchmark. It
> contains the pre-registered specification, the seeded generator, and the
> generated benchmark dossiers. The deterministic analysis engine and the model
> connector are separate, later additions.

## Synthetic Fab Twin

A controlled, fully reproducible benchmark fixture. Each case injects a known
mechanism into synthetic sensor telemetry and records the expected outcome as
private ground truth. Recovering an injected mechanism shows the analysis logic
is internally consistent; it is **not** evidence about any real fab.

| Case | Injected situation | Expected |
|---|---|---|
| `B4a` | Isolated spike in one sensor; corroborating channels stay nominal | withhold (contradiction) |
| `B4b` | Sensor flatlines / sticks | withhold (nothing to evaluate) |
| `B4c` | Downstream defect with no upstream precursor | withhold (effect without cause) |
| `B4d` | A required confirming channel was never exported | withhold (missing evidence) |
| `B4e` | A genuine multi-channel excursion that does corroborate | may support |

Expected outcomes are written to `benchmarks/evaluator/ground_truths/`, which is
excluded from version control. Public manifests record seeds, source, units,
transformations, and file checksums, but not expected verdicts.

## What is here

```
benchmarks/twin/GENERATOR_SPEC.md   # the pre-registered specification
benchmarks/twin/generate_twin.py    # the seeded generator
benchmarks/dossiers/                # generated cases B4a-B4e and manifests
config/sensor_relations/            # declarative scenario definitions
```

## Regenerate the dossiers

```sh
python -m benchmarks.twin.generate_twin
```

Requires numpy, pandas, and scipy (see `pyproject.toml`).

## Data boundary

The twin is synthetic. Its parameters are dimensionless simulation parameters,
not fab calibration or sensor physics. No fab telemetry is included, and no
model is called to produce the data.
