# Submission checklist

Source of truth for the rules: [`../hackaton_description.md`](../hackaton_description.md).
This file is the actionable checklist.

## 1. Track

**Selected: Best Apps and Agents.**

FabAgent is a usable app/copilot for a real audience (manufacturing and fab
engineers), powered by Nemotron on Nebius Token Factory. Position it as a
**manufacturing copilot with a focus on semiconductors** — deterministic
troubleshooting and RCA for manufacturing and physical-AI operations, not limited
to fabs. The old label “Industrial Copilot & Agentic Root Cause Analysis (RCA)”
is **not** an official track; do not use it on Devpost or in the UI.

Do **not** enter the Physical AI track without at least one minute of physical
hardware/robot footage. The app qualifies for Best Apps and Agents today.

Optional secondary: **Best Use of Tavily** (Tavily is a real, bounded part of the
product, not a bolt-on).

## 2. Official requirements

| Requirement | Status | Where |
|---|---|---|
| Working project on Nebius Token Factory / AI Cloud with at least one NVIDIA open-source model | **Deployed** on a Nebius AI Cloud VM; live Token Factory calls | <https://213-239-184-219.nip.io> |
| A category (track) | **Best Apps and Agents** | `docs/ui/contact.md`, README |
| Project description (what, why, how) | Present in `README.md` / `docs/PRODUCT.md` | Final edit before submission |
| Working demo URL | **Present** | <https://213-239-184-219.nip.io> |
| 3-minute public YouTube video with audio covering Nebius + Nemotron | **Missing** | Record, then add the URL |
| Public code repository with open-source license visible at top | Repository public; license present | `LICENSE` |
| README with setup instructions and run guidance | Present; final rewrite in progress | `README.md` |
| Highlight Nemotron / Token Factory / other Nebius tools | Present in README, UI, and docs | README, UI, video |
| Feedback on Nebius Token Factory / AI Cloud / NVIDIA tools | **Missing** | Add to README/Devpost |
| Pre-existing project explanation (if applicable) | Check | Add if the repo predates the submission period |
| City Winner (if attended an IRL event) | **Taipei** | Select the city in Devpost |

## 3. Deployment

1. Deploy the Streamlit app to a Nebius VM (or a Nebius service that can run a
   long-lived process). Port 8501 is the app port. Expose it through the Nebius
   firewall. **No custom domain is required**: `http://<public-ip>:8501` is an
   acceptable demo URL. For HTTPS without buying a domain, use a Cloudflare
   quick tunnel over the VM. See `DEPLOY.md`.
2. Put `NEBIUS_API_KEY` and `TAVILY_API_KEY` in the **server** environment. Never
   in the browser, the repo, a screenshot, or the video.
3. Confirm `config/models.yaml` points at the live Nemotron endpoint. Do not print
   keys or raw completions.
4. Test in an incognito window: upload a sample, run, read the result, open the
   technical audit, refresh. The app must work without a key in the browser.
5. Test offline mode as a fallback: the offline transport still works if the
   provider is down.
6. Confirm the live URL is in `docs/ui/contact.md` and the README. A judge must
   be able to click it.

## 4. Public repo

Before `git push`:

- [x] `LICENSE` (Apache 2.0) is at the repo root and visible on the landing page.
- [ ] `README.md` has: what it is, the two modes, quickstart, env vars, the
      Nemotron/Token Factory usage, the benchmark honesty note, and the license.
- [x] No `.env`, keys, tokens, or raw completions.
- [x] No `.venv/`, `.archive/`, `benchmarks/evaluator/ground_truths/`, or large
      raw datasets.
- [x] No private employer code or references.
- [x] `docs/` is the canonical doc set; old handoffs are in the local archive.
- [ ] `git status` is clean and `origin/main` has the final commit.
- [ ] The hosted URL is in the README/contact page; the video URL is added after
      recording.
- [ ] The repo is public and the license is detectable by GitHub.

## 5. 3-minute video

**0:00–0:20 — Problem.** A fab alarm fires; the engineer cannot tell a coolant
fault from a failing sensor. A naive LLM will guess; a wrong recipe change is
expensive.

**0:20–0:50 — Clean semiconductor positive control.** Run the synthetic coolant
case. Show the result card, the plain-language evidence, and the next step. Say:
“Python checks; the model explains.”

**0:50–1:20 — Real public data, honest abstention.** Run the PHM 2018 ion-mill
case. The coolant pattern is present, but other declared channels also moved, so
the result is **Needs Review**, not a bare **Fault Confirmed**. Say: “Coverage is
part of the decision. The system refuses to overclaim.”

**1:20–1:55 — Sensors Disagree.** Run the RF conflict. Show that one channel
moved and the companions stayed flat. The result is **Sensors Disagree**, not a
fault. Open the Tavily tab and show real public leads. Say: “A contradiction is
absolute; it cannot be outvoted.”

**1:55–2:25 — Auto mode.** Upload the unknown export. Show the column mapper,
the proposed cause, and the **Unknown Machine** result. Open the draft YAML
expander and download the file. Explain that the reviewer edits it offline and
pastes it back as a tool model on a later run. The hosted UI is stateless: it
never writes a shared config for other users. Say: “Start in Auto, promote to
Engineer-defined.”

**2:25–2:45 — Why it is different.** Show the coverage card and the technical
audit. Say: “Nemotron proposes and challenges; Python resolves every citation
and owns the action.” Mention the fair benchmark and the workflow comparison,
not a 100% claim.

**2:45–3:00 — Close.** “FabAgent: evidence-gated troubleshooting for fabs. The
model proposes; Python checks; the engineer decides.” Show the URL and repo.

Rules: audio must cover how you used Nebius Token Factory and NVIDIA Nemotron.
Do not show keys. Do not claim field accuracy. Keep the video under three
minutes; judges are not required to watch beyond that.

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

1. Fix any remaining false claims listed in [`STATUS.md`](STATUS.md).
2. Deploy the current product and put the URL in the UI/README.
3. Push the repo; verify the public page.
4. Record the 3-minute video.
5. Only then add polish. A working, honest demo beats a half-built extra.
