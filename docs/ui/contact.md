# Contact & project details

> **Nebius × NVIDIA Global AI Hackathon**
>
> Track: **Best Apps and Agents**

---

## Project and repository

- **Public repository:** [github.com/pablomp3/fab_agent](https://github.com/pablomp3/fab_agent)
- **License:** Apache 2.0
- **Issues and technical feedback:** [github.com/pablomp3/fab_agent/issues](https://github.com/pablomp3/fab_agent/issues)

---

## Demo and video

- **Hosted demo:** **TODO — add the Nebius URL here before submission.**
- **Demo video:** **TODO — add the public YouTube URL here before submission.**

The demo runs on Nebius with server-side NVIDIA Nemotron (Nebius Token Factory)
and optional Tavily. Keys are never sent to the browser.

---

## Reproduce locally

```sh
uv sync
cp .env.example .env          # add NEBIUS_API_KEY and TAVILY_API_KEY
.venv/bin/streamlit run src/ui/app.py
```

Use **Demo mode** for a key-free run. The deterministic engine, the UI, and the
offline path are the same ones used in the hosted demo.

---

## Benchmark

The fair comparison protocol, cases, rubric, and artifacts are in
[`../EVALUATION.md`](../EVALUATION.md). The UI performance page shows a summary
only after a run that follows the protocol. No unmeasured numbers are shown.

For technical walkthroughs, dataset questions, or tool-model contributions, open
an issue or a pull request.
