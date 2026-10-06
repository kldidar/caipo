"""Decisions on recovery requests made alongside other operations, on separate
database connections (ADR-0017).

These tests commit their data, because other connections must see it, and the
database is emptied after each of them.

Two kinds of test. One holds an operation in the middle, with its locks, and
starts another behind it: the second must wait, and the order is then known.
The other starts operations together and asserts on every order that the
database could have chosen.
"""

import base64
import re
from collections.abc import Callable
from functools import partial

import pytest
from django.core import mail as django_mail
from django.core.exceptions import PermissionDenied

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
from caipo.accounts.selectors import AuthenticationContext, Role
from caipo.accounts.services import (
    MfaOutcome,
    MfaResult,
    PasswordResetOutcome,
    PasswordResetResult,
    RecoveryDecisionOutcome,
    RecoveryDecisionResult,
    RecoveryRequestOutcome,
    RecoveryRequestResult,
    SignInOutcome,
    SignInResult,
)
from caipo.accounts.tests.fixtures import (
    UserFactory,
    code_at,
    enrolled_device,
    signed_in,
    verified,
)
from caipo.accounts.tests.test_recovery_request_concurrency import (
    _at_the_same_time,
    _behind,
    _Held,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db(transaction=True)]

# Visibly synthetic fixture values.
PASSWORD = "TEST-passphrase-for-fixtures-only"
NEW_PASSWORD = "TEST-passphrase-chosen-afterwards"
SOURCE = "203.0.113.10"
OTHER_SOURCE = "198.51.100.66"

AUTHORIZED = RecoveryDecisionResult(RecoveryDecisionOutcome.AUTHORIZED)
REJECTED = RecoveryDecisionResult(RecoveryDecisionOutcome.REJECTED)
UNAVAILABLE = RecoveryDecisionResult(RecoveryDecisionOutcome.UNAVAILABLE)

# Where a decision holds every one of its locks and has changed nothing yet.
LOCKED = "_recovery_request_for_decision"
ROUNDS = 4


def _account(user_with_roles: UserFactory, role: Role = Role.REVIEWER) -> User:
    user = user_with_roles(role)
    user.set_password(PASSWORD)
    user.save()
    enrolled_device(user)
    return user


def _administrator(user_with_roles: UserFactory) -> AuthenticationContext:
    return verified(_account(user_with_roles, Role.ADMINISTRATOR))


def _challenge(user: User, source: str = SOURCE) -> str:
    result = services.sign_in(email=user.email, password=PASSWORD, source=source)
    assert result.outcome == SignInOutcome.SECOND_FACTOR_REQUIRED
    assert result.challenge is not None
    return result.challenge


def _ask(challenge: str, source: str = SOURCE) -> RecoveryRequestResult:
    return services.request_mfa_recovery(challenge=challenge, source=source)


def _asked(user: User, source: str = SOURCE) -> int:
    result = _ask(_challenge(user, source), source)
    assert result.outcome == RecoveryRequestOutcome.REQUESTED
    assert result.number is not None
    return result.number


def _authorize(number: int, actor: AuthenticationContext) -> RecoveryDecisionResult:
    return services.authorize_mfa_recovery(actor=actor, request_number=number, source=OTHER_SOURCE)


def _reject(number: int, actor: AuthenticationContext) -> RecoveryDecisionResult:
    return services.reject_mfa_recovery(actor=actor, request_number=number, source=OTHER_SOURCE)


def _verify(challenge: str) -> MfaResult:
    return services.verify_second_factor(challenge=challenge, code=code_at(), source=SOURCE)


def _reset_token(user: User) -> str:
    services.request_password_reset(
        email=user.email,
        source=OTHER_SOURCE,
        reset_url=lambda token: f"https://caipo.test/password-reset/confirm/#{token}",
    )
    return str(re.findall(r"#(\S+)", str(django_mail.outbox[-1].body))[-1])


def _reset(token: str) -> PasswordResetResult:
    return services.reset_password(token=token, password=NEW_PASSWORD, source=OTHER_SOURCE)


def _count(event_type: str) -> int:
    return AuthenticationEvent.objects.filter(event_type=event_type).count()


def _recovered(user: User) -> bool:
    """Return whether a recovery of the account was finalised, checking that it was whole."""
    stored = User.objects.get(pk=user.pk)
    authorized = AuthenticationEvent.objects.filter(
        event_type="mfa_recovery_authorized", user=user
    ).count()
    if authorized == 0:
        assert stored.session_epoch == 0
        assert TotpDevice.objects.filter(user=user, state=TotpDeviceState.ACTIVE).exists()
        return False
    assert authorized == 1
    assert stored.session_epoch == 1
    assert not TotpDevice.objects.filter(user=user).exists()
    assert not MfaRecoveryRequest.objects.filter(user=user).exists()
    assert not PasswordReset.objects.filter(user=user).exists()
    return True


# --- Two Administrators and one request -------------------------------------------------


def test_two_administrators_authorising_one_request_at_once_finalise_it_once(
    user_with_roles: UserFactory,
) -> None:
    first, second = _administrator(user_with_roles), _administrator(user_with_roles)
    for _ in range(ROUNDS):
        user = _account(user_with_roles)
        number = _asked(user)

        results = _at_the_same_time(
            partial(_authorize, number, first), partial(_authorize, number, second)
        )

        assert sorted(results, key=repr) == sorted([AUTHORIZED, UNAVAILABLE], key=repr), results
        assert _recovered(user) is True
    assert _count("mfa_recovery_authorized") == ROUNDS


def test_a_second_authorisation_waits_for_the_first_and_finds_the_request_used(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = _administrator(user_with_roles), _administrator(user_with_roles)
    user = _account(user_with_roles)
    number = _asked(user)

    held = _Held(monkeypatch, LOCKED, lambda: _authorize(number, first))
    earlier, later = _behind(held, lambda: _authorize(number, second))

    assert (earlier, later) == (AUTHORIZED, UNAVAILABLE)
    assert _recovered(user) is True
    event = AuthenticationEvent.objects.get(event_type="mfa_recovery_authorized")
    assert event.actor == first.user


# --- An authorisation and a rejection ---------------------------------------------------


def test_an_authorisation_and_a_rejection_at_once_make_one_decision(
    user_with_roles: UserFactory,
) -> None:
    first, second = _administrator(user_with_roles), _administrator(user_with_roles)
    for _ in range(ROUNDS):
        user = _account(user_with_roles)
        number = _asked(user)

        authorized, rejected = _at_the_same_time(
            partial(_authorize, number, first), partial(_reject, number, second)
        )

        assert (authorized, rejected) in ((AUTHORIZED, UNAVAILABLE), (UNAVAILABLE, REJECTED))
        assert _recovered(user) is (authorized == AUTHORIZED)
        decisions = AuthenticationEvent.objects.filter(
            user=user, event_type__in=["mfa_recovery_authorized", "mfa_recovery_rejected"]
        )
        assert decisions.count() == 1
        assert not MfaRecoveryRequest.objects.filter(user=user).exists()


@pytest.mark.parametrize("first_is", ["authorisation", "rejection"])
def test_whichever_decision_comes_second_waits_and_finds_nothing_to_decide(
    first_is: str, user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    one, other = _administrator(user_with_roles), _administrator(user_with_roles)
    user = _account(user_with_roles)
    number = _asked(user)
    decisions: tuple[Callable[..., RecoveryDecisionResult], ...] = (_authorize, _reject)
    first, second = decisions if first_is == "authorisation" else decisions[::-1]

    held = _Held(monkeypatch, LOCKED, lambda: first(number, one))
    earlier, later = _behind(held, lambda: second(number, other))

    assert earlier == (AUTHORIZED if first_is == "authorisation" else REJECTED)
    assert later == UNAVAILABLE
    assert _recovered(user) is (first_is == "authorisation")


# --- An authorisation and a request that replaces the one being authorised --------------


def test_a_request_that_arrives_during_an_authorisation_is_refused(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    administrator, _other = _administrator(user_with_roles), _administrator(user_with_roles)
    user = _account(user_with_roles)
    number = _asked(user)
    # A later sign-in that would ask again.
    challenge = _challenge(user)

    held = _Held(monkeypatch, LOCKED, lambda: _authorize(number, administrator))
    authorized, asked = _behind(held, lambda: _ask(challenge))

    assert authorized == AUTHORIZED
    # The authorisation removed the challenge the request would have used.
    assert asked == RecoveryRequestResult(RecoveryRequestOutcome.REFUSED)
    assert _recovered(user) is True


def test_an_authorisation_of_a_request_that_is_being_replaced_is_unavailable(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    administrator, _other = _administrator(user_with_roles), _administrator(user_with_roles)
    user = _account(user_with_roles)
    earlier = _asked(user)
    challenge = _challenge(user)

    # The new request has removed the earlier one and has not yet committed.
    # The authorisation finds the earlier number, waits, and looks again.
    held = _Held(monkeypatch, "_challenge_for_recovery", lambda: _ask(challenge))
    asked, authorized = _behind(held, lambda: _authorize(earlier, administrator))

    assert isinstance(asked, RecoveryRequestResult)
    assert asked.outcome == RecoveryRequestOutcome.REQUESTED
    assert authorized == UNAVAILABLE
    assert _recovered(user) is False
    assert MfaRecoveryRequest.objects.get(user=user).pk == asked.number != earlier


def test_an_authorisation_and_a_replacing_request_at_once_leave_a_consistent_state(
    user_with_roles: UserFactory,
) -> None:
    administrator, _other = _administrator(user_with_roles), _administrator(user_with_roles)
    for _ in range(ROUNDS):
        user = _account(user_with_roles)
        number = _asked(user)
        challenge = _challenge(user)

        authorized, asked = _at_the_same_time(
            partial(_authorize, number, administrator), partial(_ask, challenge)
        )

        assert isinstance(asked, RecoveryRequestResult), asked
        assert authorized in (AUTHORIZED, UNAVAILABLE), authorized
        # Exactly one of them used what the other needed.
        assert (authorized == AUTHORIZED) is (asked.outcome == RecoveryRequestOutcome.REFUSED)
        assert _recovered(user) is (authorized == AUTHORIZED)


# --- An authorisation and a sign-in of the account --------------------------------------


def test_a_sign_in_that_arrives_during_an_authorisation_finds_no_second_factor(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    administrator, _other = _administrator(user_with_roles), _administrator(user_with_roles)
    user = _account(user_with_roles)
    number = _asked(user)

    held = _Held(monkeypatch, LOCKED, lambda: _authorize(number, administrator))
    authorized, signed = _behind(
        held, lambda: services.sign_in(email=user.email, password=PASSWORD, source=SOURCE)
    )

    assert authorized == AUTHORIZED
    assert isinstance(signed, SignInResult)
    # It ran wholly after the recovery: the password alone, at the new epoch.
    assert signed.outcome == SignInOutcome.SIGNED_IN
    assert signed.user is not None
    assert signed.user.session_epoch == 1
    assert not MfaChallenge.objects.filter(user=user).exists()


def test_an_authorisation_that_arrives_during_a_sign_in_removes_its_challenge(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    administrator, _other = _administrator(user_with_roles), _administrator(user_with_roles)
    user = _account(user_with_roles)
    number = _asked(user)

    # The sign-in holds the lock on the account's email address and has not
    # yet stored its challenge.
    held = _Held(
        monkeypatch,
        "_throttled_by",
        lambda: services.sign_in(email=user.email, password=PASSWORD, source=SOURCE),
    )
    signed, authorized = _behind(held, lambda: _authorize(number, administrator))

    assert isinstance(signed, SignInResult)
    assert signed.outcome == SignInOutcome.SECOND_FACTOR_REQUIRED
    assert signed.challenge is not None
    assert authorized == AUTHORIZED
    assert _verify(signed.challenge).outcome == MfaOutcome.REFUSED
    assert _count("login_success") == 0
    assert _recovered(user) is True


# --- An authorisation and a code for the account ----------------------------------------


def test_a_code_that_arrives_during_an_authorisation_is_refused(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    administrator, _other = _administrator(user_with_roles), _administrator(user_with_roles)
    user = _account(user_with_roles)
    number = _asked(user)
    challenge = _challenge(user)

    held = _Held(monkeypatch, LOCKED, lambda: _authorize(number, administrator))
    authorized, verified_code = _behind(held, lambda: _verify(challenge))

    assert authorized == AUTHORIZED
    assert verified_code == MfaResult(MfaOutcome.REFUSED)
    assert _count("login_success") == 0
    assert _count("mfa_verification_succeeded") == 0
    assert _recovered(user) is True


def test_an_authorisation_that_arrives_while_a_code_is_examined_ends_the_sign_in_it_completes(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    administrator, _other = _administrator(user_with_roles), _administrator(user_with_roles)
    user = _account(user_with_roles)
    number = _asked(user)
    challenge = _challenge(user)

    held = _Held(monkeypatch, "_pending_challenge", lambda: _verify(challenge))
    verified_code, authorized = _behind(held, lambda: _authorize(number, administrator))

    assert isinstance(verified_code, MfaResult)
    assert verified_code.outcome == MfaOutcome.ACCEPTED
    assert authorized == AUTHORIZED
    assert _recovered(user) is True
    # The sign-in was completed at the epoch that the recovery has since
    # left behind, against a device that no longer exists.
    context = verified_code.context
    assert context is not None
    stored = User.objects.get(pk=user.pk)
    assert context.user.get_session_auth_hash() != stored.get_session_auth_hash()
    assert selectors.permissions_of(context) == {selectors.Permission.MFA_MANAGE_OWN}


def test_an_authorisation_and_a_code_at_once_never_leave_a_verified_sign_in_behind(
    user_with_roles: UserFactory,
) -> None:
    administrator, _other = _administrator(user_with_roles), _administrator(user_with_roles)
    for _ in range(ROUNDS):
        user = _account(user_with_roles)
        number = _asked(user)
        challenge = _challenge(user)

        authorized, verified_code = _at_the_same_time(
            partial(_authorize, number, administrator), partial(_verify, challenge)
        )

        assert authorized == AUTHORIZED, authorized
        assert isinstance(verified_code, MfaResult), verified_code
        assert _recovered(user) is True
        assert not MfaChallenge.objects.filter(user=user).exists()
        if verified_code.context is not None:
            assert selectors.permissions_of(verified_code.context) == {
                selectors.Permission.MFA_MANAGE_OWN
            }


# --- An authorisation and a password reset ----------------------------------------------


def test_an_authorisation_that_arrives_during_a_password_reset_is_unavailable(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    administrator, _other = _administrator(user_with_roles), _administrator(user_with_roles)
    user = _account(user_with_roles)
    token = _reset_token(user)
    number = _asked(user)

    held = _Held(monkeypatch, "_pending_password_reset", lambda: _reset(token))
    reset, authorized = _behind(held, lambda: _authorize(number, administrator))

    assert reset == PasswordResetResult(PasswordResetOutcome.RESET)
    # The request was made on a password that no longer exists.
    assert authorized == UNAVAILABLE
    assert _recovered(user) is False
    assert User.objects.get(pk=user.pk).check_password(NEW_PASSWORD) is True


def test_a_password_reset_that_arrives_during_an_authorisation_finds_its_token_removed(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    administrator, _other = _administrator(user_with_roles), _administrator(user_with_roles)
    user = _account(user_with_roles)
    token = _reset_token(user)
    number = _asked(user)

    held = _Held(monkeypatch, LOCKED, lambda: _authorize(number, administrator))
    authorized, reset = _behind(held, lambda: _reset(token))

    assert authorized == AUTHORIZED
    assert reset == PasswordResetResult(PasswordResetOutcome.REFUSED)
    assert _recovered(user) is True
    assert User.objects.get(pk=user.pk).check_password(PASSWORD) is True
    assert _count("password_reset_succeeded") == 0


def test_an_authorisation_and_a_password_reset_at_once_never_both_take_effect(
    user_with_roles: UserFactory,
) -> None:
    # Security property 5: whichever order the database chose, a reset and a
    # recovery of the same account are never both done.
    administrator, _other = _administrator(user_with_roles), _administrator(user_with_roles)
    for _ in range(ROUNDS):
        user = _account(user_with_roles)
        token = _reset_token(user)
        number = _asked(user)

        authorized, reset = _at_the_same_time(
            partial(_authorize, number, administrator), partial(_reset, token)
        )

        assert isinstance(reset, PasswordResetResult), reset
        assert (authorized, reset.outcome) in (
            (AUTHORIZED, PasswordResetOutcome.REFUSED),
            (UNAVAILABLE, PasswordResetOutcome.RESET),
        ), (authorized, reset)
        assert _recovered(user) is (authorized == AUTHORIZED)
        password_was_reset = User.objects.get(pk=user.pk).check_password(NEW_PASSWORD)
        assert password_was_reset is (reset.outcome == PasswordResetOutcome.RESET)


def test_a_request_and_a_reset_sent_at_once_are_ordered_by_their_events_for_the_authorisation(
    user_with_roles: UserFactory, caplog: pytest.LogCaptureFixture
) -> None:
    # A request and a reset of one account hold the same locks, so one is
    # recorded wholly before the other. The authorisation that follows reads
    # that order from the events, whatever the two clocks said.
    administrator, _other = _administrator(user_with_roles), _administrator(user_with_roles)
    for _ in range(ROUNDS):
        user = _account(user_with_roles)
        token = _reset_token(user)
        challenge = _challenge(user)
        caplog.clear()

        asked, reset = _at_the_same_time(partial(_ask, challenge), partial(_reset, token))

        assert reset == PasswordResetResult(PasswordResetOutcome.RESET), reset
        assert isinstance(asked, RecoveryRequestResult), asked
        if asked.number is None:
            # The reset came first and removed the challenge: no request.
            assert not MfaRecoveryRequest.objects.filter(user=user).exists()
            continue
        events = AuthenticationEvent.objects.filter(user=user)
        requested = events.get(event_type="mfa_recovery_requested")
        succeeded = events.get(event_type="password_reset_succeeded")
        assert requested.pk < succeeded.pk
        assert _authorize(asked.number, administrator) == UNAVAILABLE
        assert [
            record.__dict__["reason"]
            for record in caplog.records
            if record.__dict__.get("event") == "mfa_recovery.decision_unavailable"
        ] == ["request_precedes_reset"]
        assert _recovered(user) is False


# --- An authorisation and a change to the actor's own second factor ---------------------


def _give_up_device(actor: AuthenticationContext, operation: str) -> MfaResult:
    change = services.disable_mfa if operation == "disable" else services.replace_mfa_device
    return change(actor=actor, password=PASSWORD, code=code_at(), source=OTHER_SOURCE)


@pytest.mark.parametrize("operation", ["disable", "replace"])
def test_an_actor_whose_device_is_being_given_up_authorises_nothing(
    operation: str, user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    administrator, _other = _administrator(user_with_roles), _administrator(user_with_roles)
    user = _account(user_with_roles)
    number = _asked(user)

    # The device is deleted and the deletion has not yet committed: a check
    # made now, without the actor's second-factor lock, still sees it.
    held = _Held(
        monkeypatch, "_remove_active_device", lambda: _give_up_device(administrator, operation)
    )
    assert selectors.can(administrator, selectors.Permission.MFA_RECOVERY_AUTHORIZE)
    given_up, authorized = _behind(held, lambda: _authorize(number, administrator))

    assert isinstance(given_up, MfaResult)
    assert given_up.outcome == MfaOutcome.ACCEPTED
    # The decision made under the lock found no verified second factor.
    assert isinstance(authorized, PermissionDenied), authorized
    assert _recovered(user) is False
    assert MfaRecoveryRequest.objects.filter(pk=number).exists()


@pytest.mark.parametrize("operation", ["disable", "replace"])
def test_an_actor_cannot_give_up_the_device_while_authorising_with_it(
    operation: str, user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    administrator, _other = _administrator(user_with_roles), _administrator(user_with_roles)
    user = _account(user_with_roles)
    number = _asked(user)

    held = _Held(monkeypatch, LOCKED, lambda: _authorize(number, administrator))
    # Still verified at this moment, and held so until the commit.
    assert TotpDevice.objects.filter(user=administrator.user, state="active").exists()
    authorized, given_up = _behind(held, lambda: _give_up_device(administrator, operation))

    assert authorized == AUTHORIZED
    assert isinstance(given_up, MfaResult)
    assert given_up.outcome == MfaOutcome.ACCEPTED
    assert _recovered(user) is True
    event = AuthenticationEvent.objects.get(event_type="mfa_recovery_authorized")
    assert event.actor == administrator.user
    # The event was written before the device went.
    given = "mfa_disabled" if operation == "disable" else "mfa_device_replaced"
    assert event.pk < AuthenticationEvent.objects.get(event_type=given).pk


def test_an_actor_whose_own_code_is_being_examined_elsewhere_waits_and_then_authorises(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    administrator, _other = _administrator(user_with_roles), _administrator(user_with_roles)
    user = _account(user_with_roles)
    number = _asked(user)
    own_challenge = _challenge(administrator.user, OTHER_SOURCE)

    held = _Held(monkeypatch, "_pending_challenge", lambda: _verify(own_challenge))
    verified_code, authorized = _behind(held, lambda: _authorize(number, administrator))

    assert isinstance(verified_code, MfaResult)
    assert verified_code.outcome == MfaOutcome.ACCEPTED
    assert authorized == AUTHORIZED


# --- An authorisation and a change to the actor's role or status ------------------------


@pytest.mark.parametrize("change", ["role", "status"])
def test_an_actor_who_is_losing_the_role_or_the_account_authorises_nothing(
    change: str, user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    administrator, other = _administrator(user_with_roles), _administrator(user_with_roles)
    user = _account(user_with_roles)
    number = _asked(user)

    def take_away() -> object:
        if change == "role":
            return services.revoke_role(
                actor=other, user=administrator.user, role=Role.ADMINISTRATOR, reason="TEST"
            )
        services.disable_user(actor=other, user=administrator.user)
        return None

    # The change holds the lock on the role events and has not yet committed:
    # a check made now still sees an Administrator.
    held = _Held(monkeypatch, "_require_another_administrator", take_away)
    assert selectors.can(administrator, selectors.Permission.MFA_RECOVERY_AUTHORIZE)
    changed, authorized = _behind(held, lambda: _authorize(number, administrator))

    assert not isinstance(changed, Exception), changed
    assert isinstance(authorized, PermissionDenied), authorized
    assert _recovered(user) is False
    assert MfaRecoveryRequest.objects.filter(pk=number).exists()
    assert not selectors.can(administrator, selectors.Permission.MFA_RECOVERY_AUTHORIZE)


@pytest.mark.parametrize("change", ["role", "status"])
def test_a_change_to_the_actor_waits_for_the_authorisation_that_is_under_way(
    change: str, user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    administrator, other = _administrator(user_with_roles), _administrator(user_with_roles)
    user = _account(user_with_roles)
    number = _asked(user)

    def take_away() -> object:
        if change == "role":
            return services.revoke_role(
                actor=other, user=administrator.user, role=Role.ADMINISTRATOR, reason="TEST"
            )
        services.disable_user(actor=other, user=administrator.user)
        return None

    held = _Held(monkeypatch, LOCKED, lambda: _authorize(number, administrator))
    authorized, changed = _behind(held, take_away)

    assert authorized == AUTHORIZED
    assert not isinstance(changed, Exception), changed
    assert _recovered(user) is True
    assert not selectors.can(administrator, selectors.Permission.MFA_RECOVERY_AUTHORIZE)


# --- An authorisation and a change to the account's role or status ----------------------


@pytest.mark.parametrize("change", ["role", "status"])
def test_an_account_that_is_losing_its_role_or_being_disabled_is_not_recovered(
    change: str, user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    administrator, other = _administrator(user_with_roles), _administrator(user_with_roles)
    user = _account(user_with_roles)
    number = _asked(user)

    def take_away() -> object:
        if change == "role":
            return services.revoke_role(actor=other, user=user, role=Role.REVIEWER, reason="TEST")
        services.disable_user(actor=other, user=user)
        return None

    # Held with the lock on the role events and nothing yet written.
    held = _Held(monkeypatch, "_serialize_account_changes", take_away)
    changed, authorized = _behind(held, lambda: _authorize(number, administrator))

    assert not isinstance(changed, Exception), changed
    assert authorized == UNAVAILABLE
    assert _recovered(user) is False
    stored = User.objects.get(pk=user.pk)
    assert (stored.status == AccountStatus.DISABLED) is (change == "status")


@pytest.mark.parametrize("change", ["role", "status"])
def test_a_change_to_the_account_waits_for_the_authorisation_that_is_under_way(
    change: str, user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    administrator, other = _administrator(user_with_roles), _administrator(user_with_roles)
    user = _account(user_with_roles)
    number = _asked(user)

    def take_away() -> object:
        if change == "role":
            return services.revoke_role(actor=other, user=user, role=Role.REVIEWER, reason="TEST")
        services.disable_user(actor=other, user=user)
        return None

    held = _Held(monkeypatch, LOCKED, lambda: _authorize(number, administrator))
    authorized, changed = _behind(held, take_away)

    assert authorized == AUTHORIZED
    assert not isinstance(changed, Exception), changed
    assert _recovered(user) is True


def test_the_other_administrator_leaving_during_an_authorisation_stops_it(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Three Administrators on record: the actor, one who is able to act, and
    # one who has no second factor and so cannot approve anything.
    administrator, leaving = _administrator(user_with_roles), _administrator(user_with_roles)
    user_with_roles(Role.ADMINISTRATOR)
    user = _account(user_with_roles)
    number = _asked(user)
    assert selectors.an_administrator_is_able_to_act(besides=(administrator.user.pk, user.pk))

    # The only other Administrator who is able to act disables their own
    # account, which the last-Administrator rule allows. The disabling holds
    # the lock on the role events and has not yet committed.
    held = _Held(
        monkeypatch,
        "_require_another_administrator",
        lambda: services.disable_user(actor=leaving, user=leaving.user),
    )
    changed, authorized = _behind(held, lambda: _authorize(number, administrator))

    assert changed is None
    # Nobody is left to approve the device that would follow.
    assert authorized == UNAVAILABLE
    assert _recovered(user) is False


# --- Authorisations for different accounts ----------------------------------------------


def test_authorisations_for_different_accounts_at_once_are_each_done_whole(
    user_with_roles: UserFactory,
) -> None:
    administrators = [_administrator(user_with_roles) for _ in range(3)]
    users = [_account(user_with_roles) for _ in range(6)]
    numbers = [_asked(user, f"203.0.113.{index + 1}") for index, user in enumerate(users)]

    results = _at_the_same_time(
        *(
            partial(_authorize, number, administrators[index % 3])
            for index, number in enumerate(numbers)
        )
    )

    assert results == [AUTHORIZED] * 6
    assert all(_recovered(user) for user in users)
    assert _count("mfa_recovery_authorized") == 6
    for administrator in administrators:
        assert User.objects.get(pk=administrator.user.pk).session_epoch == 0
        assert TotpDevice.objects.filter(user=administrator.user, state="active").exists()


def test_an_authorisation_for_another_account_waits_and_is_then_done(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = _administrator(user_with_roles), _administrator(user_with_roles)
    one, other = _account(user_with_roles), _account(user_with_roles)
    numbers = _asked(one), _asked(other)

    held = _Held(monkeypatch, LOCKED, lambda: _authorize(numbers[0], first))
    earlier, later = _behind(held, lambda: _authorize(numbers[1], second))

    assert (earlier, later) == (AUTHORIZED, AUTHORIZED)
    assert _recovered(one) is True
    assert _recovered(other) is True


# --- The order of the actor's and the account's locks -----------------------------------


def test_two_administrators_authorising_each_other_at_once_do_not_deadlock(
    user_with_roles: UserFactory,
) -> None:
    # Each is the actor of one decision and the account of the other, so
    # each decision needs the second-factor locks of the same two accounts.
    # Neither device is lost: each asked from a second sign-in.
    _third = _administrator(user_with_roles)
    for _ in range(ROUNDS):
        first, second = _administrator(user_with_roles), _administrator(user_with_roles)
        for_first, for_second = _asked(first.user), _asked(second.user)

        results = _at_the_same_time(
            partial(_authorize, for_second, first), partial(_authorize, for_first, second)
        )

        # One was done. It revoked the other actor's device, and the decision
        # that other made under the locks found no verified second factor.
        assert AUTHORIZED in results, results
        (refused,) = [result for result in results if result != AUTHORIZED]
        assert isinstance(refused, PermissionDenied), refused
        recovered = [_recovered(first.user), _recovered(second.user)]
        assert sorted(recovered) == [False, True]
        assert results.index(AUTHORIZED) == recovered.index(False)


@pytest.mark.parametrize("actor_first", [True, False])
def test_a_decision_asks_for_the_two_second_factor_locks_in_ascending_order(
    actor_first: bool, user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    _third = _administrator(user_with_roles)
    low, high = _administrator(user_with_roles), _administrator(user_with_roles)
    assert low.user.pk < high.user.pk
    actor, account = (low, high) if actor_first else (high, low)
    number = _asked(account.user)
    asked_for: list[int] = []
    lock = services._lock_second_factor

    def note(user_id: int) -> None:
        asked_for.append(user_id)
        lock(user_id)

    monkeypatch.setattr(services, "_lock_second_factor", note)

    assert _authorize(number, actor) == AUTHORIZED
    assert asked_for == [low.user.pk, high.user.pk]


# --- The Administrator who authorised, and the enrolment that follows -------------------


def _enrolment_request(user: User) -> tuple[bytes, int]:
    result = services.start_mfa_enrollment(actor=signed_in(user), password=PASSWORD, source=SOURCE)
    assert result.provisioning is not None
    number = selectors.enrollment_request_number_of(user)
    assert number is not None
    return base64.b32decode(result.provisioning.secret), number


def _approve(number: int, actor: AuthenticationContext) -> MfaResult:
    return services.approve_mfa_enrollment(actor=actor, request_number=number, source=OTHER_SOURCE)


def test_the_authoriser_and_another_administrator_approving_at_once_leave_the_others_approval(
    user_with_roles: UserFactory,
) -> None:
    authoriser, other = _administrator(user_with_roles), _administrator(user_with_roles)
    for _ in range(ROUNDS):
        user = _account(user_with_roles)
        assert _authorize(_asked(user), authoriser) == AUTHORIZED
        _secret, number = _enrolment_request(user)

        by_authoriser, by_other = _at_the_same_time(
            partial(_approve, number, authoriser), partial(_approve, number, other)
        )

        # Refused outright, or too late to find a request that awaits
        # approval: never accepted.
        assert isinstance(by_authoriser, PermissionDenied) or by_authoriser == MfaResult(
            MfaOutcome.UNAVAILABLE
        ), by_authoriser
        assert by_other == MfaResult(MfaOutcome.ACCEPTED)
        assert TotpDevice.objects.get(user=user).approved_by == other.user


def test_an_approval_by_the_authoriser_that_arrives_during_the_authorisation_is_refused(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The authorisation holds its locks and has not yet committed, so no
    # record of it can be read. The approval the same Administrator sends
    # now must not slip through before the record exists.
    authoriser, _other = _administrator(user_with_roles), _administrator(user_with_roles)
    user = _account(user_with_roles)
    number = _asked(user)
    device = TotpDevice.objects.get(user=user).pk

    held = _Held(monkeypatch, LOCKED, lambda: _authorize(number, authoriser))
    approved = _approve(device, authoriser)
    authorized = held.finish()

    assert authorized == AUTHORIZED
    # The account's device was active, not awaiting approval: there was
    # nothing to approve, and afterwards there is no device.
    assert approved == MfaResult(MfaOutcome.UNAVAILABLE)
    assert _recovered(user) is True
    _secret, following = _enrolment_request(user)
    with pytest.raises(PermissionDenied):
        _approve(following, authoriser)


def test_the_authoriser_approving_while_the_first_code_is_examined_is_still_refused(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    authoriser, other = _administrator(user_with_roles), _administrator(user_with_roles)
    user = _account(user_with_roles)
    assert _authorize(_asked(user), authoriser) == AUTHORIZED
    secret, number = _enrolment_request(user)
    assert _approve(number, other).outcome == MfaOutcome.ACCEPTED

    # The first code is accepted and the enrolment is not yet committed.
    held = _Held(
        monkeypatch,
        "_accept_code",
        lambda: services.confirm_mfa_enrollment(
            actor=signed_in(user), code=code_at(secret=secret), source=SOURCE
        ),
    )
    approved = _approve(number, authoriser)
    confirmed = held.finish()

    assert isinstance(confirmed, MfaResult)
    assert confirmed.outcome == MfaOutcome.ACCEPTED
    # The request was approved already and awaited no decision: there was
    # nothing for the authoriser to wait for or to approve.
    assert approved == MfaResult(MfaOutcome.UNAVAILABLE)
    assert TotpDevice.objects.get(user=user).approved_by == other.user
    assert selectors.open_recovery_authorizer_id(user.pk) is None
