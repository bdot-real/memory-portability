"""Check that each local engine accepts the stripped @mem/core envelope as an Ollama `format`.

Usage: uv run python scripts/schema_decode_test.py [engine ...]
"""

import json
import sys

import jsonschema

from ompm.engines import ENGINES
from ompm.schema import extraction_envelope, load_package_schema

SNIPPET = (
    "[session 3, 2026-09-14] user: Big news, I moved from Montreal to Quebec City last week. "
    "Also my sister Ingrid is allergic to walnuts, so no walnut desserts at her birthday. "
    "I still need to renew my passport; next step is getting new photos."
)
PROMPT = (
    "Extract memory items about the user and the people they mention from this conversation "
    "excerpt. Use IRIs like https://example.org/p1/user and https://example.org/p1/ingrid for "
    "people and https://example.org/p1/mN for items. Polarity is one of "
    "https://w3id.org/ompm/mem#Likes, #Dislikes, #Avoids. Return JSON only.\n\n" + SNIPPET
)


def main() -> None:
    envelope = extraction_envelope()
    full = load_package_schema()
    print("envelope bytes:", len(json.dumps(envelope)))
    for name in sys.argv[1:] or list(ENGINES):
        eng = ENGINES[name]
        r = eng.chat([{"role": "user", "content": PROMPT}], schema=envelope)
        try:
            data = json.loads(r.text)
            jsonschema.validate(data, envelope)
            # Also validate each item against the unstripped registry schema.
            for field, cls in [("facts", "Fact"), ("preferences", "Preference"),
                               ("relationships", "Relationship"), ("tasks", "TaskState")]:
                for item in data[field]:
                    jsonschema.validate(item, full["$defs"][cls])
            counts = {k: len(v) for k, v in data.items()}
            print(f"{name}: valid {counts} in {r.seconds:.1f}s")
            print("   ", json.dumps(data)[:600])
        except Exception as e:  # report and continue to the next engine
            print(f"{name}: INVALID {type(e).__name__}: {str(e)[:200]}")
            print("   ", r.text[:300])


if __name__ == "__main__":
    main()
