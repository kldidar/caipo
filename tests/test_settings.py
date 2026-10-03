"""The settings the suite runs under, and the rules each environment module must keep."""

import base64
import runpy
from datetime import timedelta
from typing import Any

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from caipo.config.settings import base
from caipo.core.structured_logging import JsonFormatter

SETTINGS_PACKAGE = "caipo.config.settings"

# Visibly synthetic: these stand in for deployment secrets and protect nothing.
TEST_SECRET_KEY = "TEST-secret-key-used-only-by-the-settings-tests-0123456789"
TEST_DATABASE_PASSWORD = "TEST-database-password"
TEST_TOTP_KEY_BYTES = bytes(range(32))
TEST_TOTP_KEY = base64.urlsafe_b64encode(TEST_TOTP_KEY_BYTES).decode()


def _load(environment: str) -> dict[str, Any]:
    """Execute a settings module afresh under the current process environment."""
    return runpy.run_module(f"{SETTINGS_PACKAGE}.{environment}")


@pytest.fixture
def deployment_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "DJANGO_SECRET_KEY": TEST_SECRET_KEY,
        "TOTP_ENCRYPTION_KEY": TEST_TOTP_KEY,
        "DJANGO_ALLOWED_HOSTS": "caipo.test, www.caipo.test",
        "POSTGRES_DB": "TEST_db",
        "POSTGRES_USER": "TEST_user",
        "POSTGRES_PASSWORD": TEST_DATABASE_PASSWORD,
        "POSTGRES_HOST": "db.test",
        "POSTGRES_PORT": "5432",
    }.items():
        monkeypatch.setenv(name, value)


def test_suite_runs_under_the_testing_settings() -> None:
    assert settings.SETTINGS_MODULE == f"{SETTINGS_PACKAGE}.testing"
    assert settings.DEBUG is False


def test_time_is_utc_and_timezone_aware() -> None:
    assert settings.USE_TZ is True
    assert settings.TIME_ZONE == "UTC"


def test_interface_is_english_with_internationalisation_enabled() -> None:
    assert settings.USE_I18N is True
    assert settings.LANGUAGE_CODE == "en"
    assert settings.LANGUAGES == [("en", "English")]


def test_database_is_postgresql() -> None:
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"


def test_custom_user_model_is_configured() -> None:
    assert settings.AUTH_USER_MODEL == "accounts.User"


def test_passwords_are_hashed_with_argon2_only() -> None:
    assert settings.PASSWORD_HASHERS == ["django.contrib.auth.hashers.Argon2PasswordHasher"]


def test_django_admin_is_not_installed() -> None:
    assert "django.contrib.admin" not in settings.INSTALLED_APPS


def test_cookies_are_secure_by_default() -> None:
    assert settings.SESSION_COOKIE_SECURE is True
    assert settings.CSRF_COOKIE_SECURE is True
    assert settings.SESSION_COOKIE_HTTPONLY is True


def test_logs_are_json_on_standard_output() -> None:
    logging_config: dict[str, Any] = settings.LOGGING
    formatter = logging_config["formatters"]["json"]["()"]
    handler = logging_config["handlers"]["stdout"]

    assert formatter == f"{JsonFormatter.__module__}.{JsonFormatter.__qualname__}"
    assert handler["formatter"] == "json"
    assert handler["stream"] == "ext://sys.stdout"
    assert logging_config["root"]["handlers"] == ["stdout"]


def test_base_settings_hold_no_secret_and_no_database() -> None:
    assert not hasattr(base, "SECRET_KEY")
    assert not hasattr(base, "TOTP_ENCRYPTION_KEY")
    assert not hasattr(base, "DATABASES")
    assert base.DEBUG is False
    assert base.ALLOWED_HOSTS == []


@pytest.mark.usefixtures("deployment_environment")
def test_production_reads_its_configuration_from_the_environment() -> None:
    production = _load("production")

    assert production["DEBUG"] is False
    assert production["SECRET_KEY"] == TEST_SECRET_KEY
    assert production["TOTP_ENCRYPTION_KEY"] == TEST_TOTP_KEY_BYTES
    assert production["ALLOWED_HOSTS"] == ["caipo.test", "www.caipo.test"]
    assert production["DATABASES"]["default"]["PASSWORD"] == TEST_DATABASE_PASSWORD
    assert production["SESSION_COOKIE_SECURE"] is True
    assert production["CSRF_COOKIE_SECURE"] is True


@pytest.mark.usefixtures("deployment_environment")
@pytest.mark.parametrize(
    "variable",
    [
        "DJANGO_SECRET_KEY",
        "TOTP_ENCRYPTION_KEY",
        "DJANGO_ALLOWED_HOSTS",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST",
    ],
)
@pytest.mark.parametrize("state", ["unset", "empty"])
def test_production_refuses_to_start_without_a_required_variable(
    monkeypatch: pytest.MonkeyPatch, variable: str, state: str
) -> None:
    if state == "unset":
        monkeypatch.delenv(variable)
    else:
        monkeypatch.setenv(variable, "")

    with pytest.raises(ImproperlyConfigured, match=variable):
        _load("production")


@pytest.mark.usefixtures("deployment_environment")
@pytest.mark.parametrize(
    "key",
    ["TEST-short", "django-insecure-" + "TEST" * 20, "t" * 60],
    ids=["short", "django-insecure-prefix", "one-repeated-character"],
)
def test_production_refuses_a_weak_secret_key(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    monkeypatch.setenv("DJANGO_SECRET_KEY", key)

    with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY") as error:
        _load("production")

    assert key not in str(error.value)


@pytest.mark.usefixtures("deployment_environment")
@pytest.mark.parametrize("environment", ["production", "development"])
@pytest.mark.parametrize(
    "key",
    [
        "TEST-not-base64!",
        base64.urlsafe_b64encode(bytes(range(16))).decode(),
        base64.urlsafe_b64encode(bytes(range(33))).decode(),
        base64.urlsafe_b64encode(bytes(32)).decode(),
        TEST_TOTP_KEY + "TEST",
        "ключ-TEST",
    ],
    ids=["not-base64", "too-short", "too-long", "all-zero", "trailing-text", "not-ascii"],
)
def test_an_unusable_totp_encryption_key_stops_start_up(
    monkeypatch: pytest.MonkeyPatch, environment: str, key: str
) -> None:
    monkeypatch.setenv("TOTP_ENCRYPTION_KEY", key)

    with pytest.raises(ImproperlyConfigured, match="TOTP_ENCRYPTION_KEY") as error:
        _load(environment)

    assert key not in str(error.value)


@pytest.mark.usefixtures("deployment_environment")
def test_development_has_no_built_in_totp_encryption_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TOTP_ENCRYPTION_KEY")

    with pytest.raises(ImproperlyConfigured, match="TOTP_ENCRYPTION_KEY"):
        _load("development")


def test_the_suite_generates_its_own_totp_encryption_key() -> None:
    assert isinstance(settings.TOTP_ENCRYPTION_KEY, bytes)
    assert len(settings.TOTP_ENCRYPTION_KEY) == 32
    assert settings.TOTP_ENCRYPTION_KEY != TEST_TOTP_KEY_BYTES


def test_second_factor_limits_are_repository_settings() -> None:
    assert settings.TOTP_ISSUER == "CAIPO"
    assert settings.TOTP_DRIFT_STEPS == 1
    assert settings.MFA_ENROLLMENT_LIFETIME == timedelta(minutes=10)
    assert settings.MFA_CHALLENGE_LIFETIME == timedelta(minutes=5)
    assert settings.MFA_THROTTLE_WINDOW == timedelta(minutes=15)
    assert settings.MFA_THROTTLE_FAILURES == 5


@pytest.mark.usefixtures("deployment_environment")
@pytest.mark.parametrize("hosts", ["*", "caipo.test,*", " , "])
def test_production_refuses_wildcard_or_empty_allowed_hosts(
    monkeypatch: pytest.MonkeyPatch, hosts: str
) -> None:
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", hosts)

    with pytest.raises(ImproperlyConfigured, match="DJANGO_ALLOWED_HOSTS"):
        _load("production")


@pytest.mark.usefixtures("deployment_environment")
def test_a_missing_variable_error_does_not_reveal_other_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DJANGO_ALLOWED_HOSTS")

    with pytest.raises(ImproperlyConfigured) as error:
        _load("production")

    assert TEST_SECRET_KEY not in str(error.value)
    assert TEST_TOTP_KEY not in str(error.value)
    assert TEST_DATABASE_PASSWORD not in str(error.value)


@pytest.mark.usefixtures("deployment_environment")
def test_debug_is_enabled_only_in_development() -> None:
    development = _load("development")

    assert development["DEBUG"] is True
    assert development["ALLOWED_HOSTS"] == ["localhost", "127.0.0.1", "[::1]"]
    assert _load("production")["DEBUG"] is False


@pytest.mark.usefixtures("deployment_environment")
def test_development_has_no_built_in_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DJANGO_SECRET_KEY")

    with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY"):
        _load("development")


def test_sessions_are_server_side_and_bounded() -> None:
    assert settings.SESSION_ENGINE == "django.contrib.sessions.backends.db"
    assert settings.SESSION_COOKIE_AGE == 12 * 60 * 60
    assert settings.SESSION_EXPIRE_AT_BROWSER_CLOSE is True
    assert settings.SESSION_COOKIE_SAMESITE == "Lax"
    assert settings.CSRF_COOKIE_SAMESITE == "Lax"
    assert settings.LOGIN_URL == "login"


def test_csrf_and_session_middleware_are_in_place_and_in_order() -> None:
    middleware = settings.MIDDLEWARE
    session = middleware.index("django.contrib.sessions.middleware.SessionMiddleware")
    csrf = middleware.index("django.middleware.csrf.CsrfViewMiddleware")
    authentication = middleware.index("django.contrib.auth.middleware.AuthenticationMiddleware")
    access = middleware.index("caipo.web.middleware.AccessDeclarationMiddleware")

    assert session < csrf < authentication < access


def _settings_that_differ_from_base(environment: str) -> set[str]:
    loaded = _load(environment)
    names = {name for name in loaded if name.isupper()} | {
        name for name in vars(base) if name.isupper()
    }
    missing = object()
    return {name for name in names if loaded.get(name, missing) != getattr(base, name, missing)}


@pytest.mark.usefixtures("deployment_environment")
def test_development_relaxes_only_what_local_http_requires() -> None:
    assert _settings_that_differ_from_base("development") == {
        "SECRET_KEY",
        "TOTP_ENCRYPTION_KEY",
        "DATABASES",
        "ALLOWED_HOSTS",
        "DEBUG",
        # The development server speaks plain HTTP.
        "SESSION_COOKIE_SECURE",
        "CSRF_COOKIE_SECURE",
    }


@pytest.mark.usefixtures("deployment_environment")
def test_production_changes_nothing_but_what_comes_from_the_environment() -> None:
    assert _settings_that_differ_from_base("production") == {
        "SECRET_KEY",
        "TOTP_ENCRYPTION_KEY",
        "DATABASES",
        "ALLOWED_HOSTS",
    }
