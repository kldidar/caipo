"""The help corpus, and the search-side transformation of text (ADR-0025 points 3 and 5).

The help corpus is the pages under `help/`, versioned in the repository: one
Markdown file per page, a `# ` title, and `## ` sections of plain paragraphs.
It is CAIPO's own text about itself. It is shown on the site and is what the
help assistant answers from.
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from django.utils.text import slugify

HELP_DIRECTORY = Path(__file__).with_name("help")
_PAGE_NAME = re.compile(r"^[a-z][a-z-]*$")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class HelpSection:
    page: str
    page_title: str
    anchor: str
    heading: str
    text: str


@dataclass(frozen=True)
class HelpPage:
    page: str
    title: str
    sections: tuple[HelpSection, ...]


class HelpCorpusError(ValueError):
    """A help page is not in the expected form."""


def parse_page(page: str, source: str) -> HelpPage:
    """Read one help page. Raises HelpCorpusError if it is not in the expected form."""
    if not _PAGE_NAME.match(page):
        raise HelpCorpusError(f"{page}: a page name is lower-case letters and hyphens")
    lines = unicodedata.normalize("NFC", source).splitlines()
    if not lines or not lines[0].startswith("# "):
        raise HelpCorpusError(f"{page}: a page starts with its '# ' title")
    title = lines[0][2:].strip()
    sections: list[HelpSection] = []
    heading: str | None = None
    paragraphs: list[str] = []

    def close() -> None:
        if heading is None:
            return
        text = "\n\n".join(paragraphs).strip()
        if not text:
            raise HelpCorpusError(f"{page}: section '{heading}' is empty")
        sections.append(HelpSection(page, title, slugify(heading), heading, text))

    for line in lines[1:]:
        if line.startswith("## "):
            close()
            heading, paragraphs = line[3:].strip(), []
        elif line.startswith("#"):
            raise HelpCorpusError(f"{page}: only '# ' and '## ' headings are used")
        elif heading is None and line.strip():
            raise HelpCorpusError(f"{page}: text before the first section")
        elif line.strip():
            paragraphs.append(line.strip())
    close()
    if not title or not sections:
        raise HelpCorpusError(f"{page}: a page has a title and at least one section")
    anchors = [section.anchor for section in sections]
    if len(anchors) != len(set(anchors)) or not all(anchors):
        raise HelpCorpusError(f"{page}: each section has its own heading")
    return HelpPage(page, title, tuple(sections))


def help_pages(directory: Path = HELP_DIRECTORY) -> tuple[HelpPage, ...]:
    """Every help page, in the order of their names."""
    return tuple(
        parse_page(path.stem, path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.md"))
    )


def search_text(text: str, transformations: Iterable[str]) -> str:
    """The derived search text of a text, by the configured transformations, in order.

    Never applied to a Segment: its result is stored only on a RetrievalChunk.
    """
    for name in transformations:
        if name == "nfkc":
            text = unicodedata.normalize("NFKC", text)
        elif name == "casefold":
            text = text.casefold()
        elif name == "collapse_whitespace":
            text = _WHITESPACE.sub(" ", text).strip()
        else:
            raise ValueError(f"Unknown search-side transformation: {name}")
    return text
