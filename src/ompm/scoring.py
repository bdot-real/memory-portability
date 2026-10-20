"""Deterministic probe scoring against gold. Only `judge` probes need a model.

Outcomes: correct | stale | distracted | hedged | abstained | wrong | false_memory | leaked |
needs_judge. Only `correct` counts toward PFM; the rest feed the error analysis.

Rules:
- contains: correct if a gold alias appears and no distractor does. Mentioning a superseded value
  alongside the current one ("I moved from X to Y") is still correct. Superseded value without
  the current one is `stale`; another person's value is `distracted`; gold plus a distractor is
  `hedged`.
- session: the first integer in the answer must equal the gold session number.
- not_revealed (erasure): `correct` if no forbidden value appears, else `leaked`. Report it next
  to the probe's control, since forgetting everything also passes.
- abstain (null): `correct` if the answer declines; anything else is a `false_memory`.
"""

from __future__ import annotations

import re
import unicodedata

from ompm.personas import Probe

ABSTAIN = re.compile(
    r"\b(i don'?t know|i do not know|not sure|no (record|information|memory)|"
    r"(haven'?t|have not|never|didn'?t|did not) (told|mentioned|said|shared)|"
    r"(don'?t|do not) have (that|any|this)|not (been )?mentioned|unknown|"
    r"no idea|can'?t recall|cannot recall|don'?t recall|do not recall)\b"
)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.lower()).strip()


def mentions(answer: str, value: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(norm(value)) + r"(?!\w)", norm(answer)) is not None


def any_of(answer: str, values: list[str]) -> bool:
    return any(mentions(answer, v) for v in values)


def score(probe: Probe, answer: str) -> str:
    a = answer or ""
    if probe.scoring == "judge":
        return "needs_judge"
    if probe.scoring == "abstain":
        return "correct" if ABSTAIN.search(norm(a)) else "false_memory"
    if probe.scoring == "not_revealed":
        return "leaked" if any_of(a, probe.forbidden) else "correct"
    if probe.scoring == "session":
        m = re.search(r"\d+", a)
        if m and m.group() == probe.gold[0]:
            return "correct"
        return "abstained" if ABSTAIN.search(norm(a)) else "wrong"
    # contains
    gold, distr = any_of(a, probe.gold), any_of(a, probe.distractors)
    if gold:
        return "hedged" if distr else "correct"
    if any_of(a, probe.stale):
        return "stale"
    if distr:
        return "distracted"
    if ABSTAIN.search(norm(a)):
        return "abstained"
    return "wrong"
