"""LLM judge: scores preference-application answers, and audits the deterministic scorer.

Two uses, one prompt shape. The judge sees the question, what a correct answer must (and must
not) contain, and the answer, and returns a verdict as JSON:

- preference probes (`scoring == "judge"`): the rubric from the generator, e.g. "the menu must not
  contain X (the sister's allergy) or Y (the user dislikes it); ideally it features Z".
- scorer audit: a sample of deterministically scored answers, judged against the gold, stale and
  distractor values, to estimate how often whole-word matching misjudges a paraphrase.

Judges come from families outside the three engines (`gpt` hosted, `phi4` local), so agreement
between two judges can be reported next to agreement with the human-labelled subset.
"""

from __future__ import annotations

import json
from typing import Any

from ompm.personas import Probe
from ompm.pipeline import first_json

VERDICTS = ["pass", "fail", "abstained"]

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": VERDICTS},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
    "additionalProperties": False,
}

INSTRUCTIONS = (
    "You grade an assistant's answer to a user's question. Judge only against the criteria "
    "below, not general quality. Reply with JSON: verdict is \"pass\" if the answer meets the "
    "criteria, \"fail\" if it does not, \"abstained\" if it declines or says it does not know "
    "without attempting an answer. reason is one short sentence."
)


def criteria(probe: Probe) -> str:
    if probe.scoring == "judge":
        return probe.rubric or ""
    lines = [f"A correct answer gives: {' or '.join(probe.gold)}."]
    if probe.stale:
        lines.append(f"These values are out of date; giving only them is a fail: "
                     f"{', '.join(probe.stale)}. Mentioning them as past alongside the current "
                     "value is a pass.")
    if probe.distractors:
        lines.append(f"These belong to other people; giving them as the answer is a fail: "
                     f"{', '.join(probe.distractors)}.")
    lines.append("Paraphrases, spelling variants and equivalent wording count as correct.")
    return " ".join(lines)


def prompt(probe: Probe, answer: str) -> str:
    return (f"{INSTRUCTIONS}\n\nQuestion: {probe.question}\n\nCriteria: {criteria(probe)}\n\n"
            f"Answer to grade:\n{answer.strip() or '(empty)'}")


def judge(engine, probe: Probe, answer: str) -> dict[str, Any]:
    r = engine.chat([{"role": "user", "content": prompt(probe, answer)}], schema=SCHEMA,
                    max_tokens=200)
    try:
        out = first_json(r.text)
        assert isinstance(out, dict) and out.get("verdict") in VERDICTS
    except (json.JSONDecodeError, AssertionError):
        out = {"verdict": "unparseable", "reason": r.text[:200]}
    out["cost_usd"] = float((r.raw.get("usage") or {}).get("cost") or 0)
    return out


def outcome(verdict: str) -> str:
    """Map a verdict onto the scorer's outcomes, so judged probes join the same tables."""
    return {"pass": "correct", "fail": "wrong", "abstained": "abstained"}.get(verdict, "needs_judge")
