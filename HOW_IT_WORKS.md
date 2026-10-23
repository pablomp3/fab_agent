# How FabAgent Works: Fast Executive Guide

## 1. The Business Problem

In semiconductor manufacturing, tools (etchers, polishers, CVD chambers) continuously stream sensor telemetry. When a disruption occurs:
* An alarm triggers on the tool during a wafer run.
* Downstream metrology spots yield loss or profile defects caused by that chamber.
* Post-maintenance requalification is needed.

**The Workflow:**
1. **Upload:** The fab engineer uploads the tool's raw sensor CSV and enters brief context (e.g., *"RF reflectometer excursion on Chamber B, wafer edge thinning"*).
2. **Profile Selection (Triage):** FabAgent matches the CSV's columns and the engineer's note against the configured tool schemas (`config/sensor_relations/*.yaml`) to pick a scope. If nothing matches, it automatically falls back to the unverified experimental mapping; it never presents a guessed mapping as a verified diagnosis.
3. **Deterministic Scan:** FabAgent uses DuckDB to run Median Absolute Deviation (MAD) anomaly checks directly on the scoped CSV channels and emits one evidence record per channel. Boolean physical predicates are then derived from that evidence.
4. **Configured Candidate + Model Narrative:** The tool configuration declares the candidate claim, class, root cause, and cited signals. NVIDIA Nemotron writes an explanatory narrative citing evidence IDs, while a deterministic Python safety gate assesses the **configured** candidate and blocks unsafe actions (like unauthorized recipe changes). The model's claim is shown separately and is never the basis of the verdict.

The product entry point for this whole flow is `analyze_csv(csv, note)` in
`src/analyze.py`. It runs the deterministic safe path (`analyze_dossier`) first
and, only when no tool schema matches, automatically falls back to the
experimental mapping (`analyze_experimental`); the fallback is clearly labelled
and never claims a physical root cause.

---

## 2. Telemetry Ingestion & MAD Anomaly Logic

### Fast Ingestion with DuckDB
Industrial CSV logs reach hundreds of megabytes or gigabytes. Loading them into standard Python memory causes crashes and latency. FabAgent uses an in-memory **DuckDB** columnar engine to stream and scan multi-GB files in milliseconds without memory overhead.

### Why Standard Deviation Fails: Outlier Masking
Traditional 3-sigma monitoring ($\mu \pm 3\sigma$) fails on sensor spikes because of **outlier masking**:
* A severe spike inflates both the sample mean ($\mu$) and standard deviation ($\sigma$).
* The blown-up variance widens the threshold, causing subsequent real anomalies to be missed.

#### Quick Example: 5 Sensor Readings `[10, 10, 10, 11, 1000]`
* **Standard Mean & Sigma ($\mu \pm 3\sigma$) Failure:**
  - $\text{Mean } \mu = \frac{\sum X}{N} = \mathbf{208.2}$, $\text{Std Dev } \sigma = \sqrt{\frac{\sum (X - \mu)^2}{N}} \approx \mathbf{442.6}$.
  - Upper threshold ($\mu + 3\sigma$): $208.2 + 3(442.6) = \mathbf{1,536}$.
  - **The Masking Failure:** The massive outlier `1000` is **less than 1,536** ($1000 < 1536$), so it is **not flagged**! The spike inflated $\sigma$ so much that it masked itself.
* **Robust Median Absolute Deviation (MAD) Success:**
  - $\text{Median} = \mathbf{10}$ (stable baseline, completely unaffected by the outlier).
  - Absolute deviations $|X_i - \text{median}|$: $[0, 0, 0, 1, 990] \implies \text{baseline } \text{MAD} \approx 1$.
  - Robust $z$ for `1000`: $0.6745 \times \frac{|1000 - 10|}{\text{MAD}} \approx \mathbf{667} \gg 3.5$ (**Instant Anomaly Detected**).

### The Solution: Median Absolute Deviation (MAD)
MAD is non-parametric and immune to outlier distortion (50% breakdown point):

$$\text{MAD} = \text{median}\left(\left|X_i - \text{median}(X)\right|\right)$$

$$\text{Robust } z = 0.6745 \times \frac{\left|X_i - \text{median}(X)\right|}{\text{MAD}}$$

* **Why Threshold = 3.5?** Under normal distribution scaling, $|z| > 3.5$ represents an extreme tail probability of **$p \approx 0.05\%$** ($p \approx 0.00046$). This conservative threshold filters out routine fab noise while reliably catching true physical excursions.
* **Boolean Predicates:** Excursions are converted into strict deterministic facts (e.g., `has_primary_signal_anomaly`, `has_instrumentation_contradiction`, `has_missing_required_evidence`). A channel with no configured threshold is marked `NOT_EVALUATED`, never "normal".

---

## 3. Triple Validation Strategy

The system is validated across three public substrates. They show the deterministic contract holds on measured data; they are **not** field validation.

| Benchmark | What it Proves | Key Metric (measured) |
|---|---|---|
| **1. Synthetic Fab Twin** | Controlled causal recovery and zero-LLM abstention on adversarial cases. | **Zero-LLM abstention** on B4a–B4d (`w3_adversarial_check.json`); B4e reaches `SUPPORTED` offline (`w4_positive_check_offline.json`). |
| **2. PHM 2018 (Seagate Ion Mill)** | Subsystem evidence on 1.7M+ rows of real, noisy etcher telemetry. | The scoped flowcool candidate is `SUPPORTED / INSPECT_COMPONENT` on `M02_DC_01` (`w5_real_data_check.json`); one subsystem, not broad accuracy. |
| **3. TEP (Tennessee Eastman Reactor)** | Cause-vs-symptom scoping; abstains on unmodeled faults. | Feed-system candidate `SUPPORTED` for IDV 1/2/6 and `INSUFFICIENT / ESCALATE` (abstains) for non-feed faults (`w5_real_data_check.json`). |

> Accuracy on the synthetic twin measures whether the agent recovers the cause we injected. It is not evidence about real-world field truth.

---

## 4. LLM Synthesis Behind Python Safety Gates

FabAgent uses an **evidence sandwich** architecture:

```
[CSV Telemetry] ──> [Python/DuckDB: Extract Facts] ──> [Config: Declare Candidate] ──> [LLM: Explain / Cite] ──> [Python Safety Gate: Assess Candidate + Enforce Action]
```

* **What the LLM Does:** Receives a bounded summary ($\le 2\text{ KB}$, plus a short engineer note and the configured candidate), interprets domain context, and writes an explanatory narrative citing specific `evidence_id` hashes. Its proposal is stored as `model_narrative` and displayed under "not gated".
* **What Python Enforces:**
  - **The configured candidate is the gated conclusion:** `candidate.claim`, `candidate.root_cause`, `candidate.hypothesis_class`, and `candidate.cited_signals` come from the tool configuration. The model cannot rename the claim or select the action.
  - **No LLM sufficiency:** Python resolves every configured citation and checks physical contradiction rules. A missing configured channel makes the candidate `INSUFFICIENT`; a hard contradiction makes it `VETOED`.
  - **Model failure does not erase the gate:** if the model call fails or returns invalid JSON, the deterministic gate still runs on the configured candidate and records the sanitized failure category as a required next check.
  - **No free-form actions:** Recipe changes (`UPDATE_RECIPE`) are unrepresentable — they are blocked by the schema. Actions are strictly typed `SuggestedAction` enums (`FIX_INPUT_FILE`, `AUTHOR_TOOL_CONFIG`, `REVIEW_DRAFT_MAPPING`, `REDUCE_CHANNELS`, `RETRY_ANALYSIS`, `REVIEW_CHANNEL_FINDINGS`, `COLLECT_MORE_DATA`, `REVIEW_CONTRADICTION`, `INSPECT_COMPONENT`, `CONTINUE_MONITORING`, `ESCALATE_TO_ENGINEER`, and the other input actions). Each is shown as a plain-language label plus a short explanation, never as the raw token.
  - **Fail-Closed:** Unverified citations or contradictions automatically collapse to `SuggestedAction.ESCALATE_TO_ENGINEER`; a supported candidate uses the scenario's declared `supported_action`. The engineer note cannot change a verdict.

### Possible Results and What They Mean

Every run ends in one of these states. Three labels are reported separately:
- **outcome** — the route the run took (Python-owned).
- **suggested_next_action** — the typed recommendation (Python-owned). It is always paired with a **label** and a short **explanation** for the user; the raw enum is never shown.
- **analysis_performed / model_called** — explicit booleans, so no UI has to infer the route.

Every action is safe by construction: there is no field a recipe change could
inhabit, so this is a structural guarantee, not a keyword filter.

| Outcome | What happened | analysis / model | Suggested action (label) |
|---|---|---|---|
| `INPUT_UNREADABLE` | The CSV path is unreadable. | no / no | `FIX_INPUT_FILE` — "Fix the file path" |
| `INPUT_MALFORMED` | The file is not parseable as a CSV. | no / no | `FIX_FILE_FORMAT` — "Re-export the file" |
| `NO_DATA_ROWS` | The file has a header but no readings. | no / no | `PROVIDE_MORE_DATA` — "Provide data rows" |
| `NO_MATCHING_TOOL_SCHEMA` | Safe path: no configured tool scenario matches the columns. | no / no | `AUTHOR_TOOL_CONFIG` — "Add a tool schema" |
| `NO_USABLE_NUMERIC_COLUMNS` | Experimental path: no numeric, non-constant column was found. | no / no | `CHECK_COLUMN_FORMAT` — "Check the columns" |
| `EVIDENCE_TOO_LARGE` | The bounded evidence summary exceeds its byte budget (**not** the CSV file size). | no / no (in experimental mode a mapping call happened first) | `REDUCE_CHANNELS` — "Use fewer channels" |
| `MODEL_REJECTED` | Transport, finish reason, response shape, or schema rejected. Direct engine use without a configured candidate; the product path still gates the configured candidate. | yes / yes | `RETRY_ANALYSIS` — "Retry the analysis" |
| `NO_PROPOSALS` | The model returned no usable proposal. Direct engine use without a configured candidate; the product path still gates the configured candidate. | yes / yes | `REVIEW_CHANNEL_FINDINGS` — "Review the channel findings" |
| `ANALYSIS_CONTRADICTED` | The configured candidate was vetoed by a hard contradiction. | yes / yes | `REVIEW_CONTRADICTION` — "Check the contradiction" |
| `ANALYSIS_SUPPORTED` | The configured candidate met `require_all`, with no `forbid_any` and no veto. | yes / yes | the scenario's declared action, or `ESCALATE_TO_ENGINEER` |
| `ANALYSIS_INCONCLUSIVE` | The configured candidate was not fully assessed or missed a required predicate. | yes / yes | `COLLECT_MORE_DATA` — "Collect more data" |
| `EXPERIMENTAL_MAPPING_REJECTED` | The model's mapping was rejected by Python validation. | yes / yes | `FIX_COLUMNS_AND_RETRY` — "Fix the columns and retry" |
| `EXPERIMENTAL_UNVERIFIED_MAPPING` | Experimental mode (see §7) produced an unverified mapping. | yes / yes | `REVIEW_DRAFT_MAPPING` — "Review the draft mapping" |

In the product path, exactly one configuration-authored candidate is gated per
scenario. The model's alternative proposals are narrative only; they do not add
or remove a gated hypothesis. A hard contradiction (`VETOED`) outranks support
and inconclusiveness. `confidence` is `LOW` only when the configured candidate
is `SUPPORTED`; otherwise `INSUFFICIENT`.

### The 2 KB Request Budget
The $\le 2\text{ KB}$ bound applies to the **evidence summary**, not to the fixed system prompt and strict JSON schema that travel with it:
* **Evidence summary** (`build_llm_payload`): the 30 GB stress input becomes **370 bytes**. The request builder caps the evidence portion at 2048 bytes, which admits about **twelve channels** (`results/e2e_payload_scaling.json`).
* **Full HTTP request** (evidence + system prompt + strict JSON schema + note): measured separately under a larger **8 KB** guard. At twelve channels it is ~3.4 KB, most of which is fixed overhead.

---

## 5. System Architecture & File Map

```text
┌─────────────────────────────────┐      ┌──────────────────────────────┐
│  1. Engineer Input (CSV + Text) │      │ 2. Tool Config (YAML Rules)  │
└────────────────┬────────────────┘      └──────────────┬───────────────┘
                 │  (match columns + note to a scenario) │
                 ▼                                       │
┌────────────────────────────────────────┐              │
│  PROFILE SELECTION / ENTRYPOINT        │              │
│  src/triage.py  ·  src/dossier.py      │              │
└────────────────┬───────────────────────┘              │
                 │                                       │
                 ▼                                       ▼
┌───────────────────────────────────────────────────────────────────────┐
│               DETERMINISTIC PYTHON ENGINE (src/core/)                 │
│                                                                       │
│  [DuckDB Streaming MAD Anomaly Scan] (src/core/duckdb_exec.py)        │
│                         │                                             │
│                         ▼                                             │
│  [Evidence Store & ID Hashing]       (src/core/evidence.py)           │
│                         │                                             │
│                         ▼                                             │
│  [Boolean Physical Predicates]       (src/core/sufficiency.py)        │
└──────────────┬────────────────────────────────────────┬───────────────┘
               │                                        │
               ▼ (Bounded Payload <= 2 KB)              │
┌───────────────────────────────────────┐               │
│ PROBABILISTIC LLM (NVIDIA Nemotron)   │               │
│ Candidate Hypotheses citing Evidence  │               │
└──────────────┬────────────────────────┘               │
               │                                        │
               ▼                                        ▼
┌───────────────────────────────────────────────────────────────────────┐
│              DETERMINISTIC SAFETY GATE (src/core/safety_gate.py)      │
│  • Re-resolves cited Evidence IDs                                     │
│  • Enforces hard physical vetoes against contradictions               │
│  • Enforces typed SuggestedAction enum (no autonomous action)          │
└──────────────────────────────────┬────────────────────────────────────┘
                                   │
                                   ▼
┌───────────────────────────────────────────────────────────────────────┐
│           TECHNICIAN GLASS-BOX DASHBOARD (src/ui/app.py, W6)          │
└───────────────────────────────────────────────────────────────────────┘
```

### Component Reference:
* **Triage / Entrypoint:** [`src/triage.py`](file:///home/pablo/code/nvidia/fab_agent/src/triage.py) & [`src/dossier.py`](file:///home/pablo/code/nvidia/fab_agent/src/dossier.py) — select a runnable scenario from CSV columns + note, then run the whole flow.
* **Tool Mappings:** [`config/sensor_relations/`](file:///home/pablo/code/nvidia/fab_agent/config/sensor_relations) & [`src/config_loader.py`](file:///home/pablo/code/nvidia/fab_agent/src/config_loader.py) — maps CSV headers to physical channels and thresholds.
* **Out-of-Core MAD Engine:** [`src/core/duckdb_exec.py`](file:///home/pablo/code/nvidia/fab_agent/src/core/duckdb_exec.py) — streams CSVs in DuckDB and computes robust $z$-scores.
* **Predicate Engine:** [`src/core/evidence.py`](file:///home/pablo/code/nvidia/fab_agent/src/core/evidence.py) & [`src/core/sufficiency.py`](file:///home/pablo/code/nvidia/fab_agent/src/core/sufficiency.py) — stores evidence IDs and derives boolean facts.
* **LLM Hypothesis Generator:** [`src/agents/rca_engine.py`](file:///home/pablo/code/nvidia/fab_agent/src/agents/rca_engine.py) & [`src/agents/model_transport.py`](file:///home/pablo/code/nvidia/fab_agent/src/agents/model_transport.py) — queries NVIDIA Nemotron via Nebius.
* **Safety Gate & Verification:** [`src/core/pipeline.py`](file:///home/pablo/code/nvidia/fab_agent/src/core/pipeline.py), [`src/core/constraints.py`](file:///home/pablo/code/nvidia/fab_agent/src/core/constraints.py), & [`src/core/safety_gate.py`](file:///home/pablo/code/nvidia/fab_agent/src/core/safety_gate.py) — checks physical vetoes and sets the typed suggested action.
* **Evaluation Harnesses:** [`benchmarks/evaluator/synthetic_abstention_runner.py`](file:///home/pablo/code/nvidia/fab_agent/benchmarks/evaluator/synthetic_abstention_runner.py), [`benchmarks/evaluator/real_data_runner.py`](file:///home/pablo/code/nvidia/fab_agent/benchmarks/evaluator/real_data_runner.py), & [`benchmarks/evaluator/dossier_e2e_runner.py`](file:///home/pablo/code/nvidia/fab_agent/benchmarks/evaluator/dossier_e2e_runner.py) — test synthetic, industrial, and engineer-style flows.
* **Technician Dashboard (W6):** [`src/ui/app.py`](file:///home/pablo/code/nvidia/fab_agent/src/ui/app.py) — Streamlit UI over `analyze_csv` (upload + note → result); pure view logic in [`src/ui/presentation.py`](file:///home/pablo/code/nvidia/fab_agent/src/ui/presentation.py) and draft-config validation in [`src/ui/config_promotion.py`](file:///home/pablo/code/nvidia/fab_agent/src/ui/config_promotion.py). Run it with `PYTHONPATH=. streamlit run src/ui/app.py`.

---

## 6. Integrating a New Fab: What You Must Add

FabAgent is built for **low-integration** deployment: to analyze a tool it needs a **sensor schema**. For a new tool you add one YAML file under `config/sensor_relations/` and nothing else. Every field is validated by [`src/config_loader.py`](file:///home/pablo/code/nvidia/fab_agent/src/config_loader.py), which rejects unknown keys.

```yaml
version: 1
name: my_etch_tool
provenance: "Vendor X chamber export schema, rev 2026-10"
signals:                                   # every channel you may scan
  - {name: RF_REFLECT_POWER, unit: "W", robust_z_threshold: 3.5, threshold_source: "standard_robust_mad_multiplier=3.5"}
  - {name: CHAMBER_PRESSURE, unit: "Pa", robust_z_threshold: 3.5, threshold_source: "standard_robust_mad_multiplier=3.5"}
  - {name: COOLANT_FLOW,     unit: "sccm", robust_z_threshold: 3.5, threshold_source: "standard_robust_mad_multiplier=3.5"}
scenarios:                                 # a scope you can diagnose
  rf_arc:
    signals:                               # the channels this scenario scans
      - {name: RF_REFLECT_POWER, unit: "W", robust_z_threshold: 3.5, threshold_source: "standard_robust_mad_multiplier=3.5"}
      - {name: CHAMBER_PRESSURE, unit: "Pa", robust_z_threshold: 3.5, threshold_source: "standard_robust_mad_multiplier=3.5"}
    predicates:
      primary_signals: [RF_REFLECT_POWER]
      corroboration_signals: [CHAMBER_PRESSURE]
    rules:
      equipment_fault:
        require_all: [has_primary_signal_anomaly]
        forbid_any: [has_missing_required_evidence]
        veto_if_any: [has_instrumentation_contradiction]
    candidate:
      claim: RF reflection event
      hypothesis_class: equipment_fault
      cited_signals: [RF_REFLECT_POWER, CHAMBER_PRESSURE]
      root_cause: equipment_fault
      failure_mode: RF reflection event; confirm the specific mode during inspection.
      mechanism: The configured relationship links reflected power and chamber pressure; the physical mechanism is not asserted.
    supported_action: INSPECT_COMPONENT
```

**What the fields mean:**
* `signals` — canonical channel names exactly as they appear in the CSV header (case-insensitive). Set `unit: null` and `robust_z_threshold: null` when you do not have an authoritative value; unknown stays unknown.
* `scenarios.<name>.signals` — the channels scanned for this scope. Keeping this narrow keeps the request within the 2 KB budget.
* `predicates.primary_signals` — channels whose anomaly is required to support the candidate.
* `predicates.corroboration_signals` — channels that, if all nominal, trigger the instrumentation-contradiction veto.
* `rules.<class>.require_all / forbid_any / veto_if_any` — the boolean rule; `hypothesis_class` in the candidate must name a rule here.
* `candidate.cited_signals` — the channels whose evidence records the gate resolves and assesses.
* `candidate.root_cause` / `failure_mode` / `mechanism` — the configuration-authored conclusion and its explanation. These are gated and displayed as the conclusion; the model narrative is separate.
* `supported_action` — the action used only when the candidate is `SUPPORTED`. It must be `INSPECT_COMPONENT`, `CONTINUE_MONITORING`, or `ESCALATE_TO_ENGINEER`; abstentions still fail closed.

**How triage picks this file:** at least **2** declared signals must appear in the CSV columns, and at least **50%** of the scenario's signals must be present. If neither holds, the safe path returns `NO_MATCHING_TOOL_SCHEMA`; `analyze_csv` then falls back to experimental mode.

> No schema yet? When no configured scenario matches, `analyze_csv` automatically
> falls back to the **experimental mode** (§7), which proposes an unverified
> mapping and returns data triage — not a diagnosis — so a fab can decide whether
> authoring a deterministic config is worth it. When a schema does match, the
> deterministic safe path runs and experimental mode is never used.

---

## 7. Experimental Low-Integration Mode (automatic fallback, unverified)

The safe path above requires a sensor schema. When a new fab has no schema yet,
`analyze_csv` automatically falls back to `analyze_experimental(csv, note)` in
[`src/experimental.py`](file:///home/pablo/code/nvidia/fab_agent/src/experimental.py),
a bounded, clearly labelled first look. It runs **only** when no configured
scenario matches; when a schema matches, the deterministic `analyze_dossier`
path runs unchanged and no mapping model is called.

**What it does:**

1. **Deterministic pre-pass.** DuckDB `DESCRIBE` lists column names and inferred
   types; for a capped set of numeric candidates it computes bounded summary
   statistics (row count, null fraction, min/median/max, MAD). No raw telemetry
   value enters the prompt.
2. **Model mapping proposal.** One strict-JSON call sees only names, types, and
   those summaries, and proposes candidate `signals` (`column`, `role_guess`,
   `unit_guess`) and candidate `relationships` (`primary`, `corroborating[]`,
   `rationale`), capped at 12 signals and 5 relationships.
3. **Python validation.** Every proposed column must exist, cast to numeric, be
   non-constant, and be unique; every relationship must cite validated signals;
   the counts must stay within budget. A rejected proposal fails closed with no
   scan.
4. **Deterministic scan.** The same MAD scan runs on the validated signals with
   the documented default `experimental_default_robust_mad_multiplier=3.5`.
   Units stay `null`; every record is marked
   `computed_by="experimental_mapping@v1"` and provenance `unverified_mapping`.
5. **Gated second call.** A standard proposal request runs with a
   configuration-authored candidate (`claim="Experimental unverified mapping
   draft"`, `root_cause=unknown`, class `experimental_unverified`); Python
   resolves citations and owns the verdict exactly as in the safe path. The
   model's proposed claim is shown only as a narrative.
6. **Output.** `outcome=EXPERIMENTAL_UNVERIFIED_MAPPING`,
   `suggested_next_action=REVIEW_DRAFT_MAPPING`,
   `analysis_performed=true`, `model_called=true`, plus a reviewable **draft
   YAML** config. Saving it turns the next run into the deterministic safe path.

**Guardrails:** automatic fallback only (it never runs when a schema matches); a distinct outcome label; no physical root-cause
claim; units never invented; every evidence record is `unverified_mapping`;
prompts send only headers/types/summaries; Python owns validation and
sufficiency; no benchmark IDs in `src/core/`; no hardcoded model IDs. It is data
triage, never RCA and never field validation. Measured offline run:
`benchmarks/evaluator/results/experimental_phm_check_offline.json`.
