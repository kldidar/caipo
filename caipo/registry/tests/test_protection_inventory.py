"""The database triggers that protect the records of ADR-0018, as one inventory.

Each migration test looks at the tables of its own app. This looks at the
whole database once, so that a protection of ADR-0018 that disappeared, sat
on another table, or appeared where none is expected fails here whichever
app's migration did it.

It is not an inventory of every trigger. The triggers of the event tables of
ADR-0012 are another decision's and are tested with the migrations that
create them, and the triggers PostgreSQL keeps for its own constraints are
not read at all.
"""

import pytest
from django.db import connection

pytestmark = [pytest.mark.services, pytest.mark.django_db]

# Table, trigger, function, and whether the trigger fires ("O": enabled, for
# every session that is not a replica).
AUDIT_PROTECTIONS = {
    (
        "accounts_auditevent",
        "accounts_auditevent_append_only",
        "accounts_auditevent_refuse_change",
        "O",
    ),
    (
        "accounts_auditeventchange",
        "accounts_auditeventchange_append_only",
        "accounts_auditeventchange_refuse_change",
        "O",
    ),
}
REGISTRY_PROTECTIONS = {
    ("registry_country", "registry_country_protect", "registry_country_refuse_change", "O"),
    ("registry_language", "registry_language_protect", "registry_language_refuse_change", "O"),
}
EXPECTED = AUDIT_PROTECTIONS | REGISTRY_PROTECTIONS
# Institution and InstitutionName are Increment 3's (ADR-0019 point 3). Until
# then neither table exists, and so neither has a protection. Increment 3
# moves them from here into the inventory above.
DEFERRED_TABLES = {"registry_institution", "registry_institutionname"}

GOVERNED_TABLES = {table for table, _, _, _ in EXPECTED} | DEFERRED_TABLES
TRIGGERS = {trigger for _, trigger, _, _ in EXPECTED}
FUNCTIONS = {function for _, _, function, _ in EXPECTED}


def _triggers() -> set[tuple[str, str, str, str]]:
    """Return every trigger that is not PostgreSQL's own: table, name, function, enabled."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgrelid::regclass::text, tgname, tgfoid::regproc::text, tgenabled"
            " FROM pg_trigger WHERE NOT tgisinternal"
        )
        return {
            (str(table), str(name), str(function), str(enabled))
            for table, name, function, enabled in cursor.fetchall()
        }


def _is_of_adr_0018(table: str, trigger: str, function: str) -> bool:
    """Say whether a trigger is one of ADR-0018's, by any of the ways it could be.

    It is on a table the decision governs, or on any table of the registry;
    or it has the name, or runs the function, of one of the protections. A
    protection put on the wrong table is therefore still found, by its name
    or its function, and compared with the inventory.
    """
    return (
        table in GOVERNED_TABLES
        or table.startswith("registry_")
        or trigger in TRIGGERS
        or function in FUNCTIONS
        or function.startswith("registry_")
    )


def test_the_protections_of_adr_0018_are_exactly_these_on_exactly_these_tables() -> None:
    found = {
        (table, trigger, function, enabled)
        for table, trigger, function, enabled in _triggers()
        if _is_of_adr_0018(table, trigger, function)
    }

    assert found == EXPECTED
    # What is deferred is absent, and not merely unprotected.
    assert DEFERRED_TABLES.isdisjoint(connection.introspection.table_names())
