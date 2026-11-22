"""The gold set and the adversarial corpus of the evaluation name only what is held (§9.2)."""

import json
from pathlib import Path

import pytest

from caipo.assistant.services import detect_language
from caipo.demo import evaluation
from caipo.demo.catalogue import load
from caipo.demo.evaluation import GoldSetError, load_adversarial, load_gold
from caipo.demo.worldbank import read_snapshot
from caipo.retrieval.corpus import help_pages

SEED = Path(evaluation.__file__).with_name("management") / "commands" / "seed_demo.py"
PROMPTS = Path(evaluation.__file__).parents[1] / "assistant" / "prompts"


def _passages() -> set[tuple[str, str]]:
    catalogue = load()
    titles = {spec.key: spec.title for spec in catalogue.documents}
    held = {
        (titles[key], locator) for key, parts in catalogue.texts.items() for locator, _ in parts
    }
    for document in load_adversarial().documents:
        held |= {(document.title, locator) for locator, _ in document.parts}
    return held


def test_each_case_is_asked_in_english_and_in_russian() -> None:
    cases = load_gold().cases

    by_pair: dict[str, set[str]] = {}
    for case in cases:
        by_pair.setdefault(case.pair, set()).add(case.language)
    assert all(languages == set(evaluation.LANGUAGES) for languages in by_pair.values())
    for case in cases:
        if case.refusal != "empty":
            assert detect_language(case.question) == case.language, case.id


def test_every_kind_of_case_is_in_the_gold_set_for_each_assistant_it_concerns() -> None:
    kinds = {(case.assistant, case.kind) for case in load_gold().cases}

    assert {kind for assistant, kind in kinds if assistant == "research"} == set(evaluation.KINDS)
    assert {kind for assistant, kind in kinds if assistant == "help"} == {
        "factual",
        "unanswerable",
        "injection",
        "causal",
    }


def test_every_expected_observation_is_held_with_the_status_its_kind_needs() -> None:
    held = {
        (row.indicator_code, row.country_alpha2, row.year): row.value
        for row in read_snapshot(frozenset()).rows
    }

    for case in load_gold().cases:
        for item in case.observations:
            assert item in held, case.id
            if case.kind == "missing":
                assert held[item] is None, case.id
            else:
                assert held[item] is not None, case.id


def test_every_expected_passage_is_held_under_its_locator() -> None:
    held = _passages()

    for case in load_gold().cases:
        for item in case.segments:
            assert item in held, case.id
        for line in case.script:
            assert (line.title, line.locator) in held, case.id


def test_every_expected_help_section_exists() -> None:
    sections = {(page.page, section.anchor) for page in help_pages() for section in page.sections}

    for case in load_gold().cases:
        assert set(case.help) <= sections, case.id


def test_every_planted_marker_is_in_the_hostile_text_the_question_or_the_instructions() -> None:
    hostile = " ".join(
        text for document in load_adversarial().documents for _, text in document.parts
    )
    # A phrase of the instructions is planted where an injection asks for them.
    instructions = " ".join(path.read_text(encoding="utf-8") for path in PROMPTS.glob("*.txt"))

    for case in load_gold().cases:
        where = f"{hostile} {case.question} {instructions}".casefold()
        for marker in case.planted:
            assert marker.casefold() in where, case.id
        for number in case.planted_numbers:
            assert str(number) in hostile, case.id


def test_the_adversarial_corpus_is_synthetic_and_never_seeded() -> None:
    corpus = load_adversarial()
    catalogue_titles = {spec.title for spec in load().documents}

    assert corpus.country == "XA"
    for document in corpus.documents:
        assert document.title.startswith("DEMO ")
        assert ".example/" in document.url
        assert document.title not in catalogue_titles
    assert "adversarial" not in SEED.read_text(encoding="utf-8")


def _write(tmp_path: Path, cases: list[dict[str, object]]) -> Path:
    path = tmp_path / "gold.json"
    path.write_text(json.dumps({"version": "TEST", "cases": cases}), encoding="utf-8")
    return path


QUESTION = {"assistant": "research", "english": "TEST question", "russian": "ТЕСТ вопрос"}


@pytest.mark.parametrize(
    "cases",
    [
        [{**QUESTION, "pair": "T1", "kind": "TEST"}],
        [{**QUESTION, "pair": "T1", "kind": "refusal"}],
        [{**QUESTION, "pair": "T1", "kind": "factual", "refusal": "empty"}],
        [{**QUESTION, "pair": "T1", "kind": "verifier"}],
        [{**QUESTION, "pair": "T1", "kind": "factual", "label": "TEST"}],
        [{**QUESTION, "pair": "T1", "kind": "factual", "assistant": "TEST"}],
        [{**QUESTION, "pair": "T1", "kind": "factual", "observations": [["TEST", 2020]]}],
        [
            {**QUESTION, "pair": "T1", "kind": "factual"},
            {**QUESTION, "pair": "T1", "kind": "causal"},
        ],
        [{"pair": "T1", "kind": "factual", "assistant": "research", "english": "TEST"}],
    ],
)
def test_a_malformed_gold_set_is_refused(tmp_path: Path, cases: list[dict[str, object]]) -> None:
    with pytest.raises(GoldSetError):
        load_gold(_write(tmp_path, cases))


def test_a_malformed_adversarial_corpus_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "adversarial.json"
    path.write_text(json.dumps({"version": "TEST", "documents": []}), encoding="utf-8")

    with pytest.raises(GoldSetError):
        load_adversarial(path)


def test_a_too_long_question_is_past_the_limit_after_the_guard_strips_it() -> None:
    case = next(case for case in load_gold().cases if case.refusal == "too_long")

    asked = evaluation.asked_question(case, 500)

    assert len(asked.strip()) > 500
