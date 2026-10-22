# Paper: Ontology-Mediated Memory Portability Across LLM Engines

ESWC 2027 In-Use track, Springer LNCS. `main.tex` inputs one file per section from `sections/`.

- **Numbers are never typed by hand.** `uv run python scripts/paper_numbers.py --tier small --prefix e`
  reads `runs/results/` and writes `numbers.tex` (`\res{key}` in the text) and `tables/*.tex`.
  Until it has run, every result prints as a bold `??`.
- **Anonymisation:** `\anontrue` in `macros.tex` hides the registry URL, repository, namespace
  owner and byline; set `\anonfalse` for camera-ready.
- **Build:** needs `llncs.cls` and `splncs04.bst` (Springer LNCS kit) and a TeX toolchain
  (e.g. `latexmk -pdf main.tex`), or upload the folder to Overleaf.
- Open items are marked `\todo{...}` and print in red.
