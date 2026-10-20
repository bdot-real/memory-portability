# Ontology-mediated memory portability

Prototype and benchmark for the paper *Ontology-Mediated Memory Portability Across LLM Engines*
(see `docs/thesis.md`, `docs/plan.md`).

- `ontology/mem-core/`: the `@mem/core` ontology (Turtle), competency questions (`cq/*.rq`) and an example
- `src/ompm/`: engine clients, store, MCP server, generator, evaluation
- `scripts/`: one-off experiments (e.g. `smoke_timing.py`)

```sh
uv sync
uv run python scripts/smoke_timing.py 16000 llama
```
