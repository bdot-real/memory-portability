"""Extraction quality of a written store against the persona's gold memory.

Each gold item has one key value (a fact's value, a preference's target, the related person's
name, a task's next step). An extracted item "covers" a gold item when that value appears in its
statement or fields (whole word, case- and diacritic-insensitive, as in scoring).
"""

from __future__ import annotations

from ompm.gold import gold_store
from ompm.personas import Item, Persona
from ompm.scoring import mentions
from ompm.store import MemoryStore


def key_value(p: Persona, it: Item) -> str:
    f = it.fields
    if it.cls == "Fact":
        return f["value"]
    if it.cls == "Preference":
        return f["target"]
    if it.cls == "Relationship":
        return next(x.name for x in p.people if x.key == f["relatedTo"])
    return f["nextStep"]


def extraction_quality(p: Persona, store: MemoryStore) -> dict[str, float | int]:
    cur_ids = {c.iri.removeprefix(gold_store(p).base) for c in gold_store(p).current()}
    current_gold = [it for it in p.items if it.id in cur_ids]
    erased = [it for it in p.items if it.erased_in is not None]
    all_values = [key_value(p, it) for it in p.items]
    texts = [c.statement for c in store.current()]
    covered = [it for it in current_gold if any(mentions(t, key_value(p, it)) for t in texts)]
    on_topic = [t for t in texts if any(mentions(t, v) for v in all_values)]
    leaked = [it for it in erased if any(mentions(t, key_value(p, it)) for t in texts)]
    tombstones = len(list(store.query(
        "PREFIX mem: <https://w3id.org/ompm/mem#> SELECT ?t WHERE { ?t a mem:Tombstone }")))
    return {
        "gold_current": len(current_gold),
        "extracted_current": len(texts),
        "recall": round(len(covered) / max(1, len(current_gold)), 3),
        "precision": round(len(on_topic) / max(1, len(texts)), 3),
        "erasures_requested": len(erased),
        "erasures_leaked": len(leaked),
        "tombstones": tombstones,
    }
