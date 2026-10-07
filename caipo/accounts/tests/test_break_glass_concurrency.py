"""The break-glass actions made alongside other operations, on separate database
connections (ADR-0017 points 59 to 70).

These tests commit their data, because other connections must see it, and the
database is emptied after each of them.

Two kinds of test, as for the decisions on recovery requests. One holds an
operation in the middle, with its locks, and starts another behind it: the
second must wait, and the order is then known. The other starts operations
together and asserts on every order that the database could have chosen.
"""

from functools import partial

import pytest
from django.utils import timezone

from caipo.accounts import selectors, services
from caipo.accounts.models import (
    AccountStatus,
    AuthenticationEvent,
    MfaChallenge,
    MfaRecoveryRequest,
    PasswordReset,
    TotpDevice,
    TotpDeviceState,
    User,
)
from caipo.accounts.selectors import AuthenticationContext, Permission, Role
from caipo.accounts.services import (
    BreakGlassOutcome,
    BreakGlassResult,
    MfaOutcome,
    MfaResult,
    PasswordResetOutcome,
    PasswordResetResult,
    RecoveryRequestOutcome,
    RecoveryRequestResult,
    SignInOutcome,
    SignInResult,
)
from caipo.accounts.tests.fixtures import UserFactory, code_at, signed_in
from caipo.accounts.tests.test_recovery_authorization_concurrency import (
    AUTHORIZED,
    PASSWORD,
    SOURCE,
    _account,
    _administrator,
    _approve,
    _ask,
    _asked,
    _authorize,
    _challenge,
    _enrolment_request,
    _reset,
    _reset_token,
    _verify,
)
from caipo.accounts.tests.test_recovery_authorization_concurrency import (
    LOCKED as DECISION_LOCKED,
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

DONE = BreakGlassResult(BreakGlassOutcome.DONE)
UNAVAILABLE = BreakGlassResult(BreakGlassOutcome.UNAVAILABLE)

BREAK_GLASS = "mfa_recovery_break_glass"
COMPLETED = "mfa_recovery_completed"
# Where a break-glass action holds every one of its locks and has changed
# nothing yet.
LOCKED = "_account_for_break_glass"


def _administrator_account(user_with_roles: UserFactory) -> User:
    return _account(user_with_roles, Role.ADMINISTRATOR)


def _revoke(user: User, number: int) -> BreakGlassResult:
    return services.break_glass_revoke_device(email=user.email, request_number=number)


def _approve_by_break_glass(user: User, number: int) -> BreakGlassResult:
    return services.break_glass_approve_enrollment(email=user.email, request_number=number)


def _confirm(user: User, secret: bytes) -> MfaResult:
    return services.confirm_mfa_enrollment(
        actor=signed_in(user), code=code_at(secret=secret), source=SOURCE
    )


def _actions(user: User | None = None) -> list[str]:
    events = AuthenticationEvent.objects.filter(event_type=BREAK_GLASS).order_by("id")
    if user is not None:
        events = events.filter(user=user)
    return list(events.values_list("break_glass_action", flat=True))


def _openers(user: User) -> int:
    """Return how many times a recovery of the account was opened, by either way."""
    authorized = AuthenticationEvent.objects.filter(
        user=user, event_type="mfa_recovery_authorized"
    ).count()
    return authorized + _actions(user).count("revoke_device")


def _revoked_whole(user: User) -> bool:
    """Return whether the account's device was revoked, checking that it was done whole."""
    stored = User.objects.get(pk=user.pk)
    if _openers(user) == 0:
        assert stored.session_epoch == 0
        assert TotpDevice.objects.filter(user=user, state=TotpDeviceState.ACTIVE).exists()
        return False
    assert _openers(user) == 1
    assert stored.session_epoch == 1
    assert not TotpDevice.objects.filter(user=user).exists()
    assert not MfaRecoveryRequest.objects.filter(user=user).exists()
    assert not PasswordReset.objects.filter(user=user).exists()
    assert not MfaChallenge.objects.filter(user=user).exists()
    return True


def _awaiting_break_glass_approval(user_with_roles: UserFactory) -> tuple[User, bytes, int]:
    """Return the only Administrator after a revocation, with the enrolment request that follows."""
    user = _administrator_account(user_with_roles)
    assert _revoke(user, _asked(user)) == DONE
    secret, number = _enrolment_request(user)
    return user, secret, number


# --- The same action more than once -----------------------------------------------------


def test_a_revocation_given_several_times_at_once_is_done_once(
    user_with_roles: UserFactory,
) -> None:
    user = _administrator_account(user_with_roles)
    number = _asked(user)

    results = _at_the_same_time(*(partial(_revoke, user, number) for _ in range(4)))

    assert sorted(results, key=str) == sorted([DONE, *[UNAVAILABLE] * 3], key=str), results
    assert _actions() == ["revoke_device"]
    assert _revoked_whole(user) is True


def test_a_second_revocation_waits_for_the_first_and_finds_the_request_used(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _administrator_account(user_with_roles)
    number = _asked(user)

    held = _Held(monkeypatch, LOCKED, lambda: _revoke(user, number))
    first, second = _behind(held, lambda: _revoke(user, number))

    assert (first, second) == (DONE, UNAVAILABLE)
    assert _actions() == ["revoke_device"]
    assert _revoked_whole(user) is True


def test_an_approval_given_several_times_at_once_is_done_once(
    user_with_roles: UserFactory,
) -> None:
    user, _secret, number = _awaiting_break_glass_approval(user_with_roles)

    results = _at_the_same_time(*(partial(_approve_by_break_glass, user, number) for _ in range(4)))

    assert sorted(results, key=str) == sorted([DONE, *[UNAVAILABLE] * 3], key=str), results
    assert _actions() == ["revoke_device", "approve_enrollment"]
    device = TotpDevice.objects.get(user=user)
    assert (device.state, device.approved_by) == (TotpDeviceState.PENDING_VERIFICATION, None)


def test_a_second_approval_waits_for_the_first_and_finds_the_request_decided(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, _secret, number = _awaiting_break_glass_approval(user_with_roles)

    held = _Held(monkeypatch, LOCKED, lambda: _approve_by_break_glass(user, number))
    first, second = _behind(held, lambda: _approve_by_break_glass(user, number))

    assert (first, second) == (DONE, UNAVAILABLE)
    assert _actions() == ["revoke_device", "approve_enrollment"]


# --- A revocation and an Administrator's authorisation ----------------------------------


@pytest.mark.parametrize("others", [1, 2])
def test_a_revocation_and_an_authorisation_at_once_open_one_recovery_by_the_path_that_applies(
    others: int, user_with_roles: UserFactory
) -> None:
    administrators = [_administrator(user_with_roles) for _ in range(others)]
    user = _administrator_account(user_with_roles)
    number = _asked(user)

    revoked, authorized = _at_the_same_time(
        partial(_revoke, user, number), partial(_authorize, number, administrators[0])
    )

    # Whichever ran first. With two other Administrators the application's
    # path applies and the command refuses; with one it is the reverse.
    if others == 2:
        assert (revoked, authorized) == (UNAVAILABLE, AUTHORIZED)
        assert _actions() == []
    else:
        assert (revoked, authorized) == (DONE, NOT_AUTHORIZED)
        assert _actions() == ["revoke_device"]
    assert _revoked_whole(user) is True


def test_a_revocation_waits_for_an_authorisation_that_is_under_way(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    administrator, _other = _administrator(user_with_roles), _administrator(user_with_roles)
    user = _administrator_account(user_with_roles)
    number = _asked(user)

    held = _Held(monkeypatch, DECISION_LOCKED, lambda: _authorize(number, administrator))
    authorized, revoked = _behind(held, lambda: _revoke(user, number))

    assert (authorized, revoked) == (AUTHORIZED, UNAVAILABLE)
    assert _actions() == []
    assert _revoked_whole(user) is True


def test_an_authorisation_waits_for_a_revocation_that_is_under_way(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    administrator = _administrator(user_with_roles)
    user = _administrator_account(user_with_roles)
    number = _asked(user)

    held = _Held(monkeypatch, LOCKED, lambda: _revoke(user, number))
    revoked, authorized = _behind(held, lambda: _authorize(number, administrator))

    assert (revoked, authorized) == (DONE, NOT_AUTHORIZED)
    assert _revoked_whole(user) is True


# --- A revocation and the owner's recovery request --------------------------------------


def test_a_request_that_arrives_during_a_revocation_is_refused(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _administrator_account(user_with_roles)
    number = _asked(user)
    challenge = _challenge(user)

    held = _Held(monkeypatch, LOCKED, lambda: _revoke(user, number))
    revoked, asked = _behind(held, lambda: _ask(challenge))

    assert revoked == DONE
    assert isinstance(asked, RecoveryRequestResult)
    # Its challenge was removed with the device it was issued for.
    assert asked.outcome == RecoveryRequestOutcome.REFUSED
    assert _revoked_whole(user) is True


def test_a_revocation_of_a_request_that_is_being_replaced_is_refused(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _administrator_account(user_with_roles)
    number = _asked(user)
    challenge = _challenge(user)

    held = _Held(monkeypatch, "_challenge_for_recovery", lambda: _ask(challenge))
    asked, revoked = _behind(held, lambda: _revoke(user, number))

    assert isinstance(asked, RecoveryRequestResult)
    assert asked.outcome == RecoveryRequestOutcome.REQUESTED
    # The number that was typed names nothing now.
    assert revoked == UNAVAILABLE
    assert _revoked_whole(user) is False
    assert asked.number is not None
    assert _revoke(user, asked.number) == DONE


# --- A revocation and a sign-in for the account -----------------------------------------


def test_a_sign_in_that_arrives_during_a_revocation_finds_no_second_factor(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _administrator_account(user_with_roles)
    number = _asked(user)

    held = _Held(monkeypatch, LOCKED, lambda: _revoke(user, number))
    revoked, signed = _behind(
        held, lambda: services.sign_in(email=user.email, password=PASSWORD, source=SOURCE)
    )

    assert revoked == DONE
    assert isinstance(signed, SignInResult)
    assert signed.outcome == SignInOutcome.SIGNED_IN
    assert signed.user is not None
    assert signed.user.session_epoch == 1
    assert _revoked_whole(user) is True


def test_a_revocation_that_arrives_during_a_sign_in_removes_its_challenge(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _administrator_account(user_with_roles)
    number = _asked(user)

    held = _Held(
        monkeypatch,
        "_throttled_by",
        lambda: services.sign_in(email=user.email, password=PASSWORD, source=SOURCE),
    )
    signed, revoked = _behind(held, lambda: _revoke(user, number))

    assert isinstance(signed, SignInResult)
    assert signed.outcome == SignInOutcome.SECOND_FACTOR_REQUIRED
    assert signed.challenge is not None
    assert revoked == DONE
    assert _verify(signed.challenge).outcome == MfaOutcome.REFUSED
    assert not AuthenticationEvent.objects.filter(event_type="login_success").exists()
    assert _revoked_whole(user) is True


def test_a_code_that_arrives_during_a_revocation_is_refused(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _administrator_account(user_with_roles)
    number = _asked(user)
    challenge = _challenge(user)

    held = _Held(monkeypatch, LOCKED, lambda: _revoke(user, number))
    revoked, verified_ = _behind(held, lambda: _verify(challenge))

    assert revoked == DONE
    assert isinstance(verified_, MfaResult)
    assert verified_.outcome == MfaOutcome.REFUSED
    assert not AuthenticationEvent.objects.filter(event_type="login_success").exists()


def test_a_revocation_that_arrives_while_a_code_is_examined_ends_the_sign_in_it_completes(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _administrator_account(user_with_roles)
    number = _asked(user)
    challenge = _challenge(user)
    session_value = User.objects.get(pk=user.pk).get_session_auth_hash()

    held = _Held(monkeypatch, "_pending_challenge", lambda: _verify(challenge))
    verified_, revoked = _behind(held, lambda: _revoke(user, number))

    assert isinstance(verified_, MfaResult)
    assert verified_.outcome == MfaOutcome.ACCEPTED
    assert revoked == DONE
    # The sign-in ran wholly before the revocation, which then ended it.
    assert User.objects.get(pk=user.pk).get_session_auth_hash() != session_value
    assert not selectors.can(verified_.context, Permission.ROLES_MANAGE)
    assert _revoked_whole(user) is True


def test_a_revocation_and_a_code_at_once_never_leave_a_verified_sign_in_behind(
    user_with_roles: UserFactory,
) -> None:
    user = _administrator_account(user_with_roles)
    number = _asked(user)
    challenge = _challenge(user)

    revoked, verified_ = _at_the_same_time(
        partial(_revoke, user, number), partial(_verify, challenge)
    )

    assert revoked == DONE
    assert isinstance(verified_, MfaResult)
    assert verified_.outcome in (MfaOutcome.ACCEPTED, MfaOutcome.REFUSED)
    if verified_.outcome == MfaOutcome.ACCEPTED:
        assert not selectors.can(verified_.context, Permission.ROLES_MANAGE)
    assert _revoked_whole(user) is True


# --- A revocation and a password reset --------------------------------------------------


def test_a_revocation_that_arrives_during_a_password_reset_is_refused(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _administrator_account(user_with_roles)
    token = _reset_token(user)
    number = _asked(user)

    held = _Held(monkeypatch, "_pending_password_reset", lambda: _reset(token))
    reset, revoked = _behind(held, lambda: _revoke(user, number))

    assert isinstance(reset, PasswordResetResult)
    assert reset.outcome == PasswordResetOutcome.RESET
    # The request was made on a password that no longer exists (point 51).
    assert revoked == UNAVAILABLE
    assert _revoked_whole(user) is False


def test_a_password_reset_that_arrives_during_a_revocation_finds_its_token_removed(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _administrator_account(user_with_roles)
    token = _reset_token(user)
    number = _asked(user)

    held = _Held(monkeypatch, LOCKED, lambda: _revoke(user, number))
    revoked, reset = _behind(held, lambda: _reset(token))

    assert revoked == DONE
    assert isinstance(reset, PasswordResetResult)
    assert reset.outcome == PasswordResetOutcome.REFUSED
    assert User.objects.get(pk=user.pk).check_password(PASSWORD)
    assert _revoked_whole(user) is True


def test_a_revocation_and_a_password_reset_at_once_never_both_take_effect(
    user_with_roles: UserFactory,
) -> None:
    user = _administrator_account(user_with_roles)
    token = _reset_token(user)
    number = _asked(user)

    revoked, reset = _at_the_same_time(partial(_revoke, user, number), partial(_reset, token))

    assert isinstance(reset, PasswordResetResult)
    was_reset = reset.outcome == PasswordResetOutcome.RESET
    assert (revoked == DONE) is not was_reset
    assert User.objects.get(pk=user.pk).check_password(PASSWORD) is not was_reset
    assert _revoked_whole(user) is not was_reset


# --- An approval and the enrolment it names ---------------------------------------------


def test_an_enrolment_request_that_arrives_during_an_approval_replaces_what_was_approved(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, _secret, number = _awaiting_break_glass_approval(user_with_roles)

    held = _Held(monkeypatch, LOCKED, lambda: _approve_by_break_glass(user, number))
    approved, started = _behind(
        held,
        lambda: services.start_mfa_enrollment(
            actor=signed_in(user), password=PASSWORD, source=SOURCE
        ),
    )

    assert approved == DONE
    assert isinstance(started, MfaResult)
    assert started.outcome == MfaOutcome.ACCEPTED
    # The approval does not outlive the request it was given to.
    device = TotpDevice.objects.get(user=user)
    assert device.pk != number
    assert (device.state, device.approved_at) == (TotpDeviceState.PENDING_APPROVAL, None)


def test_an_approval_of_a_request_that_is_being_replaced_is_refused(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, _secret, number = _awaiting_break_glass_approval(user_with_roles)

    held = _Held(
        monkeypatch,
        "_issue_pending_device",
        lambda: services.start_mfa_enrollment(
            actor=signed_in(user), password=PASSWORD, source=SOURCE
        ),
    )
    started, approved = _behind(held, lambda: _approve_by_break_glass(user, number))

    assert isinstance(started, MfaResult)
    assert started.outcome == MfaOutcome.ACCEPTED
    assert approved == UNAVAILABLE
    device = TotpDevice.objects.get(user=user)
    assert (device.state, device.approved_at) == (TotpDeviceState.PENDING_APPROVAL, None)
    assert _actions() == ["revoke_device"]


def test_an_approval_and_a_new_enrolment_request_at_once_never_leave_an_approval_on_the_new_one(
    user_with_roles: UserFactory,
) -> None:
    user, _secret, number = _awaiting_break_glass_approval(user_with_roles)

    approved, started = _at_the_same_time(
        partial(_approve_by_break_glass, user, number),
        partial(
            services.start_mfa_enrollment, actor=signed_in(user), password=PASSWORD, source=SOURCE
        ),
    )

    assert approved in (DONE, UNAVAILABLE)
    assert isinstance(started, MfaResult)
    assert started.outcome == MfaOutcome.ACCEPTED
    device = TotpDevice.objects.get(user=user)
    assert device.pk != number
    assert (device.state, device.approved_at) == (TotpDeviceState.PENDING_APPROVAL, None)


# --- An approval and the first code -----------------------------------------------------


def test_a_first_code_that_arrives_during_an_approval_waits_and_completes_the_recovery(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, secret, number = _awaiting_break_glass_approval(user_with_roles)

    held = _Held(monkeypatch, LOCKED, lambda: _approve_by_break_glass(user, number))
    approved, confirmed = _behind(held, lambda: _confirm(user, secret))

    assert approved == DONE
    assert isinstance(confirmed, MfaResult)
    assert confirmed.outcome == MfaOutcome.ACCEPTED
    assert AuthenticationEvent.objects.filter(event_type=COMPLETED, user=user).count() == 1
    assert not selectors.has_open_recovery(user.pk)


def test_an_approval_and_a_first_code_at_once_complete_only_an_approved_device(
    user_with_roles: UserFactory,
) -> None:
    user, secret, number = _awaiting_break_glass_approval(user_with_roles)

    approved, confirmed = _at_the_same_time(
        partial(_approve_by_break_glass, user, number), partial(_confirm, user, secret)
    )

    # The approval is done in either order. The code is accepted only if it
    # came after, and only then is anything active or complete.
    assert approved == DONE
    assert isinstance(confirmed, MfaResult)
    assert confirmed.outcome in (MfaOutcome.ACCEPTED, MfaOutcome.UNAVAILABLE)
    accepted = confirmed.outcome == MfaOutcome.ACCEPTED
    device = TotpDevice.objects.get(user=user)
    assert device.approved_at is not None
    assert (device.state == TotpDeviceState.ACTIVE) is accepted
    completions = AuthenticationEvent.objects.filter(event_type=COMPLETED, user=user).count()
    assert completions == (1 if accepted else 0)
    assert selectors.has_open_recovery(user.pk) is not accepted


def test_a_break_glass_action_that_arrives_while_the_first_code_is_examined_waits_and_does_nothing(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, secret, number = _awaiting_break_glass_approval(user_with_roles)
    assert _approve_by_break_glass(user, number) == DONE

    # The confirmation has activated the device and has not committed.
    held = _Held(monkeypatch, "_accept_code", lambda: _confirm(user, secret))
    confirmed, approved = _behind(held, lambda: _approve_by_break_glass(user, number))

    assert isinstance(confirmed, MfaResult)
    assert confirmed.outcome == MfaOutcome.ACCEPTED
    assert approved == UNAVAILABLE
    assert AuthenticationEvent.objects.filter(event_type=COMPLETED, user=user).count() == 1
    assert _actions() == ["revoke_device", "approve_enrollment"]


# --- A break-glass action and a change to a role or a status ----------------------------


def _take_away(change: str, actor: AuthenticationContext, user: User) -> object:
    if change == "role":
        return services.revoke_role(actor=actor, user=user, role=Role.ADMINISTRATOR, reason="TEST")
    services.disable_user(actor=actor, user=user)
    return None


@pytest.mark.parametrize("change", ["role", "status"])
def test_an_administrator_who_is_losing_the_role_or_being_disabled_is_not_revoked(
    change: str, user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = _administrator(user_with_roles)
    user = _administrator_account(user_with_roles)
    number = _asked(user)

    # Held with the lock on the role events and nothing yet written.
    held = _Held(monkeypatch, "_serialize_account_changes", lambda: _take_away(change, other, user))
    changed, revoked = _behind(held, lambda: _revoke(user, number))

    assert not isinstance(changed, Exception), changed
    assert revoked == UNAVAILABLE
    assert _revoked_whole(user) is False
    stored = User.objects.get(pk=user.pk)
    assert (stored.status == AccountStatus.DISABLED) is (change == "status")


@pytest.mark.parametrize("change", ["role", "status"])
def test_a_change_to_the_account_waits_for_the_revocation_that_is_under_way(
    change: str, user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = _administrator(user_with_roles)
    user = _administrator_account(user_with_roles)
    number = _asked(user)

    held = _Held(monkeypatch, LOCKED, lambda: _revoke(user, number))
    revoked, changed = _behind(held, lambda: _take_away(change, other, user))

    assert revoked == DONE
    assert not isinstance(changed, Exception), changed
    assert _revoked_whole(user) is True


@pytest.mark.parametrize("change", ["role", "status"])
def test_an_approval_waits_for_a_change_to_the_account_and_is_then_refused(
    change: str, user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, _secret, number = _awaiting_break_glass_approval(user_with_roles)
    # An Administrator on record who can change roles and is not able to
    # approve this enrolment: the one who, as far as the record goes,
    # authorised the recovery.
    other = _administrator(user_with_roles)
    AuthenticationEvent.objects.create(
        event_type="mfa_recovery_authorized",
        user=user,
        actor=other.user,
        identifier_key="k",
        source_key="k",
    )
    services.start_mfa_enrollment(actor=signed_in(user), password=PASSWORD, source=SOURCE)
    number = TotpDevice.objects.get(user=user).pk

    held = _Held(monkeypatch, "_serialize_account_changes", lambda: _take_away(change, other, user))
    changed, approved = _behind(held, lambda: _approve_by_break_glass(user, number))

    assert not isinstance(changed, Exception), changed
    assert approved == UNAVAILABLE
    assert TotpDevice.objects.get(user=user).state == TotpDeviceState.PENDING_APPROVAL
    assert _actions() == ["revoke_device"]


# --- Which Administrators are able to act, held still -----------------------------------


def test_a_revocation_waits_for_an_administrator_who_is_becoming_able_to_act(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # One other Administrator is able to act, and a second is giving the
    # first code of an approved device. The command does not decide on a
    # count that is about to be wrong: it waits, and then refuses, because
    # the application's own path is available.
    able = _administrator(user_with_roles)
    becoming = user_with_roles(Role.ADMINISTRATOR)
    becoming.set_password(PASSWORD)
    becoming.save()
    secret, enrolment = _enrolment_request(becoming)
    assert _approve(enrolment, able).outcome == MfaOutcome.ACCEPTED
    user = _administrator_account(user_with_roles)
    number = _asked(user)

    held = _Held(monkeypatch, "_accept_code", lambda: _confirm(becoming, secret))
    confirmed, revoked = _behind(held, lambda: _revoke(user, number))

    assert isinstance(confirmed, MfaResult)
    assert confirmed.outcome == MfaOutcome.ACCEPTED
    assert revoked == UNAVAILABLE
    assert _revoked_whole(user) is False
    assert _authorize(number, able) == AUTHORIZED


def test_an_approval_waits_for_an_administrator_who_is_becoming_able_to_act(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, _secret, number = _awaiting_break_glass_approval(user_with_roles)
    # A second Administrator whose enrolment was approved, written directly:
    # nobody is left who could approve it through the application.
    becoming = user_with_roles(Role.ADMINISTRATOR)
    becoming.set_password(PASSWORD)
    becoming.save()
    other_secret, other_enrolment = _enrolment_request(becoming)
    TotpDevice.objects.filter(pk=other_enrolment).update(
        state=TotpDeviceState.PENDING_VERIFICATION, approved_at=timezone.now()
    )

    held = _Held(monkeypatch, "_accept_code", lambda: _confirm(becoming, other_secret))
    confirmed, approved = _behind(held, lambda: _approve_by_break_glass(user, number))

    assert isinstance(confirmed, MfaResult)
    assert confirmed.outcome == MfaOutcome.ACCEPTED
    # An Administrator who may approve exists by the time the command decides.
    assert approved == UNAVAILABLE
    assert TotpDevice.objects.get(user=user).state == TotpDeviceState.PENDING_APPROVAL


def test_the_code_of_another_administrator_waits_for_a_revocation_and_is_then_accepted(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = _administrator(user_with_roles)
    other_challenge = _challenge(other.user)
    user = _administrator_account(user_with_roles)
    number = _asked(user)

    held = _Held(monkeypatch, LOCKED, lambda: _revoke(user, number))
    revoked, verified_ = _behind(held, lambda: _verify(other_challenge))

    assert revoked == DONE
    assert isinstance(verified_, MfaResult)
    assert verified_.outcome == MfaOutcome.ACCEPTED
    assert User.objects.get(pk=other.user.pk).session_epoch == 0


# --- Other accounts ---------------------------------------------------------------------


def test_the_code_of_an_account_that_is_not_an_administrator_does_not_wait_for_a_revocation(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    reviewer = _account(user_with_roles)
    reviewer_challenge = _challenge(reviewer)
    user = _administrator_account(user_with_roles)
    number = _asked(user)

    # The revocation holds every one of its locks.
    held = _Held(monkeypatch, LOCKED, lambda: _revoke(user, number))
    verified_ = _verify(reviewer_challenge)
    revoked_meanwhile = _actions()
    revoked = held.finish()

    assert verified_.outcome == MfaOutcome.ACCEPTED
    assert revoked_meanwhile == []
    assert revoked == DONE
    assert TotpDevice.objects.filter(user=reviewer, state=TotpDeviceState.ACTIVE).exists()


def test_revocations_for_two_administrators_at_once_are_each_done_whole(
    user_with_roles: UserFactory,
) -> None:
    first, second = _administrator_account(user_with_roles), _administrator_account(user_with_roles)
    numbers = [_asked(first), _asked(second)]

    results = _at_the_same_time(
        partial(_revoke, first, numbers[0]), partial(_revoke, second, numbers[1])
    )

    # Each is the other's one other Administrator, so each is revoked
    # whichever comes first, and neither waits for the other for ever.
    assert results == [DONE, DONE]
    assert _revoked_whole(first) is True
    assert _revoked_whole(second) is True
    assert _actions() == ["revoke_device", "revoke_device"]


def test_a_revocation_and_a_decision_on_another_account_at_once_do_not_deadlock(
    user_with_roles: UserFactory,
) -> None:
    administrator = _administrator(user_with_roles)
    reviewer = _account(user_with_roles)
    reviewer_number = _asked(reviewer)
    user = _administrator_account(user_with_roles)
    number = _asked(user)

    revoked, authorized = _at_the_same_time(
        partial(_revoke, user, number), partial(_authorize, reviewer_number, administrator)
    )

    assert revoked == DONE
    # The account being revoked is the Reviewer's second Administrator only
    # while its device stands: the authorisation is made if it came first.
    assert authorized in (AUTHORIZED, NOT_AUTHORIZED)
    assert _revoked_whole(user) is True
    assert (_openers(reviewer) == 1) is (authorized == AUTHORIZED)


def test_break_glass_actions_for_different_accounts_at_once_are_each_done(
    user_with_roles: UserFactory,
) -> None:
    approving, _secret, enrolment = _awaiting_break_glass_approval(user_with_roles)
    # A second Administrator, who lost the device too.
    revoking = _administrator_account(user_with_roles)
    number = _asked(revoking)

    results = _at_the_same_time(
        partial(_approve_by_break_glass, approving, enrolment), partial(_revoke, revoking, number)
    )

    # The revocation is done in either order. The approval is done only if
    # it came after it: until then the second Administrator may approve.
    assert results[1] == DONE
    assert results[0] in (DONE, UNAVAILABLE)
    assert _revoked_whole(revoking) is True
    approved = TotpDevice.objects.get(user=approving).approved_at is not None
    assert approved is (results[0] == DONE)
