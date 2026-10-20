"""Time one persona-sized context against each local engine.

Checks two things before we size the study:
  1. Ollama reads the whole prompt (prompt_eval_count matches our estimate on a cold call).
  2. How long a probe costs cold vs. with the persona context cached as a shared prefix.

Usage: uv run python scripts/smoke_timing.py [ctx_tokens] [engine ...]
"""

import random
import sys

from ompm.engines import ENGINES, estimate_tokens

TOPICS = ["work", "cooking", "travel", "family", "health", "music", "garden", "finance"]


def filler_transcript(target_tokens: int, needle: str) -> str:
    rng = random.Random(0)
    lines, i = [], 0
    while estimate_tokens([{"content": "\n".join(lines)}]) < target_tokens:
        t = rng.choice(TOPICS)
        lines.append(f"[s{i // 20}] user: Some more thoughts about {t}, item {i}, nothing major.")
        lines.append(f"[s{i // 20}] assistant: Noted about {t}. Anything else on {t}?")
        if i == len(lines) // 4:
            lines.append(f"[s{i // 20}] user: {needle}")
        i += 1
    return "\n".join(lines)


def main() -> None:
    ctx = int(sys.argv[1]) if len(sys.argv) > 1 else 16000
    names = sys.argv[2:] or list(ENGINES)
    needle = "By the way, my sister Ingrid is allergic to walnuts."
    transcript = filler_transcript(ctx, needle)
    system = {"role": "system", "content": "Prior conversation history:\n" + transcript}
    est = estimate_tokens([system])
    questions = [
        "Which nut is my sister allergic to? Answer in one word.",
        "What is my sister's name? Answer in one word.",
        "Name one topic we discussed. Answer in one word.",
    ]
    for name in names:
        eng = ENGINES[name]
        print(f"== {name} ({eng.model}) est_prompt≈{est} num_ctx={eng.num_ctx}")
        for k, q in enumerate(questions):
            r = eng.chat([system, {"role": "user", "content": q}])
            tag = "cold" if k == 0 else "warm"
            print(
                f"  {tag} prompt_eval={r.prompt_tokens:>6} out={r.completion_tokens:>3} "
                f"{r.seconds:6.1f}s  -> {r.text.strip()[:60]!r}"
            )


if __name__ == "__main__":
    main()
