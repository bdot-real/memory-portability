"""Turn run outputs into the paper's numbers and tables. No engine calls.

Usage: uv run python scripts/paper_numbers.py [--prefix e]

Reads both tiers' runs/results/<tier>/<A>-to-<B>/<prefix>*.jsonl (+ .meta.json), the strong-
extractor runs (runs/results-strong, runs/strong) where present, and writes paper/numbers.tex
(\\resdef{key}{value}, printed in the text by \\res{key}) and paper/tables/*.tex. Keys that
depend on the tier end in -small or -large. PFM is the share of primary probes scored correct, per persona and pair;
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
STRONG = ["a2x", "a1x"]  # same conditions, store written by the strong extractor
TIERS = ["small", "large"]
LABEL = {"oracle": "oracle (gold store)", "a2": "a2 ontology, rendered",
         "a1": "a1 ontology, MCP tools", "b": "b transcript", "c": "c summary",
         "a2x": "a2, strong extractor", "a1x": "a1, strong extractor"}
KINDS = ["recall", "update", "multihop", "task"]


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def boot(per_persona: dict[str, float], n: int = 2000, seed: int = 0) -> tuple[float, float]:
    rng, ids = random.Random(seed), list(per_persona)
    means = sorted(mean(per_persona[rng.choice(ids)] for _ in ids) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def load(tier: str, prefix: str):
    rows, metas, strong = [], [], []
    for f in sorted((ROOT / "runs/results" / tier).glob(f"*-to-*/{prefix}*.jsonl")):
        rows += [json.loads(x) for x in f.read_text().splitlines() if x]
        m = f.with_suffix(".meta.json")
        if m.exists():
            metas.append(json.loads(m.read_text()))
    for f in sorted((ROOT / "runs/results-strong" / tier).glob(f"*-to-*/{prefix}*.jsonl")):
        strong += [json.loads(x) for x in f.read_text().splitlines() if x]
    log = ROOT / "runs/strong" / tier / "extraction.jsonl"
    ext = [json.loads(x) for x in log.read_text().splitlines() if x] if log.exists() else []
    return rows, metas, strong, ext


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


def tier_numbers(tier: str, prefix: str, tables: Path) -> tuple[dict, dict, list]:
    """Numbers (unsuffixed keys) for one tier, its overall-table cells and its extraction rows."""
    rows, metas, strong, ext_strong = load(tier, prefix)
    out: dict[str, str] = {}
    personas = sorted({r["persona"] for r in rows})
    pairs = sorted({(r["A"], r["B"]) for r in rows})

    # Tokens of carried memory, per condition (a1 carries none in the prompt).
    tok = defaultdict(list)
    for m in metas:
        for c, t in (m.get("context_tokens") or {}).items():
            tok[c].append(t)

    # Overall PFM, plus the strong-extractor conditions on the personas they cover so far.
    cells = {}
    for c in CONDS + STRONG:
        pp = pfm_table(strong if c in STRONG else rows, c)
        if not pp:
            continue
        m, (lo, hi) = mean(pp.values()), boot(pp)
        out[f"pfm-{c}"], out[f"pfm-{c}-ci"] = fmt(m), f"[{fmt(lo)}, {fmt(hi)}]"
        t = mean(tok[c]) if tok[c] else float("nan")
        out[f"tok-{c}"] = "--" if t != t else f"{t:,.0f}"
        cells[c] = (fmt(m), f"[{fmt(lo)}, {fmt(hi)}]", out[f"tok-{c}"].replace(",", "{,}"),
                    len(pp))
        if c in STRONG:
            # Paired with the source engines' own store on the same personas and pairs.
            base_ = pfm_table(rows, c[:2])
            out[f"pfm-{c[:2]}-on-x"] = fmt(mean(base_[q] for q in pp))
            out[f"n-personas-{c}"] = str(len(pp))
    if tok["oracle"] and tok["b"]:
        out["tok-ratio-oracle-b"] = f"{mean(tok['b']) / mean(tok['oracle']):.0f}"

    # By probe kind, and by pair.
    lines = [r"\begin{tabular}{@{}l" + "c" * len(KINDS) + "@{}}", r"\toprule",
             "Condition & " + " & ".join(KINDS) + r" \\", r"\midrule"]
    for c in CONDS:
        kc = [fmt(mean(pfm_table(rows, c, {k}).values())) for k in KINDS]
        lines.append(f"{LABEL[c]} & " + " & ".join(kc) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (tables / f"pfm-kinds-{tier}.tex").write_text("\n".join(lines) + "\n")
    lines = [r"\begin{tabular}{@{}l" + "c" * len(CONDS) + "@{}}", r"\toprule",
             "$A\\to B$ & " + " & ".join(CONDS) + r" \\", r"\midrule"]
    for a, b in pairs:
        sub = [r for r in rows if r["A"] == a and r["B"] == b]
        pc = [fmt(mean(pfm_table(sub, c).values())) for c in CONDS]
        lines.append(f"{a}$\\to${b} & " + " & ".join(pc) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (tables / f"pfm-pairs-{tier}.tex").write_text("\n".join(lines) + "\n")

    # Extraction quality per source engine (one store per persona and A), then the strong
    # extractor's stores of the same dialogues.
    ext = {}
    for m in metas:
        if m.get("extraction"):
            ext[(m["persona"], m["A"])] = m["extraction"]
    errs = defaultdict(lambda: [0, 0])  # A -> [errored sessions, sessions]
    for f in (ROOT / "runs/writein/v3" / tier).glob(f"*/{prefix}*.stats.json"):
        st = json.loads(f.read_text())
        errs[f.parent.name][0] += len(st["errors"])
        errs[f.parent.name][1] += st["sessions"]
    groups = [(a, a, [e for (_, aa), e in ext.items() if aa == a])
              for a in sorted({k[1] for k in ext})]
    groups += [(f"gemma@{a}", f"x-{a}", [e for e in ext_strong if e["A"] == a])
               for a in sorted({e["A"] for e in ext_strong})]
    ext_rows, worst_tomb = [], 0.0
    for name, k, es in groups:
        if not es:
            continue
        tpr = mean(e["tombstones"] / max(1, e["erasures_requested"]) for e in es)
        if not k.startswith("x-"):
            worst_tomb = max(worst_tomb, tpr)
        out[f"recall-{k}"] = fmt(mean(e["recall"] for e in es))
        out[f"precision-{k}"] = fmt(mean(e["precision"] for e in es))
        bad, n = errs[name]
        if n:
            out[f"write-errors-{k}"] = f"{bad}/{n}"
        ext_rows.append((name, len(es), fmt(mean(e["recall"] for e in es)),
                         fmt(mean(e["recall_lenient"] for e in es)),
                         fmt(mean(e["precision"] for e in es)), fmt(tpr, 1),
                         f"{sum(e['erasures_leaked'] for e in es)}/"
                         f"{sum(e['erasures_requested'] for e in es)}",
                         f"{bad}/{n}" if n else "--"))
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
    print(f"{tier}: {len(personas)} personas, {len(pairs)} pairs, {len(rows)} answers")
    for c in CONDS + STRONG:
        if f"pfm-{c}" in out:
            print(f"  {c:7} PFM {out[f'pfm-{c}']} {out[f'pfm-{c}-ci']}  tokens {out[f'tok-{c}']}"
                  + (f"  ({cells[c][3]} personas)" if c in STRONG else ""))
    return out, cells, ext_rows


def kappa(a: list, b: list) -> tuple[float, float]:
    """Raw agreement and Cohen's kappa of two equal-length label lists."""
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum(a.count(c) / n * b.count(c) / n for c in set(a) | set(b))
    return po, (po - pe) / (1 - pe) if pe < 1 else 1.0


def agreement() -> dict[str, str]:
    """Scorer-judge, judge-judge and human agreement on pass vs. not pass.

    The scorer passes only `correct`; `hedged` (gold plus a competitor) counts as not passed, which
    is where most scorer-judge disagreement sits, so it is also reported without hedged answers.
    Human labels come from runs/labelling/sheet.csv, joined to the judges through keys.json.
    """
    import csv

    out, verdicts = {}, defaultdict(dict)  # (tier, key) -> {judge or "scorer": pass?}
    for f in sorted((ROOT / "runs/judge").glob("*/*/*.jsonl")):
        tier, judge = f.parts[-3], f.parts[-2]
        for r in (json.loads(x) for x in f.read_text().splitlines() if x):
            verdicts[tier, r["key"]][judge] = r["verdict"] == "pass"
            if r["scorer"] != "needs_judge":
                verdicts[tier, r["key"]]["scorer"] = r["scorer"] == "correct"
                verdicts[tier, r["key"]]["hedged"] = r["scorer"] == "hedged"
    sheet, keys = ROOT / "runs/labelling/sheet.csv", ROOT / "runs/labelling/keys.json"
    if sheet.exists() and keys.exists():
        ids = json.loads(keys.read_text())
        with sheet.open() as fh:
            for row in csv.DictReader(fh):
                lab = row["label (pass/fail/abstained)"].strip().lower()
                if lab:
                    tier, k = ids[row["id"]].split("|", 1)
                    verdicts[tier, k]["human"] = lab == "pass"
    raters = ["scorer", "phi4", "gemma", "human"]
    for tier in TIERS:
        vs = [v for (t, _), v in verdicts.items() if t == tier]
        for i, a in enumerate(raters):
            for b in raters[i + 1:]:
                both = [v for v in vs if a in v and b in v]
                if len(both) < 20:
                    continue
                po, k = kappa([v[a] for v in both], [v[b] for v in both])
                out[f"agree-{a}-{b}-{tier}"], out[f"kappa-{a}-{b}-{tier}"] = fmt(po), fmt(k)
                out[f"n-{a}-{b}-{tier}"] = str(len(both))
                if a == "scorer":
                    nh = [v for v in both if not v["hedged"]]
                    po, k = kappa([v[a] for v in nh], [v[b] for v in nh])
                    out[f"agree-{a}-{b}-nohedge-{tier}"] = fmt(po)
                    out[f"kappa-{a}-{b}-nohedge-{tier}"] = fmt(k)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="e")
    args = ap.parse_args()
    tables = ROOT / "paper/tables"
    tables.mkdir(parents=True, exist_ok=True)
    out: dict[str, str] = {}
    cells, ext_rows = {}, {}
    for tier in TIERS:
        if not list((ROOT / "runs/results" / tier).glob(f"*-to-*/{args.prefix}*.jsonl")):
            continue
        t_out, cells[tier], ext_rows[tier] = tier_numbers(tier, args.prefix, tables)
        out.update({f"{k}-{tier}": v for k, v in t_out.items()})
    if not cells:
        raise SystemExit("no results yet")

    # Overall table: one column group per tier.
    tiers = [t for t in TIERS if t in cells]
    lines = [r"\begin{tabular}{@{}l" + "ccr" * len(tiers) + "@{}}", r"\toprule",
             " & " + " & ".join(rf"\multicolumn{{3}}{{c}}{{{t} tier}}" for t in tiers) + r" \\",
             "".join(rf"\cmidrule(lr){{{2 + 3 * i}-{4 + 3 * i}}}" for i in range(len(tiers))),
             "Condition" + r" & \PFM & 95\% CI & Tokens" * len(tiers) + r" \\", r"\midrule"]
    for c in CONDS + STRONG:
        if not any(c in cells[t] for t in tiers):
            continue
        if c == STRONG[0]:
            lines.append(r"\midrule")
        row = [" & ".join(cells[t][c][:3]) if c in cells[t] else "-- & -- & --" for t in tiers]
        lines.append(f"{LABEL[c]} & " + " & ".join(row) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (tables / "pfm-overall.tex").write_text("\n".join(lines) + "\n")

    # Extraction table: rows per tier and source engine, strong extractor below.
    lines = [r"\begin{tabular}{@{}llcccccc@{}}", r"\toprule",
             r"Tier & Writer$@A$ & Stores & Recall & Lenient & Precision & Tomb./req. & Leaked \\",
             r"\midrule"]
    for t in tiers:
        for name, n, rec, len_, prec, tpr, leak, _ in ext_rows[t]:
            lines.append(f"{t} & {name.replace('@', '@')} & {n} & {rec} & {len_} & {prec} & "
                         f"{tpr} & {leak} \\\\")
        if t != tiers[-1]:
            lines.append(r"\midrule")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (tables / "extraction.tex").write_text("\n".join(lines) + "\n")

    man = ROOT / "data/personas" / "small" / f"manifest-{args.prefix}.json"
    if man.exists():
        ps = json.loads(man.read_text())["personas"]
        out["items-per-persona"] = f"{statistics.mean(p['items'] for p in ps):.0f}"
    for tier in TIERS:
        mf = ROOT / "data/personas" / tier / f"manifest-{args.prefix}.json"
        if mf.exists():
            ps = json.loads(mf.read_text())["personas"]
            out[f"tok-{tier}"] = f"{statistics.mean(p['est_tokens'] for p in ps) / 1000:.0f}"
    out.update(agreement())
    out["loc"] = f"{sum(len(f.read_text().splitlines()) for f in (ROOT / 'src').rglob('*.py')):,}"
    out["loc"] = out["loc"].replace(",", "{,}")

    lines = ["% Generated by scripts/paper_numbers.py; do not edit.",
             f"% prefix={args.prefix} tiers={','.join(tiers)}"]
    lines += [f"\\resdef{{{k}}}{{{v}}}" for k, v in sorted(out.items())]
    (ROOT / "paper/numbers.tex").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
