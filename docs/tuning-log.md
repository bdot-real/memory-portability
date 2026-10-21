# Dev/eval protocol and tuning log

## Protocol

- **Dev set:** the 12 small + 12 large personas in `data/personas/` (seed 2026). All prompt,
  renderer and search changes are developed and judged here, on at least 3 personas, never one.
  p01 was used for the first end-to-end runs and is the most contaminated.
- **Eval set:** generated with a fresh seed once prompts, renderer and search are frozen, and used
  only for the reported matrix. Nothing is tuned on it.
- Every change to a condition's prompt or read-out is logged below, so the tuning effort per
  condition can be reported.

## Log

| Date | Condition | Change | Judged on | Why |
| --- | --- | --- | --- | --- |
| 2026-10-21 | a (write-in) | v1 → v2: only this session, no small talk, third person, erase only on explicit request | p01 (1 persona; superseded by dev runs) | llama v1 copied first-person turns, duplicated existing items, erased 24× for 3 requests |
| 2026-10-21 | c (summary) | must return complete notes, keeping everything still true | p01 | llama overwrote notes with the last session only |
| 2026-10-21 | all | user's name stated in every context; "Answer in English" | — (fairness, applied to all) | qwen answered in Thai; readers confused the user with others |
| 2026-10-21 | a2, oracle, a1 | structured rendering grouped by person with relation to the user; MCP results annotated the same way; crude stemming; user's items preferred on ties | p01 inspection | flat statements lost who is the colleague vs. the manager |
| 2026-10-21 | scoring | abstention patterns widened ("not certain", "haven't provided", ...) | — (all conditions) | refusals were scored as wrong |
| 2026-10-21 | a (write-in) | v2 → v3: name general categories of lasting details to capture | p02–p04, llama + qwen | v2 recall 0.40–0.50; small models skipped real facts as "small talk" |
| 2026-10-21 | a (write-in) | **Freeze v3.** Dev result, strict / lenient recall, precision, tombstones (3 requested): llama v2 p02–p03 0.18 / 0.32, 0.42, 27 · llama v3 p02–p04 0.41 / 0.51, 0.45, 17 · qwen v3 p02–p04 0.51 / 0.63, 0.49, 2.3 | p02–p04 | v2 roughly halves llama recall on the same personas and over-erases (30 tombstones on p02). v2 on llama p04 and on qwen did not finish (Ollama read timeout at 600 s; raised to 1200 s), but the llama gap is decisive. Remaining llama over-erasure is reported as a finding, not tuned further |
