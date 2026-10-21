"""Extraction quality of a written store against the persona's gold memory, by field.

Gold and extracted items share the registry's shape, so an extracted current item matches a
current gold item when its identifying fields agree:

  Fact          same subject (by name) and the gold value appears in the extracted value
  Preference    same subject, gold target in the extracted target, same polarity
  Relationship  related person has the gold name, same relation type
  TaskState     the gold next step's key phrase appears in the extracted next step or statement

`recall_lenient` only asks for the right person and value in any class or field. The gap
between the two is modelling disagreement (e.g. an allergy stored as a Fact, not as a
Preference with polarity Avoids), as opposed to information that was lost.

Value comparison is whole-word and case/diacritic-insensitive, as in scoring. Recall is
reported per class: this is the extraction-loss table.
"""

from __future__ import annotations

from ompm.gold import gold_store
from ompm.personas import TASKS, Item, Persona
from ompm.schema import ITEM_CLASSES
from ompm.scoring import mentions, norm
from ompm.store import Current, MemoryStore

# Short key phrase of each next step (the second alias in the generator's task table).
STEP_KEYS = {full: short for _, s1, s2 in TASKS for full, short in (s1, s2)}


def _name_of(p: Persona, key: str) -> str:
    return next(x.name for x in p.people if x.key == key)


def _matches(p: Persona, g: Item, c: Current, names: dict[str, str]) -> bool:
    if c.cls != g.cls:
        return False
    f, e = g.fields, c.fields
    subject = norm(names.get(c.about or "", "")) == norm(_name_of(p, g.about))
    if g.cls == "Fact":
        return subject and mentions(e.get("value", ""), f["value"])
    if g.cls == "Preference":
        return (subject and mentions(e.get("target", ""), f["target"])
                and e.get("polarity") == f["polarity"])
    if g.cls == "Relationship":
        other = e.get("relatedTo") if c.about and c.about.endswith("/user") else c.about
        return (norm(names.get(other or "", "")) == norm(_name_of(p, f["relatedTo"]))
                and e.get("relationType") == f["relationType"])
    key = STEP_KEYS.get(f["nextStep"], f["nextStep"])
    return mentions(e.get("nextStep", "") + " " + c.statement, key)


def key_value(p: Persona, it: Item) -> str:
    f = it.fields
    if it.cls == "Fact":
        return f["value"]
    if it.cls == "Preference":
        return f["target"]
    if it.cls == "Relationship":
        return _name_of(p, f["relatedTo"])
    return STEP_KEYS.get(f["nextStep"], f["nextStep"])


def _lenient(p: Persona, g: Item, c: Current, names: dict[str, str]) -> bool:
    """Right person, right value, any class or field: the information survived even if it
    was not modelled the way the ontology intends (e.g. an allergy as a Fact)."""
    text = c.statement + " " + " ".join(c.fields.values())
    if g.cls == "Relationship":
        return mentions(text, key_value(p, g)) and (c.about or "").endswith("/user")
    subject = norm(names.get(c.about or "", "")) == norm(_name_of(p, g.about))
    return subject and mentions(text, key_value(p, g))


def extraction_quality(p: Persona, store: MemoryStore) -> dict:
    gs = gold_store(p)
    cur_ids = {c.iri.removeprefix(gs.base) for c in gs.current()}
    gold = [it for it in p.items if it.id in cur_ids]
    erased = [it for it in p.items if it.erased_in is not None]
    got, names = store.current(), store.names()
    matched_gold = {g.id for g in gold if any(_matches(p, g, c, names) for c in got)}
    lenient_gold = {g.id for g in gold if any(_lenient(p, g, c, names) for c in got)}
    matched_got = [c for c in got if any(_matches(p, g, c, names) for g in gold)]
    leaked = [it for it in erased
              if any(mentions(c.statement + " " + " ".join(c.fields.values()),
                              it.fields.get("value", "")) for c in got)]
    tombstones = len(list(store.query(
        "PREFIX mem: <https://w3id.org/ompm/mem#> SELECT ?t WHERE { ?t a mem:Tombstone }")))
    per_class = {}
    for cls in ITEM_CLASSES.values():
        g = [it for it in gold if it.cls == cls]
        per_class[cls] = round(sum(it.id in matched_gold for it in g) / max(1, len(g)), 3)
    return {
        "gold_current": len(gold),
        "extracted_current": len(got),
        "recall": round(len(matched_gold) / max(1, len(gold)), 3),
        "recall_lenient": round(len(lenient_gold) / max(1, len(gold)), 3),
        "precision": round(len(matched_got) / max(1, len(got)), 3),
        "recall_by_class": per_class,
        "erasures_requested": len(erased),
        "erasures_leaked": len(leaked),
        "tombstones": tombstones,
    }
