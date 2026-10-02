"""Django reaches PostgreSQL, and the schema matches the models."""

import pytest
from django.core.management import call_command
from django.db import connection

pytestmark = [pytest.mark.services, pytest.mark.django_db]


def test_django_connects_to_postgresql() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        row = cursor.fetchone()

    assert row == (1,)
    assert connection.vendor == "postgresql"


def test_tests_run_in_a_separate_test_database() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        (name,) = cursor.fetchone()

    assert name.startswith("test_")


def test_database_is_utf8_and_the_session_is_utc() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('server_encoding'), current_setting('TimeZone')")
        row = cursor.fetchone()

    assert row == ("UTF8", "UTC")


def test_migrations_match_the_models() -> None:
    # Exits with a non-zero status, raising SystemExit, if a model change has
    # no migration.
    call_command("makemigrations", check=True, dry_run=True)
