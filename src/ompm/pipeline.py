"""Migration pipeline: dialogue on engine A, write-in after each session, read-out on engine B.

Conditions (see docs/persona-spec.md):
  a1      ontology store, B queries it through the MCP server's tools
  a2      ontology store, rendered as statements into B's prompt
  b       raw transcript with session headers in B's prompt
  c       A's running free-text summary in B's prompt
  oracle  the gold store rendered into B's prompt (upper bound: no extraction loss)

A's dialogue is generated once per (persona, A, tier) and cached, so every condition sees the
same transcript. During dialogue A sees only the current session; carrying memory across
sessions is exactly what the conditions under test do afterwards.
"""

from __future__ import annotations

import asyncio
import os
import platform
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import jsonschema

logging.getLogger("httpx").setLevel(logging.WARNING)

from ompm.engines import Engine, estimate_tokens
from ompm.evaluate import extraction_quality
from ompm.gold import base, gold_store
from ompm.mcp_server import build_server
from ompm.personas import Persona, Probe
from ompm.schema import (ITEM_CLASSES, extraction_envelope, field_guide, load_package_schema,
                         to_canonical)
from ompm.scoring import score
from ompm.store import MemoryStore

RUNS = Path(__file__).resolve().parents[2] / "runs"
# Bump when write-in prompts change, so cached stores and summaries are regenerated.
WRITEIN_VERSION = "v3"
REPLY_TOKENS = 80  # A's dialogue replies; matches the persona size estimate
SUMMARY_TOKENS = 900
ANSWER_TOKENS = 120
MAX_TOOL_ROUNDS = 4

DIALOGUE_SYSTEM = ("You are a friendly personal assistant chatting with a user. Reply briefly, "
                   "in one or two sentences.")
ANSWER_RULES = ("Answer the user's question briefly, in English, using only what you remember "
                "about them. If you don't have the information, say you don't know.")


# --- Dialogue on A ---------------------------------------------------------------------------

def session_text(idx: int, date: str, turns: list[dict[str, str]]) -> str:
    lines = [f"Session {idx}, {date}"]
    lines += [f"{t['role']}: {t['content']}" for t in turns]
    return "\n".join(lines)


def dialogue(p: Persona, a: Engine, cache: Path | None = None) -> list[dict[str, Any]]:
    """Play the persona's sessions on A. Returns [{idx, date, turns:[{role, content}]}]."""
    cache = cache or RUNS / "dialogue" / p.tier / a.name / f"{p.id}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    out = []
    for s in p.sessions:
        msgs: list[dict[str, str]] = [{"role": "system", "content": DIALOGUE_SYSTEM}]
        for t in s.turns:
            msgs.append({"role": "user", "content": t.text})
            r = a.chat(msgs, max_tokens=REPLY_TOKENS)
            msgs.append({"role": "assistant", "content": r.text.strip()})
        out.append({"idx": s.idx, "date": s.date, "turns": msgs[1:]})
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


def transcript(sessions: list[dict[str, Any]]) -> str:
    return "\n\n".join(session_text(s["idx"], s["date"], s["turns"]) for s in sessions)


# --- Write-in: ontology store (a) ------------------------------------------------------------

@dataclass
class WriteStats:
    sessions: int = 0
    items: int = 0
    invalid: int = 0  # failed registry-schema validation after mapping
    bad_refs: int = 0  # supersedes/erase ids that don't exist
    erased: int = 0
    seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


class People:
    """Resolves names the model writes to person IRIs, minting new ones as people appear."""

    def __init__(self, store: MemoryStore, user_name: str):
        self.store, self.user_name = store, user_name.lower()
        store.person("user", user_name)

    def __call__(self, name: str) -> str:
        key = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "unknown"
        if key in ("user", "the-user", self.user_name, "me", "i"):
            return self.store.base + "user"
        return self.store.person("person-" + key, name.strip())


def write_envelope() -> dict[str, Any]:
    env = extraction_envelope()
    env["properties"]["erase"] = {"type": "array", "items": {"type": "string"}}
    env["required"].append("erase")
    return env


# Rule lists per prompt version. Each change is recorded in docs/tuning-log.md.
_SMALL_TALK = {
    "v2": "- Ignore small talk and passing events that won't matter later (weather, traffic, "
          "lost objects, household annoyances).\n",
    "v3": "- Capture every lasting personal detail: where people live and work, what they do, "
          "own, play, learn or belong to, their relationships, health constraints such as "
          "allergies, likes and dislikes, and plans. Skip only passing remarks about the moment "
          "(weather, traffic, lost objects, household annoyances).\n",
}


def extraction_prompt(user_name: str, guide: str, listing: str, session: str,
                      version: str = "v3") -> str:
    return (
        f"You maintain a long-term memory store about the user, {user_name}. Read the conversation "
        "session below and extract the memory items it adds or changes about the user and the "
        "people they mention.\n"
        "Rules:\n"
        "- Only extract what is said in THIS session. Never repeat an existing memory item.\n"
        + _SMALL_TALK[version] +
        f"- Write statements in the third person with names, e.g. '{user_name} lives in Ghent', "
        "never 'I live in Ghent'. Avoid pronouns; use they/them if one is unavoidable.\n"
        "- A fact about another person is about that person, not about the user.\n"
        "- If an item replaces an existing one (a move, a new job, a changed plan), put the old "
        "id in supersedes.\n"
        "- Put an id in erase ONLY when the user explicitly asks you to forget or delete "
        "something.\n\n"
        f"Fields:\n{guide}\n\nExisting memory items:\n{listing or '(none yet)'}\n\n"
        f"Session:\n{session}\n\nReturn JSON only."
    )


def write_ontology(p: Persona, a: Engine, sessions: list[dict[str, Any]],
                   version: str = WRITEIN_VERSION) -> tuple[MemoryStore, WriteStats]:
    st = MemoryStore(base(p), engine=a.model)
    defs = load_package_schema()["$defs"]
    people = People(st, p.people[0].name)
    env, guide = write_envelope(), field_guide()
    stats = WriteStats()
    for s in sessions:
        st.session(s["idx"], s["date"])
        prompt = extraction_prompt(p.people[0].name, guide, st.listing(),
                                   session_text(s["idx"], s["date"], s["turns"]), version)
        r = a.chat([{"role": "user", "content": prompt}], schema=env)
        stats.sessions += 1
        stats.seconds += r.seconds
        try:
            data = json.loads(r.text)
        except json.JSONDecodeError as e:
            stats.errors.append(f"s{s['idx']}: unparseable output: {e}")
            continue
        existing = {c.iri.removeprefix(st.base) for c in st.current()}
        for field_name, cls in ITEM_CLASSES.items():
            for obj in data.get(field_name, []):
                refs = obj.pop("supersedes", None) or []
                good = [x for x in refs if x in existing]
                stats.bad_refs += len(refs) - len(good)
                if good:
                    obj["supersedes"] = [st.base + x for x in good]
                canon = to_canonical(obj, cls, st.new_iri(), people)
                try:
                    jsonschema.validate(canon, defs[cls])
                except jsonschema.ValidationError as e:
                    stats.invalid += 1
                    stats.errors.append(f"s{s['idx']} {cls}: {e.message[:120]}")
                    continue
                st.add_item(canon, cls, s["idx"], s["date"], validate=False)
                stats.items += 1
        for x in data.get("erase", []):
            if x in existing:
                st.erase(st.base + x, s["date"])
                stats.erased += 1
            else:
                stats.bad_refs += 1
    return st, stats


# --- Write-in: running summary (c) -----------------------------------------------------------

def write_summary(p: Persona, a: Engine, sessions: list[dict[str, Any]]) -> tuple[str, float]:
    summary, seconds = "", 0.0
    for s in sessions:
        prompt = (
            f"You keep running notes about the user, {p.people[0].name}, to remember them in "
            "future conversations. Return the COMPLETE updated notes: keep everything from the "
            "current notes that is still true, even if this session didn't mention it, and add "
            "anything new. Keep session numbers and dates next to each detail. Replace details "
            "that changed. If the user asks you to forget something, remove it. Ignore small "
            "talk. Write in the third person, naming people rather than using pronouns. Return "
            "only the notes.\n\n"
            f"Current notes:\n{summary or '(none yet)'}\n\n"
            f"Session:\n{session_text(s['idx'], s['date'], s['turns'])}"
        )
        r = a.chat([{"role": "user", "content": prompt}], max_tokens=SUMMARY_TOKENS)
        summary, seconds = r.text.strip(), seconds + r.seconds
    return summary, seconds


# --- Read-out on B and probing ------------------------------------------------------------------

@dataclass
class Answer:
    text: str
    seconds: float
    prompt_tokens: int
    tool_calls: int = 0
    tool_errors: int = 0


def mcp_tools(srv) -> list[dict[str, Any]]:
    return [{"type": "function",
             "function": {"name": t.name, "description": t.description or "",
                          "parameters": t.input_schema}}
            for t in asyncio.run(srv.list_tools())]


def ask_with_context(b: Engine, context: str, question: str) -> Answer:
    msgs = [{"role": "system", "content": f"{context}\n\n{ANSWER_RULES}"},
            {"role": "user", "content": question}]
    r = b.chat(msgs, max_tokens=ANSWER_TOKENS)
    return Answer(r.text.strip(), r.seconds, r.prompt_tokens)


def ask_with_tools(b: Engine, srv, tools, question: str, user_name: str = "the user") -> Answer:
    msgs: list[dict[str, Any]] = [
        {"role": "system", "content": f"The user's name is {user_name}. You can look up what "
                                      "you remember about them with the memory tools. "
                                      f"{ANSWER_RULES}"},
        {"role": "user", "content": question}]
    calls = errors = 0
    seconds = 0.0
    prompt_tokens = 0
    for _ in range(MAX_TOOL_ROUNDS):
        r = b.chat(msgs, tools=tools, max_tokens=ANSWER_TOKENS)
        seconds += r.seconds
        prompt_tokens += r.prompt_tokens
        if not r.tool_calls:
            return Answer(r.text.strip(), seconds, prompt_tokens, calls, errors)
        msgs.append({"role": "assistant", "content": r.text, "tool_calls": r.tool_calls})
        for tc in r.tool_calls:
            fn = tc.get("function", {})
            name, args = fn.get("name", ""), fn.get("arguments") or {}
            calls += 1
            try:
                res = asyncio.run(srv.call_tool(name, args))
                out = " | ".join(c.text for c in res.content)
                if res.is_error:
                    errors += 1
            except Exception as e:  # unknown tool or bad arguments: the model sees the error
                errors += 1
                out = f"Error: {e}"
            msgs.append({"role": "tool", "content": out, "tool_name": name})
    # Out of tool rounds: ask for a final answer without tools.
    r = b.chat(msgs, max_tokens=ANSWER_TOKENS)
    return Answer(r.text.strip(), seconds + r.seconds, prompt_tokens + r.prompt_tokens,
                  calls, errors)


def contexts(p: Persona, sessions, store: MemoryStore | None, summary: str | None,
             conditions: list[str]) -> dict[str, str]:
    """Read-out context per condition. Every condition is told the user's name; the store's
    rendering (a2, oracle) states it itself."""
    who = f"The user's name is {p.people[0].name}.\n\n"
    ctx = {}
    if "a2" in conditions and store is not None:
        ctx["a2"] = "What you remember about the user (from your memory store):\n" + store.render()
    if "b" in conditions:
        ctx["b"] = who + "Your previous conversations with the user:\n\n" + transcript(sessions)
    if "c" in conditions and summary is not None:
        ctx["c"] = who + "Your notes about the user:\n" + summary
    if "oracle" in conditions:
        ctx["oracle"] = ("What you remember about the user (from your memory store):\n"
                         + gold_store(p).render())
    return ctx


def probe_all(p: Persona, b: Engine, ctx: dict[str, str], store: MemoryStore | None,
              conditions: list[str], probes: list[Probe] | None = None) -> list[dict[str, Any]]:
    """Ask every probe under every condition. Conditions run one after another so each
    condition's shared prefix stays cached across its probes."""
    probes = probes or p.probes
    rows = []
    srv = tools = None
    if "a1" in conditions and store is not None:
        srv = build_server(store)
        tools = mcp_tools(srv)
    for cond in conditions:
        for q in probes:
            if cond == "a1":
                if srv is None:
                    continue
                ans = ask_with_tools(b, srv, tools, q.question, p.people[0].name)
            elif cond in ctx:
                ans = ask_with_context(b, ctx[cond], q.question)
            else:
                continue
            rows.append({"persona": p.id, "tier": p.tier, "B": b.name, "condition": cond,
                         "probe": q.id, "kind": q.kind, "primary": q.primary,
                         "control": q.control, "question": q.question,
                         "outcome": score(q, ans.text), **asdict(ans)})
    return rows


def run(p: Persona, a: Engine, b: Engine, conditions: list[str], out_dir: Path | None = None,
        ) -> dict[str, Any]:
    """One persona, one A→B pair, the given conditions. Writes artifacts and results."""
    out_dir = out_dir or RUNS / "results" / p.tier / f"{a.name}-to-{b.name}"
    out_dir.mkdir(parents=True, exist_ok=True)
    timing: dict[str, float] = {}
    t0 = time.monotonic()
    sessions = dialogue(p, a)
    timing["dialogue"] = time.monotonic() - t0

    store = summary = None
    write_stats = None
    store_cache = RUNS / "writein" / WRITEIN_VERSION / p.tier / a.name / f"{p.id}.store.ttl"
    stats_cache = store_cache.with_suffix(".stats.json")
    if {"a1", "a2"} & set(conditions):
        t0 = time.monotonic()
        if store_cache.exists():
            store = MemoryStore.load(base(p), store_cache, engine=a.model)
            write_stats = json.loads(stats_cache.read_text())
        else:
            store, ws = write_ontology(p, a, sessions)
            write_stats = asdict(ws)
            store_cache.parent.mkdir(parents=True, exist_ok=True)
            store_cache.write_text(store.dump())
            stats_cache.write_text(json.dumps(write_stats, indent=1))
        timing["write_ontology"] = time.monotonic() - t0
    if "c" in conditions:
        t0 = time.monotonic()
        summary_cache = (RUNS / "writein" / WRITEIN_VERSION / p.tier / a.name
                         / f"{p.id}.summary.txt")
        if summary_cache.exists():
            summary = summary_cache.read_text()
        else:
            summary, _ = write_summary(p, a, sessions)
            summary_cache.parent.mkdir(parents=True, exist_ok=True)
            summary_cache.write_text(summary)
        timing["write_summary"] = time.monotonic() - t0

    ctx = contexts(p, sessions, store, summary, conditions)
    t0 = time.monotonic()
    rows = probe_all(p, b, ctx, store, conditions)
    timing["probe"] = time.monotonic() - t0
    for r in rows:
        r["A"] = a.name
    (out_dir / f"{p.id}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    meta = {"persona": p.id, "A": a.name, "B": b.name, "conditions": conditions,
            "host": os.environ.get("OMPM_HOST", platform.node()),
            "timing_s": timing, "write_stats": write_stats,
            "context_tokens": {k: estimate_tokens([{"content": v}]) for k, v in ctx.items()},
            "extraction": extraction_quality(p, store) if store is not None else None}
    (out_dir / f"{p.id}.meta.json").write_text(json.dumps(meta, indent=1))
    return meta
