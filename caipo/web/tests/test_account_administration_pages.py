"""The pages on which an Administrator changes accounts: roles, and disabling and enabling.

What may change and what is recorded is decided by `caipo.accounts`; these
tests check what the pages send it and what they show. Every account and
reason here is visibly synthetic.
"""

from typing import Any

import pytest
from django.http import HttpRequest, HttpResponse
from django.test import Client
from django.urls import include, path
from django.utils import timezone

from caipo.accounts import selectors, services
from caipo.accounts.models import AccountEvent, AccountStatus, RoleEvent, RoleEventType, User
from caipo.accounts.selectors import Permission, Role
from caipo.accounts.tests.fixtures import UserFactory, enrolled_device
from caipo.accounts.tests.fixtures import verified as verified_context
from caipo.web import accounts
from caipo.web.access import declared_access, requires
from caipo.web.tests.helpers import signed_in, verified

pytestmark = [pytest.mark.services, pytest.mark.django_db, pytest.mark.urls(__name__)]

REASON = "TEST reason for the change"
PASSWORD = "TEST-passphrase-chosen-by-the-owner"
ACCOUNTS = "/administration/accounts/"
CONTRIBUTE = "/contribute/"
UNKNOWN = 999_999


@requires(Permission.RESEARCH_CONTRIBUTE)
def contribute_view(request: HttpRequest) -> HttpResponse:
    return HttpResponse("TEST contribute")


urlpatterns = [
    path("", include("caipo.web.urls")),
    path("contribute/", contribute_view),
]


def _page(user_id: int) -> str:
    return f"{ACCOUNTS}{user_id}/"


def _grant(client: Client, user_id: int, role: str = "researcher", **data: str) -> Any:
    return client.post(f"{_page(user_id)}grant-role/", {"role": role, "reason": REASON, **data})


def _revoke(client: Client, user_id: int, role: str = "reader", **data: str) -> Any:
    return client.post(f"{_page(user_id)}revoke-role/", {"role": role, "reason": REASON, **data})


def _disable(client: Client, user_id: int, **data: str) -> Any:
    return client.post(f"{_page(user_id)}disable/", {"confirmed": "on", **data})


def _enable(client: Client, user_id: int) -> Any:
    return client.post(f"{_page(user_id)}enable/")


def _record() -> tuple[int, int, list[str]]:
    return (
        RoleEvent.objects.count(),
        AccountEvent.objects.count(),
        list(User.objects.order_by("pk").values_list("status", flat=True)),
    )


@pytest.fixture
def admin_user(user_with_roles: UserFactory) -> User:
    return user_with_roles(Role.ADMINISTRATOR)


@pytest.fixture
def administrator(admin_user: User) -> Client:
    """A client signed in as an Administrator with a trusted second factor."""
    return verified(Client(), admin_user)


def _visitor(kind: str, user_with_roles: UserFactory) -> Client:
    if kind == "anonymous":
        return Client()
    if kind == "administrator-on-a-password":
        user = user_with_roles(Role.ADMINISTRATOR)
        enrolled_device(user)
        return signed_in(Client(), user)
    return verified(Client(), user_with_roles(Role(kind)))


VISITORS = ["anonymous", "administrator-on-a-password", "reviewer", "researcher", "reader"]


# --- Who reaches these pages ------------------------------------------------------------------


@pytest.mark.parametrize("kind", VISITORS)
def test_only_a_verified_administrator_reaches_or_changes_an_account(
    user_with_roles: UserFactory, kind: str
) -> None:
    target = user_with_roles(Role.READER)
    disabled = user_with_roles(Role.READER, is_active=False)
    visitor = _visitor(kind, user_with_roles)
    before = _record()

    responses = [
        visitor.get(_page(target.pk)),
        visitor.get(_page(UNKNOWN)),
        _grant(visitor, target.pk),
        _revoke(visitor, target.pk),
        _disable(visitor, target.pk),
        _enable(visitor, disabled.pk),
        _grant(visitor, UNKNOWN),
    ]

    assert [response.status_code for response in responses] == [403] * len(responses)
    assert all(target.email not in response.content.decode() for response in responses)
    assert _record() == before


def test_each_page_declares_the_permission_its_service_requires() -> None:
    assert declared_access(accounts.detail) == Permission.ROLES_MANAGE
    assert declared_access(accounts.grant_role) == Permission.ROLES_MANAGE
    assert declared_access(accounts.revoke_role) == Permission.ROLES_MANAGE
    assert declared_access(accounts.disable) == Permission.ACCOUNTS_DEACTIVATE
    assert declared_access(accounts.enable) == Permission.ACCOUNTS_ENABLE


@pytest.mark.parametrize("change", ["grant-role", "revoke-role", "disable", "enable"])
@pytest.mark.parametrize("method", ["get", "head", "put", "patch", "delete"])
def test_changes_are_made_by_post_only(
    administrator: Client, user_with_roles: UserFactory, change: str, method: str
) -> None:
    target = user_with_roles(Role.READER)
    before = _record()

    response = getattr(administrator, method)(f"{_page(target.pk)}{change}/?role=researcher")

    assert response.status_code == 405
    assert _record() == before


def test_the_account_page_is_fetched_by_get_only(
    administrator: Client, user_with_roles: UserFactory
) -> None:
    target = user_with_roles(Role.READER)

    assert administrator.post(_page(target.pk), {"role": "researcher"}).status_code == 405
    assert selectors.roles_of(target) == {Role.READER}


def test_a_change_without_a_csrf_token_is_refused(
    admin_user: User, user_with_roles: UserFactory
) -> None:
    administrator = verified(Client(enforce_csrf_checks=True), admin_user)
    target = user_with_roles(Role.READER)
    disabled = user_with_roles(Role.READER, is_active=False)
    before = _record()

    responses = [
        _grant(administrator, target.pk),
        _revoke(administrator, target.pk),
        _disable(administrator, target.pk),
        _enable(administrator, disabled.pk),
    ]

    assert [response.status_code for response in responses] == [403] * 4
    assert _record() == before


def test_a_number_that_names_no_account_is_not_found(administrator: Client) -> None:
    before = _record()

    responses = [
        administrator.get(_page(UNKNOWN)),
        _grant(administrator, UNKNOWN),
        _revoke(administrator, UNKNOWN),
        _disable(administrator, UNKNOWN),
        _enable(administrator, UNKNOWN),
    ]

    assert [response.status_code for response in responses] == [404] * 5
    assert _record() == before


# --- What the pages show ----------------------------------------------------------------------


def test_the_accounts_page_lists_every_account_with_a_link_to_it(
    administrator: Client, admin_user: User, user_with_roles: UserFactory
) -> None:
    reader = user_with_roles(Role.READER)
    disabled = user_with_roles(Role.REVIEWER, is_active=False)

    page = administrator.get(ACCOUNTS).content.decode()

    assert "All accounts" in page
    for user in (admin_user, reader, disabled):
        assert f'href="{_page(user.pk)}"' in page
        assert user.email in page
    assert "Disabled" in page
    assert "Reviewer" in page
    # The Administrator signed in with a second factor; the others have none.
    assert ("Turned on" in page, "Not turned on" in page) == (True, True)


def test_the_account_page_shows_the_state_the_history_and_the_changes_on_offer(
    administrator: Client, admin_user: User, user_with_roles: UserFactory
) -> None:
    target = user_with_roles(Role.READER)
    services.grant_role(
        actor=verified_context(admin_user),
        user=target,
        role=Role.RESEARCHER,
        reason="TEST <b>reason</b> & more",
    )

    page = administrator.get(_page(target.pk)).content.decode()

    assert target.email in page
    assert "Reader, Researcher" in page
    assert "Created for its owner" in page
    assert "Role history" in page
    assert admin_user.email in page
    # A reason is shown as text, never as markup.
    assert "TEST &lt;b&gt;reason&lt;/b&gt; &amp; more" in page
    assert "<b>reason</b>" not in page
    # The grant form offers only the roles not held; the revoke form only those held.
    grant = page.split('id="grant_role"', 1)[1].split("</select>", 1)[0]
    revoke = page.split('id="revoke_role"', 1)[1].split("</select>", 1)[0]
    assert ('value="reviewer"' in grant, 'value="researcher"' in grant) == (True, False)
    assert ('value="researcher"' in revoke, 'value="reviewer"' in revoke) == (True, False)
    assert f'action="{_page(target.pk)}disable/"' in page
    assert f'action="{_page(target.pk)}enable/"' not in page


def test_an_administrator_sees_their_own_account_and_no_change_to_it(
    administrator: Client, admin_user: User
) -> None:
    page = administrator.get(_page(admin_user.pk)).content.decode()

    assert "This is your own account" in page
    for change in ("grant-role", "revoke-role", "disable", "enable"):
        assert f'action="{_page(admin_user.pk)}{change}/"' not in page


def test_an_administrator_changes_none_of_their_own_roles_by_the_page(
    administrator: Client, admin_user: User
) -> None:
    before = _record()

    assert _grant(administrator, admin_user.pk, "reader").status_code == 403
    assert _revoke(administrator, admin_user.pk, "administrator").status_code == 403
    assert _record() == before


def test_an_unknown_change_named_in_the_address_says_nothing(
    administrator: Client, user_with_roles: UserFactory
) -> None:
    target = user_with_roles(Role.READER)

    page = administrator.get(f"{_page(target.pk)}?changed=<script>").content.decode()

    assert 'role="status"' not in page
    assert "<script>" not in page.split("<main", 1)[1]


# --- Roles ------------------------------------------------------------------------------------


def test_a_role_granted_on_the_page_is_recorded_with_the_administrator_and_the_reason(
    administrator: Client, admin_user: User, user_with_roles: UserFactory
) -> None:
    target = user_with_roles(Role.READER)

    response = _grant(administrator, target.pk, actor="TEST someone else", account="1")

    assert response.status_code == 302
    assert response["Location"] == f"{_page(target.pk)}?changed=granted"
    event = RoleEvent.objects.latest("id")
    assert (event.user, event.actor, event.role, event.event_type, event.reason) == (
        target,
        admin_user,
        Role.RESEARCHER,
        RoleEventType.GRANTED,
        REASON,
    )
    page = administrator.get(response["Location"]).content.decode()
    assert "The role was granted." in page


def test_a_role_revoked_on_the_page_is_recorded_and_the_grant_stays_on_record(
    administrator: Client, admin_user: User, user_with_roles: UserFactory
) -> None:
    target = user_with_roles(Role.READER, Role.RESEARCHER)

    response = _revoke(administrator, target.pk, "researcher")

    assert response["Location"] == f"{_page(target.pk)}?changed=revoked"
    assert selectors.roles_of(target) == {Role.READER}
    assert list(
        RoleEvent.objects.filter(user=target, role=Role.RESEARCHER)
        .order_by("id")
        .values_list("event_type", flat=True)
    ) == [RoleEventType.GRANTED, RoleEventType.REVOKED]


@pytest.mark.parametrize(
    "data",
    [
        {"reason": ""},
        {"reason": "   "},
        {"reason": "x" * 1001},
        {"role": "superuser"},
        {"role": ""},
    ],
)
@pytest.mark.parametrize("change", ["grant", "revoke"])
def test_a_role_change_needs_one_of_the_four_roles_and_a_reason(
    administrator: Client, user_with_roles: UserFactory, change: str, data: dict[str, str]
) -> None:
    target = user_with_roles(Role.READER)
    before = _record()

    response = (_grant if change == "grant" else _revoke)(administrator, target.pk, **data)

    assert response.status_code == 400
    assert "Choose one of the roles and give a reason." in response.content.decode()
    assert _record() == before


def test_a_role_change_that_changes_nothing_is_refused_with_its_reason(
    administrator: Client, user_with_roles: UserFactory
) -> None:
    target = user_with_roles(Role.READER)
    before = _record()

    holds = _grant(administrator, target.pk, "reader")
    lacks = _revoke(administrator, target.pk, "reviewer")

    assert (holds.status_code, lacks.status_code) == (409, 409)
    assert "The account already holds that role." in holds.content.decode()
    assert "The account does not hold that role." in lacks.content.decode()
    assert _record() == before


def test_a_role_granted_on_the_page_takes_effect_on_the_next_request(
    administrator: Client, client: Client
) -> None:
    services.register_account(
        email="test.registered@caipo.test",
        source="192.0.2.1",
        activation_url=lambda token: f"/#{token}",
    )
    user = User.objects.get(email="test.registered@caipo.test")
    # Activated as its owner would activate it, without the message in between.
    User.objects.filter(pk=user.pk).update(status=AccountStatus.ACTIVE, activated_at=timezone.now())
    signed_in(client, user)
    assert client.get(CONTRIBUTE).status_code == 403
    assert (
        "Registered by its owner on the site" in administrator.get(_page(user.pk)).content.decode()
    )

    _grant(administrator, user.pk, "researcher")
    assert client.get(CONTRIBUTE).status_code == 200

    _revoke(administrator, user.pk, "researcher")
    assert client.get(CONTRIBUTE).status_code == 403


# --- Disabling and enabling -------------------------------------------------------------------


@pytest.mark.parametrize("confirmed", [None, "", "0", "off", "true"])
def test_disabling_needs_the_confirmation_ticked(
    administrator: Client, user_with_roles: UserFactory, confirmed: str | None
) -> None:
    target = user_with_roles(Role.READER)
    before = _record()
    data = {} if confirmed is None else {"confirmed": confirmed}

    response = administrator.post(f"{_page(target.pk)}disable/", data)

    assert response.status_code == 400
    assert "Tick the confirmation to disable the account." in response.content.decode()
    assert _record() == before


def test_an_account_disabled_on_the_page_is_signed_out_and_enabled_again_as_it_was(
    administrator: Client, user_with_roles: UserFactory
) -> None:
    target = user_with_roles(Role.RESEARCHER)
    session = signed_in(Client(), target)
    assert session.get(CONTRIBUTE).status_code == 200

    disabled = _disable(administrator, target.pk)

    assert disabled["Location"] == f"{_page(target.pk)}?changed=disabled"
    assert session.get(CONTRIBUTE).status_code == 403
    page = administrator.get(disabled["Location"]).content.decode()
    assert "The account was disabled." in page
    assert f'action="{_page(target.pk)}enable/"' in page

    enabled = _enable(administrator, target.pk)

    assert enabled["Location"] == f"{_page(target.pk)}?changed=enabled"
    target.refresh_from_db()
    assert target.status == AccountStatus.ACTIVE
    assert selectors.roles_of(target) == {Role.RESEARCHER}


def test_enabling_an_account_never_activated_says_its_message_must_be_sent_again(
    administrator: Client, user_with_roles: UserFactory
) -> None:
    target = user_with_roles(Role.READER, is_active=False)
    User.objects.filter(pk=target.pk).update(activated_at=None)

    response = _enable(administrator, target.pk)

    assert response["Location"] == f"{_page(target.pk)}?changed=enabled-unverified"
    target.refresh_from_db()
    assert target.status == AccountStatus.PENDING_VERIFICATION
    assert "must be sent again" in administrator.get(response["Location"]).content.decode()


def test_disabling_or_enabling_twice_is_refused_with_its_reason(
    administrator: Client, user_with_roles: UserFactory
) -> None:
    active = user_with_roles(Role.READER)
    disabled = user_with_roles(Role.READER, is_active=False)
    before = _record()

    again = _disable(administrator, disabled.pk)
    not_disabled = _enable(administrator, active.pk)

    assert (again.status_code, not_disabled.status_code) == (409, 409)
    assert "The account is already disabled." in again.content.decode()
    assert "The account is not disabled." in not_disabled.content.decode()
    assert _record() == before


def test_the_last_administrator_cannot_be_disabled_from_the_page(
    administrator: Client, admin_user: User
) -> None:
    before = _record()

    response = _disable(administrator, admin_user.pk)

    assert response.status_code == 409
    assert "That would leave the system with no Administrator." in response.content.decode()
    assert _record() == before
