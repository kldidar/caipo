import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest import mock

import pytest
from django.db import OperationalError, connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

LIVE = "/health/live/"
READY = "/health/ready/"

# Stands in for the connection details a real driver error can carry.
TEST_DRIVER_DETAIL = 'TEST connection to "db.internal.test" failed for user "TEST_user"'


@contextmanager
def _database_down() -> Iterator[None]:
    with mock.patch.object(
        connection, "cursor", side_effect=OperationalError(TEST_DRIVER_DETAIL), autospec=True
    ):
        yield


def _json(response: Any) -> Any:
    assert response["Content-Type"] == "application/json"
    return json.loads(response.content)


def test_live_reports_ok_without_touching_the_database(client: Client) -> None:
    # No database access is granted to this test, so a query would fail it.
    response = client.get(LIVE)

    assert response.status_code == 200
    assert _json(response) == {"status": "ok"}


def test_live_stays_ok_when_the_database_is_down(client: Client) -> None:
    with _database_down():
        response = client.get(LIVE)

    assert response.status_code == 200
    assert _json(response) == {"status": "ok"}


@pytest.mark.services
@pytest.mark.django_db
def test_ready_reports_ok_after_querying_the_database(client: Client) -> None:
    with CaptureQueriesContext(connection) as queries:
        response = client.get(READY)

    assert response.status_code == 200
    assert _json(response) == {"status": "ok", "checks": {"database": "ok"}}
    assert [query["sql"] for query in queries] == ["SELECT 1"]


def test_ready_reports_unavailable_when_the_database_is_down(client: Client) -> None:
    with _database_down():
        response = client.get(READY)

    assert response.status_code == 503
    assert _json(response) == {"status": "unavailable", "checks": {"database": "unavailable"}}


def test_ready_failure_exposes_no_error_detail(
    client: Client, caplog: pytest.LogCaptureFixture
) -> None:
    with _database_down(), caplog.at_level(logging.ERROR, logger="caipo.web.health"):
        response = client.get(READY)

    assert TEST_DRIVER_DETAIL not in response.content.decode()
    (record,) = [record for record in caplog.records if record.name == "caipo.web.health"]
    assert record.__dict__["event"] == "health.readiness_failed"
    assert record.__dict__["error_type"] == "OperationalError"
    assert TEST_DRIVER_DETAIL not in record.getMessage()
    assert record.exc_info is None


@pytest.mark.parametrize("path", [LIVE, READY])
def test_health_responses_are_not_cached(client: Client, path: str) -> None:
    with _database_down():
        response = client.get(path)

    assert "no-store" in response["Cache-Control"]


@pytest.mark.parametrize("path", [LIVE, READY])
@pytest.mark.parametrize("method", ["head", "options", "post", "put", "patch", "delete"])
def test_health_endpoints_accept_only_get(client: Client, path: str, method: str) -> None:
    response = getattr(client, method)(path)

    assert response.status_code == 405


@pytest.mark.parametrize("path", [LIVE, READY])
def test_health_endpoints_set_no_cookie(client: Client, path: str) -> None:
    with _database_down():
        response = client.get(path)

    assert not response.cookies
