"""The help corpus and the configuration of retrieval, read from the repository (ADR-0025)."""

from pathlib import Path

import pytest

from caipo.retrieval import config
from caipo.retrieval.corpus import HelpCorpusError, help_pages, parse_page, search_text

PAGE = (
    "# TEST Page\n\n## First section\nOne line.\nA second line.\n\nA paragraph.\n\n"
    "## Second\nMore.\n"
)


def test_a_page_is_read_into_its_sections() -> None:
    page = parse_page("test-page", PAGE)

    assert (page.page, page.title) == ("test-page", "TEST Page")
    assert [(s.anchor, s.heading, s.text) for s in page.sections] == [
        ("first-section", "First section", "One line.\n\nA second line.\n\nA paragraph."),
        ("second", "Second", "More."),
    ]


@pytest.mark.parametrize(
    ("name", "source", "message"),
    [
        ("Bad_Name", PAGE, "lower-case"),
        ("page", "No title\n## A\nText.", "starts with"),
        ("page", "# T\nText before.\n## A\nText.", "before the first section"),
        ("page", "# T\n## A\n\n## B\nText.", "is empty"),
        ("page", "# T\n## A\nText.\n## A\nMore.", "its own heading"),
        ("page", "# T\n## A\nText.\n### Deeper\nMore.", "only '# ' and '## '"),
        ("page", "# T\n", "at least one section"),
    ],
)
def test_a_page_not_in_the_expected_form_is_refused(name: str, source: str, message: str) -> None:
    with pytest.raises(HelpCorpusError, match=message):
        parse_page(name, source)


def test_every_help_page_of_the_repository_is_in_the_expected_form() -> None:
    pages = help_pages()

    assert {page.page for page in pages} >= {"about", "assistant", "analysis", "policies"}
    for page in pages:
        assert page.title and page.sections


def test_the_search_text_is_derived_and_the_original_is_not_touched() -> None:
    original = "  TEST Ａnalysis and\tEXPORT  "

    derived = search_text(original, ("nfkc", "casefold", "collapse_whitespace"))

    assert derived == "test analysis and export"
    assert original == "  TEST Ａnalysis and\tEXPORT  "


def test_an_unknown_transformation_is_refused() -> None:
    with pytest.raises(ValueError, match="Unknown"):
        search_text("TEST", ("stem",))


def test_the_configuration_of_the_repository_is_valid() -> None:
    configuration = config.load()

    assert configuration.version
    assert configuration.transformations == ("nfkc", "casefold", "collapse_whitespace")
    assert configuration.candidates_per_retriever > 0 and configuration.rrf_k > 0


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (('unit = "segment"', 'unit = "page"'), "unit"),
        (('"casefold"', '"stem"'), "transformations"),
        (('text_search_config = "english"', 'text_search_config = "russian"'), "English"),
    ],
)
def test_a_configuration_naming_what_the_code_does_not_do_is_refused(
    tmp_path: Path, change: tuple[str, str], message: str
) -> None:
    path = tmp_path / "chunking.toml"
    path.write_text(config.PATH.read_text(encoding="utf-8").replace(*change), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        config.load(path)
