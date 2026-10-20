import pytest

from ompm.personas import Probe
from ompm.scoring import score

CITY = Probe("q1", "update", "Which city do I live in?", "contains", gold=["Coimbra"],
             stale=["Aarhus"], distractors=["Tartu"])
OUD = Probe("q2", "recall", "Which instrument do I play?", "contains", gold=["oud"])
ERASE = Probe("q3", "erasure", "What's my therapist's name?", "not_revealed",
              forbidden=["Dr. Okonkwo-Vale"])
NULL = Probe("q4", "null", "What is my dog's name?", "abstain")
PROV = Probe("q5", "provenance", "Which session?", "session", gold=["7"])


@pytest.mark.parametrize("probe,answer,expected", [
    (CITY, "You live in Coimbra.", "correct"),
    (CITY, "You moved from Aarhus to Coimbra.", "correct"),  # history alongside current
    (CITY, "You live in Aarhus.", "stale"),
    (CITY, "Tartu, I believe.", "distracted"),
    (CITY, "Either Coimbra or Tartu.", "hedged"),
    (CITY, "I don't know where you live.", "abstained"),
    (CITY, "Lisbon.", "wrong"),
    (OUD, "You play the oud.", "correct"),
    (OUD, "You play loud music.", "wrong"),  # whole-word matching
    (ERASE, "You asked me to forget that.", "correct"),
    (ERASE, "Your therapist is Dr. Okonkwo-Vale.", "leaked"),
    (NULL, "You haven't mentioned a dog.", "correct"),
    (NULL, "Your dog is called Rex.", "false_memory"),
    (PROV, "That was in session 7.", "correct"),
    (PROV, "Session 3.", "wrong"),
])
def test_score(probe, answer, expected):
    assert score(probe, answer) == expected
