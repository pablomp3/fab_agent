# Known Challenges for New Adoption

FabAgent is deliberately **fail-closed**: when it cannot ground a conclusion in
evidence, it abstains or escalates instead of guessing. That is the right safety
default, but it creates adoption friction. This document lists the **open**
challenges only; resolved items were removed as they were closed.

The product entry point is `analyze_csv(csv, note)` in
[`src/analyze.py`](file:///home/pablo/code/nvidia/fab_agent/src/analyze.py). It
runs the deterministic safe path (`analyze_dossier`) first and, only when no
tool schema matches, automatically falls back to the experimental mapping
(`analyze_experimental`). The router is `src/triage.py`.

> Previously listed here and now resolved (removed): the payload budget split
> (evidence summary vs. full request), the route/action conflation (typed
> `AnalysisOutcome` + `SuggestedAction`), and "no config → always escalate"
> (now an automatic experimental fallback, see #2). Scenario-level
> `supported_action` is now declared for the product and synthetic configs, so
> a supported run can recommend `INSPECT_COMPONENT` instead of always
> escalating; abstentions still fail closed.

---

## 1. Unknown thresholds and units stay unknown

* **Symptom:** Channels configured with `robust_z_threshold: null` are reported as
  `NOT_EVALUATED`, and units may be `null`.
* **Why:** The project never invents a threshold or unit. MAD is computed on the
  input itself; a nominal baseline is provenance, not calibration.
* **Current behavior:** Honest `NOT_EVALUATED` / `null`.
* **Direction:** Populate thresholds from an authoritative source (vendor spec or
  a measured nominal baseline) in the config.

## 2. Experimental mapping is an unverified inference

* **Symptom:** For a CSV with no matching schema, the system auto-runs the
  experimental mapping and reports `EXPERIMENTAL_UNVERIFIED_MAPPING`; the result
  is a **draft** mapping, not a verified diagnosis.
* **Why:** Column semantics are inferred by the model from names and bounded
  statistics. A wrong mapping yields a confidently wrong *statistic*. Opaque
  names (e.g. `a`,`b`,`c`) get plausible-looking but meaningless role guesses.
* **How it is contained:** every proposed column is validated in Python before any
  scan; the scan uses a documented default threshold; evidence is tagged
  `unverified_mapping`; units stay `null` in evidence and in the draft YAML. The
  model's `unit_guess` is surfaced only in the mapping proposal and is never
  propagated. The gated candidate is configuration-authored (`root_cause:
  unknown` for a draft); the model's proposed claim is displayed only as a
  narrative and is never the basis of the verdict.
* **Current behavior:** The action is `REVIEW_DRAFT_MAPPING`. The W6 dashboard
  shows the detected columns, roles, and relationships, offers the draft YAML as
  a download, and can validate and save it as
  `config/sensor_relations/<name>.yaml` (the draft must round-trip through the
  engine's own loader, and an existing config is never overwritten without
  confirmation). The next run with those columns then uses the safe path.
* **Direction:** Let the operator edit individual role/unit assignments field by
  field before saving, rather than promoting the model's draft as-is.

## 3. Triage can be ambiguous when scenarios share channels

* **Symptom:** Synthetic B4a and B4e share the same columns, so triage cannot
  always tell them apart without the note.
* **Why:** Selection ranks signal coverage first, then note-keyword overlap,
  then names — a pragmatic heuristic, not semantic understanding.
* **Current behavior:** Deterministic tie-break; the benchmark gates do not use
  triage, so this does not affect W3/W4.
* **Direction:** Explicit scenario selection, or LLM-proposed scope validated by
  Python.

## 4. The live model narrative is non-deterministic; the gate is not

* **Symptom:** The same live case can produce a usable model explanation on one
  attempt and no explanation on the next.
* **Why:** Provider sampling is non-deterministic even at `temperature=0`.
* **What changed:** The gated claim, class, root cause, and citations now come
  from the configured `candidate`, not from the model's free text. The model's
  proposal is shown as a separate "not gated" narrative. If the model call
  fails or returns invalid JSON, the deterministic gate still runs on the
  configured candidate and records the sanitized failure category as a required
  next check.
* **Measured before the alignment (W4):** **4 of 5 supported attempts (rate
  0.80)** on the B4e positive control, recorded in
  `benchmarks/evaluator/results/w4_positive_stability.json` (per-attempt
  statuses). One supported run is recorded in
  `benchmarks/evaluator/results/w4_positive_check.json`. This artifact measures
  proposal availability, not the current gate's determinism.
* **Measured (user story, live 2026-10-04):** on the fault-centered PHM sample
  the live model returned `INSUFFICIENT` (→ `COLLECT_MORE_DATA`), while both
  experimental uploads mapped signals and returned a `SUPPORTED` unverified
  hypothesis (→ `REVIEW_DRAFT_MAPPING`). See
  `benchmarks/evaluator/results/user_story_live.json`.
* **Current behavior:** Report the live path as a measured rate, never as a
  guarantee. The offline path is the deterministic reference.

## 5. Explanations are deterministic templates (explainer call deferred)

* **Symptom:** The explanatory sentence is identical for every run with the same
  action.
* **Why:** The MVP uses Python templates in `src/action_guidance.py` so the text
  is guaranteed faithful and free.
* **Direction:** An optional bounded "explainer" model call could rewrite the
  sentence for analysis runs, receiving only the outcome, the action, the gated
  hypothesis statuses, and the bounded evidence summary. It would never change
  the outcome or the action.

## 6. `HOLD_LOT` is deliberately not offered

* **Symptom:** The system never recommends holding a lot.
* **Why:** Holding a lot is too consequential for this MVP; `INSPECT_COMPONENT`
  (when a scenario declares it) plus `ESCALATE_TO_ENGINEER` cover the supported
  case, and a human decides.
* **Direction:** Revisit only with a calibrated yield-impact model and explicit
  owner approval.

## 7. Downstream features and comparisons are not built

* External knowledge retrieval (Tavily / local RAG) is not implemented.
* Wafer-map spatial predicates need calibrated feature bounds before they can
  match; without them a spatial cause cannot be claimed.
* Broad accuracy is not measured; results are tied to the configured
  relationships and are **not** field validation.
* A measured naive-LLM baseline comparison is not yet recorded. The W4 positive
  control is a gate check, not a baseline study; it does not show that the gate
  beats an unconstrained model. The harness is
  `benchmarks/evaluator/naive_llm_baseline.py`; its offline fixture is a harness
  check, not a live measurement.

---

## What a new fab must provide (checklist)

1. **CSV export** with stable column headers per tool.
2. **A sensor schema** (`config/sensor_relations/<tool>.yaml`) with `signals`,
   one or more `scenarios`, `predicates`, `rules`, and a `candidate`. This is
   still required for a **verified, deterministic** result.
3. **Thresholds and units** where an authoritative source exists; otherwise the
   system reports `NOT_EVALUATED` / `null` rather than guessing.
4. **Operator context** (the note) is optional and is a hint only.

Without item 2 the system now returns an **unverified experimental draft**
(§2) instead of escalating, so a config is optional for a first look but
required to trust a result.

---

## Experimental low-integration mode (automatic fallback)

* **Entry point:** `analyze_csv(csv, note)` in
  [`src/analyze.py`](file:///home/pablo/code/nvidia/fab_agent/src/analyze.py);
  the mapping lives in `analyze_experimental` in
  [`src/experimental.py`](file:///home/pablo/code/nvidia/fab_agent/src/experimental.py).
* **When it runs:** only when the safe path returns `NO_MATCHING_TOOL_SCHEMA`.
  When a schema matches, it never runs.
* **What it gives a fab with no config:** column profiling, a bounded
  model-proposed mapping validated in Python, a deterministic MAD scan of the
  validated signals, and a reviewable draft YAML config. It reports
  `EXPERIMENTAL_UNVERIFIED_MAPPING` and `REVIEW_DRAFT_MAPPING`.
* **What it is not:** RCA. It makes no physical root-cause claim, invents no
  units, marks every evidence record `unverified_mapping`, and is never field
  validation.
* **Measured:** offline `benchmarks/evaluator/results/experimental_phm_check_offline.json`;
  live `benchmarks/evaluator/results/user_story_live.json`.
