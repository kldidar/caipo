"""Read interface of the registry: the countries, languages, and institutions with their
names that the system knows (ADR-0018 point 13, ADR-0019 Increments 2 and 3).

Every read requires `REGISTRY_READ`, whatever the caller has checked. A
deactivated record is returned like any other: it stays readable. What is
returned is a plain value and never a model, and a record is named in it by
its public identifier and never by its internal key.
"""

import uuid
from dataclasses import dataclass, replace
from datetime import date

from caipo.accounts import selectors as accounts_selectors
from caipo.accounts.selectors import AuthenticationContext, Permission
from caipo.registry.models import (
    Country,
    Institution,
    InstitutionKind,
    InstitutionName,
    InstitutionNameKind,
    Language,
)

__all__ = [
    "CountryEntry",
    "InstitutionEntry",
    "InstitutionKind",
    "InstitutionNameEntry",
    "InstitutionNameKind",
    "InstitutionReference",
    "LanguageEntry",
    "countries",
    "institutions",
    "languages",
]


@dataclass(frozen=True)
class CountryEntry:
    """A country, as a reader of the registry is shown it."""

    public_id: uuid.UUID
    alpha2: str
    alpha3: str
    name_en: str
    is_active: bool


@dataclass(frozen=True)
class LanguageEntry:
    """A language in a script, as a reader of the registry is shown it."""

    public_id: uuid.UUID
    code: str
    script_code: str
    name_en: str
    is_active: bool


def countries(context: AuthenticationContext | None) -> list[CountryEntry]:
    """Return every country, active or not, ordered by alpha-2 code.

    Reads only. Raises PermissionDenied if the context may not read the
    registry.
    """
    accounts_selectors.require_permission(context, Permission.REGISTRY_READ)
    return [
        CountryEntry(public_id, alpha2, alpha3, name_en, is_active)
        for public_id, alpha2, alpha3, name_en, is_active in Country.objects.order_by(
            "alpha2"
        ).values_list("public_id", "alpha2", "alpha3", "name_en", "is_active")
    ]


def languages(context: AuthenticationContext | None) -> list[LanguageEntry]:
    """Return every language, active or not, ordered by language code and script code.

    Reads only. Raises PermissionDenied if the context may not read the
    registry.
    """
    accounts_selectors.require_permission(context, Permission.REGISTRY_READ)
    return [
        LanguageEntry(public_id, code, script_code, name_en, is_active)
        for public_id, code, script_code, name_en, is_active in Language.objects.order_by(
            "code", "script_code"
        ).values_list("public_id", "code", "script_code", "name_en", "is_active")
    ]


@dataclass(frozen=True)
class InstitutionNameEntry:
    """A name of an institution, as a reader of the registry is shown it.

    The language is shown by its two codes. A name marked as entered in
    error is shown as such, and is not a name of its institution.
    """

    public_id: uuid.UUID
    text: str
    language: uuid.UUID
    language_code: str
    script_code: str
    kind: str
    valid_from: date | None
    valid_to: date | None
    entered_in_error: bool

    @property
    def kind_label(self) -> str:
        return str(InstitutionNameKind(self.kind).label)


@dataclass(frozen=True)
class InstitutionReference:
    """Another institution, as one institution refers to it: by identifier and by its label."""

    public_id: uuid.UUID
    label: str


@dataclass(frozen=True)
class InstitutionEntry:
    """An institution with every name it has been given, as a reader of the registry is shown it.

    The country is shown by its alpha-2 code, and an empty date or reference
    is None. `names` are its names in the order they were entered, and
    `names_entered_in_error` those marked as entered in error, which are not
    its names.
    """

    public_id: uuid.UUID
    kind: str
    country: uuid.UUID | None
    country_alpha2: str | None
    parent: InstitutionReference | None
    successor: InstitutionReference | None
    valid_from: date | None
    valid_to: date | None
    names: tuple[InstitutionNameEntry, ...]
    names_entered_in_error: tuple[InstitutionNameEntry, ...]

    @property
    def kind_label(self) -> str:
        return str(InstitutionKind(self.kind).label)

    @property
    def label(self) -> str:
        """The first of its names, which is how another institution refers to it.

        Its public identifier if it has no name: the services never leave an
        institution so, and only a change made past them could.
        """
        return self.names[0].text if self.names else str(self.public_id)


def institutions(context: AuthenticationContext | None) -> list[InstitutionEntry]:
    """Return every institution with all of its names, in the order they were entered.

    Reads only. Raises PermissionDenied if the context may not read the
    registry.
    """
    accounts_selectors.require_permission(context, Permission.REGISTRY_READ)
    # Institutions first, then names. An institution and its first name are
    # committed together, so every institution read here has its names in the
    # second read; a name of one created in between is passed over.
    rows = list(
        Institution.objects.order_by("id").values(
            "id",
            "public_id",
            "kind",
            "country__public_id",
            "country__alpha2",
            "parent_id",
            "successor_id",
            "valid_from",
            "valid_to",
        )
    )
    names: dict[int, list[InstitutionNameEntry]] = {row["id"]: [] for row in rows}
    for row in (
        InstitutionName.objects.filter(institution_id__in=names)
        .order_by("id")
        .values(
            "institution_id",
            "public_id",
            "text",
            "language__public_id",
            "language__code",
            "language__script_code",
            "kind",
            "valid_from",
            "valid_to",
            "entered_in_error",
        )
    ):
        names[row["institution_id"]].append(
            InstitutionNameEntry(
                public_id=row["public_id"],
                text=row["text"],
                language=row["language__public_id"],
                language_code=row["language__code"],
                script_code=row["language__script_code"],
                kind=row["kind"],
                valid_from=row["valid_from"],
                valid_to=row["valid_to"],
                entered_in_error=row["entered_in_error"],
            )
        )
    entries = {
        row["id"]: InstitutionEntry(
            public_id=row["public_id"],
            kind=row["kind"],
            country=row["country__public_id"],
            country_alpha2=row["country__alpha2"],
            parent=None,
            successor=None,
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            names=tuple(name for name in names[row["id"]] if not name.entered_in_error),
            names_entered_in_error=tuple(
                name for name in names[row["id"]] if name.entered_in_error
            ),
        )
        for row in rows
    }

    def reference(key: int | None) -> InstitutionReference | None:
        if key is None or key not in entries:
            return None
        return InstitutionReference(entries[key].public_id, entries[key].label)

    return [
        replace(
            entries[row["id"]],
            parent=reference(row["parent_id"]),
            successor=reference(row["successor_id"]),
        )
        for row in rows
    ]
