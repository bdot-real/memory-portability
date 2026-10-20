"""Render a persona's gold memory as @mem/core Turtle.

This is the oracle store: what a perfect extractor would have written. It is used to test the
ontology (the competency questions must hold on it) and as an upper-bound condition that
separates extraction loss from read-out loss.
"""

from __future__ import annotations

from ompm.personas import Persona

MEM = "https://w3id.org/ompm/mem#"
PREFIXES = """@prefix mem:  <https://w3id.org/ompm/mem#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix foaf: <http://xmlns.com/foaf/0.1/> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
"""


def base(p: Persona) -> str:
    return f"https://example.org/ompm/{p.id}/"


def lit(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render(p: Persona, engine: str = "gold") -> str:
    b = base(p)
    out = [PREFIXES, f"@prefix ex: <{b}> .", ""]
    for person in p.people:
        kind = "foaf:Person" if person.relation != "pet" else "foaf:Agent"
        out.append(f"ex:{person.key} a {kind} ; foaf:name {lit(person.name)} .")
    out.append(f"ex:engine a mem:Engine ; foaf:name {lit(engine)} .")
    utt_of: dict[str, str] = {}
    for s in p.sessions:
        out.append(f'ex:s{s.idx} a mem:Session ; prov:wasAssociatedWith ex:engine ; '
                   f'prov:startedAtTime "{s.date}T12:00:00Z"^^xsd:dateTime .')
        for t_i, t in enumerate(s.turns):
            if t.kind == "filler":
                continue
            u = f"u{s.idx}_{t_i}"
            out.append(f"ex:{u} a mem:Utterance ; mem:inSession ex:s{s.idx} .")
            if t.kind in ("intro", "reveal", "update"):
                for iid in t.items:
                    utt_of[iid] = u
    date_of = {s.idx: s.date for s in p.sessions}
    for it in p.items:
        if it.erased_in is not None:
            out.append(f"ex:tomb_{it.id} a mem:Tombstone ; mem:erasedItem ex:{it.id} ; "
                       f"prov:wasInvalidatedBy ex:erasure_{it.id} .")
            out.append(f"ex:erasure_{it.id} a mem:Erasure ; "
                       f'prov:atTime "{date_of[it.erased_in]}T12:00:00Z"^^xsd:dateTime .')
            continue
        props = [f"a mem:{it.cls}", f"mem:about ex:{it.about}",
                 f"mem:statement {lit(it.statement)}",
                 f'mem:validFrom "{date_of[it.session]}T12:00:00Z"^^xsd:dateTime',
                 "mem:portability mem:Portable"]
        f = it.fields
        if it.cls == "Fact":
            props += [f"mem:attribute {lit(f['attribute'])}", f"mem:value {lit(f['value'])}"]
        elif it.cls == "Preference":
            props += [f"mem:target {lit(f['target'])}", f"mem:polarity mem:{f['polarity']}"]
            if "context" in f:
                props.append(f"mem:context {lit(f['context'])}")
        elif it.cls == "Relationship":
            props += [f"mem:relatedTo ex:{f['relatedTo']}",
                      f"mem:relationType mem:{f['relationType']}"]
        elif it.cls == "TaskState":
            props += [f"mem:task {lit(f['task'])}", f"mem:taskStatus mem:{f['taskStatus']}",
                      f"mem:nextStep {lit(f['nextStep'])}"]
        if it.supersedes:
            props.append(f"mem:supersedes ex:{it.supersedes}")
        if it.id in utt_of:
            props.append(f"prov:wasDerivedFrom ex:{utt_of[it.id]}")
        out.append(f"ex:{it.id} " + " ;\n    ".join(props) + " .")
    return "\n".join(out) + "\n"
