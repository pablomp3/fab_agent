# Datasets and samples

FabAgent tests **reasoning patterns**, not a modern fab’s physics. The public
datasets provide observations; the synthetic twin provides injected causal
ground truth. Neither is field validation.

## 1. PHM 2018 — Seagate ion mill

- **What it is:** real ion-mill telemetry with a documented `Flowcool leak`
  fault in run `01_M02_DC_01`.
- **Use it for:** equipment-subsystem attribution (flowcool circuit) and
  contradiction handling.
- **Do not use it for:** process-cause attribution or yield labels. Fault
  timestamps are operator maintenance-shutdown times, not fault onset.
- **Units:** values are z-normalized in the public score file; units are
  withheld. Use `unit: null`. Never invent a unit.
- **Signal groups:**
  - `flowcool`: `FLOWCOOLFLOWRATE`, `FLOWCOOLPRESSURE`
  - `chamber`: `IONGAUGEPRESSURE`
  - `ion_source`: `ETCHBEAMVOLTAGE`, `ETCHBEAMCURRENT`,
    `ETCHSUPPRESSORVOLTAGE`, `ETCHSUPPRESSORCURRENT`
- **Leak signature used by the saved check:** coolant flow and coolant pressure
  move together. The v2 check does not assert a direction; the UI shows the
  observed values. If only one moves, the check is not satisfied.
- **Sampling:** irregular. Compute Δt; never assume a fixed sample rate.

### Samples and normal reference

The committed slices now share one clean nominal reference:

- `M02_DC_01_nominal_sample.csv` — 900 clean rows used as the `nominal_file`
  baseline. Against itself every configured channel is nominal.
- `M02_DC_01_sample.csv` — 100 normal rows followed by 900 fault-window rows.
- `M02_DC_01_demo_sample.csv` — 900 nominal rows followed by 100 fault-window
  rows.

The fault-centred and demo slices report the same result: the coolant check
passes, but the other declared channels contain large unexplained anomalies, so
coverage makes the product say **Needs Review**. The nominal control reports
**Regular Behavior**. The full-file W5 PHM artifact follows the same normal
reference and reports `INSUFFICIENT`.

## 2. TEP — Tennessee Eastman Process

- **What it is:** a chemical-process simulation with 52 measured/manipulated
  variables and known disturbance IDs.
- **Use it for:** cause vs symptom discrimination. The variables have real units;
  populate `unit`.
- **Evaluable for attribution:** IDV 1, 2, 4, 5, 6, 7, 14, 15.
- **Abstention tests:** IDV 3 and 9.
- **Do not evaluate:** IDV 13 (unmeasured latent kinetic parameter) or IDV 16–20
  (labeled `Unknown` in the original source).
- **Cause vs symptom:** the published W5 comparison keeps the original model:
  `XMEAS(1)` A feed and `XMV(3)` A feed valve are the cause; `XMEAS(7)` reactor
  pressure is the **symptom**. A model that names pressure as the cause is
  wrong. That comparison deliberately stays on its original global baseline
  until the Phase 5 re-baselining.
- **Product v2 config:** the demo config checks `XMEAS(1)` and `XMEAS(7)` as a
  feed-flow / reactor-pressure pattern with a six-row lead-in. The valve is
  recorded but stays near its normal position in the committed IDV6 sample, so
  it cannot be a required cause channel there. The config does not claim a
  physical mechanism.
- **Sample note:** the committed `IDV3_sample.csv` is an unmodeled disturbance,
  not “normal reactor behavior”. The UI must say **Needs Review** / **Ask an
  engineer**, not **Regular Behavior**.

## 3. Synthetic Fab Twin

- **What it is:** a seeded NumPy/pandas generator (`benchmarks/synthetic_twin/`)
  that injects a latent fault, a causal mechanism, and the expected sensor
  consequences. The ground truth is in the generator manifest, not in the model
  prompt.
- **Cases:** B4a–B4e; B4a is the sensor-conflict case (`sensor_17` up,
  impedance/thermal/pressure flat). B4e is the positive control.
- **Use it for:** adversarial abstention, contradiction handling, and the
  deterministic W3 gate (zero LLM calls).
- **Do not use it for:** field validation. Required line: “Accuracy on the
  synthetic twin measures whether the agent recovers the cause we injected. It is
  not evidence about real-world field truth.”
- **Anti-circularity:** `GENERATOR_SPEC.md` is committed before detector code.
  Keep the commit order; do not rewrite history.
- **Generation:** the LLM writes the generator script; it never writes CSV rows
  directly. The script uses NumPy/pandas and a fixed seed.

## 4. Sample construction rules (hybrid)

Every sample must satisfy:

1. **One baseline rule.** The same `baseline` mode is used for the demo, the
   test, and the benchmark. No per-sample tuning.
2. **Fault-centred and lead-in slices agree.** If the same fault yields two
   different results, the baseline is wrong.
3. **Nominal means nominal.** A nominal control contains no fault rows, no
   unlabeled fault tail, and no “planned recipe transitions” that look like a
   fault.
4. **Missing-channel case is explicit.** Remove a required column from a
   supported case; the expected result is **Data Incomplete**.
5. **Conflict case is explicit.** A single channel moves, companions stay flat;
   the expected result is **Sensors Disagree**.
6. **No cherry-picking.** Report all configured cases, including failures.
7. **No answer in the file name.** `flowcool_supported.csv` is acceptable for a
   demo but not for the benchmark prompt. The benchmark uses opaque IDs.
8. **Units stay honest.** PHM units are `null`; TEP units are real; synthetic
   units are `null` unless the generator defines them.

## 5. Provenance table

| Dataset | Source | What it proves | What it does not prove |
|---|---|---|---|
| PHM 2018 | Seagate ion-mill public score file | Equipment-subsystem attribution; contradiction handling | Process cause; yield impact; modern tool physics |
| TEP | Tennessee Eastman Process | Cause vs symptom; real units | Semiconductor physics |
| Synthetic twin | Seeded generator | Controlled causal recovery; abstention | Field accuracy |

## 6. The judge question

> “TEP is a 1993 chemical simulation and PHM is an ion mill. How does this prove
> FabAgent works on a modern etcher?”

Answer:

> “It does not prove the physics of a modern etcher. It proves the reasoning
> pattern: separate a cause from a symptom, detect a sensor contradiction, and
> abstain when the data is incomplete. The engine is generic; a process engineer
> supplies the tool model for their chamber. The same deterministic checks then
> run on their columns. Benchmark IDs never enter `src/core/`.”

That is the defensible claim. Do not claim more.
