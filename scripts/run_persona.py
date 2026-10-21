"""Run one persona through one A→B migration under the given conditions.

Usage:
  uv run python scripts/run_persona.py --persona p01 --tier small --a llama --b mistral \
      --conditions a1,a2,b,c,oracle

Dialogue and write-in results are cached under runs/, so re-running with another B or more
conditions reuses A's work. Results: runs/results/<tier>/<A>-to-<B>/<persona>.jsonl (+ .meta.json).
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from ompm.engines import ENGINES
from ompm.personas import load
from ompm.pipeline import run

DATA = Path(__file__).resolve().parents[1] / "data/personas"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", default="p01")
    ap.add_argument("--tier", default="small")
    ap.add_argument("--a", default="llama")
    ap.add_argument("--b", default="mistral")
    ap.add_argument("--conditions", default="a1,a2,b,c,oracle")
    args = ap.parse_args()

    p = load(DATA / args.tier / f"{args.persona}.json")
    meta = run(p, ENGINES[args.a], ENGINES[args.b], args.conditions.split(","))
    print(json.dumps(meta, indent=1))

    out = Path("runs/results") / args.tier / f"{args.a}-to-{args.b}" / f"{args.persona}.jsonl"
    rows = [json.loads(line) for line in out.read_text().splitlines() if line]
    by = defaultdict(Counter)
    for r in rows:
        by[r["condition"]][r["outcome"]] += 1
    print("\noutcomes by condition (all probes):")
    for cond, c in by.items():
        prim = [r for r in rows if r["condition"] == cond and r["primary"]]
        pfm = sum(r["outcome"] == "correct" for r in prim) / max(1, len(prim))
        print(f"  {cond:7} PFM={pfm:.2f} (n={len(prim)})  {dict(c)}")


if __name__ == "__main__":
    main()
