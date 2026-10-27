# FabAgent

**An evidence-gated troubleshooting copilot for semiconductor tools.**

FabAgent reads a tool’s sensor CSV, builds a normal reference, turns the readings
into evidence records, and checks them against a short, engineer-editable tool
model. It returns one of six plain results — **Fault Confirmed**, **Regular
Behavior**, **Sensors Disagree**, **Data Incomplete**, **Needs Review**, or
**Unknown Machine** — and one safe next step.

The rule is simple:

> **Nemotron proposes and challenges. Python checks. The engineer decides.**

A human always confirms the action. FabAgent never changes a recipe and never
holds a lot.

> **Build status (2026-10-27):** the deterministic engine, UI, demo, offline
> fallback, Auto column mapping, tool model, coverage, differential, and
> challenge layer are implemented. The fair benchmark is being re-run with a
> fixed protocol; no old 100%/0% number is used. See
> [`docs/STATUS.md`](docs/STATUS.md).

---

## Why

A fab tool streams hundreds of channels. When an alarm fires, a junior engineer
has to decide whether a coolant drop is a real equipment fault, a failing sensor,
a downstream symptom, or normal recipe behaviour. A naive LLM is fluent but it
cannot prove coverage, cannot detect a contradiction deterministically, and may
recommend a recipe change on a single noisy channel.

FabAgent is built to be useful without being trusted with the decision:

- **Evidence IDs, not prose.** Every finding has an ID; the model may cite only
  those IDs; Python resolves every citation.
- **A deterministic gate.** Coverage, missing channels, contradictions, and the
  allowed action are computed in Python. A contradiction is absolute; it cannot
  be outvoted.
- **Fail-closed.** If the data is incomplete, the model fails, or the cause is
  not configured, the result is **Needs Review** / **Data Incomplete**, not a
  guess.
- **No recipe or hold action.** The action set is small and typed.
- **Bounded payload.** Raw telemetry stays in DuckDB; only a small statistical
  summary crosses the network.

---

## Two ways to use it

### Engineer-defined

The engineer has a **tool model** — a short YAML file with the columns, the
normal reference, and the fault checks. The run is deterministic:

```
CSV → match tool model → build normal reference → evidence → fault checks
    → Python result → one safe next step
```

Nemotron adds the explanation and challenge; a temporary outage does not change
the result or the action.

### Auto (unknown export)

No saved tool model? FabAgent does not guess a diagnosis. It does three bounded
things:

1. **Column mapper** — Nemotron proposes what each column means; Python validates
   every proposal.
2. **Cause finder** — Nemotron proposes possible causes from the evidence.
3. **Python check** — each cause is mapped to a saved fault check. A cause
   without a check is **Needs Review**, never a confirmed fault.

The engineer reviews the guessed columns, saves the tool model, and re-runs. The
next run is deterministic. **Start in Auto, promote to Engineer-defined.**

---

## The six results

| Result | What it means | What to do |
|---|---|---|
| **Fault Confirmed** | The evidence supports the suspected fault. | Inspect the named part. |
| **Regular Behavior** | Every checked signal is normal. | Keep monitoring. |
| **Sensors Disagree** | One signal moved; the signals that should agree did not. | Check the sensor first. |
| **Data Incomplete** | A required signal is missing. | Get the missing data. |
| **Needs Review** | The data is not enough to confirm or rule out a cause. | Ask an engineer to review. |
| **Unknown Machine** | The export does not match a saved tool model. | Review the guessed columns. |

The main UI uses these words only. Internal enum names stay in the Audit tab.

---

## How it works

```
┌────────────────────────────────────────────────────────────────────┐
│ UI: six results, differential table, audit tab                     │
└───────────────────────────▲────────────────────────────────────────┘
                            │ typed result + plain-language mapping
┌───────────────────────────┴────────────────────────────────────────┐
│ Nemotron: column mapper · cause finder · challenge check · explain │
│ bounded payload, schema-validated, never decides                    │
└───────────────────────────▲────────────────────────────────────────┘
                            │ evidence IDs + saved tool-model checks
┌───────────────────────────┴────────────────────────────────────────┐
│ Python + DuckDB: baseline → evidence → coverage → checks → gate    │
│ no model, no network, no benchmark IDs                             │
└────────────────────────────────────────────────────────────────────┘
```

- **Baseline:** `lead_in`, `nominal_file`, or per-recipe-step (advanced). A
  global median/MAD can absorb a fault into “normal”.
- **Evidence:** one record per declared signal: anomaly, nominal, or missing.
- **Coverage:** unexplained large anomalies prevent a bare **Fault Confirmed**.
- **Differential:** all saved checks are shown, not just one scenario.
- **Challenge:** the model proposes a disconfirming test; Python evaluates it.
  The challenge can only downgrade a result.

---

## Quickstart

Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

```sh
uv sync
cp .env.example .env          # add NEBIUS_API_KEY and TAVILY_API_KEY
.venv/bin/streamlit run src/ui/app.py
```

Open <http://localhost:8501>. Use **Demo mode** to run without a key.

Environment:

| Variable | Used for |
|---|---|
| `NEBIUS_API_KEY` | Nemotron calls through Nebius Token Factory |
| `TAVILY_API_KEY` | Optional public troubleshooting leads |
| `FABAGENT_MODEL_CONFIG` | Optional path to `config/models.yaml` |

Keys are server-side only. They are never sent to the browser and never logged.

### Run the tests

```sh
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/ruff check .
.venv/bin/basedpyright
PYTHONPATH=. .venv/bin/python benchmarks/evaluator/synthetic_abstention_runner.py
PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.dossier_e2e_runner --offline
PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.experimental_e2e_runner
PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.e2e_suite_runner
```

---

## Tool model

A tool model is one short YAML file. It answers three questions: which columns
matter, what normal looks like, and which patterns count as a fault.

```yaml
tool:
  name: ion_mill_m02
  label: Ion Mill M02
baseline:
  mode: lead_in
  rows: 200
signals:
  - {name: FLOWCOOLFLOWRATE, label: Coolant flow, unit: null, alert_at: 3.5}
  - {name: FLOWCOOLPRESSURE, label: Coolant pressure, unit: null, alert_at: 3.5}
  - {name: IONGAUGEPRESSURE, label: Chamber pressure, unit: null, alert_at: 3.5}
checks:
  - id: coolant_leak
    label: Coolant loop fault
    kind: equipment_fault
    must_be_unusual:
      - {signal: FLOWCOOLFLOWRATE, direction: any}
      - {signal: FLOWCOOLPRESSURE, direction: any}
    must_stay_normal: [IONGAUGEPRESSURE]
    action: INSPECT_COMPONENT
    advice: Inspect the coolant loop before changing the recipe.
```

The full guide, including the TEP and sensor-conflict examples, is
[`docs/YAML_GUIDE.md`](docs/YAML_GUIDE.md). The product has one tool-model
format; the raw YAML is an advanced engineering surface, not a first-run step.

---

## Demo

The dashboard ships eight prepared demo inputs and can generate a seeded export:

- a supported coolant fault;
- a nominal run;
- a sensor conflict;
- an unknown machine.

The demo runs in offline mode with no key. The result still comes from Python;
the offline transport only replaces the model calls.

---

## Benchmark

FabAgent is compared with raw Gemini, ChatGPT, and Nemotron-only on the same
neutral evidence. The benchmark measures **safe decisions**, not “decisiveness”:

- unsafe action rate;
- correct cause rate;
- appropriate abstention;
- false-alarm rate;
- evidence accuracy.

The protocol, cases, rubric, and fairness rules are in
[`docs/EVALUATION.md`](docs/EVALUATION.md). On the fixed eight-case evidence set
(2026-10-27), the deterministic gate reference made **0/8 unsafe actions**; the
live Nemotron-only run made **4/8 unsafe actions** and false-alarmed on the
nominal case. The naive prompt does not receive the saved tool-model checks, so
this is a workflow comparison, not a pure gate ablation. The aggregate is in
[`benchmarks/evaluator/results/naive_llm/2026-10-27/summary.json`](benchmarks/evaluator/results/naive_llm/2026-10-27/summary.json).
The old 100%/0% table was based on prompts that leaked the answer and is not
used.

---

## What FabAgent is not

- Not autonomous RCA. A human confirms every action.
- Not field validation. Public and synthetic datasets test the reasoning pattern,
  not a modern fab’s physics.
- Not a recipe controller. It never changes a recipe and never holds a lot.
- Not a replacement for a process engineer. It is a first-pass triage and an
  onboarding aid.

---

## Docs

| Doc | What it covers |
|---|---|
| [`docs/PRODUCT.md`](docs/PRODUCT.md) | Product definition and the judge story |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Current and hybrid architecture, contracts |
| [`docs/UI_VOCABULARY.md`](docs/UI_VOCABULARY.md) | The six words and copy rules |
| [`docs/YAML_GUIDE.md`](docs/YAML_GUIDE.md) | Tool model |
| [`docs/EVALUATION.md`](docs/EVALUATION.md) | Fair benchmark vs Gemini/ChatGPT |
| [`docs/DATASETS.md`](docs/DATASETS.md) | PHM/TEP/synthetic limits |
| [`docs/STATUS.md`](docs/STATUS.md) | Verified state and known issues |
| [`docs/HYBRID_IMPLEMENTATION.md`](docs/HYBRID_IMPLEMENTATION.md) | Implementation entrypoint |
| [`docs/SUBMISSION.md`](docs/SUBMISSION.md) | Hackathon checklist |

---

## Built with

- **NVIDIA Nemotron** through **Nebius Token Factory** — mapping, cause finding,
  challenge, explanation.
- **Nebius AI Cloud** — deployment target.
- **Tavily** — bounded public troubleshooting leads; never evidence.
- **DuckDB** — local, bounded telemetry analysis.
- **Streamlit** — the engineer UI.

## License

Apache 2.0. See [`LICENSE`](LICENSE).
