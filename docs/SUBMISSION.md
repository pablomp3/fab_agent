# Submission checklist

Source of truth for the rules: [`../hackaton_description.md`](../hackaton_description.md).
This file is the actionable checklist.

## 1. Track

**Recommended: Best Apps and Agents.**

FabAgent is a usable app/copilot for a real audience (fab engineers), powered by
Nemotron on Nebius Token Factory. The old label “Industrial Copilot & Agentic
Root Cause Analysis (RCA)” is **not** an official track; do not use it on Devpost
or in the UI.

Optional secondary: **Best Use of Tavily** (Tavily is a real, bounded part of the
product, not a bolt-on).

## 2. Official requirements

| Requirement | Status | Where |
|---|---|---|
| Working project on Nebius Token Factory / AI Cloud with at least one NVIDIA open-source model | **Not deployed yet** | Nebius deployment |
| A category (track) | Corrected in `docs/ui/contact.md`; verify the hosted page | `docs/ui/contact.md` |
| Project description (what, why, how) | Draft in `README.md` / `docs/PRODUCT.md` | Update for submission |
| Working demo URL | **Missing** | `docs/ui/contact.md` has a placeholder; add the real Nebius URL |
| 3-minute public YouTube video with audio covering Nebius + Nemotron | **Missing** | Record |
| Public code repository with open-source license visible at top | Repo exists; **working tree not pushed**; license present | `LICENSE` |
| README with setup instructions and run guidance | Exists; needs final rewrite | `README.md` |
| Highlight Nemotron / Token Factory / other Nebius tools | Partly | README, UI, video |
| Feedback on Nebius Token Factory / AI Cloud / NVIDIA tools | **Missing** | Add a short section to README/Devpost |
| Pre-existing project explanation (if applicable) | Check | Add if the repo predates the submission period |
| City Winner (if attended an IRL event) | Check | Select city if applicable |

## 3. Deployment

1. Deploy the Streamlit app to a Nebius VM or a Nebius serverless setup that can
   run a long-lived process. Port 8501 is the app port; expose it through the
   platform URL.
2. Put `NEBIUS_API_KEY` and `TAVILY_API_KEY` in the **server** environment. Never
   in the browser, the repo, a screenshot, or the video.
3. Confirm `config/models.yaml` points at the live Nemotron endpoint. Do not print
   keys or raw completions.
4. Test in an incognito window: upload a sample, run, read the result, open the
   audit, refresh. The app must work without a key in the browser.
5. Test offline mode as a fallback: `DEMO`/offline transport still works if the
   provider is down.
6. Put the real URL in `docs/ui/contact.md` and the README. A judge must be able
   to click it.

## 4. Public repo

Before `git push`:

- [ ] `LICENSE` (Apache 2.0) is at the repo root and visible on the landing page.
- [ ] `README.md` has: what it is, the two modes, quickstart, env vars, the
      Nemotron/Token Factory usage, the benchmark honesty note, and the license.
- [ ] No `.env`, keys, tokens, or raw completions.
- [ ] No `.venv/`, `.archive/`, `benchmarks/evaluator/ground_truths/`, or large
      raw datasets.
- [ ] No private employer code or references.
- [ ] `docs/` is the canonical doc set; old handoffs are not in the product.
- [ ] `git status` is clean; `origin/main` is no longer `fbc2bbd`.
- [ ] The hosted URL and video URL are in the README/contact page.
- [ ] The repo is public and the license is detectable by GitHub.

## 5. 3-minute video

**0:00–0:20 — Problem.** A fab alarm fires; the engineer cannot tell a coolant
fault from a failing sensor. A naive LLM will guess; a wrong recipe change is
expensive.

**0:20–0:50 — Engineer-defined run.** Upload the PHM demo; show the result card,
the plain-language evidence, and the next step. Say: “Python checks; the model
explains.”

**0:50–1:30 — Sensors Disagree.** Upload the RF conflict. Show that one channel
moved and the companions stayed flat. The result is **Sensors Disagree**, not a
fault. Say: “A contradiction is absolute; it cannot be outvoted.”

**1:30–2:10 — Auto mode.** Upload an unknown export. Show the column mapper, the
proposed cause, and the **Unknown Machine** / **Needs Review** result. Add one
fault check in the promotion form, save the tool model, re-run, and show the
deterministic result. Say: “Start in Auto, promote to Engineer-defined.”

**2:10–2:40 — Why it is different.** Show the gate/coverage and the audit tab.
Say: “Nemotron proposes and challenges; Python resolves every citation and owns
the action.” Mention the fair benchmark and the ablation, not a 100% claim.

**2:40–3:00 — Close.** “FabAgent: evidence-gated troubleshooting for fabs. The
model proposes; Python checks; the engineer decides.” Show the URL and repo.

Rules: audio must cover how you used Nebius Token Factory and NVIDIA Nemotron.
Do not show keys. Do not claim field accuracy.

## 6. Feedback section (for Devpost / README)

Add 3–5 concrete bullets:

- What worked in Token Factory (model availability, latency, OpenAI-compatible
  API, Nemotron structured output).
- What was hard (rate limits, model/region naming, JSON reliability, cold
  starts).
- What you would change.
- Which Nebius services you used (Token Factory; optionally Serverless
  Endpoints/Jobs).
- Which NVIDIA models you used (`Nemotron-3.5-Lightning` for mapping/fast calls,
  `Nemotron-3-Ultra` for synthesis/challenge, with exact IDs from
  `config/models.yaml`).

## 7. What to say / not say

**Say:**

- “Evidence-gated troubleshooting copilot.”
- “The model proposes; Python checks; the engineer decides.”
- “Low-integration: bring a CSV and a tool model.”
- “We abstain when the data is not enough.”
- “Our benchmark measures safe decisions on a fixed case set, not field
  accuracy.”

**Do not say:**

- “Autonomous RCA.”
- “Air-gapped.”
- “Zero integration.”
- “100% accurate.”
- “Beats Exensio/Klarity.”
- “The AI never makes things up.”

## 8. Deadline triage

If there are fewer than 72 hours left:

1. Fix the P0 false claims in [`STATUS.md`](STATUS.md) §3.
2. Deploy the current product and put the URL in the UI/README.
3. Push the repo; verify the public page.
4. Record the 3-minute video.
5. Only then add hybrid extras. A working, honest demo beats a half-built
   architecture.
