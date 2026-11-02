"""The reasons the demonstrator's services give for a refusal are marked for translation.

CLAUDE.md requires every user-facing string to be marked for translation.
A refusal's reason is shown on the page that was refused, so each message
passes through gettext, with named placeholders rather than f-strings, which
gettext cannot translate, and the names of fields are translated too.
"""

import ast
from pathlib import Path

import pytest

from caipo.core.entry import InvalidEntryError, clean_address, clean_text

APPLICATION = Path(__file__).resolve().parents[2]
MODULES = [
    "core/entry.py",
    "sources/services.py",
    "policies/services.py",
    "indicators/services.py",
    "research/services.py",
    "research/inputs.py",
    "web/sources.py",
    "web/policies.py",
    "web/research.py",
]


def _is_gettext(node: ast.expr) -> bool:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        node = node.left
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_"


def _refusals(tree: ast.AST) -> list[ast.Call]:
    return [
        node.exc
        for node in ast.walk(tree)
        if isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call)
        and isinstance(node.exc.func, ast.Name)
        and node.exc.func.id.endswith("Error")
        and node.exc.args
    ]


@pytest.mark.parametrize("module", MODULES)
def test_every_refusal_reason_passes_through_gettext(module: str) -> None:
    tree = ast.parse((APPLICATION / module).read_text(encoding="utf-8"))

    untranslated = [
        f"{module}:{call.lineno}" for call in _refusals(tree) if not _is_gettext(call.args[0])
    ]
    with_fstrings = [
        f"{module}:{node.lineno}"
        for call in _refusals(tree)
        for node in ast.walk(call)
        if isinstance(node, ast.JoinedStr)
    ]

    assert untranslated == []
    assert with_fstrings == []


@pytest.mark.parametrize("module", MODULES)
def test_every_field_named_in_a_reason_is_translated(module: str) -> None:
    tree = ast.parse((APPLICATION / module).read_text(encoding="utf-8"))

    untranslated = [
        f"{module}:{node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.keyword)
        and node.arg == "field"
        and isinstance(node.value, ast.Constant)
    ]

    assert untranslated == []


def test_a_reason_names_its_field_and_limit() -> None:
    with pytest.raises(InvalidEntryError, match=r"^The title is at most 5 characters\.$"):
        clean_text("TEST too long", field="title", max_length=5)
    with pytest.raises(InvalidEntryError, match=r"^The address is an http or https address\.$"):
        clean_address("javascript:alert(1)", field="address", max_length=100)
