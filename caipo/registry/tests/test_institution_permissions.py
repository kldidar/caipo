"""Who may read and maintain institutions and their names (ADR-0018 points 11 to 14,
testing requirement 1; ADR-0019 Increment 3).

Each Institution and InstitutionName operation of the write matrix, and the
read of those records, for each of the four roles, for an anonymous context,
for a disabled account, and for an Administrator and a Reviewer on a
password alone. A refusal writes nothing. The accounts are those of
test_permissions.py, so that both kinds of record are tested against the
same table of who acts.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied

from caipo.accounts.selectors import AuthenticationContext, Role
from caipo.registry import selectors, services
from caipo.registry.services import NewName
from caipo.registry.tests.helpers import (
    UNKNOWN,
    ActingAs,
    events,
    institution,
    names_of,
    stored_with_institutions,
)
from caipo.registry.tests.test_permissions import ACTORS, MAY_ENTER, MAY_READ

pytestmark = [pytest.mark.services, pytest.mark.django_db]


@dataclass(frozen=True)
class Records:
    """A country, a language, and an institution with two names, for the operations to act on."""

    country: uuid.UUID
    language: uuid.UUID
    institution: uuid.UUID
    name: uuid.UUID
    other_name: uuid.UUID


@pytest.fixture
def records(administrator: AuthenticationContext) -> Records:
    country = services.create_country(
        actor=administrator, alpha2="XA", alpha3="XAA", name_en="TEST Country A"
    )
    language = services.create_language(
        actor=administrator, code="qaa", script_code="Qaaa", name_en="TEST Language A"
    )
    public_id = institution(administrator, language, country=country)
    services.add_institution_name(
        actor=administrator,
        institution=public_id,
        name=NewName(text="TEST Second name", language=language, kind="abbreviation"),
    )
    name, other_name = names_of(public_id)
    return Records(country, language, public_id, name, other_name)


type Operation = Callable[[Any, Records], object]

# The five Institution and InstitutionName rows of the write matrix.
WRITES: dict[str, Operation] = {
    "create_institution": lambda actor, records: services.create_institution(
        actor=actor,
        kind="university",
        country=records.country,
        parent=records.institution,
        first_name=NewName(text="TEST University", language=records.language, kind="official"),
    ),
    "change_institution": lambda actor, records: services.change_institution(
        actor=actor,
        public_id=records.institution,
        kind="regulator",
        country=None,
        parent=None,
        successor=None,
        valid_from=None,
        valid_to=None,
    ),
    "add_institution_name": lambda actor, records: services.add_institution_name(
        actor=actor,
        institution=records.institution,
        name=NewName(text="TEST Third name", language=records.language, kind="official"),
    ),
    "change_institution_name_dates": lambda actor, records: services.change_institution_name_dates(
        actor=actor, public_id=records.other_name, valid_from=None, valid_to=date(2001, 2, 3)
    ),
    "mark_institution_name_entered_in_error": lambda actor, records: (
        services.mark_institution_name_entered_in_error(actor=actor, public_id=records.name)
    ),
}
# How many audit events each writes.
EVENTS_WRITTEN = {
    "create_institution": 2,
    "change_institution": 1,
    "add_institution_name": 1,
    "change_institution_name_dates": 1,
    "mark_institution_name_entered_in_error": 1,
}
# Written out here, not read from the policy: ADR-0018 points 11 to 14. Every
# account that holds `registry.institutions.manage` writes institutions.
MAY_MAINTAIN = MAY_ENTER


def _context(acting_as: ActingAs, actor: str) -> AuthenticationContext | None:
    described = ACTORS[actor]
    if described is None:
        return None
    roles, how = described
    return acting_as(*roles, **how)


def test_the_accounts_that_maintain_institutions_are_those_of_adr_0018() -> None:
    """Researcher on a password, Reviewer and Administrator verified, and no Reader."""
    assert MAY_MAINTAIN == {
        "researcher",
        "researcher-verified",
        "reviewer-verified",
        "administrator-verified",
        "researcher-and-reviewer-on-a-password",
        "every-role-but-administrator-verified",
        "every-role-on-a-password",
    }


@pytest.mark.parametrize("operation", WRITES)
@pytest.mark.parametrize("actor", sorted(set(ACTORS) - MAY_MAINTAIN))
def test_a_write_is_refused_to_every_account_that_does_not_maintain_institutions(
    acting_as: ActingAs, records: Records, operation: str, actor: str
) -> None:
    context = _context(acting_as, actor)
    before = stored_with_institutions()

    with pytest.raises(PermissionDenied):
        WRITES[operation](context, records)

    assert stored_with_institutions() == before


@pytest.mark.parametrize("operation", WRITES)
@pytest.mark.parametrize("actor", sorted(MAY_MAINTAIN))
def test_a_write_is_allowed_to_every_account_that_maintains_institutions_and_is_theirs(
    acting_as: ActingAs, records: Records, operation: str, actor: str
) -> None:
    context = _context(acting_as, actor)
    assert context is not None
    recorded_before = len(events())

    WRITES[operation](context, records)

    written = events()[recorded_before:]
    assert len(written) == EVENTS_WRITTEN[operation]
    assert {event[3] for event in written} == {context.user.pk}


@pytest.mark.parametrize("actor", sorted(ACTORS))
def test_the_read_of_institutions_is_allowed_exactly_to_the_accounts_that_read_the_registry(
    acting_as: ActingAs, records: Records, actor: str
) -> None:
    context = _context(acting_as, actor)
    before = stored_with_institutions()

    if actor in MAY_READ:
        (entry,) = selectors.institutions(context)
        assert entry.public_id == records.institution and len(entry.names) == 2
    else:
        with pytest.raises(PermissionDenied):
            selectors.institutions(context)

    assert stored_with_institutions() == before


# --- The permission comes first -----------------------------------------------

NOTHING = NewName(text="", language=UNKNOWN, kind="")

REFUSED_FIRST: dict[str, Callable[[Any], object]] = {
    "create an institution that is not valid": lambda actor: services.create_institution(
        actor=actor, kind="", country=UNKNOWN, first_name=NOTHING
    ),
    "change an institution that does not exist": lambda actor: services.change_institution(
        actor=actor,
        public_id=UNKNOWN,
        kind="",
        country=None,
        parent=None,
        successor=None,
        valid_from=None,
        valid_to=None,
    ),
    "add a name to an institution that does not exist": lambda actor: services.add_institution_name(
        actor=actor, institution=UNKNOWN, name=NOTHING
    ),
    "change the dates of a name that does not exist": lambda actor: (
        services.change_institution_name_dates(
            actor=actor, public_id=UNKNOWN, valid_from=None, valid_to=None
        )
    ),
    "mark a name that does not exist": lambda actor: (
        services.mark_institution_name_entered_in_error(actor=actor, public_id=UNKNOWN)
    ),
}


@pytest.mark.parametrize("request_made", REFUSED_FIRST)
@pytest.mark.parametrize(
    "actor",
    ["reader", "reviewer-on-a-password", "administrator-on-a-password", "anonymous"],
)
def test_an_account_without_the_permission_learns_nothing_about_a_record_or_its_input(
    acting_as: ActingAs, request_made: str, actor: str
) -> None:
    """Refused as it would be for a record that exists and input that is valid."""
    with pytest.raises(PermissionDenied):
        REFUSED_FIRST[request_made](_context(acting_as, actor))


def test_a_refused_write_is_logged_as_a_refused_permission(
    acting_as: ActingAs, records: Records, caplog: pytest.LogCaptureFixture
) -> None:
    reader = acting_as(Role.READER)
    caplog.clear()

    with pytest.raises(PermissionDenied):
        WRITES["mark_institution_name_entered_in_error"](reader, records)

    (record,) = [record for record in caplog.records if record.name == "caipo.accounts.selectors"]
    assert record.__dict__["event"] == "authorization.denied"
    assert record.__dict__["permission"] == "registry.institutions.manage"
    assert record.__dict__["user_id"] == reader.user.pk
    assert [record for record in caplog.records if record.name == "caipo.registry.services"] == []


def test_the_reference_permission_is_not_needed_and_does_not_suffice(
    acting_as: ActingAs, records: Records
) -> None:
    """A Researcher, who cannot change a country, maintains institutions (ADR-0018 point 13)."""
    researcher = acting_as(Role.RESEARCHER)

    with pytest.raises(PermissionDenied):
        services.rename_country(actor=researcher, public_id=records.country, name_en="TEST")
    WRITES["change_institution"](researcher, records)

    assert events()[-1][:2] == ("updated", "registry.institution")
