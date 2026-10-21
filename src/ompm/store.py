"""The canonical memory store: @mem/core triples in an Oxigraph store, one per persona and run.

Items arrive in the registry's JSON shape (see `schema.to_canonical`) and are written as RDF.
The pipeline, not the model, records provenance (session, utterance, engine) and validity.
Erasure deletes an item's content and leaves a tombstone, so CQ5 (no erased content) holds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jsonschema
import pyoxigraph as ox

from ompm.schema import ITEM_CLASSES, MEM, ONTOLOGY_PATH, SCHEMA_PATH, load_package_schema

PROV = "http://www.w3.org/ns/prov#"
FOAF = "http://xmlns.com/foaf/0.1/"
RDF_TYPE = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
XSD_DT = ox.NamedNode("http://www.w3.org/2001/XMLSchema#dateTime")
DATA_GRAPH = ox.NamedNode("urn:ompm:data")

# Properties whose JSON value is an IRI rather than a literal.
IRI_VALUED = {"about", "relatedTo", "polarity", "relationType", "taskStatus", "supersedes",
              "consentScope", "portability"}


def n(iri: str) -> ox.NamedNode:
    return ox.NamedNode(iri)


@dataclass
class Current:
    iri: str
    cls: str
    statement: str
    session: int | None


class MemoryStore:
    def __init__(self, base: str, schema_path=None, engine: str = "engine"):
        self.base = base
        self.store = ox.Store()
        self.store.load(path=str(ONTOLOGY_PATH), format=ox.RdfFormat.TURTLE,
                        to_graph=ox.DefaultGraph())
        self.defs = load_package_schema(schema_path or SCHEMA_PATH)["$defs"]
        self.engine = n(base + "engine")
        self._add(self.engine, RDF_TYPE, n(MEM + "Engine"))
        self._add(self.engine, n(FOAF + "name"), ox.Literal(engine))
        self._counter = 0

    # --- writing ---------------------------------------------------------------------------

    def _add(self, s, p, o):
        self.store.add(ox.Quad(s, p, o, DATA_GRAPH))

    def new_iri(self) -> str:
        self._counter += 1
        return f"{self.base}x{self._counter:03d}"

    def person(self, key: str, name: str | None = None) -> str:
        iri = self.base + key
        node = n(iri)
        if not any(self.store.quads_for_pattern(node, RDF_TYPE, None, DATA_GRAPH)):
            self._add(node, RDF_TYPE, n(FOAF + "Person"))
            if name:
                self._add(node, n(FOAF + "name"), ox.Literal(name))
        return iri

    def session(self, idx: int, date: str) -> ox.NamedNode:
        node = n(f"{self.base}s{idx}")
        self._add(node, RDF_TYPE, n(MEM + "Session"))
        self._add(node, n(PROV + "wasAssociatedWith"), self.engine)
        self._add(node, n(PROV + "startedAtTime"), ox.Literal(f"{date}T12:00:00Z", datatype=XSD_DT))
        return node

    def add_item(self, obj: dict[str, Any], cls: str, session: int, date: str,
                 utterance: str | None = None, validate: bool = True) -> str:
        """Write one item in registry JSON shape; returns its IRI."""
        if validate:
            jsonschema.validate(obj, self.defs[cls])
        node = n(obj["@id"])
        self._add(node, RDF_TYPE, n(MEM + cls))
        for k, v in obj.items():
            if k == "@id":
                continue
            for val in v if isinstance(v, list) else [v]:
                o = n(val) if k in IRI_VALUED else ox.Literal(str(val))
                self._add(node, n(MEM + k), o)
        self._add(node, n(MEM + "validFrom"), ox.Literal(f"{date}T12:00:00Z", datatype=XSD_DT))
        self._add(node, n(MEM + "portability"), n(MEM + "Portable"))
        utt = n(utterance or f"{self.base}u{session}")
        self._add(utt, RDF_TYPE, n(MEM + "Utterance"))
        self._add(utt, n(MEM + "inSession"), n(f"{self.base}s{session}"))
        self._add(node, n(PROV + "wasDerivedFrom"), utt)
        return obj["@id"]

    def erase(self, iri: str, date: str) -> None:
        """Remove every triple about the item and leave an auditable tombstone."""
        node = n(iri)
        for q in list(self.store.quads_for_pattern(node, None, None, DATA_GRAPH)):
            self.store.remove(q)
        for q in list(self.store.quads_for_pattern(None, None, node, DATA_GRAPH)):
            if q.predicate.value != MEM + "supersedes":
                self.store.remove(q)
        tomb, act = n(iri + "_tomb"), n(iri + "_erasure")
        self._add(tomb, RDF_TYPE, n(MEM + "Tombstone"))
        self._add(tomb, n(MEM + "erasedItem"), node)
        self._add(tomb, n(PROV + "wasInvalidatedBy"), act)
        self._add(act, RDF_TYPE, n(MEM + "Erasure"))
        self._add(act, n(PROV + "atTime"), ox.Literal(f"{date}T12:00:00Z", datatype=XSD_DT))

    # --- reading ---------------------------------------------------------------------------

    def query(self, sparql: str):
        return self.store.query(sparql, use_default_graph_as_union=True)

    def current(self) -> list[Current]:
        """Items not superseded and not erased, oldest first."""
        q = f"""PREFIX mem: <{MEM}> PREFIX prov: <{PROV}>
        SELECT ?i ?cls ?st ?sess WHERE {{
          GRAPH <urn:ompm:data> {{ ?i a ?cls ; mem:statement ?st . }}
          FILTER (?cls IN ({", ".join(f"mem:{c}" for c in ITEM_CLASSES.values())}))
          FILTER NOT EXISTS {{ ?newer mem:supersedes ?i }}
          OPTIONAL {{ ?i prov:wasDerivedFrom/mem:inSession ?sess }}
        }} ORDER BY ?sess ?i"""
        out = []
        for r in self.query(q):
            sess = r["sess"].value.removeprefix(self.base + "s") if r["sess"] else None
            out.append(Current(r["i"].value, r["cls"].value.removeprefix(MEM), r["st"].value,
                               int(sess) if sess and sess.isdigit() else None))
        return out

    def render(self, with_sessions: bool = True) -> str:
        """Current items as text, for read-out mode (a2): one statement per line."""
        lines = []
        for c in self.current():
            tag = f"[session {c.session}] " if with_sessions and c.session else ""
            lines.append(f"- {tag}{c.statement}")
        return "\n".join(lines)

    def listing(self) -> str:
        """Current items with short ids, shown to the extractor so it can supersede or erase."""
        return "\n".join(f"{c.iri.removeprefix(self.base)} ({c.cls}): {c.statement}"
                         for c in self.current())

    def dump(self) -> str:
        """The data graph only, as Turtle. The ontology is reloaded from mem.ttl, never from a
        dump (reloading it would duplicate its blank-node lists)."""
        return self.store.dump(format=ox.RdfFormat.TURTLE, from_graph=DATA_GRAPH).decode()

    @classmethod
    def load(cls, base: str, path, engine: str = "engine") -> "MemoryStore":
        st = cls(base, engine=engine)
        st.store.load(path=str(path), format=ox.RdfFormat.TURTLE, to_graph=DATA_GRAPH)
        st._counter = sum(1 for c in st.current())  # informational; loaded stores are read-only
        return st

    def stats(self) -> dict[str, int]:
        cur = self.current()
        return {c: sum(1 for x in cur if x.cls == c) for c in ITEM_CLASSES.values()}
