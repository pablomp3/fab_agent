# Status — 2026-10-28

## 0. 2026-10-28 UI polish and loader safety

- **Stale-server guard.** The app now runs a real minimal tool-model load and the
  promotion validator before rendering. An old Streamlit process is stopped with
  a restart instruction instead of showing “configuration version must be 1 or 2”.
- **YAML editor can no longer stay blank.** A stale empty widget is refilled from
  the saved tool model; there is a Reload saved YAML button and a download button.
- **Start here and How it works rebuilt.** A product-level HTML flow diagram now
  shows CSV + optional tool model → Nemotron → Python + DuckDB → result, with
  Tavily and the audit trail visible. The copy is shorter and leads with business
  value, then technical depth.
- **`docs/ui/about.md` and `docs/ui/models.md` rewritten** around the same
  division of labour; the old journal-style copy is gone.

## 0.1 2026-10-27 UI and schema cleanup

- **No service switches.** Nemotron and Tavily are part of the product. The
  sidebar shows live/offline status only; it does not let the user turn them
  off. A server key means live; no key means the deterministic offline fixture.
- **One-click demo fixed.** The demo no longer renders two “Analysis complete”
  blocks. It runs inside Step 2, uses a keyed dataset choice, and defaults to
  the public TEP feed case so the first result is **Fault Confirmed**.
- **Result state is scoped.** A result is dropped when the selected dataset or
  input source changes.
- **YAML is advanced-only.** The Run page shows a readable tool-model summary
  (normal reference, signals, checks, next step). The raw editor is behind
  “Advanced: edit the tool model YAML”; it no longer greets a new user with a
  460px text box.
- **Tool-model file has no version line.** Public configs omit `version`; the
  current schema is the only product schema. The v1 loader remains internal-only
  for the W3/W4 benchmark fixtures and is not referenced by the UI or docs.
- **Synthetic RF demo is v2.** `synthetic_rf.yaml` uses `corroborated_by` so a
  single RF spike with flat companions is **Sensors Disagree**, not a false
  equipment confirmation.
- **Auto promotion works.** The unknown-machine draft now has a form to add one
  engineer-authored fault check and save it; re-running the same upload makes
  the next result deterministic.
- **Coverage and z display fixed.** A coverage-demoted result now says which
  saved check passed and which signals remain unexplained. Very large robust z
  values display as “≥50z (very large)”; raw values stay in Audit.
- **Differential semantics fixed.** Unexplained coverage anomalies are no longer
  listed as “evidence against” a cause, and flat corroborating companions are
  correctly listed against a sensor-conflict claim.
- **Benchmark ground truth fixed.** The PHM coverage case now matches the
  pipeline’s evidence, and its cause is not scored because the safe result is
  **Needs Review**. The incomparable old 2/5 baseline is not shown in the
  eight-case table.
- **Measured eight-case evidence exists.** `results/naive_llm/2026-10-27/
  summary.json` records FabAgent (gate reference) **0/8 unsafe**, and live
  Nemotron-only **4/8 unsafe** with a false alarm on the nominal case. The naive
  prompt does not receive the saved checks; the report says so.

This is the only current status document. The old `IMPLEMENTATION_STATUS_HANDOFF.md`,
`handoff.md`, Gemini/Codex reviews, and `CRITIQUE_AND_WIN_PLAN.md` are archived
and historical. Do not treat them as current.

## 1. Verified green

Run on 2026-10-26 from `/home/pablo/code/nvidia/fab_agent`:

| Check | Command | Result |
|---|---|---|
| Unit tests | `.venv/bin/python -m unittest discover -s tests -q` | **203 tests, OK** |
| Lint | `.venv/bin/ruff check .` | **All checks passed** |
| Types | `.venv/bin/basedpyright` | **0 errors, 0 warnings** |
| W3 abstention | `PYTHONPATH=. .venv/bin/python benchmarks/evaluator/synthetic_abstention_runner.py` | **GREEN (cases=4, llm_calls=0)** |
| E2E both paths | `PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.e2e_suite_runner` | **safe 4/4, experimental 4/4** |
| W5 real-data | `PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.real_data_runner` | **PHM 1/1, TEP 10/10** |

The E2E safe results are currently:

- PHM flowcool: `ANALYSIS_INCONCLUSIVE` — the coolant check passes, but the
  v2 coverage rule demotes the result because other declared channels contain
  large unexplained anomalies. The product word is **Needs Review**.
- TEP IDV6: `ANALYSIS_SUPPORTED`.
- TEP IDV3: `ANALYSIS_INCONCLUSIVE` (**Needs Review**).
- Synthetic B4a: `ANALYSIS_CONTRADICTED`.

The PHM demo slice and the fault-centred slice now agree because both use the
same clean `nominal_file` baseline. W5.5 and the fault-centred e2e run no longer
flip between supported and inconclusive.

## 2. What works

- Deterministic core: DuckDB median/MAD, evidence IDs, predicates, hard
  contradiction, typed action, fail-closed.
- UI: upload, optional note, analysis, result card, evidence, audit, demo mode,
  YAML view, benchmark/contact pages.
- Offline demo: key-free; live mode: Nebius Nemotron + Tavily.
- Auto/experimental fallback: column mapping, draft YAML, review/promotion;
  a model-proposed cause without a saved check stays **Needs Review**.
- Differential result: every saved check is scored, one challenge can downgrade
  a confirmed check, and coverage is shared across checks.
- Fair-benchmark runner: neutral prompts, 8 balanced cases, Gemini/ChatGPT
  runbooks, per-case artifacts, and a summary reader on the performance page.
- W3: adversarial abstention with zero LLM calls.
- 2 KB payload bound; raw telemetry stays in DuckDB.
- 203 tests, ruff, pyright clean.

## 3. P0 — false or unsafe claims

Fixed in Phase 1 (2026-10-26):

1. **TEP IDV3 no longer says “Regular Behavior”.** The result word is derived
   from the evidence: an unexplained `3.93z` anomaly is **Needs Review**, and
   the action is “Ask an engineer to review”.
2. **A contradiction now emits `instrumentation_fault`.** `VETOED` overrides the
   configured `root_cause` in the structured hypothesis, so the UI and the audit
   record agree.
3. **No hardcoded `3.50z`.** `Evidence.threshold` carries the configured value;
   the findings, table, and chart read it (and show `—` when unset).
4. **The live badge uses the run.** Offline stays “Offline demo fixture”; a live
   run with no usable narrative says “AI explanation unavailable”; only a
   returned explanation says “Live Nemotron”.
5. **Tavily runs on `ANALYSIS_CONTRADICTED`.** A contradiction is exactly when
   an external lead helps; the search still cannot change the gate.
6. **The “every checked sensor is within range” claim is evidence-derived.** It
   is only used when no anomaly and no missing channel exist.
7. **Main-flow copy is clean.** `hypothesis_class` is no longer displayed in the
   AI tab; action phrases follow `docs/UI_VOCABULARY.md`; a regression test scans
   every demo result card for internal enum tokens.

Fixed in Phase 2 (2026-10-26):

1. **PHM baseline inconsistency.** The v2 loader accepts `lead_in` and
   `nominal_file`; the PHM config uses a clean 900-row `nominal_file`. The
   fault-centred and demo slices agree, and the nominal control reads
   **Regular Behavior**.
2. **The nominal sample is clean.** `M02_DC_01_nominal_sample.csv` was
   regenerated from a normal window whose own robust-z maximum is below 3.5 for
   every configured channel.
3. **Coverage prevents a false confirmation.** Every declared signal is scored.
   A supported result is demoted to `INSUFFICIENT` when an unexplained anomaly
   has `|z| >= 5`; the limit lives in `src/policy.py`, not in a YAML
   file and not in `src/core/`. The fault slices show **Needs Review**, not **Fault Confirmed**.

Fixed in Phase 3 (2026-10-26):

1. **All saved checks are assessed.** One evidence pass is shared by every
   configured check, and the result includes a differential row for each check.
   Shared coverage means one check's channels do not demote another check.
2. **The cause finder can only propose.** It names a saved check or `new` and
   cites evidence IDs Python already produced. A `new` cause is Python-set to
   `INSUFFICIENT` and shown as **Needs Review**; it never carries a confirmed
   action.
3. **The challenge check can only downgrade.** One model-proposed disconfirming
   test is evaluated against the evidence. If it is not met, the confirmed check
   becomes `INSUFFICIENT`; a malformed or unresolved challenge is ignored and
   marked **AI challenge unavailable**.
4. **A failed model call is still deterministic.** The Python gate runs first
   and the route/action survive a transport, schema, finish-reason, or size
   failure. No raw completion or key is logged.
5. **The mapping role is separate.** `MAPPING` has its own configured role and
   environment override; auto mode still writes a v2 draft and now records a
   model-proposed cause as an unverified differential row, not a supported one.
6. **`must_stay_normal` semantics are explicit.** v2 maps the field to
   `forbidden_anomaly_signals`: a listed signal that moves is the contradiction.
   v1 `corroboration_signals` keeps its original all-nominal semantics.
7. **The saved relative baseline path survives the UI temp copy.** Before a
   demo/generated YAML is written to the run directory, its relative
   `baseline.file` is resolved from the saved config. The Needs Review card also
   names the actually unexplained large signals, not the check's own channels.

Known limitation carried forward: `must_be_unusual.direction` is validated but
not yet scored because evidence stores an absolute robust-z value. The shipped
configs use `any`; rejecting or scoring `up`/`down` needs signed evidence.

Fixed in Phase 4 (2026-10-26):

1. **The result page uses the six words with the engineer's labels.** The run
   carries `signal_labels` from the selected v2 tool model; the headline, why
   bullets, differential, and “What else moved” card name “Coolant flow”, not
   `FLOWCOOLFLOWRATE`.
2. **The differential is visible.** Every saved check renders as a row with
   evidence for, evidence against, and one of the six result words. An
   unconfigured model cause is a **Needs Review** row, never an action.
3. **Coverage is visible.** The “What else moved” card lists every unexplained
   declared signal and marks the large subset. It is shown even when the
   headline stays **Fault Confirmed**.
4. **The Audit section is real.** Evidence IDs, raw statuses, gated statuses,
   model roles, the bounded payload size, the challenge text, and unresolved
   citations live in “Measurements & Audit”; the result card and AI narrative
   stay in plain language.
5. **The tool model is YAML-first.** The Run page shows the commented YAML
   directly with a read-only signal summary; add/remove signal and check lines
   after reading the comments. The upload template is now v2; every run still
   goes through the same loader.
6. **No model IDs in the user-facing UI.** The sidebar and How-it-works page
   show role names (“Nemotron synthesis (server-side)”), not provider model IDs.
7. **The old 100% vs 0% chart is gone.** The performance page says “Benchmark in
   progress” and shows only the committed Nemotron-only 2/5 safe baseline until
   Phase 5 writes a summary. No chart is drawn from an unmeasured number.
8. **Copy fixes.** `CONTINUE_MONITORING` no longer says a fault was supported,
   and `ANALYSIS_INCONCLUSIVE` no longer maps directly to **Regular Behavior**.
9. **A stale Streamlit module is detected.** A server that started before the
   v2 loader now shows a “restart once” message instead of failing with
   “configuration has unknown keys: baseline, checks, tool”. The YAML itself is
   unchanged and valid.

Started in Phase 5 (2026-10-26):

1. **The fair benchmark runner exists.** `benchmarks/evaluator/naive_llm_benchmark.py`
   supports `--provider gemini|openai|nebius`, `--track evidence|raw`,
   `--case` (number or id), `--print-prompt`, `--ingest`, `--write-runbooks`,
   and `--out`. It writes `manifest.json`, per-case prompt/response/score JSON,
   `cases.yaml`, and `summary.json`; an unparsable answer is recorded as a
   failure.
2. **Eight balanced cases exist.** `cases.yaml` covers four fault/positive
   cases, two nominal/abstention controls, one unmodeled disturbance, and one
   missing-channel case, with safe/unsafe actions and expected evidence sets.
3. **The prompts are neutral.** No case id, dataset/scenario name, alarm note,
   cause, or expected action; every system gets the same cause/action menu,
   including `HOLD_LOT` and `ADJUST_RECIPE`.
4. **Gemini/ChatGPT experiments are ready.** The copy/paste sheets are under
   `benchmarks/evaluator/naive_llm_runbooks/2026-10-26/evidence/` and
   `.../raw/`, with an ingest command for each case.
5. **Triage now reaches Data Incomplete.** A missing primary channel no longer
   falls through to Auto mode just because the primary subset is incomplete; the
   saved check runs and returns **Data Incomplete**.

Still P0:

1. **Gemini/ChatGPT benchmark rows are still pending.** The eight-case
   Nemotron-only run is committed in
   `benchmarks/evaluator/results/naive_llm/2026-10-27/summary.json`; the Gemini
   and ChatGPT rows need their provider keys or the manual runbooks. The UI
   shows the measured FabAgent and Nemotron-only rows plus the pending rows.
2. **W5 TEP remains on its published global baseline.** The TEP product config
   uses `lead_in`; the legacy W5 runner deliberately keeps the old global
   baseline so the recorded artifact is not silently rewritten.

## 4. P1 — the hybrid build

See [`HYBRID_IMPLEMENTATION.md`](HYBRID_IMPLEMENTATION.md). In short:

- six result words everywhere; internal enums only in Audit;
- one user-facing tool model (signals + baseline + checks); legacy v1 fixtures
  are internal benchmark tests only;
- baseline modes (`lead_in`, `nominal_file`, `recipe_step`; the first two are
  scored, `recipe_step` fails closed until implemented);
- coverage rule (no “Fault Confirmed” with large unexplained anomalies);
- differential table (all checks, not one scenario) — Phase 3 result model and
  Phase 4 card done;
- Nemotron roles: column mapper, cause finder, challenge check, explainer —
  Phase 3 roles wired; the explainer is the cause finder's `why` today;
- challenge/falsification downgrade — Phase 3 done;
- readable tool-model summary plus advanced YAML — Phase 4 done;
- fair benchmark runner, 8 cases, and Gemini/ChatGPT runbooks — Phase 5
  started; measured summary pending provider runs;
- keep the UI layout and pages.

## 5. P2 — submission

- Hosted Nebius URL (Streamlit, server-side keys).
- Public repo pushed; `origin/main` is still `fbc2bbd`.
- 3-minute video.
- Correct track: **Best Apps and Agents** (the old label “Industrial Copilot &
  Agentic Root Cause Analysis (RCA)” is not an official track).
- `docs/ui/contact.md` and `README.md` updated with the URL and video.
- Incognito test: upload, run, result, refresh; no key in the browser.

## 6. Repository state

- `HEAD` = `origin/main` = `fbc2bbd`.
- The entire UI/product overhaul is uncommitted (working tree only).
- No hosted URL in `docs/ui/contact.md`; it only says “port 8501”.
- Old docs are in `.archive/2026-10-26/` (ignored), not in the product.
- Do not commit `.archive/`, `.venv/`, raw keys, or private ground truths.

## 7. How to verify a change

```sh
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/ruff check .
.venv/bin/basedpyright
PYTHONPATH=. .venv/bin/python benchmarks/evaluator/synthetic_abstention_runner.py
PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.dossier_e2e_runner --offline
PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.experimental_e2e_runner
PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.e2e_suite_runner
```

A change is not done until all seven are green and the UI still renders every
page in offline mode.
