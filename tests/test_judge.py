import json

from ompm.engines import ChatResult
from ompm.judge import SCHEMA, criteria, judge, outcome, prompt
from ompm.personas import Probe

PREF = Probe("q9", "preference", "Suggest a dinner menu for me and my sister.", "judge",
             forbidden=["sesame", "okra"],
             rubric="The menu must not contain sesame (Ines's allergy) or okra.")
CITY = Probe("q1", "update", "Which city do I live in?", "contains", gold=["Coimbra"],
             stale=["Aarhus"], distractors=["Tartu"])


class Canned:
    def __init__(self, text):
        self.text, self.seen = text, None

    def chat(self, messages, schema=None, max_tokens=None, tools=None):
        self.seen = (messages, schema)
        return ChatResult(self.text, [], 1, 1, 0.0, {"usage": {"cost": 0.001}})


def test_criteria_use_rubric_or_gold():
    assert criteria(PREF).startswith("The menu must not contain sesame")
    c = criteria(CITY)
    assert "Coimbra" in c and "Aarhus" in c and "Tartu" in c and "Paraphrases" in c


def test_judge_parses_verdict_and_cost():
    eng = Canned(json.dumps({"verdict": "fail", "reason": "contains sesame"}))
    v = judge(eng, PREF, "Sesame noodles and a salad.")
    assert v["verdict"] == "fail" and v["cost_usd"] == 0.001
    messages, schema = eng.seen
    assert schema is SCHEMA and "Sesame noodles" in messages[0]["content"]
    assert outcome(v["verdict"]) == "wrong"


def test_unparseable_reply_is_not_scored():
    v = judge(Canned("I think it passes"), PREF, "Grilled fish.")
    assert v["verdict"] == "unparseable" and outcome(v["verdict"]) == "needs_judge"


def test_prompt_marks_empty_answer():
    assert "(empty)" in prompt(CITY, "  ")
