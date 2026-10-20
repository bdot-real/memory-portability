"""Check schema-constrained extraction on each local engine.

Uses the model view of the @mem/core schema as the Ollama `format` and the registry field
descriptions in the prompt; maps output back to the registry shape and validates it there.

Usage: uv run python scripts/schema_decode_test.py [--schema PATH] [engine ...]
"""

import argparse
import json
from pathlib import Path

import jsonschema

from ompm.engines import ENGINES
from ompm.schema import (ITEM_CLASSES, SCHEMA_PATH, extraction_envelope, field_guide,
                         load_package_schema, to_canonical)

SNIPPET = (
    "[Session 3, 2026-09-14] user: Big news, I moved from Montreal to Quebec City last week. "
    "Also my sister Ingrid is allergic to walnuts, so no walnut desserts at her birthday. "
    "I still need to renew my passport; next step is getting new photos."
)
KNOWN = "Existing memory items:\nm1 (Fact): Dana lives in Montreal."
EXPECT = {"facts": 1, "preferences": 1, "relationships": 1, "tasks": 1}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", type=Path, default=SCHEMA_PATH)
    ap.add_argument("engines", nargs="*")
    args = ap.parse_args()

    package = load_package_schema(args.schema)
    envelope = extraction_envelope(package)
    prompt = (
        "You maintain a memory store about the user (Dana). From the conversation excerpt, "
        "extract every new or changed memory item. Write each statement in the third person, "
        "naming people rather than using pronouns (use they/them if a pronoun is unavoidable), "
        "so it makes sense on its own. Facts about another person are about that person. "
        "If an item replaces an existing one, list the old id in supersedes.\n\n"
        f"Fields:\n{field_guide(package)}\n\n{KNOWN}\n\nExcerpt:\n{SNIPPET}\n\nReturn JSON only."
    )
    print(f"schema: {args.schema.name}; envelope bytes: {len(json.dumps(envelope))}")
    for name in args.engines or list(ENGINES):
        r = ENGINES[name].chat([{"role": "user", "content": prompt}], schema=envelope)
        try:
            data = json.loads(r.text)
            jsonschema.validate(data, envelope)
            n = 0
            for field, cls in ITEM_CLASSES.items():
                for obj in data[field]:
                    n += 1
                    canon = to_canonical(obj, cls, f"https://example.org/x/m{n}",
                                         lambda who: f"https://example.org/x/{who.lower()}")
                    jsonschema.validate(canon, package["$defs"][cls])
            counts = {k: len(v) for k, v in data.items()}
            print(f"{name}: valid in {r.seconds:.0f}s, counts {counts} (expected ~{EXPECT})")
            for field in ITEM_CLASSES:
                for obj in data[field]:
                    print(f"    {field[:-1]:12} {json.dumps(obj, ensure_ascii=False)[:150]}")
        except Exception as e:  # report and continue with the next engine
            print(f"{name}: INVALID {type(e).__name__}: {str(e)[:200]}\n    {r.text[:300]}")


if __name__ == "__main__":
    main()
