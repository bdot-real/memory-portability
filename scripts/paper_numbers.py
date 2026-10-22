"""Turn run outputs into the paper's numbers and tables. No engine calls.

Usage: uv run python scripts/paper_numbers.py [--tier small] [--prefix e]

Reads runs/results/<tier>/<A>-to-<B>/<prefix>*.jsonl (+ .meta.json) and writes
paper/numbers.tex (\\resdef{key}{value}, printed in the text by \\res{key}) and
paper/tables/*.tex. PFM is the share of primary probes scored correct, per persona and pair;
summaries average over pairs within a persona, then over personas, with 95% bootstrap
intervals over personas.
"""

import argparse
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONDS = ["oracle", "a2", "a1", "b", "c"]
LABEL = {"oracle": "oracle (gold store)", "a2": "a2 ontology, rendered",
         "a1": "a1 ontology, MCP tools", "b": "b transcript", "c": "c summary"}
KINDS = ["recall", "update", "multihop", "task"]


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def boot(per_persona: dict[str, float], n: int = 2000, seed: int = 0) -> tuple[float, float]:
    rng, ids = random.Random(seed), list(per_persona)
    means = sorted(mean(per_persona[rng.choice(ids)] for _ in ids) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def load(tier: str, prefix: str):
    rows, metas = [], []
    for f in sorted((ROOT / "runs/results" / tier).glob(f"*-to-*/{prefix}*.jsonl")):
        rows += [json.loads(x) for x in f.read_text().splitlines() if x]
        m = f.with_suffix(".meta.json")
        if m.exists():
            metas.append(json.loads(m.read_text()))
    return rows, metas


def pfm_table(rows, cond, kinds=None):
    """{persona: PFM averaged over pairs} for one condition."""
    acc = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["condition"] != cond or not r["primary"]:
            continue
        if kinds and r["kind"] not in kinds:
            continue
        acc[r["persona"]][(r["A"], r["B"])].append(r["outcome"] == "correct")
    return {p: mean(mean(v) for v in pairs.values()) for p, pairs in acc.items()}


def fmt(x, d=2):
    return "--" if x != x else f"{x:.{d}f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="small")
    ap.add_argument("--prefix", default="e")
    args = ap.parse_args()
    rows, metas = load(args.tier, args.prefix)
    if not rows:
        raise SystemExit("no results yet")
    personas = sorted({r["persona"] for r in rows})
    pairs = sorted({(r["A"], r["B"]) for r in rows})
    out: dict[str, str] = {}
    tables = ROOT / "paper/tables"
    tables.mkdir(parents=True, exist_ok=True)

    # Tokens of carried memory, per condition (a1 carries none in the prompt).
    tok = defaultdict(list)
    for m in metas:
        for c, t in (m.get("context_tokens") or {}).items():
            tok[c].append(t)

    # Overall PFM table.
    lines = [r"\begin{tabular}{@{}lccr@{}}", r"\toprule",
             r"Condition & \PFM & 95\% CI & Tokens \\", r"\midrule"]
    for c in CONDS:
        pp = pfm_table(rows, c)
        if not pp:
            continue
        m, (lo, hi) = mean(pp.values()), boot(pp)
        out[f"pfm-{c}"] = fmt(m)
        out[f"pfm-{c}-ci"] = f"[{fmt(lo)}, {fmt(hi)}]"
        t = mean(tok[c]) if tok[c] else float("nan")
        out[f"tok-{c}"] = "--" if t != t else f"{t:,.0f}"
        lines.append(f"{LABEL[c]} & {fmt(m)} & [{fmt(lo)}, {fmt(hi)}] & "
                     f"{out[f'tok-{c}'].replace(',', '{,}')} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (tables / "pfm-overall.tex").write_text("\n".join(lines) + "\n")
    if tok["oracle"] and tok["b"]:
        out["tok-ratio-oracle-b"] = f"{mean(tok['b']) / mean(tok['oracle']):.0f}"

    # By probe kind.
    lines = [r"\begin{tabular}{@{}l" + "c" * len(KINDS) + "@{}}", r"\toprule",
             "Condition & " + " & ".join(KINDS) + r" \\", r"\midrule"]
    for c in CONDS:
        cells = [fmt(mean(pfm_table(rows, c, {k}).values())) for k in KINDS]
        lines.append(f"{LABEL[c]} & " + " & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (tables / "pfm-kinds.tex").write_text("\n".join(lines) + "\n")

    # By pair.
    lines = [r"\begin{tabular}{@{}l" + "c" * len(CONDS) + "@{}}", r"\toprule",
             "$A\\to B$ & " + " & ".join(CONDS) + r" \\", r"\midrule"]
    for a, b in pairs:
        sub = [r for r in rows if r["A"] == a and r["B"] == b]
        cells = [fmt(mean(pfm_table(sub, c).values())) for c in CONDS]
        lines.append(f"{a}$\\to${b} & " + " & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (tables / "pfm-pairs.tex").write_text("\n".join(lines) + "\n")

    # Extraction quality per source engine (one store per persona and A).
    ext = {}
    for m in metas:
        if m.get("extraction"):
            ext[(m["persona"], m["A"])] = m["extraction"]
    lines = [r"\begin{tabular}{@{}lccccc@{}}", r"\toprule",
             r"$A$ & Recall & Lenient & Precision & Tombstones/request & Leaked \\", r"\midrule"]
    worst_tomb = 0.0
    for a in sorted({k[1] for k in ext}):
        es = [e for (p, aa), e in ext.items() if aa == a]
        tpr = mean(e["tombstones"] / max(1, e["erasures_requested"]) for e in es)
        worst_tomb = max(worst_tomb, tpr)
        leaked = sum(e["erasures_leaked"] for e in es)
        req = sum(e["erasures_requested"] for e in es)
        out[f"recall-{a}"] = fmt(mean(e["recall"] for e in es))
        lines.append(f"{a} & {fmt(mean(e['recall'] for e in es))} & "
                     f"{fmt(mean(e['recall_lenient'] for e in es))} & "
                     f"{fmt(mean(e['precision'] for e in es))} & {fmt(tpr, 1)} & "
                     f"{leaked}/{req} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (tables / "extraction.tex").write_text("\n".join(lines) + "\n")
    out["tomb-per-request"] = fmt(worst_tomb, 1)

    # Tool use (a1).
    a1 = [r for r in rows if r["condition"] == "a1"]
    if a1:
        out["a1-nocall-rate"] = fmt(mean(r["tool_calls"] == 0 for r in a1))
        out["a1-calls-per-probe"] = fmt(mean(r["tool_calls"] for r in a1), 1)
        out["a1-tool-error-rate"] = fmt(
            sum(r["tool_errors"] for r in a1) / max(1, sum(r["tool_calls"] for r in a1)))

    # Secondary probes: provenance and null accuracy; erasure leaks given the control recalled.
    by_key = {(r["persona"], r["A"], r["B"], r["condition"], r["probe"]): r for r in rows}
    for c in CONDS:
        cr = [r for r in rows if r["condition"] == c]
        for kind in ("provenance", "null"):
            xs = [r["outcome"] == "correct" for r in cr if r["kind"] == kind]
            out[f"{kind}-{c}"] = fmt(mean(xs))
        er = [r for r in cr if r["kind"] == "erasure" and r.get("control")]
        ok = [r for r in er if by_key.get((r["persona"], r["A"], r["B"], c, r["control"]),
                                          {}).get("outcome") == "correct"]
        out[f"leak-{c}"] = fmt(mean(r["outcome"] == "leaked" for r in ok))
        out[f"leak-{c}-n"] = str(len(ok))

    out["n-personas"] = str(len(personas))
    out["n-pairs"] = str(len(pairs))
    out["n-probes"] = f"{len({(r['persona'], r['probe']) for r in rows}):,}".replace(",", "{,}")
    out["n-answers"] = f"{len(rows):,}".replace(",", "{,}")
    man = ROOT / "data/personas" / args.tier / f"manifest-{args.prefix}.json"
    if man.exists():
        ps = json.loads(man.read_text())["personas"]
        out["items-per-persona"] = f"{statistics.mean(p['items'] for p in ps):.0f}"
    for tier in ("small", "large"):
        mf = ROOT / "data/personas" / tier / f"manifest-{args.prefix}.json"
        if mf.exists():
            ps = json.loads(mf.read_text())["personas"]
            out[f"tok-{tier}"] = f"{statistics.mean(p['est_tokens'] for p in ps) / 1000:.0f}"
    out["loc"] = f"{sum(len(f.read_text().splitlines()) for f in (ROOT / 'src').rglob('*.py')):,}"
    out["loc"] = out["loc"].replace(",", "{,}")

    lines = ["% Generated by scripts/paper_numbers.py; do not edit.",
             f"% tier={args.tier} prefix={args.prefix} personas={','.join(personas)}"]
    lines += [f"\\resdef{{{k}}}{{{v}}}" for k, v in sorted(out.items())]
    (ROOT / "paper/numbers.tex").write_text("\n".join(lines) + "\n")
    print(f"{len(personas)} personas, {len(pairs)} pairs, {len(rows)} answers")
    for c in CONDS:
        if f"pfm-{c}" in out:
            print(f"  {c:7} PFM {out[f'pfm-{c}']} {out[f'pfm-{c}-ci']}  tokens {out[f'tok-{c}']}")


if __name__ == "__main__":
    main()
