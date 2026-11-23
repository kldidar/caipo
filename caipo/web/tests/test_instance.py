"""The public demonstration instance (ADR-0024 points 5, 7, and 8): its pages and services."""

from typing import Any

import pytest
from django.core.exceptions import PermissionDenied
from django.test import Client, RequestFactory, override_settings

from caipo.accounts import selectors, services
from caipo.accounts.models import User
from caipo.accounts.selectors import Permission, Role
from caipo.accounts.tests.fixtures import UserFactory
from caipo.articles import services as articles_services
from caipo.web import instance
from caipo.web.authentication import source
from caipo.web.tests.helpers import signed_in

pytestmark = pytest.mark.django_db

SHARED = "TEST.shared@caipo.test"
INSTANCE = {
    "DEMONSTRATION_INSTANCE": True,
    "REGISTRATION_OPEN": False,
    "PASSWORD_RESET_OPEN": False,
    "SHARED_ACCOUNT_EMAIL": SHARED,
    "SHARED_ACCOUNT_PASSWORD": "TEST-shared-password",
}
NOTICE = "A demonstration of CAIPO."


def _text(response: Any) -> str:
    return str(response.content.decode())


def _shared_reader(user_with_roles: UserFactory) -> User:
    user = user_with_roles(Role.READER)
    user.email = SHARED.lower()
    user.save(update_fields=["email"])
    return user


# --- The client address --------------------------------------------------------------


@pytest.mark.parametrize(
    ("proxies", "forwarded", "expected"),
    [
        (0, "203.0.113.9", "192.0.2.1"),
        (1, "203.0.113.9", "203.0.113.9"),
        # A client that writes the header itself is never believed: the
        # proxy's own entry is the last one.
        (1, "198.51.100.7, 203.0.113.9", "203.0.113.9"),
        (1, " 198.51.100.7 ,203.0.113.9 ", "203.0.113.9"),
        (2, "198.51.100.7, 203.0.113.9, 192.0.2.50", "203.0.113.9"),
        (1, "", "192.0.2.1"),
        (2, "203.0.113.9", "192.0.2.1"),
    ],
)
def test_the_client_address_is_the_entry_the_trusted_proxy_added(
    proxies: int, forwarded: str, expected: str
) -> None:
    request = RequestFactory().get("/", REMOTE_ADDR="192.0.2.1", HTTP_X_FORWARDED_FOR=forwarded)

    with override_settings(TRUSTED_PROXY_COUNT=proxies):
        assert source(request) == expected


# --- What every page says ------------------------------------------------------------


@pytest.mark.parametrize("url", ["/", "/login/", "/help/", "/register/"])
def test_every_page_of_the_instance_carries_its_notice(client: Client, url: str) -> None:
    with override_settings(**INSTANCE):
        page = _text(client.get(url))

    assert NOTICE in page
    assert "standard request logs" in page and "about a minute to wake" in page


def test_no_other_environment_carries_the_notice(client: Client) -> None:
    assert NOTICE not in _text(client.get("/"))


def test_the_assistants_say_how_long_questions_are_kept(
    client: Client, user_with_roles: UserFactory
) -> None:
    reader = signed_in(client, user_with_roles(Role.READER))

    with override_settings(**INSTANCE):
        pages = [_text(reader.get("/assistant/")), _text(reader.get("/help/ask/"))]

    for page in pages:
        assert "kept until the site is taken down, by 30 June 2027 at the latest" in page
    assert "taken down" not in _text(reader.get("/assistant/"))


# --- Registration and password reset are closed --------------------------------------


@pytest.mark.parametrize("url", ["/register/", "/password-reset/"])
def test_a_closed_form_says_so_and_refuses_what_is_sent_anyway(client: Client, url: str) -> None:
    with override_settings(**INSTANCE):
        shown = client.get(url)
        sent = client.post(url, {"email": "TEST.visitor@caipo.test"})

    assert shown.status_code == 200 and "closed on this demonstration" in _text(shown)
    assert "<form" not in _text(shown)
    assert sent.status_code == 403
    assert not User.objects.filter(email="TEST.visitor@caipo.test").exists()


def test_the_services_refuse_a_registration_or_a_reset_where_they_are_closed() -> None:
    with override_settings(**INSTANCE):
        with pytest.raises(PermissionDenied):
            services.register_account(
                email="TEST.visitor@caipo.test", source="192.0.2.1", activation_url=str
            )
        with pytest.raises(PermissionDenied):
            services.request_password_reset(
                email="TEST.visitor@caipo.test", source="192.0.2.1", reset_url=str
            )
    assert not User.objects.filter(email="TEST.visitor@caipo.test").exists()


@pytest.mark.parametrize("url", ["/", "/login/"])
def test_no_page_offers_what_the_instance_has_closed(client: Client, url: str) -> None:
    with override_settings(**INSTANCE):
        page = _text(client.get(url))

    assert 'href="/register/"' not in page
    assert 'href="/password-reset/"' not in page


# --- The shared account --------------------------------------------------------------


def test_the_sign_in_page_publishes_the_shared_account(client: Client) -> None:
    with override_settings(**INSTANCE):
        page = _text(client.get("/login/"))

    assert SHARED in page and "TEST-shared-password" in page
    assert "TEST-shared-password" not in _text(client.get("/login/"))


def test_the_pages_withhold_from_the_shared_account_what_its_services_refuse(
    user_with_roles: UserFactory,
) -> None:
    shared = selectors.authentication_context(_shared_reader(user_with_roles))
    other = selectors.authentication_context(user_with_roles(Role.READER))

    with override_settings(**INSTANCE):
        assert instance.permissions_shown(shared) == {
            Permission.WORKSPACE_READ,
            Permission.REGISTRY_READ,
            Permission.ASSISTANT_ASK,
        }
        assert instance.permissions_shown(other) == selectors.permissions_of(other)
        # The authorization policy reads no setting: it is unchanged.
        assert selectors.can(shared, Permission.MFA_MANAGE_OWN)
    assert instance.permissions_shown(shared) == selectors.permissions_of(shared)


@pytest.mark.parametrize(
    "change",
    [
        lambda actor: services.start_mfa_enrollment(
            actor=actor, password="TEST-password", source="192.0.2.1"
        ),
        lambda actor: services.confirm_mfa_enrollment(
            actor=actor, code="000000", source="192.0.2.1"
        ),
        lambda actor: services.disable_mfa(
            actor=actor, password="TEST-password", code="000000", source="192.0.2.1"
        ),
        lambda actor: services.replace_mfa_device(
            actor=actor, password="TEST-password", code="000000", source="192.0.2.1"
        ),
        lambda actor: articles_services.submit_article(
            actor=actor,
            author_name="TEST author",
            title="TEST title",
            summary="TEST summary",
            body="TEST body",
            licence="CC-BY-4.0",
        ),
    ],
    ids=["start enrolment", "confirm enrolment", "disable", "replace", "submit an article"],
)
def test_each_change_is_refused_to_the_shared_account_by_its_service(
    user_with_roles: UserFactory, change: Any
) -> None:
    shared = selectors.authentication_context(_shared_reader(user_with_roles))

    with override_settings(**INSTANCE), pytest.raises(PermissionDenied):
        change(shared)


def test_the_pages_of_those_changes_are_refused_and_not_offered(
    client: Client, user_with_roles: UserFactory
) -> None:
    shared = signed_in(client, _shared_reader(user_with_roles))

    with override_settings(**INSTANCE):
        assert shared.get("/account/second-factor/").status_code == 403
        assert shared.get("/articles/new/").status_code == 403
        home = _text(shared.get("/"))
    assert 'href="/articles/new/"' not in home
    assert 'href="/account/second-factor/"' not in home
