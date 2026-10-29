# FabAgent

**A manufacturing RCA copilot that refuses to guess.**

[![Live demo](https://img.shields.io/badge/live-demo-0B6E99?style=flat-square)](https://213-239-184-219.nip.io)
[![Nebius x NVIDIA](https://img.shields.io/badge/Nebius%20x%20NVIDIA-Best%20Apps%20and%20Agents-76B900?style=flat-square)](https://213-239-184-219.nip.io)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square)](pyproject.toml)

FabAgent reads a tool’s sensor CSV, builds a normal reference, checks the
engineer’s saved fault patterns, and returns one of six plain results with one
safe next step.

**NVIDIA Nemotron reasons. Tavily researches. Python decides. The engineer acts.**

> **Live demo:** <https://213-239-184-219.nip.io>
>
> **Track:** Best Apps and Agents · **City:** Taipei
>
> **Runs on:** Nebius AI Cloud · **Inference:** Nebius Token Factory

---

## The problem

A fab tool streams hundreds of channels. When an alarm fires, an engineer has to
decide whether a coolant drop is a real equipment fault, a failing sensor, a
downstream symptom, or normal recipe behaviour.

A naive LLM is fluent, but it cannot prove coverage, cannot detect a
contradiction deterministically, and may recommend a recipe change on one noisy
channel. FabAgent keeps the AI useful without handing it the decision.

---

## How a run works

| Layer | What happens | Runs on |
|---|---|---|
| **1. Understand** | Nemotron maps unknown columns, proposes possible causes, and challenges the leading cause. | Nebius Token Factory: `nvidia/Nemotron-3-Ultra-550b-a55b` for unknown-machine mapping; `nvidia/Nemotron-3_5-Lightning` for cause finding, challenge, and explanation. |
| **2. Research** | Tavily finds public troubleshooting leads when the result is uncertain. They are leads, never evidence. | Tavily Search API |
| **3. Decide** | DuckDB computes robust statistics; Python builds evidence IDs, applies coverage and contradictions, and selects one safe action. | Python + DuckDB |
| **4. Act** | The engineer reviews the result, the evidence, and the audit trail, then confirms the next step. | Human |

```
CSV + tool model
      │
      ▼
Nemotron ──► Tavily ──► Python + DuckDB ──► Engineer
(mapping,     (public     (evidence,         (review,
 causes,       leads)      coverage,          confirm,
 challenge)                action)            act)
```

The model never owns the verdict. If the data is incomplete, the model fails, or
the cause is not configured, the result is **Needs Review** or **Data
Incomplete**, not a guess.

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

---

## Why it is different

- **Evidence IDs, not prose.** Every finding has an ID; the model may cite only
  those IDs; Python resolves every citation.
- **A deterministic gate.** Coverage, missing channels, contradictions, and the
  allowed action are computed in Python. A contradiction cannot be outvoted.
- **Fail-closed.** Incomplete data, a failed model call, or an unconfigured cause
  never becomes a confident diagnosis.
- **No recipe or hold action.** The action set is typed; a recipe change or lot
  hold is not representable.
- **Bounded payload.** Raw telemetry stays in DuckDB; only a small statistical
  summary crosses the network.

---

## Benchmark

We compare safe decisions and correct causes on a fixed known-answer set. The
goal is not confident prose; it is the right action, or a safe abstention.

| System | Unsafe actions | Correct cause | n |
|---|---:|---:|---:|
| **FabAgent** | **0/4** | **3/3 scored** | 4 |
| Gemini 3.8 Flash (medium) | 1/4 | 1/3 scored | 4 |
| GPT-5.6 Luna | 0/4 | 1/3 scored | 4 |

The eight-case FabAgent vs Nemotron-only workflow comparison is **0/8 vs 2/8
unsafe**, with a false alarm on the healthy run. Because the naive arm does not
receive the saved tool-model checks, this is a **workflow comparison**, not a
pure gate ablation.

These are known-answer tests, not field accuracy. The protocol, cases, rubric,
and artifacts are in [`docs/EVALUATION.md`](docs/EVALUATION.md) and
[`benchmarks/evaluator/results/naive_llm/2026-10-28/`](benchmarks/evaluator/results/naive_llm/2026-10-28/).

---

## Quickstart

Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

```sh
uv sync
cp .env.example .env          # add NEBIUS_API_KEY and TAVILY_API_KEY
.venv/bin/streamlit run src/ui/app.py
```

Open <http://localhost:8501>. Without server keys the app runs the deterministic
offline fixture; the engine, UI, and decision path are the same as the hosted
demo.

### Docker

```sh
docker build -t fabagent .
docker run -p 8501:8501 --env-file .env fabagent
```

| Variable | Used for |
|---|---|
| `NEBIUS_API_KEY` | NVIDIA Nemotron through Nebius Token Factory |
| `TAVILY_API_KEY` | Public troubleshooting leads on uncertain results |
| `FABAGENT_MODEL_CONFIG` | Optional path to `config/models.yaml` |

Keys are server-side only. They are never sent to the browser and never logged.

To deploy on a Nebius VM, see [`docs/DEPLOY.md`](docs/DEPLOY.md).

---

## Project layout

```
src/core/        deterministic statistics, evidence, coverage, gate
src/agents/      bounded Nemotron calls and schema validation
src/tools/       Tavily research
src/ui/          Streamlit app
config/          model routes and engineer-editable tool models
benchmarks/      known-answer cases, runners, and committed artifacts
docs/            product, architecture, evaluation, deployment
```

---

## Docs

| Doc | What it covers |
|---|---|
| [`docs/PRODUCT.md`](docs/PRODUCT.md) | Product definition and the judge story |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Architecture, contracts, invariants |
| [`docs/YAML_GUIDE.md`](docs/YAML_GUIDE.md) | The tool model an engineer edits |
| [`docs/EVALUATION.md`](docs/EVALUATION.md) | Benchmark protocol and fairness rules |
| [`docs/DATASETS.md`](docs/DATASETS.md) | PHM 2018, TEP, synthetic twin |
| [`docs/DEPLOY.md`](docs/DEPLOY.md) | Nebius VM, Docker, systemd |

---

## Feedback on the Nebius stack

- **Token Factory’s OpenAI-compatible API** kept the client small: one transport,
  one key path, no provider-specific SDK.
- **Nemotron 3 Ultra** is a good fit for the hard unknown-column mapping step.
  **Nemotron 3.5 Lightning** keeps cause finding, challenge, and explanation
  responsive.
- **Structured output still needs a validator.** Malformed or unresolved model
  output is treated as a failed model call; the Python result still runs.
- **Tavily is a good fit for bounded research**, but the query matters. Signal
  labels plus the configured claim work better than raw column names.
- **Not used:** Serverless Jobs or Serverless Endpoints. This is a long-lived
  Streamlit app with request-time inference, so a Nebius VM was simpler.

---

## License

Apache 2.0. See [`LICENSE`](LICENSE).

---

Built by [Pablo](https://pablomp3.github.io/) · [LinkedIn](https://www.linkedin.com/in/pablomp3/)
