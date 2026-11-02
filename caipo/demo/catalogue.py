"""What the demonstration environment holds (ADR-0020), read from `catalogue.json`.

The records are data, kept in that file and not in code. Two parts, never mixed:

- `demonstration`: synthetic records of two synthetic countries. Every title
  starts with DEMO. They show what the software does and say nothing about
  any real country.
- `reference`: real public documents of the two study countries, by their
  metadata only, each as found on the access date from the address given,
  with a provisional assignment and its reason.

No statistic, quotation, or date in the file was invented for a real country.
"""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

PATH = Path(__file__).with_name("catalogue.json")


@dataclass(frozen=True)
class SourceSpec:
    key: str
    data_class: str
    name: str
    publisher: str
    url: str
    tier: str
    permitted_use: str
    country: str | None
    licence: str
    licence_verified: bool
    coverage: str
    limitations: str


@dataclass(frozen=True)
class DocumentSpec:
    key: str
    source: str
    country: str
    document_type: str
    title: str
    language: tuple[str, str]
    title_en: str
    title_en_official: bool
    identifier: str
    issued: date | None
    url: str
    issuer: str | None
    notes: str


@dataclass(frozen=True)
class ProvisionSpec:
    provision_type: str
    document: str
    locator: str
    label: str
    quoted_text: str


@dataclass(frozen=True)
class PolicySpec:
    data_class: str
    country: str
    policy_type: str
    title: str
    language: tuple[str, str]
    corpus: str
    reason: str
    ai_focus: str
    category: str
    title_en: str
    lead: str | None
    summary: str
    documents: tuple[tuple[str, str], ...]
    events: tuple[tuple[str, date, str, str], ...]
    provisions: tuple[ProvisionSpec, ...]


@dataclass(frozen=True)
class Catalogue:
    accessed: date
    countries: tuple[tuple[str, str, str], ...]
    languages: tuple[tuple[str, str, str], ...]
    institutions: tuple[tuple[str, str, str, str], ...]
    sources: tuple[SourceSpec, ...]
    documents: tuple[DocumentSpec, ...]
    policies: tuple[PolicySpec, ...]

    @property
    def english(self) -> tuple[str, str]:
        """The language in which the demonstration records' titles are written."""
        code, script, _ = self.languages[0]
        return (code, script)


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _policy(item: dict[str, Any]) -> PolicySpec:
    return PolicySpec(
        data_class=item["data_class"],
        country=item["country"],
        policy_type=item["policy_type"],
        title=item["title"],
        language=(item["language"][0], item["language"][1]),
        corpus=item["corpus"],
        reason=item["reason"],
        ai_focus=item["ai_focus"],
        category=item["category"],
        title_en=item["title_en"],
        lead=item["lead"],
        summary=item["summary"],
        documents=tuple((document, role) for document, role in item["documents"]),
        events=tuple(
            (event_type, date.fromisoformat(effective), document, locator)
            for event_type, effective, document, locator in item["events"]
        ),
        provisions=tuple(ProvisionSpec(**provision) for provision in item["provisions"]),
    )


def load(path: Path = PATH) -> Catalogue:
    """Read the catalogue. Raises KeyError, TypeError, or ValueError if the file is malformed."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return Catalogue(
        accessed=date.fromisoformat(data["accessed"]),
        countries=tuple((a, b, c) for a, b, c in data["countries"]),
        languages=tuple((a, b, c) for a, b, c in data["languages"]),
        institutions=tuple((a, b, c, d) for a, b, c, d in data["institutions"]),
        sources=tuple(SourceSpec(**item) for item in data["sources"]),
        documents=tuple(
            DocumentSpec(
                **{**item, "language": tuple(item["language"]), "issued": _date(item["issued"])}
            )
            for item in data["documents"]
        ),
        policies=tuple(_policy(item) for item in data["policies"]),
    )
