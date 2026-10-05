"""Deny by default: a view without an access declaration is refused (NFR-11)."""

import logging
from collections.abc import Iterator

import pytest
from django.http import HttpRequest, HttpResponse
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver, path

from caipo.web.access import PUBLIC, declared_access, public

calls: list[str] = []


def undeclared_view(request: HttpRequest) -> HttpResponse:
    calls.append("undeclared")
    return HttpResponse("TEST undeclared")


@public
def public_view(request: HttpRequest) -> HttpResponse:
    calls.append("public")
    return HttpResponse("TEST public")


urlpatterns = [
    path("undeclared/", undeclared_view),
    path("public/", public_view),
]


@pytest.fixture(autouse=True)
def _reset_calls() -> Iterator[None]:
    calls.clear()
    yield
    calls.clear()


def _patterns(resolver: URLResolver) -> Iterator[URLPattern]:
    for entry in resolver.url_patterns:
        if isinstance(entry, URLResolver):
            yield from _patterns(entry)
        else:
            yield entry


@pytest.mark.urls(__name__)
def test_a_view_without_a_declaration_is_refused_before_it_runs(
    client: Client, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="caipo.web.middleware"):
        response = client.get("/undeclared/")

    assert response.status_code == 403
    assert b"TEST undeclared" not in response.content
    assert calls == []
    (record,) = [record for record in caplog.records if record.name == "caipo.web.middleware"]
    assert record.__dict__["event"] == "access.undeclared_view"
    assert record.__dict__["view"] == "undeclared_view"


@pytest.mark.urls(__name__)
def test_a_public_view_is_served_to_an_anonymous_visitor(client: Client) -> None:
    response = client.get("/public/")

    assert response.status_code == 200
    assert calls == ["public"]


def test_declared_access_reads_the_declaration() -> None:
    assert declared_access(public_view) == PUBLIC
    assert declared_access(undeclared_view) is None


def test_every_routed_view_declares_its_access() -> None:
    patterns = list(_patterns(get_resolver()))

    assert patterns, "the URL configuration has no views to check"
    undeclared = [
        str(entry.pattern) for entry in patterns if declared_access(entry.callback) is None
    ]
    assert undeclared == []


def test_only_the_health_and_sign_in_endpoints_are_public() -> None:
    public_routes = {
        entry.name
        for entry in _patterns(get_resolver())
        if declared_access(entry.callback) == PUBLIC
    }

    # Signing in, with or without a second factor, must be reachable by someone
    # who is not signed in, and signing out when not signed in must be harmless.
    # Activating an account is done by someone whose account cannot be signed
    # in to yet, and a password is reset by someone who cannot sign in
    # (ADR-0016). Recovery of a lost second factor is asked for from a sign-in
    # that awaits its code, by someone who is therefore not signed in
    # (ADR-0017).
    assert public_routes == {
        "health-live",
        "health-ready",
        "login",
        "login-verify",
        "login-recover",
        "logout",
        "activate",
        "password-reset",
        "password-reset-confirm",
    }
