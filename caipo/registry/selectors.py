"""Read interface of the registry: the countries and languages the system knows
(ADR-0018 point 13, ADR-0019 Increment 2).

Every read requires `REGISTRY_READ`, whatever the caller has checked. A
deactivated record is returned like any other: it stays readable. What is
returned is a plain value and never a model, and a record is named in it by
its public identifier and never by its internal key.
"""

import uuid
from dataclasses import dataclass

from caipo.accounts import selectors as accounts_selectors
from caipo.accounts.selectors import AuthenticationContext, Permission
from caipo.registry.models import Country, Language

__all__ = ["CountryEntry", "LanguageEntry", "countries", "languages"]


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
