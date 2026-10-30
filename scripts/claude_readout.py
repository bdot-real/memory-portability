"""Claude as reader B: a local engine's dialogue, store and summary, read out by a Claude model.

Same personas, cached dialogue and write-in of source engine A, same conditions and probes as the
local matrix; only B changes. Tests whether a strong reader closes the a1 (MCP tools) and b
(transcript) gaps that 7-14B readers leave. A is always a local engine, so every pair stays
cross-family.

  uv run python scripts/claude_readout.py --personas e01 --tier large --a qwen --b haiku,sonnet,opus

Only personas whose dialogue and write-in on A are cached are run, so this never calls Ollama.
Answers: runs/results-claude/<tier>/<A>-to-<B>/<persona>.jsonl (+ .meta.json).
Cost, tokens and served model per run: runs/results-claude/<tier>/cost.jsonl.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from ompm.engines import CLAUDE, ENGINES
from ompm.personas import load
from ompm.pipeline import RUNS, WRITEIN_VERSION, run

DATA = Path(__file__).resolve().parents[1] / "data/personas"
OUT = RUNS / "results-claude"


class BudgetExceeded(RuntimeError):
    pass


class Metered:
    """Wraps a Claude engine to add up cost, cache use and the model versions served, and stops
    the run once the spend passes `budget`."""

    def __init__(self, engine, budget: float):
        self.engine, self.budget = engine, budget
        self.name, self.model = engine.name, engine.model
        self.cost, self.calls, self.served = 0.0, 0, set()
        self.tokens = Counter()
        self.stops = Counter()

    def chat(self, *args, **kw):
        if self.cost > self.budget:
            raise BudgetExceeded(f"{self.name}: ${self.cost:.2f} spent, budget ${self.budget}")
        r = self.engine.chat(*args, **kw)
        u = r.raw["usage"]
        self.calls += 1
        self.cost += u["cost"]
        self.served.add(r.raw["model"])
        self.stops[r.raw["stop_reason"]] += 1
        for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens",
                  "cache_read_input_tokens"):
            self.tokens[k] += u.get(k) or 0
        return r


def persona_ids(spec: str) -> list[str]:
    if "-" in spec:
        lo, hi = spec.split("-")
        return [f"{lo[0]}{k:02d}" for k in range(int(lo[1:]), int(hi[1:]) + 1)]
    return spec.split(",")


def cached(tier: str, a: str, pid: str) -> bool:
    w = RUNS / "writein" / WRITEIN_VERSION / tier / a
    return all(p.exists() for p in (RUNS / "dialogue" / tier / a / f"{pid}.json",
                                    w / f"{pid}.store.ttl", w / f"{pid}.summary.txt"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--personas", default="e01")
    ap.add_argument("--tier", default="large")
    ap.add_argument("--a", default="qwen")
    ap.add_argument("--b", default="haiku,sonnet,opus")
    ap.add_argument("--conditions", default="a1,a2,b,c,oracle")
    ap.add_argument("--budget", type=float, default=5.0, help="USD cap per B model")
    args = ap.parse_args()

    conditions = args.conditions.split(",")
    log = OUT / args.tier / "cost.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    for b_name in args.b.split(","):
        b = Metered(CLAUDE[b_name], args.budget)
        for a_name in args.a.split(","):
            for pid in persona_ids(args.personas):
                out = OUT / args.tier / f"{a_name}-to-{b_name}"
                if (out / f"{pid}.jsonl").exists():
                    print(f"skip {pid} {a_name}->{b_name}: done")
                    continue
                if not cached(args.tier, a_name, pid):
                    print(f"skip {pid} {a_name}->{b_name}: A's dialogue or write-in not cached")
                    continue
                before = (b.cost, b.calls, Counter(b.tokens), Counter(b.stops))
                p = load(DATA / args.tier / f"{pid}.json")
                run(p, ENGINES[a_name], b, conditions, out_dir=out)
                rows = [json.loads(x) for x in (out / f"{pid}.jsonl").read_text().splitlines()]
                pfm = {}
                for c in conditions:
                    prim = [r for r in rows if r["condition"] == c and r["primary"]]
                    pfm[c] = round(sum(r["outcome"] == "correct" for r in prim)
                                   / max(1, len(prim)), 3)
                rec = {"persona": pid, "tier": args.tier, "A": a_name, "B": b_name,
                       "model": b.model, "served": sorted(b.served),
                       "cost_usd": round(b.cost - before[0], 4), "calls": b.calls - before[1],
                       "tokens": dict(b.tokens - before[2]), "stops": dict(b.stops - before[3]), "pfm": pfm}
                with log.open("a") as f:
                    f.write(json.dumps(rec) + "\n")
                print(json.dumps(rec))
        print(f"{b_name}: ${b.cost:.4f} over {b.calls} calls")


if __name__ == "__main__":
    main()
