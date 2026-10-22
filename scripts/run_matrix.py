"""Run the eval matrix: every persona × every cross-engine A→B pair × all conditions.

Usage:
  uv run python scripts/run_matrix.py --tier small --personas e01-e12

Resumable: a (persona, pair) whose results file exists is skipped, and dialogue and write-in are
cached per A, so a killed run picks up where it stopped. Personas are the outer loop, so a partial
run still covers every pair for the personas it finished. A failure is logged and the run moves on.
Log: runs/matrix-<tier>.log
"""

import argparse
import json
import time
import traceback
from pathlib import Path

from ompm.engines import ENGINES
from ompm.personas import load
from ompm.pipeline import RUNS, run

DATA = Path(__file__).resolve().parents[1] / "data/personas"
CONDITIONS = ["a1", "a2", "b", "c", "oracle"]


def persona_ids(spec: str) -> list[str]:
    if "-" in spec:
        lo, hi = spec.split("-")
        return [f"{lo[0]}{k:02d}" for k in range(int(lo[1:]), int(hi[1:]) + 1)]
    return spec.split(",")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="small")
    ap.add_argument("--personas", default="e01-e12")
    ap.add_argument("--engines", default="llama,mistral,qwen")
    args = ap.parse_args()

    engines = args.engines.split(",")
    pairs = [(a, b) for a in engines for b in engines if a != b]
    log = RUNS / f"matrix-{args.tier}.log"
    log.parent.mkdir(parents=True, exist_ok=True)

    def note(msg: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
        print(line, flush=True)
        with log.open("a") as f:
            f.write(line + "\n")

    note(f"start tier={args.tier} personas={args.personas} pairs={pairs}")
    for pid in persona_ids(args.personas):
        p = load(DATA / args.tier / f"{pid}.json")
        for a, b in pairs:
            out = RUNS / "results" / args.tier / f"{a}-to-{b}" / f"{pid}.jsonl"
            if out.exists():
                continue
            t0 = time.monotonic()
            try:
                meta = run(p, ENGINES[a], ENGINES[b], CONDITIONS)
            except Exception:
                note(f"FAIL {pid} {a}->{b}\n{traceback.format_exc()}")
                continue
            rows = [json.loads(x) for x in out.read_text().splitlines() if x]
            pfm = {}
            for c in CONDITIONS:
                prim = [r for r in rows if r["condition"] == c and r["primary"]]
                pfm[c] = round(sum(r["outcome"] == "correct" for r in prim) / max(1, len(prim)), 2)
            note(f"done {pid} {a}->{b} {time.monotonic() - t0:.0f}s PFM {pfm} "
                 f"recall {(meta['extraction'] or {}).get('recall')}")
    note("end")


if __name__ == "__main__":
    main()
