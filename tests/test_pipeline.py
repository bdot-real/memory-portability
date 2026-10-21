"""Pipeline plumbing with a fake engine (no Ollama): a perfect extractor must reproduce the gold
store through the real write path (model view -> registry shape -> validation -> store)."""

import json
import re

from ompm.engines import ChatResult
from ompm.gold import gold_store
from ompm.personas import generate
from ompm.pipeline import (ask_with_tools, build_server, contexts, dialogue, mcp_tools, probe_all,
                           write_ontology, write_summary)


class FakeEngine:
    """Answers each kind of pipeline call the way a perfect engine would."""

    name = model = "fake"

    def __init__(self, persona):
        self.p = persona
        self.names = {x.key: x.name for x in persona.people}

    def chat(self, messages, tools=None, schema=None, max_tokens=None):
        prompt = messages[-1]["content"] if messages[-1]["role"] != "tool" else ""
        if schema is not None:
            text = json.dumps(self.extract(messages[-1]["content"]))
        elif tools is not None:
            return self.tool_turn(messages)
        elif prompt.startswith("You keep running notes"):
            text = "notes"
        else:
            text = "Noted."
        return ChatResult(text, [], 10, 2, 0.0, {})

    def tool_turn(self, messages):
        if messages[-1]["role"] == "tool":
            return ChatResult(messages[-1]["content"], [], 10, 2, 0.0, {})
        call = {"function": {"name": "search_memory",
                             "arguments": {"query": messages[-1]["content"]}}}
        return ChatResult("", [call], 10, 2, 0.0, {})

    def extract(self, prompt):
        idx = int(re.search(r"Session:\nSession (\d+),", prompt).group(1))
        listing = dict((st, iid) for iid, st in
                       re.findall(r"^(x\d+) \(\w+\): (.*)$", prompt, flags=re.M))
        gold_id_to_listing = {it.id: listing.get(it.statement) for it in self.p.items}
        out = {"facts": [], "preferences": [], "relationships": [], "tasks": [], "erase": []}
        field_of = {"Fact": "facts", "Preference": "preferences",
                    "Relationship": "relationships", "TaskState": "tasks"}
        for t in self.p.sessions[idx - 1].turns:
            for iid in t.items:
                it = self.p.item(iid)
                if t.kind == "erase":
                    out["erase"].append(gold_id_to_listing[iid])
                    continue
                obj = {"about": self.names[it.about], "statement": it.statement}
                for k, v in it.fields.items():
                    obj[k] = self.names[v] if k == "relatedTo" else v
                if it.supersedes:
                    obj["supersedes"] = [gold_id_to_listing[it.supersedes]]
                out[field_of[it.cls]].append(obj)
        return out


def test_perfect_extractor_reproduces_gold(tmp_path):
    p = generate("pl", seed=11)
    a = FakeEngine(p)
    sessions = dialogue(p, a, cache=tmp_path / "d.json")
    store, stats = write_ontology(p, a, sessions)
    assert stats.invalid == 0 and stats.bad_refs == 0, stats.errors
    assert stats.erased == 3
    got = sorted(c.statement for c in store.current())
    want = sorted(c.statement for c in gold_store(p).current())
    assert got == want


def test_probe_rows_for_every_condition(tmp_path):
    p = generate("pl", seed=12)
    a = FakeEngine(p)
    sessions = dialogue(p, a, cache=tmp_path / "d.json")
    store, _ = write_ontology(p, a, sessions)
    summary, _ = write_summary(p, a, sessions)
    conds = ["a1", "a2", "b", "c", "oracle"]
    ctx = contexts(p, sessions, store, summary, conds)
    rows = probe_all(p, a, ctx, store, conds)
    assert {r["condition"] for r in rows} == set(conds)
    assert len(rows) == len(conds) * len(p.probes)
    # The fake B answers tool questions with the tool output, so a1 recall should be found.
    a1 = [r for r in rows if r["condition"] == "a1" and r["kind"] == "recall"]
    assert sum(r["outcome"] == "correct" for r in a1) >= len(a1) // 2
    assert all(r["tool_calls"] >= 1 for r in a1)


def test_tool_bridge_reports_bad_calls():
    p = generate("pl", seed=13)
    srv = build_server(gold_store(p))

    class BadTools(FakeEngine):
        def tool_turn(self, messages):
            if messages[-1]["role"] == "tool":
                return ChatResult("I don't know.", [], 1, 1, 0.0, {})
            return ChatResult("", [{"function": {"name": "no_such_tool", "arguments": {}}}],
                              1, 1, 0.0, {})

    ans = ask_with_tools(BadTools(p), srv, mcp_tools(srv), "Where do I live?")
    assert ans.tool_errors == 1 and ans.text == "I don't know."


def test_extraction_quality_of_perfect_extractor(tmp_path):
    from ompm.evaluate import extraction_quality
    p = generate("pl", seed=14)
    a = FakeEngine(p)
    store, _ = write_ontology(p, a, dialogue(p, a, cache=tmp_path / "d.json"))
    q = extraction_quality(p, store)
    assert q["recall"] == 1.0 and q["precision"] == 1.0
    assert q["erasures_leaked"] == 0 and q["tombstones"] == q["erasures_requested"] == 3
