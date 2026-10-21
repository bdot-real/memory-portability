"""Generate the persona dataset: one JSON and one gold Turtle file per persona, plus a manifest.

Usage: uv run python scripts/generate_personas.py [--n 12] [--tier small] [--seed 2026] [--prefix p]

The dev set is prefix "p" (seed 2026). The eval set is prefix "e" with a fresh seed, generated
only after prompts were frozen; its manifest is manifest-e.json.
"""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from ompm.gold import render
from ompm.personas import generate


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--tier", choices=["small", "large"], default="small")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--prefix", default="p")
    ap.add_argument("--out", type=Path, default=Path("data/personas"))
    args = ap.parse_args()

    out = args.out / args.tier
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"seed": args.seed, "tier": args.tier, "prefix": args.prefix, "personas": []}
    kinds: Counter = Counter()
    for k in range(args.n):
        pid = f"{args.prefix}{k + 1:02d}"
        p = generate(pid, seed=args.seed * 1000 + k, tier=args.tier)
        js = json.dumps(p.to_json(), indent=1, ensure_ascii=False)
        ttl = render(p)
        (out / f"{pid}.json").write_text(js)
        (out / f"{pid}.gold.ttl").write_text(ttl)
        kinds.update(q.kind for q in p.probes)
        manifest["personas"].append({
            "id": pid, "items": len(p.items), "probes": len(p.probes),
            "est_tokens": p.est_tokens,
            "sha256": hashlib.sha256((js + ttl).encode()).hexdigest(),
        })
    manifest["probe_kinds"] = dict(kinds)
    manifest["dataset_sha256"] = hashlib.sha256(
        "".join(x["sha256"] for x in manifest["personas"]).encode()).hexdigest()
    (out / ("manifest.json" if args.prefix == "p" else f"manifest-{args.prefix}.json")).write_text(json.dumps(manifest, indent=1))
    print(json.dumps({k: v for k, v in manifest.items() if k != "personas"}, indent=1))
    for x in manifest["personas"][:3]:
        print(x)


if __name__ == "__main__":
    main()
