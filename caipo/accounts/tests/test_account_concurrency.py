"""Account lifecycle operations made at the same time, on separate database connections.

These tests commit their data, because other connections must see it, and the
database is emptied after each of them.
"""

import re
import threading
from collections.abc import Callable

import pytest
from django.conf import LazySettings
from django.core import mail as django_mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connections

from caipo.accounts import services
from caipo.accounts.models import (
    AccountActivation,
    AccountEvent,
    AccountStatus,
    RoleEvent,
    User,
)
from caipo.accounts.selectors import AuthenticationContext, Role
from caipo.accounts.services import (
    AccountChangeError,
    ActivationOutcome,
    ActivationResult,
    LastAdministratorError,
    SignInOutcome,
)
from caipo.accounts.tests.fixtures import UserFactory, approving_administrator, verified

pytestmark = [pytest.mark.services, pytest.mark.django_db(transaction=True)]

# Visibly synthetic fixture values.
EMAIL = "test.invited@caipo.test"
PASSWORD = "TEST-passphrase-chosen-by-the-owner"
OTHER_PASSWORD = "TEST-another-passphrase-entirely"
SOURCE = "203.0.113.10"
WAIT_SECONDS = 30


def _at_the_same_time(*operations: Callable[[], object]) -> list[object]:
    """Run the operations together, each on its own connection.

    Returns what each returned, or the exception it raised, in the order given.
    """
    barrier = threading.Barrier(len(operations))
    results: list[object] = [None] * len(operations)

    def run(index: int, operation: Callable[[], object]) -> None:
        try:
            barrier.wait(timeout=WAIT_SECONDS)
            results[index] = operation()
        except Exception as error:  # recorded and asserted on by the test, not hidden
            results[index] = error
        finally:
            connections.close_all()

    threads = [
        threading.Thread(target=run, args=(index, operation))
        for index, operation in enumerate(operations)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=WAIT_SECONDS)
        assert not thread.is_alive(), "an operation did not finish"
    return results


def _url(token: str) -> str:
    return f"https://caipo.test/activate/#{token}"


def _invited(role: Role = Role.READER) -> tuple[User, str]:
    created = services.create_user(
        actor=approving_administrator(),
        email=EMAIL,
        role=role,
        source=SOURCE,
        activation_url=_url,
    )
    (token,) = re.findall(r"#(\S+)", str(django_mail.outbox[-1].body))
    return created.user, str(token)


def _events() -> list[str]:
    return list(AccountEvent.objects.order_by("id").values_list("event_type", flat=True))


def _outcomes(results: list[object]) -> list[str]:
    assert all(isinstance(result, ActivationResult) for result in results), results
    return sorted(
        result.outcome.value for result in results if isinstance(result, ActivationResult)
    )


def test_one_token_used_several_times_at_once_activates_once() -> None:
    user, token = _invited()

    def activate() -> ActivationResult:
        return services.activate_account(token=token, password=PASSWORD, source=SOURCE)

    results = _at_the_same_time(activate, activate, activate, activate)

    assert _outcomes(results) == ["activated", "refused", "refused", "refused"]
    assert User.objects.get(pk=user.pk).status == AccountStatus.ACTIVE
    assert _events().count("verification_succeeded") == 1
    assert _events().count("verification_failed") == 3
    assert not AccountActivation.objects.exists()


def test_two_people_with_the_same_token_cannot_both_set_the_password() -> None:
    user, token = _invited()

    first, second = _at_the_same_time(
        lambda: services.activate_account(token=token, password=PASSWORD, source=SOURCE),
        lambda: services.activate_account(token=token, password=OTHER_PASSWORD, source=SOURCE),
    )

    assert _outcomes([first, second]) == ["activated", "refused"]
    assert isinstance(first, ActivationResult)
    winner, loser = (
        (PASSWORD, OTHER_PASSWORD)
        if first.outcome == ActivationOutcome.ACTIVATED
        else (OTHER_PASSWORD, PASSWORD)
    )
    stored = User.objects.get(pk=user.pk)
    assert stored.check_password(winner) is True
    assert stored.check_password(loser) is False


def test_wrong_tokens_sent_at_once_cannot_exceed_the_limit(settings: LazySettings) -> None:
    _invited()
    limit = settings.ACCOUNT_ACTIVATION_THROTTLE_FAILURES

    def guess() -> ActivationResult:
        return services.activate_account(token="A" * 43, password=PASSWORD, source=SOURCE)

    results = _at_the_same_time(*([guess] * (limit + 6)))

    assert _outcomes(results) == ["refused"] * limit + ["throttled"] * 6
    assert _events().count("verification_failed") == limit


def test_the_same_account_created_twice_at_once_is_created_once(
    user_with_roles: UserFactory,
) -> None:
    first, second = (verified(user_with_roles(Role.ADMINISTRATOR)) for _ in range(2))
    users = User.objects.count()

    def create(actor: AuthenticationContext, role: Role) -> Callable[[], object]:
        return lambda: services.create_user(
            actor=actor, email=EMAIL, role=role, source=SOURCE, activation_url=_url
        )

    results = _at_the_same_time(create(first, Role.READER), create(second, Role.ADMINISTRATOR))

    created = [result for result in results if isinstance(result, services.CreatedAccount)]
    refused = [result for result in results if isinstance(result, ValidationError)]
    assert (len(created), len(refused)) == (1, 1), results
    assert User.objects.count() == users + 1
    user = User.objects.get(email=EMAIL)
    # One account, one role, one token, one message: nothing of the loser's.
    assert RoleEvent.objects.filter(user=user).count() == 1
    assert AccountActivation.objects.filter(user=user).count() == 1
    assert _events() == ["account_created", "verification_sent"]
    assert len(django_mail.outbox) == 1


def test_an_activation_and_a_disabling_at_once_never_leave_a_usable_account() -> None:
    user, token = _invited()
    administrator = approving_administrator()

    activated, disabled = _at_the_same_time(
        lambda: services.activate_account(token=token, password=PASSWORD, source=SOURCE),
        lambda: services.disable_user(actor=administrator, user=user),
    )

    # Whichever came first, the account ends disabled and cannot be signed in to.
    assert disabled is None
    assert isinstance(activated, ActivationResult)
    stored = User.objects.get(pk=user.pk)
    assert stored.status == AccountStatus.DISABLED
    assert not AccountActivation.objects.exists()
    sign_in = services.sign_in(email=EMAIL, password=PASSWORD, source=SOURCE)
    assert sign_in.outcome == SignInOutcome.REFUSED
    if activated.outcome == ActivationOutcome.ACTIVATED:
        assert stored.activated_at is not None
        assert _events()[-2:] == ["verification_succeeded", "account_disabled"]
    else:
        assert activated.outcome == ActivationOutcome.REFUSED
        assert stored.activated_at is None
        assert stored.check_password(PASSWORD) is False


def test_an_activation_and_a_new_message_at_once_leave_one_consistent_state() -> None:
    user, token = _invited()
    administrator = approving_administrator()

    activated, sent = _at_the_same_time(
        lambda: services.activate_account(token=token, password=PASSWORD, source=SOURCE),
        lambda: services.send_account_verification(
            actor=administrator, user_id=user.pk, source=SOURCE, activation_url=_url
        ),
    )

    assert isinstance(activated, ActivationResult)
    stored = User.objects.get(pk=user.pk)
    if activated.outcome == ActivationOutcome.ACTIVATED:
        # Activated first: there was nothing left to send a message for.
        assert isinstance(sent, AccountChangeError)
        assert stored.status == AccountStatus.ACTIVE
        assert not AccountActivation.objects.exists()
    else:
        # The new message came first: the old token was already replaced.
        assert sent is True
        assert activated.outcome == ActivationOutcome.REFUSED
        assert stored.status == AccountStatus.PENDING_VERIFICATION
        assert AccountActivation.objects.filter(user=user).count() == 1


def test_an_account_disabled_twice_at_once_is_disabled_once() -> None:
    user, _ = _invited()
    administrator = approving_administrator()

    def disable() -> None:
        services.disable_user(actor=administrator, user=user)

    results = _at_the_same_time(disable, disable, disable)

    assert sorted(type(result).__name__ for result in results) == [
        "AccountChangeError",
        "AccountChangeError",
        "NoneType",
    ]
    assert _events().count("account_disabled") == 1


def test_a_disabling_and_an_enabling_at_once_leave_the_status_the_last_event_says(
    user_with_roles: UserFactory,
) -> None:
    target = user_with_roles(Role.READER)
    administrator = approving_administrator()

    disabled, enabled = _at_the_same_time(
        lambda: services.disable_user(actor=administrator, user=target),
        lambda: services.enable_user(actor=administrator, user=target),
    )

    assert disabled is None
    stored = User.objects.get(pk=target.pk)
    if isinstance(enabled, AccountChangeError):
        # The enabling came first and found an account that was not disabled.
        assert _events() == ["account_disabled"]
        assert stored.status == AccountStatus.DISABLED
    else:
        assert enabled == AccountStatus.ACTIVE
        assert _events() == ["account_disabled", "account_enabled"]
        assert stored.status == AccountStatus.ACTIVE


def test_two_administrators_disabling_each_other_leave_one(user_with_roles: UserFactory) -> None:
    first, second = user_with_roles(Role.ADMINISTRATOR), user_with_roles(Role.ADMINISTRATOR)
    as_first, as_second = verified(first), verified(second)

    results = _at_the_same_time(
        lambda: services.disable_user(actor=as_first, user=second),
        lambda: services.disable_user(actor=as_second, user=first),
    )

    # The one that waited was either no longer able to act or would have been the last.
    assert sum(result is None for result in results) == 1, results
    (refusal,) = [result for result in results if result is not None]
    assert isinstance(refusal, (PermissionDenied, LastAdministratorError))
    assert User.objects.filter(pk__in=[first.pk, second.pk], status="active").count() == 1
    assert _events() == ["account_disabled"]
