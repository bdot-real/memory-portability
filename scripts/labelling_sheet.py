"""Export the human-labelling sheet: a fixed subset of the answers both judges grade.

  uv run python scripts/labelling_sheet.py            # writes runs/labelling/sheet.csv

Per tier: --audit answers per deterministic outcome (drawn from judge_answers' audit sample, so
every labelled answer also has both judges' verdicts) and --pref preference answers. Rows are
shuffled and identified by a number only; the scorer's outcome, the condition and the engines stay
out of the sheet, so the labeller grades blind. runs/labelling/keys.json maps each number to the
key that joins the label back to runs/judge/<tier>/<judge>/*.jsonl; don't send it to the labeller.
"""

import argparse
import csv
import json
import random

from judge_answers import DATA, audit_sample, key

from ompm.judge import criteria
from ompm.personas import load
from ompm.pipeline import RUNS


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", type=int, default=10, help="answers per outcome and tier")
    ap.add_argument("--pref", type=int, default=40, help="preference answers per tier")
    ap.add_argument("--prefix", default="e")
    args = ap.parse_args()

    rng, out = random.Random(2028), []
    for tier in ("small", "large"):
        rows = []
        for f in sorted((RUNS / "results" / tier).glob(f"*-to-*/{args.prefix}*.jsonl")):
            rows += [json.loads(x) for x in f.read_text().splitlines() if x]
        audit = audit_sample(rows, 40)  # the judges' sample; take a subset of it per outcome
        picked = []
        for o in sorted({r["outcome"] for r in audit}):
            picked += [r for r in audit if r["outcome"] == o][: args.audit]
        pref = sorted((r for r in rows if r["kind"] == "preference"), key=key)
        picked += rng.sample(pref, min(args.pref, len(pref)))
        personas = {}
        for r in picked:
            if r["persona"] not in personas:
                personas[r["persona"]] = load(DATA / tier / f"{r['persona']}.json")
            probe = next(q for q in personas[r["persona"]].probes if q.id == r["probe"])
            out.append({"key": f"{tier}|{key(r)}", "question": probe.question,
                        "criteria": criteria(probe), "answer": r["text"].strip() or "(empty)",
                        "label (pass/fail/abstained)": "", "note": ""})
    rng.shuffle(out)
    path = RUNS / "labelling" / "sheet.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = {}
    for i, row in enumerate(out, 1):
        keys[i] = row.pop("key")
        out[i - 1] = {"id": i, **row}
    (path.parent / "keys.json").write_text(json.dumps(keys, indent=1))
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(f"{len(out)} rows -> {path}")


if __name__ == "__main__":
    main()
