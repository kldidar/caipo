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
from caipo.registry.models import Country, Language

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
