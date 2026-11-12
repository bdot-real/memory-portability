"""Archive the run outputs on Zenodo as a draft record; publishing is a separate step.

  uv run python scripts/zenodo_upload.py draft <archive.zip>   # create a draft, upload, print DOI
  uv run python scripts/zenodo_upload.py publish <draft id>     # make it public (permanent)

Needs ZENODO_TOKEN in .env: a personal access token from zenodo.org (Account > Applications) with
the deposit:write and deposit:actions scopes. ZENODO_SANDBOX=1 uses sandbox.zenodo.org instead.
A draft can be edited or deleted on the website; a published record and its DOI cannot be
deleted, only superseded by a new version.
"""

import sys
from pathlib import Path

import httpx

from ompm.engines import api_key


def env(var: str) -> str | None:
    try:
        return api_key(var)  # environment, else the repo's .env
    except KeyError:
        return None


HOST = "https://sandbox.zenodo.org" if env("ZENODO_SANDBOX") == "1" else "https://zenodo.org"
TOKEN = env("ZENODO_TOKEN")

METADATA = {
    "upload_type": "dataset",
    "title": "Run outputs: Ontology-Mediated Memory Portability Across LLM Engines",
    "creators": [{"name": "Medulan, Blake", "affiliation": "Independent researcher"}],
    "description": (
        "<p>Raw outputs behind every number in the paper <em>Ontology-Mediated Memory "
        "Portability Across LLM Engines</em> (ESWC 2027 In-Use track): dialogues played on "
        "three open-weight engines, ontology stores written by those engines and by stronger "
        "hosted extractors, every probe answer under five migration conditions, judge "
        "verdicts and 200 blind human labels. All personas are synthetic.</p>"
        "<p>Code, ontology, personas and paper sources: "
        "<a href=\"https://github.com/bdot-real/memory-portability\">"
        "github.com/bdot-real/memory-portability</a>. Unpack at the repository root; "
        "scripts/paper_numbers.py regenerates the paper's numbers without calling any "
        "engine.</p>"),
    "access_right": "open",
    "license": "cc-by-4.0",
    "keywords": ["agent memory", "portability", "ontologies", "PROV-O", "MCP",
                 "LLM evaluation"],
    "related_identifiers": [{"relation": "isSupplementTo", "resource_type": "software",
                             "identifier": "https://github.com/bdot-real/memory-portability"}],
}


def client() -> httpx.Client:
    if not TOKEN:
        raise SystemExit("ZENODO_TOKEN is not set in .env")
    return httpx.Client(base_url=HOST, headers={"Authorization": f"Bearer {TOKEN}"},
                        timeout=httpx.Timeout(30, write=600))


def draft(archive: Path) -> None:
    with client() as c:
        r = c.post("/api/deposit/depositions", json={"metadata": METADATA})
        r.raise_for_status()
        dep = r.json()
        with archive.open("rb") as fh:
            up = c.put(f"{dep['links']['bucket']}/{archive.name}", content=fh)
        up.raise_for_status()
        doi = dep["metadata"]["prereserve_doi"]["doi"]
        print(f"draft id   {dep['id']}")
        print(f"review at  {HOST}/uploads/{dep['id']}")
        print(f"DOI        {doi} (reserved; resolves once published)")
        print(f"uploaded   {archive.name}, {up.json()['size']} bytes, {up.json()['checksum']}")


def publish(dep_id: str) -> None:
    with client() as c:
        r = c.post(f"/api/deposit/depositions/{dep_id}/actions/publish")
        r.raise_for_status()
        print(f"published  {r.json()['doi_url']}")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("draft", "publish"):
        raise SystemExit(__doc__)
    draft(Path(sys.argv[2])) if sys.argv[1] == "draft" else publish(sys.argv[2])
