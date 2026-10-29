# What the results mean

FabAgent answers one question:

> *Can I trust this data enough to act, or does it contradict itself?*

| Result | Badge | Plain meaning | Suggested next step |
| :--- | :--- | :--- | :--- |
| **Fault Confirmed** | `[🔴 FAULT CONFIRMED]` | The evidence supports the suspected fault. | Inspect the named part; a human confirms. |
| **Regular Behavior** | `[🟢 REGULAR BEHAVIOR]` | Every checked signal is within its normal range. | Keep monitoring. |
| **Sensors Disagree** | `[🟡 SENSORS DISAGREE]` | One signal moved, but the signals that should agree did not. This usually points to a sensor or calibration problem. | Check the sensor first; do not change the recipe. |
| **Data Incomplete** | `[⚠️ DATA INCOMPLETE]` | A required signal is missing from the export. The fault cannot be judged. | Get the missing data. |
| **Needs Review** | `[🟠 NEEDS REVIEW]` | The data is not enough to confirm or rule out a cause, or an unexplained anomaly is present. | Ask an engineer to review. |
| **Unknown Machine** | `[⚪ UNKNOWN MACHINE]` | The export does not match a saved tool model. The columns were guessed. | Review the guessed columns and download the draft. |

Optional small badge: **AI explanation unavailable** — the model call failed, but
the Python result still ran.

## What is kept separate

- **Python result:** the normal reference, evidence, coverage, fault checks,
  contradictions, and the suggested next step. Deterministic and auditable.
- **AI explanation (Nemotron):** the plain-language summary, the possible causes,
  and the challenge. Helpful context; it cannot change the result.

## What you will not see in the main result

Internal debug labels. They live in the **Audit** tab, next to the raw evidence,
for debugging and for a technical reviewer. The main result always uses one of
the six plain words above.

## How to read the result

1. **Start with the badge.** It tells you whether you can act, should check a
   sensor, need more data, or need a human.
2. **Read the one-sentence why.** It names the signals that moved and the ones
   that stayed normal.
3. **Check the differential table.** It shows the other possible causes and why
   they were ruled out.
4. **Check “What else moved”.** It lists unexplained anomalies. Large unexplained
   anomalies are why the result becomes **Needs Review**.
5. **Follow the suggested next step.** It is a suggestion; a human confirms it.
