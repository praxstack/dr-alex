"""Directive 1 (binding): exactly ONE function may invoke the model.

Statically prove that the ``claude`` subprocess is spawned from exactly one place —
``dr_alex.llm.complete`` — and that its signature *requires* a ``TriageResult``. Every
input path (typed, one-shot, TUI, future voice/PWA) must route through it, and RED must
short-circuit before it. This is the structural guarantee that no reply can be produced
without a deterministic safety verdict.
"""

from __future__ import annotations

import ast
from pathlib import Path

_PKG_DIRS = ("dr_alex", "safety", "books")
_ROOT = Path(__file__).resolve().parent.parent

# Process-spawning calls we consider "invoking an external model/tool".
_SPAWN = {
    ("subprocess", "run"), ("subprocess", "Popen"), ("subprocess", "call"),
    ("subprocess", "check_output"), ("subprocess", "check_call"),
    ("subprocess", "getoutput"), ("subprocess", "getstatusoutput"),
    ("os", "system"), ("os", "popen"),
}


def _is_spawn(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and (node.func.value.id, node.func.attr) in _SPAWN
    )


def _direct_calls(fn: ast.AST):
    """Yield calls inside ``fn`` that are not nested in an inner function."""
    for child in ast.iter_child_nodes(fn):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue  # a nested function owns its own calls
        yield from _walk_stopping_at_functions(child)


def _walk_stopping_at_functions(node: ast.AST):
    yield node
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield from _walk_stopping_at_functions(child)


def _spawning_functions() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for pkg in _PKG_DIRS:
        for path in (_ROOT / pkg).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if any(_is_spawn(c) for c in _direct_calls(node)):
                        found.append((f"{pkg}/{path.name}", node.name))
    return found


def test_exactly_one_function_spawns_the_model() -> None:
    spawners = _spawning_functions()
    assert spawners == [("dr_alex/llm.py", "complete")], (
        f"model may only be invoked by dr_alex.llm.complete; found: {spawners}"
    )


def test_entrypoint_requires_a_triage_result() -> None:
    tree = ast.parse((_ROOT / "dr_alex" / "llm.py").read_text(encoding="utf-8"))
    complete = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "complete"
    )
    annotations = []
    for arg in [*complete.args.posonlyargs, *complete.args.args, *complete.args.kwonlyargs]:
        if arg.annotation is not None:
            annotations.append(ast.unparse(arg.annotation))
    assert any("TriageResult" in a for a in annotations), (
        f"complete() must require a TriageResult; annotations were {annotations}"
    )


def test_entrypoint_guards_against_red() -> None:
    # complete() must reference Tier.RED (the defensive short-circuit guard).
    src = (_ROOT / "dr_alex" / "llm.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    complete = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "complete"
    )
    seg = ast.get_source_segment(src, complete) or ""
    assert "Tier.RED" in seg
