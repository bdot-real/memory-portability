# Ontology-mediated memory portability

Prototype and benchmark for the paper *Ontology-Mediated Memory Portability Across LLM Engines*
(sources in `paper/`; results log in `docs/findings.md`).

- `ontology/mem-core/`: the `@mem/core` ontology (Turtle), competency questions (`cq/*.rq`) and an example
- `src/ompm/`: engine clients, store, MCP server, generator, evaluation
- `scripts/`: one-off experiments (e.g. `smoke_timing.py`)

```sh
uv sync
uv run python scripts/smoke_timing.py 16000 llama
```

## Licence

Code, benchmark generator and data: Apache-2.0 (`LICENSE`). The `@mem/core` ontology
(`ontology/mem-core/`) is CC BY 4.0, as declared in `mem.ttl`.

Run outputs (`runs/`: dialogues, stores, answers, judge verdicts, human labels) are not in git.
They are archived on Zenodo, CC BY 4.0:
[doi:10.5281/zenodo.24168038](https://doi.org/10.5281/zenodo.24168038) (latest version). Unzip
at the repository root; `scripts/paper_numbers.py` and `scripts/claude_numbers.py` then
regenerate the paper's numbers without calling any engine.
