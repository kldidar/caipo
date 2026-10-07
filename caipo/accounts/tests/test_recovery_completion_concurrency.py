"""The first code of a recovered account's new device, given alongside other
operations on separate database connections (ADR-0017, points 37 and 49).

These tests commit their data, because other connections must see it, and the
database is emptied after each of them.

Two kinds of test, as for the decisions on recovery requests. One holds an
operation in the middle, with its locks, and starts another behind it. The
other starts operations together and asserts on every order that the database
could have chosen.
"""

import base64
from datetime import timedelta
from functools import partial

import pytest
from django.core.exceptions import PermissionDenied

from caipo.accounts import selectors, services
from caipo.accounts.models import (
    AuthenticationEvent,
    MfaRecoveryRequest,
    RoleEventType,
    TotpDevice,
    TotpDeviceState,
    User,
)
from caipo.accounts.selectors import AuthenticationContext, Role
from caipo.accounts.services import MfaOutcome, MfaResult
from caipo.accounts.tests.fixtures import Clock, UserFactory, code_at, signed_in
from caipo.accounts.tests.test_recovery_authorization import _change_role
from caipo.accounts.tests.test_recovery_authorization_concurrency import (
    AUTHORIZED,
    LOCKED,
    PASSWORD,
    ROUNDS,
    SOURCE,
    _account,
    _administrator,
    _approve,
    _asked,
    _authorize,
    _enrolment_request,
)
from caipo.accounts.tests.test_recovery_authorization_concurrency import (
    UNAVAILABLE as NOT_AUTHORIZED,
)
from caipo.accounts.tests.test_recovery_request_concurrency import (
    _at_the_same_time,
    _behind,
    _Held,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db(transaction=True)]

COMPLETED = "mfa_recovery_completed"
ACCEPTED = MfaOutcome.ACCEPTED
UNAVAILABLE = MfaResult(MfaOutcome.UNAVAILABLE)
STEP = timedelta(seconds=30)
# The recoveries of one account, in the order recorded, when its first code
# and the authorisation of its next recovery are given together.
CODE_FIRST = ["mfa_recovery_authorized", COMPLETED, "mfa_recovery_authorized"]
AUTHORISATION_FIRST = ["mfa_recovery_authorized", COMPLETED]


def _confirm(user: User, secret: bytes) -> MfaResult:
    return services.confirm_mfa_enrollment(
        actor=signed_in(user), code=code_at(secret=secret), source=SOURCE
    )


def _completions(user: User) -> int:
    return AuthenticationEvent.objects.filter(event_type=COMPLETED, user=user).count()


def _succeeded(user: User) -> int:
    return AuthenticationEvent.objects.filter(
        event_type="mfa_enrollment_succeeded", user=user
    ).count()


def _approved_after_recovery(
    user: User, authoriser: AuthenticationContext, approver: AuthenticationContext
) -> bytes:
    """Take the account's recovery as far as an approved enrolment; return the new secret."""
    assert _authorize(_asked(user), authoriser) == AUTHORIZED
    secret, number = _enrolment_request(user)
    assert _approve(number, approver).outcome == ACCEPTED
    return secret


def _outcome(result: object) -> MfaOutcome:
    assert isinstance(result, MfaResult), result
    return result.outcome


# --- The first code, given twice --------------------------------------------------------


def test_a_first_code_given_twice_at_once_completes_the_recovery_once(
    user_with_roles: UserFactory,
) -> None:
    authoriser, other = _administrator(user_with_roles), _administrator(user_with_roles)
    for _ in range(ROUNDS):
        user = _account(user_with_roles)
        secret = _approved_after_recovery(user, authoriser, other)

        results = _at_the_same_time(*(partial(_confirm, user, secret) for _ in range(4)))

        outcomes = sorted(_outcome(result) for result in results)
        assert outcomes == sorted([ACCEPTED, *[MfaOutcome.UNAVAILABLE] * 3]), outcomes
        assert _succeeded(user) == 1
        assert _completions(user) == 1
        assert selectors.open_recovery_authorizer_id(user.pk) is None


def test_a_second_first_code_waits_for_the_first_and_completes_nothing(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    authoriser, other = _administrator(user_with_roles), _administrator(user_with_roles)
    user = _account(user_with_roles)
    secret = _approved_after_recovery(user, authoriser, other)

    # The first code is accepted and nothing is committed.
    held = _Held(monkeypatch, "_accept_code", lambda: _confirm(user, secret))
    first, second = _behind(held, lambda: _confirm(user, secret))

    assert _outcome(first) == ACCEPTED
    assert second == UNAVAILABLE
    assert _completions(user) == 1


# --- The recovery is closed when the confirmation commits, and not before ---------------


def test_the_recovery_is_open_to_everyone_else_until_the_confirmation_commits(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    authoriser, other = _administrator(user_with_roles), _administrator(user_with_roles)
    user = _account(user_with_roles)
    secret = _approved_after_recovery(user, authoriser, other)

    # Held after its first event, `mfa_enrollment_succeeded`, is written.
    held = _Held(monkeypatch, "_record", lambda: _confirm(user, secret))
    open_meanwhile = selectors.open_recovery_authorizer_id(user.pk)
    completions_meanwhile = _completions(user)
    confirmed = held.finish()

    assert open_meanwhile == authoriser.user.pk
    assert completions_meanwhile == 0
    assert _outcome(confirmed) == ACCEPTED
    assert _completions(user) == 1
    assert selectors.open_recovery_authorizer_id(user.pk) is None


def test_the_authoriser_approving_as_the_first_code_is_given_approves_nothing(
    user_with_roles: UserFactory,
) -> None:
    authoriser, other = _administrator(user_with_roles), _administrator(user_with_roles)
    for _ in range(ROUNDS):
        user = _account(user_with_roles)
        assert _authorize(_asked(user), authoriser) == AUTHORIZED
        secret, number = _enrolment_request(user)
        assert _approve(number, other).outcome == ACCEPTED

        confirmed, approved = _at_the_same_time(
            partial(_confirm, user, secret), partial(_approve, number, authoriser)
        )

        # Whichever ran first, the request no longer awaited a decision.
        assert _outcome(confirmed) == ACCEPTED
        assert approved == UNAVAILABLE
        assert TotpDevice.objects.get(user=user).approved_by == other.user
        assert _completions(user) == 1


def test_an_approval_and_a_first_code_at_once_complete_only_an_approved_device(
    user_with_roles: UserFactory,
) -> None:
    authoriser, other = _administrator(user_with_roles), _administrator(user_with_roles)
    for _ in range(ROUNDS):
        user = _account(user_with_roles)
        assert _authorize(_asked(user), authoriser) == AUTHORIZED
        secret, number = _enrolment_request(user)

        confirmed, approved = _at_the_same_time(
            partial(_confirm, user, secret), partial(_approve, number, other)
        )

        # The approval is given either way. The code was examined after it,
        # and the recovery is complete, or before it, and nothing happened.
        assert _outcome(approved) == ACCEPTED
        device = TotpDevice.objects.get(user=user)
        assert device.approved_by == other.user
        if _outcome(confirmed) == ACCEPTED:
            assert device.state == TotpDeviceState.ACTIVE
            assert (_succeeded(user), _completions(user)) == (1, 1)
            assert selectors.open_recovery_authorizer_id(user.pk) is None
        else:
            assert confirmed == UNAVAILABLE
            assert device.state == TotpDeviceState.PENDING_VERIFICATION
            assert (_succeeded(user), _completions(user)) == (0, 0)
            assert selectors.open_recovery_authorizer_id(user.pk) == authoriser.user.pk


# --- The first code and another enrolment of the same account ---------------------------


def test_a_first_code_and_a_new_enrolment_request_at_once_never_complete_an_unapproved_device(
    user_with_roles: UserFactory,
) -> None:
    authoriser, other = _administrator(user_with_roles), _administrator(user_with_roles)
    for _ in range(ROUNDS):
        user = _account(user_with_roles)
        secret = _approved_after_recovery(user, authoriser, other)

        confirmed, started = _at_the_same_time(
            partial(_confirm, user, secret),
            partial(
                services.start_mfa_enrollment,
                actor=signed_in(user),
                password=PASSWORD,
                source=SOURCE,
            ),
        )

        device = TotpDevice.objects.get(user=user)
        if _outcome(confirmed) == ACCEPTED:
            # The code came first: the approved device is active, and no new
            # request is taken while it is.
            assert _outcome(started) == MfaOutcome.UNAVAILABLE
            assert device.state == TotpDeviceState.ACTIVE
            assert device.approved_by == other.user
            assert _completions(user) == 1
            assert selectors.open_recovery_authorizer_id(user.pk) is None
        else:
            # The new request came first: the approved secret is gone, the
            # code is for nothing, and the recovery is as open as it was.
            assert confirmed == UNAVAILABLE
            assert _outcome(started) == ACCEPTED
            assert device.state == TotpDeviceState.PENDING_APPROVAL
            assert device.approved_at is None
            assert (_succeeded(user), _completions(user)) == (0, 0)
            assert selectors.open_recovery_authorizer_id(user.pk) == authoriser.user.pk
            with pytest.raises(PermissionDenied):
                _approve(device.pk, authoriser)


# --- The first code and the authorisation of the same account's next recovery -----------


def _lifecycle(user: User) -> list[str]:
    return list(
        AuthenticationEvent.objects.filter(
            user=user, event_type__in=["mfa_recovery_authorized", COMPLETED]
        )
        .order_by("id")
        .values_list("event_type", flat=True)
    )


def _a_first_code_and_a_request_both_awaited(
    user_with_roles: UserFactory,
    authoriser: AuthenticationContext,
    other: AuthenticationContext,
    clock: Clock,
) -> tuple[User, bytes, int]:
    """Return an account with an open recovery whose first code and next recovery both wait.

    The only way both can: the recovery was authorised and no trusted device
    followed, because the account enrolled without approval while it did not
    hold the role. On that device it asked for recovery again, and then
    replaced the device after all. The new one is approved and awaits its
    first code, and the request has not lapsed. Returns the account, the
    secret of the approved device, and the number of the request.
    """
    user = _account(user_with_roles)
    assert _authorize(_asked(user), authoriser) == AUTHORIZED
    _change_role(user, Role.REVIEWER, RoleEventType.REVOKED)
    _change_role(user, Role.READER, RoleEventType.GRANTED)
    started = services.start_mfa_enrollment(actor=signed_in(user), password=PASSWORD, source=SOURCE)
    assert started.provisioning is not None
    untrusted = base64.b32decode(started.provisioning.secret)
    assert _confirm(user, untrusted).outcome == ACCEPTED
    _change_role(user, Role.REVIEWER, RoleEventType.GRANTED)

    number = _asked(user)
    clock(STEP * 4)
    replaced = services.replace_mfa_device(
        actor=signed_in(user), password=PASSWORD, code=code_at(secret=untrusted), source=SOURCE
    )
    assert replaced.provisioning is not None
    approval = selectors.enrollment_request_number_of(user)
    assert approval is not None
    assert _approve(approval, other).outcome == ACCEPTED
    assert _lifecycle(user) == ["mfa_recovery_authorized"]
    return user, base64.b32decode(replaced.provisioning.secret), number


def _the_code_came_first(user: User, other: AuthenticationContext) -> None:
    # The first recovery was completed whole, and the next one was then
    # authorised on the device that completed it, which it revoked.
    assert _lifecycle(user) == CODE_FIRST
    assert selectors.open_recovery_authorizer_id(user.pk) == other.user.pk
    assert not TotpDevice.objects.filter(user=user).exists()
    assert not MfaRecoveryRequest.objects.filter(user=user).exists()
    assert User.objects.get(pk=user.pk).session_epoch == 2


def _the_authorisation_came_first(user: User, other: AuthenticationContext, number: int) -> None:
    # It found a device that awaited its first code, so the account was not
    # eligible and nothing was authorised. The code then completed the first
    # recovery, and the request is as it was.
    assert _lifecycle(user) == AUTHORISATION_FIRST
    assert selectors.open_recovery_authorizer_id(user.pk) is None
    device = TotpDevice.objects.get(user=user)
    assert (device.state, device.approved_by) == (TotpDeviceState.ACTIVE, other.user)
    assert MfaRecoveryRequest.objects.filter(pk=number, user=user).exists()
    assert User.objects.get(pk=user.pk).session_epoch == 1


def test_an_authorisation_waits_for_the_first_code_and_opens_the_next_recovery_after_it(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch, clock: Clock
) -> None:
    authoriser, other = _administrator(user_with_roles), _administrator(user_with_roles)
    user, secret, number = _a_first_code_and_a_request_both_awaited(
        user_with_roles, authoriser, other, clock
    )

    # Held between its two events: `mfa_enrollment_succeeded` is written and
    # `mfa_recovery_completed` is not.
    held = _Held(monkeypatch, "_record", lambda: _confirm(user, secret))
    confirmed, authorized = _behind(held, lambda: _authorize(number, other))

    assert _outcome(confirmed) == ACCEPTED
    assert authorized == AUTHORIZED
    assert (_succeeded(user), _completions(user)) == (2, 1)
    _the_code_came_first(user, other)


def test_a_first_code_waits_for_the_authorisation_and_completes_the_recovery_it_left_open(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch, clock: Clock
) -> None:
    authoriser, other = _administrator(user_with_roles), _administrator(user_with_roles)
    user, secret, number = _a_first_code_and_a_request_both_awaited(
        user_with_roles, authoriser, other, clock
    )

    # The authorisation holds every one of its locks and has decided nothing.
    held = _Held(monkeypatch, LOCKED, lambda: _authorize(number, other))
    authorized, confirmed = _behind(held, lambda: _confirm(user, secret))

    assert authorized == NOT_AUTHORIZED
    assert _outcome(confirmed) == ACCEPTED
    assert (_succeeded(user), _completions(user)) == (2, 1)
    _the_authorisation_came_first(user, other, number)


def test_a_first_code_and_an_authorisation_of_the_same_account_at_once_are_one_after_the_other(
    user_with_roles: UserFactory, clock: Clock
) -> None:
    authoriser, other = _administrator(user_with_roles), _administrator(user_with_roles)
    for _ in range(ROUNDS):
        user, secret, number = _a_first_code_and_a_request_both_awaited(
            user_with_roles, authoriser, other, clock
        )

        confirmed, authorized = _at_the_same_time(
            partial(_confirm, user, secret), partial(_authorize, number, other)
        )

        # The code is accepted in either order, and the recovery it completes
        # is the first: never one that was authorised while it was examined.
        assert _outcome(confirmed) == ACCEPTED
        assert (_succeeded(user), _completions(user)) == (2, 1)
        if authorized == AUTHORIZED:
            _the_code_came_first(user, other)
        else:
            assert authorized == NOT_AUTHORIZED
            _the_authorisation_came_first(user, other, number)


# --- Other accounts ---------------------------------------------------------------------


def test_first_codes_of_different_accounts_at_once_complete_each_recovery_once(
    user_with_roles: UserFactory,
) -> None:
    authoriser, other = _administrator(user_with_roles), _administrator(user_with_roles)
    for _ in range(ROUNDS):
        users = [_account(user_with_roles) for _ in range(3)]
        secrets = [_approved_after_recovery(user, authoriser, other) for user in users]
        # One more recovery, which nobody completes.
        waiting = _account(user_with_roles)
        _approved_after_recovery(waiting, authoriser, other)

        results = _at_the_same_time(
            *(partial(_confirm, user, secret) for user, secret in zip(users, secrets, strict=True))
        )

        assert [_outcome(result) for result in results] == [ACCEPTED] * 3
        assert [_completions(user) for user in users] == [1, 1, 1]
        assert _completions(waiting) == 0
        assert selectors.open_recovery_authorizer_id(waiting.pk) == authoriser.user.pk


def test_a_first_code_does_not_wait_for_the_authorisation_of_another_accounts_recovery(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    authoriser, other = _administrator(user_with_roles), _administrator(user_with_roles)
    user, elsewhere = _account(user_with_roles), _account(user_with_roles)
    secret = _approved_after_recovery(user, authoriser, other)
    number = _asked(elsewhere)

    # The other account's authorisation holds every one of its locks.
    held = _Held(monkeypatch, LOCKED, lambda: _authorize(number, authoriser))
    confirmed = _confirm(user, secret)
    completions_meanwhile = (_completions(user), _completions(elsewhere))
    authorized = held.finish()

    assert _outcome(confirmed) == ACCEPTED
    assert completions_meanwhile == (1, 0)
    assert authorized == AUTHORIZED
    assert selectors.open_recovery_authorizer_id(user.pk) is None
    assert selectors.open_recovery_authorizer_id(elsewhere.pk) == authoriser.user.pk
    assert _completions(elsewhere) == 0
