"""Fixtures for tests that need users with roles, in this app and in the apps above it.

Registered for the whole suite by the conftest.py at the repository root.
"""

import logging
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from itertools import count

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.twofactor.totp import TOTP
from django.utils import timezone

from caipo.accounts import totp
from caipo.accounts.authorization import Assurance, Role
from caipo.accounts.models import RoleEvent, RoleEventType, TotpDevice, TotpDeviceState, User
from caipo.accounts.selectors import AuthenticationContext

type UserFactory = Callable[..., User]
type Clock = Callable[[timedelta], None]

# Visibly synthetic: the secret of every second factor these helpers create.
TEST_TOTP_SECRET = b"TEST-totp-secret-000"


def code_at(at: datetime | None = None, *, secret: bytes = TEST_TOTP_SECRET) -> str:
    """Return the code an authenticator application would show at a time, by default now.

    Computed with the library directly, not with the application's own
    verification code, so that the two are checked against each other.
    """
    moment = at or timezone.now()
    # The noqa below: TOTP is HMAC-SHA1 by RFC 6238.
    generator = TOTP(secret, 6, hashes.SHA1(), 30)  # noqa: S303
    return generator.generate(int(moment.timestamp())).decode()


_STANDARD_RECORD_ATTRIBUTES = frozenset(vars(logging.makeLogRecord({})))


def logged(records: Iterable[logging.LogRecord]) -> str:
    """Return what callers put into log records: each message and its extra fields.

    The attributes logging itself adds (times, thread and process numbers) are
    left out. They are long numbers in which a six-digit code can occur by
    chance.
    """

    def extra(record: logging.LogRecord) -> dict[str, object]:
        return {
            name: value
            for name, value in vars(record).items()
            if name not in _STANDARD_RECORD_ATTRIBUTES
        }

    return " ".join(f"{record.getMessage()} {extra(record)}" for record in records)


def signed_in(user: User) -> AuthenticationContext:
    """Return the context of the account after a sign-in with its password alone."""
    return AuthenticationContext(user, Assurance.PASSWORD_AUTHENTICATED)


def enrolled_device(
    user: User, *, secret: bytes = TEST_TOTP_SECRET, trusted: bool = True
) -> TotpDevice:
    """Return the account's active second factor, creating it if it has none.

    The row is written directly, with the real encryption, as roles are
    seeded directly: the services under test are not used to set up their own
    preconditions. Its last used step is in the distant past, so any current
    code is fresh. It is trusted, as if a synthetic Administrator had approved
    its enrolment, unless `trusted` is false: then it is what an account
    enrols on its password alone.
    """
    ciphertext, key_id = totp.encrypt_secret(secret, user_id=user.pk)
    now = timezone.now()
    approval = {}
    if trusted:
        approver, _ = User.objects.get_or_create(email="test.approver@caipo.test")
        approval = {"approved_at": now, "approved_by": approver}
    device, _ = TotpDevice.objects.get_or_create(
        user=user,
        defaults={
            "state": TotpDeviceState.ACTIVE,
            "secret_ciphertext": ciphertext,
            "key_id": key_id,
            "last_used_step": 0,
            "confirmed_at": now,
            **approval,
        },
    )
    return device


def verified(user: User) -> AuthenticationContext:
    """Return the context of the account after a sign-in with password and second factor.

    The account gets a real, active, trusted second factor, and the context is
    the one the verification service returns for it. Nothing in the authorization
    decision is replaced: it reads this device like any other.
    """
    return AuthenticationContext(user, Assurance.MFA_VERIFIED, enrolled_device(user).pk)


def approving_administrator() -> AuthenticationContext:
    """Return the verified context of a synthetic Administrator who can approve enrolments.

    The account is created on first use, with its role and its trusted second
    factor written directly, like every other precondition here.
    """
    user, created = User.objects.get_or_create(email="test.approving.administrator@caipo.test")
    if created:
        seeder, _ = User.objects.get_or_create(email="test.seed@caipo.test")
        RoleEvent.objects.create(
            user=user,
            role=Role.ADMINISTRATOR,
            event_type=RoleEventType.GRANTED,
            actor=seeder,
            reason="TEST fixture",
        )
    return verified(user)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    """Return a function that moves the application's clock forward."""
    current = [timezone.now()]

    def now() -> datetime:
        return current[0]

    def advance(by: timedelta) -> None:
        current[0] += by

    monkeypatch.setattr(timezone, "now", now)
    return advance


@pytest.fixture
def user_with_roles(db: None) -> UserFactory:
    """Return a factory for synthetic users holding the given roles.

    Roles are seeded as RoleEvent rows written directly, attributed to a
    synthetic seeding account. This stands in for the bootstrap of the first
    Administrator; the services under test are not used to set up their own
    preconditions.
    """
    numbers = count(1)

    def make(*roles: Role, is_active: bool = True) -> User:
        user = User.objects.create_user(f"test.user{next(numbers)}@caipo.test")
        if roles:
            seeder, _ = User.objects.get_or_create(email="test.seed@caipo.test")
            for role in roles:
                RoleEvent.objects.create(
                    user=user,
                    role=role,
                    event_type=RoleEventType.GRANTED,
                    actor=seeder,
                    reason="TEST fixture",
                )
        if not is_active:
            User.objects.filter(pk=user.pk).update(is_active=False)
            user.refresh_from_db()
        return user

    return make
