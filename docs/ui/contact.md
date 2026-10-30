# Project & contact

> **Nebius × NVIDIA Global AI Hackathon**
>
> Track: **Best Apps and Agents** · City: **Taipei**
>
> Positioning: **a manufacturing copilot with a focus on semiconductors** —
> safe, evidence-gated troubleshooting and RCA for factory machines.

---

## Project and repository

- **Public repository:** [github.com/pablomp3/fab_agent](https://github.com/pablomp3/fab_agent)
- **License:** Apache 2.0
- **Issues and technical feedback:** [github.com/pablomp3/fab_agent/issues](https://github.com/pablomp3/fab_agent/issues)

## Builder

- **Personal site:** [pablomp3.github.io](https://pablomp3.github.io/)
- **LinkedIn:** [linkedin.com/in/pablomp3](https://www.linkedin.com/in/pablomp3/)

---

## Demo and video

- **Hosted demo:** [https://213-239-184-219.nip.io](https://213-239-184-219.nip.io)
- **Demo video:** **to be published before submission.**

The demo runs on a **Nebius AI Cloud** VM with server-side **NVIDIA Nemotron**
(Nebius Token Factory) and **Tavily-powered research** for uncertain results.
Keys are never sent to the browser.

---

## Reproduce locally

```sh
uv sync
cp .env.example .env          # add NEBIUS_API_KEY and TAVILY_API_KEY
.venv/bin/streamlit run src/ui/app.py
```

Without server keys the app runs on the deterministic offline fixture; the
engine, UI, and decision path are the same ones used in the hosted demo.

---

## Benchmark

The benchmark page shows the protocol, cases, and measured results. It compares
safe decisions and correct causes on a fixed case set. No unmeasured numbers are
shown.

For technical walkthroughs, dataset questions, or tool-model contributions, open
an issue or a pull request.
