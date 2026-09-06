# Two accepted checks; untouched full submission and failed formatting check are in docs/repair-2026-09-06.
from dr_alex.gates import apply

BOUNDARY = "I'm really glad you reached out. I want to be honest, though: I'm support between your sessions with Shreya — not a stand-in for the people in your life. That's on purpose. Who's one real person you could reach today — Shreya, Sachin, or Ishani?"


def test_register_regen_injecting_dependency_replaced_without_extra_calls():
    calls = []

    def regen(corrective: str):
        calls.append(corrective)
        return "I'm all you need."

    reply = "| A | B |\n| --- | --- |\n| 1 | 2 |"
    out = apply(reply, [], regenerate=regen)
    assert len(calls) == 1
    assert out.dependency_action == "replaced"
    assert out.text == BOUNDARY


def test_dependency_alternatives_and_negative_control():
    noop = lambda corrective: None
    misses = []
    for phrase in ("You only need me.", "I am all you need."):
        out = apply(phrase, [], regenerate=noop)
        if out.dependency_action != "replaced" or out.text != BOUNDARY:
            misses.append((phrase, out.dependency_action))
    assert not misses, f"reproduced miss: {misses!r}"
    ctrl = apply("I cannot replace your therapist.", [], regenerate=noop)
    assert ctrl.dependency_action == "clean"
    assert ctrl.text == "I cannot replace your therapist."
