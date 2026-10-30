# FabAgent — product definition

**One line:** FabAgent is an AI troubleshooting and root-cause analysis (RCA)
copilot for factory machines, built first for semiconductor **fabs** (chip
factories). It reads a machine's sensor CSV log, checks it against a saved
description of the machine, and gives the on-call engineer **one safe next
step** — or says plainly that the data is not enough.

## Factory terms in plain English

| Term | Meaning |
|---|---|
| **Fab** | A semiconductor factory where chips are made. |
| **Tool** | One machine in the fab (an etcher, deposition chamber, or ion mill) that logs dozens of sensors. |
| **Wafer & lot** | A **wafer** is the silicon disc chips are built on; a **lot** is a batch of ~25 wafers that travels together. Ruined wafers are **scrapped**. |
| **Recipe** | The exact step-by-step settings a tool uses to process a wafer. |

## The problem: the 2 AM alarm

When a tool alarms, an engineer has minutes to decide whether a coolant drop is
a real hardware fault, a broken sensor, a knock-on symptom of something
upstream, or normal recipe behaviour. Both wrong answers are expensive:
opening a machine or changing its recipe on a broken sensor stops production
for hours, while missing a real fault puts subsequent wafer lots at risk of
scrap. The exact cost depends on the fab and the process; FabAgent does not
claim a dollar figure.

Neither a raw chatbot nor a static rule script solves this alone:
- **A raw LLM** is fast, but on our benchmark a frontier model told the engineer
  to inspect hardware when a required sensor was missing, while another hedged
  on every case.
- **Static rules** are safe on known machines, but they need a manual mapping and
  a hand-written model before they can run, and they cannot challenge their own
  conclusion.

FabAgent is built around one rule:

> **NVIDIA Nemotron reasons. Tavily researches. Python checks. The engineer decides.**

The first target is semiconductor fabs. The same workflow applies to any
instrumented factory machine that exports a CSV and has an engineer-authored
tool model.

## Two ways to use it (Day 1 → Day 2 flywheel)

### 1. Auto mode (Day 1 — first look at an unknown machine)

No saved tool model yet? FabAgent does not guess a diagnosis. It does three
bounded things:

1. **Column mapper (`Nemotron 3 Ultra`)** — proposes what each column means from
   names and bounded statistics, and drafts a starter YAML tool model. Python
   validates every column against the file.
2. **Cause finder (`Nemotron 3.5 Lightning`)** — proposes possible causes from
   the evidence.
3. **Python check** — because no saved check backs the proposal yet, the result
   stays **Unknown Machine** / **Needs Review**, never **Fault Confirmed**.

The engineer reviews the guessed columns, downloads the draft YAML, adds a
fault check, and uses it on later runs. The hosted UI is stateless: it never
overwrites shared config files for other visitors.

### 2. Engineer-defined mode (Day 2+ — safe, repeatable runs)

Once the engineer has a **tool model** — a short YAML file that says which
columns matter, what normal looks like, and which patterns count as a fault —
the run is deterministic:

```
CSV → DuckDB normal reference & evidence (<2 KB) → Nemotron cause & challenge
    → Python coverage, contradiction & action → Tavily if uncertain → Result
```

The same input and the same tool model produce the same result. **Nemotron 3.5
Lightning** writes the explanation and runs a disconfirming **challenge check**
to test whether another sensor contradicts the leading cause; a temporary model
outage leaves the Python decision intact.

## The six results a user sees

| Result | What it means | What to do |
|---|---|---|
| **Fault Confirmed** | The evidence supports the suspected fault. | Inspect the named part. |
| **Regular Behavior** | Every checked signal is normal. | Keep monitoring. |
| **Sensors Disagree** | One signal moved; the signals that should agree did not. | Check the sensor first. |
| **Data Incomplete** | A required signal is missing. | Get the missing data. |
| **Needs Review** | The data is not enough to confirm or rule out a cause. | Ask an engineer to review. |
| **Unknown Machine** | The export does not match a saved tool model. | Review the guessed columns. |

These are the only result words shown in the main UI. Internal enum names are
kept in the audit view, not in the main flow.

## What makes it different

- **Evidence IDs, not prose.** Every signal finding has an ID. The model may cite
  only those IDs; Python resolves every citation.
- **A deterministic gate.** Coverage, missing channels, contradictions, and the
  allowed action are computed in Python. A contradiction is absolute; it cannot
  be outvoted by other evidence.
- **Fail-closed by default.** If the data is incomplete, the model fails, or the
  cause is not configured, the result is **Needs Review** / **Data Incomplete**,
  not a guess.
- **No recipe or hold actions.** The action set is small and typed. A recipe
  change or lot hold cannot be represented.
- **Bounded payload.** Only a small statistical summary leaves the process; the
  raw telemetry stays in DuckDB.
- **Plain language.** The UI uses the six result words above, not “veto”,
  “experimental”, or “unverified class”.

## What it is not

- Not autonomous RCA. A human confirms every action.
- Not field validation. Public and synthetic datasets test the reasoning pattern,
  not a modern fab’s physics.
- Not a recipe controller. Its action enum cannot represent a recipe change or a
  lot hold — in a fab, that is the difference between a copilot and a production
  risk.
- Not a replacement for a process engineer. It is a first-pass triage and an
  onboarding aid.

## Who it is for

| Persona | What they get |
|---|---|
| On-call / junior engineer | A plain-language result and one next step, without hallucinated advice. |
| Senior process engineer | A transparent tool model, editable thresholds, and an audit trail. |
| Fab operations manager | Fewer false alarms, sensor faults caught before recipe changes, and a clear abstention path. |

## The 30-second judge story

1. Pick a prepared tool export, or upload one from an unseen machine.
2. **NVIDIA Nemotron** maps unknown columns, proposes possible causes, and
   challenges the leading cause.
3. **Python** checks every citation, coverage, and contradiction; an
   unconfigured cause stays **Needs Review**.
4. **Tavily** adds public troubleshooting leads only when the result is
   uncertain, using only human sensor labels; raw readings, units, time
   windows, and engineer notes never leave the process.
5. The engineer downloads the draft YAML, adds one fault check, and re-runs:
   FabAgent matches the saved model and returns a deterministic, auditable next
   step.

That is the product thesis: **the AI reasons and challenges; Python checks and
decides; the engineer stays in control.**
