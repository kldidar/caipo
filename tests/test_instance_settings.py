"""The settings of the public demonstration instance (ADR-0024 points 5 to 7)."""

import base64
import runpy
import sys
from collections.abc import Iterator
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from caipo.config.settings import base

# Visibly synthetic: these stand in for the instance's secrets and protect nothing.
TEST_PUBLIC_URL = "https://caipo.test"
TEST_SHARED_PASSWORD = "TEST-shared-password"


def _instance() -> dict[str, Any]:
    return runpy.run_module("caipo.config.settings.instance")


@pytest.fixture
def instance_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name, value in {
        "DJANGO_SECRET_KEY": "TEST-secret-key-used-only-by-the-instance-tests-0123456789",
        "TOTP_ENCRYPTION_KEY": base64.urlsafe_b64encode(bytes(range(32))).decode(),
        "DJANGO_ALLOWED_HOSTS": "caipo.test",
        "CAIPO_PUBLIC_URL": TEST_PUBLIC_URL,
        "POSTGRES_DB": "TEST_db",
        "POSTGRES_USER": "TEST_user",
        "POSTGRES_PASSWORD": "TEST-database-password",
        "POSTGRES_HOST": "db.test",
        "POSTGRES_PORT": "5432",
        "GROQ_API_KEY": "TEST-groq-key-not-real",
        "CAIPO_SHARED_PASSWORD": TEST_SHARED_PASSWORD,
    }.items():
        monkeypatch.setenv(name, value)
    loaded = set(sys.modules)
    yield
    # The instance's settings import the production module; the other
    # settings tests run that module afresh, and must find it not imported.
    for name in set(sys.modules) - loaded:
        if name.startswith("caipo.config.settings."):
            del sys.modules[name]


@pytest.mark.usefixtures("instance_environment")
def test_the_instance_is_production_hardened_for_one_host_behind_a_proxy() -> None:
    instance = _instance()

    assert instance["DEBUG"] is False
    assert instance["SECURE_PROXY_SSL_HEADER"] == ("HTTP_X_FORWARDED_PROTO", "https")
    assert instance["SECURE_SSL_REDIRECT"] is True
    assert instance["SECURE_REDIRECT_EXEMPT"] == [r"^health/"]
    assert instance["SECURE_HSTS_SECONDS"] == 31_536_000
    assert instance["CSRF_TRUSTED_ORIGINS"] == [TEST_PUBLIC_URL]
    assert instance["SESSION_COOKIE_SECURE"] is True and instance["CSRF_COOKIE_SECURE"] is True
    assert instance["DATABASES"]["default"]["OPTIONS"]["sslmode"] == "require"


@pytest.mark.usefixtures("instance_environment")
def test_static_files_are_served_right_after_the_security_middleware() -> None:
    middleware = _instance()["MIDDLEWARE"]

    security = middleware.index("django.middleware.security.SecurityMiddleware")
    assert middleware[security + 1] == "whitenoise.middleware.WhiteNoiseMiddleware"
    assert "whitenoise.middleware.WhiteNoiseMiddleware" not in base.MIDDLEWARE, (
        "the instance builds its own list and changes nothing it imports"
    )


@pytest.mark.usefixtures("instance_environment")
def test_the_instance_closes_what_sends_a_message_and_publishes_its_shared_account() -> None:
    instance = _instance()

    assert instance["DEMONSTRATION_INSTANCE"] is True
    assert instance["REGISTRATION_OPEN"] is False
    assert instance["PASSWORD_RESET_OPEN"] is False
    assert instance["SHARED_ACCOUNT_EMAIL"] == "demo.reader@caipo.test"
    assert instance["SHARED_ACCOUNT_PASSWORD"] == TEST_SHARED_PASSWORD
    assert instance["TRUSTED_PROXY_COUNT"] == 1


@pytest.mark.usefixtures("instance_environment")
def test_the_instance_does_not_start_without_the_shared_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CAIPO_SHARED_PASSWORD")

    with pytest.raises(ImproperlyConfigured, match="CAIPO_SHARED_PASSWORD"):
        _instance()


def test_every_other_environment_has_no_instance_switch_turned() -> None:
    assert base.DEMONSTRATION_INSTANCE is False
    assert base.REGISTRATION_OPEN is True and base.PASSWORD_RESET_OPEN is True
    assert base.SHARED_ACCOUNT_EMAIL == "" and base.SHARED_ACCOUNT_PASSWORD == ""
    assert base.TRUSTED_PROXY_COUNT == 0
