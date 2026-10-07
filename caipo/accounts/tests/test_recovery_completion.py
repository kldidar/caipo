"""The record that a recovery is complete (ADR-0017, points 37, 48, and 49).

A recovery that an Administrator authorised is complete when the device the
account then enrols, and another Administrator approves, accepts its first
code. No HTTP is involved, and nothing stands in for TOTP or for the
authorization decision: requests are made, authorised, and approved, and
enrolments confirmed, by the services themselves.
"""

import base64
import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.conf import LazySettings
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from caipo.accounts import selectors, services
from caipo.accounts.models import (
    AccountStatus,
    AuthenticationEvent,
    AuthenticationEventType,
    RoleEventType,
    TotpDevice,
    TotpDeviceState,
    User,
)
from caipo.accounts.selectors import Assurance, AuthenticationContext, MfaState, Permission, Role
from caipo.accounts.services import MfaOutcome
from caipo.accounts.tests.fixtures import (
    Clock,
    UserFactory,
    code_at,
    enrolled_device,
    logged,
    signed_in,
    verified,
)
from caipo.accounts.tests.test_recovery_authorization import (
    ADMINISTRATOR_SOURCE,
    AUTHORIZED,
    HOUR,
    PASSWORD,
    SOURCE,
    STEP,
    _approve,
    _asked,
    _authorize,
    _change_role,
    _confirm,
    _enrolment_request,
    _events,
    _reject,
    _state,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db]

type AccountFactory = Callable[..., User]

COMPLETED = "mfa_recovery_completed"
MINUTE = timedelta(minutes=1)


@pytest.fixture
def account(user_with_roles: UserFactory) -> AccountFactory:
    """Return a factory for synthetic users with a known password and an active second factor."""

    def make(*roles: Role) -> User:
        user = user_with_roles(*roles)
        user.set_password(PASSWORD)
        user.save()
        enrolled_device(user)
        return user

    return make


@pytest.fixture
def administrator(account: AccountFactory) -> AuthenticationContext:
    """Return the verified context of the Administrator who authorises."""
    return verified(account(Role.ADMINISTRATOR))


@pytest.fixture
def another(account: AccountFactory) -> AuthenticationContext:
    """Return the verified context of the Administrator who approves the enrolment."""
    return verified(account(Role.ADMINISTRATOR))


def _completions(user: User | None = None) -> list[AuthenticationEvent]:
    events = AuthenticationEvent.objects.filter(event_type=COMPLETED).order_by("id")
    if user is not None:
        events = events.filter(user=user)
    return list(events)


def _approved_after_recovery(
    user: User, authoriser: AuthenticationContext, approver: AuthenticationContext
) -> bytes:
    """Take the account's recovery as far as an approved enrolment; return the new secret."""
    assert _authorize(_asked(user), authoriser) == AUTHORIZED
    secret, number = _enrolment_request(user)
    assert _approve(number, approver).outcome == MfaOutcome.ACCEPTED
    return secret


def _without_a_device(user_with_roles: UserFactory, *roles: Role) -> User:
    user = user_with_roles(*roles)
    user.set_password(PASSWORD)
    user.save()
    return user


def _event(event_type: str, user: User, *, actor: User | None = None) -> AuthenticationEvent:
    return AuthenticationEvent.objects.create(
        event_type=event_type, user=user, actor=actor, identifier_key="k", source_key="s"
    )


# --- A recovery is complete at the first code of the approved device (point 49) ---------


@pytest.mark.parametrize("role", [Role.REVIEWER, Role.ADMINISTRATOR])
def test_the_first_code_of_the_approved_device_completes_the_recovery(
    role: Role,
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    user = account(role)
    secret = _approved_after_recovery(user, administrator, another)
    assert _completions() == []

    confirmed = _confirm(user, secret)

    assert confirmed.outcome == MfaOutcome.ACCEPTED
    assert _events(user)[-6:] == [
        "mfa_recovery_requested",
        "mfa_recovery_authorized",
        "mfa_enrollment_started",
        "mfa_enrollment_approved",
        "mfa_enrollment_succeeded",
        COMPLETED,
    ]
    (completed,) = _completions()
    assert completed.user == user
    assert "mfa_recovery.completed" in [record.__dict__.get("event") for record in caplog.records]


def test_the_completion_names_the_account_and_nobody_else(
    account: AccountFactory, administrator: AuthenticationContext, another: AuthenticationContext
) -> None:
    user = account(Role.REVIEWER)
    secret = _approved_after_recovery(user, administrator, another)
    _confirm(user, secret)

    (completed,) = _completions()
    succeeded = AuthenticationEvent.objects.get(event_type="mfa_enrollment_succeeded", user=user)
    assert completed.user == user
    assert completed.actor is None
    assert completed.break_glass_action == ""
    # Recorded under the request that gave the code, as its enrolment event is.
    assert (completed.identifier_key, completed.source_key, completed.correlation_id) == (
        succeeded.identifier_key,
        succeeded.source_key,
        succeeded.correlation_id,
    )
    assert completed.source_key != ""


def test_the_completion_follows_its_enrolment_and_its_authorisation_by_identifier(
    account: AccountFactory, administrator: AuthenticationContext, another: AuthenticationContext
) -> None:
    user = account(Role.REVIEWER)
    secret = _approved_after_recovery(user, administrator, another)
    _confirm(user, secret)

    identifiers = {
        event_type: AuthenticationEvent.objects.get(event_type=event_type, user=user).pk
        for event_type in ("mfa_recovery_authorized", "mfa_enrollment_succeeded", COMPLETED)
    }
    assert (
        identifiers["mfa_recovery_authorized"]
        < identifiers["mfa_enrollment_succeeded"]
        < identifiers[COMPLETED]
    )


def test_the_completion_gives_nothing_that_a_confirmed_enrolment_does_not(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    user_with_roles: UserFactory,
) -> None:
    # The same enrolment with and without a recovery before it: the two
    # results differ only in whose they are.
    recovered = account(Role.REVIEWER)
    secret = _approved_after_recovery(recovered, administrator, another)
    plain = _without_a_device(user_with_roles, Role.REVIEWER)
    plain_secret, number = _enrolment_request(plain)
    assert _approve(number, another).outcome == MfaOutcome.ACCEPTED

    after_recovery = _confirm(recovered, secret)
    without = _confirm(plain, plain_secret)

    for result, user in ((after_recovery, recovered), (without, plain)):
        assert result.outcome == MfaOutcome.ACCEPTED
        assert result.provisioning is None
        assert result.context == AuthenticationContext(
            user, Assurance.MFA_VERIFIED, TotpDevice.objects.get(user=user).pk
        )
        assert selectors.can(result.context, Permission.RESEARCH_REVIEW)
    assert [event.user for event in _completions()] == [recovered]


def test_completing_changes_nothing_but_the_device_and_the_two_events(
    account: AccountFactory, administrator: AuthenticationContext, another: AuthenticationContext
) -> None:
    user = account(Role.REVIEWER, Role.READER)
    secret = _approved_after_recovery(user, administrator, another)
    before = _state()

    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED

    after = _state()
    # The password, status, session epoch, email address and its verification
    # of every account, every role, and every request, challenge, and reset
    # token are as they were.
    for unchanged in ("users", "roles", "requests", "challenges", "resets"):
        assert after[unchanged] == before[unchanged], unchanged
    assert User.objects.get(pk=user.pk).session_epoch == 1
    # Nothing was removed from the record or changed in it, and what was
    # added is the enrolment and the completion: no count that throttles
    # anything moved.
    assert after["events"][: len(before["events"])] == before["events"]
    assert [event["event_type"] for event in after["events"][len(before["events"]) :]] == [
        "mfa_enrollment_succeeded",
        COMPLETED,
    ]
    # One device, the one that was approved, and no other.
    (device_before,) = (row for row in before["devices"] if row["user_id"] == user.pk)
    (device_after,) = (row for row in after["devices"] if row["user_id"] == user.pk)
    assert device_after["id"] == device_before["id"]
    assert device_after["state"] == TotpDeviceState.ACTIVE
    assert device_after["approved_by_id"] == another.user.pk
    assert [row for row in after["devices"] if row["user_id"] != user.pk] == [
        row for row in before["devices"] if row["user_id"] != user.pk
    ]


# --- What does not complete a recovery --------------------------------------------------


def test_an_approval_alone_completes_nothing(
    account: AccountFactory, administrator: AuthenticationContext, another: AuthenticationContext
) -> None:
    user = account(Role.REVIEWER)

    _approved_after_recovery(user, administrator, another)

    assert _completions() == []
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION
    assert selectors.open_recovery_authorizer_id(user.pk) == administrator.user.pk


def test_a_wrong_first_code_completes_nothing_and_the_right_one_then_does(
    account: AccountFactory, administrator: AuthenticationContext, another: AuthenticationContext
) -> None:
    user = account(Role.REVIEWER)
    secret = _approved_after_recovery(user, administrator, another)
    right = code_at(secret=secret)
    wrong = f"{(int(right) + 1) % 10**6:06d}"

    refused = services.confirm_mfa_enrollment(actor=signed_in(user), code=wrong, source=SOURCE)

    assert refused.outcome == MfaOutcome.REFUSED
    assert _events(user)[-1] == "mfa_verification_failed"
    assert _completions() == []
    assert selectors.open_recovery_authorizer_id(user.pk) == administrator.user.pk

    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED
    assert len(_completions(user)) == 1


def test_an_approved_enrolment_that_lapsed_completes_nothing(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    clock: Clock,
    settings: LazySettings,
) -> None:
    user = account(Role.REVIEWER)
    secret = _approved_after_recovery(user, administrator, another)
    clock(settings.MFA_APPROVAL_LIFETIME)

    assert _confirm(user, secret).outcome == MfaOutcome.UNAVAILABLE

    assert _completions() == []
    assert selectors.open_recovery_authorizer_id(user.pk) == administrator.user.pk


def test_a_throttled_first_code_completes_nothing(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    settings: LazySettings,
) -> None:
    user = account(Role.REVIEWER)
    secret = _approved_after_recovery(user, administrator, another)
    right = code_at(secret=secret)
    wrong = f"{(int(right) + 1) % 10**6:06d}"
    for _ in range(settings.MFA_THROTTLE_FAILURES):
        services.confirm_mfa_enrollment(actor=signed_in(user), code=wrong, source=SOURCE)

    assert _confirm(user, secret).outcome == MfaOutcome.THROTTLED

    assert _completions() == []
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION


def test_a_disabled_account_completes_nothing(
    account: AccountFactory, administrator: AuthenticationContext, another: AuthenticationContext
) -> None:
    user = account(Role.REVIEWER)
    secret = _approved_after_recovery(user, administrator, another)
    User.objects.filter(pk=user.pk).update(status=AccountStatus.DISABLED)
    user.refresh_from_db()

    with pytest.raises(PermissionDenied):
        _confirm(user, secret)

    assert _completions() == []
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION


def test_an_enrolment_that_follows_no_recovery_completes_nothing(
    user_with_roles: UserFactory, administrator: AuthenticationContext
) -> None:
    user = _without_a_device(user_with_roles, Role.REVIEWER)
    secret, number = _enrolment_request(user)
    assert _approve(number, administrator).outcome == MfaOutcome.ACCEPTED

    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED

    assert _events(user) == [
        "mfa_enrollment_started",
        "mfa_enrollment_approved",
        "mfa_enrollment_succeeded",
    ]
    assert _completions() == []


def test_an_enrolment_that_needs_no_approval_completes_nothing(
    user_with_roles: UserFactory,
) -> None:
    user = _without_a_device(user_with_roles, Role.READER)
    started = services.start_mfa_enrollment(actor=signed_in(user), password=PASSWORD, source=SOURCE)
    assert started.provisioning is not None

    assert _confirm(user, base64.b32decode(started.provisioning.secret)).outcome == (
        MfaOutcome.ACCEPTED
    )

    assert _completions() == []


def test_a_rejected_recovery_request_is_not_completed_by_a_later_enrolment(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    clock: Clock,
) -> None:
    user = account(Role.REVIEWER)
    _reject(_asked(user), administrator)
    # The owner still holds the device and replaces it on both proofs.
    clock(STEP * 4)
    replaced = services.replace_mfa_device(
        actor=signed_in(user), password=PASSWORD, code=code_at(), source=SOURCE
    )
    assert replaced.provisioning is not None
    number = selectors.enrollment_request_number_of(user)
    assert number is not None
    assert _approve(number, another).outcome == MfaOutcome.ACCEPTED

    assert _confirm(user, base64.b32decode(replaced.provisioning.secret)).outcome == (
        MfaOutcome.ACCEPTED
    )

    assert _completions() == []


def test_a_device_that_nobody_approved_completes_nothing_and_its_approved_successor_does(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    clock: Clock,
) -> None:
    user = account(Role.REVIEWER)
    assert _authorize(_asked(user), administrator) == AUTHORIZED
    # The account loses the role, enrols by itself as a Reader does, and is
    # given the role back: its device is active and nobody approved it.
    _change_role(user, Role.REVIEWER, RoleEventType.REVOKED)
    _change_role(user, Role.READER, RoleEventType.GRANTED)
    started = services.start_mfa_enrollment(actor=signed_in(user), password=PASSWORD, source=SOURCE)
    assert started.provisioning is not None
    secret = base64.b32decode(started.provisioning.secret)
    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED
    _change_role(user, Role.REVIEWER, RoleEventType.GRANTED)

    assert TotpDevice.objects.get(user=user).approved_at is None
    assert _completions() == []
    assert selectors.open_recovery_authorizer_id(user.pk) == administrator.user.pk

    # It replaces that device. The new one is approved, and its first code is
    # the first of a trusted device since the recovery was authorised.
    clock(STEP * 4)
    replaced = services.replace_mfa_device(
        actor=signed_in(user), password=PASSWORD, code=code_at(secret=secret), source=SOURCE
    )
    assert replaced.provisioning is not None
    number = selectors.enrollment_request_number_of(user)
    assert number is not None
    with pytest.raises(PermissionDenied):
        _approve(number, administrator)
    assert _approve(number, another).outcome == MfaOutcome.ACCEPTED
    assert _confirm(user, base64.b32decode(replaced.provisioning.secret)).outcome == (
        MfaOutcome.ACCEPTED
    )

    assert len(_completions(user)) == 1
    assert selectors.open_recovery_authorizer_id(user.pk) is None


# --- Once for a recovery ----------------------------------------------------------------


def test_a_confirmation_sent_again_records_no_second_completion(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    clock: Clock,
) -> None:
    user = account(Role.REVIEWER)
    secret = _approved_after_recovery(user, administrator, another)
    code = code_at(secret=secret)
    first = services.confirm_mfa_enrollment(actor=signed_in(user), code=code, source=SOURCE)
    assert first.outcome == MfaOutcome.ACCEPTED
    before = _state()

    again = services.confirm_mfa_enrollment(actor=signed_in(user), code=code, source=SOURCE)
    clock(STEP * 4)
    later = _confirm(user, secret)

    assert again.outcome == later.outcome == MfaOutcome.UNAVAILABLE
    assert _state() == before
    assert len(_completions()) == 1


def test_an_enrolment_after_a_completed_recovery_completes_nothing_more(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    clock: Clock,
) -> None:
    user = account(Role.REVIEWER)
    secret = _approved_after_recovery(user, administrator, another)
    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED

    # Later the account replaces that device on both proofs. This enrolment
    # follows no recovery, and the Administrator who authorised approves it.
    clock(STEP * 4)
    replaced = services.replace_mfa_device(
        actor=signed_in(user), password=PASSWORD, code=code_at(secret=secret), source=SOURCE
    )
    assert replaced.provisioning is not None
    number = selectors.enrollment_request_number_of(user)
    assert number is not None
    assert _approve(number, administrator).outcome == MfaOutcome.ACCEPTED
    assert _confirm(user, base64.b32decode(replaced.provisioning.secret)).outcome == (
        MfaOutcome.ACCEPTED
    )

    assert _events(user).count("mfa_enrollment_succeeded") == 2
    assert len(_completions(user)) == 1


def test_each_recovery_of_an_account_has_its_own_completion(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    clock: Clock,
) -> None:
    user = account(Role.REVIEWER)
    secret = _approved_after_recovery(user, administrator, another)
    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED

    # The new device is lost as well. Its code is never asked for: the owner
    # asks again, and this time the other Administrator authorises.
    clock(MINUTE)
    assert _authorize(_asked(user), another) == AUTHORIZED
    assert len(_completions(user)) == 1
    assert selectors.open_recovery_authorizer_id(user.pk) == another.user.pk
    secret, number = _enrolment_request(user)
    assert _approve(number, administrator).outcome == MfaOutcome.ACCEPTED
    assert selectors.open_recovery_authorizer_id(user.pk) == another.user.pk
    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED

    lifecycle = [
        event_type
        for event_type in _events(user)
        if event_type in ("mfa_recovery_authorized", COMPLETED)
    ]
    assert lifecycle == ["mfa_recovery_authorized", COMPLETED, "mfa_recovery_authorized", COMPLETED]
    assert selectors.open_recovery_authorizer_id(user.pk) is None


def test_a_recovery_that_was_superseded_is_never_completed(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    clock: Clock,
) -> None:
    user = account(Role.REVIEWER)
    assert _authorize(_asked(user), administrator) == AUTHORIZED
    # No trusted device follows: the account enrols without approval while it
    # does not hold the role, gets the role back, and loses that device too.
    _change_role(user, Role.REVIEWER, RoleEventType.REVOKED)
    _change_role(user, Role.READER, RoleEventType.GRANTED)
    started = services.start_mfa_enrollment(actor=signed_in(user), password=PASSWORD, source=SOURCE)
    assert started.provisioning is not None
    assert _confirm(user, base64.b32decode(started.provisioning.secret)).outcome == (
        MfaOutcome.ACCEPTED
    )
    _change_role(user, Role.REVIEWER, RoleEventType.GRANTED)
    clock(MINUTE)
    assert _authorize(_asked(user), another) == AUTHORIZED
    secret, number = _enrolment_request(user)
    assert _approve(number, administrator).outcome == MfaOutcome.ACCEPTED

    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED

    lifecycle = [
        event_type
        for event_type in _events(user)
        if event_type in ("mfa_recovery_authorized", COMPLETED)
    ]
    # Two authorisations and one completion, which belongs to the later one.
    assert lifecycle == ["mfa_recovery_authorized", "mfa_recovery_authorized", COMPLETED]


def test_completing_one_recovery_leaves_another_accounts_recovery_open(
    account: AccountFactory, administrator: AuthenticationContext, another: AuthenticationContext
) -> None:
    first, second = account(Role.REVIEWER), account(Role.REVIEWER)
    secret = _approved_after_recovery(first, administrator, another)
    _approved_after_recovery(second, administrator, another)

    assert _confirm(first, secret).outcome == MfaOutcome.ACCEPTED

    assert [event.user for event in _completions()] == [first]
    assert selectors.open_recovery_authorizer_id(first.pk) is None
    assert selectors.open_recovery_authorizer_id(second.pk) == administrator.user.pk
    assert selectors.mfa_state_of(second) == MfaState.PENDING_VERIFICATION


# --- What an open recovery is (point 37) ------------------------------------------------


def test_a_recovery_stays_open_through_every_step_before_the_first_code(
    account: AccountFactory, administrator: AuthenticationContext, another: AuthenticationContext
) -> None:
    user = account(Role.REVIEWER)
    authoriser = administrator.user.pk
    assert selectors.open_recovery_authorizer_id(user.pk) is None

    number = _asked(user)
    assert selectors.open_recovery_authorizer_id(user.pk) is None

    assert _authorize(number, administrator) == AUTHORIZED
    assert selectors.open_recovery_authorizer_id(user.pk) == authoriser

    secret, number = _enrolment_request(user)
    assert selectors.open_recovery_authorizer_id(user.pk) == authoriser

    assert _approve(number, another).outcome == MfaOutcome.ACCEPTED
    assert selectors.open_recovery_authorizer_id(user.pk) == authoriser

    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED
    assert selectors.open_recovery_authorizer_id(user.pk) is None


def test_only_the_completion_event_closes_a_recovery(user_with_roles: UserFactory) -> None:
    # The events of an approved and confirmed enrolment, written directly and
    # without the completion: nothing is inferred from them.
    user, authoriser, approver = (user_with_roles() for _ in range(3))
    _event("mfa_recovery_authorized", user, actor=authoriser)
    _event("mfa_enrollment_started", user)
    _event("mfa_enrollment_approved", user, actor=approver)
    _event("mfa_enrollment_succeeded", user)
    assert selectors.open_recovery_authorizer_id(user.pk) == authoriser.pk

    _event(COMPLETED, user)

    assert selectors.open_recovery_authorizer_id(user.pk) is None


def test_a_completion_closes_only_a_recovery_authorised_before_it(
    user_with_roles: UserFactory,
) -> None:
    user, first, second = (user_with_roles() for _ in range(3))
    _event("mfa_recovery_authorized", user, actor=first)
    _event(COMPLETED, user)
    assert selectors.open_recovery_authorizer_id(user.pk) is None

    # The latest authorisation decides, and the earlier completion is not its.
    _event("mfa_recovery_authorized", user, actor=second)

    assert selectors.open_recovery_authorizer_id(user.pk) == second.pk


def test_the_latest_authorisation_is_the_one_recorded_last_even_if_its_time_is_earlier(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two hosts whose clocks disagree: the one that recorded the second
    # authorisation is an hour behind the one that recorded the first. Which
    # is the most recent is read from the order of the events.
    user, first, second = (user_with_roles() for _ in range(3))
    recorded_at = timezone.now()
    monkeypatch.setattr(timezone, "now", lambda: recorded_at)
    earlier = _event("mfa_recovery_authorized", user, actor=first)
    monkeypatch.setattr(timezone, "now", lambda: recorded_at - HOUR)
    later = _event("mfa_recovery_authorized", user, actor=second)
    assert earlier.pk < later.pk
    assert earlier.created_at > later.created_at

    assert selectors.open_recovery_authorizer_id(user.pk) == second.pk

    # A completion on the slow clock as well: it is before the first
    # authorisation by its time and after both by its identifier.
    completed = _event(COMPLETED, user)
    assert completed.created_at < earlier.created_at

    assert selectors.open_recovery_authorizer_id(user.pk) is None


def test_a_completion_recorded_between_two_authorisations_closes_only_the_first(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The same two clocks. By the times alone the completion would follow the
    # second authorisation; by the events it is before it.
    user, first, second = (user_with_roles() for _ in range(3))
    recorded_at = timezone.now()
    monkeypatch.setattr(timezone, "now", lambda: recorded_at)
    _event("mfa_recovery_authorized", user, actor=first)
    completed = _event(COMPLETED, user)
    monkeypatch.setattr(timezone, "now", lambda: recorded_at - HOUR)
    later = _event("mfa_recovery_authorized", user, actor=second)
    assert completed.pk < later.pk
    assert completed.created_at > later.created_at

    assert selectors.open_recovery_authorizer_id(user.pk) == second.pk


def test_a_completion_of_another_account_closes_nothing(user_with_roles: UserFactory) -> None:
    user, other, authoriser = (user_with_roles() for _ in range(3))
    _event("mfa_recovery_authorized", user, actor=authoriser)
    _event("mfa_recovery_authorized", other, actor=authoriser)

    _event(COMPLETED, other)

    assert selectors.open_recovery_authorizer_id(user.pk) == authoriser.pk
    assert selectors.open_recovery_authorizer_id(other.pk) is None


def test_an_enrolment_of_another_account_closes_nothing(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    user_with_roles: UserFactory,
) -> None:
    recovered = account(Role.REVIEWER)
    assert _authorize(_asked(recovered), administrator) == AUTHORIZED
    bystander = _without_a_device(user_with_roles, Role.REVIEWER)
    secret, number = _enrolment_request(bystander)
    assert _approve(number, another).outcome == MfaOutcome.ACCEPTED

    assert _confirm(bystander, secret).outcome == MfaOutcome.ACCEPTED

    assert _completions() == []
    assert selectors.open_recovery_authorizer_id(recovered.pk) == administrator.user.pk


def test_the_authoriser_is_refused_until_the_completion_is_recorded_and_not_after(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    clock: Clock,
) -> None:
    user = account(Role.REVIEWER)
    assert _authorize(_asked(user), administrator) == AUTHORIZED
    # Asked for twice: each request is refused to the Administrator who
    # authorised, whatever was approved before it.
    for _ in range(2):
        secret, number = _enrolment_request(user)
        with pytest.raises(PermissionDenied):
            _approve(number, administrator)
        assert _approve(number, another).outcome == MfaOutcome.ACCEPTED
    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED
    assert len(_completions(user)) == 1

    clock(STEP * 4)
    replaced = services.replace_mfa_device(
        actor=signed_in(user), password=PASSWORD, code=code_at(secret=secret), source=SOURCE
    )
    assert replaced.outcome == MfaOutcome.ACCEPTED
    following = selectors.enrollment_request_number_of(user)
    assert following is not None

    assert _approve(following, administrator).outcome == MfaOutcome.ACCEPTED


# --- A fault leaves nothing half done ---------------------------------------------------


def test_a_completion_that_cannot_be_recorded_leaves_the_enrolment_unconfirmed(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = account(Role.REVIEWER)
    secret = _approved_after_recovery(user, administrator, another)
    before = _state()
    record = services._record

    def fail(event_type: AuthenticationEventType, *args: Any, **kwargs: Any) -> None:
        if event_type == AuthenticationEventType.MFA_RECOVERY_COMPLETED:
            raise RuntimeError("TEST fault in recording the completion")
        record(event_type, *args, **kwargs)

    with monkeypatch.context() as patched:
        patched.setattr(services, "_record", fail)
        with pytest.raises(RuntimeError, match="TEST fault"):
            _confirm(user, secret)

    # The device is not active and `mfa_enrollment_succeeded` is not kept.
    assert _state() == before
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION
    # The same code is then accepted, and the recovery is completed once.
    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED
    assert len(_completions(user)) == 1


def test_a_fault_while_deciding_on_the_completion_leaves_the_enrolment_unconfirmed(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = account(Role.REVIEWER)
    secret = _approved_after_recovery(user, administrator, another)
    before = _state()

    def fail(user_id: int) -> int | None:
        raise RuntimeError("TEST fault before the completion is recorded")

    with monkeypatch.context() as patched:
        patched.setattr(selectors, "open_recovery_authorizer_id", fail)
        with pytest.raises(RuntimeError, match="TEST fault"):
            _confirm(user, secret)

    assert _state() == before
    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED
    assert len(_completions(user)) == 1


# --- What is kept, and what is not (point 88) -------------------------------------------


def test_the_completion_and_its_log_line_hold_no_address_password_or_secret(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    user = account(Role.REVIEWER)
    assert _authorize(_asked(user), administrator) == AUTHORIZED
    started = services.start_mfa_enrollment(actor=signed_in(user), password=PASSWORD, source=SOURCE)
    assert started.provisioning is not None
    number = selectors.enrollment_request_number_of(user)
    assert number is not None
    assert _approve(number, another).outcome == MfaOutcome.ACCEPTED
    secret = base64.b32decode(started.provisioning.secret)
    code = code_at(secret=secret)
    caplog.clear()

    confirmed = services.confirm_mfa_enrollment(actor=signed_in(user), code=code, source=SOURCE)

    assert confirmed.outcome == MfaOutcome.ACCEPTED
    forbidden = [
        user.email,
        administrator.user.email,
        another.user.email,
        SOURCE,
        ADMINISTRATOR_SOURCE,
        PASSWORD,
        started.provisioning.secret,
        started.provisioning.uri,
    ]
    events = repr(list(AuthenticationEvent.objects.filter(event_type=COMPLETED).values()))
    written = logged(caplog.records)
    for value in forbidden:
        assert value not in events, value
        assert value not in written, value
    # The code is six digits, which occur by chance in a keyed hash; it is
    # looked for in the log line of the completion, which holds no hash.
    (line,) = (
        record
        for record in caplog.records
        if record.__dict__.get("event") == "mfa_recovery.completed"
    )
    assert code not in logged([line])
    assert line.__dict__["user_id"] == user.pk
    assert "actor_id" not in line.__dict__
