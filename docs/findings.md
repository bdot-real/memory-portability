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
