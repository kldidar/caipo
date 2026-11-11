"""The tested rules of the interface text style guide (docs/INTERFACE_TEXT.md, P-14).

Every template and every string marked for translation in the application is
read. A sentence that uses a word of cause or of non-existence must deny it:
CAIPO never states that something caused an outcome, and never presents an
empty result as proof that something does not exist.
"""

import ast
import re
from collections.abc import Iterator
from pathlib import Path

APPLICATION = Path(__file__).resolve().parents[2]
TEMPLATES = APPLICATION / "web" / "templates"
TRANSLATING = {"_", "gettext", "gettext_lazy", "ngettext", "ngettext_lazy", "pgettext"}

CAUSE = re.compile(
    r"\b(caus(e|es|ed|ing|al)|effects?|impacts?|led to|due to|thanks to|as a result|"
    r"drove|driven by|boost(s|ed)?|contributed to|attributable)\b",
    re.IGNORECASE,
)
# "Takes effect" is about when a change applies, not about an outcome.
NOT_CAUSE = re.compile(r"\btakes? effect\b", re.IGNORECASE)
NON_EXISTENCE = re.compile(r"\b(does not exist|do not exist|no [a-z ]{1,40} exists?)\b", re.I)
DENIAL = re.compile(r"\b(not|no|never|nor|cannot|neither|without)\b", re.IGNORECASE)
SENTENCE = re.compile(r"[^.!?;]+")


def _template_text(source: str) -> str:
    """The words a template shows: its translated strings and its literal text."""
    text = re.sub(r"\{%\s*(?:translate|trans)\s+(['\"])(.*?)\1[^%]*%\}", r" \2 ", source)
    text = re.sub(r"\{%\s*(?:end)?blocktrans(?:late)?[^%]*%\}", " ", text)
    text = re.sub(r"\{%.*?%\}|\{\{.*?\}\}|\{#.*?#\}", " ", text, flags=re.DOTALL)
    return re.sub(r"<[^>]+>", " ", text)


def _translated_strings(path: Path) -> Iterator[str]:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in TRANSLATING
        ):
            for argument in node.args:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    yield argument.value


def _texts() -> Iterator[tuple[str, str]]:
    for path in sorted(TEMPLATES.rglob("*.html")):
        yield str(path.relative_to(APPLICATION)), _template_text(path.read_text(encoding="utf-8"))
    for path in sorted(APPLICATION.rglob("*.py")):
        parts = path.relative_to(APPLICATION).parts
        if "tests" in parts or "migrations" in parts:
            continue
        for text in _translated_strings(path):
            yield str(path.relative_to(APPLICATION)), text


def _undenied(pattern: re.Pattern[str]) -> list[str]:
    found = []
    for where, text in _texts():
        for sentence in SENTENCE.findall(" ".join(text.split())):
            claim = NOT_CAUSE.sub(" ", sentence)
            if pattern.search(claim) and not DENIAL.search(claim):
                found.append(f"{where}: {sentence.strip()}")
    return found


def test_the_scan_reads_templates_and_translated_strings() -> None:
    texts = list(_texts())

    assert any(where.endswith(".html") for where, _ in texts)
    assert any(where.endswith(".py") for where, _ in texts)
    assert any("Not a causal analysis" in text for _, text in texts)


def test_a_word_of_cause_appears_only_in_a_sentence_that_denies_it() -> None:
    assert _undenied(CAUSE) == []


def test_a_word_of_non_existence_appears_only_in_a_sentence_that_denies_it() -> None:
    assert _undenied(NON_EXISTENCE) == []


def test_the_rules_catch_what_they_are_for() -> None:
    """The patterns find a claim and let its denial pass."""
    claim = "The strategy led to higher exports"
    denial = "They do not show that any policy caused any change"

    assert CAUSE.search(claim) and not DENIAL.search(claim)
    assert CAUSE.search(denial) and DENIAL.search(denial)
    assert NON_EXISTENCE.search("No such policy exists")
    assert not CAUSE.search(NOT_CAUSE.sub(" ", "It takes effect on the next request"))
