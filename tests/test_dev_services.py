"""Smoke tests for the local development services.

They prove that the PostgreSQL and Redis containers from docker-compose.yml are
reachable with the credentials in the environment, and that both refuse a
client without valid credentials. They contain no application behaviour.
"""

import os

import psycopg
import pytest
import redis

pytestmark = pytest.mark.services

CONNECT_TIMEOUT_SECONDS = 5


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"{name} is not set; run with `uv run --env-file .env pytest`")
    return value


def _postgres_connect(password: str) -> psycopg.Connection:
    return psycopg.connect(
        host=_env("POSTGRES_HOST"),
        port=int(_env("POSTGRES_PORT")),
        dbname=_env("POSTGRES_DB"),
        user=_env("POSTGRES_USER"),
        password=password,
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
    )


def _redis_client(password: str | None) -> redis.Redis:
    return redis.Redis(
        host=_env("REDIS_HOST"),
        port=int(_env("REDIS_PORT")),
        password=password,
        socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
        socket_timeout=CONNECT_TIMEOUT_SECONDS,
    )


def test_postgres_accepts_configured_credentials() -> None:
    with _postgres_connect(_env("POSTGRES_PASSWORD")) as connection:
        row = connection.execute(
            "SELECT current_database(), current_setting('server_encoding')"
        ).fetchone()

    assert row == (_env("POSTGRES_DB"), "UTF8")


def test_postgres_rejects_wrong_password() -> None:
    with pytest.raises(psycopg.OperationalError):
        _postgres_connect(_env("POSTGRES_PASSWORD") + "-wrong").close()


def test_redis_accepts_configured_password() -> None:
    client = _redis_client(_env("REDIS_PASSWORD"))
    try:
        assert client.ping() is True
    finally:
        client.close()


def test_redis_rejects_unauthenticated_client() -> None:
    client = _redis_client(None)
    try:
        with pytest.raises(redis.AuthenticationError):
            client.ping()
    finally:
        client.close()
