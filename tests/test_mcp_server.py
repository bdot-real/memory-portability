import asyncio

from ompm.mcp_server import build_server
from ompm.personas import generate
from tests.test_store import replay


def call(srv, name, args):
    r = asyncio.run(srv.call_tool(name, args))
    return " ".join(c.text for c in r.content)


def test_tools_answer_probes_and_hide_erased():
    p = generate("m", seed=5)
    srv = build_server(replay(p))
    names = {t.name for t in asyncio.run(srv.list_tools())}
    assert names == {"search_memory", "list_people", "memories_about", "memory_history"}
    city = next(q for q in p.probes if q.question == "Which city do I live in?")
    assert city.gold[0] in call(srv, "search_memory", {"query": "home city live"})
    people = call(srv, "list_people", {})
    for person in p.people[1:]:
        assert person.name in people
    history = call(srv, "memory_history", {"topic": "home city"})
    assert city.stale[0] in history and "replaced later" in history
    for q in p.probes:
        if q.kind == "erasure":
            assert q.forbidden[0] not in call(srv, "memories_about", {"person": "user"})
