# FabAgent vs frontier LLM

We compared FabAgent with Gemini 3.8 Flash (medium) and GPT-5.6 Luna on the same
four completed cases. The first benchmark gives each model only the prompt and a
bounded evidence summary. The second gives it the raw CSV as well. A third
benchmark compares the full FabAgent workflow — saved tool-model checks plus the
Python gate — with the same Nemotron model used without them. That third table is
a workflow comparison, not a pure gate ablation.

The goal is simple: **safe decisions and the right cause, not confident prose.**
