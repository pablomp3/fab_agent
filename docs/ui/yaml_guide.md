#### Tool model

A tool model is the saved knowledge an engineer attaches to a machine. It
answers three questions:

1. Which columns matter?
2. What does normal look like?
3. Which patterns count as a fault, and what should we do?

> **You do not need to edit this file for a demo.** The Run page opens with a
> readable summary of the saved model. The YAML editor is an advanced surface
> for the engineer who owns the machine.

```yaml
tool:
  name: ion_mill_m02
  label: Ion Mill M02

baseline:
  mode: lead_in       # first rows of this file
  rows: 200

signals:
  - {name: FLOWCOOLFLOWRATE, label: Coolant flow, unit: null, alert_at: 3.5}
  - {name: FLOWCOOLPRESSURE, label: Coolant pressure, unit: null, alert_at: 3.5}
  - {name: IONGAUGEPRESSURE, label: Chamber pressure, unit: null, alert_at: 3.5}

checks:
  - id: coolant_leak
    label: Coolant loop fault
    kind: equipment_fault
    must_be_unusual: [FLOWCOOLFLOWRATE, FLOWCOOLPRESSURE]
    must_stay_normal: [IONGAUGEPRESSURE]
    action: INSPECT_COMPONENT
    advice: Inspect the coolant loop before changing the recipe.
```

| Setting | What it does |
| :--- | :--- |
| `signals` | The columns to check. `label` is what the user sees; `alert_at` is the sensitivity (default `3.5`). |
| `baseline` | What “normal” means: a lead-in, a separate normal file, or a recipe step. The normal view describes it in plain words, not as a path. |
| `checks` | The fault patterns. `must_be_unusual` must all move; `must_stay_normal` must all stay quiet; `action` is the suggested next step. |
| `corroborated_by` | Optional. Signals that should move together with the primary signal. If they stay flat, the result is **Sensors Disagree**. |

> **Safe by design:** a missing required signal is **Data Incomplete**. If a
> `must_stay_normal` signal also moves, the result is **Sensors Disagree**, not a
> confirmed fault. A model-proposed cause that is not in this file is **Needs
> Review**, never an action.

The full field reference is in [`../YAML_GUIDE.md`](../YAML_GUIDE.md).
