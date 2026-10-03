from datetime import timedelta

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.db import IntegrityError, transaction

from caipo.accounts.models import AccountStatus, User

pytestmark = [pytest.mark.services, pytest.mark.django_db]

# Visibly synthetic fixture values (CLAUDE.md, research integrity requirements).
EMAIL = "test.reader@caipo.test"
PASSWORD = "TEST-passphrase-for-fixtures-only"


def test_it_is_the_configured_user_model() -> None:
    assert get_user_model() is User
    assert User.USERNAME_FIELD == "email"


def test_create_user_stores_an_active_user_identified_by_email() -> None:
    user = User.objects.create_user(EMAIL, PASSWORD)

    stored = User.objects.get(pk=user.pk)
    assert stored.email == EMAIL
    assert stored.get_username() == EMAIL
    assert str(stored) == EMAIL
    assert stored.is_active is True
    assert stored.last_login is None


@pytest.mark.parametrize(
    "given",
    [
        "Test.Reader@CAIPO.Test",
        "  test.reader@caipo.test  ",
        "TEST.READER@CAIPO.TEST",
        # Full-width letters: a compatibility form that displays like the ASCII address.
        "ｔｅｓｔ.reader@caipo.test",
    ],
)
def test_create_user_normalizes_the_email(given: str) -> None:
    assert User.objects.create_user(given, PASSWORD).email == EMAIL


@pytest.mark.parametrize("email", ["", "   "])
def test_create_user_requires_an_email(email: str) -> None:
    with pytest.raises(ValueError, match="email"):
        User.objects.create_user(email, PASSWORD)

    assert not User.objects.exists()


def test_password_is_stored_as_an_argon2_hash() -> None:
    user = User.objects.create_user(EMAIL, PASSWORD)

    assert user.password.startswith("argon2$")
    assert PASSWORD not in user.password
    assert user.check_password(PASSWORD) is True
    assert user.check_password(PASSWORD + "-wrong") is False


def test_user_created_without_a_password_cannot_authenticate() -> None:
    user = User.objects.create_user(EMAIL)

    assert user.has_usable_password() is False
    assert authenticate(email=EMAIL, password="") is None


def test_timestamps_are_timezone_aware_utc() -> None:
    user = User.objects.create_user(EMAIL, PASSWORD)

    assert user.created_at.utcoffset() == timedelta(0)
    assert user.updated_at.utcoffset() == timedelta(0)


def test_saving_moves_updated_at_and_keeps_created_at() -> None:
    user = User.objects.create_user(EMAIL, PASSWORD)
    created_at, updated_at = user.created_at, user.updated_at

    user.status = AccountStatus.DISABLED
    user.save()

    stored = User.objects.get(pk=user.pk)
    assert stored.created_at == created_at
    assert stored.updated_at > updated_at


def test_email_is_unique_regardless_of_case() -> None:
    User.objects.create_user(EMAIL, PASSWORD)

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user(EMAIL.upper(), PASSWORD)

    assert User.objects.count() == 1


def test_database_rejects_a_case_variant_written_without_the_manager() -> None:
    User.objects.create_user(EMAIL, PASSWORD)

    with (
        pytest.raises(IntegrityError, match="accounts_user_email_case_insensitive"),
        transaction.atomic(),
    ):
        User.objects.bulk_create([User(email=EMAIL.upper())])

    assert User.objects.count() == 1


def test_lookup_by_natural_key_ignores_case() -> None:
    user = User.objects.create_user(EMAIL, PASSWORD)

    assert User.objects.get_by_natural_key(" Test.Reader@Caipo.TEST ") == user


def test_authentication_accepts_the_email_and_password() -> None:
    user = User.objects.create_user(EMAIL, PASSWORD)

    assert authenticate(email=EMAIL.upper(), password=PASSWORD) == user


def test_authentication_rejects_a_wrong_password() -> None:
    User.objects.create_user(EMAIL, PASSWORD)

    assert authenticate(email=EMAIL, password=PASSWORD + "-wrong") is None


@pytest.mark.parametrize("status", [AccountStatus.DISABLED, AccountStatus.PENDING_VERIFICATION])
def test_authentication_rejects_a_user_that_is_not_active(status: AccountStatus) -> None:
    user = User.objects.create_user(EMAIL, PASSWORD)
    assert authenticate(email=EMAIL, password=PASSWORD) == user
    User.objects.filter(pk=user.pk).update(
        status=status,
        # An account that awaits verification has never been active.
        activated_at=None if status == AccountStatus.PENDING_VERIFICATION else user.activated_at,
    )

    assert authenticate(email=EMAIL, password=PASSWORD) is None


def test_there_are_no_staff_or_superuser_privileges() -> None:
    # Columns only: the relation from RoleEvent back to its user is not a field of the user.
    field_names = {field.name for field in User._meta.concrete_fields}

    assert field_names == {
        "id",
        "password",
        "last_login",
        "email",
        "status",
        "email_verified_at",
        "activated_at",
        "created_at",
        "updated_at",
    }
    assert not hasattr(User.objects, "create_superuser")
