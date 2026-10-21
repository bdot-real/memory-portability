"""Dev-set extraction experiment: write-in only, scored against gold by field.

Usage: uv run python scripts/dev_extraction.py --personas p02,p03,p04 --a llama,qwen --version v3
Stores are cached under runs/writein/<version>/<tier>/<A>/. Use only dev personas.
"""

import argparse
import json
from pathlib import Path
from statistics import mean

from ompm.engines import ENGINES
from ompm.evaluate import extraction_quality
from ompm.gold import base
from ompm.personas import load
from ompm.pipeline import RUNS, dialogue, write_ontology
from ompm.store import MemoryStore

DATA = Path(__file__).resolve().parents[1] / "data/personas"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--personas", default="p02,p03,p04")
    ap.add_argument("--a", default="llama,qwen")
    ap.add_argument("--version", default="v3")
    ap.add_argument("--tier", default="small")
    args = ap.parse_args()
    for a_name in args.a.split(","):
        a, results = ENGINES[a_name], []
        for pid in args.personas.split(","):
            p = load(DATA / args.tier / f"{pid}.json")
            cache = RUNS / "writein" / args.version / args.tier / a_name / f"{pid}.store.ttl"
            if cache.exists():
                st = MemoryStore.load(base(p), cache)
            else:
                st, stats = write_ontology(p, a, dialogue(p, a), version=args.version)
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(st.dump())
            q = extraction_quality(p, st)
            results.append(q)
            print(a_name, pid, json.dumps(q), flush=True)
        keys = ("recall", "recall_lenient", "precision", "erasures_leaked", "tombstones")
        print(f"== {a_name} {args.version} mean:",
              {k: round(mean(r[k] for r in results), 3) for k in keys}, flush=True)


if __name__ == "__main__":
    main()
