"""Authorising and rejecting a recovery request (ADR-0017, points 34 to 53).

An Administrator who is signed in with a trusted second factor decides on
another account's request. No HTTP is involved, and nothing stands in for
TOTP or for the authorization decision: requests are made, passwords reset,
and enrolments approved by the services themselves.
"""

import base64
import dataclasses
import inspect
import logging
import re
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.conf import LazySettings
from django.core import mail as django_mail
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from caipo.accounts import selectors, services
from caipo.accounts.models import (
    AccountStatus,
    AuthenticationEvent,
    MfaChallenge,
    MfaRecoveryRequest,
    PasswordReset,
    RoleEvent,
    RoleEventType,
    TotpDevice,
    TotpDeviceState,
    User,
)
from caipo.accounts.selectors import (
    Assurance,
    AuthenticationContext,
    MfaState,
    Permission,
    Role,
)
from caipo.accounts.services import (
    MfaOutcome,
    PasswordResetOutcome,
    RecoveryDecisionOutcome,
    RecoveryDecisionResult,
    RecoveryRefusalReason,
    RecoveryRequestOutcome,
    SignInOutcome,
)
from caipo.accounts.tests.fixtures import (
    Clock,
    UserFactory,
    code_at,
    enrolled_device,
    logged,
    signed_in,
    supporting_account,
    verified,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db]

type AccountFactory = Callable[..., User]

# Visibly synthetic fixture values.
PASSWORD = "TEST-passphrase-for-fixtures-only"
NEW_PASSWORD = "TEST-passphrase-chosen-afterwards"
SOURCE = "203.0.113.10"
ADMINISTRATOR_SOURCE = "198.51.100.66"

AUTHORIZED = RecoveryDecisionResult(RecoveryDecisionOutcome.AUTHORIZED)
REJECTED = RecoveryDecisionResult(RecoveryDecisionOutcome.REJECTED)
UNAVAILABLE = RecoveryDecisionResult(RecoveryDecisionOutcome.UNAVAILABLE)

DECISION_EVENTS = ["mfa_recovery_authorized", "mfa_recovery_rejected"]
STEP = timedelta(seconds=30)
MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)


@pytest.fixture
def account(user_with_roles: UserFactory) -> AccountFactory:
    """Return a factory for synthetic users with a known password and an active second factor."""

    def make(*roles: Role, trusted: bool = True) -> User:
        user = user_with_roles(*roles)
        user.set_password(PASSWORD)
        user.save()
        enrolled_device(user, trusted=trusted)
        return user

    return make


@pytest.fixture
def administrator(account: AccountFactory) -> AuthenticationContext:
    """Return the verified context of the Administrator who decides."""
    return verified(account(Role.ADMINISTRATOR))


@pytest.fixture
def another(account: AccountFactory) -> AuthenticationContext:
    """Return the verified context of a further Administrator, who is able to act."""
    return verified(account(Role.ADMINISTRATOR))


def _challenge(user: User, password: str = PASSWORD) -> str:
    result = services.sign_in(email=user.email, password=password, source=SOURCE)
    assert result.outcome == SignInOutcome.SECOND_FACTOR_REQUIRED
    assert result.challenge is not None
    return result.challenge


def _asked(user: User, password: str = PASSWORD) -> int:
    """Make a recovery request for the account, as its owner would, and return its number."""
    result = services.request_mfa_recovery(challenge=_challenge(user, password), source=SOURCE)
    assert result.outcome == RecoveryRequestOutcome.REQUESTED
    assert result.number is not None
    return result.number


def _authorize(number: int, actor: AuthenticationContext) -> RecoveryDecisionResult:
    return services.authorize_mfa_recovery(
        actor=actor, request_number=number, source=ADMINISTRATOR_SOURCE
    )


def _reject(number: int, actor: AuthenticationContext) -> RecoveryDecisionResult:
    return services.reject_mfa_recovery(
        actor=actor, request_number=number, source=ADMINISTRATOR_SOURCE
    )


DECISIONS = [_authorize, _reject]


def _reset_password(user: User, password: str = NEW_PASSWORD) -> None:
    """Reset the account's password as its owner would, with the token from the message."""
    services.request_password_reset(
        email=user.email,
        source=SOURCE,
        reset_url=lambda token: f"https://caipo.test/password-reset/confirm/#{token}",
    )
    token = re.findall(r"#(\S+)", str(django_mail.outbox[-1].body))[-1]
    result = services.reset_password(token=token, password=password, source=SOURCE)
    assert result.outcome == PasswordResetOutcome.RESET


def _reset_token(user: User) -> str:
    services.request_password_reset(
        email=user.email,
        source=SOURCE,
        reset_url=lambda token: f"https://caipo.test/password-reset/confirm/#{token}",
    )
    return str(re.findall(r"#(\S+)", str(django_mail.outbox[-1].body))[-1])


def _change_role(user: User, role: Role, event_type: RoleEventType) -> None:
    RoleEvent.objects.create(
        user=user,
        role=role,
        event_type=event_type,
        actor=supporting_account("test.seed@caipo.test"),
        reason="TEST fixture",
    )


def _events(user: User | None = None) -> list[str]:
    events = AuthenticationEvent.objects.order_by("id")
    if user is not None:
        events = events.filter(user=user)
    return list(events.values_list("event_type", flat=True))


def _decisions() -> list[tuple[str, int | None, int | None]]:
    return list(
        AuthenticationEvent.objects.filter(event_type__in=DECISION_EVENTS)
        .order_by("id")
        .values_list("event_type", "user_id", "actor_id")
    )


def _state() -> dict[str, Any]:
    """Return everything a decision that is not made must leave as it is."""
    return {
        "events": list(AuthenticationEvent.objects.order_by("id").values()),
        "requests": list(MfaRecoveryRequest.objects.order_by("id").values()),
        "challenges": list(MfaChallenge.objects.order_by("id").values()),
        "resets": list(PasswordReset.objects.order_by("id").values()),
        "devices": list(TotpDevice.objects.order_by("id").values()),
        "users": list(User.objects.order_by("id").values()),
        "roles": list(RoleEvent.objects.order_by("id").values()),
    }


def _reasons(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.__dict__["reason"]
        for record in caplog.records
        if record.__dict__.get("event") == "mfa_recovery.decision_unavailable"
    ]


def _enrolment_request(user: User, password: str = PASSWORD) -> tuple[bytes, int]:
    """Start an enrolment for an account that needs approval; return its secret and number."""
    result = services.start_mfa_enrollment(actor=signed_in(user), password=password, source=SOURCE)
    assert result.outcome == MfaOutcome.ACCEPTED
    assert result.provisioning is not None
    number = selectors.enrollment_request_number_of(user)
    assert number is not None
    return base64.b32decode(result.provisioning.secret), number


def _approve(number: int, actor: AuthenticationContext) -> services.MfaResult:
    return services.approve_mfa_enrollment(
        actor=actor, request_number=number, source=ADMINISTRATOR_SOURCE
    )


def _confirm(user: User, secret: bytes) -> services.MfaResult:
    return services.confirm_mfa_enrollment(
        actor=signed_in(user), code=code_at(secret=secret), source=SOURCE
    )


# --- An authorisation finalises the recovery (point 45) --------------------------------


def test_authorising_revokes_the_device_and_finalises_in_one_step(
    account: AccountFactory, administrator: AuthenticationContext, another: AuthenticationContext
) -> None:
    user = account(Role.REVIEWER)
    reset_token = _reset_token(user)
    number = _asked(user)
    challenge = _challenge(user)
    assert PasswordReset.objects.filter(user=user).exists()

    assert _authorize(number, administrator) == AUTHORIZED

    assert not TotpDevice.objects.filter(user=user).exists()
    assert User.objects.get(pk=user.pk).session_epoch == 1
    assert not MfaChallenge.objects.filter(user=user).exists()
    assert not PasswordReset.objects.filter(user=user).exists()
    assert not MfaRecoveryRequest.objects.filter(user=user).exists()
    assert _decisions() == [("mfa_recovery_authorized", user.pk, administrator.user.pk)]
    # What existed before the recovery is refused after it.
    refused = services.verify_second_factor(challenge=challenge, code=code_at(), source=SOURCE)
    assert refused.outcome == MfaOutcome.REFUSED
    reset = services.reset_password(token=reset_token, password=NEW_PASSWORD, source=SOURCE)
    assert reset.outcome == PasswordResetOutcome.REFUSED
    assert _authorize(number, administrator) == UNAVAILABLE


def test_the_authorisation_is_recorded_naming_the_account_and_the_administrator(
    account: AccountFactory, administrator: AuthenticationContext, another: AuthenticationContext
) -> None:
    user = account(Role.REVIEWER)

    _authorize(_asked(user), administrator)

    event = AuthenticationEvent.objects.get(event_type="mfa_recovery_authorized")
    assert event.user == user
    assert event.actor == administrator.user
    assert event.identifier_key == services._key("identifier", user.email)
    assert event.source_key == services._key("source", ADMINISTRATOR_SOURCE)
    assert event.break_glass_action == ""


def test_authorising_changes_nothing_else_about_the_account(
    account: AccountFactory, administrator: AuthenticationContext, another: AuthenticationContext
) -> None:
    user = account(Role.REVIEWER, Role.READER)
    number = _asked(user)
    before: dict[str, Any] = dict(User.objects.filter(pk=user.pk).values().get())
    roles = selectors.roles_of(user)
    events = _events(user)

    assert _authorize(number, administrator) == AUTHORIZED

    after: dict[str, Any] = dict(User.objects.filter(pk=user.pk).values().get())
    assert {name for name in before if before[name] != after[name]} <= {
        "session_epoch",
        "updated_at",
    }
    assert after["password"] == before["password"]
    assert after["status"] == AccountStatus.ACTIVE
    assert selectors.roles_of(user) == roles
    # One event more, and nothing that counts as a sign-in or a refused code.
    assert _events(user) == [*events, "mfa_recovery_authorized"]


def test_the_epoch_goes_up_by_one_from_wherever_it_stood(
    account: AccountFactory, administrator: AuthenticationContext, another: AuthenticationContext
) -> None:
    user = account(Role.REVIEWER)
    User.objects.filter(pk=user.pk).update(session_epoch=41)
    bystander = account(Role.REVIEWER)

    assert _authorize(_asked(user), administrator) == AUTHORIZED

    assert User.objects.get(pk=user.pk).session_epoch == 42
    assert User.objects.get(pk=bystander.pk).session_epoch == 0
    assert User.objects.get(pk=administrator.user.pk).session_epoch == 0


def test_the_epoch_is_raised_in_the_database_and_not_from_a_value_read_earlier() -> None:
    source = inspect.getsource(services.authorize_mfa_recovery)

    assert 'session_epoch=F("session_epoch") + 1' in source


def test_authorising_signs_nobody_in_and_returns_no_context(
    account: AccountFactory, administrator: AuthenticationContext, another: AuthenticationContext
) -> None:
    user = account(Role.ADMINISTRATOR)
    logins = _events().count("login_success")

    result = _authorize(_asked(user), administrator)

    assert [field.name for field in dataclasses.fields(result)] == ["outcome"]
    assert _events().count("login_success") == logins
    assert not TotpDevice.objects.filter(user=user).exists()
    for decide in (services.authorize_mfa_recovery, services.reject_mfa_recovery):
        assert list(inspect.signature(decide).parameters) == ["actor", "request_number", "source"]


def test_a_recovered_account_holds_nothing_on_its_password_but_its_own_second_factor(
    account: AccountFactory, administrator: AuthenticationContext, another: AuthenticationContext
) -> None:
    user = account(Role.ADMINISTRATOR)
    lost_device = TotpDevice.objects.get(user=user).pk

    _authorize(_asked(user), administrator)

    result = services.sign_in(email=user.email, password=PASSWORD, source=SOURCE)
    assert result.outcome == SignInOutcome.SIGNED_IN
    assert selectors.mfa_state_of(user) == MfaState.NOT_ENROLLED
    assert selectors.permissions_of(signed_in(user)) == {Permission.MFA_MANAGE_OWN}
    # A context that still claims the lost device is worth no more.
    stale = AuthenticationContext(user, Assurance.MFA_VERIFIED, lost_device)
    assert selectors.permissions_of(stale) == {Permission.MFA_MANAGE_OWN}


def test_authorising_touches_no_other_account(
    account: AccountFactory, administrator: AuthenticationContext, another: AuthenticationContext
) -> None:
    user = account(Role.REVIEWER)
    bystander = account(Role.REVIEWER)
    _reset_token(bystander)
    bystander_number = _asked(bystander)
    bystander_challenge = _challenge(bystander)
    number = _asked(user)

    def of_bystander() -> dict[str, Any]:
        state = _state()
        return {
            "requests": [row for row in state["requests"] if row["user_id"] == bystander.pk],
            "challenges": [row for row in state["challenges"] if row["user_id"] == bystander.pk],
            "resets": [row for row in state["resets"] if row["user_id"] == bystander.pk],
            "devices": [row for row in state["devices"] if row["user_id"] != user.pk],
            "users": [row for row in state["users"] if row["id"] != user.pk],
        }

    before = of_bystander()

    assert _authorize(number, administrator) == AUTHORIZED

    assert of_bystander() == before
    assert MfaRecoveryRequest.objects.get().pk == bystander_number
    verified_bystander = services.verify_second_factor(
        challenge=bystander_challenge, code=code_at(), source=SOURCE
    )
    assert verified_bystander.outcome == MfaOutcome.ACCEPTED


def test_an_authorisation_that_fails_part_way_changes_nothing(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = account(Role.REVIEWER)
    _reset_token(user)
    number = _asked(user)
    _challenge(user)
    before = _state()

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("TEST fault after every other step of the finalisation")

    with monkeypatch.context() as patched:
        patched.setattr(services, "_record", fail)
        with pytest.raises(RuntimeError, match="TEST fault"):
            _authorize(number, administrator)

    assert _state() == before
    # The same request can still be authorised.
    assert _authorize(number, administrator) == AUTHORIZED


@pytest.mark.parametrize("step", [TotpDevice, MfaChallenge, PasswordReset, MfaRecoveryRequest])
def test_a_fault_at_any_step_of_the_finalisation_rolls_back_the_steps_before_it(
    step: type[Any],
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = account(Role.REVIEWER)
    _reset_token(user)
    number = _asked(user)
    _challenge(user)
    before = _state()
    queryset = type(step.objects.all())
    delete = queryset.delete

    def fail(self: Any) -> Any:
        if self.model is step and "WHERE" in str(self.query):
            raise RuntimeError("TEST fault in one step of the finalisation")
        return delete(self)

    with monkeypatch.context() as patched:
        patched.setattr(queryset, "delete", fail)
        with pytest.raises(RuntimeError, match="TEST fault"):
            _authorize(number, administrator)

    assert _state() == before


# --- Who may decide (points 34, 35, and 42) --------------------------------------------


@pytest.mark.parametrize("decide", DECISIONS)
@pytest.mark.parametrize("role", [Role.READER, Role.RESEARCHER, Role.REVIEWER])
def test_no_other_role_decides_whatever_its_assurance(
    decide: Callable[..., RecoveryDecisionResult],
    role: Role,
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
) -> None:
    user = account(Role.REVIEWER)
    number = _asked(user)
    actor = verified(account(role))
    before = _state()

    with pytest.raises(PermissionDenied):
        decide(number, actor)

    assert _state() == before


@pytest.mark.parametrize("decide", DECISIONS)
def test_an_administrator_on_a_password_alone_decides_nothing(
    decide: Callable[..., RecoveryDecisionResult],
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
) -> None:
    number = _asked(account(Role.REVIEWER))
    before = _state()

    with pytest.raises(PermissionDenied):
        decide(number, signed_in(administrator.user))

    assert _state() == before


@pytest.mark.parametrize("decide", DECISIONS)
def test_an_administrator_whose_device_nobody_approved_decides_nothing(
    decide: Callable[..., RecoveryDecisionResult],
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
) -> None:
    number = _asked(account(Role.REVIEWER))
    untrusted = account(Role.ADMINISTRATOR, trusted=False)
    claim = AuthenticationContext(
        untrusted, Assurance.MFA_VERIFIED, TotpDevice.objects.get(user=untrusted).pk
    )
    before = _state()

    with pytest.raises(PermissionDenied):
        decide(number, claim)

    assert _state() == before


@pytest.mark.parametrize("decide", DECISIONS)
def test_a_context_that_claims_somebody_elses_device_decides_nothing(
    decide: Callable[..., RecoveryDecisionResult],
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
) -> None:
    number = _asked(account(Role.REVIEWER))
    claim = AuthenticationContext(administrator.user, Assurance.MFA_VERIFIED, another.mfa_device_id)

    with pytest.raises(PermissionDenied):
        decide(number, claim)

    assert MfaRecoveryRequest.objects.filter(pk=number).exists()


@pytest.mark.parametrize("decide", DECISIONS)
def test_a_disabled_administrator_decides_nothing(
    decide: Callable[..., RecoveryDecisionResult],
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
) -> None:
    number = _asked(account(Role.REVIEWER))
    services.disable_user(actor=another, user=administrator.user)

    with pytest.raises(PermissionDenied):
        decide(number, administrator)

    assert MfaRecoveryRequest.objects.filter(pk=number).exists()


@pytest.mark.parametrize("decide", DECISIONS)
def test_a_caller_without_the_permission_takes_no_lock_and_learns_nothing(
    decide: Callable[..., RecoveryDecisionResult],
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
) -> None:
    existing = _asked(account(Role.REVIEWER))
    reviewer = verified(account(Role.REVIEWER))

    for number in (existing, existing + 1000):
        with CaptureQueriesContext(connection) as queries, pytest.raises(PermissionDenied):
            decide(number, reviewer)

        touched = " ".join(query["sql"] for query in queries.captured_queries)
        assert "LOCK TABLE" not in touched
        assert "pg_advisory_xact_lock" not in touched
        assert "accounts_mfarecoveryrequest" not in touched


@pytest.mark.parametrize("decide", DECISIONS)
def test_nobody_decides_on_their_own_request(
    decide: Callable[..., RecoveryDecisionResult],
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The device is not lost: the Administrator is still signed in with it
    # elsewhere, and asked for recovery from a second sign-in.
    account(Role.ADMINISTRATOR)
    number = _asked(administrator.user)
    before = _state()

    with pytest.raises(PermissionDenied):
        decide(number, administrator)

    assert _state() == before
    assert "mfa_recovery.own_decision_refused" in [
        record.__dict__.get("event") for record in caplog.records
    ]


# --- The permission is decided twice, and the second time under the locks ---------------


def _lock_steps(statements: list[str]) -> list[str]:
    """Return, in order, the locks a decision took and where it decided the permission."""
    steps = []
    for statement in statements:
        advisory = re.search(r"pg_advisory_xact_lock\((\d+), (\d+)\)", statement)
        if "LOCK TABLE accounts_roleevent" in statement:
            steps.append("role events")
        elif advisory:
            steps.append(f"advisory {advisory.group(1)}:{advisory.group(2)}")
        elif "FOR UPDATE" in statement and '"accounts_user"' in statement.split("WHERE")[0]:
            steps.append("account row")
        elif "FOR UPDATE" in statement:
            steps.append("request row")
        elif '"accounts_totpdevice"' in statement and '"approved_at" IS NOT NULL' in statement:
            # The half of the decision that reads the device the context names.
            steps.append("permission")
    return steps


@pytest.mark.parametrize("decide", DECISIONS)
@pytest.mark.parametrize("actor_first", [True, False])
def test_the_locks_are_taken_in_one_order_with_the_permission_decided_under_them(
    decide: Callable[..., RecoveryDecisionResult],
    actor_first: bool,
    account: AccountFactory,
) -> None:
    # The actor's identifier is below the account's in one case and above it
    # in the other. The order of the two second-factor locks follows the
    # identifiers, not the roles the two play.
    first, second = account(Role.ADMINISTRATOR), account(Role.ADMINISTRATOR)
    verified(account(Role.ADMINISTRATOR))
    actor, user = (first, second) if actor_first else (second, first)
    assert (actor.pk < user.pk) is actor_first
    number = _asked(user)
    identifier = int(services._key("identifier", user.email)[:8], 16) >> 1

    with CaptureQueriesContext(connection) as queries:
        decide(number, verified(actor))

    steps = _lock_steps([query["sql"] for query in queries.captured_queries])
    assert steps[:8] == [
        "permission",
        "role events",
        f"advisory 2:{identifier}",
        f"advisory 3:{min(actor.pk, user.pk)}",
        f"advisory 3:{max(actor.pk, user.pk)}",
        "permission",
        "account row",
        "request row",
    ]
    assert steps.count("role events") == 1
    assert sum(step.startswith("advisory") for step in steps) == 3


@pytest.mark.parametrize("decide", DECISIONS)
@pytest.mark.parametrize("lost", ["device", "role", "status"])
def test_an_actor_who_stops_being_verified_before_the_locks_are_held_is_refused_under_them(
    decide: Callable[..., RecoveryDecisionResult],
    lost: str,
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = account(Role.REVIEWER)
    number = _asked(user)
    lock = services._lock_second_factors

    def lose_it_then_lock(*user_ids: int) -> None:
        # What a change that committed between the first check and the locks
        # would have left. The first check has passed by now.
        if lost == "device":
            TotpDevice.objects.filter(user=administrator.user).delete()
        elif lost == "role":
            _change_role(administrator.user, Role.ADMINISTRATOR, RoleEventType.REVOKED)
        else:
            User.objects.filter(pk=administrator.user.pk).update(status=AccountStatus.DISABLED)
        lock(*user_ids)

    monkeypatch.setattr(services, "_lock_second_factors", lose_it_then_lock)

    with pytest.raises(PermissionDenied):
        decide(number, administrator)

    assert TotpDevice.objects.filter(user=user, state=TotpDeviceState.ACTIVE).exists()
    assert MfaRecoveryRequest.objects.filter(pk=number).exists()
    assert User.objects.get(pk=user.pk).session_epoch == 0
    assert _decisions() == []


# --- When an authorisation is not available (point 38) ---------------------------------


def test_a_number_that_names_no_request_is_unavailable(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    number = _asked(account(Role.REVIEWER))
    before = _state()

    assert _authorize(number + 1000, administrator) == UNAVAILABLE

    assert _state() == before
    assert _reasons(caplog) == ["unknown_request"]


def test_a_request_lapses_after_thirty_minutes_exactly(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    clock: Clock,
    settings: LazySettings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert timedelta(minutes=30) == settings.MFA_RECOVERY_REQUEST_LIFETIME
    late, in_time = account(Role.REVIEWER), account(Role.REVIEWER)
    late_number, in_time_number = _asked(late), _asked(in_time)

    clock(timedelta(minutes=30) - timedelta(seconds=1))
    assert _authorize(in_time_number, administrator) == AUTHORIZED
    clock(timedelta(seconds=1))
    before = _state()
    assert _authorize(late_number, administrator) == UNAVAILABLE

    assert _state() == before
    assert _reasons(caplog) == ["lapsed"]
    assert TotpDevice.objects.filter(user=late).exists()


def test_a_request_that_was_replaced_is_unavailable_and_the_new_one_is_not(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user = account(Role.REVIEWER)
    earlier = _asked(user)
    current = _asked(user)

    assert _authorize(earlier, administrator) == UNAVAILABLE
    assert _reasons(caplog) == ["unknown_request"]
    assert TotpDevice.objects.filter(user=user).exists()
    assert _authorize(current, administrator) == AUTHORIZED


def test_a_request_made_before_a_password_reset_is_invalid_whatever_its_age(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    clock: Clock,
    settings: LazySettings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Long enough that only the reset stands between the request and its
    # authorisation: neither the lapse nor the cooling-off does.
    settings.MFA_RECOVERY_REQUEST_LIFETIME = timedelta(days=30)
    user = account(Role.REVIEWER)
    number = _asked(user)
    clock(MINUTE)
    _reset_password(user)

    for wait in (MINUTE, settings.MFA_RECOVERY_COOLING_OFF, timedelta(days=7)):
        clock(wait)
        before = _state()
        assert _authorize(number, administrator) == UNAVAILABLE
        assert _state() == before

    assert _reasons(caplog) == ["request_precedes_reset"] * 3
    assert TotpDevice.objects.filter(user=user).exists()


def _event_id(user: User, event_type: str) -> int:
    return int(AuthenticationEvent.objects.filter(user=user, event_type=event_type).latest("id").pk)


def test_a_request_recorded_after_a_reset_is_in_order_even_if_its_time_is_earlier(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    monkeypatch: pytest.MonkeyPatch,
    settings: LazySettings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Two hosts whose clocks disagree: the one that took the request is an
    # hour behind the one that took the reset. What was recorded first is
    # read from the order of the events, which no clock decides.
    settings.MFA_RECOVERY_REQUEST_LIFETIME = timedelta(days=30)
    reset_at = timezone.now()
    user = account(Role.REVIEWER)
    monkeypatch.setattr(timezone, "now", lambda: reset_at)
    _reset_password(user)
    monkeypatch.setattr(timezone, "now", lambda: reset_at - HOUR)
    number = _asked(user, NEW_PASSWORD)
    request = MfaRecoveryRequest.objects.get(pk=number)
    reset = AuthenticationEvent.objects.get(user=user, event_type="password_reset_succeeded")
    assert request.created_at < reset.created_at
    assert _event_id(user, "mfa_recovery_requested") > reset.pk

    # The cooling-off is counted from the time of the reset, on its clock.
    monkeypatch.setattr(timezone, "now", lambda: reset_at + timedelta(hours=24, seconds=-1))
    assert _authorize(number, administrator) == UNAVAILABLE
    assert _reasons(caplog) == ["cooling_off"]

    monkeypatch.setattr(timezone, "now", lambda: reset_at + timedelta(hours=24))
    assert _authorize(number, administrator) == AUTHORIZED


def test_a_request_recorded_before_a_reset_is_invalid_even_if_its_time_is_later(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    monkeypatch: pytest.MonkeyPatch,
    settings: LazySettings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The other way round: the host that took the reset is an hour behind,
    # so by the times alone the request would seem to follow the reset.
    settings.MFA_RECOVERY_REQUEST_LIFETIME = timedelta(days=30)
    requested_at = timezone.now()
    user = account(Role.REVIEWER)
    monkeypatch.setattr(timezone, "now", lambda: requested_at)
    number = _asked(user)
    monkeypatch.setattr(timezone, "now", lambda: requested_at - HOUR)
    _reset_password(user)
    request = MfaRecoveryRequest.objects.get(pk=number)
    reset = AuthenticationEvent.objects.get(user=user, event_type="password_reset_succeeded")
    assert request.created_at > reset.created_at
    assert _event_id(user, "mfa_recovery_requested") < reset.pk

    # Long after the cooling-off has passed on either clock.
    monkeypatch.setattr(timezone, "now", lambda: requested_at + timedelta(days=2))
    before = _state()
    assert _authorize(number, administrator) == UNAVAILABLE

    assert _state() == before
    assert _reasons(caplog) == ["request_precedes_reset"]
    assert TotpDevice.objects.filter(user=user, state=TotpDeviceState.ACTIVE).exists()


def test_a_request_and_a_reset_at_the_same_instant_are_ordered_by_their_events(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    clock: Clock,
    settings: LazySettings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The clock stands still, so the times tie. Neither order is ambiguous.
    settings.MFA_RECOVERY_REQUEST_LIFETIME = timedelta(days=30)
    reset_first, request_first = account(Role.REVIEWER), account(Role.REVIEWER)
    _reset_password(reset_first)
    after_reset = _asked(reset_first, NEW_PASSWORD)
    before_reset = _asked(request_first)
    _reset_password(request_first)
    for user in (reset_first, request_first):
        reset = AuthenticationEvent.objects.get(user=user, event_type="password_reset_succeeded")
        assert MfaRecoveryRequest.objects.get(user=user).created_at == reset.created_at

    clock(settings.MFA_RECOVERY_COOLING_OFF)

    assert _authorize(before_reset, administrator) == UNAVAILABLE
    assert _reasons(caplog) == ["request_precedes_reset"]
    assert _authorize(after_reset, administrator) == AUTHORIZED


def test_the_order_is_read_from_the_event_of_the_current_request_and_not_an_earlier_one(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    clock: Clock,
    settings: LazySettings,
) -> None:
    # A request before the reset, and another after it, which replaces the
    # first: the one that stands was made on the new password.
    user = account(Role.REVIEWER)
    _asked(user)
    clock(MINUTE)
    _reset_password(user)
    clock(settings.MFA_RECOVERY_COOLING_OFF)
    current = _asked(user, NEW_PASSWORD)

    assert _authorize(current, administrator) == AUTHORIZED


def test_the_order_of_a_request_and_a_reset_is_not_read_from_their_times() -> None:
    source = inspect.getsource(services._recovery_authorization_refusal)

    assert "requested_event_id < reset_event_id" in source
    assert "request.created_at" not in source
    # The one use of a time is the cooling-off, from the time of the reset.
    assert source.count("created_at") == 1
    assert "reset_at + settings.MFA_RECOVERY_COOLING_OFF" in source


def test_no_recovery_is_authorised_within_a_day_of_a_password_reset(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    clock: Clock,
    settings: LazySettings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert timedelta(hours=24) == settings.MFA_RECOVERY_COOLING_OFF
    user = account(Role.REVIEWER)
    _reset_password(user)
    clock(timedelta(hours=24) - 10 * MINUTE)
    number = _asked(user, NEW_PASSWORD)

    clock(10 * MINUTE - timedelta(seconds=1))
    before = _state()
    assert _authorize(number, administrator) == UNAVAILABLE
    assert _state() == before
    assert _reasons(caplog) == ["cooling_off"]

    clock(timedelta(seconds=1))
    assert _authorize(number, administrator) == AUTHORIZED
    # The password is the one the reset set: a recovery sets none.
    assert User.objects.get(pk=user.pk).check_password(NEW_PASSWORD) is True


def test_a_reset_followed_at_once_by_a_request_gains_nothing(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    clock: Clock,
    settings: LazySettings,
) -> None:
    # What a mailbox alone can reach (point 57): a password, and a request
    # that lapses long before the cooling-off has passed.
    user = account(Role.REVIEWER)
    _reset_password(user)
    clock(MINUTE)
    number = _asked(user, NEW_PASSWORD)

    assert _authorize(number, administrator) == UNAVAILABLE
    clock(settings.MFA_RECOVERY_REQUEST_LIFETIME)
    assert _authorize(number, administrator) == UNAVAILABLE
    clock(settings.MFA_RECOVERY_COOLING_OFF)
    assert _authorize(number, administrator) == UNAVAILABLE

    assert TotpDevice.objects.filter(user=user, state=TotpDeviceState.ACTIVE).exists()
    assert User.objects.get(pk=user.pk).session_epoch == 0


def test_only_the_latest_reset_counts_and_only_one_that_succeeded(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    clock: Clock,
) -> None:
    user = account(Role.REVIEWER)
    _reset_password(user)
    clock(timedelta(hours=25))
    # Asked for and never used: no password was replaced.
    _reset_token(user)
    services.reset_password(token="TEST-not-a-token", password=NEW_PASSWORD, source=SOURCE)
    clock(MINUTE)
    number = _asked(user, NEW_PASSWORD)

    assert _authorize(number, administrator) == AUTHORIZED


@pytest.mark.parametrize("change", ["disabled", "role_revoked", "role_replaced", "device_given_up"])
def test_an_account_that_is_no_longer_eligible_is_not_recovered(
    change: str,
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user = account(Role.REVIEWER)
    number = _asked(user)
    if change == "disabled":
        services.disable_user(actor=another, user=user)
    elif change == "role_revoked":
        _change_role(user, Role.REVIEWER, RoleEventType.REVOKED)
    elif change == "role_replaced":
        _change_role(user, Role.REVIEWER, RoleEventType.REVOKED)
        _change_role(user, Role.READER, RoleEventType.GRANTED)
    else:
        given_up = services.disable_mfa(
            actor=verified(user), password=PASSWORD, code=code_at(), source=SOURCE
        )
        assert given_up.outcome == MfaOutcome.ACCEPTED
    before = _state()

    assert _authorize(number, administrator) == UNAVAILABLE

    assert _state() == before
    assert _reasons(caplog) == ["not_eligible"]


def test_eligibility_is_read_from_the_record_when_the_request_is_authorised(
    account: AccountFactory, administrator: AuthenticationContext, another: AuthenticationContext
) -> None:
    user = account(Role.REVIEWER)
    number = _asked(user)
    # The object the caller might hold is not consulted: the role is.
    _change_role(user, Role.REVIEWER, RoleEventType.REVOKED)
    _change_role(user, Role.ADMINISTRATOR, RoleEventType.GRANTED)

    assert _authorize(number, administrator) == AUTHORIZED


# --- Another Administrator must exist to approve what follows (points 39 to 41) --------


def test_a_reviewer_is_recovered_with_two_administrators_and_not_with_one(
    account: AccountFactory,
    administrator: AuthenticationContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user = account(Role.REVIEWER)
    number = _asked(user)
    before = _state()

    assert _authorize(number, administrator) == UNAVAILABLE
    assert _state() == before
    assert _reasons(caplog) == ["no_other_administrator"]

    verified(account(Role.ADMINISTRATOR))
    assert _authorize(number, administrator) == AUTHORIZED


def test_an_administrator_is_recovered_with_three_administrators_and_not_with_two(
    account: AccountFactory,
    administrator: AuthenticationContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The account being recovered is an Administrator who is able to act on
    # record, and does not count: its device is the one that is lost.
    user = account(Role.ADMINISTRATOR)
    number = _asked(user)

    assert _authorize(number, administrator) == UNAVAILABLE
    assert _reasons(caplog) == ["no_other_administrator"]
    assert TotpDevice.objects.filter(user=user).exists()

    verified(account(Role.ADMINISTRATOR))
    assert _authorize(number, administrator) == AUTHORIZED


@pytest.mark.parametrize(
    "unable",
    [
        "disabled",
        "role_revoked",
        "no_device",
        "untrusted_device",
        "pending_device",
        "approved_device_without_its_first_code",
        "not_active",
    ],
)
def test_an_administrator_who_is_not_able_to_act_does_not_count(
    unable: str,
    account: AccountFactory,
    administrator: AuthenticationContext,
    user_with_roles: UserFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    number = _asked(account(Role.REVIEWER))
    if unable == "disabled":
        other = account(Role.ADMINISTRATOR)
        User.objects.filter(pk=other.pk).update(status=AccountStatus.DISABLED)
    elif unable == "role_revoked":
        _change_role(account(Role.ADMINISTRATOR), Role.ADMINISTRATOR, RoleEventType.REVOKED)
    elif unable == "no_device":
        user_with_roles(Role.ADMINISTRATOR)
    elif unable == "untrusted_device":
        account(Role.ADMINISTRATOR, trusted=False)
    elif unable == "pending_device":
        other = user_with_roles(Role.ADMINISTRATOR)
        other.set_password(PASSWORD)
        other.save()
        _enrolment_request(other)
    elif unable == "approved_device_without_its_first_code":
        # Approved, and so trusted once it is active. It is not active: no
        # code from it has been accepted, and it verifies nothing yet.
        other = user_with_roles(Role.ADMINISTRATOR)
        other.set_password(PASSWORD)
        other.save()
        _secret, pending = _enrolment_request(other)
        device = TotpDevice.objects.get(pk=pending)
        device.state = TotpDeviceState.PENDING_VERIFICATION
        device.approved_at = device.created_at
        device.approved_by = supporting_account("test.approver@caipo.test")
        device.save()
    else:
        other = account(Role.ADMINISTRATOR)
        User.objects.filter(pk=other.pk).update(
            status=AccountStatus.PENDING_VERIFICATION, activated_at=None
        )
    before = _state()

    assert _authorize(number, administrator) == UNAVAILABLE

    assert _state() == before
    assert _reasons(caplog) == ["no_other_administrator"]


def test_a_reviewer_with_a_trusted_device_does_not_count_as_the_other_administrator(
    account: AccountFactory, administrator: AuthenticationContext
) -> None:
    number = _asked(account(Role.REVIEWER))
    verified(account(Role.REVIEWER))

    assert _authorize(number, administrator) == UNAVAILABLE


def test_who_is_able_to_act_is_narrower_than_who_is_an_administrator_on_record(
    account: AccountFactory, user_with_roles: UserFactory
) -> None:
    able = account(Role.ADMINISTRATOR)
    on_record_only = user_with_roles(Role.ADMINISTRATOR)

    assert selectors.an_administrator_is_able_to_act(besides=()) is True
    assert selectors.an_administrator_is_able_to_act(besides=(on_record_only.pk,)) is True
    assert selectors.an_administrator_is_able_to_act(besides=(able.pk,)) is False
    # The last-Administrator rule still counts the one who has no device.
    services._require_another_administrator(besides=able)


# --- One answer for every authorisation that is not made -------------------------------


def test_every_reason_is_the_same_result_and_only_the_log_tells_them_apart(
    account: AccountFactory,
    administrator: AuthenticationContext,
    clock: Clock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    results = []
    # No other Administrator exists yet.
    alone = _asked(account(Role.REVIEWER))
    results.append(_authorize(alone, administrator))
    verified(account(Role.ADMINISTRATOR))

    results.append(_authorize(alone + 1000, administrator))

    ineligible = account(Role.REVIEWER)
    number = _asked(ineligible)
    _change_role(ineligible, Role.REVIEWER, RoleEventType.REVOKED)
    results.append(_authorize(number, administrator))

    reset_after = account(Role.REVIEWER)
    number = _asked(reset_after)
    clock(MINUTE)
    _reset_password(reset_after)
    results.append(_authorize(number, administrator))

    reset_before = account(Role.REVIEWER)
    _reset_password(reset_before)
    clock(MINUTE)
    results.append(_authorize(_asked(reset_before, NEW_PASSWORD), administrator))

    lapsed = _asked(account(Role.REVIEWER))
    clock(timedelta(minutes=30))
    results.append(_authorize(lapsed, administrator))

    assert results == [UNAVAILABLE] * 6
    assert [field.name for field in dataclasses.fields(RecoveryDecisionResult)] == ["outcome"]
    assert _reasons(caplog) == [
        "no_other_administrator",
        "unknown_request",
        "not_eligible",
        "request_precedes_reset",
        "cooling_off",
        "lapsed",
    ]
    assert set(_reasons(caplog)) == {reason.value for reason in RecoveryRefusalReason}
    assert _decisions() == []


def test_an_authorisation_that_is_not_made_records_no_failed_submission(
    account: AccountFactory, administrator: AuthenticationContext, settings: LazySettings
) -> None:
    # Point 72: it is not a refused submission and counts towards no limit.
    user = account(Role.REVIEWER)
    number = _asked(user)
    events = _events()

    for _ in range(settings.MFA_RECOVERY_THROTTLE_FAILURES + 2):
        assert _authorize(number, administrator) == UNAVAILABLE
        assert _authorize(number + 1000, administrator) == UNAVAILABLE

    assert _events() == events
    assert "mfa_recovery_failed" not in _events()
    # The account can still ask from the same source.
    assert _asked(user) != number


# --- Rejecting (point 36) --------------------------------------------------------------


def test_a_rejection_removes_the_request_and_changes_nothing_else(
    account: AccountFactory, administrator: AuthenticationContext
) -> None:
    user = account(Role.REVIEWER)
    _reset_token(user)
    number = _asked(user)
    challenge = _challenge(user)
    before = _state()

    assert _reject(number, administrator) == REJECTED

    after = _state()
    assert after["requests"] == []
    assert _decisions() == [("mfa_recovery_rejected", user.pk, administrator.user.pk)]
    for unchanged in ("challenges", "resets", "devices", "users", "roles"):
        assert after[unchanged] == before[unchanged], unchanged
    assert after["events"][:-1] == before["events"]
    # The device still signs the account in.
    accepted = services.verify_second_factor(challenge=challenge, code=code_at(), source=SOURCE)
    assert accepted.outcome == MfaOutcome.ACCEPTED


def test_an_account_whose_request_was_rejected_may_ask_again(
    account: AccountFactory, administrator: AuthenticationContext, another: AuthenticationContext
) -> None:
    user = account(Role.REVIEWER)
    rejected = _asked(user)
    _reject(rejected, administrator)

    again = _asked(user)

    assert again != rejected
    assert _reject(rejected, administrator) == UNAVAILABLE
    assert _authorize(rejected, administrator) == UNAVAILABLE
    assert _authorize(again, administrator) == AUTHORIZED


def test_a_rejection_needs_no_other_administrator_and_no_eligible_account(
    account: AccountFactory, administrator: AuthenticationContext, clock: Clock
) -> None:
    # Everything that would stop an authorisation, short of the request
    # having lapsed: one Administrator, a reset a minute ago, and no role.
    user = account(Role.REVIEWER)
    number = _asked(user)
    clock(MINUTE)
    _reset_password(user)
    _change_role(user, Role.REVIEWER, RoleEventType.REVOKED)
    assert _authorize(number, administrator) == UNAVAILABLE

    assert _reject(number, administrator) == REJECTED


def test_a_rejection_of_a_request_that_is_gone_or_lapsed_is_unavailable(
    account: AccountFactory,
    administrator: AuthenticationContext,
    clock: Clock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    number = _asked(account(Role.REVIEWER))

    assert _reject(number + 1000, administrator) == UNAVAILABLE
    clock(timedelta(minutes=30))
    before = _state()
    assert _reject(number, administrator) == UNAVAILABLE

    assert _state() == before
    assert _reasons(caplog) == ["unknown_request", "lapsed"]
    assert _decisions() == []


# --- The Administrator who authorised does not approve what follows (point 37) ---------


def test_whoever_authorised_a_recovery_cannot_approve_the_enrolment_that_follows(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user = account(Role.REVIEWER)
    _authorize(_asked(user), administrator)
    _secret, number = _enrolment_request(user)
    before = _state()

    with pytest.raises(PermissionDenied):
        _approve(number, administrator)

    assert _state() == before
    assert selectors.mfa_state_of(user) == MfaState.PENDING_APPROVAL
    assert "mfa.recovery_authorizer_approval_refused" in [
        record.__dict__.get("event") for record in caplog.records
    ]


def test_an_administrator_who_did_not_authorise_approves_it(
    account: AccountFactory, administrator: AuthenticationContext, another: AuthenticationContext
) -> None:
    user = account(Role.REVIEWER)
    _authorize(_asked(user), administrator)
    secret, number = _enrolment_request(user)

    assert _approve(number, another).outcome == MfaOutcome.ACCEPTED

    device = TotpDevice.objects.get(user=user)
    assert device.approved_by == another.user
    confirmed = _confirm(user, secret)
    assert confirmed.outcome == MfaOutcome.ACCEPTED
    # Authorised by one Administrator and approved by a different one.
    authorized = AuthenticationEvent.objects.get(event_type="mfa_recovery_authorized")
    approved = AuthenticationEvent.objects.filter(
        event_type="mfa_enrollment_approved", user=user
    ).get()
    assert authorized.actor == administrator.user
    assert approved.actor == another.user
    assert selectors.can(confirmed.context, Permission.RESEARCH_REVIEW)


def test_the_rule_is_in_the_approval_service_that_every_approval_goes_through(
    account: AccountFactory, administrator: AuthenticationContext, another: AuthenticationContext
) -> None:
    # Not a rule of some page for recoveries: the one service that approves
    # an enrolment refuses, however the enrolment came to be requested.
    user = account(Role.REVIEWER)
    _authorize(_asked(user), administrator)
    for _ in range(3):
        _secret, number = _enrolment_request(user)
        with pytest.raises(PermissionDenied):
            services.approve_mfa_enrollment(
                actor=administrator, request_number=number, source=SOURCE
            )

    assert "open_recovery_authorizer_id" in inspect.getsource(services._decide_enrollment)


def test_the_authoriser_stays_refused_until_a_trusted_device_has_become_active(
    account: AccountFactory, administrator: AuthenticationContext, another: AuthenticationContext
) -> None:
    user = account(Role.REVIEWER)
    _authorize(_asked(user), administrator)
    assert selectors.open_recovery_authorizer_id(user.pk) == administrator.user.pk

    # Requested, and approved by the other Administrator: no device is active.
    secret, number = _enrolment_request(user)
    assert _approve(number, another).outcome == MfaOutcome.ACCEPTED
    assert selectors.open_recovery_authorizer_id(user.pk) == administrator.user.pk

    # Requested again before the first code: the approval is gone with the
    # earlier secret, and the authoriser is refused the new request too.
    secret, number = _enrolment_request(user)
    with pytest.raises(PermissionDenied):
        _approve(number, administrator)
    assert _approve(number, another).outcome == MfaOutcome.ACCEPTED
    assert selectors.open_recovery_authorizer_id(user.pk) == administrator.user.pk

    # The first code makes the approved device active: the recovery is over.
    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED
    assert selectors.open_recovery_authorizer_id(user.pk) is None


def test_the_authoriser_may_approve_again_once_the_recovery_is_over(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    clock: Clock,
) -> None:
    user = account(Role.REVIEWER)
    _authorize(_asked(user), administrator)
    secret, number = _enrolment_request(user)
    _approve(number, another)
    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED

    # Later the account replaces that device on both proofs. This enrolment
    # follows no recovery.
    clock(STEP * 4)
    replaced = services.replace_mfa_device(
        actor=signed_in(user), password=PASSWORD, code=code_at(secret=secret), source=SOURCE
    )
    assert replaced.outcome == MfaOutcome.ACCEPTED
    following = selectors.enrollment_request_number_of(user)
    assert following is not None

    assert _approve(following, administrator).outcome == MfaOutcome.ACCEPTED


def test_a_device_that_nobody_approved_does_not_end_the_recovery(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    clock: Clock,
) -> None:
    user = account(Role.REVIEWER)
    _authorize(_asked(user), administrator)
    # The account loses the role, enrols by itself as a Reader does, and is
    # given the role back: its device is active and nobody approved it.
    _change_role(user, Role.REVIEWER, RoleEventType.REVOKED)
    _change_role(user, Role.READER, RoleEventType.GRANTED)
    started = services.start_mfa_enrollment(actor=signed_in(user), password=PASSWORD, source=SOURCE)
    assert started.provisioning is not None
    secret = base64.b32decode(started.provisioning.secret)
    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED
    assert TotpDevice.objects.get(user=user).approved_at is None
    _change_role(user, Role.REVIEWER, RoleEventType.GRANTED)

    assert selectors.open_recovery_authorizer_id(user.pk) == administrator.user.pk

    # It replaces that device, and the new one awaits approval.
    clock(STEP * 4)
    replaced = services.replace_mfa_device(
        actor=signed_in(user), password=PASSWORD, code=code_at(secret=secret), source=SOURCE
    )
    assert replaced.outcome == MfaOutcome.ACCEPTED
    number = selectors.enrollment_request_number_of(user)
    assert number is not None
    with pytest.raises(PermissionDenied):
        _approve(number, administrator)
    assert _approve(number, another).outcome == MfaOutcome.ACCEPTED


def test_an_approval_does_not_outlive_the_request_it_was_given_to(
    account: AccountFactory, administrator: AuthenticationContext, another: AuthenticationContext
) -> None:
    user = account(Role.REVIEWER)
    _authorize(_asked(user), administrator)
    _secret, number = _enrolment_request(user)
    assert _approve(number, another).outcome == MfaOutcome.ACCEPTED
    # Before the first code, the account loses the role and asks again. The
    # new request needs no approval and has none: the earlier approval went
    # with the earlier secret.
    _change_role(user, Role.REVIEWER, RoleEventType.REVOKED)
    _change_role(user, Role.READER, RoleEventType.GRANTED)
    started = services.start_mfa_enrollment(actor=signed_in(user), password=PASSWORD, source=SOURCE)
    assert started.provisioning is not None
    assert _confirm(user, base64.b32decode(started.provisioning.secret)).outcome == (
        MfaOutcome.ACCEPTED
    )

    assert TotpDevice.objects.get(user=user).approved_at is None
    assert selectors.open_recovery_authorizer_id(user.pk) == administrator.user.pk


def test_the_rule_names_whoever_authorised_the_most_recent_recovery(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    clock: Clock,
) -> None:
    third = verified(account(Role.ADMINISTRATOR))
    user = account(Role.REVIEWER)
    _authorize(_asked(user), administrator)
    secret, number = _enrolment_request(user)
    _approve(number, another)
    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED

    # The new device is lost as well, and another Administrator authorises.
    clock(MINUTE)
    assert _authorize(_asked(user), another) == AUTHORIZED
    assert selectors.open_recovery_authorizer_id(user.pk) == another.user.pk
    _secret, number = _enrolment_request(user)

    with pytest.raises(PermissionDenied):
        _approve(number, another)
    assert _approve(number, administrator).outcome == MfaOutcome.ACCEPTED
    assert third.user.pk not in (administrator.user.pk, another.user.pk)


def test_the_rule_does_not_reach_an_account_that_was_never_recovered(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    user_with_roles: UserFactory,
) -> None:
    recovered = account(Role.REVIEWER)
    _authorize(_asked(recovered), administrator)
    bystander = user_with_roles(Role.REVIEWER)
    bystander.set_password(PASSWORD)
    bystander.save()
    _secret, number = _enrolment_request(bystander)

    assert selectors.open_recovery_authorizer_id(bystander.pk) is None
    assert _approve(number, administrator).outcome == MfaOutcome.ACCEPTED


def test_the_authoriser_may_still_reject_the_enrolment_that_follows(
    account: AccountFactory, administrator: AuthenticationContext, another: AuthenticationContext
) -> None:
    # A rejection makes no device trusted, and the rule is about trust.
    user = account(Role.REVIEWER)
    _authorize(_asked(user), administrator)
    _secret, number = _enrolment_request(user)

    rejected = services.reject_mfa_enrollment(
        actor=administrator, request_number=number, source=SOURCE
    )

    assert rejected.outcome == MfaOutcome.ACCEPTED
    assert selectors.open_recovery_authorizer_id(user.pk) == administrator.user.pk


def test_a_rejected_recovery_request_opens_no_recovery(
    account: AccountFactory, administrator: AuthenticationContext
) -> None:
    user = account(Role.REVIEWER)
    _reject(_asked(user), administrator)

    assert selectors.open_recovery_authorizer_id(user.pk) is None


def test_one_administrator_cannot_do_both_and_so_cannot_take_over_an_account(
    account: AccountFactory, administrator: AuthenticationContext, another: AuthenticationContext
) -> None:
    # Security property 6, end to end: an Administrator who knows a
    # Reviewer's password asks, authorises, asks for an enrolment, and is
    # stopped at the approval. The device they hold accepts no code.
    user = account(Role.REVIEWER)
    assert _authorize(_asked(user), administrator) == AUTHORIZED
    secret, number = _enrolment_request(user)

    with pytest.raises(PermissionDenied):
        _approve(number, administrator)

    assert _confirm(user, secret).outcome == MfaOutcome.UNAVAILABLE
    assert selectors.permissions_of(signed_in(user)) == {Permission.MFA_MANAGE_OWN}
    assert not TotpDevice.objects.filter(user=user, state=TotpDeviceState.ACTIVE).exists()


# --- The list an Administrator decides from --------------------------------------------


def test_the_list_holds_what_awaits_a_decision_oldest_first(
    account: AccountFactory, administrator: AuthenticationContext, clock: Clock
) -> None:
    first, second, lapsed = (account(Role.REVIEWER) for _ in range(3))
    lapsed_number = _asked(lapsed)
    clock(timedelta(minutes=20))
    first_number = _asked(first)
    clock(MINUTE)
    second_number = _asked(second)
    clock(timedelta(minutes=9))

    listed = selectors.recovery_requests_awaiting_decision(administrator)

    assert [(item.number, item.email) for item in listed] == [
        (first_number, first.email),
        (second_number, second.email),
    ]
    assert lapsed_number not in [item.number for item in listed]
    assert [field.name for field in dataclasses.fields(listed[0])] == [
        "number",
        "email",
        "requested_at",
    ]


def test_the_list_never_holds_the_request_of_whoever_is_looking(
    account: AccountFactory, administrator: AuthenticationContext
) -> None:
    _asked(administrator.user)

    assert selectors.recovery_requests_awaiting_decision(administrator) == []


def test_the_list_is_refused_to_a_password_and_to_every_other_role(
    account: AccountFactory, administrator: AuthenticationContext
) -> None:
    refused = [signed_in(administrator.user)]
    refused += [verified(account(role)) for role in (Role.READER, Role.RESEARCHER, Role.REVIEWER)]

    for context in refused:
        with pytest.raises(PermissionDenied):
            selectors.recovery_requests_awaiting_decision(context)


# --- What is kept, and what is not (point 88) ------------------------------------------


def test_no_event_and_no_log_holds_an_address_a_password_or_a_secret(
    account: AccountFactory,
    administrator: AuthenticationContext,
    another: AuthenticationContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    authorized, rejected, unavailable = (account(Role.REVIEWER) for _ in range(3))
    challenge = _challenge(authorized)
    reset_token = _reset_token(authorized)
    numbers = [_asked(user) for user in (authorized, rejected, unavailable)]
    _change_role(unavailable, Role.REVIEWER, RoleEventType.REVOKED)
    caplog.clear()

    assert _authorize(numbers[0], administrator) == AUTHORIZED
    assert _reject(numbers[1], administrator) == REJECTED
    assert _authorize(numbers[2], administrator) == UNAVAILABLE

    forbidden = [
        *(user.email for user in (authorized, rejected, unavailable, administrator.user)),
        SOURCE,
        ADMINISTRATOR_SOURCE,
        PASSWORD,
        challenge,
        reset_token,
        base64.b32encode(b"TEST-totp-secret-000").decode(),
    ]
    events = repr(list(AuthenticationEvent.objects.filter(event_type__in=DECISION_EVENTS).values()))
    written = logged(caplog.records)
    for value in forbidden:
        assert value not in events, value
        assert value not in written, value
    assert {
        event
        for event in (record.__dict__.get("event") for record in caplog.records)
        if isinstance(event, str) and event.startswith("mfa_recovery.")
    } == {
        "mfa_recovery.authorized",
        "mfa_recovery.rejected",
        "mfa_recovery.decision_unavailable",
    }


def test_a_decision_that_is_not_made_is_logged_by_reason_and_actor_only(
    account: AccountFactory,
    administrator: AuthenticationContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user = account(Role.REVIEWER)
    number = _asked(user)
    caplog.clear()

    _authorize(number, administrator)

    (record,) = [
        record
        for record in caplog.records
        if record.__dict__.get("event") == "mfa_recovery.decision_unavailable"
    ]
    extra = {name: record.__dict__[name] for name in ("event", "decision", "reason", "actor_id")}
    assert extra == {
        "event": "mfa_recovery.decision_unavailable",
        "decision": "authorize",
        "reason": "no_other_administrator",
        "actor_id": administrator.user.pk,
    }
    assert "user_id" not in record.__dict__
    assert str(number) not in record.getMessage()
