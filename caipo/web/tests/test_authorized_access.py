"""Views that declare a permission are served only to accounts that hold it."""

import logging
from collections.abc import Iterator

import pytest
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.test import Client
from django.urls import path

from caipo.accounts import selectors, services
from caipo.accounts.models import User
from caipo.accounts.selectors import Permission, Role
from caipo.accounts.tests.fixtures import UserFactory
from caipo.accounts.tests.fixtures import signed_in as acting
from caipo.accounts.tests.fixtures import verified as acting_verified
from caipo.web import sessions
from caipo.web.access import PUBLIC, declared_access, public, requires
from caipo.web.tests.helpers import signed_in, verified

pytestmark = [pytest.mark.services, pytest.mark.django_db, pytest.mark.urls(__name__)]

calls: list[str] = []


def _view(name: str) -> HttpResponse:
    calls.append(name)
    return HttpResponse(f"TEST {name}")


@public
def public_view(request: HttpRequest) -> HttpResponse:
    return _view("public")


@requires(Permission.WORKSPACE_READ)
def read_view(request: HttpRequest) -> HttpResponse:
    return _view("read")


@requires(Permission.RESEARCH_CONTRIBUTE)
def contribute_view(request: HttpRequest) -> HttpResponse:
    return _view("contribute")


@requires(Permission.RESEARCH_REVIEW)
def review_view(request: HttpRequest) -> HttpResponse:
    return _view("review")


@requires(Permission.ROLES_MANAGE)
def manage_roles_view(request: HttpRequest) -> HttpResponse:
    return _view("manage-roles")


@requires(Permission.WORKSPACE_READ)
def read_view_calling_a_stricter_service(request: HttpRequest) -> HttpResponse:
    """A view whose declaration is weaker than what the service it calls demands."""
    selectors.require_permission(sessions.authentication_context(request), Permission.ROLES_MANAGE)
    return _view("stricter-service")


def view_with_a_malformed_declaration(request: HttpRequest) -> HttpResponse:
    return _view("malformed")


# What a careless or hostile change might write instead of a declaration: the
# permission's text, not the Permission.
vars(view_with_a_malformed_declaration)["caipo_access"] = "workspace.read"

VIEWS = {
    "/public/": public_view,
    "/read/": read_view,
    "/contribute/": contribute_view,
    "/review/": review_view,
    "/manage-roles/": manage_roles_view,
}
PERMISSION_OF = {
    "/read/": Permission.WORKSPACE_READ,
    "/contribute/": Permission.RESEARCH_CONTRIBUTE,
    "/review/": Permission.RESEARCH_REVIEW,
    "/manage-roles/": Permission.ROLES_MANAGE,
}

urlpatterns = [
    *(path(url.strip("/") + "/", view) for url, view in VIEWS.items()),
    path("stricter-service/", read_view_calling_a_stricter_service),
    path("malformed/", view_with_a_malformed_declaration),
]


@pytest.fixture(autouse=True)
def _reset_calls() -> Iterator[None]:
    calls.clear()
    yield
    calls.clear()


def _served(client: Client) -> set[str]:
    """Return the test URLs this client is served."""
    return {url for url in VIEWS if client.get(url).status_code == 200}


def test_an_anonymous_visitor_reaches_only_the_public_view(client: Client) -> None:
    assert _served(client) == {"/public/"}
    assert calls == ["public"]


@pytest.mark.parametrize("url", sorted(PERMISSION_OF))
def test_an_anonymous_visitor_is_refused_before_the_view_runs(client: Client, url: str) -> None:
    response = client.get(url)

    assert response.status_code == 403
    assert b"TEST" not in response.content
    assert calls == []


def test_signing_in_without_a_role_grants_nothing_beyond_public(
    client: Client, user_with_roles: UserFactory
) -> None:
    assert _served(signed_in(client, user_with_roles())) == {"/public/"}


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        ((Role.READER,), {"/public/", "/read/"}),
        ((Role.RESEARCHER,), {"/public/", "/read/", "/contribute/"}),
        # On a password alone these two roles open no page.
        ((Role.REVIEWER,), {"/public/"}),
        ((Role.ADMINISTRATOR,), {"/public/"}),
        ((Role.READER, Role.ADMINISTRATOR), {"/public/", "/read/"}),
    ],
)
def test_what_each_role_reaches_on_a_password_alone(
    client: Client, user_with_roles: UserFactory, roles: tuple[Role, ...], expected: set[str]
) -> None:
    assert _served(signed_in(client, user_with_roles(*roles))) == expected


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        ((Role.READER,), {"/public/", "/read/"}),
        ((Role.RESEARCHER,), {"/public/", "/read/", "/contribute/"}),
        ((Role.REVIEWER,), {"/public/", "/read/", "/contribute/", "/review/"}),
        ((Role.ADMINISTRATOR,), {"/public/", "/manage-roles/"}),
        (
            (Role.REVIEWER, Role.ADMINISTRATOR),
            {"/public/", "/read/", "/contribute/", "/review/", "/manage-roles/"},
        ),
    ],
)
def test_what_each_role_reaches_with_a_verified_second_factor(
    client: Client, user_with_roles: UserFactory, roles: tuple[Role, ...], expected: set[str]
) -> None:
    assert _served(verified(client, user_with_roles(*roles))) == expected


@pytest.mark.parametrize("role", list(Role))
def test_the_http_boundary_and_the_service_layer_agree(
    client: Client, user_with_roles: UserFactory, role: Role
) -> None:
    user = user_with_roles(role)

    for sign_in, actor in ((signed_in, acting(user)), (verified, acting_verified(user))):
        sign_in(client, user)
        for url, permission in PERMISSION_OF.items():
            assert (client.get(url).status_code == 200) == selectors.can(actor, permission), url


def test_a_refusal_is_logged_without_the_email(
    client: Client, user_with_roles: UserFactory, caplog: pytest.LogCaptureFixture
) -> None:
    user = user_with_roles(Role.READER)

    with caplog.at_level(logging.WARNING, logger="caipo.web.middleware"):
        response = signed_in(client, user).get("/contribute/")

    assert response.status_code == 403
    assert calls == []
    (record,) = [record for record in caplog.records if record.name == "caipo.web.middleware"]
    assert record.__dict__["event"] == "access.denied"
    assert record.__dict__["view"] == "contribute_view"
    assert record.__dict__["permission"] == "research.contribute"
    assert record.__dict__["user_id"] == user.pk
    assert user.email not in str(record.__dict__)


@pytest.mark.parametrize("method", ["get", "post", "put", "patch", "delete", "head", "options"])
def test_a_refusal_does_not_depend_on_the_http_method(
    client: Client, user_with_roles: UserFactory, method: str
) -> None:
    response = getattr(signed_in(client, user_with_roles(Role.READER)), method)("/contribute/")

    assert response.status_code == 403
    assert calls == []


def test_a_role_supplied_by_the_browser_is_ignored(
    client: Client, user_with_roles: UserFactory
) -> None:
    verified(client, user_with_roles(Role.READER))
    client.cookies["role"] = "administrator"
    client.cookies["roles"] = "administrator"

    response = client.post(
        "/manage-roles/?role=administrator&roles=administrator",
        data={"role": "administrator", "is_administrator": "true"},
        headers={"X-Role": "administrator", "X-User-Role": "administrator"},
    )

    assert response.status_code == 403
    assert calls == []


def test_a_role_written_into_the_session_is_ignored(
    client: Client, user_with_roles: UserFactory
) -> None:
    verified(client, user_with_roles(Role.READER))
    session = client.session
    session["role"] = "administrator"
    session["roles"] = ["administrator"]
    session.save()

    assert client.get("/manage-roles/").status_code == 403
    assert calls == []


@pytest.mark.parametrize("roles", [(Role.ADMINISTRATOR,), (Role.REVIEWER,)])
def test_no_request_input_stands_in_for_a_second_factor(
    client: Client, user_with_roles: UserFactory, roles: tuple[Role, ...]
) -> None:
    signed_in(client, user_with_roles(*roles))
    names = [
        "mfa",
        "mfa_verified",
        "mfa_enrolled",
        "otp",
        "otp_verified",
        "totp",
        "bypass_mfa",
        "assurance",
        sessions.VERIFIED_DEVICE_KEY,
    ]
    session = client.session
    for name in names:
        client.cookies[name] = "true"
        session[name] = True
    session["assurance"] = "mfa_verified"
    session.save()
    query = "&".join(f"{name}=true" for name in names)
    headers = {f"X-{name.replace('_', '-')}": "true" for name in names}

    for url in ("/manage-roles/", "/review/"):
        response = client.post(f"{url}?{query}", data=dict.fromkeys(names, "true"), headers=headers)
        assert response.status_code == 403, url
    assert calls == []


def test_a_revoked_role_stops_working_on_the_next_request(
    client: Client, user_with_roles: UserFactory
) -> None:
    administrator = user_with_roles(Role.ADMINISTRATOR)
    user = user_with_roles(Role.RESEARCHER)
    verified(client, user)
    assert client.get("/contribute/").status_code == 200

    services.revoke_role(
        actor=acting_verified(administrator),
        user=user,
        role=Role.RESEARCHER,
        reason="TEST revocation",
    )

    assert client.get("/contribute/").status_code == 403


def test_a_deactivated_account_is_refused_on_its_next_request(
    client: Client, user_with_roles: UserFactory
) -> None:
    user = user_with_roles(Role.READER)
    signed_in(client, user)
    assert client.get("/read/").status_code == 200

    User.objects.filter(pk=user.pk).update(status="disabled")

    assert client.get("/read/").status_code == 403


def test_a_service_refuses_even_when_the_view_declaration_let_the_request_in(
    client: Client, user_with_roles: UserFactory
) -> None:
    response = signed_in(client, user_with_roles(Role.READER)).get("/stricter-service/")

    assert response.status_code == 403
    assert calls == []


def test_a_malformed_declaration_counts_as_none(
    client: Client, user_with_roles: UserFactory
) -> None:
    assert declared_access(view_with_a_malformed_declaration) is None
    assert signed_in(client, user_with_roles(Role.READER)).get("/malformed/").status_code == 403
    assert calls == []


def test_declarations_are_read_back_exactly() -> None:
    assert declared_access(public_view) == PUBLIC
    assert declared_access(read_view) is Permission.WORKSPACE_READ
    assert declared_access(manage_roles_view) is Permission.ROLES_MANAGE


@pytest.mark.parametrize("not_a_permission", ["workspace.read", "public", "administrator", None])
def test_requires_accepts_only_a_permission(not_a_permission: object) -> None:
    with pytest.raises(TypeError):
        # The ignore below: an argument that is not a Permission is the case under test.
        requires(not_a_permission)  # type: ignore[arg-type]


def test_a_service_can_be_called_with_no_request_at_all(user_with_roles: UserFactory) -> None:
    with pytest.raises(PermissionDenied):
        services.grant_role(
            actor=acting(user_with_roles(Role.READER)),
            user=user_with_roles(),
            role=Role.READER,
            reason="TEST attempt",
        )


@pytest.mark.urls("caipo.config.urls")
@pytest.mark.parametrize("roles", [None, (), (Role.READER,), (Role.ADMINISTRATOR,)])
def test_health_endpoints_stay_open_to_everyone(
    client: Client, user_with_roles: UserFactory, roles: tuple[Role, ...] | None
) -> None:
    if roles is not None:
        signed_in(client, user_with_roles(*roles))

    assert client.get("/health/live/").status_code == 200
    assert client.get("/health/ready/").status_code == 200
