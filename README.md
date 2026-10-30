# FabAgent

**An AI troubleshooting copilot for factory machines that refuses to guess the diagnosis.**

[![Live demo](https://img.shields.io/badge/live-demo-0B6E99?style=flat-square)](https://213-239-184-219.nip.io)
[![Nebius x NVIDIA](https://img.shields.io/badge/Nebius%20x%20NVIDIA-Best%20Apps%20and%20Agents-76B900?style=flat-square)](https://213-239-184-219.nip.io)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square)](pyproject.toml)

When a chip-factory machine raises an alarm, FabAgent reads its sensor log (a CSV
file), works out what went wrong, and gives the on-call engineer **one safe next
step** — or says plainly that the data is not enough to decide.

**NVIDIA Nemotron reasons. Tavily researches. Python decides. The engineer acts.**

> **Live demo:** <https://213-239-184-219.nip.io>
>
> **Track:** Best Apps and Agents · **City:** Taipei
>
> **Runs on:** Nebius AI Cloud · **Inference:** Nebius Token Factory
> (`nvidia/Nemotron-3-Ultra-550b-a55b`, `nvidia/Nemotron-3_5-Lightning`)

---

## A chip factory in 30 seconds

No semiconductor background needed. Five words are enough:

| Term | Plain meaning |
|---|---|
| **Fab** | A semiconductor factory, where chips are made. |
| **Tool** | One machine in the fab (etcher, deposition chamber, ion mill). A fab runs hundreds of them; each logs dozens of sensors — coolant flow, chamber pressure, RF power, and so on. |
| **Wafer** | The thin silicon disc that chips are built on. One wafer holds hundreds of chips. |
| **Lot** | A batch of wafers (usually 25) that travels through the tools together. |
| **Recipe** | The exact step-by-step settings a tool uses to process a wafer. |

A chip passes through hundreds of these steps. If one tool misbehaves, every
wafer that follows it can be ruined (**scrapped**).

---

## The problem: the 2 AM alarm

A tool raises an alarm in the middle of the night. The on-call engineer exports
the tool's sensor log and has minutes to answer one question:

> Is this a **real hardware fault**, a **broken sensor**, a **knock-on effect**
> of something upstream, or **normal behaviour** that only looks odd?

Both wrong answers are expensive:

| Wrong call | What happens |
|---|---|
| **Act on a broken sensor** — open the machine or change the recipe because one faulty sensor spiked | The tool stops for hours while engineers chase a problem that does not exist. |
| **Miss a real fault** — keep running, or fix the wrong part because data was missing | Every lot that follows is at risk of being scrapped. |

The exact cost depends on the fab and process, so FabAgent claims no dollar
figure.

### Why not just ask a chatbot?

LLMs are fast and fluent, but on our benchmark (below) one raw frontier model told
the engineer to **inspect the hardware when a required sensor was missing**, while
another escalated almost every case without naming a cause. Neither works at
2 AM: a chatbot cannot prove it checked every sensor, cannot spot contradicting
sensors, and nothing stops it from suggesting a recipe change.

### Why not just write rules?

Fixed rules are safe on machines someone has already described, but they need a
manual mapping and a hand-written model first, and they cannot challenge their own
conclusion.

**FabAgent combines both:** NVIDIA Nemotron does the parts that need reasoning,
and plain Python code owns the final decision.

---

## What FabAgent does

Everything starts with the **tool-data CSV an engineer exports from the
machine**. Four layers run in order:

1. **Reads the sensor log locally.** DuckDB compares each sensor with its own
   normal behaviour and reduces thousands of rows to a few findings, each with
   an ID (`EV_…`). Raw data never leaves the server; only a summary under 2 KB
   reaches the model.
2. **Lets NVIDIA Nemotron reason over the findings.**
   - **New machine?** *Nemotron 3 Ultra* guesses what each column means and
     drafts a starter **tool model** (a short YAML file saying which sensors
     matter and what a fault looks like). The engineer reviews it once; later
     runs are deterministic.
   - **Known machine?** *Nemotron 3.5 Lightning* proposes likely causes, then
     **challenges its leading cause** by naming a sensor that should have moved
     if it were real. Python checks that test against the data and downgrades the
     result if it fails.
3. **Lets Python make the decision.** It re-checks every finding the model
   cites, refuses to confirm a fault while a large movement is unexplained,
   treats a sensor contradiction as a hard stop, and picks one action from a
   fixed list. *Change the recipe* and *hold the lot* are not on that list, so no
   model output can produce them.
4. **Researches only when unsure.** If the result is uncertain, the sensors
   disagree, or the machine is unknown, Tavily searches public troubleshooting
   material using plain sensor labels (e.g. `RF power`) — never raw readings or
   engineer notes. Links appear as leads for a human and cannot change the
   result.

```
1 · Local triage          2 · AI reasoning               3 · Decision + research      4 · Result
sensor CSV ──► DuckDB ──► NVIDIA Nemotron           ──► Python checks          ──► one of six results
< 2 KB summary            Ultra: maps new machines        coverage · contradiction     + one safe next step
with evidence IDs         Lightning: causes · challenge   Tavily only if unsure        engineer confirms
```

| Step | What happens | Runs on |
|---|---|---|
| **1 · Local triage** | Match the CSV to a saved tool model (or switch to Auto mode), build the normal reference, and emit one finding per sensor. | DuckDB + Python on a Nebius AI Cloud VM |
| **2 · AI reasoning** | Map an unknown machine and draft its tool model; propose causes with evidence IDs; challenge the leading cause; explain the result. | Nebius Token Factory: `nvidia/Nemotron-3-Ultra-550b-a55b` (mapping) · `nvidia/Nemotron-3_5-Lightning` (causes, challenge, explanation) |
| **3 · Decision + research** | Re-check every citation, apply coverage and contradiction rules, pick one action. Run Tavily only on uncertain or conflicting results. | Python · Tavily Search API |
| **4 · Result** | One of six plain results, one next step, the ruled-out causes, and an audit trail. | The engineer |

If data is incomplete, the model call fails, or the cause has no saved check, the
answer is **Needs Review** or **Data Incomplete** — never a guess. The hosted
**How it works** page lists the exact model IDs and live call counts.

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

The same workflow fits any machine that exports sensor data; fabs come first
because a wrong call costs the most.

---

## Why it is different

- **Evidence IDs, not prose.** Every finding has an ID; the model may cite only
  those, and Python re-checks every citation.
- **Contradictions cannot be outvoted.** If a sensor moves and its companions
  stay flat, the answer is **Sensors Disagree**, whatever the model says.
- **Fail-closed.** Incomplete data, a failed model call, or an unknown cause
  never becomes a confident diagnosis.
- **The action field cannot express an unsafe action.** It is a fixed list in
  code; recipe changes and lot holds cannot be represented.
- **Raw data stays home.** Only a small statistical summary crosses the network.

### Why the Tavily integration is not a bolt-on

- **Selective by design.** Research runs only when the result is uncertain,
  contradicted, or from an unknown machine; a confirmed fault skips the call.
- **Sanitized.** `build_tavily_query` sends the fault name and up to three human
  sensor labels (e.g. `RF power`, not `sensor_17`) — never readings, units, time
  windows, or notes.
- **Isolated.** Results appear as public leads in their own tab and cannot change
  the evidence, a citation, or the result.

---

## Benchmark

We compare safe decisions and correct causes on fixed cases with known answers
(an injected simulator fault, or a label from a public dataset). The goal is the
right action — or a safe "I don't know".

**Score** = safe actions + correct causes + appropriate abstentions (correctly
saying "not enough data"). **Unsafe** means a recipe change, holding the lot, or
inspecting hardware on a healthy run, a sensor conflict, or a file missing a
required sensor. FabAgent rows show Python's decision; no model response can
change it.

### Benchmark 1 — FabAgent vs frontier LLMs (prompt + evidence summary)

| System | Unsafe actions | Correct cause | Abstention | Score |
|---|---:|---:|---:|---:|
| **FabAgent** | **0/4** | **3/3** | **1/1** | **8/8** |
| Gemini 3.8 Flash (medium) | 1/4 | 1/3 | 0/1 | 4/8 |
| GPT-5.6 Luna | 0/4 | 1/3 | 1/1 | 6/8 |

#### What each system actually recommended

For the same four cases: action chosen and, where scored, cause named
(✓ correct, ✗ wrong).

| # | Case | FabAgent | Gemini 3.8 Flash | GPT-5.6 Luna |
|---:|---|---|---|---|
| 1 | Real ion-mill coolant fault, but other sensors also moved unexplained *(cause not scored; tests restraint)* | Ask an engineer | Inspect the part | Ask an engineer |
| 2 | Chemical-plant feed failure: upstream cause vs. pressure symptom | Ask an engineer · upstream feed ✓ | Ask an engineer · unknown ✗ | Ask an engineer · unknown ✗ |
| 3 | One RF sensor spikes, its companion sensors stay flat | Check the sensor · sensor fault ✓ | Check the sensor · sensor fault ✓ | Ask an engineer · unknown ✗ |
| 4 | Coolant fault with a required sensor missing from the file | Get more data · unknown ✓ | **Inspect the part (unsafe)** · equipment fault ✗ | Ask an engineer · unknown ✓ |

The risk is two-sided: Gemini inspects hardware when a required coolant-flow
sensor is missing; GPT-5.6 avoids unsafe actions but misses the feed failure and
the sensor conflict. FabAgent alone has zero unsafe actions and the correct cause
on every scored case.

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

This is the core design result. Deciding alone, the model sees only anonymous
sensor names (`sensor_17`, `XMEAS(1)`) and no machine description, so it guesses:
it inspects hardware on two sensor conflicts and raises a false alarm on a
healthy run. FabAgent instead uses the model to map, propose, challenge, and
explain, while Python decides. The FabAgent row is Python's decision with model
calls replaced by a fixed offline fixture, so the safety reflects the workflow,
not a lucky response. Since the zero-shot arm lacks the saved checks, this is a
**workflow comparison**, not a pure ablation; all three benchmarks are
known-answer tests, not field accuracy in a production fab.

Datasets: the [PHM 2018](docs/DATASETS.md) ion-mill set (real tool telemetry),
the Tennessee Eastman Process (a public chemical-plant simulation for
cause-vs-symptom tests), and a seeded synthetic twin. Protocol, cases, rubric, and
artifacts: [`docs/EVALUATION.md`](docs/EVALUATION.md) and
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
  one key path, no provider SDK.
- **Two tiers, two timeouts.** `nvidia/Nemotron-3-Ultra-550b-a55b` (60 s) runs the
  one-shot unknown-machine mapping; `nvidia/Nemotron-3_5-Lightning` (30 s) keeps
  causes, challenge, and explanation responsive. Two explicit routes beat one
  large model everywhere.
- **Structured output still needs a validator.** We saw `schema_validation` /
  `malformed_json`, `finish_reason=length` when reasoning tokens exhaust the
  completion budget, and unresolved `EV_*` citations. Each counts as a failed
  model call, so the Python result still runs. For fail-closed industrial use we
  would ask for strict JSON-schema decoding and a separate reasoning-token budget.
- **Tavily suits bounded research**, but the query matters: sensor labels plus the
  configured fault name beat raw column names.
- **Not used:** Serverless Jobs or Serverless Endpoints. A long-lived Streamlit
  app with request-time inference made a Nebius VM simpler.

---

## License

Apache 2.0. See [`LICENSE`](LICENSE).

---

Built by [Pablo](https://pablomp3.github.io/) · [LinkedIn](https://www.linkedin.com/in/pablomp3/)
