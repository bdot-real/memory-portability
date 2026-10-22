"""Strong-extractor experiment: a larger hosted model (default gemini-3.5-flash, free tier) writes the store from a local engine's dialogue.

Same personas, same cached dialogue of source engine A, same write-in prompt (v3) and schema;
only the extracting model changes. Comparing its store with A's own isolates extraction loss.

  # write-in and extraction quality (OpenRouter only; safe while Ollama is busy)
  uv run python scripts/strong_extraction.py write --personas e01-e12 --a llama,mistral,qwen
  # read-out by the local engines (needs Ollama: run after the matrix)
  uv run python scripts/strong_extraction.py probe --personas e01-e12 --a llama,mistral,qwen

Only personas whose dialogue on A is already cached are used, so `write` never calls Ollama.
Stores: runs/writein/v3/<tier>/<x>@<A>/. Quality and cost: runs/strong/<tier>/extraction.jsonl.
Answers: runs/results-strong/<tier>/<x>@<A>-to-<B>/<persona>.jsonl, conditions a1x and a2x.
"""

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

from ompm.engines import ENGINES, FREE, HOSTED
from ompm.evaluate import extraction_quality
from ompm.personas import load
from ompm.pipeline import (RUNS, WRITEIN_VERSION, base, contexts, dialogue, probe_all,
                           write_ontology)
from ompm.store import MemoryStore

DATA = Path(__file__).resolve().parents[1] / "data/personas"
EXTRACTORS = {**FREE, **HOSTED}


class Metered:
    """Wraps an engine to add up OpenRouter's reported cost."""

    def __init__(self, engine):
        self.engine, self.cost, self.calls = engine, 0.0, 0
        self.name, self.model = engine.name, engine.model

    def chat(self, *args, **kw):
        r = self.engine.chat(*args, **kw)
        self.calls += 1
        self.cost += float(r.raw.get("usage", {}).get("cost") or 0)
        return r


def persona_ids(spec: str) -> list[str]:
    if "-" in spec:
        lo, hi = spec.split("-")
        return [f"{lo[0]}{k:02d}" for k in range(int(lo[1:]), int(hi[1:]) + 1)]
    return spec.split(",")


def store_path(tier: str, x: str, a: str, pid: str) -> Path:
    return RUNS / "writein" / WRITEIN_VERSION / tier / f"{x}@{a}" / f"{pid}.store.ttl"


def write(args) -> None:
    x = Metered(EXTRACTORS[args.x])
    log = RUNS / "strong" / args.tier / "extraction.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    for pid in persona_ids(args.personas):
        p = load(DATA / args.tier / f"{pid}.json")
        for a in args.a.split(","):
            if not (RUNS / "dialogue" / args.tier / a / f"{pid}.json").exists():
                continue  # dialogue not cached yet; dialogue() would call Ollama
            out = store_path(args.tier, args.x, a, pid)
            if out.exists():
                continue
            sessions = dialogue(p, ENGINES[a])
            cost0, t0 = x.cost, time.monotonic()
            try:
                st, stats = write_ontology(p, x, sessions)
            except Exception as e:  # e.g. the free tier stayed overloaded; retried next pass
                print(pid, a, "FAIL", str(e)[:200], flush=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(st.dump())
            out.with_suffix(".stats.json").write_text(json.dumps(asdict(stats), indent=1))
            q = extraction_quality(p, st)
            rec = {"persona": pid, "A": a, "extractor": x.model, "cost_usd": round(x.cost - cost0, 4),
                   "seconds": round(time.monotonic() - t0), "invalid": stats.invalid,
                   "bad_refs": stats.bad_refs, **q}
            with log.open("a") as f:
                f.write(json.dumps(rec) + "\n")
            print(pid, a, f"${rec['cost_usd']}", f"{rec['seconds']}s", "recall", q["recall"],
                  "lenient", q["recall_lenient"], "precision", q["precision"],
                  "tombstones", q["tombstones"], flush=True)
    print(f"total {x.calls} calls, ${x.cost:.2f}")


def probe(args) -> None:
    for pid in persona_ids(args.personas):
        p = load(DATA / args.tier / f"{pid}.json")
        for a in args.a.split(","):
            src = store_path(args.tier, args.x, a, pid)
            if not src.exists():
                continue
            store = MemoryStore.load(base(p), src, engine=EXTRACTORS[args.x].model)
            sessions = dialogue(p, ENGINES[a])
            for b in [e for e in ENGINES if e != a]:
                out = (RUNS / "results-strong" / args.tier / f"{args.x}@{a}-to-{b}"
                       / f"{pid}.jsonl")
                if out.exists():
                    continue
                ctx = contexts(p, sessions, store, None, ["a1", "a2"])
                rows = probe_all(p, ENGINES[b], ctx, store, ["a1", "a2"])
                for r in rows:
                    r["A"], r["extractor"] = a, args.x
                    r["condition"] += "x"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
                prim = [r for r in rows if r["primary"]]
                for c in ("a1x", "a2x"):
                    pr = [r for r in prim if r["condition"] == c]
                    print(pid, f"{a}->{b}", c,
                          round(sum(r["outcome"] == "correct" for r in pr) / max(1, len(pr)), 2),
                          flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["write", "probe"])
    ap.add_argument("--tier", default="small")
    ap.add_argument("--personas", default="e01-e12")
    ap.add_argument("--a", default="llama,mistral,qwen")
    ap.add_argument("--x", default="gemini", choices=list(EXTRACTORS))
    args = ap.parse_args()
    (write if args.mode == "write" else probe)(args)


if __name__ == "__main__":
    main()
