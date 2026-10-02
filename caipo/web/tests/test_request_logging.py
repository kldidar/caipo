"""Every log line of a request carries that request's correlation ID (NFR-06)."""

import io
import json
import logging
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse
from django.test import Client
from django.urls import path

from caipo.core.correlation import get_correlation_id
from caipo.core.structured_logging import JsonFormatter
from caipo.web.access import public

seen: list[str | None] = []


@public
def ok_view(request: HttpRequest) -> HttpResponse:
    seen.append(get_correlation_id())
    logging.getLogger("caipo.test").info("TEST inside the view")
    return HttpResponse("TEST ok")


@public
def failing_view(request: HttpRequest) -> HttpResponse:
    raise RuntimeError("TEST failure")


@public
def not_found_view(request: HttpRequest) -> HttpResponse:
    raise Http404


@public
def denied_view(request: HttpRequest) -> HttpResponse:
    raise PermissionDenied


@public
def error_status_view(request: HttpRequest) -> HttpResponse:
    return HttpResponse(status=409)


def undeclared_view(request: HttpRequest) -> HttpResponse:
    return HttpResponse()


urlpatterns = [
    path("ok/", ok_view),
    path("failing/", failing_view),
    path("not-found/", not_found_view),
    path("denied/", denied_view),
    path("error-status/", error_status_view),
    path("undeclared/", undeclared_view),
]


def _request_log(url: str) -> tuple[int, list[dict[str, Any]]]:
    """Make one request and return its status and the log lines it produced."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        response = Client(raise_request_exception=False).get(url)
    finally:
        root.removeHandler(handler)
        root.setLevel(level)
    return response.status_code, [json.loads(line) for line in stream.getvalue().splitlines()]


@pytest.mark.urls(__name__)
def test_a_request_runs_under_a_correlation_id_that_ends_with_it() -> None:
    seen.clear()

    status, entries = _request_log("/ok/")

    assert status == 200
    (correlation_id,) = seen
    assert correlation_id is not None
    assert [entry["correlation_id"] for entry in entries] == [correlation_id]
    assert get_correlation_id() is None


@pytest.mark.urls(__name__)
def test_each_request_gets_its_own_correlation_id() -> None:
    seen.clear()

    _request_log("/ok/")
    _request_log("/ok/")

    assert len(set(seen)) == 2


@pytest.mark.urls(__name__)
@pytest.mark.parametrize(
    ("url", "expected_status"),
    [
        ("/failing/", 500),
        ("/not-found/", 404),
        ("/no-such-route/", 404),
        ("/denied/", 403),
        ("/error-status/", 409),
        ("/undeclared/", 403),
    ],
)
def test_error_responses_are_logged_with_the_correlation_id(url: str, expected_status: int) -> None:
    status, entries = _request_log(url)

    assert status == expected_status
    assert entries, "an error response must leave a log line"
    correlation_ids = {entry["correlation_id"] for entry in entries}
    assert len(correlation_ids) == 1
    assert None not in correlation_ids


@pytest.mark.urls(__name__)
def test_the_request_object_itself_is_never_logged() -> None:
    _, entries = _request_log("/not-found/")

    assert all("request" not in entry for entry in entries)
