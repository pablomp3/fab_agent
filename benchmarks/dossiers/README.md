# `benchmarks/dossiers/` — Synthetic Fab Twin fixtures

This directory holds the generated Synthetic Fab Twin benchmark dossiers. Each
folder is one scenario: a CSV telemetry payload plus a `manifest.json` that
records exactly how it was produced. Expected outcomes live outside version
control in `benchmarks/evaluator/ground_truths/`.

## Scenario map

| Folder | Purpose |
|---|---|
| `B4a/` | Isolated single-sensor excursion with nominal corroborating channels. |
| `B4b/` | Flatlined / stuck sensor. |
| `B4c/` | Downstream defect with no upstream precursor. |
| `B4d/` | Missing required confirming channel. |
| `B4e/` | Corroborated multi-channel excursion (positive control). |

## How the generated cases work

Each dossier is built from deterministic, seeded math — no model is involved:

1. Baseline `10 + N(0, 1)` with a small random-walk drift `N(0, 0.05)`, sampled
   at 1 Hz for 120 observations.
2. An explicit injected mechanism (rectangle pulse, flatline, or missing
   channel) is applied per case.
3. Reproducibility is locked by recording the `seed`, generator revision,
   configuration revision, and telemetry `sha256` in `manifest.json`.

Regenerate every dossier with:

```sh
python -m benchmarks.twin.generate_twin
```

## Why these fixtures

Each case maps to a real troubleshooting situation:

| Case | Situation it models |
|---|---|
| `B4a` | One sensor trips while its corroborating sensors are normal → an instrumentation false alarm; do not blame the tool. |
| `B4b` | A sensor freezes at one value → the channel says nothing; do not conclude. |
| `B4c` | A downstream metrology excursion with no upstream precursor → do not invent an upstream cause. |
| `B4d` | The confirming channel was never exported → missing evidence must not be guessed. |
| `B4e` | A genuine corroborated fault → a root cause may legitimately be supported. |

These are controlled evaluation fixtures, not field data. Recovering an injected
mechanism does not establish real-world field truth.
