"""Break-glass cannot be reached over HTTP, and what it does is seen over HTTP (ADR-0017 point 60).

No page, parameter, header, or cookie performs or shortens it. The command's
two services are called here directly, as the command calls them, and what
they did is read from the next request of a real session.
"""

import inspect
from collections.abc import Iterator
from pathlib import Path

import pytest
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver

import caipo.web
from caipo.accounts import selectors, services
from caipo.accounts.models import AuthenticationEvent, TotpDevice, TotpDeviceState, User
from caipo.accounts.selectors import Role
from caipo.accounts.services import BreakGlassOutcome
from caipo.accounts.tests.fixtures import UserFactory, code_at, enrolled_device
from caipo.accounts.tests.test_recovery_authorization import PASSWORD, _asked, _enrolment_request
from caipo.web.tests.helpers import signed_in, verified

pytestmark = [pytest.mark.services, pytest.mark.django_db]

LOGIN = "/login/"
OWN_PAGE = "/account/second-factor/"
CONFIRM = "/account/second-factor/confirm/"
ACCOUNTS = "/administration/accounts/"
REQUESTS = "/administration/recovery-requests/"
ENROLMENT_REQUESTS = "/administration/second-factor-requests/"
BREAK_GLASS = "mfa_recovery_break_glass"
DONE = BreakGlassOutcome.DONE


def _patterns(resolver: URLResolver) -> Iterator[URLPattern]:
    for entry in resolver.url_patterns:
        if isinstance(entry, URLResolver):
            yield from _patterns(entry)
        else:
            yield entry


@pytest.fixture
def administrator(user_with_roles: UserFactory) -> User:
    """Return the only Administrator, with a known password and an active second factor."""
    user = user_with_roles(Role.ADMINISTRATOR)
    user.set_password(PASSWORD)
    user.save()
    enrolled_device(user)
    return user


def _break_glass_events() -> int:
    return AuthenticationEvent.objects.filter(event_type=BREAK_GLASS).count()


def test_no_route_is_a_break_glass_route() -> None:
    routes = list(_patterns(get_resolver()))

    # The command added none. Two were added since, and both only read: the
    # history of an account's own recoveries and that of every account
    # (ADR-0017 point 78). Neither performs or starts anything.
    assert len(routes) == 25
    for route in routes:
        described = f"{route.name} {route.pattern} {route.callback.__module__}"
        assert "break" not in described.lower()
        assert "glass" not in described.lower()
        assert "emergency" not in described.lower()
        view = inspect.getsource(inspect.getmodule(route.callback) or caipo.web)
        assert "break_glass" not in view
        assert "call_command" not in view


def test_nothing_in_the_web_package_knows_of_break_glass() -> None:
    package_root = Path(inspect.getfile(caipo.web)).parent
    knowing = sorted(
        str(path.relative_to(package_root))
        for path in package_root.rglob("*")
        if path.is_file()
        and "tests" not in path.parts
        and path.suffix in {".py", ".html", ".js"}
        and ("break_glass" in path.read_text() or "break-glass" in path.read_text().lower())
    )

    assert knowing == []


@pytest.mark.parametrize(
    "path",
    [
        "/administration/break-glass/",
        "/administration/recovery-requests/break-glass/",
        "/administration/recovery-requests/1/break-glass/",
        "/administration/recovery-requests/1/revoke/",
        "/account/second-factor/break-glass/",
        "/break-glass/",
        "/recover_mfa_break_glass/",
        "/api/break-glass/",
    ],
)
def test_no_such_page_exists_even_for_a_verified_administrator(
    path: str, administrator: User
) -> None:
    client = verified(Client(), administrator)
    number = _asked(administrator)

    for response in (client.get(path), client.post(path, {"number": number})):
        assert response.status_code == 404
    assert _break_glass_events() == 0


def test_the_only_administrator_cannot_recover_its_own_account_through_the_application(
    administrator: User,
) -> None:
    # Still signed in with the device on another machine, and asking for
    # recovery from a second sign-in. Nothing sent with the request turns the
    # application's refusal into what the command does.
    client = verified(Client(enforce_csrf_checks=False), administrator)
    number = _asked(administrator)

    response = client.post(
        f"{REQUESTS}{number}/authorize/",
        {
            "confirmed": "on",
            "break_glass": "1",
            "break_glass_action": "revoke_device",
            "action": "revoke_device",
            "confirmation": "revoke lost second factor",
        },
        headers={"X-Break-Glass": "revoke_device", "X-Caipo-Break-Glass": "1"},
    )

    assert response.status_code == 403
    assert _break_glass_events() == 0
    assert TotpDevice.objects.filter(user=administrator, state=TotpDeviceState.ACTIVE).exists()
    assert User.objects.get(pk=administrator.pk).session_epoch == 0


def test_no_administrator_can_approve_through_the_application_what_only_the_command_may(
    administrator: User,
) -> None:
    # After a revocation the account holds one permission on its password,
    # and the page that approves enrolments is not it.
    number = _asked(administrator)
    assert (
        services.break_glass_revoke_device(email=administrator.email, request_number=number).outcome
        == DONE
    )
    _secret, enrolment = _enrolment_request(administrator)
    client = signed_in(Client(), administrator)

    listing = client.get(ENROLMENT_REQUESTS)
    approval = client.post(
        f"{ENROLMENT_REQUESTS}{enrolment}/approve/",
        {"confirmed": "on", "break_glass_action": "approve_enrollment"},
    )

    assert (listing.status_code, approval.status_code) == (403, 403)
    assert TotpDevice.objects.get(user=administrator).state == TotpDeviceState.PENDING_APPROVAL
    assert _break_glass_events() == 1


def test_a_session_from_before_a_revocation_by_the_command_is_refused_after_it(
    administrator: User, user_with_roles: UserFactory
) -> None:
    held_by_the_lost_device = verified(Client(), administrator)
    bystander = user_with_roles(Role.READER)
    other = signed_in(Client(), bystander)
    assert held_by_the_lost_device.get(ACCOUNTS).status_code == 200
    number = _asked(administrator)

    result = services.break_glass_revoke_device(email=administrator.email, request_number=number)

    assert result.outcome == DONE
    # Not signed in at all any more, and so not at the weaker assurance either.
    assert held_by_the_lost_device.get(ACCOUNTS).status_code == 403
    assert held_by_the_lost_device.get(OWN_PAGE).status_code == 403
    assert other.get(OWN_PAGE).status_code == 200


def test_the_only_administrator_is_recovered_by_the_command_and_its_own_first_code(
    administrator: User,
) -> None:
    number = _asked(administrator)
    assert (
        services.break_glass_revoke_device(email=administrator.email, request_number=number).outcome
        == DONE
    )
    # The password signs the account in, by itself, and confers nothing.
    client = Client()
    assert (
        client.post(LOGIN, {"email": administrator.email, "password": PASSWORD}).status_code == 302
    )
    assert client.get(OWN_PAGE).status_code == 200
    assert client.get(ACCOUNTS).status_code == 403
    secret, enrolment = _enrolment_request(administrator)
    # Not before the approval, whatever code is given.
    assert client.post(CONFIRM, {"code": code_at(secret=secret)}).status_code != 302
    assert client.get(ACCOUNTS).status_code == 403

    approved = services.break_glass_approve_enrollment(
        email=administrator.email, request_number=enrolment
    )

    assert approved.outcome == DONE
    # The approval alone confers nothing: the first code is still to be given.
    assert client.get(ACCOUNTS).status_code == 403
    assert client.post(CONFIRM, {"code": code_at(secret=secret)}).status_code == 302
    assert client.get(ACCOUNTS).status_code == 200
    assert not selectors.has_open_recovery(administrator.pk)
    assert list(
        AuthenticationEvent.objects.filter(user=administrator)
        .exclude(event_type__in=["mfa_challenge_issued", "login_success"])
        .order_by("id")
        .values_list("event_type", "break_glass_action")
    ) == [
        ("mfa_recovery_requested", ""),
        (BREAK_GLASS, "revoke_device"),
        ("mfa_enrollment_started", ""),
        (BREAK_GLASS, "approve_enrollment"),
        ("mfa_enrollment_succeeded", ""),
        ("mfa_recovery_completed", ""),
    ]
