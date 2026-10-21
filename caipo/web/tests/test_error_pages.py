"""The pages answered for a refusal, for no such page, and for a failure (L1, L2, and L8
of the diagnostic of 2026-10-20).

A refusal stays a refusal: the status is 403 whoever asks, and nothing on
the page depends on the record asked for. What the page says depends only on
who asked: an anonymous visitor is offered the sign-in page, an account that
lacks the permission only for want of a trusted second factor is told so,
and any other account is told that it has no access. No error page shows
the exception or the path inside the code, and a refusal or failure is
never stored by a cache.
"""

import io
import json
import logging
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.test import Client, RequestFactory
from django.urls import get_resolver, include, path

from caipo.accounts.models import AccountStatus, User
from caipo.accounts.selectors import Role
from caipo.accounts.tests.fixtures import UserFactory, enrolled_device
from caipo.core.structured_logging import JsonFormatter
from caipo.web import errors
from caipo.web.access import public
from caipo.web.tests.helpers import signed_in, verified

pytestmark = pytest.mark.django_db

BROWSE = "/registry/"
ENTRY = "/registry/entry/"
ACCOUNTS = "/administration/accounts/"
ANONYMOUS_TEXT = "Sign in, and you will be brought back here"
SECOND_FACTOR_TEXT = "only after you sign in with a code from your authenticator application"
NOT_PERMITTED_TEXT = "Your account does not have access to this page."


@public
def failing_view(request: HttpRequest) -> HttpResponse:
    raise RuntimeError("TEST internal detail that must not be shown")


@public
def denied_view(request: HttpRequest) -> HttpResponse:
    raise PermissionDenied("TEST internal reason that must not be shown")


# Used by the tests that need a view to fail: this module is then the URL
# configuration, and names the same handlers as the root one.
urlpatterns = [
    path("failing/", failing_view),
    path("denied/", denied_view),
    path("", include("caipo.web.urls")),
]
handler403 = "caipo.web.errors.permission_denied"
handler404 = "caipo.web.errors.page_not_found"
handler500 = "caipo.web.errors.server_error"


def _text(response: Any) -> str:
    return str(response.content.decode())


def _never_cached(response: Any) -> bool:
    return "no-store" in response.get("Cache-Control", "")


def test_the_root_configuration_names_the_web_handlers() -> None:
    resolver = get_resolver()
    handlers: dict[int, object] = {
        status: resolver.resolve_error_handler(status) for status in (403, 404, 500)
    }

    assert handlers == {
        403: errors.permission_denied,
        404: errors.page_not_found,
        500: errors.server_error,
    }


# --- 403 ----------------------------------------------------------------------------


@pytest.mark.parametrize("url", [BROWSE, ENTRY, ACCOUNTS])
def test_an_anonymous_visitor_is_offered_the_sign_in_page_and_brought_back(
    client: Client, url: str
) -> None:
    response = client.get(url)

    assert response.status_code == 403
    page = _text(response)
    assert ANONYMOUS_TEXT in page
    assert f'href="/login/?next={url}"' in page
    assert SECOND_FACTOR_TEXT not in page
    assert _never_cached(response)


def test_a_refused_post_of_an_anonymous_visitor_offers_the_sign_in_page_alone(
    client: Client,
) -> None:
    response = client.post("/registry/entry/institutions/create/", {})

    assert response.status_code == 403
    assert 'href="/login/"' in _text(response)
    assert "next=" not in _text(response)


@pytest.mark.parametrize(
    ("role", "url"),
    [
        (Role.ADMINISTRATOR, BROWSE),
        (Role.ADMINISTRATOR, ENTRY),
        (Role.ADMINISTRATOR, ACCOUNTS),
        (Role.REVIEWER, BROWSE),
        (Role.REVIEWER, ENTRY),
    ],
)
def test_an_account_refused_for_want_of_a_second_factor_is_told_so(
    user_with_roles: UserFactory, role: Role, url: str
) -> None:
    response = signed_in(Client(), user_with_roles(role)).get(url)

    assert response.status_code == 403
    page = _text(response)
    assert SECOND_FACTOR_TEXT in page
    assert 'href="/account/second-factor/"' in page
    assert ANONYMOUS_TEXT not in page
    assert _never_cached(response)


@pytest.mark.parametrize(
    ("roles", "second_factor", "url"),
    [
        ((Role.READER,), False, ENTRY),
        ((Role.RESEARCHER,), False, ACCOUNTS),
        ((), False, BROWSE),
        # A Reviewer would not reach the accounts page with a second factor either.
        ((Role.REVIEWER,), False, ACCOUNTS),
        ((Role.REVIEWER,), True, ACCOUNTS),
    ],
)
def test_an_account_without_the_permission_is_told_only_that_it_has_no_access(
    user_with_roles: UserFactory, roles: tuple[Role, ...], second_factor: bool, url: str
) -> None:
    user = user_with_roles(*roles)
    client = verified(Client(), user) if second_factor else signed_in(Client(), user)

    response = client.get(url)

    assert response.status_code == 403
    page = _text(response)
    assert NOT_PERMITTED_TEXT in page
    assert SECOND_FACTOR_TEXT not in page
    assert _never_cached(response)


def test_a_disabled_account_is_not_told_to_use_a_second_factor(
    user_with_roles: UserFactory,
) -> None:
    """Django no longer takes the session for the account, which is then treated as no one."""
    user = user_with_roles(Role.ADMINISTRATOR)
    client = signed_in(Client(), user)
    User.objects.filter(pk=user.pk).update(status=AccountStatus.DISABLED)

    response = client.get(BROWSE)

    assert response.status_code == 403
    assert SECOND_FACTOR_TEXT not in _text(response)


def test_an_untrusted_second_factor_is_still_refused_and_told_what_is_missing(
    user_with_roles: UserFactory,
) -> None:
    user = user_with_roles(Role.ADMINISTRATOR)
    enrolled_device(user, trusted=False)

    response = verified(Client(), user).get(ENTRY)

    assert response.status_code == 403
    assert SECOND_FACTOR_TEXT in _text(response)


def test_the_page_changes_no_answer_an_account_with_the_permission_gets(
    user_with_roles: UserFactory,
) -> None:
    assert verified(Client(), user_with_roles(Role.ADMINISTRATOR)).get(ENTRY).status_code == 200


@pytest.mark.urls(__name__)
def test_a_refusal_page_shows_no_reason_given_by_the_code(client: Client) -> None:
    response = client.get("/denied/")

    assert response.status_code == 403
    assert "TEST internal reason" not in _text(response)


# --- 404 and 500 --------------------------------------------------------------------


def test_no_such_page_is_answered_without_the_path_or_a_reason(client: Client) -> None:
    response = client.get("/TEST-no-such-page/<script>/")

    assert response.status_code == 404
    page = _text(response)
    assert "Page not found" in page
    assert "TEST-no-such-page" not in page
    assert "<script>" not in page


@pytest.mark.urls(__name__)
def test_a_failure_is_answered_with_a_page_that_says_nothing_about_it() -> None:
    response = Client(raise_request_exception=False).get("/failing/")

    assert response.status_code == 500
    page = _text(response)
    assert "Something went wrong" in page
    assert "TEST internal detail" not in page
    assert "RuntimeError" not in page
    assert "Traceback" not in page
    assert _never_cached(response)


def test_the_failure_page_is_rendered_without_the_request() -> None:
    """Nothing that may itself have failed, such as the session or the database, is used."""
    response = errors.server_error(RequestFactory().get("/"))

    assert response.status_code == 500
    assert "Something went wrong" in _text(response)


# --- L2: a refusal is logged once with its traceback --------------------------------


def _request_log(client: Client, method: str, url: str) -> tuple[int, list[dict[str, Any]]]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        response = getattr(client, method)(url)
    finally:
        root.removeHandler(handler)
        root.setLevel(level)
    return response.status_code, [json.loads(line) for line in stream.getvalue().splitlines()]


def test_a_refusal_is_logged_as_an_event_and_once_more_without_a_traceback(
    client: Client,
) -> None:
    status, entries = _request_log(client, "get", BROWSE)

    assert status == 403
    (denied,) = [entry for entry in entries if entry.get("event") == "access.denied"]
    assert denied["permission"] == "registry.read"
    (summary,) = [entry for entry in entries if entry["logger"] == "django.request"]
    assert summary["status_code"] == 403
    assert "exception" not in summary
    assert not any("exception" in entry for entry in entries)


@pytest.mark.urls(__name__)
def test_a_refusal_raised_inside_a_view_is_logged_without_a_traceback() -> None:
    """However the PermissionDenied arose, the summary line stays and its traceback goes."""
    status, entries = _request_log(Client(), "get", "/denied/")

    assert status == 403
    (summary,) = [entry for entry in entries if entry["logger"] == "django.request"]
    assert summary["status_code"] == 403
    assert "exception" not in summary


@pytest.mark.urls(__name__)
def test_a_failure_keeps_its_traceback() -> None:
    status, entries = _request_log(Client(raise_request_exception=False), "get", "/failing/")

    assert status == 500
    (summary,) = [entry for entry in entries if entry["logger"] == "django.request"]
    assert "RuntimeError: TEST internal detail" in summary["exception"]
