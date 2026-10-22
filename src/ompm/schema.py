"""Adapter from the registry's generated JSON Schema to engine-ready extraction schemas.

The registry emits one closed-world schema per @mem/core class (pinned copy in
ontology/mem-core/schemas/). The adapter derives a *model view* of each item class from it:

- pipeline-owned properties are dropped (@id, confidence, consent, validity, portability):
  the pipeline mints IRIs and records provenance, the model never does;
- IRI-valued properties that point at people become plain names, resolved by the pipeline;
- concept-valued properties become enums of concept local names, read from the owl:oneOf
  class each ranges over;
- annotation keywords that constrained decoders reject (format, pattern, x-iri) are removed.

`to_canonical` maps model output back to the registry shape, which is then validated against
the unmodified registry schema, so the two cannot drift apart silently.
"""

from __future__ import annotations

import copy
import functools
import json
from pathlib import Path
from typing import Any

import pyoxigraph as ox

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "ontology/mem-core/schemas"
SCHEMA_PATH = SCHEMA_DIR / "mem-core-0.4.0.schema.json"
ONTOLOGY_PATH = ROOT / "ontology/mem-core/mem.ttl"
MEM = "https://w3id.org/ompm/mem#"

# Item classes the extractor writes, keyed by envelope field.
ITEM_CLASSES = {
    "facts": "Fact",
    "preferences": "Preference",
    "relationships": "Relationship",
    "tasks": "TaskState",
}

# Keywords constrained decoders reject or ignore; they carry no structural meaning.
STRIP = {"format", "pattern", "description", "x-iri", "x-package", "$schema", "title"}

# Set by the pipeline, never by the model.
PIPELINE_OWNED = {"@id", "confidence", "consentScope", "validFrom", "validUntil", "portability",
                  "dueBy"}
# IRI-valued properties the model fills with a person's name.
PERSON_VALUED = {"about", "relatedTo"}
def load_package_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def strip(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: strip(v) for k, v in node.items() if k not in STRIP}
    if isinstance(node, list):
        return [strip(v) for v in node]
    return node


def class_schema(name: str, package: dict[str, Any] | None = None) -> dict[str, Any]:
    package = package or load_package_schema()
    return strip(copy.deepcopy(package["$defs"][name]))


@functools.cache
def concept_enums(ontology: Path = ONTOLOGY_PATH) -> dict[str, list[str]]:
    """Allowed values (local names) of each concept-valued property, read from the ontology:
    the property's range is a class defined by owl:oneOf."""
    store = ox.Store()
    store.load(path=str(ontology), format=ox.RdfFormat.TURTLE)
    q = """PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    SELECT ?p ?m WHERE {
      ?p rdfs:range ?c .
      { ?c owl:equivalentClass/owl:oneOf ?list } UNION { ?c owl:oneOf ?list }
      ?list rdf:rest*/rdf:first ?m .
    } ORDER BY ?p ?m"""
    out: dict[str, list[str]] = {}
    for p, m in store.query(q):
        out.setdefault(p.value.removeprefix(MEM), []).append(m.value.removeprefix(MEM))
    return out


def model_view(cls: str, package: dict[str, Any] | None = None,
               enums: dict[str, list[str]] | None = None) -> dict[str, Any]:
    package = package or load_package_schema()
    enums = enums or concept_enums()
    src = package["$defs"][cls]
    props, required = {}, []
    for name, spec in src["properties"].items():
        if name in PIPELINE_OWNED:
            continue
        spec = strip(copy.deepcopy(spec))
        if name in enums:
            # Local names are easier for small models than IRIs; to_canonical expands them.
            spec = {"type": "string", "enum": enums[name]}
        elif name in PERSON_VALUED:
            spec = {"type": "string"}
        props[name] = spec
        if name in src.get("required", []):
            required.append(name)
    return {"type": "object", "properties": props, "required": required,
            "additionalProperties": False}


def extraction_envelope(package: dict[str, Any] | None = None) -> dict[str, Any]:
    """One object with an array per item class: avoids anyOf, which decoders handle poorly."""
    package = package or load_package_schema()
    enums = concept_enums()
    props = {field: {"type": "array", "items": model_view(cls, package, enums)}
             for field, cls in ITEM_CLASSES.items()}
    return {"type": "object", "properties": props, "required": list(props),
            "additionalProperties": False}


def field_guide(package: dict[str, Any] | None = None) -> str:
    """Field descriptions from the registry schema, for the extraction prompt.

    Constrained decoding enforces shape but the model never sees the schema, so the meaning of
    each field has to be in the prompt.
    """
    package = package or load_package_schema()
    enums = concept_enums()
    lines = []
    for field, cls in ITEM_CLASSES.items():
        d = package["$defs"][cls]
        lines.append(f"{field} ({cls}): {d.get('description', '')}")
        for name, spec in d["properties"].items():
            if name in PIPELINE_OWNED:
                continue
            desc = spec.get("description", name)
            if name in enums:
                desc += f" One of: {', '.join(enums[name])}."
            elif name in PERSON_VALUED:
                desc += " Give the person's name, or 'user' for the user."
            elif name == "supersedes":
                desc += " Use ids of existing memory items shown above."
            req = " (required)" if name in d.get("required", []) else ""
            lines.append(f"  - {name}{req}: {desc}")
    return "\n".join(lines)


def to_canonical(obj: dict[str, Any], cls: str, iri: str, person_iri) -> dict[str, Any]:
    """Model-view item -> registry shape. `person_iri(name)` resolves names to IRIs."""
    out: dict[str, Any] = {"@id": iri}
    for k, v in obj.items():
        if k in PERSON_VALUED:
            out[k] = person_iri(v)
        elif k in concept_enums():
            out[k] = MEM + v
        else:
            out[k] = v
    return out


def gold_canonical(item, persona) -> dict[str, Any]:
    """One gold item in the registry's JSON shape: what a perfect extractor would write."""
    from ompm.gold import base

    b = base(persona)
    obj: dict[str, Any] = {"@id": b + item.id, "about": b + item.about,
                           "statement": item.statement}
    for k, v in item.fields.items():
        if k in PERSON_VALUED:
            obj[k] = b + v
        elif k in concept_enums():
            obj[k] = MEM + v
        else:
            obj[k] = v
    if item.supersedes:
        obj["supersedes"] = [b + item.supersedes]
    return obj


def gold_to_envelope(persona) -> dict[str, list[dict[str, Any]]]:
    """A persona's current (non-erased) gold items in the registry's JSON shape, so extraction
    can be scored item by item. Tests validate it against the pinned registry schema."""
    field_of = {cls: field for field, cls in ITEM_CLASSES.items()}
    env: dict[str, list[dict[str, Any]]] = {f: [] for f in ITEM_CLASSES}
    for it in persona.items:
        if it.erased_in is None:
            env[field_of[it.cls]].append(gold_canonical(it, persona))
    return env
