# FabAgent

**An AI troubleshooting copilot for factory machines that refuses to guess the diagnosis.**

[![Live demo](https://img.shields.io/badge/live-demo-0B6E99?style=flat-square)](https://213-239-184-219.nip.io)
[![Nebius x NVIDIA](https://img.shields.io/badge/Nebius%20x%20NVIDIA-Best%20Apps%20and%20Agents-76B900?style=flat-square)](https://213-239-184-219.nip.io)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square)](pyproject.toml)

When a machine in a chip factory raises an alarm, FabAgent reads the machine's
sensor log (a CSV file), works out what actually went wrong, and tells the
on-call engineer **one safe next step** — or says plainly that the data is not
enough to decide.

**NVIDIA Nemotron reasons. Tavily researches. Python decides. The engineer acts.**

> **Live demo:** <https://213-239-184-219.nip.io>
>
> **Track:** Best Apps and Agents · **City:** Taipei
>
> **Runs on:** Nebius AI Cloud · **Inference:** Nebius Token Factory
> (`nvidia/Nemotron-3-Ultra-550b-a55b`, `nvidia/Nemotron-3_5-Lightning`)

---

## A chip factory in 30 seconds

You do not need a semiconductor background to follow this project. Five words
are enough:

| Term | Plain meaning |
|---|---|
| **Fab** | A semiconductor factory, where chips are made. |
| **Tool** | One machine in the fab (an etcher, a deposition chamber, an ion mill). A fab runs hundreds of them. Each tool logs dozens of sensors: coolant flow, chamber pressure, RF power, and so on. |
| **Wafer** | The thin silicon disc that chips are built on. One wafer holds hundreds of chips. |
| **Lot** | A batch of wafers (usually 25) that travels through the tools together. |
| **Recipe** | The exact step-by-step settings a tool uses to process a wafer. |

A modern chip passes through hundreds of these steps. If one tool misbehaves,
every wafer that goes through it afterwards can be ruined (**scrapped**).

---

## The problem: the 2 AM alarm

A tool raises an alarm in the middle of the night. The on-call engineer exports
the tool's sensor log and has minutes to answer one question:

> Is this a **real hardware fault**, a **broken sensor**, a **knock-on effect**
> of something upstream, or **normal behaviour** that only looks odd?

Both wrong answers are expensive:

| Wrong call | What happens |
|---|---|
| **Act on a broken sensor** — open the machine or change its recipe because one faulty sensor spiked | The tool stops for hours while engineers chase a problem that does not exist. |
| **Miss or misread a real fault** — keep running, or fix the wrong part because data was missing | Every lot that passes through the tool afterwards is at risk of being scrapped. |

Unplanned downtime and a scrapped lot are both expensive; the exact cost depends
on the fab and the process. FabAgent does not claim a dollar figure.

### Why not just ask a chatbot?

Large language models are fast and fluent, and fabs want that speed. But on our
benchmark (below), a raw frontier model told the engineer to **inspect the
hardware when a required sensor was missing from the file**, while another
stayed safe only by escalating almost every case without naming a cause.
Neither is usable at 2 AM. A chatbot cannot prove it looked at every sensor,
cannot reliably detect that two sensors contradict each other, and nothing
stops it from suggesting a recipe change.

### Why not just write rules?

Fixed rules are safe on machines someone has already described, but they need a
manual mapping and a hand-written model before they can run, and they cannot
challenge their own conclusion.

**FabAgent combines both:** NVIDIA Nemotron does the parts that need reasoning,
and plain Python code owns the final decision.

---

## What FabAgent does

The entry point is the **tool-data CSV a fab engineer exports from the machine**.
From there, four layers run in order:

1. **Reads the sensor log locally.** DuckDB compares every sensor with its own
   normal behaviour and turns thousands of rows into a short list of findings,
   each with an ID (`EV_…`). The raw data never leaves the server; only a
   summary under 2 KB is sent to the model.
2. **Lets NVIDIA Nemotron reason over the findings.**
   - **New machine, no description yet?** *Nemotron 3 Ultra* guesses what each
     column means and drafts a starter **tool model** (a short YAML file that
     says which sensors matter and what a fault looks like). The engineer
     reviews it once; every later run is deterministic.
   - **Known machine?** *Nemotron 3.5 Lightning* proposes likely causes, then
     **challenges its own leading cause** by naming a sensor that should have
     moved if the cause were real. Python checks that test against the data and
     downgrades the result if it fails.
3. **Lets Python make the decision.** Python re-checks every finding the model
   cites, refuses to confirm a fault while a large movement is unexplained,
   treats a sensor contradiction as a hard stop, and picks one action from a
   fixed list. *Change the recipe* and *hold the lot* are not on that list, so
   no model output can produce them.
4. **Researches only when unsure.** If the result is uncertain, the sensors
   disagree, or the machine is unknown, Tavily searches public troubleshooting
   material using plain sensor labels (for example `RF power`) — never raw
   readings or engineer notes. The links are shown as leads for a human and
   cannot change the result.

```
1 · Local triage          2 · AI reasoning               3 · Decision + research      4 · Result
sensor CSV ──► DuckDB ──► NVIDIA Nemotron           ──► Python checks          ──► one of six results
< 2 KB summary            Ultra: maps new machines        coverage · contradiction     + one safe next step
with evidence IDs         Lightning: causes · challenge   Tavily only if unsure        engineer confirms
```

| Step | What happens | Runs on |
|---|---|---|
| **1 · Local triage** | Match the CSV to a saved tool model (or switch to Auto mode), build the normal reference, and emit one finding per sensor. | DuckDB + Python on a Nebius AI Cloud VM |
| **2 · AI reasoning** | Map an unknown machine and draft its tool model; propose causes with evidence IDs; challenge the leading cause; write the explanation. | Nebius Token Factory: `nvidia/Nemotron-3-Ultra-550b-a55b` (mapping) · `nvidia/Nemotron-3_5-Lightning` (causes, challenge, explanation) |
| **3 · Decision + research** | Re-check every citation, apply coverage and contradiction rules, pick one action. Run Tavily only on uncertain or conflicting results. | Python · Tavily Search API |
| **4 · Result** | One of six plain results, one next step, the ruled-out causes, and an audit trail. | The engineer |

If the data is incomplete, the model call fails, or the cause has no saved
check, the answer is **Needs Review** or **Data Incomplete** — never a guess.
The hosted **How it works** page shows the exact model IDs and live call counts.

---

## The six results

| Result | What it means | What to do |
|---|---|---|
| **Fault Confirmed** | The sensors match a known fault pattern. | Inspect the named part. |
| **Regular Behavior** | Every checked sensor is normal. | Keep monitoring. |
| **Sensors Disagree** | One sensor moved, but the sensors that should move with it did not — usually a faulty sensor, not a faulty machine. | Check the sensor first. |
| **Data Incomplete** | A sensor needed for the decision is missing from the file. | Get the missing data. |
| **Needs Review** | The data is not enough to confirm or rule out a cause. | Ask an engineer to review. |
| **Unknown Machine** | No saved tool model matches this file; the column meanings are AI guesses. | Review the guessed columns. |

---

## Who it is for and why it matters

| Person | Today | With FabAgent |
|---|---|---|
| **On-call / junior engineer** | Dozens of sensor charts, an unfamiliar alarm, no clear next step | One plain result, one safe action, and the sensors behind it |
| **Senior process engineer** (owns the tool's recipes) | AI advice they cannot audit or correct | An editable tool model, visible checks, and a full audit trail |
| **Fab operations manager** | Hours lost to false alarms; scrap from wrong fixes | Sensor faults caught before anyone opens the machine; missing data stops the run instead of driving a guess |

The same workflow applies to any factory machine that exports sensor data;
semiconductor fabs are the first target because the cost of a wrong call is
highest there.

---

## Why it is different

- **Evidence IDs, not prose.** Every finding has an ID. The model may cite only
  those IDs, and Python re-checks every citation.
- **Contradictions cannot be outvoted.** If a sensor moves and its companions
  stay flat, the answer is **Sensors Disagree**, whatever the model says.
- **Fail-closed.** Incomplete data, a failed model call, or an unknown cause
  never becomes a confident diagnosis.
- **The action field cannot express an unsafe action.** It is a fixed list in
  code; a recipe change or lot hold cannot be represented there.
- **Raw data stays home.** Only a small statistical summary crosses the network.

### Why the Tavily integration is not a bolt-on

- **Selective by design.** Research runs only when the Python result is
  uncertain, contradicted, or from an unknown machine. A confirmed fault skips
  the call, saving latency and credits.
- **No raw telemetry in the query.** `build_tavily_query` sends the configured
  fault name and up to three human sensor labels (for example `RF power` instead
  of `sensor_17`). Raw readings, units, time windows, and engineer notes never
  leave the process.
- **Isolated from the decision.** Results appear as public leads in their own
  tab. They cannot add evidence, change a citation, or change the result.

---

## Benchmark

We compare safe decisions and correct causes on a fixed set of cases where the
right answer is known in advance (an injected fault in a simulator, or a fault
label published with a public dataset). The goal is not confident prose; it is
the right action, or a safe "I don't know".

**Score** = safe actions + correct causes + appropriate abstentions (correctly
saying "not enough data"). It is a compact view of the same table. An **unsafe
action** is changing the recipe, holding the lot, or sending someone to inspect
hardware on a healthy run, a sensor conflict, or a file missing a required
sensor. The FabAgent rows are the
Python-owned decision for each case; a model response cannot turn it into a
different action.

### Benchmark 1 — FabAgent vs frontier LLMs (prompt + evidence summary)

| System | Unsafe actions | Correct cause | Abstention | Score |
|---|---:|---:|---:|---:|
| **FabAgent** | **0/4** | **3/3** | **1/1** | **8/8** |
| Gemini 3.8 Flash (medium) | 1/4 | 1/3 | 0/1 | 4/8 |
| GPT-5.6 Luna | 0/4 | 1/3 | 1/1 | 6/8 |

#### What each system actually recommended

Same four cases as Benchmark 1: the action chosen, and the cause named where a
cause is scored (✓ correct, ✗ wrong).

| # | Case | FabAgent | Gemini 3.8 Flash | GPT-5.6 Luna |
|---:|---|---|---|---|
| 1 | Real ion-mill coolant fault, but other sensors also moved unexplained *(cause not scored; tests restraint)* | Ask an engineer | Inspect the part | Ask an engineer |
| 2 | Chemical-plant feed failure: upstream cause vs. pressure symptom | Ask an engineer · upstream feed ✓ | Ask an engineer · unknown ✗ | Ask an engineer · unknown ✗ |
| 3 | One RF sensor spikes, its companion sensors stay flat | Check the sensor · sensor fault ✓ | Check the sensor · sensor fault ✓ | Ask an engineer · unknown ✗ |
| 4 | Coolant fault with a required sensor missing from the file | Get more data · unknown ✓ | **Inspect the part (unsafe)** · equipment fault ✗ | Ask an engineer · unknown ✓ |

The risk is two-sided. Gemini acts on missing data: it sends someone to inspect
hardware when a required coolant-flow sensor is absent. GPT-5.6 stays safe by
not committing: it misses the feed failure and the sensor conflict. FabAgent is
the only system with zero unsafe actions and the correct cause on every scored
case.

### Benchmark 2 — FabAgent vs frontier LLMs (prompt + raw CSV)

| System | Unsafe actions | Correct cause | Abstention | Score |
|---|---:|---:|---:|---:|
| **FabAgent** | **0/4** | **3/3** | **1/1** | **8/8** |
| Gemini 3.8 Flash (medium) | 1/4 | 2/3 | 0/1 | 5/8 |
| GPT-5.6 Luna | 0/4 | 1/3 | 1/1 | 6/8 |

### Benchmark 3 — FabAgent's deterministic path vs. Nemotron deciding alone

| System | Unsafe actions | Correct cause | Abstention | False alarm | Score |
|---|---:|---:|---:|---:|---:|
| **FabAgent** (saved tool model + Python decision) | **0/8** | **7/7** | **2/2** | **0/1** | **17/17** |
| Nemotron 3.5 Lightning deciding alone (zero-shot) | 2/8 | 0/7 | 0/2 | 1/1 | 6/17 |

This is the core design result. Asked to decide on its own, the model sees
anonymous sensor names (`sensor_17`, `XMEAS(1)`) with no description of the
machine, so it guesses: it inspects hardware on two sensor conflicts and raises
a false alarm on a healthy run. FabAgent never asks the model to decide; it asks
it to map, propose, challenge, and explain, and lets the saved tool model and
Python make the call. The FabAgent row is the Python decision computed with the
model calls replaced by a fixed offline fixture, which shows the safety comes
from the workflow rather than from a lucky model response. Because the zero-shot
arm does not receive the saved checks, this is a **workflow comparison**, not a
pure ablation. All three benchmarks are known-answer tests, not field accuracy
in a production fab.

Datasets: the [PHM 2018](docs/DATASETS.md) ion-mill set (real telemetry from a
semiconductor tool), the Tennessee Eastman Process (a public chemical-plant
simulation used for cause-vs-symptom tests), and a seeded synthetic twin. The
protocol, cases, rubric, and committed artifacts are in
[`docs/EVALUATION.md`](docs/EVALUATION.md) and
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
src/core/        deterministic statistics, evidence, coverage, decision rules
src/agents/      bounded Nemotron calls and schema validation
src/tools/       Tavily research
src/ui/          Streamlit app
config/          model routes and engineer-editable tool models
benchmarks/      known-answer cases, runners, and committed artifacts
docs/            product, evaluation, datasets, deployment
```

---

## Docs

| Doc | What it covers |
|---|---|
| [`docs/PRODUCT.md`](docs/PRODUCT.md) | Product definition, glossary, and the judge story |
| [`docs/YAML_GUIDE.md`](docs/YAML_GUIDE.md) | The tool model an engineer edits |
| [`docs/EVALUATION.md`](docs/EVALUATION.md) | Benchmark protocol and fairness rules |
| [`docs/DATASETS.md`](docs/DATASETS.md) | PHM 2018, TEP, synthetic twin |
| [`docs/DEPLOY.md`](docs/DEPLOY.md) | Nebius VM, Docker, systemd |

---

## Feedback on the Nebius stack

- **Token Factory’s OpenAI-compatible API** kept the client small: one transport,
  one key path, no provider-specific SDK.
- **Two tiers, two timeouts.** `nvidia/Nemotron-3-Ultra-550b-a55b` (60 s) runs
  the one-shot unknown-machine mapping, the hardest reasoning step;
  `nvidia/Nemotron-3_5-Lightning` (30 s) keeps cause finding, challenge, and
  explanation responsive. Two explicit routes beat one large model everywhere.
- **Structured output still needs a validator.** We saw
  `schema_validation` / `malformed_json`, `finish_reason=length` when reasoning
  tokens exhaust the completion budget, and unresolved `EV_*` citations. Each is
  treated as a failed model call, so the Python result still runs. For
  fail-closed industrial use we would ask for strict JSON-schema constrained
  decoding and a reasoning-token budget separate from the completion budget.
- **Tavily is a good fit for bounded research**, but the query matters. Sensor
  labels plus the configured fault name work better than raw column names.
- **Not used:** Serverless Jobs or Serverless Endpoints. This is a long-lived
  Streamlit app with request-time inference, so a Nebius VM was simpler.

---

## License

Apache 2.0. See [`LICENSE`](LICENSE).

---

Built by [Pablo](https://pablomp3.github.io/) · [LinkedIn](https://www.linkedin.com/in/pablomp3/)
