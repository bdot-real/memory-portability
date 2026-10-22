# Paper: Ontology-Mediated Memory Portability Across LLM Engines

ESWC 2027 In-Use track, Springer LNCS. `main.tex` inputs one file per section from `sections/`.

- **Numbers are never typed by hand.** `uv run python scripts/paper_numbers.py --tier small --prefix e`
  reads `runs/results/` and writes `numbers.tex` (`\res{key}` in the text) and `tables/*.tex`.
  Until it has run, every result prints as a bold `??`.
- **Anonymisation:** `\anontrue` in `macros.tex` hides the registry URL, repository, namespace
  owner and byline; set `\anonfalse` for camera-ready.
- **Build:** `tectonic -X compile main.tex` (Tectonic 0.17, `brew install tectonic`; it fetches
  `llncs.cls` and `splncs04.bst` from its TeX Live bundle on first run). Overleaf also works.
- Open items are marked `\todo{...}` and print in red.
