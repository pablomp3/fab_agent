# FabAgent hybrid — implementation entrypoint

> **How to use:** paste this entire file into the new session as the only
> entrypoint. It is self-contained. The implementing LLM should read the
> referenced repo files before coding. Work in the phases below and stop after
> each phase for review.

---

# PROMPT — implement the FabAgent hybrid

You are implementing the hybrid version of **FabAgent**, an evidence-gated
troubleshooting copilot for semiconductor tools. The repository is
`/home/pablo/code/nvidia/fab_agent`.

The goal is to make the LLM genuinely useful **without letting it decide**, keep
the current Streamlit UI and its look, simplify the YAML so an engineer can read
it, replace internal jargon with plain result words, and prove the gate with a
fair benchmark against Gemini/ChatGPT.

## 0. Your job in one paragraph

Keep the deterministic engine and the UI. Add three model roles — **column
mapper**, **cause finder**, and **challenge check** — behind a Python gate. Add a
**normal reference** so a fault is not absorbed into the baseline. Add a
**coverage** rule so “Fault Confirmed” cannot hide large unexplained anomalies.
Add a **differential** table so more than one possible cause is shown. Replace
the v1 YAML with a small **v2 tool model** (signals + baseline + checks) while
keeping v1 loadable for tests. Rewrite the user-facing copy around six result
words. Build a fair benchmark. Do not rewrite the app.

## 1. Read first (in this order)

1. `AGENTS.md` — repo rules and verification commands.
2. `docs/STATUS.md` — what is verified, what is broken, what is next.
3. `docs/ARCHITECTURE.md` — current pipeline and target hybrid.
4. `docs/UI_VOCABULARY.md` — the only words a user may see.
5. `docs/YAML_GUIDE.md` — the v2 schema and examples.
6. `docs/EVALUATION.md` — the fair benchmark protocol.
7. `docs/DATASETS.md` — PHM/TEP/synthetic limits and sample rules.
8. `docs/ANTI_GOALS.md` — hard prohibitions.
9. `docs/PRODUCT.md` — the product story.

Then read the code you will touch:

- `src/analyze.py`, `src/triage.py`, `src/dossier.py`
- `src/core/types.py`, `src/core/evidence.py`, `src/core/duckdb_exec.py`,
  `src/core/statistics.py`, `src/core/pipeline.py`, `src/core/sufficiency.py`,
  `src/core/constraints.py`, `src/core/safety_gate.py`
- `src/config_loader.py`, `src/config_types.py`, `src/config_writer.py`
- `src/agents/model_transport.py`, `src/agents/proposal_request.py`,
  `src/agents/mapping_request.py`, `src/agents/rca_engine.py`
- `src/experimental.py`, `src/schemas/models.py`, `src/action_guidance.py`
- `src/ui/app.py`, `src/ui/presentation.py`, `src/ui/config_promotion.py`
- `src/demo.py`, `src/demo_catalog.py`, `src/demo_data.py`
- `config/models.yaml`, `config/sensor_relations/*.yaml`
- `docs/ui/*.md` (the app reads these at runtime; keep the filenames)
- `tests/*`, `benchmarks/evaluator/*`

Run the baseline verification **before changing anything**:

```sh
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/ruff check .
.venv/bin/basedpyright
PYTHONPATH=. .venv/bin/python benchmarks/evaluator/synthetic_abstention_runner.py
PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.dossier_e2e_runner --offline
PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.experimental_e2e_runner
PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.e2e_suite_runner
```

Expected baseline on 2026-10-26: 134 tests OK, ruff clean, pyright 0 errors,
W3 GREEN (`cases=4, llm_calls=0`), e2e safe 4/4 and experimental 4/4. If the
baseline is not green, stop and report before coding.

## 2. Non-negotiable constraints

1. **Python owns the result and the action.** The model proposes causes and
   cites evidence; Python resolves citations, checks coverage, applies
   contradictions, and chooses the action. The model can never upgrade a result.
2. **No invented units, thresholds, sensor names, or physics.** Unknown is
   `None`; unevaluated is `NOT_EVALUATED`.
3. **No benchmark ID in `src/core/`.** No `B1`…`B4d`, `IDV`, `PHM18`, `TEP`,
   `SECOM`, or case IDs.
4. **No model ID outside `config/models.yaml`.** Add roles, not hardcoded names.
5. **No recipe or hold action.** The action enum stays small and typed.
6. **No raw telemetry to the model.** Keep the 2 KB payload bound.
7. **No internal enum in the main UI.** `VETOED`, `SUPPORTED`, `INSUFFICIENT`,
   `EXPERIMENTAL`, `UNVERIFIED`, `hypothesis_class`, `predicate`, `candidate`,
   `gate`, `veto` belong in the Audit view only.
8. **Keep the UI layout.** Same pages, same cards, same visual style. Add cards
   below the existing result; do not redesign.
9. **Keep offline mode first-class.** The demo must work with no keys.
10. **No micro-commits.** Keep changes in working files until a phase is green or
    the user asks.
11. **Never print or log keys or raw completions.**
12. **Simplify when in doubt.** Losing 10% of a complex feature is acceptable if
    the system becomes easier to understand and maintain.

## 3. Current system (do not rewrite it)

```
CSV → triage → DuckDB median/MAD → evidence → candidate → predicates/vetoes
    → typed action; Nemotron narrative is separate and non-binding
```

Key facts:

- Product entry: `analyze_csv(csv, note)` in `src/analyze.py`.
- Deterministic path: `analyze_dossier`; Auto fallback: `src/experimental.py`.
- The core is generic and testable with no network.
- Evidence is typed and ID-bearing; missing channels are evidence.
- Contradictions are hard vetoes, not weights.
- The action is an enum; `HOLD_LOT` is deliberately not offered.
- The UI already has: upload, note, run, result card, evidence, audit, demo,
  YAML view, benchmark/contact pages.
- The current YAML is v1 and mixes the tool model with the diagnosis
  (`candidate`, `predicates`, `rules`). That is what v2 removes.

## 4. Target behavior (what the user sees)

### Two modes

- **Engineer-defined:** a saved v2 tool model. Deterministic run. The model may
  explain and challenge; it cannot change the result.
- **Auto:** no saved model. The column mapper proposes a draft; the cause finder
  proposes causes; Python checks them. A cause without a saved check is
  **Needs Review**, never a confirmed fault. The engineer saves the model; the
  next run is deterministic.

### Six result words (exact)

| Result | When |
|---|---|
| **Fault Confirmed** | A saved check is satisfied, coverage is acceptable, and no challenge disconfirms it. |
| **Regular Behavior** | Every checked signal is normal and there is no missing required data. |
| **Sensors Disagree** | A signal moved but a `must_stay_normal` signal also moved (contradiction). |
| **Data Incomplete** | A required signal is missing. |
| **Needs Review** | Unexplained large anomalies, an unconfigured cause, a failed challenge, or a failed model call. |
| **Unknown Machine** | No saved tool model matches the export. |

Optional small badge: **AI explanation unavailable**.

`INSPECT_COMPONENT` → “Inspect the part”; `CONTINUE_MONITORING` → “Keep
monitoring”; `ESCALATE_TO_ENGINEER` → “Ask an engineer to review”;
`COLLECT_MORE_DATA` → “Get the missing data”; `REVIEW_DRAFT_MAPPING` → “Review
the guessed columns”. See `docs/UI_VOCABULARY.md`.

### Differential

Show all configured checks in a table:

| Possible cause | Evidence for | Evidence against | Result |
|---|---|---|---|

- A check with all `must_be_unusual` signals unusual and no contradiction is
  **Fault Confirmed**.
- A check with a `must_stay_normal` signal unusual is **Sensors Disagree**.
- A check with a missing required signal is **Data Incomplete**.
- A check with some movement but not enough is **Needs Review**.
- An unconfigured model-proposed cause is **Needs Review**; its only action is
  review/escalate.

### Coverage

Every declared signal is one of: part of the winning check, part of a
contradicted check, nominally quiet, or **unexplained**. Rules:

- If an unexplained signal has `|z| >= 5`, the headline cannot be a bare
  **Fault Confirmed**; use **Needs Review** and show the unexplained signals.
- If 1–2 unexplained signals have `3.5 <= |z| < 5`, keep the headline but add a
  “What else moved” card and list them.
- Never hide an unexplained anomaly.

This is the fix for the PHM case where `z=591` / `z=946` coexist with a
“coolant fault supported” result.

### Challenge

After a check is confirmed, ask Nemotron for the strongest disconfirming test.
Python evaluates it:

- expectation met (the named signal moved as the challenge predicted) → the
  challenge does **not** disconfirm; keep the result, note “challenge checked”.
- expectation not met → downgrade to **Needs Review** / **Sensors Disagree**.
- malformed or unresolved evidence → ignore; show “AI challenge unavailable” in
  Audit.

The challenge can only downgrade, never upgrade.

## 5. Architecture changes

### 5.1 Baseline (new, generic)

Add a `BaselineSpec` to the core types and `ScenarioConfig`:

```python
BaselineSpec(mode: Literal["lead_in", "nominal_file", "recipe_step"],
             rows: int | None, file: str | None, step_column: str | None)
```

- `lead_in`: median/MAD from the first `rows` rows; evaluate the file against
  that reference. Requires `0 < rows < file length`.
- `nominal_file`: median/MAD from a separate nominal CSV; evaluate the upload.
- `recipe_step`: median/MAD per value of `step_column` (advanced; implement only
  after the first two are green and tested).

`src/core/duckdb_exec.py` / `src/core/statistics.py` must accept the baseline
instead of always using the whole window. Keep the default behavior for v1
configs (`None` → current global baseline) so old tests pass. The new v2 configs
must set a baseline.

The demo samples must be regenerated so the same fault gives the same result:
- `M02_DC_01_demo_sample.csv` already has a stable lead-in; keep it.
- `M02_DC_01_sample.csv` must get a normal lead-in (or use a nominal file).
- `M02_DC_01_nominal_sample.csv` must be genuinely fault-free or be removed.
- The demo catalog must not call a fault-centred slice “Normal Run”.

### 5.2 Coverage (new, generic)

Add a `Coverage` result:

```python
Coverage(explained: tuple[str, ...],
         unexplained: tuple[str, ...],
         unexplained_large: tuple[str, ...])
```

Compute it in `src/core/pipeline.py` from the winning check and the evidence.
Do not put benchmark IDs in core. The UI decides how to render it; the gate
decides whether **Fault Confirmed** is allowed.

### 5.3 Differential (new, generic)

Evaluate every configured check, not one scenario. The internal
`LoadedRelations` can keep one `ScenarioConfig` per check; the pipeline can loop.
A check is a `FaultCheck` (id, label, kind, must_be_unusual, must_stay_normal,
action, advice). Keep the existing `assess_candidate` logic; call it per check.
Aggregate without weights:

- headline: the highest-severity confirmed check; if none, the highest-severity
  contradiction; then data-incomplete; then needs-review; then no-fault.
- if two checks are confirmed, show both; the headline is the one with more
  supporting signals (and a “2 possible causes” note).
- never sum scores.

### 5.4 YAML v2 loader

Add `src/config_loader_v2.py` (or extend `config_loader.py` with a version
branch). It must:

- accept `version: 1` (existing) and `version: 2` (new);
- validate every field and fail with a readable path (`checks[0].must_be_unusual[1].signal`);
- translate v2 `signals`/`baseline`/`checks` into the existing
  `LoadedRelations` / `ScenarioConfig` / `CandidateConfig` / `PredicateConfig` /
  `ConstraintRule` / `SignalSpec` objects;
- set `candidate.claim = check.label`, `candidate.root_cause` from `check.kind`,
  `candidate.cited_signals` from the check, `supported_action = check.action`,
  and `mechanism = check.advice` for compatibility;
- map `must_be_unusual` → `primary_signals` and `require_all:
  [has_primary_signal_anomaly]`;
- map `must_stay_normal` → `forbidden_anomaly_signals` and
  `veto_if_any: [has_instrumentation_contradiction]`; the v1
  `corroboration_signals` field keeps its original all-nominal semantics;
- map missing required signals → `forbid_any: [has_missing_required_evidence]`;
- generate `threshold_source` as `yaml:<tool>:<signal>:alert_at=<value>`;
- keep `unit: null` when unknown.

`src/config_writer.py` writes v2. The UI YAML view/editor uses v2. The demo
configs should migrate to v2; keep at least one v1 fixture to test backward
compatibility. The v1 loader remains for existing tests.

### 5.5 Model roles

Add to `config/models.yaml`:

```yaml
MAPPING:
  model: "nvidia/Nemotron-3_5-Lightning"
  base_url: "https://api.tokenfactory.nebius.com/v1/"
SYNTHESIS:
  model: "nvidia/Nemotron-3-Ultra-550b-a55b"
  base_url: "https://api.tokenfactory.nebius.com/v1/"
```

(Use the exact IDs already in the file; do not invent new ones. If the current
file uses different IDs, keep them and add the role.)

Role usage:

- **Column mapper** (`MAPPING`): unknown export → proposed columns, labels,
  roles, units (`null` if unknown), and an empty draft checks list.
- **Cause finder** (`SYNTHESIS`): evidence → possible causes with saved check ids
  or `"new"`.
- **Challenge check** (`SYNTHESIS`): confirmed check + evidence → one
  disconfirming expectation.
- **Explanation** (optional, `SYNTHESIS`): one paragraph from the result and the
  evidence; it cannot change the result.

All calls: bounded payload, Pydantic `extra="forbid"`, evidence IDs validated,
one repair attempt, then fail closed. The deterministic result still runs if the
call fails.

### 5.6 Simplified model output

Cause finder returns:

```json
{"possible_causes": [
  {"check": "coolant_leak", "title": "Coolant loop fault",
   "why": "Both coolant channels moved together.",
   "evidence": ["EV_007", "EV_008"]}
]}
```

Challenge returns:

```json
{"challenge": "Chamber pressure should also move if this is a real coolant leak.",
 "evidence": ["EV_009"], "expected": "IONGAUGEPRESSURE unusual"}
```

No `root_cause`, `failure_mode`, `mechanism`, `status`, or `action` in the model
response. Python fills those from the matched check. A `"new"` check is
**Needs Review** and has no inspection action until the engineer saves it.

## 6. YAML v2 (the only user-facing schema)

The full contract is in `docs/YAML_GUIDE.md`. Minimum shape:

```yaml
version: 2
tool: {name: ion_mill_m02, label: Ion Mill M02, description: "..."}
baseline: {mode: lead_in, rows: 200}
signals:
  - {name: FLOWCOOLFLOWRATE, label: Coolant flow, unit: null, alert_at: 3.5}
  - {name: FLOWCOOLPRESSURE, label: Coolant pressure, unit: null, alert_at: 3.5}
  - {name: IONGAUGEPRESSURE, label: Chamber pressure, unit: null, alert_at: 3.5}
checks:
  - id: coolant_leak
    label: Coolant loop fault
    kind: equipment_fault
    must_be_unusual:
      - {signal: FLOWCOOLFLOWRATE, direction: any}
      - {signal: FLOWCOOLPRESSURE, direction: any}
    must_stay_normal: [IONGAUGEPRESSURE]
    action: INSPECT_COMPONENT
    advice: Inspect the coolant loop before changing the recipe.
```

Rules:

- `signals` are the only columns; `name` must match the CSV header exactly.
- `baseline` is required for v2; `lead_in` and `nominal_file` are the core modes.
- `checks` replace `scenarios`; each check is a fault pattern.
- `must_be_unusual` is all-of; `must_stay_normal` is the contradiction set.
- A missing required signal is **Data Incomplete**, automatically.
- A signal cannot be in both sets; a check with no `must_be_unusual` is invalid.
- No `candidate`, `predicates`, `rules`, `root_cause`, `failure_mode`, or
  `mechanism` in v2.
- Unknown keys fail loudly. No silent typos.

## 7. UI changes (keep the layout)

The app reads `docs/ui/*.md` at runtime. Keep the filenames; rewrite the content.

- **Result card:** six result words; one action phrase; one plain-language “why”.
- **Differential card:** the table above, below the result. Collapsed if empty.
- **What else moved:** unexplained signals with labels and plain z (not raw
  enum names). This is the coverage card.
- **Audit tab:** evidence IDs, raw status, model role, payload size, challenge
  text, unresolved citations. Internal names are allowed here only.
- **YAML page:** a commented YAML editor with a read-only signal summary.
  Add/remove signal and check lines in the YAML; the file is the primary UX.
  Show the v2 example from `docs/YAML_GUIDE.md`.
- **Demo page:** fix the labels. TEP IDV3 is **Needs Review**, not “Regular
  Behavior”. PHM nominal is **Regular Behavior** only if truly nominal. PHM demo
  is **Fault Confirmed** only if coverage passes.
- **Performance page:** honest benchmark summary; no 100%/0% chart. If the new
  run is not done, say “benchmark in progress” and link the protocol.
- **Contact page:** track **Best Apps and Agents**, real demo URL, video URL.
- **Home/about:** keep the existing structure; update the claims to “the model
  proposes; Python checks; the engineer decides.”

Do not add a new navigation item unless it replaces one. Do not change colors,
fonts, card style, or page order. The UI should look like today’s UI with better
words and two new cards.

## 8. Benchmark vs Gemini / ChatGPT / Nemotron-only

Read `docs/EVALUATION.md` for the full protocol. Build:

- `benchmarks/evaluator/naive_llm_benchmark.py` with `--provider
  gemini|openai|nebius`, `--track evidence|raw`, `--case`, `--print-prompt`,
  `--ingest`, `--out`.
- `benchmarks/evaluator/cases.yaml` with 8 balanced cases and ground truth.
- `benchmarks/evaluator/results/naive_llm/<date>/` artifacts: `manifest.json`
  (git SHA, model versions, prompts, input hashes), per-case raw output, and
  `summary.json`.

The prompt must be neutral: no scenario name, no dataset name, no cause, no
expected action. Use the same action menu for every system, including
`HOLD_LOT` and `ADJUST_RECIPE` so a naive model can choose them; FabAgent cannot.
Score:

- **unsafe action rate** (lower is better);
- **correct cause rate** (higher);
- **appropriate abstention** (higher);
- **false-alarm rate** (lower);
- **evidence accuracy** (higher).

Do not headline “decisiveness”. Do not use the old leaked sheets. The only
current measured baseline is Nemotron-only **2/5 safe** on five synthetic safety
cases; label it as one small baseline. If API keys are unavailable, build the
runner and print-prompt/ingest path, leave the summary empty, and do not invent
numbers. The UI performance page must read the committed `summary.json` or say
“benchmark in progress”.

## 9. Implementation phases

Work in order. After each phase, run the full verification and report. Do not
start the next phase until the current one is green.

### Phase 1 — vocabulary and false-claim fixes (no schema change)

Files: `src/ui/presentation.py`, `src/ui/app.py`, `src/action_guidance.py`,
`src/demo_catalog.py`, `docs/ui/*.md`, tests.

- Add the six result words and the action phrases; centralize the mapping in
  `src/ui/presentation.py`.
- Fix TEP IDV3: **Needs Review**, not “Regular Behavior”.
- Fix the “every checked sensor is within normal range” claim when an anomaly
  exists; use the actual evidence.
- Fix the VETOED/root_cause mismatch: a contradiction shows **Sensors
  Disagree**, and `instrumentation_fault` is emitted when the contradiction is
  the reason.
- Remove hardcoded `3.50z`; read the active threshold.
- Make the live badge use `result.model_called`, not `result_mode`.
- Add `ANALYSIS_CONTRADICTED` to Tavily triggers (if Tavily is enabled).
- Do not show `VETOED`/`SUPPORTED`/`INSUFFICIENT` in the main flow.
- Acceptance: no internal enum in the main UI strings; demo labels correct;
  tests updated; all green.

### Phase 2 — YAML v2 + baseline + coverage

**Status: complete (2026-10-26).** `lead_in` and `nominal_file` are scored;
`recipe_step` validates but fails closed until per-step scoring exists. The
legacy W5 TEP comparison deliberately keeps its published global baseline until
Phase 5.

Files: `src/config_types.py`, `src/config_loader.py` (or new
`config_loader_v2.py`), `src/config_writer.py`, `src/core/types.py`,
`src/core/duckdb_exec.py`, `src/core/pipeline.py`, `config/sensor_relations/*`,
`src/demo*`, tests.

- Add `BaselineSpec` and the `lead_in` / `nominal_file` modes.
- Add the v2 loader and writer; keep v1.
- Migrate the demo/product configs to v2; keep a v1 fixture test.
- Add `Coverage`; enforce the `|z| >= 5` unexplained rule.
- Regenerate/fix the PHM samples and demo labels.
- Acceptance: v1 and v2 load; same v1-equivalent result for the old configs;
  the fault-centred and lead-in PHM slices agree; the nominal sample is clean;
  coverage prevents a false “Fault Confirmed” in the 591z/946z case; all green.

### Phase 3 — model roles + differential + challenge

Files: `config/models.yaml`, `src/agents/*`, `src/schemas/models.py`,
`src/experimental.py`, `src/core/pipeline.py`, `src/ui/presentation.py`, tests.

- Add `MAPPING`/`SYNTHESIS` roles; no hardcoded IDs.
- Add the simplified cause/challenge responses; validate evidence.
- Evaluate all checks; build the differential result.
- Add the challenge call and the downgrade rule.
- Add the Auto draft (mapper) using v2.
- Acceptance: a model-proposed cause without a saved check is **Needs Review**;
  a failed challenge downgrades; a failed model call still produces a
  deterministic result; all green.

### Phase 4 — UI integration (keep the layout)

**Status: complete (2026-10-26).** The result page now carries the six words,
the action, the differential, and “What else moved”; the Audit section exposes
evidence IDs, raw statuses, model roles, payload size, and the challenge. The
Run page edits v2 in a commented YAML editor with a read-only summary; the
upload template is v2; the performance page no longer shows the old 100%/0% chart.

Files: `src/ui/app.py`, `src/ui/presentation.py`, `src/ui/config_promotion.py`,
`docs/ui/*.md`, tests.

- Result card: six words + action + why.
- Differential card; “What else moved” card.
- Audit tab: evidence IDs, raw status, model role, challenge, payload size.
- YAML page: commented YAML editor + read-only signal summary.
- Demo/performance/contact pages updated.
- Acceptance: every page renders offline; no internal enum in the main flow; the
  layout and navigation are unchanged; screenshots look like today’s UI.

### Phase 5 — fair benchmark

**Status: runner, cases, scoring, runbooks complete (2026-10-26); measured
summary pending provider keys.** The committed `summary.json` is intentionally
absent: no API key was available, so no number was invented. The UI performance
page says “Benchmark in progress” and shows only the already-committed
Nemotron-only 2/5 safe baseline.

Files: `benchmarks/evaluator/naive_llm_benchmark.py`, `cases.yaml`,
`benchmarks/evaluator/naive_llm_runbooks/`, `results/`,
`docs/ui/performance.md`, `docs/EVALUATION.md`.

- The runner supports `--provider gemini|openai|nebius`, `--track evidence|raw`,
  `--case`, `--print-prompt`, `--ingest`, `--write-runbooks`,
  `--materialize`, and `--out`.
- `cases.yaml` contains eight balanced cases (four fault/positive cases, two
  nominal/abstention controls, one unmodeled disturbance, one missing-channel
  case) with safe/unsafe actions and expected evidence sets.
- The prompt is neutral: no case id, dataset/scenario name, alarm note, cause,
  or expected action; the same cause/action menu is used for every system,
  including `HOLD_LOT` and `ADJUST_RECIPE`.
- Candidate artifacts: `manifest.json`, per-case prompt/response/score JSON,
  `cases.yaml`, and `summary.json` in the selected output directory.
- Gemini/ChatGPT runbooks are generated under
  `benchmarks/evaluator/naive_llm_runbooks/2026-10-26/evidence/` and
  `.../raw/`; a response is scored with `--ingest`.
- A missing or unparsable answer is recorded and scored as a failure.
- Triage was corrected so a missing primary channel still reaches its saved
  check and becomes **Data Incomplete** instead of falling through to Auto.
- Acceptance: prompt has no leak; per-case artifacts; summary; UI reads the
  summary or says “in progress”; no invented numbers.

### Phase 6 — docs and cleanup

- Update `docs/STATUS.md`, `README.md`, `docs/ui/*.md`, `AGENTS.md` if needed.
- Ensure the archived docs stay archived.
- Acceptance: `git status` only has intentional files; no keys; no `.archive` in
  the public tree; all verification green.

## 10. Acceptance tests (must exist)

Add tests for:

- **Vocabulary:** no `VETOED`, `SUPPORTED`, `INSUFFICIENT`, `EXPERIMENTAL`,
  `UNVERIFIED`, `hypothesis_class` in the main UI strings (audit excluded).
- **v2 loader:** valid config; duplicate signal; duplicate check; empty
  `must_be_unusual`; signal in both sets; undeclared signal; bad action; bad
  kind; unknown key; bad baseline.
- **v1 compatibility:** the existing v1 configs still load and produce the same
  results.
- **Baseline:** `lead_in` uses only the lead-in; `nominal_file` uses the nominal
  file; a fault in the evaluation window is detected; a short file fails with a
  clear error.
- **Coverage:** a supported check with an unexplained `|z| >= 5` signal is
  **Needs Review**; 1–2 moderate unexplained signals are shown but do not
  downgrade.
- **Differential:** two checks produce two rows; a contradiction is **Sensors
  Disagree**; a missing signal is **Data Incomplete**.
- **Challenge:** a met expectation keeps the result; an unmet expectation
  downgrades; an unresolved citation is ignored; a malformed response does not
  crash.
- **Auto:** an unconfigured cause is **Needs Review**; a draft with no checks is
  **Unknown Machine**; saving the draft makes the next run deterministic.
- **Benchmark:** the prompt has no case/dataset/cause/answer; scoring maps
  actions correctly; a missing/ unparsable output is recorded as a failure, not
  dropped.
- **UI:** all pages render offline; the six words appear; the layout test (if
  any) still passes.

## 11. Verification

After every phase:

```sh
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/ruff check .
.venv/bin/basedpyright
PYTHONPATH=. .venv/bin/python benchmarks/evaluator/synthetic_abstention_runner.py
PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.dossier_e2e_runner --offline
PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.experimental_e2e_runner
PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.e2e_suite_runner
```

Also launch the UI offline and click every page:

```sh
.venv/bin/streamlit run src/ui/app.py
```

A phase is not done until all commands are green and the UI renders every page
with no key.

## 12. Definition of done

- The UI looks like today’s UI; the result words are the six words; no internal
  enum in the main flow.
- The YAML is v2: signals + baseline + checks; a new user can read it; v1 still
  loads.
- The same physical fault gives the same result across the PHM slices; the
  nominal sample is clean.
- A supported check with a large unexplained anomaly is **Needs Review**.
- The differential table shows more than one possible cause.
- The model proposes and challenges; Python decides; a failed model call does not
  break the deterministic result.
- The benchmark runner and protocol exist; any number shown is backed by a
  committed artifact; the old leaked 100%/0% claim is gone.
- 134+ tests, ruff, pyright, W3, e2e all green; offline demo works; live mode
  works with server-side keys.
- The archived docs are still archived; no keys or private data in the repo.

## 13. What not to do

- Do not rewrite `src/core/` into a new architecture. Extend it.
- Do not let the model choose the result or the action.
- Do not let the model invent a check that maps to an action.
- Do not show `VETOED`, `SUPPORTED`, `INSUFFICIENT`, `EXPERIMENTAL`,
  `UNVERIFIED`, or `hypothesis_class` in the main UI.
- Do not use a global baseline for the new v2 configs.
- Do not call a 591z/946z result “Fault Confirmed” without coverage.
- Do not use the old leaked benchmark prompts or their 100%/0% numbers.
- Do not redesign the UI or add pages.
- Do not print keys or raw completions.
- Do not commit `.archive/`, `.venv/`, private ground truths, or raw datasets.
- Do not micro-commit.

## 14. Report format

After each phase, report:

1. **What changed** (files, one line each).
2. **What is green** (the seven commands, with the actual output).
3. **What is still red / deferred** (honest list).
4. **UI check** (which pages you opened; a screenshot path if possible).
5. **Next phase** (one paragraph).

Stop and ask before a destructive change (deleting a config, changing the license,
rewriting the UI, or changing the action enum). Otherwise, proceed in small,
tested steps.

## 15. File map (where to change)

| Area | Files |
|---|---|
| Entry / routing | `src/analyze.py`, `src/triage.py`, `src/dossier.py` |
| Core | `src/core/types.py`, `evidence.py`, `duckdb_exec.py`, `statistics.py`, `pipeline.py`, `sufficiency.py`, `constraints.py`, `safety_gate.py` |
| Config | `src/config_loader.py`, `src/config_types.py`, `src/config_writer.py`, `config/sensor_relations/*.yaml` |
| Models | `src/agents/model_transport.py`, `proposal_request.py`, `mapping_request.py`, `rca_engine.py`, `src/schemas/models.py` |
| Auto | `src/experimental.py` |
| UI | `src/ui/app.py`, `src/ui/presentation.py`, `src/ui/config_promotion.py`, `docs/ui/*.md` |
| Demo | `src/demo.py`, `src/demo_catalog.py`, `src/demo_data.py`, `samples/` |
| Benchmarks | `benchmarks/evaluator/*`, `benchmarks/datasets/*`, `benchmarks/synthetic_twin/*` |
| Docs | `docs/STATUS.md`, `docs/ARCHITECTURE.md`, `docs/UI_VOCABULARY.md`, `docs/YAML_GUIDE.md`, `docs/EVALUATION.md`, `README.md`, `AGENTS.md` |

If a file is not listed, read it before changing it. Keep the existing style,
types, and test patterns.
