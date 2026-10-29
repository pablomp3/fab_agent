# FabAgent — 3-minute demo script

**Target length:** 2:55  
**Format:** screen recording + voice-over. No face cam required.  
**Live demo:** <https://213-239-184-219.nip.io>

---

## Before recording

1. Redeploy the VM to the latest `main` and restart the container.
2. Open the demo URL in a **fresh incognito window**.
3. Confirm the sidebar shows **NVIDIA Nemotron: Live** and **Tavily research:
   Live**.
4. Run one analysis to warm up the model, then start a new incognito session so
   the recording starts clean.
5. Put `samples/unknown_tool.csv` somewhere easy to reach in the file picker.
6. Set browser zoom to ~110%, hide bookmarks, close notifications, and use a
   clean desktop.
7. Record at 1080p/30fps. Do a 15-second microphone test.
8. Record 2–3 takes and keep the best one.

Do **not** show `.env`, `/etc/fabagent.env`, a terminal, SSH, or raw model output.

---

## 0:00–0:15 — Start here

**Page:** Start here

**Show:** the title, the three layer cards, and the live demo.

**Say:**

> Semiconductor fabs generate hundreds of sensor channels. When a tool alarms, an
> engineer has minutes to decide: real fault, failing sensor, or normal recipe
> behaviour? A wrong action is expensive. FabAgent turns that export into one
> defensible next step. Nemotron reasons, Tavily researches, Python checks, and
> the engineer decides.

---

## 0:15–0:40 — Clean positive control

**Page:** Run troubleshooting  
**Action:** click **Try a one-click demo** → *Synthetic dataset — coolant excursion*

**Say:**

> This is a seeded semiconductor positive control. DuckDB computes the
> statistics. Python builds evidence and checks the saved fault pattern.
> Nemotron writes the explanation, but it cannot change the result.

**Show:** result card, why bullets, and **Next step: Inspect the part**.

**Say:**

> Fault Confirmed, with the evidence and one safe next step.

**Optional (5 seconds):** open **Technical audit**.

> Every finding has an evidence ID. The model sees a bounded summary under 2 KB,
> never the raw telemetry.

Close the audit.

---

## 0:40–1:10 — Real data, honest abstention

**Page:** Run troubleshooting  
**Action:** select **PHM 2018 dataset — ion mill coolant window** → run

**Say:**

> Now real public ion-mill data with a documented coolant fault. The coolant
> check passes. But look at *What else moved*: beam and suppressor channels also
> moved and are unexplained. So the result is **Needs Review**, not Fault
> Confirmed.

**Show:** the **What else moved** card and the coverage explanation.

**Say:**

> A chatbot would confidently name the coolant leak. FabAgent refuses to
> overclaim when the evidence does not cover the tool.

---

## 1:10–1:45 — Sensor conflict + Tavily

**Page:** Run troubleshooting  
**Action:** select **Synthetic dataset — RF sensor conflict** → run

**Say:**

> One RF channel spiked. Its redundant companions stayed flat. That is a
> contradiction, and a contradiction is absolute; it cannot be outvoted.

**Show:** **Sensors Disagree** and the differential table.

> The next step is check the sensor, not change the recipe.

**Action:** open the **Tavily research** tab.

**Say:**

> Tavily adds public troubleshooting leads for the engineer. These are leads,
> never evidence; they cannot change the gate.

**Show:** the references briefly. Do not read them aloud.

---

## 1:45–2:15 — Unknown export + Auto mode

**Page:** Run troubleshooting  
**Action:** switch to **Upload my own CSV** → upload `samples/unknown_tool.csv` → run

**Say:**

> No saved tool model. It does not guess a diagnosis. Nemotron maps the columns,
> proposes a possible cause, and Python keeps it **Unknown Machine** until an
> engineer saves a check.

**Show:** the guessed columns and the unverified proposed cause.

**Action:** open the draft YAML expander and click **Download current YAML**.

**Say:**

> The hosted demo is stateless: download the draft, review it in your repo, and
> deploy or paste it back. Start in Auto, promote to Engineer-defined.

---

## 2:15–2:35 — Exact stack + live usage

**Page:** How it works

**Show:** the flow diagram, **Current server configuration**, and **Live runtime
usage**.

**Say:**

> Nemotron has four bounded jobs. Unknown-machine mapping uses Nemotron 3 Ultra;
> cause finding, challenge, and explanation use Nemotron 3.5 Lightning. Tavily
> runs only when the result is uncertain. The usage table starts at zero and
> counts the actual Nebius Token Factory and Tavily calls, not offline fixtures.

Point to the exact model IDs and the per-model counts.

---

## 2:35–2:55 — Benchmark

**Page:** FabAgent vs frontier LLM

**Show:** Benchmark 1 and Benchmark 3. Point to the **Score** column, then do not
read every number.

**Say:**

> On a fixed known-answer set, FabAgent scores 8/8; Gemini 4/8; GPT-5.6 6/8. On
> the eight-case workflow comparison it is 17/17 versus 6/17. This is a workflow
> comparison, not a pure gate ablation, and not field accuracy.

---

## 2:55–3:00 — Close

**Page:** Project & contact

**Show:** the live URL, repository, and your name.

**Say:**

> FabAgent: evidence-gated troubleshooting for fabs. The model proposes, Python
> checks, the engineer decides. Live demo and repo are here. Thanks.

---

## If you run over 3:00, cut in this order

1. The technical audit beat in the first demo.
2. The benchmark details down to one sentence.
3. The unknown-machine draft-YAML download.
4. The How it works page; keep only the live usage sentence.

---

## Face cam

- **No face cam is fine.** The product is the story.
- If you use one, keep it small in the bottom-right corner, only for the intro
  and close, and never cover the result card.
- Look at the camera for the first and last sentence; look at the screen for the
  rest.

---

## Say this / not that

**Say:** “evidence-gated troubleshooting copilot”, “known-answer cases”,
“workflow comparison”, “the engineer decides”, “low-integration”, “we abstain
when the data is not enough.”

**Do not say:** “autonomous RCA”, “100% accurate”, “beats Exensio/Klarity”,
“air-gapped”, “zero integration”, “the AI never makes things up”, or “physical
AI”.
