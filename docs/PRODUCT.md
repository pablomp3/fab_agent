# FabAgent — product definition

**One line:** FabAgent is a deterministic troubleshooting and RCA copilot for
manufacturing and physical-AI operations, with a focus on semiconductor tools. It
turns a CSV export into a small set of evidence records, checks them against a
saved tool model, and gives the engineer one safe next step — or says plainly
that the data is not enough.

## The problem

A fab tool streams hundreds of channels. When an alarm fires, a junior engineer
has to decide whether a coolant drop is a real equipment fault, a failing sensor,
a downstream symptom, or normal recipe behaviour. A naive LLM is fast and fluent
but it cannot prove coverage, it cannot detect a contradiction deterministically,
and it can recommend a recipe change or a hold on a single noisy channel.

FabAgent is built around one rule:

> **NVIDIA Nemotron reasons. Tavily researches. Python checks. The engineer decides.**

The first target is semiconductor fabs. The same workflow applies to any
instrumented manufacturing or physical-AI operation that can export a CSV and
describe its own tool model.

## Two ways to use it

### 1. Engineer-defined (the safe, repeatable mode)

The engineer has a **tool model** — a short YAML file that says which columns
matter, what “normal” looks like, and which patterns count as a fault. The run is
deterministic:

```
CSV → match tool model → build normal reference → evidence → fault checks
    → Python result → one safe next step
```

The same input and the same tool model produce the same result. Nemotron adds
explanation and challenge; a temporary outage does not change the result or the
action.

### 2. Auto (the first-look mode for an unknown export)

No saved tool model? FabAgent does not guess a diagnosis. It does three bounded
things:

1. **Column mapper** — Nemotron proposes what each column means, from names and
   bounded statistics. Python validates every proposal.
2. **Cause finder** — Nemotron proposes possible causes from the evidence.
3. **Python check** — each proposed cause is mapped to a configured fault check.
   A cause that is not backed by a check is shown as **Needs Review**, never as
   a confirmed fault.

The engineer reviews the guessed columns, downloads the draft, edits it, and
pastes it back as a tool model on a later run. The hosted UI is stateless: it
does not write shared config files. This is the “start in Auto, promote to
Engineer-defined” story.

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
  change cannot be represented.
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
| Junior / onboarding engineer | A plain-language result and one next step, without hallucinated advice. |
| Senior process engineer | A transparent tool model, editable thresholds, and an audit trail. |
| Fab operations manager | Fewer false alarms, sensor faults caught before recipe changes, and a clear abstention path. |

## The 30-second judge story

1. Pick a prepared tool export, or upload one from an unseen machine.
2. NVIDIA Nemotron maps unknown columns and proposes possible causes.
3. Python checks them; an unconfigured cause stays **Needs Review**.
4. Tavily adds public troubleshooting leads if the data is uncertain.
5. The engineer downloads the draft, adds one fault check in their own config
   repository, and deploys or pastes the reviewed model.
6. Upload the same export again: FabAgent matches the saved model, and the
   result is deterministic with a safe next step.

That is the product thesis: **the AI reasons and challenges; Python checks and
decides; the engineer stays in control.**
