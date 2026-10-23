"""Run a judge over matrix answers: every preference answer, plus a scorer-audit sample.

  uv run python scripts/judge_answers.py --judge gemma          # hosted, free tier (default)
  uv run python scripts/judge_answers.py --judge gemini         # hosted, free tier, 20 requests/day
  uv run python scripts/judge_answers.py --judge gpt            # hosted (OpenRouter, paid)
  uv run python scripts/judge_answers.py --judge phi4           # local (needs Ollama)
  uv run python scripts/judge_answers.py --judge gpt --audit 40 # 40 answers per outcome

Resumable: verdicts are appended to runs/judge/<tier>/<judge>/<task>.jsonl, keyed by
persona, A, B, condition and probe, and keys already judged are skipped. The audit sample is
drawn with a fixed seed from primary answers, stratified by the deterministic outcome (draw it
only once the matrix is complete, or the sample shifts as answers are added), so both
judges grade the same answers (and the same ones go to the human labeller).
"""

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

from ompm.engines import FREE, HOSTED, JUDGE
from ompm.judge import judge
from ompm.personas import load
from ompm.pipeline import RUNS

DATA = Path(__file__).resolve().parents[1] / "data/personas"
JUDGES = {"gemma": FREE["gemma"], "gemini": FREE["gemini"], "gpt": HOSTED["gpt"], "phi4": JUDGE}


def key(r) -> str:
    return "|".join([r["persona"], r["A"], r["B"], r["condition"], r["probe"]])


def audit_sample(rows, per_outcome: int, seed: int = 2027):
    by = defaultdict(list)
    for r in sorted(rows, key=key):
        if r["primary"]:
            by[r["outcome"]].append(r)
    rng = random.Random(seed)
    return [r for o in sorted(by) for r in rng.sample(by[o], min(per_outcome, len(by[o])))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", choices=list(JUDGES), default="gemma")
    ap.add_argument("--tier", default="small")
    ap.add_argument("--prefix", default="e")
    ap.add_argument("--audit", type=int, default=40, help="answers per outcome; 0 to skip")
    args = ap.parse_args()

    rows = []
    for f in sorted((RUNS / "results" / args.tier).glob(f"*-to-*/{args.prefix}*.jsonl")):
        rows += [json.loads(x) for x in f.read_text().splitlines() if x]
    tasks = {"preference": [r for r in rows if r["kind"] == "preference"]}
    if args.audit:
        tasks["audit"] = audit_sample(rows, args.audit)

    eng, personas, total = JUDGES[args.judge], {}, 0.0
    for task, todo in tasks.items():
        out = RUNS / "judge" / args.tier / args.judge / f"{task}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        done = {json.loads(x)["key"] for x in out.read_text().splitlines()} if out.exists() else set()
        for r in todo:
            if key(r) in done:
                continue
            if r["persona"] not in personas:
                personas[r["persona"]] = load(DATA / args.tier / f"{r['persona']}.json")
            probe = next(q for q in personas[r["persona"]].probes if q.id == r["probe"])
            v = judge(eng, probe, r["text"])
            total += v["cost_usd"]
            rec = {"key": key(r), "kind": r["kind"], "condition": r["condition"],
                   "scorer": r["outcome"], "judge": args.judge, **v}
            with out.open("a") as f:
                f.write(json.dumps(rec) + "\n")
        print(task, len(todo), "answers", flush=True)
    print(f"judge {args.judge}: ${total:.2f}")


if __name__ == "__main__":
    main()
