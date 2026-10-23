# FabAgent

**An evidence-gated root-cause copilot for semiconductor manufacturing.**

FabAgent reads a tool's sensor CSV, scopes it against a declarative tool
configuration, turns the readings into evidence records, and gates a
configuration-authored candidate through deterministic Python rules. An NVIDIA
Nemotron model (served through Nebius Token Factory) writes an explanatory
narrative and cites evidence IDs, but it does **not** decide the verdict or the
action. A human always decides what to do next.

The product entry point is `analyze_csv(csv, note)` in
[`src/analyze.py`](src/analyze.py).

```
CSV ──> DuckDB triage ──> scoped evidence ──> configured candidate
                                                   │
                                                   ▼
                              Nemotron narrative (not gated)
                                                   │
                                                   ▼
                         Python predicates + vetoes + typed action
```

## Try it in 30 seconds (no API key)

```sh
uv sync
PYTHONPATH=. .venv/bin/streamlit run src/ui/app.py
```

Open the app, keep **Demo mode** on, and run one of the four synthetic samples:

| Sample | What it shows |
|---|---|
| `flowcool_supported.csv` | Safe path, `SUPPORTED`, action `INSPECT_COMPONENT` |
| `flowcool_inconclusive.csv` | Safe path, `INSUFFICIENT`, action `COLLECT_MORE_DATA` |
| `rf_contradiction.csv` | Corroborating channels are nominal, so the contradiction veto wins over the model's arc story |
| `unknown_tool.csv` | No schema matches; experimental mapping, unverified evidence, reviewable draft config |

Demo mode uses a deterministic local transport that goes through the same
engine, citation resolver, predicates, and gate as a live call. It is a demo
transport, not a substitute for the live model. The samples are synthetic and
are not field validation.

For live mode, set `NEBIUS_API_KEY` in the environment and turn demo mode off:

```sh
export NEBIUS_API_KEY          # set it in your shell or secret manager
PYTHONPATH=. .venv/bin/streamlit run src/ui/app.py
```

The app never displays, logs, or stores the key.

## The core contract

1. **The configuration owns the candidate.** Each scenario declares
   `candidate.claim`, `candidate.hypothesis_class`, `candidate.cited_signals`,
   `candidate.root_cause`, and a `supported_action`. The model cannot rename the
   claim or choose the action.
2. **Python owns the verdict.** Every configured signal is resolved to an
   evidence record. Boolean predicates are derived from that evidence. A
   configured channel with no evidence forces `INSUFFICIENT`; a hard
   contradiction forces `VETOED`.
3. **The model owns the narrative, not the conclusion.** The model's proposal is
   stored as `model_narrative` and shown under “not gated.” If the model call
   fails or returns invalid JSON, the deterministic gate still runs and records
   the sanitized failure category as a required next check.
4. **Actions are typed and safe.** There is no free-form action field and no
   recipe-change action. `HOLD_LOT` is deliberately not offered. Supported runs
   use the scenario's declared `INSPECT_COMPONENT`, `CONTINUE_MONITORING`, or
   `ESCALATE_TO_ENGINEER`; every other route fails closed.
5. **Unknown stays unknown.** Units and thresholds without an authoritative
   source remain `null`/`NOT_EVALUATED`; the system never invents a number.

## Quickstart for developers

```sh
uv sync

# Unit tests, linter, and strict type-checker
.venv/bin/python -m unittest discover -s tests
.venv/bin/ruff check .
.venv/bin/basedpyright

# Deterministic gates (no provider key)
PYTHONPATH=. .venv/bin/python benchmarks/evaluator/synthetic_abstention_runner.py
PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.dossier_e2e_runner --offline
PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.experimental_e2e_runner
PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.e2e_suite_runner
```

The live positive control and the live end-to-end walkthrough need
`NEBIUS_API_KEY`:

```sh
PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.llm_positive_control
PYTHONPATH=. .venv/bin/python benchmarks/evaluator/user_story_runner.py --live
```

## How a run flows

1. **Triage.** `src/triage.py` matches CSV headers (and the optional engineer
   note) against runnable scenarios in `config/sensor_relations/*.yaml`.
2. **Evidence.** `src/core/duckdb_exec.py` scans only the selected scenario's
   channels with DuckDB and computes an approximate robust MAD z-score per
   channel. It emits one bounded evidence record per channel: anomaly, nominal,
   missing, or not evaluated.
3. **Gate.** `src/agents/rca_engine.py` sends a ≤2 KB evidence summary and the
   configured candidate to Nemotron. The model returns a strict-JSON narrative
   with evidence IDs. Python resolves the configured citations, derives boolean
   predicates, applies the scenario's `require_all` / `forbid_any` /
   `veto_if_any` rule, and chooses the typed action.
4. **Present.** The Streamlit dashboard shows the five stages explicitly:
   triage, scope, model call, Python verdict, and next step. The model narrative
   is a separate expander.

If no schema matches, `analyze_csv` automatically falls back to the
experimental mapping (`src/experimental.py`): it profiles columns, asks the
model for a bounded mapping, validates every column in Python, scans the
validated signals with a documented default threshold, marks all evidence
`unverified_mapping`, and offers a draft YAML config. Saving the draft turns the
next run into the deterministic safe path. It is data triage, not a physical
root-cause claim.

## Configuration example

```yaml
version: 1
name: ion_mill_phm18
provenance: "PHM 2018 documented signal groups"
signals:
  - {name: FLOWCOOLFLOWRATE, unit: null, robust_z_threshold: null}
  - {name: FLOWCOOLPRESSURE, unit: null, robust_z_threshold: null}
scenarios:
  flowcool:
    signals:
      - {name: FLOWCOOLFLOWRATE, unit: null, robust_z_threshold: 3.5, threshold_source: "standard_robust_mad_multiplier=3.5"}
      - {name: FLOWCOOLPRESSURE, unit: null, robust_z_threshold: 3.5, threshold_source: "standard_robust_mad_multiplier=3.5"}
    predicates:
      primary_signals: [FLOWCOOLFLOWRATE, FLOWCOOLPRESSURE]
    rules:
      equipment_fault:
        require_all: [has_primary_signal_anomaly]
        forbid_any: [has_missing_required_evidence]
    candidate:
      claim: flowcool subsystem fault
      hypothesis_class: equipment_fault
      cited_signals: [FLOWCOOLFLOWRATE, FLOWCOOLPRESSURE]
      root_cause: equipment_fault
      failure_mode: Flowcool subsystem fault; confirm the specific mode during inspection.
      mechanism: The configured relationship links coolant flow and pressure; the physical mechanism is not asserted.
    supported_action: INSPECT_COMPONENT
```

The loader rejects unknown keys and invalid actions. `supported_action` is
limited to `INSPECT_COMPONENT`, `CONTINUE_MONITORING`, or
`ESCALATE_TO_ENGINEER`; a data-quality action cannot be declared as a supported
outcome.

## Validation (measured, with limits)

The repository records receipts for every deterministic gate. These are
engineering checks on public or synthetic substrates, **not** field validation
and **not** a broad accuracy claim.

| Gate | What it checks | Receipt |
|---|---|---|
| W2 | A 30 GB stress input becomes a 370-byte evidence payload | `benchmarks/evaluator/results/w2_payload_check.json` |
| W3 | B4a–B4d abstain or veto with **zero LLM calls** | `benchmarks/evaluator/results/w3_adversarial_check.json` |
| W4 | B4e positive control reaches a Python-gated result | `benchmarks/evaluator/results/w4_positive_check_offline.json` |
| W5 | PHM 2018 flowcool and TEP feed cases on measured data | `benchmarks/evaluator/results/w5_real_data_check.json` |
| W5.5 | Engineer flow, payload scaling, and the safe path | `benchmarks/evaluator/results/e2e_phm_check_offline.json` |
| Experimental | Unknown export → validated mapping → draft config | `benchmarks/evaluator/results/experimental_phm_check_offline.json` |

Measured highlights:

- **W3:** all four adversarial cases pass with `llm_calls=0`. B4a is `VETOED`
  because the corroborating channels contradict the primary anomaly; B4b–B4d
  abstain rather than over-claim.
- **W4:** the B4e positive control is `SUPPORTED` offline. The live path is
  non-deterministic; a recorded live stability run measured 4/5 supported
  proposals **before** the candidate-alignment change. That artifact measures
  proposal availability, not the current gate's determinism.
- **W5:** the scoped PHM 2018 flowcool candidate is `SUPPORTED /
  INSPECT_COMPONENT`; TEP IDV 1/2/6 are supported and the other configured IDVs
  abstain. This is one subsystem and one cause/symptom relationship, not broad
  accuracy.
- **Experimental:** the unknown-export path validates every column in Python and
  marks every evidence record `unverified_mapping`; it never claims a physical
  root cause.

The single naive-LLM baseline harness is
[`benchmarks/evaluator/naive_llm_baseline.py`](benchmarks/evaluator/naive_llm_baseline.py).
Its offline mode is a harness check with an over-claiming fixture
(`results/naive_llm_baseline_offline.json`), **not** a measured LLM baseline.
Run it with `--live` to record `results/naive_llm_baseline.json`.

The full dataset defense for judges is in
[`dataset_validation_defense.md`](dataset_validation_defense.md). The open
adoption limits are in [`KNOWN_CHALLENGES.md`](KNOWN_CHALLENGES.md), and the
route/action reference is in [`SUGGESTED_ACTIONS.md`](SUGGESTED_ACTIONS.md).

## Repository map

```
fab_agent/
├── src/
│   ├── core/                 # deterministic engine: no LLM, no YAML, no network
│   │   ├── duckdb_exec.py    # bounded MAD scan -> evidence records
│   │   ├── sufficiency.py    # evidence -> boolean predicates
│   │   ├── constraints.py    # require_all / forbid_any / veto_if_any
│   │   ├── safety_gate.py    # typed, fail-closed action
│   │   └── pipeline.py       # assess one candidate
│   ├── agents/               # the model boundary: proposes narrative only
│   ├── ui/                   # Streamlit dashboard and pure view helpers
│   ├── config_loader.py      # strict YAML -> immutable config objects
│   ├── config_types.py       # CandidateConfig / ScenarioConfig
│   ├── triage.py             # CSV headers + note -> scenario
│   ├── dossier.py            # safe path
│   ├── experimental.py       # unverified mapping fallback
│   ├── analyze.py            # product entry point
│   └── demo.py               # key-free deterministic demo transport
├── config/
│   ├── models.yaml           # SYNTHESIS route (Nebius / Nemotron)
│   └── sensor_relations/     # tool schemas and candidates
├── samples/                  # four synthetic demo CSVs
├── benchmarks/               # W2-W5.5 evaluators and receipts
├── tests/                    # 118 unit tests
└── docs: README, HOW_IT_WORKS, KNOWN_CHALLENGES, SUGGESTED_ACTIONS
```

`src/core/` is deliberately generic: it imports only the standard library and
DuckDB. Tool physics and sensor relationships live in YAML, parsed outside
`src/core/`. Benchmark IDs are banned from `src/core/`.

## Data boundary and limitations

- The Synthetic Fab Twin is a controlled fixture. Recovering its injected cause
  does not establish real-world field truth.
- Public datasets provide observations within the limits described in
  [`KNOWN_CHALLENGES.md`](KNOWN_CHALLENGES.md),
  [`anti_goals.md`](anti_goals.md), and
  [`dataset_validation_defense.md`](dataset_validation_defense.md). WM-811K
  spatial patterns are not causes.
- Raw telemetry stays in the local analysis path. Model requests contain only a
  bounded structured evidence payload; an oversized request raises
  `PayloadTooLarge` instead of being truncated or sent.
- External knowledge retrieval (Tavily/RAG) is not implemented. Wafer-map
  spatial predicates need calibrated feature bounds. A measured naive-LLM
  baseline is not yet recorded; the harness and an offline fixture exist, but
  the fixture is not evidence about the live model.
- The live model is non-deterministic. The gate is deterministic; the narrative
  may be absent.

## License

Apache-2.0. See [`LICENSE`](LICENSE).
