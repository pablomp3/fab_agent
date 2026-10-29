# A fab copilot that shows its evidence

A semiconductor tool streams hundreds of channels. When an alarm fires, an
engineer has to decide whether a coolant drop is a real equipment fault, a
failing sensor, a downstream symptom, or normal recipe behaviour.

**FabAgent turns that CSV into one defensible next step.** It builds a normal
reference, scores every declared signal, checks the engineer's saved fault
patterns, and returns one of six plain results — with the evidence and the
contradiction attached.

> **NVIDIA Nemotron reasons. Tavily researches. Python checks. The engineer decides.**

---

## Why it matters

| Persona | What is expensive today | What FabAgent changes |
| --- | --- | --- |
| **Junior engineer** | Hundreds of time series, unfamiliar alarms, no clear next step | One plain result, one safe action, and the exact signals behind it |
| **Senior process engineer** | Black-box AI, hidden thresholds, unauditable advice | An editable tool model, visible checks, and a full audit trail |
| **Fab operations** | False alarms, unnecessary downtime, a recipe change on one noisy channel | Sensor conflicts are caught before a recipe change; missing data fails closed |

The value is not “another chatbot.” It is **decision hygiene**: the same input
gives the same answer, every claim is traceable, and the system abstains when
the data cannot support an action.

---

## How a run works

1. **Read the export.** The CSV is matched to a saved tool model, or Auto mode
   drafts one.
2. **Build normal and evidence.** A lead-in or saved normal file defines
   “normal”; every declared signal becomes an anomaly, nominal, or missing
   record with an evidence ID.
3. **Ask Nemotron to help.** It maps unknown columns, proposes causes, and
   challenges the leading cause. Tavily adds public leads only when the data is
   uncertain.
4. **Let Python decide.** Python resolves every citation, applies coverage and
   contradictions, and returns one of six results with one safe next step.

---

## What makes it different

- **The gate is deterministic.** DuckDB builds the statistics; Python owns the
  result and the action.
- **The model is useful, not authoritative.** Nemotron never owns the verdict.
- **Contradictions are absolute.** If a signal moves but the channels that
  should agree stay flat, the result is **Sensors Disagree**, not a fault.
- **Nothing large is hidden.** “What else moved” lists every unexplained
  declared signal; a large one prevents a bare **Fault Confirmed**.
- **The action is typed.** There is no recipe change and no lot hold in the
  action set. A human confirms the next step.

---

## What FabAgent will never do

- **Never change a recipe or hold a lot.** A human confirms every action.
- **Never treat model prose as evidence.** Every citation is resolved against
  the data.
- **Never invent tool physics.** Unknown units and thresholds stay `None`.
- **Never send raw telemetry to the model.** Only a bounded summary leaves the
  process.
- **Never hide a missing channel or an unexplained anomaly.**
