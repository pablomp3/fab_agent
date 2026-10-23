# Suggested Next Actions — route reference

The product entry point `analyze_csv(csv, note)` in `src/analyze.py` runs the
deterministic **safe path** first, and, only when no tool schema matches,
automatically falls back to the **experimental** mapping. This table records the
routes the system can take, the typed action Python assigns, and what the user
sees. The user is always the fab engineer.

The action is Python-owned and typed (`SuggestedAction`). Every action has a
plain-language label and a short explanation in `src/action_guidance.py`; the raw
enum is never shown. There is no field a recipe change can inhabit, and
`HOLD_LOT` is deliberately not offered. Anything not listed, or an unexpected
internal error, defaults to `ESCALATE_TO_ENGINEER`.

The gated claim, class, root cause, and citations come from the configured
`candidate`. The model's proposal is displayed as a separate "not gated"
narrative. If the model call fails, the deterministic gate still runs on the
configured candidate; the failure is recorded as a required next check.

For open adoption limits, see [`KNOWN_CHALLENGES.md`](KNOWN_CHALLENGES.md).

The `Demo sample` column names a synthetic file in [`samples/`](samples/). Demo
mode in the dashboard needs no provider key.

| `outcome` | Mode | Machine action | User label | What it means for the user | Demo sample |
|---|---|---|---|---|---|
| `INPUT_UNREADABLE` | safe | `FIX_INPUT_FILE` | Fix the file path | The file could not be opened; check the path and permissions. | Upload a missing path. |
| `INPUT_MALFORMED` | safe | `FIX_FILE_FORMAT` | Re-export the file | The file is not parseable as CSV; re-export as UTF-8 CSV. | Upload a non-CSV file. |
| `NO_DATA_ROWS` | safe | `PROVIDE_MORE_DATA` | Provide data rows | Header only, no readings; nothing to check. | Header-only export. |
| `NO_MATCHING_TOOL_SCHEMA` | safe → experimental | `AUTHOR_TOOL_CONFIG` | Add a tool schema | No configured tool matched. With `analyze_csv` this immediately falls back to experimental mode; the action applies only if the fallback is disabled. | `unknown_tool.csv` (fallback follows). |
| `NO_USABLE_NUMERIC_COLUMNS` | experimental | `CHECK_COLUMN_FORMAT` | Check the columns | No numeric, varying column; no signal can be scored. | All-constant/text export. |
| `EVIDENCE_TOO_LARGE` | both | `REDUCE_CHANNELS` | Use fewer channels | Too many channels for one safe pass; narrow the scope. | More than ~12 varying channels. |
| `MODEL_REJECTED` | both | `RETRY_ANALYSIS` | Retry the analysis | The model call failed or returned nothing usable; retry. In safe mode the configured gate still runs. | Live mode with a failed call. |
| `NO_PROPOSALS` | both | `REVIEW_CHANNEL_FINDINGS` | Review the channel findings | The model proposed nothing; the channel findings are still valid. | Live mode with an empty proposal list. |
| `ANALYSIS_CONTRADICTED` | safe | `REVIEW_CONTRADICTION` | Check the contradiction | Two signals disagree; a sensor may be faulty or mislabeled. | `rf_contradiction.csv` |
| `ANALYSIS_SUPPORTED` | safe | `INSPECT_COMPONENT` / `CONTINUE_MONITORING` / `ESCALATE_TO_ENGINEER` | Inspect the component / Continue monitoring / Escalate to an engineer | A cause is supported; the action is the scenario's declared `supported_action`, defaulting to human review. The flowcool and synthetic configs declare `INSPECT_COMPONENT`; the upstream-process config declares `ESCALATE_TO_ENGINEER`. | `flowcool_supported.csv` |
| `ANALYSIS_INCONCLUSIVE` | safe | `COLLECT_MORE_DATA` | Collect more data | Nothing proven; review what moved and what was missing. The required-next-checks list names the missing configured channels. | `flowcool_inconclusive.csv` |
| `EXPERIMENTAL_MAPPING_REJECTED` | experimental | `FIX_COLUMNS_AND_RETRY` | Fix the columns and retry | The inferred mapping failed Python validation; nothing was scanned. | Invalid/constant mapping. |
| `EXPERIMENTAL_UNVERIFIED_MAPPING` | experimental | `REVIEW_DRAFT_MAPPING` | Review the draft mapping | Channels were inferred from names and statistics; review the draft config before trusting it. | `unknown_tool.csv` |
