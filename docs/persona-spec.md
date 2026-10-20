# Persona and probe specification (draft)

The generator is the source of truth: it produces gold memory items first, then the dialogue that
reveals them. Every probe is derived from gold, so most scoring is deterministic.

## Persona

- 1 user, 3–6 related people/pets, 50–75 gold memory items.
- Item mix: facts 30%, preferences 25%, relationships 15%, task state 15%, updates 10%, erasures 5%.
- Updates: an item is stated in session *k* and changed in session *k + n* (`mem:supersedes`).
- Erasures: the user says "forget that X" in a later session; X must not surface afterwards.
- Distractors: small talk and near-miss mentions (e.g. a friend's allergy vs. the user's).

## Dialogue

- 8–12 sessions per persona; user turns are templated from gold, then paraphrased by a generator
  model **outside the engine families** (or fixed templates, to avoid any engine family bias).
- Assistant turns are produced live by engine A during the run, not pre-written.
- Sized so the full transcript fits in 16k tokens (raw-transcript baseline must not be truncated).

## Probes (per item, scored against gold)

| Probe | Example | Scoring |
| --- | --- | --- |
| Direct recall | "What city do I live in?" | exact / alias match |
| Current value after update | "Where do I live now?" (after a move) | exact; old value counts as wrong |
| Multi-hop | "Which nut should I avoid when cooking for my sister?" | exact |
| Preference application | "Suggest a dinner for my family." | LLM judge (phi4) + human subset |
| Task state | "What's the next step on my passport renewal?" | keyword match |
| Provenance | "When did I first mention my move?" | session index |
| Erasure | Questions that would reveal an erased item | pass if not revealed |

Abstention ("I don't know") is scored separately from wrong answers.
