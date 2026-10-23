# Demo samples

These four small CSVs are **synthetic demo inputs**, not field telemetry. They
exercise the product paths without a provider key when the dashboard's demo
mode is enabled.

| File | What it demonstrates |
|---|---|
| `flowcool_supported.csv` | Safe path: a configured flowcool schema, both channels anomalous, Python verdict `SUPPORTED`, action `INSPECT_COMPONENT`. |
| `flowcool_inconclusive.csv` | Safe path: the configured channels are present but neither is anomalous, so the gate abstains and asks for more data. |
| `rf_contradiction.csv` | Safe path: `sensor_17` is anomalous while every configured corroborating channel is nominal. The contradiction veto wins, so the model's arc story cannot support an action. |
| `unknown_tool.csv` | Experimental fallback: no configured schema matches, the mapping is inferred, evidence is marked unverified, and the UI offers a draft config to review and save. |

The safe-path samples use the headers of the public PHM 2018 / synthetic-twin
configurations so the deterministic triage can select a scenario. The values
are hand-written; they are not copied from a fab or from a public dataset.

Run the dashboard in demo mode (no `NEBIUS_API_KEY` needed) or run the same
files through the product entry point with an offline transport:

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
