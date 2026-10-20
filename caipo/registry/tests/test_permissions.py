"""Who may read and write the registry (ADR-0018 points 11 to 14, testing requirement 1).

Each Country and Language operation of the write matrix, and the read, for
each of the four roles, for an anonymous context, for a disabled account, and
for an Administrator on a password alone. A refusal writes nothing.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied

from caipo.accounts import selectors as accounts_selectors
from caipo.accounts.selectors import AuthenticationContext, Permission, Role
from caipo.registry import selectors, services
from caipo.registry.models import Country, Language
from caipo.registry.tests.helpers import UNKNOWN, ActingAs, events, stored

pytestmark = [pytest.mark.services, pytest.mark.django_db]


@dataclass(frozen=True)
class Records:
    """An active and a deactivated record of each kind, for the operations to act on."""

    country: uuid.UUID
    deactivated_country: uuid.UUID
    language: uuid.UUID
    deactivated_language: uuid.UUID


@pytest.fixture
def records(administrator: AuthenticationContext) -> Records:
    country = services.create_country(
        actor=administrator, alpha2="XA", alpha3="XAA", name_en="TEST Country A"
    )
    deactivated_country = services.create_country(
        actor=administrator, alpha2="XB", alpha3="XBB", name_en="TEST Country B"
    )
    services.deactivate_country(actor=administrator, public_id=deactivated_country)
    language = services.create_language(
        actor=administrator, code="qaa", script_code="Qaaa", name_en="TEST Language A"
    )
    deactivated_language = services.create_language(
        actor=administrator, code="qab", script_code="Qaaa", name_en="TEST Language B"
    )
    services.deactivate_language(actor=administrator, public_id=deactivated_language)
    return Records(country, deactivated_country, language, deactivated_language)


type Operation = Callable[[AuthenticationContext | None, Records], object]

# The six Country and Language rows of the write matrix, as eight operations:
# deactivating and reactivating are one row and two operations.
WRITES: dict[str, Operation] = {
    "create_country": lambda actor, records: services.create_country(
        actor=actor,  # type: ignore[arg-type]  # an anonymous context is among the cases under test
        alpha2="QM",
        alpha3="QMA",
        name_en="TEST Country C",
    ),
    "rename_country": lambda actor, records: services.rename_country(
        actor=actor,  # type: ignore[arg-type]  # as above
        public_id=records.country,
        name_en="TEST Renamed",
    ),
    "deactivate_country": lambda actor, records: services.deactivate_country(
        actor=actor,  # type: ignore[arg-type]  # as above
        public_id=records.country,
    ),
    "reactivate_country": lambda actor, records: services.reactivate_country(
        actor=actor,  # type: ignore[arg-type]  # as above
        public_id=records.deactivated_country,
    ),
    "create_language": lambda actor, records: services.create_language(
        actor=actor,  # type: ignore[arg-type]  # as above
        code="qac",
        script_code="Qaaa",
        name_en="TEST Language C",
    ),
    "rename_language": lambda actor, records: services.rename_language(
        actor=actor,  # type: ignore[arg-type]  # as above
        public_id=records.language,
        name_en="TEST Renamed",
    ),
    "deactivate_language": lambda actor, records: services.deactivate_language(
        actor=actor,  # type: ignore[arg-type]  # as above
        public_id=records.language,
    ),
    "reactivate_language": lambda actor, records: services.reactivate_language(
        actor=actor,  # type: ignore[arg-type]  # as above
        public_id=records.deactivated_language,
    ),
}
READS: dict[str, Operation] = {
    "countries": lambda actor, records: selectors.countries(actor),
    "languages": lambda actor, records: selectors.languages(actor),
}

# Who acts: the arguments of `acting_as`, or None for an anonymous context.
type Actor = tuple[tuple[Role, ...], dict[str, bool]] | None

VERIFIED = {"second_factor": True}
ANONYMOUS: Actor = None
ACTORS: dict[str, Actor] = {
    "reader": ((Role.READER,), {}),
    "reader-verified": ((Role.READER,), VERIFIED),
    "researcher": ((Role.RESEARCHER,), {}),
    "researcher-verified": ((Role.RESEARCHER,), VERIFIED),
    "reviewer-on-a-password": ((Role.REVIEWER,), {}),
    "reviewer-verified": ((Role.REVIEWER,), VERIFIED),
    "reviewer-untrusted-second-factor": (
        (Role.REVIEWER,),
        {"second_factor": True, "trusted": False},
    ),
    "administrator-on-a-password": ((Role.ADMINISTRATOR,), {}),
    "administrator-verified": ((Role.ADMINISTRATOR,), VERIFIED),
    "administrator-untrusted-second-factor": (
        (Role.ADMINISTRATOR,),
        {"second_factor": True, "trusted": False},
    ),
    "researcher-and-reviewer-on-a-password": ((Role.RESEARCHER, Role.REVIEWER), {}),
    "every-role-but-administrator-verified": (
        (Role.READER, Role.RESEARCHER, Role.REVIEWER),
        VERIFIED,
    ),
    "every-role-on-a-password": (tuple(Role), {}),
    "no-role": ((), {}),
    "no-role-verified": ((), VERIFIED),
    "disabled-administrator-verified": (
        (Role.ADMINISTRATOR,),
        {"second_factor": True, "is_active": False},
    ),
    "disabled-reader": ((Role.READER,), {"is_active": False}),
    "disabled-researcher": ((Role.RESEARCHER,), {"is_active": False}),
    "disabled-reviewer-verified": ((Role.REVIEWER,), {"second_factor": True, "is_active": False}),
    "anonymous": ANONYMOUS,
}
# Written out here, not read from the policy: ADR-0018 points 11 to 13.
MAY_WRITE = {"administrator-verified"}
MAY_READ = {
    "reader",
    "reader-verified",
    "researcher",
    "researcher-verified",
    "reviewer-verified",
    "administrator-verified",
    # A Researcher needs no second factor, and keeps what that role confers.
    "researcher-and-reviewer-on-a-password",
    "every-role-but-administrator-verified",
    "every-role-on-a-password",
}
MAY_ENTER = {
    "researcher",
    "researcher-verified",
    "reviewer-verified",
    "administrator-verified",
    "researcher-and-reviewer-on-a-password",
    "every-role-but-administrator-verified",
    "every-role-on-a-password",
}


def _context(acting_as: ActingAs, actor: str) -> AuthenticationContext | None:
    described = ACTORS[actor]
    if described is None:
        return None
    roles, how = described
    return acting_as(*roles, **how)


@pytest.mark.parametrize("operation", WRITES)
@pytest.mark.parametrize("actor", sorted(set(ACTORS) - MAY_WRITE))
def test_a_write_is_refused_to_every_account_but_a_verified_administrator_and_writes_nothing(
    acting_as: ActingAs, records: Records, operation: str, actor: str
) -> None:
    context = _context(acting_as, actor)
    before = stored()

    with pytest.raises(PermissionDenied):
        WRITES[operation](context, records)

    assert stored() == before


@pytest.mark.parametrize("operation", WRITES)
@pytest.mark.parametrize("actor", sorted(MAY_WRITE))
def test_a_write_is_allowed_to_a_verified_administrator_and_is_recorded_as_theirs(
    acting_as: ActingAs, records: Records, operation: str, actor: str
) -> None:
    context = _context(acting_as, actor)
    assert context is not None
    recorded_before = len(events())

    WRITES[operation](context, records)

    (event,) = events()[recorded_before:]
    assert event[3] == context.user.pk


@pytest.mark.parametrize("operation", READS)
@pytest.mark.parametrize("actor", sorted(ACTORS))
def test_a_read_is_allowed_exactly_to_the_accounts_that_hold_the_read_permission(
    acting_as: ActingAs, records: Records, operation: str, actor: str
) -> None:
    context = _context(acting_as, actor)
    before = stored()

    if actor in MAY_READ:
        assert len(READS[operation](context, records)) == 2  # type: ignore[arg-type]  # a read returns a list
    else:
        with pytest.raises(PermissionDenied):
            READS[operation](context, records)

    assert stored() == before


@pytest.mark.parametrize("actor", sorted(ACTORS))
def test_each_account_holds_exactly_the_registry_permissions_of_its_roles_and_assurance(
    acting_as: ActingAs, actor: str
) -> None:
    context = _context(acting_as, actor)
    registry = {
        Permission.REGISTRY_READ,
        Permission.REGISTRY_REFERENCE_MANAGE,
        Permission.REGISTRY_INSTITUTIONS_MANAGE,
    }

    held = accounts_selectors.permissions_of(context) & registry

    expected = set()
    if actor in MAY_READ:
        expected.add(Permission.REGISTRY_READ)
    if actor in MAY_WRITE:
        expected.add(Permission.REGISTRY_REFERENCE_MANAGE)
    if actor in MAY_ENTER:
        expected.add(Permission.REGISTRY_INSTITUTIONS_MANAGE)
    assert held == expected


@pytest.mark.parametrize(
    ("roles", "how"),
    [
        ((Role.READER,), {}),
        ((Role.RESEARCHER,), {}),
        ((Role.REVIEWER,), VERIFIED),
        ((Role.ADMINISTRATOR,), VERIFIED),
    ],
)
def test_a_registry_permission_confers_no_research_permission_and_the_reverse(
    acting_as: ActingAs, roles: tuple[Role, ...], how: dict[str, bool]
) -> None:
    """ADR-0018 point 11: registry maintenance is not research."""
    held = accounts_selectors.permissions_of(acting_as(*roles, **how))
    research = {
        Permission.WORKSPACE_READ,
        Permission.RESEARCH_CONTRIBUTE,
        Permission.RESEARCH_REVIEW,
    }

    if Role.ADMINISTRATOR in roles:
        assert held.isdisjoint(research)
    else:
        assert Permission.REGISTRY_REFERENCE_MANAGE not in held


def test_holding_the_institutions_permission_allows_no_country_or_language_operation(
    acting_as: ActingAs, records: Records
) -> None:
    """It is a permission of institution maintenance only (ADR-0018 points 11 and 13)."""
    researcher = acting_as(Role.RESEARCHER)
    assert accounts_selectors.can(researcher, Permission.REGISTRY_INSTITUTIONS_MANAGE)
    before = stored()

    for operation in WRITES.values():
        with pytest.raises(PermissionDenied):
            operation(researcher, records)

    assert stored() == before


# --- The permission comes first -----------------------------------------------


REFUSED_FIRST: dict[str, Callable[[Any], object]] = {
    "create a country with a code of the wrong form": lambda actor: services.create_country(
        actor=actor, alpha2="x", alpha3="", name_en=""
    ),
    "create a language with a code of the wrong form": lambda actor: services.create_language(
        actor=actor, code="QAA", script_code="", name_en=""
    ),
    "rename a country that does not exist": lambda actor: services.rename_country(
        actor=actor, public_id=UNKNOWN, name_en=""
    ),
    "deactivate a country that does not exist": lambda actor: services.deactivate_country(
        actor=actor, public_id=UNKNOWN
    ),
    "reactivate a country that does not exist": lambda actor: services.reactivate_country(
        actor=actor, public_id=UNKNOWN
    ),
    "rename a language that does not exist": lambda actor: services.rename_language(
        actor=actor, public_id=UNKNOWN, name_en=""
    ),
    "deactivate a language that does not exist": lambda actor: services.deactivate_language(
        actor=actor, public_id=UNKNOWN
    ),
    "reactivate a language that does not exist": lambda actor: services.reactivate_language(
        actor=actor, public_id=UNKNOWN
    ),
}


@pytest.mark.parametrize("request_made", REFUSED_FIRST)
@pytest.mark.parametrize("actor", ["researcher", "administrator-on-a-password", "anonymous"])
def test_an_account_without_the_permission_learns_nothing_about_a_record_or_its_input(
    acting_as: ActingAs, request_made: str, actor: str
) -> None:
    """Refused as it would be for a record that exists and input that is valid."""
    with pytest.raises(PermissionDenied):
        REFUSED_FIRST[request_made](_context(acting_as, actor))


@pytest.mark.parametrize(
    "operation", ["rename_country", "deactivate_country", "create_country", "create_language"]
)
def test_an_account_without_the_permission_is_refused_the_same_whatever_the_record_is(
    acting_as: ActingAs, records: Records, operation: str
) -> None:
    """A change that would change nothing, or a code in use, is not told apart from any other."""
    researcher = acting_as(Role.RESEARCHER)
    no_change = Records(
        country=records.deactivated_country,
        deactivated_country=records.country,
        language=records.deactivated_language,
        deactivated_language=records.language,
    )

    with pytest.raises(PermissionDenied):
        WRITES[operation](researcher, no_change)
    with pytest.raises(PermissionDenied):
        services.create_country(actor=researcher, alpha2="XA", alpha3="XAA", name_en="TEST")
    with pytest.raises(PermissionDenied):
        services.create_language(actor=researcher, code="qaa", script_code="Qaaa", name_en="TEST")


def test_a_refused_write_is_logged_as_a_refused_permission(
    acting_as: ActingAs, records: Records, caplog: pytest.LogCaptureFixture
) -> None:
    researcher = acting_as(Role.RESEARCHER)
    caplog.clear()

    with pytest.raises(PermissionDenied):
        services.deactivate_country(actor=researcher, public_id=records.country)

    (record,) = [record for record in caplog.records if record.name == "caipo.accounts.selectors"]
    assert record.__dict__["event"] == "authorization.denied"
    assert record.__dict__["permission"] == "registry.reference.manage"
    assert record.__dict__["user_id"] == researcher.user.pk
    assert [record for record in caplog.records if record.name == "caipo.registry.services"] == []


# --- An account that stops being allowed --------------------------------------


def test_an_administrator_whose_second_factor_is_not_theirs_writes_nothing(
    acting_as: ActingAs, records: Records
) -> None:
    """A context that names another account's device proves no second factor."""
    administrator = acting_as(Role.ADMINISTRATOR, second_factor=True)
    other = acting_as(Role.ADMINISTRATOR, second_factor=True)
    assert other.mfa_device_id is not None
    borrowed = AuthenticationContext(administrator.user, other.assurance, other.mfa_device_id)
    before = stored()

    with pytest.raises(PermissionDenied):
        services.deactivate_country(actor=borrowed, public_id=records.country)

    assert stored() == before
    assert Country.objects.get(public_id=records.country).is_active
    assert Language.objects.count() == 2
