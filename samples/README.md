# Demo samples

The dashboard ships four small CSVs and can generate a fresh seeded export.
They are **demo inputs**, not field telemetry. They exercise the product paths
without a provider key when the dashboard's offline transport is selected.

| File | What it demonstrates | Expected result |
|---|---|---|
| `flowcool_supported.csv` | A saved coolant tool model; both coolant channels move | **Fault Confirmed** → Inspect the part |
| `flowcool_inconclusive.csv` | The coolant channels are present but neither moves | **Regular Behavior** or **Needs Review** (see the coverage note) |
| `rf_contradiction.csv` | `sensor_17` moves while every companion stays normal | **Sensors Disagree** → Check the sensor first |
| `unknown_tool.csv` | No saved tool model matches; the mapper drafts one | **Unknown Machine** → Review the guessed columns |

The safe-path samples use the headers of the public PHM 2018 / synthetic-twin
configurations so triage can select a tool model. The values are hand-written;
they are not copied from a fab or a public dataset.

> **PHM slices:** the committed PHM `M02_DC_01_nominal_sample.csv` is a clean
> normal control, and the two fault slices use it as their `nominal_file`
> baseline. The same fault gives the same product result. See
> [`docs/DATASETS.md`](../docs/DATASETS.md).

Run the dashboard in offline mode, or run the same files through the product entry
point:

```sh
PYTHONPATH=. .venv/bin/python - <<'PY'
from benchmarks.evaluator.echo_transport import (
    ExperimentalEchoTransport,
    offline_engine_factory,
    offline_mapping_factory,
)
from src.analyze import analyze_csv

transport = ExperimentalEchoTransport()
result = analyze_csv(
    "samples/rf_contradiction.csv",
    "RF sensor excursion",
    engine_factory=offline_engine_factory(transport),
    mapping_factory=offline_mapping_factory(transport),
)
print(result.mode, result.outcome, result.suggested_next_action)
PY
```

The generator writes a nominal lead-in and an optional drift, but it never writes
a ground-truth label. Python still decides.
