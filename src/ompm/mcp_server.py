"""MCP server over a MemoryStore: read-out mode (a1).

The same server object is used two ways: in-process by the evaluation loop (list_tools /
call_tool, bridged to Ollama tool calls), and over stdio for any MCP client:

    uv run python -m ompm.mcp_server data/personas/small/p01.gold.ttl

Erased items are absent from the store, so no tool can return them.
"""

from __future__ import annotations

import re
import sys

import pyoxigraph as ox
from mcp.server.mcpserver import MCPServer

from ompm.store import FOAF, MEM, PROV, MemoryStore

STOP = {"my", "the", "a", "an", "of", "is", "what", "which", "who", "do", "i", "me", "on", "in",
        "for", "to", "did", "does", "am", "at", "about", "and", "or", "you", "your"}


def tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP}


def _items(store: MemoryStore, include_superseded: bool = False):
    q = f"""PREFIX mem: <{MEM}> PREFIX prov: <{PROV}> PREFIX foaf: <{FOAF}>
    SELECT ?i ?cls ?st ?sess ?date ?newer (GROUP_CONCAT(DISTINCT ?name; separator=" ") AS ?names)
           (GROUP_CONCAT(DISTINCT ?f; separator=" ") AS ?fields)
    WHERE {{
      GRAPH <urn:ompm:data> {{ ?i a ?cls ; mem:statement ?st . }}
      OPTIONAL {{ ?i prov:wasDerivedFrom/mem:inSession ?sess }}
      OPTIONAL {{ ?i mem:validFrom ?date }}
      OPTIONAL {{ ?newer mem:supersedes ?i }}
      OPTIONAL {{ ?i mem:about|mem:relatedTo ?p . ?p foaf:name ?name }}
      OPTIONAL {{ ?i mem:attribute|mem:target|mem:task|mem:context|mem:nextStep ?f }}
    }} GROUP BY ?i ?cls ?st ?sess ?date ?newer ORDER BY ?date ?i"""
    for r in store.query(q):
        if r["newer"] and not include_superseded:
            continue
        sess = r["sess"].value.removeprefix(store.base + "s") if r["sess"] else "?"
        date = r["date"].value[:10] if r["date"] else "?"
        status = " (replaced later)" if r["newer"] else ""
        yield {
            "text": f"[session {sess}, {date}] {r['st'].value}{status}",
            "match": tokens(" ".join(r[k].value for k in ("st", "names", "fields") if r[k])
                            + " " + r["cls"].value.rsplit("#", 1)[-1]),
        }


def build_server(store: MemoryStore) -> MCPServer:
    srv = MCPServer("ompm-memory", instructions=(
        "Long-term memory about the user, stored against the @mem/core ontology. Use these "
        "tools to look up facts, preferences, relationships and tasks before answering."))

    @srv.tool()
    def search_memory(query: str, limit: int = 8) -> list[str]:
        """Search current memories about the user and people they know by keywords,
        e.g. 'home city', 'sister allergy', 'passport next step'."""
        q = tokens(query)
        scored = sorted(((len(q & it["match"]), it["text"]) for it in _items(store)),
                        key=lambda x: -x[0])
        hits = [t for s, t in scored if s > 0][:limit]
        return hits or ["No matching memories."]

    @srv.tool()
    def list_people() -> list[str]:
        """List the people (and pets) the user has mentioned, with how they relate to the user."""
        q = f"""PREFIX mem: <{MEM}> PREFIX foaf: <{FOAF}>
        SELECT ?name ?rel WHERE {{ GRAPH <urn:ompm:data> {{
          ?r a mem:Relationship ; mem:relatedTo ?p ; mem:relationType ?t . }}
          ?p foaf:name ?name . FILTER NOT EXISTS {{ ?n mem:supersedes ?r }}
          BIND(STRAFTER(STR(?t), "#") AS ?rel) }}"""
        out = [f"{r['name'].value}: {r['rel'].value.lower()}" for r in store.query(q)]
        return out or ["No people recorded."]

    @srv.tool()
    def memories_about(person: str) -> list[str]:
        """All current memories about one person, by name (use 'user' for the user)."""
        want = tokens(person)
        hits = [it["text"] for it in _items(store) if want & it["match"]]
        return hits or [f"No memories about {person}."]

    @srv.tool()
    def memory_history(topic: str) -> list[str]:
        """Memories on a topic including ones that were later replaced, with the session and
        date each was recorded. Use for 'when did I tell you' or 'what changed' questions."""
        q = tokens(topic)
        hits = [it["text"] for it in _items(store, include_superseded=True) if q & it["match"]]
        return hits or ["No matching memories."]

    return srv


def store_from_turtle(path: str, base: str) -> MemoryStore:
    st = MemoryStore(base)
    st.store.load(path=path, format=ox.RdfFormat.TURTLE, to_graph=ox.NamedNode("urn:ompm:data"))
    return st


if __name__ == "__main__":
    ttl = sys.argv[1]
    pid = ttl.rsplit("/", 1)[-1].split(".")[0]
    build_server(store_from_turtle(ttl, f"https://example.org/ompm/{pid}/")).run()
