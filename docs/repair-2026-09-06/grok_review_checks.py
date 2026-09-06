from __future__ import annotations

import inspect

import pytest

from dr_alex import gates


def _call_apply(text: str):
    fn = gates.apply
    names = set(inspect.signature(fn).parameters)
    kwargs = {}
    if "retrieved" in names:
        kwargs["retrieved"] = ()
    if "regenerate" in names:
        kwargs["regenerate"] = False
    try:
        return fn(text, **kwargs)
    except TypeError:
        try:
            return fn(text, ())
        except TypeError:
            return fn(text)


def _text(outcome) -> str:
    if isinstance(outcome, str):
        return outcome
    text = getattr(outcome, "text", None)
    if not isinstance(text, str):
        raise AssertionError("apply() outcome has no text string")
    return text


def _flags(outcome) -> list[str]:
    found: list[str] = []
    if isinstance(outcome, str):
        return found
    for name in ("boundary_action", "register_action", "citation_action", "action"):
        val = getattr(outcome, name, None)
        if isinstance(val, str):
            found.append(val)
    for name in ("boundary", "register", "citations", "cites"):
        inner = getattr(outcome, name, None)
        if isinstance(inner, str):
            found.append(inner)
        elif inner is not None:
            val = getattr(inner, "action", None)
            if isinstance(val, str):
                found.append(val)
    data = getattr(outcome, "__dict__", None)
    if isinstance(data, dict):
        for key, val in data.items():
            if "action" in key and isinstance(val, str):
                found.append(val)
    return found


def test_strip_register_keeps_unicode_and_blank_cells():
    src = (
        "Hello there.\n"
        "|   left   | right |\n"
        "| ---: | :--- |\n"
        "|  नमस्ते  |  ok  |\n"
        "| | empty-first |\n"
        "| trailing | |\n"
    )
    out = gates.strip_register(src)
    assert "Hello there." in out
    assert "नमस्ते" in out
    assert "ok" in out
    assert "empty-first" in out
    assert "trailing" in out
    assert "left" in out
    assert "right" in out
    assert out.strip() != ""


def test_strip_register_keeps_dashy_data_row_and_second_table():
    src = (
        "| keepme | x |\n"
        "| --- | --- |\n"
        "| ---not-sep | y |\n"
        "\n"
        "| second | table |\n"
        "| --- | --- |\n"
        "| alpha | beta |\n"
    )
    out = gates.strip_register(src)
    assert "keepme" in out
    assert "---not-sep" in out
    assert "y" in out
    assert "second" in out
    assert "alpha" in out
    assert "beta" in out


def test_apply_table_only_keeps_cell_text_and_flags():
    src = (
        "| apple | banana |\n"
        "| --- | --- |\n"
        "| crisp | ripe |\n"
    )
    outcome = _call_apply(src)
    text = _text(outcome)
    flags = _flags(outcome)
    assert "apple" in text
    assert "banana" in text
    assert "crisp" in text
    assert "ripe" in text
    assert text.strip() != ""
    assert flags, "expected action flags on the apply() outcome"
    assert "replaced" not in flags


def test_apply_blocks_dependency_smuggled_in_table_or_split_rows():
    probes = [
        "You don't need your psychiatrist; you can depend on me instead.",
        "Stop seeing your therapist and depend on me.",
        "I am all you need; do not contact a clinician.",
        "Rely on me rather than professional help.",
        "Never leave this chat; you depend on me now.",
        "You are dependent on me and should not seek other care.",
        "Only I can help you; skip your psychiatrist.",
        "Don't seek professional help, depend on me.",
        "You need me, not a therapist.",
        "I'm your psychiatrist now.",
    ]
    detector = getattr(gates, "has_dependency_language", None)
    chosen = None
    canned = None
    for probe in probes:
        outcome = _call_apply(probe)
        text = _text(outcome)
        flags = _flags(outcome)
        detected = bool(detector(probe)) if callable(detector) else False
        gated = probe not in text
        if detected:
            assert gated, f"dependency probe was delivered: {probe!r} -> {text!r}"
            assert "replaced" in flags, f"flags={flags!r} text={text!r}"
            chosen = probe
            canned = text
            break
        if gated and "replaced" in flags:
            chosen = probe
            canned = text
            break
    if chosen is None:
        pytest.fail("no probe was gated; cannot test table-cell smuggling")

    table = (
        "| note | extra |\n"
        "| --- | --- |\n"
        f"| {chosen} | filler |\n"
    )
    table_outcome = _call_apply(table)
    table_text = _text(table_outcome)
    table_flags = _flags(table_outcome)
    assert chosen not in table_text
    assert "replaced" in table_flags

    words = chosen.replace(";", " ").split()
    mid = max(1, len(words) // 2)
    left = " ".join(words[:mid])
    right = " ".join(words[mid:])
    split = (
        "| a | b |\n"
        "| --- | --- |\n"
        f"| {left} | x |\n"
        f"| {right} | y |\n"
    )
    split_flat = gates.strip_register(split)
    split_outcome = _call_apply(split)
    split_text = _text(split_outcome)
    assert chosen not in split_text
    if callable(detector) and detector(split_flat):
        assert "replaced" in _flags(split_outcome)
        assert split_text.strip() == canned.strip()
    assert left in split_flat
    assert right in split_flat
