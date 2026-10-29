# FabAgent

**A deterministic troubleshooting and RCA copilot for manufacturing and
industrial operations, with a focus on semiconductor fabs.**

> **Nebius × NVIDIA Global AI Hackathon — Best Apps and Agents Track**
>
> **Live demo:** <https://213-239-184-219.nip.io> · **City award:** Taipei
>
> Deployed on a **Nebius AI Cloud** VM, powered by **NVIDIA Nemotron** served
> through **Nebius Token Factory**, with **Tavily** research at runtime.

FabAgent reads a tool’s sensor CSV, builds a normal reference, turns the readings
into evidence records, and checks them against a short, engineer-editable tool
model. It returns one of six plain results — **Fault Confirmed**, **Regular
Behavior**, **Sensors Disagree**, **Data Incomplete**, **Needs Review**, or
**Unknown Machine** — and one safe next step.

The rule is simple:

> **NVIDIA Nemotron reasons. Tavily researches. Python checks. The engineer decides.**

A human always confirms the action. FabAgent never changes a recipe and never
holds a lot.

> **Build status (2026-10-29):** the deterministic engine, UI, demo, offline
> fallback, Auto column mapping, tool model, coverage, differential, challenge
> layer, and fair benchmark are implemented and verified. No old 100%/0% number
> is used. See [`docs/STATUS.md`](docs/STATUS.md).

---

## Why

A fab tool streams hundreds of channels. When an alarm fires, a junior engineer
has to decide whether a coolant drop is a real equipment fault, a failing sensor,
a downstream symptom, or normal recipe behaviour. The same problem appears on any
instrumented manufacturing line: the telemetry is rich, the time is short, and a
wrong action is expensive.

A naive LLM is fluent but it cannot prove coverage, cannot detect a contradiction
deterministically, and may recommend a recipe change on a single noisy channel.
FabAgent keeps the AI useful without handing it the decision:

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

## Hackathon fit

FabAgent is submitted to the **Best Apps and Agents** track. It is a usable
copilot for a real audience — manufacturing and fab engineers — not a robotics or
embodied-edge system. The project makes live runtime calls to NVIDIA Nemotron
through Nebius Token Factory, runs on a Nebius AI Cloud VM, and calls Tavily at
runtime for bounded public research. It is also eligible for the **Best Use of
Tavily** bonus and the **Taipei** city award.

The Physical AI track would require at least one minute of physical
hardware/robot footage and an embodied or edge-agent design. FabAgent analyzes
tool telemetry; it does not sense or actuate in the physical world. Best Apps and
Agents is the honest fit.

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

The engineer reviews the guessed columns, downloads the draft YAML, edits it,
and pastes it back as a tool model on a later run. The hosted UI is stateless:
it does not write shared config files. The next run is deterministic once the
reviewed model is deployed or pasted. **Start in Auto, promote to
Engineer-defined.**

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
│ Tavily research: public troubleshooting leads on uncertain results  │
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

The hosted demo is <https://213-239-184-219.nip.io>. To run it yourself, you need
Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

```sh
uv sync
cp .env.example .env          # add NEBIUS_API_KEY and TAVILY_API_KEY
.venv/bin/streamlit run src/ui/app.py
```

Open <http://localhost:8501>. Without a server key the app uses the
deterministic offline fixture. Add the server keys for live NVIDIA Nemotron and
Tavily research.

### Run with Docker (local)

```sh
docker build -t fabagent .
docker run -p 8501:8501 --env-file .env fabagent
```

Environment:

| Variable | Used for |
|---|---|
| `NEBIUS_API_KEY` | NVIDIA Nemotron through Nebius Token Factory |
| `TAVILY_API_KEY` | Public troubleshooting leads on uncertain results |
| `FABAGENT_MODEL_CONFIG` | Optional path to `config/models.yaml` |

Keys are server-side only. They are never sent to the browser and never logged.

### Deploy on a Nebius VM

See [`docs/DEPLOY.md`](docs/DEPLOY.md) for Docker and systemd examples, the
health endpoint, key handling, and the pre-video checklist. The hosted UI is
read-only for tool models: users can download a draft YAML, but saving a new
shared model is a deliberate repository/deployment step.

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
[`docs/EVALUATION.md`](docs/EVALUATION.md). The matched four-case head-to-head
(2026-10-28, evidence track) is:

| System | Unsafe | Correct cause | Abstention | n |
|---|---:|---:|---:|---:|
| **FabAgent** | **0/4** | **3/3 scored** | **1/1** | 4 |
| Gemini 3.8 Flash (medium) | 1/4 | 1/3 scored | 0/1 | 4 |
| GPT-5.6 Luna | 0/4 | 1/3 scored | 1/1 | 4 |

Gemini inspected the part on the missing-channel case; GPT-5.6 stayed safe but
rarely committed to a cause, and named the cause only where “unknown” was the
correct answer. The raw-CSV track shows the same ordering. The full eight-case
FabAgent vs Nemotron-only workflow comparison is **0/8 vs 2/8 unsafe**, with a
false alarm on the nominal case. The naive prompt does not receive the saved tool-model checks,
so this is a workflow comparison, not a pure gate ablation. Artifacts:
[`head_to_head.json`](benchmarks/evaluator/results/naive_llm/2026-10-28/head_to_head.json)
and [`summary.json`](benchmarks/evaluator/results/naive_llm/2026-10-28/summary.json).
The old 100%/0% table was based on prompts that leaked the answer and is not
used.

---

## What FabAgent is not

- Not autonomous RCA. A human confirms every action.
- Not field validation. Public and synthetic datasets test the reasoning pattern,
  not a modern fab’s physics.
- Not a recipe controller. Its action enum cannot represent a recipe change or a
  lot hold — in a fab, that is the difference between a copilot and a production
  risk.
- Not a replacement for a process engineer. It is a first-pass triage and an
  onboarding aid.

---

## Docs

| Doc | What it covers |
|---|---|
| [`docs/PRODUCT.md`](docs/PRODUCT.md) | Product definition and the judge story |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Current architecture, contracts, invariants |
| [`docs/UI_VOCABULARY.md`](docs/UI_VOCABULARY.md) | The six words and copy rules |
| [`docs/YAML_GUIDE.md`](docs/YAML_GUIDE.md) | Tool model |
| [`docs/EVALUATION.md`](docs/EVALUATION.md) | Fair benchmark vs Gemini/ChatGPT |
| [`docs/DATASETS.md`](docs/DATASETS.md) | PHM/TEP/synthetic limits |
| [`docs/STATUS.md`](docs/STATUS.md) | Verified state and known issues |
| [`docs/DEPLOY.md`](docs/DEPLOY.md) | Nebius VM deployment and the pre-video checklist |
| [`docs/ANTI_GOALS.md`](docs/ANTI_GOALS.md) | Hard prohibitions and rejected designs |
| [`docs/SUBMISSION.md`](docs/SUBMISSION.md) | Hackathon checklist |

---

## Built with

- **NVIDIA Nemotron** through **Nebius Token Factory** — the live AI reasoning
  layer: mapping, cause finding, challenge, explanation. The hosted demo makes
  real runtime calls to the Token Factory inference API.
- **Nebius AI Cloud** — the hosted demo runs on a Nebius VM with server-side keys.
- **Tavily** — the live external research layer: bounded public troubleshooting
  leads when the data is uncertain; never evidence. The hosted demo makes real
  runtime Tavily API calls.
- **DuckDB** — local, bounded telemetry analysis.
- **Streamlit** — the engineer UI.

## Feedback on the Nebius stack

- **Token Factory’s OpenAI-compatible API** kept the client small: one transport,
  one key path, and no provider-specific SDK in the product.
- **Nemotron 3.5 Lightning** is fast enough for interactive column mapping and
  cause finding. The bounded evidence summary keeps latency and cost predictable.
- **Structured output still needs a validator.** The app treats a malformed or
  unresolved model response as a failed model call; the Python result still runs.
- **Tavily is a good fit for bounded research**, but the query matters. Sending
  signal labels plus the configured claim is materially better than sending raw
  column names.
- **What would help:** clearer per-model capability metadata (structured output,
  context limits, cold-start behavior) and stable model aliases in the Token
  Factory catalog.
- **What we did not use:** Serverless Jobs or Serverless Endpoints. This app is a
  long-lived Streamlit process with request-time inference, so a VM was the
  simpler deployment.

## License

Apache 2.0. See [`LICENSE`](LICENSE).
