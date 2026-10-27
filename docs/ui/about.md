# A fab copilot that shows its evidence

A semiconductor tool streams hundreds of channels. When an alarm fires, an
engineer has to decide whether a coolant drop is a real equipment fault, a
failing sensor, a downstream symptom, or normal recipe behaviour.

**FabAgent turns that CSV into one defensible next step.** It builds a normal
reference, scores every declared signal, checks the engineer's saved fault
patterns, and returns one of six plain results — with the evidence and the
contradiction attached.

> **Nemotron proposes. Python checks. The engineer decides.**

---

## Why it matters

| Persona | What is expensive today | What FabAgent changes |
| --- | --- | --- |
| **Junior engineer** | Hundreds of time series, unfamiliar alarm codes, no clear next step | One plain result, one safe action, and the exact signals behind it |
| **Senior process engineer** | Black-box AI, hidden thresholds, unauditable advice | An editable tool model, visible checks, and a full audit trail |
| **Fab operations** | False alarms, unnecessary downtime, a recipe change on one noisy channel | Sensor conflicts are caught before a recipe change; missing data fails closed |

The value is not “another chatbot.” It is **decision hygiene**: the same input
gives the same answer, every claim is traceable, and the system abstains when
the data cannot support an action.

---

## What makes it different

- **The gate is deterministic.** DuckDB builds the statistics; Python resolves
  every evidence ID, applies coverage, and chooses the action.
- **The model is useful, not authoritative.** Nemotron maps unknown columns,
  proposes causes, challenges the leading cause, and writes the explanation.
  It never owns the verdict.
- **Contradictions are absolute.** If a signal moves but the channels that
  should agree stay flat, the result is **Sensors Disagree**, not a fault.
- **Nothing large is hidden.** “What else moved” lists every unexplained
  declared signal; a large one prevents a bare **Fault Confirmed**.
- **The action is typed.** The action set contains no recipe change and no lot
  hold. A human confirms the next step.

---

## How a run works

1. **Read the export.** The CSV is matched to a saved tool model, or Auto mode
   drafts one.
2. **Build normal.** A lead-in, a saved normal file, or a recipe-step reference
   defines what “normal” means.
3. **Create evidence.** Every declared signal becomes an anomaly, nominal, or
   missing record with an ID.
4. **Run the checks.** Python scores every saved fault pattern, coverage, and
   contradiction.
5. **Ask the model to help.** Nemotron proposes causes and one disconfirming
   test; Python evaluates the citations and the test.
6. **Return one result.** One of six words, one safe next step, and an audit
   trail a reviewer can follow.

---

## What FabAgent will never do

- **Never change a recipe autonomously.** A human confirms every action.
- **Never treat model prose as evidence.** Every citation is resolved against
  the data.
- **Never invent tool physics.** Unknown units, thresholds, and relationships
  stay `None`.
- **Never send raw telemetry to the model.** Only a bounded summary leaves the
  process.
- **Never call a single sensor spike a confirmed fault when the companions
  disagree.**
- **Never hide an unexplained anomaly.** It appears in the result and can push
  the outcome to **Needs Review**.
