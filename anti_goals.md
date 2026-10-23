# ANTI_GOALS.md – Explicit Prohibitions

Everything here was **considered and rejected** with evidence. Each is a plausible-looking move that a competent engineer – or a model trained on 2024–2025 material – would reach for by default.

Stating them as prohibitions is the only reliable way to keep them out. If you find yourself doing any of these, you have reintroduced a known defect.

---

## A. DATASETS

### A1. Do not use SECOM. For anything.

1,567 runs × 590 features named `Feature_1`...`Feature_590`. No units, no tool IDs, no sensor semantics. Label is a single pass/fail bit.

Zero papers between 2008 and 2026 recovered the feature semantics. The anonymization was a precondition of release and there is no public key. **Mapping a SECOM feature to a physical sensor is fabrication**, and a judge who knows the dataset – plausible on an NVIDIA/Nebius panel – identifies it immediately.

Not even for "generic high-dimensional anomaly handling." It adds nothing the other substrates lack and carries the association.

### A2. Do not treat WM-811K labels as causes.

9 morphological pattern classes; 172,950 labeled of 811,457 (21.3%).

Patterns are **shapes, not causes**. One Edge-Ring pattern has many possible process causes and the dataset contains nothing to discriminate them. The pattern→cause tables in the literature self-describe as *"a literature summary, not fab-calibrated... never a root-cause diagnosis."*

Permitted: computing spatial features, and calibrating classifier thresholds against the morphological labels (honest, verifiable).  
Forbidden: any inference of the form *Edge-Ring ⇒ coater degradation*.

### A3. Do not blend datasets into a synthetic "fab benchmark."

Specifically: combining WM-811K morphology with SECOM features and presenting the result as a causal semiconductor benchmark. This was v1's B1. It is fabrication, and recognizable on sight.

### A4. Do not use the SemiKong evaluation set as correctness ground truth.

LLM-judged on six subjective style criteria, with GPT-4o-authored reference answers. The paper's own Table 6 reports **Claude-3-haiku 22.16 > Claude-3.5-Sonnet 21.25** – a metric that inverts that ordering on process engineering is measuring formatting.

Using an LLM-judged benchmark as ground truth would also directly contradict this project's founding principle.

### A5. Do not claim to beat SemiKong.

Different task – knowledge-recall QA versus numeric diagnosis. Claiming victory on an unrelated, invalid benchmark is the same class of error as v1's fabricated metrics table.

Permitted: citing it as prior work, and using its 10-group process taxonomy as a UI filter / RAG routing tag.

### A6. Do not query the SemiKong ontology for causal validation.

Verified: 364 of 388 modules (93.8%) are empty placeholders. Zero occurrences of `causes`, `hasFailureMode`, `affectedBy`, or `resultsIn`. C4F8 absent entirely. Tooling is regex string-matching; `export-agentic.sh` contains `# TODO: Implement RDF parser`.

A taxonomy of process names cannot validate a causal hypothesis. Building a SPARQL validator over it costs two weeks and returns nothing. Write the project's own small explicit constraint model instead.

---

## B. ARCHITECTURE

### B1. Do not add a vision model.

Deleted deliberately, and not only because `Nemotron-3-Nano-Omni` and `Cosmos3-Super-Reasoner` were deprecated 2026-08-31.

A wafer map is a **sparse die-level pass/fail grid, not a photograph**. Rendering it to pixels so a VLM can report "looks like a ring" destroys quantities that are directly computable – radial profile, angular uniformity, edge-band concentration, component elongation – and replaces traceable evidence with an untraceable opinion.

Numerical extraction is more accurate, deterministic, reproducible, cheaper, and carries an `evidence_id`.

### B2. Do not reintroduce a weighted evidence score.

Specifically not `+0.35 / +0.25 / +0.20 / +0.20 / -0.40` with threshold `0.60`.

Two fatal problems: the constants are unjustifiable ("why 0.35 and not 0.45?" has no answer), and a contradiction worth only -0.40 can be **outvoted by accumulated weak support** – which defeats the entire abstention mechanism.

Use predicates with hard vetoes. More deterministic, more explainable, and a veto is absolute.

### B3. Do not implement the safety gate as a string filter.

An allowlist stripping `UPDATE_RECIPE` is defeated by *"increase RF by 5%"*, *"adjust the gas ratio"*, *"try a shorter over-etch"*.

Constrain the output **type** so free-form actions are unrepresentable. The suggested action is an enum; there is no field a recipe change can inhabit.

### B4. Do not let a benchmark identifier into `src/core/`.

Forbidden anywhere under `src/core/`: `B1`...`B4d`, `IDV`, `PHM18`, `TEP`, `SECOM`, or any case ID.

```python
if benchmark == "B4":  # ❌ this is a B4 detector, not a constraint engine
    if sensor_17 > 10:
        ...
```

Core implements generic engineering constraints; benchmarks supply YAML configuration. Enforced by `tests/test_no_benchmark_ids_in_core.py`.

This is what licenses the README claim: *"benchmark scenarios instantiate generic engineering constraints; they contain no benchmark-specific RCA answers."*

### B5. Do not hardcode model IDs in agent code.

All three v1 IDs were invalid and one model is now dead. The error was not picking wrong IDs – it was **hardcoding IDs at all**.

Roles resolve through `config/models.yaml`. Agent code says `TRIAGE`, never a model name.

### B6. Do not let the LLM decide evidence sufficiency.

If a prompt asks a model *"is this enough evidence to conclude X?"*, the architecture has been inverted. Sufficiency is computed in `src/core/sufficiency.py` from predicates.

### B7. Do not silently omit missing data.

A missing channel is diagnostically meaningful – it is why `INSUFFICIENT` exists. Emit `MISSING_CHANNEL` evidence. Never skip, never impute, never default to zero.

### B8. Do not let `src/core/` import from `src/agents/`, `src/tools/`, or `src/ui/`.

One-way dependencies. Core must be testable with no network, no keys, no config – which is exactly what the Week 3 gate proves.

---

## C. EVALUATION

### C1. Do not write a number you have not measured.

v1 contained a table claiming ~40% baseline accuracy, 100% FabAgent accuracy, ~70% hallucination rates – all invented before any code existed.

Every number in the README traces to a committed file in `benchmarks/evaluator/results/`. **A measured 68% beats an invented 95%**, because the first survives a judge asking to see the run.

### C2. Do not gate on an LLM-judged metric.

Deterministic metrics gate from day one. Model-judged metrics are report-only until thresholds are calibrated against committed real runs.

Gating on an uncalibrated judge trains you to ignore red – and would repeat the exact methodological error documented against SemiKong in §2.1.

### C3. Do not aggregate by mean.

Minimum across cases. If B4a–c pass and B4d fails, the mean reports 75% and a pattern matcher ships. Report mean as a secondary statistic; gate on the minimum.

### C4. Do not let a missing metric pass.

Fail-closed. `MISSING` and `NOT_EVALUATED` both fail the build. A malformed case file that silently drops a suite while everything reports green is the worst possible outcome for a project whose claim is evaluation rigor.

### C5. Do not evaluate root-cause attribution on TEP IDV 13 or 16–20.

IDV 16–20 are labeled `Unknown` in the original Fortran source; no ground truth exists. IDV 13's root cause is an **unmeasured latent kinetic parameter** – no XMEAS or XMV variable is the cause.

Evaluable for attribution: **IDV 1, 2, 4, 5, 6, 7, 14, 15** only. IDV 3 and 9 are abstention tests.

### C6. Do not claim PHM 2018 demonstrates process-cause attribution.

Its faults are **equipment-subsystem** failures in the flowcool circuit. They are not process causes and not yield labels. Fault timestamps are operator maintenance-shutdown times, not fault onset.

### C7. Do not build the Tier A/B/C ablation.

One vanilla baseline. The three-tier study is a small research paper and judges evaluate whether the system works, not the ablation table.

### C8. Do not write detector code before committing `GENERATOR_SPEC.md`.

The git commit order **is** the anti-circularity proof for the synthetic twin. Unrecoverable once violated – the history either shows the spec came first or it does not.

### C9. Do not let the same model write both the generator and the detector.

Shared assumptions are exactly what the pre-registration protocol exists to prevent. Different models, and they never see each other's code.

---

## D. CLAIMS

### D1. Do not say "air-gapped."

You call Nebius. Say what is true: raw telemetry stays in DuckDB; only bounded statistical summaries cross the network.

### D2. Do not say "zero integration."

You need CSV exports, a sensor schema, and manuals. Say **low-integration** or **bring-your-own-export**.

### D3. Do not claim superiority over Exensio / Klarity / YieldExplorer.

They win on integration depth and deployment maturity. Competing there loses. The defensible niche is low-integration local triage with explicit abstention.

### D4. Do not present synthetic results as field validation.

Required line: *"Accuracy on the synthetic twin measures whether the agent recovers the cause we injected. It is not evidence about real-world field truth."*

### D5. Do not frame the project as "autonomous RCA for semiconductor fabs."

That framing invites *"show me your root-cause labels"* – which do not exist publicly. Frame as an **evidence-gated troubleshooting copilot**. Identical code, very different judge reaction.

---

## E. PROCESS

### E1. Do not edit `design_v2.md` to match your code.

Read-only to the implementer. Disagreement → stop and report.

### E2. Do not build the UI first.

Streamlit is Week 6. A polished UI over an unproven core is the classic hackathon failure.

### E3. Do not connect an LLM before the Week 3 gate passes.

B4a–B4d must pass deterministically with **zero LLM calls**. If the safety story cannot stand on pure Python, no prompting repairs it in Week 4.

### E4. Do not add a dependency without justification.

State what it does, why stdlib or an existing dep cannot, and its transitive weight.

### E5. Do not build an abstraction for fewer than three implementations.

No plugin systems, registries, or factories until there are three real cases. Two is a coincidence.

### E6. Do not reference the employer's proprietary repository anywhere.

No code, no comments, no commit messages, no README, no video. The generic patterns adopted are independently standard practice and require no attribution – and attribution would create precisely the association to avoid.