## The problem

A fab tool alarms. The engineer has minutes to decide what to do. Three things
make that hard:

- **The signal is ambiguous.** A coolant drop can be a real leak, a failing
  sensor, a downstream symptom, or normal recipe behaviour.
- **The wrong action is expensive.** A missed fault scraps wafers; a false alarm
  stops a tool; a recipe change on one noisy channel can do both.
- **The evidence is hard to hold together.** Hundreds of channels, missing data,
  and contradictory sensors arrive faster than a human can check them. A fluent
  LLM will still guess.

**FabAgent turns that export into one defensible next step.** It builds a normal
reference, scores every declared signal, checks the engineer's saved fault
patterns, and returns one of six plain results with the evidence attached.

> **NVIDIA Nemotron reasons. Tavily researches. Python checks. The engineer decides.**

---

## What you get

| Result | What it means | What to do |
| --- | --- | --- |
| **Fault Confirmed** | The evidence supports the suspected fault. | Inspect the named part. |
| **Regular Behavior** | Every checked signal is normal. | Keep monitoring. |
| **Sensors Disagree** | One signal moved; the signals that should agree did not. | Check the sensor first. |
| **Data Incomplete** | A required signal is missing. | Get the missing data. |
| **Needs Review** | The data is not enough to confirm or rule out a cause. | Ask an engineer to review. |
| **Unknown Machine** | The export does not match a saved tool model. | Review the guessed columns. |

Every result comes with a next step, a plain-language reason, and an audit
trail. The result is computed by Python, so the same input and the same tool
model give the same answer.

---

## Built for manufacturing tools, with a focus on semiconductor fabs

The first target is semiconductor tool telemetry: etch, deposition, ion mill,
RF stations, and the public PHM/TEP benchmarks. The same evidence-gated workflow
applies to any instrumented manufacturing tool that exports sensor telemetry —
injection moulding, industrial robotics, energy equipment.

---

## Who it is for

| Persona | What is expensive today | What FabAgent changes |
| --- | --- | --- |
| **Junior engineer** | Hundreds of time series, unfamiliar alarms, no clear next step | One plain result, one safe action, and the signals behind it |
| **Senior process engineer** | Black-box AI, hidden thresholds, unauditable advice | An editable tool model, visible checks, and a full audit trail |
| **Operations manager** | False alarms, unnecessary downtime, a recipe change on one noisy channel | Sensor conflicts are caught before a recipe change; missing data fails closed |

The value is **decision hygiene**: the AI adds
reasoning and research, Python owns the decision, and the system abstains when
the data cannot support an action.

---

## Hard limits, enforced by the type system

These are not policy promises. They are properties of the code:

- **It cannot change a recipe or hold a lot.** In a fab, a wrong recipe edit can
  scrap wafers and a lot hold can stop a line. FabAgent’s action is a closed
  enum — inspect the part, keep monitoring, ask an engineer, collect more data,
  or check the sensor. A recipe edit is not representable.
- **It cannot promote a model guess into a fault.** A cause proposed by NVIDIA
  Nemotron without a saved check is **Needs Review**, never **Fault Confirmed**.
- **It cannot outvote a contradiction.** If a signal moves and the channels that
  should agree stay flat, the result is **Sensors Disagree**.
- **It cannot hide missing data.** A required channel that is absent becomes
  **Data Incomplete**.
- **It cannot send raw telemetry to the model.** Only a bounded statistical
  summary crosses the network, and every citation is re-resolved by Python.
- **It cannot confirm a fault while a large signal is unexplained.** The 5z
  coverage policy prevents a bare **Fault Confirmed**.
