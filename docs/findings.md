# Findings log

Results worth reporting in the paper, in the order they were found. Each entry names the commit
or script that reproduces it.

## F1. Schema-valid is not the same as meaningful (Oct 20, 2026)

`scripts/schema_decode_test.py`, three local engines, one three-sentence excerpt, Ollama
constrained decoding (`format`) with the registry-generated JSON Schema.

- **@mem/core 0.2.0** (every property an optional array, only `@id` required; schema shown only as
  a grammar): all three engines produced JSON that validated, and all of it was nonsense, e.g. facts
  with no attribute, person IRIs used as item ids, invented classes.
- **@mem/core 0.3.0** (17 functional properties, required fields per item class via
  `owl:cardinality 1`, field descriptions from `skos:definition` in the prompt, SKOS enums
  injected by the adapter, pipeline-owned fields removed from the model view):

| Engine | Time | Items vs. expected (F/P/R/T = 1/1/1/1) | Errors |
| --- | --- | --- | --- |
| qwen2.5:14b | 55 s | 1/1/1/1 | none structural |
| llama3.1:8b | 36 s | 2/1/0/1 | missed relationship; `supersedes` on the wrong item; another person's allergy stored as a fact about the user |
| mistral:7b | 39 s | 1/1/0/1 | missed relationship; another person's allergy recorded as the user's constraint |

**Claim this supports:** the closed-world constraints in the ontology (cardinality, functional
properties, definitions) carry through the registry's generated schema into the engine adapter and
decide whether small models extract usable memory. Valid syntax alone is not enough.

**Also observed:** statements written in the first person ("I live in ..."), and one engine
assigning a gendered pronoun the source never used. The extraction prompt now requires third-person
statements that name people and use they/them where a pronoun is unavoidable.

## F2. Registry limitations found by this work

- The generated JSON Schema and closed shapes include only properties declared in the package.
  Properties reused from declared dependencies (e.g. `prov:wasDerivedFrom`, whose domain
  `prov:Entity` is an ancestor of `mem:MemoryItem`) are missing, so instance data that reuses
  PROV-O fails the local closed-shape check. We kept PROV-O rather than defining `mem:` aliases;
  the issue was raised with the registry maintainers.
- The generator had no enum support. Since fixed upstream (owl:oneOf ranges → `enum`), not yet
  deployed; @mem/core 0.4.0 will adopt it.

## F3. Small-model write-in: losses are extraction, and erasure is over-applied (Oct 21, 2026)

Frozen write-in prompt v3, dev personas p02–p04 (30 current gold items each):

| A | strict recall | lenient recall | precision | tombstones (3 requested) | erasures leaked |
| --- | --- | --- | --- | --- | --- |
| llama3.1:8b | 0.41 | 0.51 | 0.45 | 9–22 (mean 17) | 2 of 9 |
| qwen2.5:14b | 0.51 | 0.63 | 0.49 | 1–3 (mean 2.3) | 1 of 9 |

- Relationships survive best (0.6–1.0); plain Facts are lost most (0.07–0.43).
- The gap between lenient and strict recall (~0.1) is modelling disagreement, e.g. an allergy
  written as a Fact rather than a Preference that Avoids.
- llama tombstones far more items than the user asked to forget, which deletes true memories.
  This is a hazard specific to structured memory: a transcript cannot be over-erased by
  mistake. The paper should report tombstone precision alongside leaks.

## F4. Large tier on Kaggle: llama write-in never terminates (Oct 23, 2026)

Kaggle session v4 (T4, same pinned digests), large tier e01–e03, 12 h session limit:

- Every pair with llama3.1:8b as A failed: its first write-in request hit the 20-minute timeout.
  Kaggle's Ollama starts llama-server with `--context-shift`, so a reply that never closes its
  JSON is never cut off by the context window. mistral and qwen write-ins took 2–7 min per
  persona on the same machine.
- Fix (commit 7112316): local write-in replies are capped at 4096 tokens; a capped reply fails
  to parse and counts as an errored session. Small-tier llama write-ins take ~30 s per session
  on the Mac, far below the cap, so small-tier results are unaffected.
- Throughput: qwen→llama took 2.4–2.6 h per persona on the T4 (vs ~0.5 h on the Mac for small),
  so one 12 h session covers about 1.5 personas. The large tier needs several sessions.
- Early sign (10 runs, not yet analysed): with the full large-tier transcript (b), llama as B
  scores 0.54–0.57 against 0.79–0.89 for qwen, while the oracle store stays at 0.86–1.0.

## F5. Large tier complete: the transcript degrades, the gold store does not (Oct 26, 2026)

Kaggle sessions v5–v6, e01–e12, all 72 runs, no failures (F4's cap fixed the llama pairs).
`paper_numbers.py --tier large`:

| condition | small PFM | large PFM | large tokens |
| --- | --- | --- | --- |
| oracle | 0.95 | 0.93 [0.91, 0.94] | 569 |
| b transcript | 0.84 | 0.58 [0.56, 0.61] | 17,360 |
| a2 rendered store | 0.47 | 0.36 [0.31, 0.40] | 693 |
| c summary | 0.44 | 0.20 [0.14, 0.25] | 727 |
| a1 MCP tools | 0.14 | 0.08 [0.07, 0.10] | -- |

- The oracle store is 31× smaller than the transcript and 0.35 better on the large tier.
- Transcript loss is engine-dependent: as reader B, mistral 0.35 and llama 0.55, qwen 0.86 (e01–e06).
- Small-model write-in recall falls to 0.25–0.36 (from 0.35–0.56); tombstones per request 3.9.
- Gemma 4 31B as strong extractor (small tier, first 18 stores): recall 0.80–0.97, precision
  0.69–0.94, tombstones 2–4 for 3 requests. The store's ceiling is extraction, not the format.

## F6. Claude as reader B: transcript loss is a small-reader effect (Oct 30, 2026)

`scripts/claude_readout.py`, large tier e01–e12, B = `claude-opus-5-5` and `claude-haiku-5-5` on
each local engine's cached dialogue, store and summary (36 runs per B). Thinking off where the
model allows it (Opus: low effort, thinking headroom above the 120-token answer cap). PFM with 95%
bootstrap intervals over personas:

| B | oracle | b transcript | a2 store | c summary | a1 MCP tools |
| --- | --- | --- | --- | --- | --- |
| local (6 pairs) | 0.93 [0.91, 0.94] | 0.58 [0.56, 0.61] | 0.36 [0.31, 0.40] | 0.20 [0.14, 0.25] | 0.08 [0.07, 0.10] |
| Haiku 5.5 | 0.97 [0.95, 0.99] | 0.90 [0.87, 0.93] | 0.41 [0.36, 0.45] | 0.20 [0.15, 0.26] | 0.31 [0.27, 0.36] |
| Opus 5.5 | 0.94 [0.93, 0.95] | 0.95 [0.93, 0.96] | 0.41 [0.37, 0.46] | 0.20 [0.14, 0.25] | 0.35 [0.31, 0.38] |

- A strong reader recovers the 17k-token transcript (0.95) as well as the gold store (0.94). F5's
  transcript degradation belongs to 7–14B readers; for strong readers the gold store's advantage
  is tokens (~31× fewer), not accuracy.
- Stores written by local engines stay near 0.41 even with Opus reading them: the ceiling is
  extraction, as F5 found. Large-tier strong extraction (a2x) is the missing number.
- Both Claude models called a tool for every probe (1.8 calls per probe; locals 0.43, mistral
  none). a1 reaches 85% of a2 on the same stores, so local a1 (0.08) is mostly tool-use weakness.
- Cost: Opus $27.61 (9,270 calls), Haiku $0.77 (8,220 calls); the transcript prefix is cached.
  Hosted Claude models take no temperature or seed; outputs are kept under runs/results-claude/.
