# FabAgent — architecture

This document describes the system that exists today and the target hybrid
architecture. The **target** sections are the implementation contract; the
**current** sections are what the code does now.

## 1. Design rules

1. **Python owns sufficiency and action.** The LLM proposes causes and cites
   evidence; Python resolves the citations, checks coverage, applies
   contradictions, and chooses the action. A model call can never turn a
   contradiction into a confirmed fault.
2. **Evidence is typed.** Every finding is an `Evidence` record with an ID,
   kind, signal, statistic, value, unit, window, provenance, and summary. The
   model may cite only these IDs.
3. **Fail closed.** Missing data, an unresolved citation, a failed model call, or
   an unconfigured cause produces `Needs Review` / `Data Incomplete`, never a
   confident guess.
4. **No invented physics.** Units, thresholds, sensor names, and relationships
   are never invented. Unknown is `None`; unevaluated is `NOT_EVALUATED`.
5. **The core is generic.** `src/core/` contains no benchmark IDs, no YAML, and
   no imports from `agents/`, `tools/`, or `ui/`.
6. **The UI uses plain words.** The six user-facing results are the vocabulary in
   [`UI_VOCABULARY.md`](UI_VOCABULARY.md). Internal enums stay in the audit view.
7. **The UI stays familiar.** The hybrid is an extension of the existing
   Streamlit layout, not a redesign.

## 2. Current pipeline (as-is)

```
CSV upload + optional note
        │
        ▼
src/analyze.py  analyze_csv()
        │
        ├─ src/triage.py ── match a config in config/sensor_relations/
        │
        ├─ src/dossier.py ── read CSV, scope columns
        │
        ├─ src/core/duckdb_exec.py ── median/MAD over the input window
        │
        ├─ src/core/evidence.py ── anomaly / nominal / missing records
        │
        ├─ src/core/pipeline.py ── assess_candidate()
        │       └─ src/core/sufficiency.py ── predicates and contradiction
        │
        ├─ src/agents/proposal_request.py ── optional Nemotron narrative
        │
        └─ src/agents/rca_engine.py ── gate + typed action
                └─ src/core/safety_gate.py
```

The product entry point is `analyze_csv(csv, note)` in `src/analyze.py`. The
deterministic path is `analyze_dossier`; when no tool model matches, the router
falls back to `src/experimental.py` (`analyze_experimental`), which asks the
model for a column mapping and returns an unverified draft.

### What is good and must be preserved

- `src/core/` is small, typed, and testable without a network or a key.
- Every declared signal emits an anomaly, nominal, or missing record. Absence is
  never read as normal.
- Contradictions are hard vetoes, not weights.
- The action is a typed enum; recipe changes and lot holds are unrepresentable.
- The 2 KB payload bound keeps raw telemetry out of the model call.
- The offline transport makes the demo reproducible without keys.

### Where the pre-hybrid design hurt

| Problem | Evidence | Effect |
|---|---|---|
| **Global baseline** | Before Phase 2, median/MAD was computed over the whole file. A fault that occupies most of the window was absorbed into “normal”; the PHM demo reported `z=591` / `z=946` on other channels. | The same physical fault flipped between `Fault Confirmed` and `Needs Review` depending on the slice. Phase 2 adds `lead_in` / `nominal_file`; the PHM demo and benchmark now share one clean nominal reference. |
| **YAML contains the diagnosis** | `candidate.claim`, `root_cause`, `failure_mode`, and `mechanism` are in the tool model. | The answer looks pre-written; the model is decorative. |
| **One scenario per run** | Triage selects one config; there is no differential. | A second plausible cause is never shown. |
| **No coverage rule** | Before Phase 2, a supported candidate could coexist with five large unexplained anomalies. | “Fault Confirmed” overstated what the data covered. Phase 2 demotes a supported check when an unexplained anomaly is `|z| >= 5`. |
| **No challenge** | The model is asked to explain, not to falsify. | The strongest disconfirming evidence is not tested. |
| **Leaky vocabulary** | UI texts use `VETOED`, `SUPPORTED`, `EXPERIMENTAL_UNVERIFIED_MAPPING`, `hypothesis_class`. | New users cannot tell what happened. |
| **Leaky benchmark** | Prompts name the scenario and the answer. | The comparison is not evidence of model quality. |

## 3. Target hybrid architecture

Three layers, each with a narrow job:

```
┌────────────────────────────────────────────────────────────────────┐
│ 3. UI: six result words, differential table, audit tab              │
│    (same pages, same layout, same visual style)                     │
└───────────────────────────▲────────────────────────────────────────┘
                            │ typed result + plain-language mapping
┌───────────────────────────┴────────────────────────────────────────┐
│ 2. Model helpers (Nemotron via Nebius Token Factory)                │
│    a. Column mapper   b. Cause finder   c. Challenge check          │
│    d. Explainer       — all bounded, schema-validated, non-binding  │
└───────────────────────────▲────────────────────────────────────────┘
                            │ evidence IDs + tool-model checks
┌───────────────────────────┴────────────────────────────────────────┐
│ 1. Deterministic core (Python + DuckDB)                             │
│    baseline → evidence → coverage → fault checks → gate → action    │
│    no model, no network, no benchmark IDs                           │
└────────────────────────────────────────────────────────────────────┘
```

### 3.1 Engineer-defined mode

The engineer has a saved **tool model** (see
[`YAML_GUIDE.md`](YAML_GUIDE.md)). The run is:

1. Match the uploaded CSV to a tool model by its signal set.
2. Build the **normal reference** using `baseline` (`lead_in` or
   `nominal_file`; `recipe_step` validates but fails closed until per-step
   scoring is implemented).
3. Emit one evidence record per declared signal: anomaly, nominal, or missing.
4. Evaluate every fault check:
   - `must_be_unusual`: all listed signals must be unusual.
   - `must_stay_normal`: if any listed signal is unusual, the check is
     contradicted (**Sensors Disagree**).
   - missing required signals: **Data Incomplete**.
5. Compute **coverage**: how many declared signals are explained by the winning
   check. Unexplained large anomalies prevent a bare **Fault Confirmed**.
6. If the model is enabled, it may add a **Challenge check**: a disconfirming
   test with evidence IDs. Python evaluates the test; if it fails, the result is
   downgraded to **Needs Review** / **Sensors Disagree**.
7. Choose one typed action. The considered action set is:
   `INSPECT_COMPONENT`, `CONTINUE_MONITORING`, `ESCALATE_TO_ENGINEER`.
   The UI may also show `COLLECT_MORE_DATA`, `REVIEW_DRAFT_MAPPING`,
   `CHECK_THE_SENSOR`, `FIX_THE_FILE`, `TRY_AGAIN`.
8. Show the deterministic result even if the model call fails.

### 3.2 Auto mode (unknown machine)

No tool model matches. The system does **not** claim a diagnosis:

1. **Column mapper** proposes columns, labels, roles, and units from names and
   bounded statistics. Python validates every column against the file.
2. The mapper produces a **draft tool model** (YAML v2) with empty or guessed
   checks.
3. **Cause finder** proposes possible causes from the evidence, with evidence
   IDs.
4. Python maps each proposed cause to a fault check. A cause with a configured
   check is evaluated deterministically; a cause without one is shown as
   **Needs Review**, with no action beyond “review the draft”.
5. The engineer edits the draft, saves it, and re-runs. The next run is
   Engineer-defined.

The key safety property: **the model cannot invent a check that maps to an
action.** Only a check that exists in the saved tool model can produce
`INSPECT_COMPONENT` or `CONTINUE_MONITORING`.

### 3.3 Differential

Evaluate all configured checks, not just one. The UI shows a small table:

| Possible cause | Evidence for | Evidence against | Result |
|---|---|---|---|
| Coolant loop fault | `FLOWCOOLFLOWRATE` +, `FLOWCOOLPRESSURE` + | none | **Fault Confirmed** |
| Chamber pressure fault | `IONGAUGEPRESSURE` + | coolant channels normal | **Sensors Disagree** |

The table uses the six result words; it does not show predicates or enum names.
If no check is confirmed, the table is still useful: it shows what was ruled out.

## 4. Contracts

### 4.1 Evidence (existing, keep)

`src/core/types.py` defines `Evidence` (or the equivalent frozen dataclass) with:

- `evidence_id` — the only thing a model may cite
- `kind` — `SENSOR_ANOMALY`, `SENSOR_NOMINAL`, `MISSING_CHANNEL`, …
- `signal`, `statistic`, `value`, `unit` (`None` when unknown), `window`
- `provenance` — file + row range
- `computed_by` — e.g. `robust_mad_zscore@v1`
- `summary` — one line for the bounded payload

Every declared signal emits exactly one record. `EvidenceStore.resolve_all(ids)`
returns resolved and unresolved IDs; unresolved IDs are hallucinated citations.

### 4.2 Tool model (user-facing)

Defined in [`YAML_GUIDE.md`](YAML_GUIDE.md). Shape:

```yaml
tool: {name, label, description}
baseline: {mode, rows | file | step_column}
signals: [{name, label, unit, alert_at}]
checks: [{id, label, kind, must_be_unusual, must_stay_normal, action, advice}]
```

The loader translates the tool model into the existing internal
`ScenarioConfig` / `CandidateConfig` / `PredicateConfig` / `ConstraintRule`
objects. The core continues to see the same generic contracts. The UI and public
configs use one schema; legacy v1 fixtures are internal benchmark tests only.

### 4.3 Fault check (new internal)

A `FaultCheck` is the internal, generic representation of one `checks` entry:

- `id`, `label`, `kind` (`equipment_fault`, `instrumentation_fault`,
  `upstream_process`, `process_drift`, `material_issue`)
- `must_be_unusual`: list of `(signal, direction)`
- `must_stay_normal`: list of signals
- `action`: typed `SuggestedAction`
- `advice`: one sentence

It is configuration-authored. The model may propose a check, but it becomes
actionable only after the engineer saves it.

### 4.4 Model output (simplified)

The cause finder returns a small object, not a full RCA:

```json
{
  "possible_causes": [
    {
      "check": "coolant_leak",
      "title": "Coolant loop fault",
      "why": "Both coolant channels moved together.",
      "evidence": ["EV_007", "EV_008"]
    }
  ]
}
```

Rules:

- `check` must match a saved check id, or be `"new"`.
- `evidence` must contain only IDs from the payload.
- No `root_cause`, `failure_mode`, `mechanism`, `status`, or `action` in the
  model response. Python fills those from the matched check.
- If the response is invalid, the deterministic result still runs; the UI adds
  **AI explanation unavailable**.

The challenge check returns:

```json
{
  "challenge": "If this were a real coolant fault, chamber pressure should also move.",
  "evidence": ["EV_009"],
  "expected": "IONGAUGEPRESSURE unusual"
}
```

Python evaluates the expectation against the evidence store. A failed challenge
downgrades the result; a challenge with unresolved IDs is discarded.

### 4.5 Result (existing shape, new display)

The internal `RCAOutputModel` / `AnalysisResult` can keep its fields for
compatibility. The UI maps them to the six words:

| Internal | User-facing |
|---|---|
| `SUPPORTED` | **Fault Confirmed** |
| `INSUFFICIENT` + all checked signals nominal | **Regular Behavior** |
| `INSUFFICIENT` + missing required signal | **Data Incomplete** |
| `INSUFFICIENT` + unexplained anomaly | **Needs Review** |
| `VETOED` (contradiction) | **Sensors Disagree** |
| `EXPERIMENTAL_UNVERIFIED_MAPPING` | **Unknown Machine** |

The mapping is centralized in `src/ui/presentation.py`; no page invents its own
wording.

## 5. File map

| Area | Files | Role |
|---|---|---|
| Entry / routing | `src/analyze.py`, `src/triage.py`, `src/dossier.py` | Product entry, tool matching, CSV scope |
| Core | `src/core/types.py`, `evidence.py`, `duckdb_exec.py`, `statistics.py`, `pipeline.py`, `sufficiency.py`, `constraints.py`, `safety_gate.py` | Generic deterministic engine |
| Config | `src/config_loader.py`, `src/config_types.py`, `src/config_writer.py`, `config/sensor_relations/*.yaml` | Tool model load/save |
| Model helpers | `src/agents/model_transport.py`, `proposal_request.py`, `mapping_request.py`, `rca_engine.py` | Bounded Nemotron calls |
| Auto mode | `src/experimental.py` | Draft mapping and proposal path |
| External | `src/tools/tavily_search.py` | Optional public leads |
| UI | `src/ui/app.py`, `src/ui/presentation.py`, `src/ui/config_promotion.py`, `docs/ui/*.md` | Streamlit pages and copy |
| Demo | `src/demo.py`, `src/demo_catalog.py`, `src/demo_data.py`, `samples/` | Key-free demo |
| Benchmarks | `benchmarks/evaluator/*`, `benchmarks/synthetic_twin/*`, `benchmarks/datasets/*` | W3/W5/e2e and naive-LLM comparison |

## 6. Invariants and verification

Run after every change (from `AGENTS.md`):

```sh
.venv/bin/python -m unittest discover -s tests
.venv/bin/ruff check .
.venv/bin/basedpyright
PYTHONPATH=. .venv/bin/python benchmarks/evaluator/synthetic_abstention_runner.py   # W3, llm_calls=0
PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.dossier_e2e_runner --offline  # W5.5, key-free
PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.experimental_e2e_runner     # experimental path, key-free
PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.e2e_suite_runner            # 4-case both-path suite
```

Hard invariants:

- `src/core/` imports only stdlib, numpy, duckdb, and other core modules.
- No benchmark identifier (`B1`…`B4d`, `IDV`, `PHM18`, `TEP`, `SECOM`) in
  `src/core/`.
- No model ID outside `config/models.yaml`.
- No invented units or thresholds; unknown is `None`.
- A missing channel is evidence, never silence.
- The action is an enum; no free-form recipe field.
- The UI never shows an internal enum in the main flow.
- A benchmark number in the README or UI must trace to a committed artifact.

## 7. Non-goals for the hybrid

- No full rewrite. Keep the existing engine and tests.
- No LLM-decided verdict. The model becomes useful by proposing and challenging,
  not by judging.
- No new UI layout. The same pages, cards, and colors; the result vocabulary and
  the differential table are the visible changes.
- No cloud dependency in the demo. Offline mode stays first-class.
- No benchmark victory claim from leaked prompts. The new benchmark follows
  [`EVALUATION.md`](EVALUATION.md).
