import glob
import json
from pathlib import Path

import pyoxigraph as ox
import pytest

from ompm.gold import render
from ompm.personas import TIERS, generate

ROOT = Path(__file__).resolve().parents[1]
CQ = {Path(q).stem[:2]: Path(q).read_text()
      for q in glob.glob(str(ROOT / "ontology/mem-core/cq/*.rq"))}
PERSONAS = [generate(f"t{k}", seed=100 + k, tier="small") for k in range(6)]


def transcript(p, upto=None):
    return " ".join(t.text for s in p.sessions if upto is None or s.idx <= upto
                    for t in s.turns)


def store(p):
    s = ox.Store()
    s.load(path=str(ROOT / "ontology/mem-core/mem.ttl"), format=ox.RdfFormat.TURTLE)
    s.load(render(p).encode(), format=ox.RdfFormat.TURTLE)
    return s


def rows(s, cq):
    return len(list(s.query(CQ[cq])))


def test_deterministic():
    a, b = generate("x", seed=7), generate("x", seed=7)
    assert json.dumps(a.to_json()) == json.dumps(b.to_json())


@pytest.mark.parametrize("p", PERSONAS, ids=lambda p: p.id)
class TestPersona:
    def test_values_unique_and_not_substrings(self, p):
        # Session-number answers are scored by integer extraction, not containment.
        vals = sorted({v.lower() for q in p.probes if q.scoring != "session"
                       for v in q.gold[:1] + q.stale[:1] + q.distractors + q.forbidden})
        for i, a in enumerate(vals):
            for b in vals[i + 1:]:
                assert a not in b and b not in a, (a, b)

    def test_gold_is_revealed_before_probe_time(self, p):
        text = transcript(p).lower()
        for q in p.probes:
            # forbidden[0] is the value as said; later entries are alternative leak spellings.
            for v in q.gold[:1] + q.stale[:1] + q.forbidden[:1]:
                if q.scoring in ("contains", "not_revealed", "judge"):
                    assert v.lower() in text, (q.id, v)

    def test_updates_come_later(self, p):
        for it in p.items:
            if it.supersedes:
                assert it.session > p.item(it.supersedes).session

    def test_people_introduced_before_their_facts(self, p):
        intro = {it.fields["relatedTo"]: it.session for it in p.items if it.cls == "Relationship"}
        for it in p.items:
            if it.about != "user":
                assert it.session >= intro[it.about], it.id

    def test_erasures_follow_reveal(self, p):
        erased = [it for it in p.items if it.erased_in]
        assert len(erased) == 3
        for it in erased:
            assert it.erased_in > it.session
            erase_turns = [t for t in p.sessions[it.erased_in - 1].turns if t.kind == "erase"]
            assert any(it.id in t.items for t in erase_turns)

    def test_null_probes_are_never_answered(self, p):
        text = transcript(p).lower()
        for q in p.probes:
            if q.kind == "null":
                assert "dog" not in text or "dog" not in q.question.lower()

    def test_erasure_controls_exist(self, p):
        ids = {q.id for q in p.probes}
        for q in p.probes:
            if q.kind == "erasure":
                assert q.control in ids

    def test_size_tier(self, p):
        assert TIERS["small"] <= p.est_tokens <= TIERS["small"] * 1.05

    def test_competency_questions_hold_on_gold(self, p):
        s = store(p)
        fact_updates = sum(1 for it in p.items if it.supersedes and it.cls == "Fact")
        open_tasks = len({it.fields["task"] for it in p.items if it.cls == "TaskState"})
        relationships = sum(1 for it in p.items if it.cls == "Relationship")
        assert rows(s, "05") == 0  # no erased item keeps content
        assert rows(s, "08") == 3  # every erasure is auditable
        assert rows(s, "02") == fact_updates
        assert rows(s, "04") == open_tasks
        assert rows(s, "07") == relationships
        assert rows(s, "03") == len([it for it in p.items if not it.erased_in])


@pytest.mark.parametrize("p", PERSONAS[:2], ids=lambda p: p.id)
def test_gold_items_validate_against_registry_schema(p):
    """One shape everywhere: every gold item is a valid instance of its class in the pinned
    registry schema, so the gold store, extractor output and store input share one shape."""
    import jsonschema

    from ompm.schema import ITEM_CLASSES, gold_to_envelope, load_package_schema

    defs = load_package_schema()["$defs"]
    for field, cls in ITEM_CLASSES.items():
        for obj in gold_to_envelope(p)[field]:
            jsonschema.validate(obj, defs[cls])


def test_filler_is_varied():
    from ompm.personas import generate
    p = generate("big", seed=1, tier="large")
    filler = [t.text for s in p.sessions for t in s.turns if t.kind == "filler"]
    assert len(set(filler)) / len(filler) > 0.9
