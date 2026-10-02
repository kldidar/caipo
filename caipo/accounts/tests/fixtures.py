"""Fixtures for tests that need users with roles, in this app and in the apps above it.

Registered for the whole suite by the conftest.py at the repository root.
"""

from collections.abc import Callable
from itertools import count

import pytest

from caipo.accounts import mfa
from caipo.accounts.authorization import Role
from caipo.accounts.models import RoleEvent, RoleEventType, User

type UserFactory = Callable[..., User]


@pytest.fixture
def mfa_enrolled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Treat every account as enrolled in multi-factor authentication.

    No enrolment mechanism exists yet (caipo.accounts.mfa), so this is the only
    way to exercise what Reviewer and Administrator accounts will be able to do
    once it does. It replaces the missing input, not the decision under test.
    """
    monkeypatch.setattr(mfa, "is_enrolled", lambda user: True)


@pytest.fixture
def user_with_roles(db: None) -> UserFactory:
    """Return a factory for synthetic users holding the given roles.

    Roles are seeded as RoleEvent rows written directly, attributed to a
    synthetic seeding account. This stands in for the bootstrap of the first
    Administrator, which is not designed yet; the services under test are not
    used to set up their own preconditions.
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
