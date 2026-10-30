# Tool model YAML

A **tool model** is the one file an engineer edits to describe a factory
machine (in a chip factory, or **fab**, each machine is called a **tool**). It
answers three questions:

1. **Which sensor columns matter?** (`signals`)
2. **What does normal look like?** (`baseline`)
3. **Which patterns count as a fault, and what should we do?** (`checks`)

Everything else — evidence IDs, predicates, z-scores, coverage — is computed by
Python. The YAML does not contain a diagnosis narrative, a `candidate`, a
`predicate` block, or a `rules` block. Changing a **recipe** (the step-by-step
settings a tool uses on a wafer) or holding a **lot** (a batch of ~25 wafers)
is not an allowed action in this file.

> **Safety:** a check can only produce an action that you wrote. A model-proposed
> cause that is not in this file is shown as **Needs Review**, never as
> **Fault Confirmed**.

## 1. A complete example

```yaml

tool:
  name: ion_mill_m02
  label: Ion Mill M02
  description: Coolant loop and beam telemetry.

# What "normal" means. Choose one mode.
baseline:
  mode: lead_in        # lead_in | nominal_file | recipe_step
  rows: 200            # used by lead_in
  # file: nominal.csv  # used by nominal_file
  # step_column: recipe_step  # used by recipe_step

signals:
  - name: FLOWCOOLFLOWRATE
    label: Coolant flow
    unit: null
    alert_at: 3.5
  - name: FLOWCOOLPRESSURE
    label: Coolant pressure
    unit: null
    alert_at: 3.5
  - name: IONGAUGEPRESSURE
    label: Chamber pressure
    unit: null
    alert_at: 3.5
  - name: ETCHBEAMVOLTAGE
    label: Beam voltage
    unit: null
    alert_at: 3.5

checks:
  - id: coolant_leak
    label: Coolant loop fault
    kind: equipment_fault
    must_be_unusual:
      - signal: FLOWCOOLFLOWRATE
        direction: any
      - signal: FLOWCOOLPRESSURE
        direction: any
    must_stay_normal:
      - signal: IONGAUGEPRESSURE
    action: INSPECT_COMPONENT
    advice: Inspect the coolant loop before changing the recipe.
```

What the UI shows from this file:

- The signal labels and alert levels in the tool model card.
- Four fault checks (if there are four `checks` entries), each as a row in the
  differential table.
- For `coolant_leak`: **Fault Confirmed** only when both coolant signals are
  unusual **and** chamber pressure stays normal. If pressure also moves, the
  result is **Sensors Disagree** (or **Needs Review** if the pressure move is
  small/ambiguous).
- If `FLOWCOOLFLOWRATE` is missing: **Data Incomplete**.

## 2. Field reference

### `tool`

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | Stable id, lowercase, no spaces. Used for the filename and audit. |
| `label` | yes | Human name shown in the UI. |
| `description` | no | One sentence. |

### `baseline`

| Field | Required | Meaning |
|---|---|---|
| `mode` | yes | `lead_in`, `nominal_file`, or `recipe_step`. |
| `rows` | for `lead_in` | Number of leading rows used as the normal reference. Must be > 0 and < file length. |
| `file` | for `nominal_file` | Path to a nominal CSV, relative to the YAML file. |
| `step_column` | for `recipe_step` | Column that identifies the recipe step. Each step gets its own median/MAD. The schema accepts this mode, but scoring currently fails closed until per-step baselines are implemented; use `lead_in` or `nominal_file` today. |

A `nominal_file` must contain every declared signal name. Paths are resolved
relative to the YAML file, and a missing or short baseline fails closed.

Why this exists: a median/MAD over the whole file absorbs a fault that occupies
most of the window. A lead-in, a nominal file, or a per-step baseline is the
difference between “the fault is visible” and “the fault is the new normal”.

### `signals`

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | Must match a CSV header exactly (case-sensitive). |
| `label` | yes | User-facing name. If omitted, use `name`. |
| `unit` | no | `null` when unknown. Never invent a unit. |
| `alert_at` | no | Robust z threshold. Default `3.5`. `null` means `NOT_EVALUATED`. |

`alert_at` is the only sensitivity knob. Higher = fewer alerts. The UI says
“alert level”, not “robust z threshold”.

The score is `z = 0.6745 × |value − median| / MAD` over the normal reference.
`0.6745` is `Φ⁻¹(0.75)`; for normal data `MAD ≈ 0.6745σ`, so the result is in
normal-equivalent sigma units. MAD is used instead of the standard deviation so
a few fault points do not inflate “normal”. **3.5z is a statistical screening
default (about a 0.047% two-sided normal tail), not a physics-derived
tolerance**; replace it with a calibrated limit when one exists. The 5z coverage
limit is a separate product policy and cannot be lowered by this file.

### `checks`

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Stable id, lowercase, unique. The model may cite this id. |
| `label` | yes | User-facing cause name. |
| `kind` | yes | `equipment_fault`, `instrumentation_fault`, `upstream_process`, `process_drift`, `material_issue`. |
| `must_be_unusual` | yes | All listed signals must be unusual. Each entry is `{signal, direction}`; `direction` is `any`, `up`, or `down`. |
| `must_stay_normal` | no | If any listed signal is unusual, the check is contradicted (**Sensors Disagree**). |
| `corroborated_by` | no | Signals that should move with the primary signal. If they stay flat while the primary moves, the result is **Sensors Disagree**. |
| `action` | yes | `INSPECT_COMPONENT`, `CONTINUE_MONITORING`, or `ESCALATE_TO_ENGINEER`. |
| `advice` | yes | One sentence shown next to the action. |

Plain labels for the UI:

| `kind` | UI label |
|---|---|
| `equipment_fault` | Equipment fault |
| `instrumentation_fault` | Sensor / instrument fault |
| `upstream_process` | Upstream process |
| `process_drift` | Process drift |
| `material_issue` | Material issue |

`direction` is optional and defaults to `any`. The current gate validates the
value but treats it as `any`; sign-specific scoring is deferred. Do not rely on
`up` / `down` to reject a move in the other direction yet.

A check with an empty `must_be_unusual` is invalid: it would confirm on no
evidence. A signal cannot appear in both `must_be_unusual` and
`must_stay_normal`. The id `new` is reserved for a model-proposed cause with
no saved check and cannot be used as a configured check id.

## 3. Coverage

Python scores **every** declared signal, not only the signals in the passing
check. A channel is *explained* when it belongs to a configured check or stayed
nominal. An anomaly outside the check is *unexplained*.

If any unexplained anomaly reaches the product policy limit (`|z| >= 5`), a
check that would otherwise be **Fault Confirmed** is demoted to
**Needs Review**. The limit is product policy in `src/policy.py`; a tool
config cannot lower it. This is why a coolant check on the PHM demo can pass
while the result still says **Needs Review**: the beam and suppressor channels
moved too.

## 4. Examples

### TEP feed disturbance (cause vs symptom)

```yaml
tool:
  name: tep_reactor
  label: TEP Reactor
baseline:
  mode: lead_in
  rows: 12
signals:
  - {name: "XMEAS(1)", label: A feed flow, unit: kscmh, alert_at: 3.5}
  - {name: "XMV(3)", label: A feed valve, unit: "%", alert_at: 3.5}
  - {name: "XMEAS(7)", label: Reactor pressure, unit: kPa, alert_at: 3.5}
checks:
  - id: feed_loss
    label: Feed-system disturbance
    kind: upstream_process
    must_be_unusual:
      - {signal: "XMEAS(1)", direction: any}
      - {signal: "XMV(3)", direction: any}
    must_stay_normal: []
    action: ESCALATE_TO_ENGINEER
    advice: Ask an engineer to confirm the feed line; reactor pressure is a symptom.
```

The key: `XMEAS(7)` is a **symptom**. If a model names it as the cause, the
differential table shows it as **Needs Review**; the configured cause remains
`feed_loss`.

> The shipped TEP demo config uses a different pattern check: it requires
> `XMEAS(1)` and `XMEAS(7)` because the valve in the committed sample stays
> near its normal position. It does not claim that pressure is the physical
> cause. See [`DATASETS.md`](DATASETS.md).

### Sensor conflict (single channel moved, companions flat)

```yaml
tool:
  name: rf_station
  label: RF Station
baseline:
  mode: lead_in
  rows: 50
signals:
  - {name: sensor_17, label: RF sensor, unit: null, alert_at: 3.5}
  - {name: impedance, label: Impedance, unit: null, alert_at: 3.5}
  - {name: thermal, label: Thermal, unit: null, alert_at: 3.5}
  - {name: pressure, label: Pressure, unit: null, alert_at: 3.5}
checks:
  - id: rf_arc
    label: RF arc
    kind: equipment_fault
    must_be_unusual: [sensor_17, impedance, thermal, pressure]
    corroborated_by: [impedance, thermal, pressure]
    must_stay_normal: []
    action: INSPECT_COMPONENT
    advice: Inspect the RF generator.
```

If `sensor_17` moves but all three companions stay normal, the result is
**Sensors Disagree** (“check the sensor first”), not **Fault Confirmed**.

### Unknown machine (draft)

For an unknown export, the column mapper writes a draft with:

```yaml
tool:
  name: draft_export_2026_10_26
  label: Draft mapping
baseline:
  mode: lead_in
  rows: 50
signals:
  - {name: col_a, label: Column A, unit: null, alert_at: 3.5}
  - {name: col_b, label: Column B, unit: null, alert_at: 3.5}
checks: []
```

No checks means no diagnosis. The result is **Unknown Machine**; the action is
**Review the guessed columns**. The hosted UI is stateless: it lets the engineer
download the draft YAML, but it does not write a shared config. The engineer
edits the draft in their own repository, adds checks, and deploys or pastes the
reviewed model; the next run is deterministic.

## 5. Validation rules

The loader must reject, with a clear message:

- a duplicate signal `name`;
- a duplicate check `id`;
- a check with no `must_be_unusual`;
- a signal in both `must_be_unusual` and `must_stay_normal`;
- a check that references an undeclared signal;
- an unknown `kind` or `action`;
- `alert_at <= 0` (or `null`);
- `lead_in` with `rows <= 0`, or `rows >=` the uploaded row count;
- `nominal_file` with a missing file or a header mismatch;
- `recipe_step` with a missing `step_column`;
- unknown keys (fail loudly; do not silently ignore a typo).

The error message should name the YAML path (`checks[0].must_be_unusual[1].signal`)
and what to do. Do not show a Python traceback.

## 6. What not to put in the YAML

- No `candidate`, `root_cause`, `failure_mode`, `mechanism`, or free-text
  diagnosis. The label and advice are enough.
- No `predicates` or `rules`. The check shape is the rule.
- No sensor values or thresholds from a specific fault window.
- No recipe changes, lot holds, or “auto-fix” actions.
- No benchmark IDs.
