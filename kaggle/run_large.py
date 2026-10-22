"""Kaggle job: run the large-tier eval matrix on a Kaggle GPU with the pinned Ollama models.

Pushed by scripts/kaggle_push.sh together with the code bundle (private dataset ompm-bundle).
Steps:
  1. unpack (or copy, if Kaggle unpacked it) the bundle into /kaggle/working/ompm (so runs/ lands in the job's output)
  2. install and start Ollama, pull the three engines, and stop unless every model's digest
     equals the one pinned on the Mac (docs/artifacts.md): same weights, or no run at all
  3. run scripts/run_matrix.py --tier large on the personas in OMPM_PERSONAS
  4. pack runs/ as ompm-runs.tar.gz for `kaggle kernels output`

Kaggle sessions stop after about 12 hours. run_matrix is resumable per (persona, pair), and the
whole persona is the unit split between machines, so the next push takes the next personas.
"""

import os
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

PERSONAS = "e01-e03"  # edited by scripts/kaggle_push.sh
PINNED = {"llama3.1:8b": "46e0c10c039e", "mistral:7b": "6577803aa9a0",
          "qwen2.5:14b-instruct": "7cdf5a0187d5"}
WORK = Path("/kaggle/working/ompm")


def sh(cmd: str, **kw) -> str:
    print("$", cmd, flush=True)
    p = subprocess.run(cmd, shell=True, text=True, capture_output=True, **kw)
    if p.returncode:
        print(p.stdout[-2000:], p.stderr[-2000:], sep="\n", flush=True)
        p.check_returncode()
    return p.stdout


def main() -> None:
    # Kaggle may unpack an uploaded archive, so accept either the tarball or its contents.
    print(sh("find /kaggle/input -maxdepth 4 | head -30"), flush=True)
    bundle = next(Path("/kaggle/input").rglob("ompm.tar.gz"), None)
    if bundle:
        WORK.mkdir(parents=True, exist_ok=True)
        with tarfile.open(bundle) as t:
            t.extractall(WORK, filter="data")
    else:
        src = next(Path("/kaggle/input").rglob("pyproject.toml")).parent
        shutil.copytree(src, WORK, dirs_exist_ok=True)

    print(sh("curl -sS -o /dev/null -w '%{http_code}' https://ollama.com"), "<- internet check",
          flush=True)
    # The installer unpacks a .tar.zst; the Kaggle image may lack zstd.
    sh("command -v zstd || (apt-get update -qq && apt-get install -y -qq zstd)")
    sh("curl -fsSL https://ollama.com/install.sh | sh")
    subprocess.Popen("ollama serve > /kaggle/working/ollama.log 2>&1", shell=True)
    time.sleep(10)
    for tag in PINNED:
        sh(f"ollama pull {tag}")
    listing = sh("ollama list")
    print(listing, flush=True)
    for tag, digest in PINNED.items():
        line = next((x for x in listing.splitlines() if x.split()[:1] == [tag]), "")
        if digest not in line:
            sys.exit(f"digest mismatch for {tag}: want {digest}, got {line!r}; not running")

    sh("pip install -q uv")
    env = {**os.environ, "OMPM_HOST": "kaggle-" + sh("nvidia-smi --query-gpu=name --format=csv,noheader").split("\n")[0].replace(" ", "-"),
           "PYTHONUNBUFFERED": "1"}
    proc = subprocess.run(
        f"uv run --python 3.12 python scripts/run_matrix.py --tier large --personas {PERSONAS}",
        shell=True, cwd=WORK, env=env)
    with tarfile.open("/kaggle/working/ompm-runs.tar.gz", "w:gz") as t:
        t.add(WORK / "runs", arcname="runs")
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
