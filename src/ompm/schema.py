"""Adapter from the registry's generated JSON Schema to engine-ready extraction schemas.

The registry emits one closed-world schema per @mem/core class (pinned copy in
ontology/mem-core/schemas/). Engines with constrained decoding accept only a subset of JSON
Schema, so we strip annotation keywords and wrap the item classes in one envelope object.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "ontology/mem-core/schemas/mem-core-0.2.0.schema.json"
)

# Item classes the extractor writes, keyed by envelope field.
ITEM_CLASSES = {
    "facts": "Fact",
    "preferences": "Preference",
    "relationships": "Relationship",
    "tasks": "TaskState",
}

# Keywords constrained decoders reject or ignore; they carry no structural meaning.
STRIP = {"format", "pattern", "description", "x-iri", "x-package", "$schema", "title"}


def load_package_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    return json.loads(path.read_text())


def strip(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: strip(v) for k, v in node.items() if k not in STRIP}
    if isinstance(node, list):
        return [strip(v) for v in node]
    return node


def class_schema(name: str, package: dict[str, Any] | None = None) -> dict[str, Any]:
    package = package or load_package_schema()
    return strip(copy.deepcopy(package["$defs"][name]))


def extraction_envelope(package: dict[str, Any] | None = None) -> dict[str, Any]:
    """One object with an array per item class: avoids anyOf, which decoders handle poorly."""
    package = package or load_package_schema()
    props = {
        field: {"type": "array", "items": class_schema(cls, package)}
        for field, cls in ITEM_CLASSES.items()
    }
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


def gold_to_envelope(persona) -> dict[str, list[dict[str, Any]]]:
    """A persona's current (non-erased) gold items in the extraction envelope's JSON shape.

    This is what a perfect extractor returns, so extraction can be scored item by item, and it
    pins the item shape to the registry schema (tests validate it).
    """
    from ompm.gold import base

    b = base(persona)
    mem = "https://w3id.org/ompm/mem#"
    field_of = {cls: field for field, cls in ITEM_CLASSES.items()}
    env: dict[str, list[dict[str, Any]]] = {f: [] for f in ITEM_CLASSES}
    for it in persona.items:
        if it.erased_in is not None:
            continue
        obj: dict[str, Any] = {"@id": b + it.id, "about": b + it.about,
                               "statement": it.statement}
        for k, v in it.fields.items():
            if k in ("relatedTo",):
                obj[k] = b + v
            elif k in ("polarity", "relationType", "taskStatus"):
                obj[k] = mem + v
            else:
                obj[k] = v
        if it.supersedes:
            obj["supersedes"] = [b + it.supersedes]
        env[field_of[it.cls]].append(obj)
    return env
