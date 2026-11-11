"""Local page for labelling the human-agreement sheet, one answer at a time.

  uv run python scripts/label_ui.py            # then open http://127.0.0.1:8765

Reads and writes runs/labelling/sheet.csv in place (each label is saved as you go; a copy of the
sheet as it was at start-up is kept as sheet.csv.bak). It never opens keys.json, so the page
shows only what the labeller may see: question, criteria and answer. Keys: 1 pass, 2 fail,
3 abstained, arrows or j/k to move, n to jump to the next unlabelled row. Stdlib only; listens on
localhost.
"""

import argparse
import csv
import json
import os
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SHEET = Path(__file__).resolve().parents[1] / "runs/labelling/sheet.csv"
LABEL = "label (pass/fail/abstained)"
LABELS = {"pass", "fail", "abstained", ""}
LOCK = threading.Lock()


def read() -> tuple[list[str], list[dict]]:
    with SHEET.open(newline="") as f:
        r = csv.DictReader(f)
        return list(r.fieldnames), list(r)


def write(fields: list[str], rows: list[dict]) -> None:
    tmp = SHEET.with_suffix(".csv.tmp")
    with tmp.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, SHEET)  # atomic: a crash never leaves a half-written sheet


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Answer labelling</title>
<style>
:root { --bg:#fafaf8; --fg:#1d1d1b; --muted:#6b6b66; --line:#e2e1dc; --card:#fff;
  --pass:#1f7a4d; --fail:#b3261e; --abst:#8a6d00; --accent:#2f5bd3; }
@media (prefers-color-scheme: dark) { :root { --bg:#171716; --fg:#ecebe6; --muted:#9a9a93;
  --line:#33332f; --card:#20201e; --pass:#5cc08c; --fail:#f2857c; --abst:#e3c25a; --accent:#8ea8ff; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:16px/1.5 -apple-system, system-ui, sans-serif; }
main { max-width:760px; margin:0 auto; padding:24px 16px 64px; }
header { display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:16px; }
h1 { font-size:17px; margin:0; font-weight:600; }
.progress { flex:1; min-width:160px; height:6px; background:var(--line); border-radius:3px; overflow:hidden; }
.progress > div { height:100%; background:var(--accent); width:0; transition:width .2s; }
.count { color:var(--muted); font-variant-numeric:tabular-nums; font-size:14px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:20px; }
.label { font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); margin:0 0 4px; }
.q { font-size:19px; font-weight:600; margin:0 0 18px; }
.crit { margin:0 0 18px; padding:12px 14px; border-left:3px solid var(--accent);
  background:color-mix(in srgb, var(--accent) 7%, transparent); border-radius:4px; }
.ans { white-space:pre-wrap; margin:0 0 20px; padding:12px 14px; border:1px solid var(--line); border-radius:6px; }
.btns { display:flex; gap:8px; flex-wrap:wrap; }
button { font:inherit; padding:10px 16px; border-radius:8px; border:1px solid var(--line);
  background:var(--card); color:var(--fg); cursor:pointer; }
button kbd { font:12px ui-monospace, monospace; color:var(--muted); margin-left:6px; }
button.pass.on { background:var(--pass); border-color:var(--pass); color:#fff; }
button.fail.on { background:var(--fail); border-color:var(--fail); color:#fff; }
button.abstained.on { background:var(--abst); border-color:var(--abst); color:#fff; }
button.on kbd { color:inherit; opacity:.8; }
textarea { width:100%; font:inherit; margin-top:14px; padding:8px 10px; border-radius:6px;
  border:1px solid var(--line); background:var(--bg); color:var(--fg); min-height:44px; resize:vertical; }
nav { display:flex; justify-content:space-between; gap:8px; margin-top:16px; flex-wrap:wrap; }
.status { color:var(--muted); font-size:13px; min-height:1.5em; margin-top:8px; }
.help { color:var(--muted); font-size:13px; margin-top:24px; }
.done { text-align:center; padding:40px 20px; }
</style></head>
<body><main>
<header><h1>Answer labelling</h1><div class="progress"><div id="bar"></div></div>
<span class="count" id="count"></span></header>
<div class="card" id="card"></div>
<nav><button id="prev">&larr; Previous <kbd>k</kbd></button>
<button id="next-unl">Next unlabelled <kbd>n</kbd></button>
<button id="next">Next <kbd>j</kbd> &rarr;</button></nav>
<div class="status" id="status"></div>
<p class="help">Judge only whether the answer meets the criteria. <b>Pass</b>: meets them.
<b>Fail</b>: wrong, out of date, someone else's value, or breaks a constraint.
<b>Abstained</b>: declines or says it doesn't know. Every choice is saved immediately to the sheet.</p>
</main>
<script>
let rows = [], i = 0;
const $ = id => document.getElementById(id);
const esc = s => s.replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

async function load() {
  rows = await (await fetch("/api/rows")).json();
  const first = rows.findIndex(r => !r.label);
  i = first < 0 ? 0 : first;
  render();
}
function render() {
  const done = rows.filter(r => r.label).length;
  $("bar").style.width = (100 * done / rows.length) + "%";
  $("count").textContent = `${done} / ${rows.length} labelled`;
  const r = rows[i];
  $("card").innerHTML = `
    <p class="label">Item ${r.id} &middot; ${i + 1} of ${rows.length}</p>
    <p class="q">${esc(r.question)}</p>
    <p class="label">Criteria</p><div class="crit">${esc(r.criteria)}</div>
    <p class="label">Answer</p><div class="ans">${esc(r.answer)}</div>
    <div class="btns">
      ${["pass","fail","abstained"].map((l, k) =>
        `<button class="${l}${r.label === l ? " on" : ""}" data-l="${l}">${l[0].toUpperCase() + l.slice(1)}<kbd>${k + 1}</kbd></button>`).join("")}
    </div>
    <textarea id="note" placeholder="Note (optional)">${esc(r.note || "")}</textarea>`;
  document.querySelectorAll(".btns button").forEach(b => b.onclick = () => setLabel(b.dataset.l));
  $("note").onchange = () => save(rows[i].label, $("note").value);
}
async function save(label, note) {
  const r = rows[i];
  const res = await fetch("/api/label", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({id: r.id, label, note})});
  if (!res.ok) { $("status").textContent = "Not saved: " + await res.text(); return false; }
  r.label = label; r.note = note;
  $("status").textContent = `Saved item ${r.id}` + (label ? `: ${label}` : "");
  return true;
}
async function setLabel(l) {
  const label = rows[i].label === l ? "" : l;  // clicking the chosen label again clears it
  if (await save(label, $("note").value) && label) {
    const next = rows.findIndex((r, k) => k > i && !r.label);
    if (next >= 0) i = next;
    else if (rows.every(r => r.label)) { finish(); return; }
  }
  render();
}
function finish() {
  render();
  $("card").insertAdjacentHTML("afterbegin",
    `<div class="done"><p class="q">All ${rows.length} answers labelled.</p>
     <p>The labels are in runs/labelling/sheet.csv. You can still go back and change any of them.</p></div>`);
}
function move(d) { i = Math.max(0, Math.min(rows.length - 1, i + d)); render(); }
$("prev").onclick = () => move(-1);
$("next").onclick = () => move(1);
$("next-unl").onclick = () => { const n = rows.findIndex((r, k) => k > i && !r.label);
  const m = n >= 0 ? n : rows.findIndex(r => !r.label); if (m >= 0) { i = m; render(); } };
document.addEventListener("keydown", e => {
  if (e.target.tagName === "TEXTAREA") return;
  if (e.key === "1") setLabel("pass");
  else if (e.key === "2") setLabel("fail");
  else if (e.key === "3") setLabel("abstained");
  else if (e.key === "ArrowLeft" || e.key === "k") move(-1);
  else if (e.key === "ArrowRight" || e.key === "j") move(1);
  else if (e.key === "n") $("next-unl").click();
});
load();
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: str, ctype: str = "text/plain; charset=utf-8") -> None:
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if self.path == "/api/rows":
            with LOCK:
                _, rows = read()
            out = [{"id": r["id"], "question": r["question"], "criteria": r["criteria"],
                    "answer": r["answer"], "label": r[LABEL].strip().lower(), "note": r["note"]}
                   for r in rows]
            return self._send(200, json.dumps(out), "application/json")
        self._send(404, "not found")

    def do_POST(self):
        if self.path != "/api/label":
            return self._send(404, "not found")
        try:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            rid, label, note = str(body["id"]), str(body["label"]), str(body.get("note", ""))
        except (ValueError, KeyError, TypeError):
            return self._send(400, "bad request")
        if label not in LABELS:
            return self._send(400, f"label must be one of {sorted(LABELS - {''})}")
        with LOCK:
            fields, rows = read()
            hit = [r for r in rows if r["id"] == rid]
            if not hit:
                return self._send(404, f"no row {rid}")
            hit[0][LABEL], hit[0]["note"] = label, note
            write(fields, rows)
        self._send(200, "ok")

    def log_message(self, *args):  # keep the terminal quiet
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    if not SHEET.exists():
        raise SystemExit(f"{SHEET} not found; run scripts/labelling_sheet.py first")
    shutil.copy2(SHEET, SHEET.with_suffix(".csv.bak"))
    _, rows = read()
    done = sum(bool(r[LABEL].strip()) for r in rows)
    print(f"{done}/{len(rows)} labelled. Open http://127.0.0.1:{args.port}  (Ctrl-C to stop)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
