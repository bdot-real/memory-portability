# Persona, run protocol and probe specification

Implemented in `src/ompm/personas.py` (generator), `src/ompm/gold.py` (gold store) and
`src/ompm/scoring.py` (scorer). Generate with `scripts/generate_personas.py`; checksums are in
`data/personas/<tier>/manifest.json`.

## Persona (gold first)

Every persona is derived from a seed. Gold items are fixed before any dialogue exists, and user
turns are templated from them, so no LLM or engine family shapes the input.

- **People:** the user, 4 related people (from sister, brother, partner, colleague, friend,
  manager) and a pet. People are introduced before any fact about them is stated.
- **Items (~38 per persona):**
  - user facts: home city, employer, occupation, language, instrument, car, club, street
  - updates (oversampled): home city, employer, language, favourite food, and about 2 of 3
    tasks change once
  - facts about other people: occupation (all 4), allergy (all 4), home city (2 of them; these
    are distractors for "where do I live")
  - preferences: a liked dish (updated), a disliked food, a seat preference with context, a
    scheduling constraint
  - 3 tasks with next steps
  - 3 erasures: therapist, salary, ex-partner
- **Values** are uncommon (small cities, invented employers, rare dishes) so models can't guess
  them from priors. Within a persona they are unique and no value is a substring of another;
  a test enforces this.
- **Synthetic names only.** None of the names refers to a real person.

## Size tiers

| Tier | Est. tokens | Purpose |
| --- | --- | --- |
| small | ~8k | Fits every engine comfortably; raw transcript should do well here |
| large | ~24k | Under 85% of a 32k window on every engine; where cost and degradation should favour structure |

Both tiers carry the same items and probes. Only the filler (small talk with no memory content)
differs. The estimate includes about 60 tokens per assistant turn, which is the run-time
`num_predict` cap.

## Run protocol (fixed for all conditions)

1. **Dialogue on A:** sessions are played in order. User turns come from the dataset; A
   replies live (temperature 0, reply cap). Each session starts with a header like
   `Session 3, 2026-06-26`.
2. **Write-in after every session, with the same cadence for every condition:**
   - (a) ontology: A extracts items from the session into the store, constrained by the
     `@mem/core` JSON Schema. A sees the current store, so it can link `supersedes` and act on
     erasures. The pipeline, not the model, records session provenance.
   - (b) raw transcript: nothing to write; the full transcript with session date headers is
     carried over.
   - (c) summary: A updates a running free-text summary after each session and is told to keep
     dates and session numbers.
   - (oracle) the gold store (`gold.py`): an upper bound that separates extraction loss from
     read-out loss.
3. **Read-out on B:** (a1) B queries the store through MCP tools; (a2) the store is rendered as
   statements into B's prompt; (b) the transcript goes into B's prompt; (c) the summary goes
   into B's prompt.
4. **Probing:** each probe is asked in a fresh turn with the same carried-over memory. The shared
   prefix is cached across probes (see `scripts/smoke_timing.py`).

## Probes and scoring

| Kind | Example | Scoring | Primary |
| --- | --- | --- | --- |
| recall | "What car do I drive?" | contains gold | ✓ |
| update | "Which city do I live in?" | contains new value; old value alone = stale | ✓ |
| multihop | "If I cook for my colleague, which ingredient must I leave out?" | contains gold; other people's values = distracted | ✓ |
| task | "What's my next step on renewing my passport?" | contains next-step key phrase | ✓ |
| erasure | "What's my therapist's name?" | erased value must not appear | ✓ |
| provenance | "In which session did I tell you about my new employer?" | session number | |
| null | "What is my dog's name?" (never stated) | must abstain; else false memory | |
| preference | "Suggest a dinner menu for me and my sister." | LLM judge with rubric + human subset | |

Scoring rules are documented in `scoring.py`. In short: matching is whole-word and
case/diacritic-insensitive; a superseded value mentioned *alongside* the current one counts as
correct; gold plus a distractor counts as `hedged` (wrong).

**PFM** uses one primary probe per item (about 30 per persona). Provenance, null and preference
probes are reported separately.

**Erasure control:** each erasure probe names a matched recall probe on a non-erased user fact.
Erasure is reported only together with that control (e.g. "leak rate among cases where the
control was recalled"), because a model that remembers nothing passes erasure trivially.

**Statistics:** probes within a persona are correlated, so confidence intervals are bootstrapped
over personas.

## Related dataset

LongMemEval (Wu et al., ICLR 2025; MIT-licensed code) benchmarks long-term memory of a single
chat assistant over haystack sessions. We cite it as related work rather than extending it: it
has no notion of migrating memory between engines, erasure, or an ontology-backed store, and its
answers are free text without the competitor strings our deterministic scoring needs.

## Threats to validity

- The dialogue is templated, so the phrasing is repetitive. This keeps it free of engine-family
  bias at the cost of realism. A paraphrase pass with a model outside the engine families is a
  possible extension.
- Values are uncommon by design, which may understate how much engines can fill in from priors
  in real use.
