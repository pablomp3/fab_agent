# Anti-goals — hard prohibitions

Each item was considered and rejected with evidence. If you find yourself doing
one, you have reintroduced a known defect. Keep this list short; add an item only
with a concrete failure it prevents.

## A. Datasets

- **A1. No SECOM.** No units, no sensor semantics, no tool IDs. Mapping a
  `Feature_N` to a physical sensor is fabrication.
- **A2. WM-811K labels are shapes, not causes.** Use them only for spatial
  features or threshold calibration. Never infer `Edge-Ring ⇒ coater
  degradation`.
- **A3. Do not blend datasets into a synthetic “fab benchmark”.** A causal claim
  needs a causal generator, not a collage.
- **A4. Do not use SemiKong evaluation as ground truth.** It is LLM-judged on
  style criteria; it is not a numeric RCA label.
- **A5. Do not claim to beat SemiKong.** Different task (QA vs numeric diagnosis).
- **A6. Do not query the SemiKong ontology for causal validation.** Most modules
  are empty placeholders; it is a taxonomy, not a cause model.
- **A7. Do not evaluate TEP IDV 13 or 16–20 for attribution.** No ground truth
  (13 is an unmeasured latent parameter; 16–20 are labeled Unknown). IDV 3 and 9
  are abstention tests. Evaluable: IDV 1, 2, 4, 5, 6, 7, 14, 15.
- **A8. PHM 2018 is equipment-subsystem, not process-cause, validation.** Fault
  times are operator shutdown times, not onset.

## B. Architecture

- **B1. No vision model for wafer maps.** A wafer map is a sparse die grid, not a
  photograph. Compute numerical features; keep an `evidence_id`.
- **B2. No weighted evidence score.** Constants are unjustifiable and a
  contradiction can be outvoted. Use predicates with hard vetoes.
- **B3. No string-filter safety gate.** Constrain the output type so a recipe
  change is unrepresentable.
- **B4. No benchmark ID in `src/core/`.** `B1`…`B4d`, `IDV`, `PHM18`, `TEP`,
  `SECOM`, case IDs. Core is generic; benchmarks are configuration.
- **B5. No hardcoded model IDs in agent code.** Resolve roles through
  `config/models.yaml`.
- **B6. Do not let the LLM decide sufficiency.** Python computes it from
  predicates and coverage.
- **B7. Do not silently omit missing data.** Emit `MISSING_CHANNEL`; never
  impute or default to zero.
- **B8. Do not let `src/core/` import agents, tools, or UI.** One-way
  dependencies; core must run with no network, keys, or config.
- **B9. Do not let the model invent an actionable check.** In Auto mode a
  proposed cause that is not in the saved tool model is **Needs Review**, never
  `INSPECT_COMPONENT`.
- **B10. Do not use a global baseline for multi-step data.** Use a lead-in,
  nominal file, or per-recipe-step baseline. A global median hides a fault that
  occupies most of the window.
- **B11. Do not show internal enum names in the main UI.** `VETOED`,
  `SUPPORTED`, `INSUFFICIENT`, `EXPERIMENTAL_UNVERIFIED_MAPPING`,
  `UNVERIFIED_CLASS`, `hypothesis_class` belong in the audit view only.

## C. Evaluation

- **C1. Do not write a number you have not measured.** Every number in the
  README/UI traces to a committed artifact in `benchmarks/evaluator/results/`.
- **C2. Do not gate on an LLM-judged metric.** Deterministic metrics gate;
  model-judged metrics are report-only until calibrated.
- **C3. Do not aggregate by mean.** Gate on the minimum across cases; report the
  mean as secondary.
- **C4. Do not let a missing metric pass.** `MISSING` and `NOT_EVALUATED` fail
  the build.
- **C5. Do not leak the answer in a benchmark prompt.** No scenario name, no
  ground truth, no alarm note that names the cause, no answer menu that reveals
  the safe action. Use the same neutral prompt for every system.
- **C6. Do not compare a tool-assisted model with an unaided one without saying
  so.** Either disable code execution for all, or report a separate
  “vendor-default with tools” track.
- **C7. Do not hand-score without a rubric.** Publish the rubric, the raw
  outputs, the model version/date, and the input hashes.
- **C8. Do not call a fault-centred slice “normal”.** If the file contains the
  fault, it is not a nominal control.
- **C9. Do not write detector code before the generator spec is committed.** Git
  order is the anti-circularity proof.

## D. Claims

- **D1. Do not say “air-gapped”.** Say: raw telemetry stays in DuckDB; only a
  bounded statistical summary crosses the network.
- **D2. Do not say “zero integration”.** Say **low-integration** or
  **bring-your-own-export**. A CSV, a tool model, and manuals are required.
- **D3. Do not claim superiority over Exensio / Klarity / YieldExplorer.** The
  defensible niche is low-integration local triage with explicit abstention.
- **D4. Do not present synthetic results as field validation.** Required line:
  “Accuracy on the synthetic twin measures whether the agent recovers the cause
  we injected. It is not evidence about real-world field truth.”
- **D5. Do not frame it as “autonomous RCA”.** Frame it as an
  **evidence-gated troubleshooting copilot**. A human confirms every action.
- **D6. Do not claim “the AI never makes things up”.** Say: every model claim
  is checked against evidence, and the system abstains when the data is not
  enough.

## E. Process

- **E1. Do not edit this document to match the code.** If a constraint seems
  wrong, stop and report.
- **E2. Do not build the UI first.** The engine and its tests come first.
- **E3. Do not connect an LLM before the deterministic gate passes.** W3 must
  pass with zero LLM calls.
- **E4. Do not add a dependency without justification.** State what it does, why
  stdlib/existing deps cannot, and its transitive weight.
- **E5. Do not build an abstraction for fewer than three implementations.**
- **E6. Do not reference an employer’s proprietary repository.** No code,
  comments, commits, README, or video.
- **E7. Do not micro-commit.** Keep changes in working files until a phase or
  gate is complete, or the user asks.
