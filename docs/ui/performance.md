# FabAgent vs frontier LLM

We compared FabAgent with **Gemini 3.8 Flash (medium)** and **GPT-5.6 Luna** on
cases where the right answer is known in advance (an injected fault in a
simulator, or a published fault label in a public dataset).

- **Benchmark 1** gives each system the same neutral prompt and `< 2 KB`
  evidence summary.
- **Benchmark 2** attaches the raw CSV sensor log as well.
- **Benchmark 3** compares FabAgent’s deterministic path — saved tool model plus
  Python decision, with model calls replaced by a fixed offline fixture — against
  Nemotron 3.5 Lightning zero-shot on the evidence alone. Because the zero-shot
  arm does not receive the saved checks, Benchmark 3 is a **workflow
  comparison**, not a pure gate ablation.

The goal is simple: **safe decisions and the right cause — or an honest "not
enough data" — rather than confident prose.**
