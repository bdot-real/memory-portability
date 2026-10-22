# Published artifacts

Cite these exact versions in the paper. Registry versions are immutable and content-hashed.

| Artifact | Version | Integrity | Location |
| --- | --- | --- | --- |
| `@mem/core` ontology | 0.1.0 | `blake3-3ab1cd693efbd2a0ba3558d57ef5404a0dfcb68cd6c9a5c4aea8028d5b837edd` | https://onto.melx.buzz/package/@mem/core |
| `@mem/core` ontology | **0.4.0** (cite this) | `blake3-c9d66511e121da881b8871363308b458babd74805fecf9be541828dc360a4ef0` | https://onto.melx.buzz/package/@mem/core |
| `@mem/core` ontology | 0.3.0 | `blake3-36eead6851adb6f80030983ec65a95d4f728d8d101e18ea4fa7610d0a0990356` | https://onto.melx.buzz/package/@mem/core |
| `@mem/core` ontology | 0.2.0 | `blake3-86f3da673851d9ec515ef4f75a28c00fba0e1fe1c4a6b50d8f1bf748852878f3` | https://onto.melx.buzz/package/@mem/core |
| `@w3c/skos` (dependency) | 1.0.0 | `blake3-f4f7dfa3b4f8205e04a066079c7a81916f1603d21ce13f298e6f72186cd5513f` | https://onto.melx.buzz/package/@w3c/skos |

`@mem/core` 0.4.0 semantic hash: `d29a2a5fd13b0dd0de3d15968b3c727c433f2f2b66890ebfc1cab3d224851d6d` (adds mem:Polarity, mem:RelationType, mem:TaskStatus as owl:oneOf ranges, emitted as JSON Schema `enum`, Pydantic `Literal` and SHACL `sh:in`; polarity 3, relationType 8, taskStatus 4 members; 11 tests passed, 1 skipped; 35/35 coverage). Its generated JSON Schema is pinned at `ontology/mem-core/schemas/mem-core-0.4.0.schema.json` and is the one the pipeline uses.

`@mem/core` 0.3.0 semantic hash: `1dcb0e0eb388b923d8a6b5ef3abb00b5b8344dd98cfbbc0b13a14a207995a657` (functional properties, required fields, mem:task, definitions; 10/10 CQs, 32/32 coverage). Its JSON Schema is pinned at `ontology/mem-core/schemas/mem-core-0.3.0.schema.json` (used for the dev runs).

0.1.0/0.2.0 semantic hash (unchanged between them, tests only): `2ec0073941e779088804bacb76b95a09bea80026d3e3ca5e1269a2b76ea7f136`.
Dependencies (exact): `@w3c/prov-o` 1.0.0, `@foaf/foaf` 0.99.0, `@dcmi/terms` 1.0.0,
`@w3c/time` 1.0.0, `@w3c/skos` 1.0.0.

Pending: w3id.org redirect (https://github.com/perma-id/w3id.org/pull/6930, opened 2026-10-20) for
`https://w3id.org/ompm/mem#` awaiting merge; Zenodo DOI for code and dataset at submission.
