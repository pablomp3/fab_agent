# What the result terms mean

| Term | Plain meaning | What to do |
| --- | --- | --- |
| **SUPPORTED** | The configured candidate met every required check. | Follow the typed next action. A human still confirms it. |
| **INSUFFICIENT** | The configured candidate did not meet every required check. | Collect or verify the missing channels. Do not treat it as a fault. |
| **VETOED** | A hard contradiction was found in the configured evidence. | Review the contradiction before acting. |
| **EXPERIMENTAL** | No configured schema matched, so the mapping is unverified. | Review the draft mapping. Do not treat it as a root cause. |

## Two things are shown separately

- **Gated conclusion:** the configured candidate, the evidence citations, the
  verdict, and the typed action. Python owns all of these.
- **Model narrative:** the model's explanation. It is useful context, but it is
  not evidence and it cannot change the verdict.

A missing configured channel forces **INSUFFICIENT** even when the other
citations look convincing.
