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
        "for", "to", "did", "does", "am", "at", "about", "and", "or", "you", "your", "now"}


def stem(w: str) -> str:
    """Crude suffix stripping so 'live', 'lives' and 'living' match."""
    for suf in ("ing", "ies", "es", "ed", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def tokens(s: str) -> set[str]:
    return {stem(w) for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP}


def _items(store: MemoryStore, include_superseded: bool = False):
    """Items with an annotation saying whose they are and how that person relates to the user."""
    cur = store.current()
    names, rel = store.names(), store.relations(cur)
    rows = [(c, False) for c in cur]
    if include_superseded:
        current_iris = {c.iri for c in cur}
        rows += [(c, True) for c in _superseded(store) if c.iri not in current_iris]
    for c, replaced in rows:
        who = store.describe_person(c.about, names, rel)
        status = " (replaced later)" if replaced else ""
        date = c.fields.get("validFrom", "")[:10]
        when = f"session {c.session}, {date}" if date else f"session {c.session}"
        text = f"[{when}] {c.statement}{status} (about {who})"
        match = tokens(" ".join([c.statement, who, c.cls] + [
            v for k, v in c.fields.items()
            if k in ("attribute", "target", "task", "context", "nextStep", "value")]))
        yield {"text": text, "match": match, "user": c.about == store.base + "user"}


def _superseded(store: MemoryStore):
    """Items that a newer item replaced, oldest first (for memory_history)."""
    from ompm.store import Current

    q = f"""PREFIX mem: <{MEM}> PREFIX prov: <{PROV}>
    SELECT DISTINCT ?i ?cls ?st ?sess WHERE {{
      GRAPH <urn:ompm:data> {{ ?i a ?cls ; mem:statement ?st . ?newer mem:supersedes ?i }}
      OPTIONAL {{ ?i prov:wasDerivedFrom/mem:inSession ?sess }}
    }}"""
    out = []
    for r in store.query(q):
        sess = r["sess"].value.removeprefix(store.base + "s") if r["sess"] else ""
        fields = {r2["p"].value.removeprefix(MEM): r2["o"].value.removeprefix(MEM)
                  for r2 in store.query(f"SELECT ?p ?o WHERE {{ GRAPH <urn:ompm:data> {{ "
                                        f"<{r['i'].value}> ?p ?o }} }}")}
        out.append(Current(r["i"].value, r["cls"].value.removeprefix(MEM), r["st"].value,
                           int(sess) if sess.isdigit() else None, fields.get("about"), fields))
    return out


def build_server(store: MemoryStore) -> MCPServer:
    srv = MCPServer("ompm-memory", instructions=(
        "Long-term memory about the user, stored against the @mem/core ontology. Use these "
        "tools to look up facts, preferences, relationships and tasks before answering."))

    @srv.tool()
    def search_memory(query: str, limit: int = 8) -> list[str]:
        """Search current memories about the user and people they know by keywords,
        e.g. 'home city', 'sister allergy', 'passport next step'."""
        q = tokens(query)
        scored = [(len(q & it["match"]), it["user"], it["text"]) for it in _items(store)]
        scored.sort(key=lambda x: (-x[0], not x[1]))  # best match first; the user's own on ties
        hits = [t for s, _, t in scored if s > 0][:limit]
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
        """All current memories about one person, by name or by relation to the user
        (e.g. 'Niamh', 'my sister', 'manager'); use 'user' for the user."""
        want = tokens(person) - {"user"} or {"__user__"}
        hits = [it["text"] for it in _items(store)
                if (want == {"__user__"} and it["user"]) or
                (want & tokens(it["text"].rsplit("(about ", 1)[-1]))]
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
