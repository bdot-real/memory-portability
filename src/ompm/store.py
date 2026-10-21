"""The canonical memory store: @mem/core triples in an Oxigraph store, one per persona and run.

Items arrive in the registry's JSON shape (see `schema.to_canonical`) and are written as RDF.
The pipeline, not the model, records provenance (session, utterance, engine) and validity.
Erasure deletes an item's content and leaves a tombstone, so CQ5 (no erased content) holds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    about: str | None = None  # person IRI
    fields: dict[str, str] = field(default_factory=dict)  # mem: local name -> value


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
        """Items not superseded and not erased, oldest first, with their fields."""
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
        fields: dict[str, dict[str, str]] = {}
        fq = f"""SELECT ?i ?p ?o WHERE {{ GRAPH <urn:ompm:data> {{ ?i ?p ?o }}
                 FILTER (STRSTARTS(STR(?p), "{MEM}")) }}"""
        for r in self.query(fq):
            fields.setdefault(r["i"].value, {})[r["p"].value.removeprefix(MEM)] = \
                r["o"].value.removeprefix(MEM)
        for c in out:
            c.fields = fields.get(c.iri, {})
            c.about = c.fields.get("about")
        out.sort(key=lambda c: (c.session if c.session is not None else 10**6, c.iri))
        return out

    def names(self) -> dict[str, str]:
        q = f"SELECT ?p ?n WHERE {{ ?p <{FOAF}name> ?n }}"
        return {r["p"].value: r["n"].value for r in self.query(q)}

    def relations(self, cur: list[Current] | None = None) -> dict[str, str]:
        """Person IRI -> how they relate to the user, from current Relationship items."""
        user = self.base + "user"
        rel = {}
        for c in cur if cur is not None else self.current():
            if c.cls != "Relationship" or "relationType" not in c.fields:
                continue
            other = c.fields.get("relatedTo") if c.about == user else (
                c.about if c.fields.get("relatedTo") == user else None)
            if other:
                rel[other] = c.fields["relationType"].lower()
        return rel

    def describe_person(self, iri: str | None, names=None, rel=None) -> str:
        names = names if names is not None else self.names()
        rel = rel if rel is not None else self.relations()
        user = names.get(self.base + "user", "the user")
        if iri == self.base + "user":
            return f"{user} (the user)"
        name = names.get(iri or "", "someone")
        return f"{name}, {user}'s {rel[iri]}" if iri in rel else name

    def render(self, with_sessions: bool = True) -> str:
        """Current items grouped by person, with each person's relation to the user. Used for
        read-out (a2, oracle) so relational structure in the store reaches the reader."""
        cur, names = self.current(), self.names()
        rel = self.relations(cur)
        user_iri = self.base + "user"
        groups: dict[str, list[Current]] = {}
        for c in cur:
            groups.setdefault(c.about or "", []).append(c)
        order = [user_iri] + [k for k in groups if k != user_iri]
        lines = [f"The user is {names.get(user_iri, 'the user')}."]
        for who in order:
            items = groups.get(who, [])
            if not items and who != user_iri:
                continue
            lines.append(f"\nAbout {self.describe_person(who, names, rel)}:")
            for c in items:
                tag = f"[session {c.session}] " if with_sessions and c.session else ""
                lines.append(f"- {tag}{c.statement}")
        known = [k for k in rel if k not in groups]
        if known:
            lines.append("\nOther people " + names.get(user_iri, "the user") + " knows: " +
                         "; ".join(self.describe_person(k, names, rel) for k in known))
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
