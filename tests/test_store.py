import glob
from pathlib import Path

import pytest

from ompm.gold import base
from ompm.personas import generate
from ompm.schema import gold_canonical
from ompm.store import MemoryStore

ROOT = Path(__file__).resolve().parents[1]
CQ = {Path(q).stem[:2]: Path(q).read_text()
      for q in glob.glob(str(ROOT / "ontology/mem-core/cq/*.rq"))}


def replay(p) -> MemoryStore:
    """Write a persona's gold items into a store session by session, as a perfect extractor."""
    st = MemoryStore(base(p))
    for person in p.people:
        st.person(person.key, person.name)
    for s in p.sessions:
        st.session(s.idx, s.date)
        for t in s.turns:
            for iid in t.items:
                it = p.item(iid)
                if t.kind == "erase":
                    st.erase(base(p) + iid, s.date)
                else:
                    # Validation against the registry schema is enabled once 0.3.0 is pinned.
                    st.add_item(gold_canonical(it, p), it.cls, s.idx, s.date, validate=False)
    return st


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_replayed_store_matches_gold(seed):
    p = generate("r", seed=seed)
    st = replay(p)
    rows = lambda cq: len(list(st.query(CQ[cq])))  # noqa: E731
    assert rows("05") == 0
    assert rows("08") == 3
    assert rows("02") == sum(1 for it in p.items if it.supersedes and it.cls == "Fact")
    assert rows("04") == len({it.fields["task"] for it in p.items if it.cls == "TaskState"})
    current = {c.iri.removeprefix(base(p)) for c in st.current()}
    expected = {it.id for it in p.items if it.erased_in is None and
                not any(o.supersedes == it.id for o in p.items)}
    assert current == expected


def test_render_has_current_values_only():
    p = generate("r", seed=4)
    text = replay(p).render()
    for q in p.probes:
        if q.kind in ("update", "recall", "multihop", "task"):
            assert any(g.lower() in text.lower() for g in q.gold), q.question
        if q.kind == "erasure":
            assert q.forbidden[0].lower() not in text.lower()
        if q.kind == "update":
            assert q.stale[0].lower() not in text.lower()
    assert "[session " in text
