"""What the registry tests share: synthetic records, and reading what a service left behind.

The accounts these tests act as come from the `acting_as` fixture, which the
conftest.py at the repository root registers for the whole suite. Nothing
here imports the tests of another app, and from `caipo.accounts.models` only
the two audit models are imported, to read what a registry service recorded
(ADR-0019 points 26 and 27). No test creates an audit record through them.
"""

import uuid
from collections.abc import Callable
from typing import Any

from caipo.accounts.models import AuditEvent, AuditEventChange
from caipo.accounts.selectors import AuthenticationContext
from caipo.registry import services
from caipo.registry.models import Country, Institution, InstitutionName, Language
from caipo.registry.services import NewName

type ActingAs = Callable[..., AuthenticationContext]

# Visibly synthetic. The codes are from the ranges that ISO 3166, ISO 639-3,
# and ISO 15924 reserve for private use, so none names a real country,
# language, or script.
COUNTRIES = [
    ("XA", "XAA", "TEST Country A"),
    ("XB", "XBB", "TEST Country B"),
    ("QM", "QMA", "TEST Country C"),
]
LANGUAGES = [
    ("qaa", "Qaaa", "TEST Language A"),
    ("qaa", "Qaab", "TEST Language A in another script"),
    ("qab", "Qaaa", "TEST Language B"),
]
# The identifier of no record.
UNKNOWN = uuid.UUID("00000000-0000-4000-8000-00000000ffff")


def stored() -> dict[str, list[Any]]:
    """Return everything the registry and the audit record hold, to compare before and after."""
    return {
        "countries": list(Country.objects.order_by("id").values()),
        "languages": list(Language.objects.order_by("id").values()),
        "events": list(AuditEvent.objects.order_by("id").values()),
        "changes": list(AuditEventChange.objects.order_by("id").values()),
    }


def events() -> list[tuple[str, str, uuid.UUID, int]]:
    """Return each audit event as its action, target type, target, and actor, oldest first."""
    return list(
        AuditEvent.objects.order_by("id").values_list(
            "action", "target_type", "target_public_id", "actor_id"
        )
    )


def changes() -> list[tuple[int, str, str, str]]:
    """Return each change record as its event, field, old value, and new value, oldest first."""
    return list(
        AuditEventChange.objects.order_by("id").values_list(
            "event_id", "field", "old_value", "new_value"
        )
    )


def stored_with_institutions() -> dict[str, list[Any]]:
    """Return what `stored` returns, and every institution and name as well."""
    return {
        **stored(),
        "institutions": list(Institution.objects.order_by("id").values()),
        "names": list(InstitutionName.objects.order_by("id").values()),
    }


def reference_records(actor: AuthenticationContext) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """Create the three synthetic countries and languages, and return their identifiers."""
    countries = [
        services.create_country(actor=actor, alpha2=alpha2, alpha3=alpha3, name_en=name_en)
        for alpha2, alpha3, name_en in COUNTRIES
    ]
    languages = [
        services.create_language(actor=actor, code=code, script_code=script, name_en=name_en)
        for code, script, name_en in LANGUAGES
    ]
    return countries, languages


def institution(
    actor: AuthenticationContext,
    language: uuid.UUID,
    text: str = "TEST Institution",
    **attributes: Any,
) -> uuid.UUID:
    """Create an institution with one official name and return its identifier: a ministry unless
    told otherwise."""
    return services.create_institution(
        actor=actor,
        **{"kind": "ministry", **attributes},
        first_name=NewName(text=text, language=language, kind="official"),
    )


def names_of(public_id: uuid.UUID) -> list[uuid.UUID]:
    """Return the identifiers of an institution's names, in the order they were entered."""
    return list(
        InstitutionName.objects.filter(institution__public_id=public_id)
        .order_by("id")
        .values_list("public_id", flat=True)
    )
