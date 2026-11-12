"""Paper numbers for the Claude runs (findings F6, F7). No engine calls.

Usage: uv run python scripts/claude_numbers.py

Reads, for the large tier:
  runs/results-claude/<tier>/<A>-to-<B>/   Claude as reader B on local engines' memory (F6)
  runs/results-strong/<tier>/claude-opus@<A>-to-<B>/, runs/strong/<tier>/extraction.jsonl
                                           Claude Opus as extractor, local readers (F7)
  runs/results/<tier>/                     the local matrix, for paired baselines
and writes paper/numbers-claude.tex. Kept apart from paper/numbers.tex so that the main numbers
can be regenerated independently. PFM is aggregated as in paper_numbers.py.

Token counts here are mean prompt tokens per primary probe as reported by the reader (system
prompt, carried memory and question), so conditions compare on one measure; the main table's
token column counts carried memory only.
"""

import json
from collections import defaultdict
from pathlib import Path

from paper_numbers import boot, fmt, mean, pfm_table

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
TIER = "large"
X = "claude-opus"
READERS = {"opus": "opus", "haiku": "haiku"}


def rows_in(pattern: str) -> list[dict]:
    rows = []
    for f in sorted(RUNS.glob(pattern)):
        rows += [json.loads(x) for x in f.read_text().splitlines() if x]
    return rows


def pfm(rows, cond, out, key):
    pp = pfm_table(rows, cond)
    if not pp:
        return None
    lo, hi = boot(pp)
    out[key], out[f"{key}-ci"] = fmt(mean(pp.values())), f"[{fmt(lo)}, {fmt(hi)}]"
    return pp


def ptok(rows, cond) -> float:
    return mean(r["prompt_tokens"] for r in rows
                if r["condition"] == cond and r["primary"] and r.get("prompt_tokens"))


def opus_precision() -> dict[str, str]:
    """Why Opus's stores have lower precision: classify every current item that matches no
    current gold item. 'superseded': it restates a value the gold has since replaced or erased
    (the newer item was stored without a supersedes link); 'modelling': it matches a current gold
    item only leniently (other class or field); 'outside': no gold item at all, mostly small talk."""
    from ompm.evaluate import _lenient, _matches
    from ompm.gold import gold_store
    from ompm.personas import load
    from ompm.pipeline import WRITEIN_VERSION, base
    from ompm.store import MemoryStore

    n, kinds = 0, {"superseded": 0, "modelling": 0, "outside": 0}
    for f in sorted((RUNS / "writein" / WRITEIN_VERSION / TIER).glob(f"{X}@*/e*.store.ttl")):
        p = load(ROOT / "data/personas" / TIER / f"{f.name.split('.')[0]}.json")
        st = MemoryStore.load(base(p), f, engine=X)
        got, names = st.current(), st.names()
        gs = gold_store(p)
        cur = {c.iri.removeprefix(gs.base) for c in gs.current()}
        gold = [it for it in p.items if it.id in cur]
        old = [it for it in p.items if it.id not in cur]
        for c in got:
            n += 1
            if any(_matches(p, g, c, names) for g in gold):
                continue
            if any(_lenient(p, g, c, names) for g in gold):
                kinds["modelling"] += 1
            elif any(_lenient(p, g, c, names) for g in old):
                kinds["superseded"] += 1
            else:
                kinds["outside"] += 1
    un = sum(kinds.values())
    out = {f"opus-unmatched-share-{TIER}": fmt(un / n)}
    for k, v in kinds.items():
        out[f"opus-unmatched-{k}-{TIER}"] = fmt(v / n)
    return out


def main() -> None:
    out: dict[str, str] = {}
    local = rows_in(f"results/{TIER}/*-to-*/e*.jsonl")

    # F6: Claude as reader B.
    for b in READERS:
        rows = rows_in(f"results-claude/{TIER}/*-to-{b}/e*.jsonl")
        for c in ("oracle", "a2", "a1", "b", "c"):
            pfm(rows, c, out, f"pfm-{c}-{b}-reader-{TIER}")
        a1 = [r for r in rows if r["condition"] == "a1" and r["primary"]]
        if a1:
            out[f"a1-calls-per-probe-{b}-{TIER}"] = fmt(mean(r["tool_calls"] for r in a1), 1)
    cost = defaultdict(float)
    log = RUNS / "results-claude" / TIER / "cost.jsonl"
    for x in (json.loads(x) for x in log.read_text().splitlines() if x):
        cost[x["B"]] += x["cost_usd"]
    for b, usd in cost.items():
        out[f"cost-{b}-reader-{TIER}"] = f"{usd:.0f}"

    # F7: Claude Opus as extractor, local readers.
    strong = rows_in(f"results-strong/{TIER}/{X}@*-to-*/e*.jsonl")
    for c in ("a2x", "a1x"):
        pfm(strong, c, out, f"pfm-{c}-opus-{TIER}")
    by_b = defaultdict(list)
    for r in strong:
        by_b[r["B"]].append(r)
    for b, rs in by_b.items():
        out[f"pfm-a2x-opus-{b}-{TIER}"] = fmt(mean(pfm_table(rs, "a2x").values()))
        out[f"pfm-a2-{b}-reader-{TIER}"] = fmt(mean(pfm_table(
            [r for r in local if r["B"] == b], "a2").values()))
        out[f"pfm-oracle-{b}-reader-{TIER}"] = fmt(mean(pfm_table(
            [r for r in local if r["B"] == b], "oracle").values()))
    t = {"a2x": ptok(strong, "a2x"), "oracle": ptok(local, "oracle"), "b": ptok(local, "b")}
    for c, v in t.items():
        out[f"ptok-{c}-{TIER}"] = f"{v:,.0f}".replace(",", "{,}")
    out[f"ptok-ratio-a2x-b-{TIER}"] = f"{t['b'] / t['a2x']:.0f}"

    ext = [json.loads(x) for x in (RUNS / "strong" / TIER / "extraction.jsonl").read_text()
           .splitlines() if x]
    ext = [e for e in ext if e["extractor"] == "claude-opus-5-5"]
    out[f"n-stores-opus-{TIER}"] = str(len(ext))
    out[f"recall-opus-{TIER}"] = fmt(mean(e["recall"] for e in ext))
    out[f"precision-opus-{TIER}"] = fmt(mean(e["precision"] for e in ext))
    out[f"cost-opus-extraction-{TIER}"] = f"{sum(e['cost_usd'] for e in ext):.2f}"
    out[f"cost-opus-per-store-{TIER}"] = f"{sum(e['cost_usd'] for e in ext) / len(ext):.2f}"

    out.update(opus_precision())
    stale = [r for r in strong if r["condition"] == "a2x" and r["kind"] == "update"
             and r["primary"]]
    out[f"stale-a2x-update-opus-{TIER}"] = fmt(mean(r["outcome"] == "stale" for r in stale))

    lines = ["% Generated by scripts/claude_numbers.py; do not edit."]
    lines += [f"\\resdef{{{k}}}{{{v}}}" for k, v in sorted(out.items())]
    (ROOT / "paper/numbers-claude.tex").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
