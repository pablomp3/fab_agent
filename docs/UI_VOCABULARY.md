# UI vocabulary — the words users see

The main UI uses **six result words** and a small set of action phrases. Internal
enum names are audit-only. This file is the source of truth for copy; if a term
is not here, do not show it to a user.

## 1. Results

| Result | Badge | Plain meaning | Default next step |
|---|---|---|---|
| **Fault Confirmed** | 🔴 | The evidence supports the suspected fault. | Inspect the named part. |
| **Regular Behavior** | 🟢 | Every checked signal is normal. | Keep monitoring. |
| **Sensors Disagree** | 🟡 | One signal moved; the signals that should agree did not. | Check the sensor first. |
| **Data Incomplete** | ⚠️ | A required signal is missing. | Get the missing data. |
| **Needs Review** | 🟠 | The data is not enough to confirm or rule out a cause. | Ask an engineer to review. |
| **Unknown Machine** | ⚪ | The export does not match a saved tool model. | Review the guessed columns. |

Optional small badge, not a main result: **AI explanation unavailable** — the
model call failed, but the Python result still ran.

### Mapping from internal names

| Internal | User-facing |
|---|---|
| `SUPPORTED` | **Fault Confirmed** |
| `INSUFFICIENT` + all checked signals nominal | **Regular Behavior** |
| `INSUFFICIENT` + required signal missing | **Data Incomplete** |
| `INSUFFICIENT` + unexplained anomaly | **Needs Review** |
| `VETOED` / `ANALYSIS_CONTRADICTED` | **Sensors Disagree** |
| `EXPERIMENTAL_UNVERIFIED_MAPPING` / `NO_MATCHING_TOOL_SCHEMA` | **Unknown Machine** |
| `MODEL_REJECTED` / `NO_PROPOSALS` | **Needs Review** + “AI explanation unavailable” |
| `ANALYSIS_SUPPORTED` | **Fault Confirmed** |
| `ANALYSIS_INCONCLUSIVE` | **Regular Behavior** or **Needs Review** (use the evidence) |

Never show these in the main flow: `VETOED`, `SUPPORTED`, `INSUFFICIENT`,
`EXPERIMENTAL`, `UNVERIFIED`, `UNVERIFIED_CLASS`, `hypothesis_class`,
`predicate`, `evidence_id`, `gate`, `candidate`, `narrative`, `triage`,
`scenario`, `rule`, `veto`, `disposition`.

`evidence_id` may appear in the **Audit** tab, next to the matching finding. It
must not be the only explanation of a result.

## 2. Actions

Use these phrases, not the enum names:

| Enum | User phrase |
|---|---|
| `INSPECT_COMPONENT` | **Inspect the part** |
| `CONTINUE_MONITORING` | **Keep monitoring** |
| `ESCALATE_TO_ENGINEER` | **Ask an engineer to review** |
| `COLLECT_MORE_DATA` | **Get the missing data** |
| `REVIEW_CONTRADICTION` | **Check the sensor first** |
| `REVIEW_DRAFT_MAPPING` | **Review the guessed columns** |
| `AUTHOR_TOOL_CONFIG` | **Describe the machine** |
| `RETRY_ANALYSIS` | **Try again** |
| `FIX_INPUT_FILE` / `FIX_FILE_FORMAT` | **Fix the file** |
| `CHECK_COLUMN_FORMAT` | **Check the columns** |
| `PROVIDE_MORE_DATA` | **Provide more data** |
| `REDUCE_CHANNELS` | **Use fewer channels** |
| `REVIEW_CHANNEL_FINDINGS` | **Review the channel findings** |
| `FIX_COLUMNS_AND_RETRY` | **Fix the columns and retry** |

The action is always a suggestion. The human confirms it.

## 3. Model roles

Use plain role names, not “agent” jargon:

- **Column mapper** — guesses what each column means for an unknown export.
- **Cause finder** — proposes possible causes from the evidence.
- **Challenge check** — tries to falsify the leading cause.
- **Explanation** — writes the one-paragraph summary.

In the UI: “Nemotron: column mapper”, “Nemotron: cause finder”, etc. Do not show
model IDs or API details to the user.

## 4. The differential table

Use exactly these columns:

| Possible cause | Evidence for | Evidence against | Result |
|---|---|---|---|

- “Result” uses the six result words.
- “Evidence for” and “Evidence against” use sensor labels, not evidence IDs.
- If a cause is unconfigured, its result is **Needs Review**, and the only
  action is “Review the guessed columns” / “Ask an engineer to review”.
- Never label an unconfigured cause “Fault Confirmed”.

## 5. Copy rules

**Do:**

- Start with what happened, then what to do: “Coolant flow and pressure both
  moved. Inspect the coolant loop.”
- Name the sensor label, not the raw column, when a label exists.
- Say “the checked signals” when coverage is partial.
- Say “the data is not enough” instead of “insufficient evidence”.
- Say “the model could not help” instead of “model rejected”.
- Keep one sentence per idea.

**Do not:**

- Say “100% safe”, “never wrong”, “guaranteed”.
- Say “air-gapped” or “zero integration”.
- Say “AI decided” or “the model confirmed”.
- Say “veto”, “predicate”, “gate”, “candidate”, “hypothesis class”.
- Show a raw z-score without a label and a plain meaning.
- Show a result without a next step.
- Use a green “Regular Behavior” when a declared signal is missing or an
  unexplained anomaly is present; use **Data Incomplete** / **Needs Review**.

## 6. Page-level constraints

Keep the current Streamlit layout, pages, cards, colors, and navigation. The
hybrid changes:

- the result badge and the action card (new words above);
- the “Why” section (plain-language evidence, not enum names);
- a new **Differential** card on the result page (the table above);
- the **Audit** tab (evidence IDs, raw status, model role, payload size);
- the advanced tool-model editor (see [`YAML_GUIDE.md`](YAML_GUIDE.md));
- the benchmark page (honest summary; see [`EVALUATION.md`](EVALUATION.md)).

Do not add a new navigation item unless it replaces an existing one. Do not
redesign the home page. Do not change the demo flow.

## 7. Examples

**Good — confirmed:**

> **Fault Confirmed** · Coolant loop fault
> Coolant flow and coolant pressure both moved outside the normal range. The
> chamber pressure stayed normal, so this is not a pressure-sensor artifact.
> **Next step:** Inspect the coolant loop.

**Good — disagree:**

> **Sensors Disagree** · RF sensor
> The RF sensor moved, but the two channels that should agree with it stayed
> normal. This usually means a sensor or calibration problem, not an equipment
> fault. **Next step:** Check the sensor first.

**Good — incomplete:**

> **Data Incomplete** · Coolant loop fault
> The coolant flow is missing from this export, so the fault cannot be judged.
> **Next step:** Get the missing data.

**Bad:**

> `VETOED`: `has_instrumentation_contradiction` is true. Candidate
> `instrumentation_fault` rejected by gate.

Why it is bad: internal names, no plain meaning, no next step, and it sounds like
the system is arguing with itself.
