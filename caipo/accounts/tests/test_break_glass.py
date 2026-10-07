"""The two emergency actions of the break-glass command (ADR-0017, points 59 to 70).

The services the command calls, without the command: what each action
requires, what it does, what it leaves alone, and how the recovery it opens
or continues is completed. No HTTP is involved, and nothing stands in for
TOTP or for the authorization decision: requests are made, authorised, and
approved, and enrolments confirmed, by the services themselves.
"""

import base64
import dataclasses
import inspect
import logging
import re
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

import caipo
from caipo.accounts import authorization, selectors, services, totp
from caipo.accounts.models import (
    AccountStatus,
    AuthenticationEvent,
    BreakGlassAction,
    MfaChallenge,
    MfaRecoveryRequest,
    PasswordReset,
    RoleEventType,
    TotpDevice,
    TotpDeviceState,
    User,
)
from caipo.accounts.selectors import (
    Assurance,
    AuthenticationContext,
    MfaState,
    OpenRecovery,
    Permission,
    Role,
)
from caipo.accounts.services import (
    BreakGlassOutcome,
    BreakGlassResult,
    MfaOutcome,
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
from caipo.accounts.tests.test_recovery_authorization import (
    AUTHORIZED,
    NEW_PASSWORD,
    PASSWORD,
    SOURCE,
    STEP,
    _approve,
    _asked,
    _authorize,
    _challenge,
    _change_role,
    _confirm,
    _enrolment_request,
    _events,
    _reset_password,
    _reset_token,
    _state,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db]

type AccountFactory = Callable[..., User]

DONE = BreakGlassResult(BreakGlassOutcome.DONE)
UNAVAILABLE = BreakGlassResult(BreakGlassOutcome.UNAVAILABLE)

BREAK_GLASS = "mfa_recovery_break_glass"
REVOKE = "revoke_device"
APPROVE = "approve_enrollment"
COMPLETED = "mfa_recovery_completed"


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


def _revoke(user: User, number: int) -> BreakGlassResult:
    return services.break_glass_revoke_device(email=user.email, request_number=number)


def _approve_by_break_glass(user: User, number: int) -> BreakGlassResult:
    return services.break_glass_approve_enrollment(email=user.email, request_number=number)


def _revoked(user: User) -> None:
    """Revoke the account's device by break-glass, on a request its owner makes."""
    assert _revoke(user, _asked(user)) == DONE


def _break_glass_events(user: User | None = None) -> list[AuthenticationEvent]:
    events = AuthenticationEvent.objects.filter(event_type=BREAK_GLASS).order_by("id")
    if user is not None:
        events = events.filter(user=user)
    return list(events)


def _reasons(caplog: pytest.LogCaptureFixture) -> list[tuple[str, str]]:
    return [
        (record.__dict__["action"], record.__dict__["reason"])
        for record in caplog.records
        if record.__dict__.get("event") == "mfa_recovery.break_glass_unavailable"
    ]


def _pending_device(user: User) -> TotpDevice:
    """Write a request that awaits approval straight into the table, past every service."""
    ciphertext, key_id = totp.encrypt_secret(b"TEST-totp-secret-999", user_id=user.pk)
    return TotpDevice.objects.create(
        user=user,
        state=TotpDeviceState.PENDING_APPROVAL,
        secret_ciphertext=ciphertext,
        key_id=key_id,
    )


def _unable(administrator: User, how: str) -> None:
    """Leave an Administrator on record who is not able to act (point 39)."""
    if how == "no device":
        TotpDevice.objects.filter(user=administrator).delete()
    elif how == "untrusted device":
        TotpDevice.objects.filter(user=administrator).update(approved_at=None, approved_by=None)
    elif how == "disabled":
        User.objects.filter(pk=administrator.pk).update(status=AccountStatus.DISABLED)
    elif how == "role revoked":
        _change_role(administrator, Role.ADMINISTRATOR, RoleEventType.REVOKED)
    else:
        TotpDevice.objects.filter(user=administrator).delete()
        _pending_device(administrator)


UNABLE = ["no device", "untrusted device", "disabled", "role revoked", "pending device"]


# --- Revoking: who and when (points 59, 63, and 66) -------------------------------------


def test_the_only_administrator_has_the_lost_device_revoked(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    number = _asked(user)

    assert _revoke(user, number) == DONE

    assert not TotpDevice.objects.filter(user=user).exists()
    assert selectors.mfa_state_of(user) == MfaState.NOT_ENROLLED


def test_one_other_administrator_is_not_enough_for_the_normal_path_so_the_command_revokes(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    other = verified(account(Role.ADMINISTRATOR))
    number = _asked(user)
    # The application's own path: one Administrator cannot authorise alone.
    assert _authorize(number, other).outcome.value == "unavailable"

    assert _revoke(user, number) == DONE


def test_two_other_administrators_who_are_able_to_act_make_the_command_refuse(
    account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    user = account(Role.ADMINISTRATOR)
    first, _second = verified(account(Role.ADMINISTRATOR)), verified(account(Role.ADMINISTRATOR))
    number = _asked(user)
    before = _state()

    assert _revoke(user, number) == UNAVAILABLE

    assert _state() == before
    assert _reasons(caplog) == [(REVOKE, "normal_path_available")]
    # They do it, as point 66 says.
    assert _authorize(number, first) == AUTHORIZED


@pytest.mark.parametrize("how", UNABLE)
def test_an_administrator_who_is_not_able_to_act_does_not_make_the_normal_path_available(
    how: str, account: AccountFactory
) -> None:
    user = account(Role.ADMINISTRATOR)
    verified(account(Role.ADMINISTRATOR))
    _unable(account(Role.ADMINISTRATOR), how)
    number = _asked(user)

    assert _revoke(user, number) == DONE


def test_a_reviewer_with_a_trusted_device_is_not_one_of_the_two_administrators(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    verified(account(Role.ADMINISTRATOR))
    verified(account(Role.REVIEWER))

    assert _revoke(user, _asked(user)) == DONE


@pytest.mark.parametrize("roles", [(Role.REVIEWER,), (Role.REVIEWER, Role.RESEARCHER)])
def test_the_command_never_revokes_for_a_reviewer(
    roles: tuple[Role, ...], account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    # Point 43, whatever the number of Administrators: here there is none.
    user = account(*roles)
    number = _asked(user)
    before = _state()

    assert _revoke(user, number) == UNAVAILABLE

    assert _state() == before
    assert _reasons(caplog) == [(REVOKE, "not_administrator")]


@pytest.mark.parametrize("role", [Role.READER, Role.RESEARCHER])
def test_the_command_never_revokes_for_an_account_without_a_privileged_role(
    role: Role, account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    user = account(role)
    # Such an account cannot ask. Suppose a request existed all the same.
    request = MfaRecoveryRequest.objects.create(user=user, created_at=timezone.now())
    before = _state()

    assert _revoke(user, request.pk) == UNAVAILABLE

    assert _state() == before
    assert _reasons(caplog) == [(REVOKE, "not_administrator")]


def test_an_administrator_who_also_holds_another_role_is_recovered(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR, Role.REVIEWER)

    assert _revoke(user, _asked(user)) == DONE


def test_an_administrator_whose_role_was_revoked_since_asking_is_refused(
    account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    user = account(Role.ADMINISTRATOR, Role.REVIEWER)
    number = _asked(user)
    _change_role(user, Role.ADMINISTRATOR, RoleEventType.REVOKED)

    assert _revoke(user, number) == UNAVAILABLE
    assert _reasons(caplog) == [(REVOKE, "not_administrator")]


def test_a_disabled_account_is_refused(
    account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    user = account(Role.ADMINISTRATOR)
    number = _asked(user)
    User.objects.filter(pk=user.pk).update(status=AccountStatus.DISABLED)
    before = _state()

    assert _revoke(user, number) == UNAVAILABLE

    assert _state() == before
    assert _reasons(caplog) == [(REVOKE, "not_eligible")]


@pytest.mark.parametrize("email", ["test.nobody@caipo.test", "", "TEST not an address", "1"])
def test_an_address_that_has_no_account_is_refused(
    email: str, account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    number = _asked(account(Role.ADMINISTRATOR))
    before = _state()

    result = services.break_glass_revoke_device(email=email, request_number=number)

    assert result == UNAVAILABLE
    assert _state() == before
    assert _reasons(caplog) == [(REVOKE, "unknown_account")]


def test_the_address_is_read_as_sign_in_reads_it(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    number = _asked(user)

    result = services.break_glass_revoke_device(
        email=f"  {user.email.upper()} ", request_number=number
    )

    assert result == DONE


def test_the_account_and_the_number_must_name_the_same_request(
    account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    user, other = account(Role.ADMINISTRATOR), account(Role.ADMINISTRATOR)
    number, other_number = _asked(user), _asked(other)
    before = _state()

    # Each number is a current request, of the other account.
    assert _revoke(user, other_number) == UNAVAILABLE
    assert _revoke(other, number) == UNAVAILABLE
    assert _revoke(user, number + other_number + 1000) == UNAVAILABLE

    assert _state() == before
    assert _reasons(caplog) == [(REVOKE, "unknown_request")] * 3
    assert _revoke(user, number) == DONE


def test_a_request_that_was_replaced_is_refused_and_the_new_one_is_not(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    earlier = _asked(user)
    current = _asked(user)

    assert _revoke(user, earlier) == UNAVAILABLE
    assert _revoke(user, current) == DONE


def test_a_request_lapses_for_the_command_after_thirty_minutes_exactly(
    account: AccountFactory, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    user = account(Role.ADMINISTRATOR)
    lapsing = _asked(user)
    clock(timedelta(minutes=30))
    before = _state()

    assert _revoke(user, lapsing) == UNAVAILABLE

    assert _state() == before
    assert _reasons(caplog) == [(REVOKE, "lapsed")]
    in_time = _asked(user)
    clock(timedelta(minutes=30) - timedelta(seconds=1))
    assert _revoke(user, in_time) == DONE


def test_a_request_made_before_a_password_reset_is_refused_whatever_its_age(
    account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    # Point 51.
    user = account(Role.ADMINISTRATOR)
    number = _asked(user)
    _reset_password(user)
    before = _state()

    assert _revoke(user, number) == UNAVAILABLE

    assert _state() == before
    assert _reasons(caplog) == [(REVOKE, "request_precedes_reset")]


def test_the_command_does_not_revoke_within_a_day_of_a_password_reset(
    account: AccountFactory, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    # Point 50: the cooling-off binds the break-glass procedure too.
    user = account(Role.ADMINISTRATOR)
    _reset_password(user)
    clock(timedelta(hours=24) - timedelta(seconds=1))
    number = _asked(user, NEW_PASSWORD)
    before = _state()

    assert _revoke(user, number) == UNAVAILABLE

    assert _state() == before
    assert _reasons(caplog) == [(REVOKE, "cooling_off")]
    clock(timedelta(seconds=1))
    assert _revoke(user, number) == DONE


def test_an_account_whose_device_is_gone_is_refused(
    account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    user = account(Role.ADMINISTRATOR)
    number = _asked(user)
    TotpDevice.objects.filter(user=user).delete()
    before = _state()

    assert _revoke(user, number) == UNAVAILABLE

    assert _state() == before
    assert _reasons(caplog) == [(REVOKE, "not_eligible")]


def test_a_device_that_only_awaits_approval_is_not_a_lost_device(
    account: AccountFactory,
) -> None:
    # Point 16: such an account needs no recovery.
    user = account(Role.ADMINISTRATOR)
    number = _asked(user)
    TotpDevice.objects.filter(user=user).delete()
    _pending_device(user)

    assert _revoke(user, number) == UNAVAILABLE


def test_a_device_that_nobody_approved_is_revoked_like_any_other(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR, trusted=False)

    assert _revoke(user, _asked(user)) == DONE


# --- Revoking: every effect of an authorisation (points 45 and 63) ----------------------


def test_revoking_has_every_effect_of_an_authorisation(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    User.objects.filter(pk=user.pk).update(session_epoch=41)
    _reset_token(user)
    number = _asked(user)
    _challenge(user)
    assert MfaChallenge.objects.filter(user=user).exists()
    assert PasswordReset.objects.filter(user=user).exists()

    assert _revoke(user, number) == DONE

    assert not TotpDevice.objects.filter(user=user).exists()
    assert User.objects.get(pk=user.pk).session_epoch == 42
    assert not MfaChallenge.objects.filter(user=user).exists()
    assert not PasswordReset.objects.filter(user=user).exists()
    assert not MfaRecoveryRequest.objects.filter(user=user).exists()


def test_revoking_and_authorising_leave_the_same_state_but_for_their_record(
    account: AccountFactory,
) -> None:
    def left_by(finalise: Callable[[User, int], object], user: User) -> dict[str, Any]:
        _reset_token(user)
        number = _asked(user)
        _challenge(user)
        finalise(user, number)
        stored = User.objects.get(pk=user.pk)
        return {
            "epoch": stored.session_epoch,
            "device": TotpDevice.objects.filter(user=user).count(),
            "challenge": MfaChallenge.objects.filter(user=user).count(),
            "reset": PasswordReset.objects.filter(user=user).count(),
            "request": MfaRecoveryRequest.objects.filter(user=user).count(),
            "events": _events(user)[:-1],
        }

    by_command = left_by(_revoke, account(Role.ADMINISTRATOR))
    authoriser = verified(account(Role.ADMINISTRATOR))
    verified(account(Role.ADMINISTRATOR))
    by_administrator = left_by(
        lambda user, number: _authorize(number, authoriser), account(Role.ADMINISTRATOR)
    )

    assert by_command == by_administrator
    assert by_command["epoch"] == 1
    assert services._finalize_recovery.__name__ in inspect.getsource(
        services.break_glass_revoke_device
    )


def test_the_revocation_is_recorded_once_as_a_break_glass_event_and_as_nothing_else(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    number = _asked(user)
    events_before = AuthenticationEvent.objects.count()

    assert _revoke(user, number) == DONE

    assert AuthenticationEvent.objects.count() == events_before + 1
    (event,) = _break_glass_events()
    assert event == AuthenticationEvent.objects.order_by("-id").first()
    assert (event.user, event.actor) == (user, None)
    assert event.break_glass_action == BreakGlassAction.REVOKE_DEVICE == REVOKE
    assert event.source_key == ""
    assert event.identifier_key == services._key("identifier", user.email)
    assert not AuthenticationEvent.objects.filter(event_type="mfa_recovery_authorized").exists()
    assert not AuthenticationEvent.objects.filter(event_type="mfa_recovery_failed").exists()


def test_revoking_changes_nothing_else_about_the_account(account: AccountFactory) -> None:
    # Property 9.
    user = account(Role.ADMINISTRATOR, Role.RESEARCHER)
    services.sign_in(email=user.email, password="TEST-wrong-passphrase", source=SOURCE)
    number = _asked(user)
    stored = User.objects.get(pk=user.pk)
    kept = (stored.password, stored.status, stored.email, stored.email_verified_at)
    kept_events = list(AuthenticationEvent.objects.order_by("id").values())
    roles = selectors.roles_of(user)

    assert _revoke(user, number) == DONE

    stored = User.objects.get(pk=user.pk)
    assert (stored.password, stored.status, stored.email, stored.email_verified_at) == kept
    assert stored.check_password(PASSWORD)
    assert selectors.roles_of(user) == roles
    # Every event that the limits count is as it was: one event was added.
    assert list(AuthenticationEvent.objects.order_by("id").values())[:-1] == kept_events


def test_revoking_touches_no_other_account(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    bystander = account(Role.ADMINISTRATOR)
    other_number = _asked(bystander)
    _reset_token(bystander)
    bystander_challenge = _challenge(bystander)

    assert _revoke(user, _asked(user)) == DONE

    assert User.objects.get(pk=bystander.pk).session_epoch == 0
    assert TotpDevice.objects.filter(user=bystander, state=TotpDeviceState.ACTIVE).exists()
    assert MfaRecoveryRequest.objects.filter(pk=other_number).exists()
    assert PasswordReset.objects.filter(user=bystander).exists()
    verification = services.verify_second_factor(
        challenge=bystander_challenge, code=code_at(), source=SOURCE
    )
    assert verification.outcome == MfaOutcome.ACCEPTED


def test_revoking_signs_nobody_in_and_returns_nothing_but_an_outcome(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)

    result = _revoke(user, _asked(user))

    assert [field.name for field in dataclasses.fields(result)] == ["outcome"]
    assert not AuthenticationEvent.objects.filter(
        user=user, event_type__in=["login_success", "mfa_verification_succeeded"]
    ).exists()
    assert not TotpDevice.objects.filter(user=user).exists()


def test_what_existed_before_the_revocation_is_refused_after_it(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    context = verified(user)
    session_value = user.get_session_auth_hash()
    token = _reset_token(user)
    number = _asked(user)
    challenge = _challenge(user)
    assert selectors.can(context, Permission.ROLES_MANAGE)

    assert _revoke(user, number) == DONE

    assert User.objects.get(pk=user.pk).get_session_auth_hash() != session_value
    assert not selectors.can(context, Permission.ROLES_MANAGE)
    verification = services.verify_second_factor(challenge=challenge, code=code_at(), source=SOURCE)
    assert verification.outcome == MfaOutcome.REFUSED
    reset = services.reset_password(token=token, password=NEW_PASSWORD, source=SOURCE)
    assert reset.outcome.value == "refused"
    assert User.objects.get(pk=user.pk).check_password(PASSWORD)


def test_a_recovered_administrator_holds_nothing_on_the_password_but_its_own_second_factor(
    account: AccountFactory,
) -> None:
    # Properties 1 and 2.
    user = account(Role.ADMINISTRATOR)
    _revoked(user)

    result = services.sign_in(email=user.email, password=PASSWORD, source=SOURCE)

    assert result.outcome == SignInOutcome.SIGNED_IN
    assert selectors.permissions_of(signed_in(user)) == {Permission.MFA_MANAGE_OWN}
    claimed = AuthenticationContext(user, Assurance.MFA_VERIFIED, 1)
    assert selectors.permissions_of(claimed) == {Permission.MFA_MANAGE_OWN}


def test_a_revocation_cannot_be_done_twice(
    account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    user = account(Role.ADMINISTRATOR)
    number = _asked(user)
    assert _revoke(user, number) == DONE
    before = _state()

    assert _revoke(user, number) == UNAVAILABLE

    assert _state() == before
    assert _reasons(caplog) == [(REVOKE, "unknown_request")]
    assert len(_break_glass_events()) == 1


# --- Revoking: faults ------------------------------------------------------------------


def _fail(*args: object, **kwargs: object) -> None:
    raise RuntimeError("TEST fault in a break-glass action")


def test_a_revocation_whose_event_cannot_be_written_changes_nothing(
    account: AccountFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = account(Role.ADMINISTRATOR)
    _reset_token(user)
    number = _asked(user)
    _challenge(user)
    before = _state()

    with monkeypatch.context() as patched:
        patched.setattr(services, "_record", _fail)
        with pytest.raises(RuntimeError, match="TEST fault"):
            _revoke(user, number)

    assert _state() == before
    assert _revoke(user, number) == DONE


@pytest.mark.parametrize("step", [TotpDevice, MfaChallenge, PasswordReset, MfaRecoveryRequest])
def test_a_fault_at_any_removal_of_the_revocation_rolls_back_the_steps_before_it(
    step: type[Any], account: AccountFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = account(Role.ADMINISTRATOR)
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
            _revoke(user, number)

    assert _state() == before
    assert _revoke(user, number) == DONE


def test_a_fault_while_ending_the_sessions_rolls_back_the_revocation(
    account: AccountFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = account(Role.ADMINISTRATOR)
    number = _asked(user)
    before = _state()
    queryset = type(User.objects.all())
    update = queryset.update

    def fail(self: Any, **kwargs: Any) -> Any:
        if "session_epoch" in kwargs:
            raise RuntimeError("TEST fault while raising the session epoch")
        return update(self, **kwargs)

    with monkeypatch.context() as patched:
        patched.setattr(queryset, "update", fail)
        with pytest.raises(RuntimeError, match="TEST fault"):
            _revoke(user, number)

    assert _state() == before
    assert TotpDevice.objects.filter(user=user, state=TotpDeviceState.ACTIVE).exists()


def test_the_database_refuses_a_revocation_recorded_with_a_source_or_an_actor(
    account: AccountFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Suppose the service were wrong about its own event. The constraints
    # refuse it, and the revocation is rolled back with it.
    user, other = account(Role.ADMINISTRATOR), account(Role.ADMINISTRATOR)
    number = _asked(user)
    before = _state()
    record = services._record
    action = BreakGlassAction.REVOKE_DEVICE

    def with_a_source(event_type: Any, named: Any, key: str, _source: str, **_: Any) -> None:
        record(event_type, named, key, "k", break_glass_action=action)

    def with_an_actor(event_type: Any, named: Any, key: str, _source: str, **_: Any) -> None:
        record(event_type, named, key, "", actor=other, break_glass_action=action)

    def without_an_action(event_type: Any, named: Any, key: str, _source: str, **_: Any) -> None:
        record(event_type, named, key, "")

    for wrong, constraint in (
        (with_a_source, "break_glass_has_no_source"),
        (with_an_actor, "actor_iff_decision"),
        (without_an_action, "action_iff_break_glass"),
    ):
        with monkeypatch.context() as patched:
            patched.setattr(services, "_record", wrong)
            with pytest.raises(IntegrityError, match=constraint):
                _revoke(user, number)
        assert _state() == before


# --- Approving: which enrolment, and when (points 63 and 66) ----------------------------


def test_the_only_administrator_has_the_enrolment_that_follows_approved(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    _revoked(user)
    _secret, number = _enrolment_request(user)

    assert _approve_by_break_glass(user, number) == DONE

    device = TotpDevice.objects.get(user=user)
    assert device.pk == number
    assert device.state == TotpDeviceState.PENDING_VERIFICATION
    assert device.approved_at is not None
    assert device.approved_by is None
    assert (device.confirmed_at, device.last_used_step) == (None, None)


def test_an_approval_by_the_command_makes_nothing_active_and_nothing_trusted_yet(
    account: AccountFactory,
) -> None:
    # Point 64.
    user = account(Role.ADMINISTRATOR)
    _revoked(user)
    _secret, number = _enrolment_request(user)

    result = _approve_by_break_glass(user, number)

    assert [field.name for field in dataclasses.fields(result)] == ["outcome"]
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION
    assert not TotpDevice.objects.filter(state=TotpDeviceState.ACTIVE, user=user).exists()
    claimed = AuthenticationContext(user, Assurance.MFA_VERIFIED, number)
    assert selectors.permissions_of(claimed) == {Permission.MFA_MANAGE_OWN}
    # The password still signs in by itself: the device is not asked for.
    assert (
        services.sign_in(email=user.email, password=PASSWORD, source=SOURCE).outcome
        == SignInOutcome.SIGNED_IN
    )
    assert selectors.has_open_recovery(user.pk)
    assert not AuthenticationEvent.objects.filter(event_type=COMPLETED).exists()


def test_the_approval_is_recorded_once_as_a_break_glass_event_and_as_nothing_else(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    _revoked(user)
    _secret, number = _enrolment_request(user)
    events_before = AuthenticationEvent.objects.count()
    kept = User.objects.filter(pk=user.pk).values().get()

    assert _approve_by_break_glass(user, number) == DONE

    assert AuthenticationEvent.objects.count() == events_before + 1
    event = AuthenticationEvent.objects.order_by("-id").first()
    assert event is not None
    assert (event.event_type, event.user, event.actor) == (BREAK_GLASS, user, None)
    assert event.break_glass_action == BreakGlassAction.APPROVE_ENROLLMENT == APPROVE
    assert event.source_key == ""
    assert not AuthenticationEvent.objects.filter(event_type="mfa_enrollment_approved").exists()
    # The account itself is as it was: no password, status, or session change.
    assert User.objects.filter(pk=user.pk).values().get() == kept


def test_no_code_is_accepted_before_the_approval_and_the_first_code_is_still_required_after(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    _revoked(user)
    secret, number = _enrolment_request(user)

    assert _confirm(user, secret).outcome == MfaOutcome.UNAVAILABLE
    assert _approve_by_break_glass(user, number) == DONE
    wrong = services.confirm_mfa_enrollment(actor=signed_in(user), code="000000", source=SOURCE)

    assert wrong.outcome == MfaOutcome.REFUSED
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION
    assert not AuthenticationEvent.objects.filter(event_type=COMPLETED).exists()
    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED


def test_where_an_administrator_may_approve_the_command_refuses_and_that_administrator_does(
    account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    # Point 63: "the command revokes and that Administrator approves."
    user = account(Role.ADMINISTRATOR)
    other = verified(account(Role.ADMINISTRATOR))
    _revoked(user)
    _secret, number = _enrolment_request(user)
    before = _state()

    assert _approve_by_break_glass(user, number) == UNAVAILABLE

    assert _state() == before
    assert _reasons(caplog) == [(APPROVE, "normal_path_available")]
    # Nobody authorised a recovery that the command opened, so point 37 bars
    # nobody: the one other Administrator approves.
    assert selectors.open_recovery_authorizer_id(user.pk) is None
    assert _approve(number, other).outcome == MfaOutcome.ACCEPTED
    assert TotpDevice.objects.get(user=user).approved_by == other.user


@pytest.mark.parametrize("how", UNABLE)
def test_an_administrator_who_is_not_able_to_act_is_not_one_who_may_approve(
    how: str, account: AccountFactory
) -> None:
    user = account(Role.ADMINISTRATOR)
    _unable(account(Role.ADMINISTRATOR), how)
    _revoked(user)
    _secret, number = _enrolment_request(user)

    assert _approve_by_break_glass(user, number) == DONE


def test_whoever_authorised_the_recovery_is_not_an_administrator_who_may_approve(
    account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    # Point 37 is kept: the authoriser stays refused, and so does not make
    # the application's own path available.
    user = account(Role.ADMINISTRATOR)
    authoriser = verified(account(Role.ADMINISTRATOR))
    another = verified(account(Role.ADMINISTRATOR))
    assert _authorize(_asked(user), authoriser) == AUTHORIZED
    _secret, number = _enrolment_request(user)

    # While the third Administrator is able to act, that one approves.
    assert _approve_by_break_glass(user, number) == UNAVAILABLE
    assert _reasons(caplog) == [(APPROVE, "normal_path_available")]

    TotpDevice.objects.filter(user=another.user).delete()
    with pytest.raises(PermissionDenied):
        _approve(number, authoriser)
    assert _approve_by_break_glass(user, number) == DONE
    assert selectors.open_recovery_authorizer_id(user.pk) == authoriser.user.pk


def test_the_account_and_the_number_must_name_the_same_enrolment(
    account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    user, other = account(Role.ADMINISTRATOR), account(Role.ADMINISTRATOR)
    # Neither has anyone to approve: each lost its device.
    assert _revoke(user, _asked(user)) == DONE
    assert _revoke(other, _asked(other)) == DONE
    _secret, number = _enrolment_request(user)
    _other_secret, other_number = _enrolment_request(other)
    before = _state()

    assert _approve_by_break_glass(user, other_number) == UNAVAILABLE
    assert _approve_by_break_glass(other, number) == UNAVAILABLE
    assert _approve_by_break_glass(user, number + other_number + 1000) == UNAVAILABLE
    unknown = services.break_glass_approve_enrollment(
        email="test.nobody@caipo.test", request_number=number
    )

    assert unknown == UNAVAILABLE
    assert _state() == before
    assert _reasons(caplog) == [(APPROVE, "unknown_enrollment")] * 3 + [
        (APPROVE, "unknown_account")
    ]
    assert _approve_by_break_glass(user, number) == DONE


def test_a_number_that_was_replaced_names_nothing_and_the_new_one_is_approved(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    _revoked(user)
    _stale_secret, stale = _enrolment_request(user)
    secret, current = _enrolment_request(user)
    assert stale != current

    assert _approve_by_break_glass(user, stale) == UNAVAILABLE
    assert _approve_by_break_glass(user, current) == DONE
    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED


def test_an_enrolment_request_lapses_for_the_command_as_for_an_administrator(
    account: AccountFactory, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    user = account(Role.ADMINISTRATOR)
    _revoked(user)
    _secret, number = _enrolment_request(user)
    clock(timedelta(hours=72))
    before = _state()

    assert _approve_by_break_glass(user, number) == UNAVAILABLE

    assert _state() == before
    assert _reasons(caplog) == [(APPROVE, "unknown_enrollment")]


def test_no_cooling_off_is_added_to_the_approval(account: AccountFactory) -> None:
    # Owner decision: the 24 hours bind the revocation, which finalises the
    # recovery, and not the approval, as they do not bind an Administrator's.
    user = account(Role.ADMINISTRATOR)
    _revoked(user)
    _reset_password(user)
    _secret, number = _enrolment_request(user, NEW_PASSWORD)

    assert _approve_by_break_glass(user, number) == DONE


def test_an_enrolment_cannot_be_approved_twice(
    account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    user = account(Role.ADMINISTRATOR)
    _revoked(user)
    _secret, number = _enrolment_request(user)
    assert _approve_by_break_glass(user, number) == DONE
    before = _state()

    assert _approve_by_break_glass(user, number) == UNAVAILABLE

    assert _state() == before
    assert _reasons(caplog) == [(APPROVE, "unknown_enrollment")]
    assert [event.break_glass_action for event in _break_glass_events()] == [REVOKE, APPROVE]


def test_the_command_never_approves_for_an_account_that_is_not_an_administrator(
    account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    user = account(Role.ADMINISTRATOR, Role.REVIEWER)
    _revoked(user)
    _change_role(user, Role.ADMINISTRATOR, RoleEventType.REVOKED)
    # Still a request that awaits approval: a Reviewer needs one too.
    _secret, number = _enrolment_request(user)
    before = _state()

    assert _approve_by_break_glass(user, number) == UNAVAILABLE

    assert _state() == before
    assert _reasons(caplog) == [(APPROVE, "not_administrator")]


def test_the_command_does_not_approve_for_a_disabled_account(
    account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    user = account(Role.ADMINISTRATOR)
    _revoked(user)
    _secret, number = _enrolment_request(user)
    User.objects.filter(pk=user.pk).update(status=AccountStatus.DISABLED)

    assert _approve_by_break_glass(user, number) == UNAVAILABLE
    assert _reasons(caplog) == [(APPROVE, "not_eligible")]


def test_an_enrolment_that_follows_no_recovery_is_never_approved_by_the_command(
    user_with_roles: UserFactory, caplog: pytest.LogCaptureFixture
) -> None:
    # An Administrator who never had a device, and the only one.
    user = user_with_roles(Role.ADMINISTRATOR)
    user.set_password(PASSWORD)
    user.save()
    _secret, number = _enrolment_request(user)
    before = _state()

    assert _approve_by_break_glass(user, number) == UNAVAILABLE

    assert _state() == before
    assert _reasons(caplog) == [(APPROVE, "no_open_recovery")]


def test_the_only_administrator_who_replaces_the_device_by_choice_is_not_helped(
    account: AccountFactory, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    # ADR-0017, "Consequences". The recovery before it was completed.
    user = account(Role.ADMINISTRATOR)
    _revoked(user)
    secret, number = _enrolment_request(user)
    assert _approve_by_break_glass(user, number) == DONE
    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED
    assert not selectors.has_open_recovery(user.pk)
    clock(STEP)
    replaced = services.replace_mfa_device(
        actor=signed_in(user), password=PASSWORD, code=code_at(secret=secret), source=SOURCE
    )
    assert replaced.outcome == MfaOutcome.ACCEPTED
    again = selectors.enrollment_request_number_of(user)
    assert again is not None

    assert _approve_by_break_glass(user, again) == UNAVAILABLE
    assert _reasons(caplog) == [(APPROVE, "no_open_recovery")]


# --- Approving: the current enrolment of the open recovery ------------------------------


def test_an_approval_that_was_replaced_does_not_stand_in_the_way_of_the_request_that_replaced_it(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    _revoked(user)
    _first_secret, first = _enrolment_request(user)
    assert _approve_by_break_glass(user, first) == DONE
    # Asked again before the first code: the approval is lost with the secret.
    secret, second = _enrolment_request(user)
    assert TotpDevice.objects.get(user=user).approved_at is None

    assert _approve_by_break_glass(user, second) == DONE

    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED
    assert _events(user).count(COMPLETED) == 1


def test_an_enrolment_that_succeeded_and_was_replaced_does_not_poison_the_one_that_follows(
    account: AccountFactory, clock: Clock
) -> None:
    # Owner decision D3. The account lost its role while its recovery was
    # open, enrolled a device that nobody had to approve, got the role back,
    # and replaced that device: the request that now awaits approval is the
    # current one of the recovery, whatever succeeded before it.
    user = account(Role.ADMINISTRATOR)
    _revoked(user)
    _change_role(user, Role.ADMINISTRATOR, RoleEventType.REVOKED)
    _change_role(user, Role.READER, RoleEventType.GRANTED)
    started = services.start_mfa_enrollment(actor=signed_in(user), password=PASSWORD, source=SOURCE)
    assert started.provisioning is not None
    unapproved = base64.b32decode(started.provisioning.secret)
    assert _confirm(user, unapproved).outcome == MfaOutcome.ACCEPTED
    # A device nobody approved completes nothing.
    assert selectors.has_open_recovery(user.pk)
    _change_role(user, Role.ADMINISTRATOR, RoleEventType.GRANTED)
    clock(STEP)
    replaced = services.replace_mfa_device(
        actor=signed_in(user), password=PASSWORD, code=code_at(secret=unapproved), source=SOURCE
    )
    assert replaced.provisioning is not None
    secret = base64.b32decode(replaced.provisioning.secret)
    number = selectors.enrollment_request_number_of(user)
    assert number is not None
    assert "mfa_enrollment_succeeded" in _events(user)

    assert _approve_by_break_glass(user, number) == DONE

    clock(STEP)
    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED
    assert _events(user).count(COMPLETED) == 1
    assert not selectors.has_open_recovery(user.pk)


def test_a_pending_device_that_no_enrolment_of_the_recovery_accounts_for_is_refused(
    account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    user = account(Role.ADMINISTRATOR)
    _revoked(user)
    # A request in the table that no `mfa_enrollment_started` event records.
    device = _pending_device(user)
    before = _state()

    assert _approve_by_break_glass(user, device.pk) == UNAVAILABLE

    assert _state() == before
    assert _reasons(caplog) == [(APPROVE, "not_current_enrollment")]


@pytest.mark.parametrize(
    "ended_by", ["mfa_enrollment_rejected", "mfa_enrollment_succeeded", "mfa_disabled"]
)
def test_a_pending_device_whose_enrolment_the_record_says_has_ended_is_refused(
    ended_by: str, account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    user = account(Role.ADMINISTRATOR)
    _revoked(user)
    _secret, number = _enrolment_request(user)
    decided = ended_by == "mfa_enrollment_rejected"
    # The record says that enrolment is over; the row says it awaits approval.
    AuthenticationEvent.objects.create(
        event_type=ended_by,
        user=user,
        actor=supporting_account("test.seed@caipo.test") if decided else None,
        identifier_key="k",
        source_key="k",
    )

    assert _approve_by_break_glass(user, number) == UNAVAILABLE
    assert _reasons(caplog) == [(APPROVE, "not_current_enrollment")]


@pytest.mark.parametrize("opened_by", ["an Administrator", "the command"])
def test_an_enrolment_started_before_the_recovery_was_opened_is_not_of_that_recovery(
    opened_by: str, account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    user = account(Role.ADMINISTRATOR)
    _revoked(user)
    _secret, number = _enrolment_request(user)
    # A later opening that, impossibly, left the pending request in place.
    # Whoever is named as having authorised it is not able to act, so nothing
    # but the order of the two events stands between the request and an
    # approval.
    authoriser = supporting_account("test.seed@caipo.test")
    if opened_by == "an Administrator":
        opener = AuthenticationEvent.objects.create(
            event_type="mfa_recovery_authorized",
            user=user,
            actor=authoriser,
            identifier_key="k",
            source_key="k",
        )
        expected = OpenRecovery(opener.pk, authoriser.pk)
    else:
        opener = AuthenticationEvent.objects.create(
            event_type=BREAK_GLASS,
            user=user,
            identifier_key="k",
            source_key="",
            break_glass_action=REVOKE,
        )
        expected = OpenRecovery(opener.pk, None)

    recovery = selectors.open_recovery_of(user.pk)

    assert recovery == expected
    assert not selectors.pending_enrollment_follows(user.pk, recovery)
    assert _approve_by_break_glass(user, number) == UNAVAILABLE
    assert _reasons(caplog) == [(APPROVE, "not_current_enrollment")]
    assert TotpDevice.objects.get(user=user).state == TotpDeviceState.PENDING_APPROVAL


# --- Approving: faults ------------------------------------------------------------------


def test_an_approval_whose_event_cannot_be_written_changes_nothing(
    account: AccountFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = account(Role.ADMINISTRATOR)
    _revoked(user)
    _secret, number = _enrolment_request(user)
    before = _state()

    with monkeypatch.context() as patched:
        patched.setattr(services, "_record", _fail)
        with pytest.raises(RuntimeError, match="TEST fault"):
            _approve_by_break_glass(user, number)

    assert _state() == before
    assert TotpDevice.objects.get(user=user).state == TotpDeviceState.PENDING_APPROVAL
    assert _approve_by_break_glass(user, number) == DONE


def test_an_approval_whose_device_cannot_be_written_records_nothing(
    account: AccountFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = account(Role.ADMINISTRATOR)
    _revoked(user)
    _secret, number = _enrolment_request(user)
    before = _state()

    with monkeypatch.context() as patched:
        patched.setattr(TotpDevice, "save", _fail)
        with pytest.raises(RuntimeError, match="TEST fault"):
            _approve_by_break_glass(user, number)

    assert _state() == before
    assert [event.break_glass_action for event in _break_glass_events()] == [REVOKE]


# --- The recovery is completed, whichever way it was opened and approved (point 49) -----


@pytest.mark.parametrize("opened_by", ["an Administrator", "the command"])
@pytest.mark.parametrize("approved_by", ["an Administrator", "the command"])
def test_every_way_through_a_recovery_ends_in_one_completion(
    opened_by: str, approved_by: str, account: AccountFactory
) -> None:
    user = account(Role.ADMINISTRATOR)
    authoriser = approver = None
    if opened_by == "an Administrator":
        authoriser = verified(account(Role.ADMINISTRATOR))
        approver = verified(account(Role.ADMINISTRATOR))
        assert _authorize(_asked(user), authoriser) == AUTHORIZED
        opener = ("mfa_recovery_authorized", "")
    else:
        if approved_by == "an Administrator":
            approver = verified(account(Role.ADMINISTRATOR))
        _revoked(user)
        opener = (BREAK_GLASS, REVOKE)
    secret, number = _enrolment_request(user)
    if approved_by == "an Administrator":
        assert approver is not None
        assert _approve(number, approver).outcome == MfaOutcome.ACCEPTED
        approval = ("mfa_enrollment_approved", "")
    else:
        if approver is not None:
            # The Administrator who would have approved is no longer able to.
            TotpDevice.objects.filter(user=approver.user).delete()
        assert _approve_by_break_glass(user, number) == DONE
        approval = (BREAK_GLASS, APPROVE)

    assert selectors.has_open_recovery(user.pk)
    assert selectors.open_recovery_authorizer_id(user.pk) == (
        authoriser.user.pk if authoriser is not None else None
    )
    result = _confirm(user, secret)

    assert result.outcome == MfaOutcome.ACCEPTED
    assert not selectors.has_open_recovery(user.pk)
    assert selectors.open_recovery_of(user.pk) is None
    recorded = list(
        AuthenticationEvent.objects.filter(user=user)
        .order_by("id")
        .values_list("event_type", "break_glass_action")
    )
    assert recorded == [
        ("mfa_challenge_issued", ""),
        ("mfa_recovery_requested", ""),
        opener,
        ("mfa_enrollment_started", ""),
        approval,
        ("mfa_enrollment_succeeded", ""),
        (COMPLETED, ""),
    ]
    completed = AuthenticationEvent.objects.get(event_type=COMPLETED)
    assert (completed.user, completed.actor) == (user, None)
    # The new device is trusted, by its approval and its first code.
    assert result.context is not None
    assert selectors.can(result.context, Permission.ROLES_MANAGE)
    # A confirmation sent again completes nothing more.
    assert _confirm(user, secret).outcome == MfaOutcome.UNAVAILABLE
    assert _events(user).count(COMPLETED) == 1


def test_a_recovery_opened_by_the_command_stays_open_until_the_first_code(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    assert selectors.open_recovery_of(user.pk) is None
    number = _asked(user)
    assert not selectors.has_open_recovery(user.pk)

    assert _revoke(user, number) == DONE
    (opener,) = _break_glass_events(user)

    assert selectors.open_recovery_of(user.pk) == OpenRecovery(opener.pk, None)
    assert selectors.has_open_recovery(user.pk)
    assert selectors.open_recovery_authorizer_id(user.pk) is None
    secret, enrolment = _enrolment_request(user)
    assert _approve_by_break_glass(user, enrolment) == DONE
    # The approval opens nothing and closes nothing.
    assert selectors.open_recovery_of(user.pk) == OpenRecovery(opener.pk, None)
    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED
    assert selectors.open_recovery_of(user.pk) is None


def test_an_approval_event_of_the_command_is_not_an_opener(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    AuthenticationEvent.objects.create(
        event_type=BREAK_GLASS,
        user=user,
        identifier_key="k",
        source_key="",
        break_glass_action=APPROVE,
    )

    assert selectors.open_recovery_of(user.pk) is None
    assert not selectors.has_open_recovery(user.pk)


def test_the_most_recent_opener_decides_whoever_or_whatever_it_was(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    authoriser = account(Role.ADMINISTRATOR)

    def event(event_type: str, **values: Any) -> AuthenticationEvent:
        values.setdefault("source_key", "" if event_type == BREAK_GLASS else "k")
        return AuthenticationEvent.objects.create(
            event_type=event_type, user=user, identifier_key="k", **values
        )

    event("mfa_recovery_authorized", actor=authoriser)
    assert selectors.open_recovery_authorizer_id(user.pk) == authoriser.pk
    # A later revocation by the command supersedes it: nobody is barred.
    by_command = event(BREAK_GLASS, break_glass_action=REVOKE)
    assert selectors.open_recovery_of(user.pk) == OpenRecovery(by_command.pk, None)
    assert selectors.open_recovery_authorizer_id(user.pk) is None
    # And a later authorisation supersedes that.
    again = event("mfa_recovery_authorized", actor=authoriser)
    assert selectors.open_recovery_of(user.pk) == OpenRecovery(again.pk, authoriser.pk)
    event(COMPLETED)
    assert selectors.open_recovery_of(user.pk) is None
    # A completion closes what was opened before it and nothing after it.
    later = event(BREAK_GLASS, break_glass_action=REVOKE)
    assert selectors.open_recovery_of(user.pk) == OpenRecovery(later.pk, None)


def test_a_recovery_of_one_account_is_not_a_recovery_of_another(
    account: AccountFactory,
) -> None:
    user, other = account(Role.ADMINISTRATOR), account(Role.ADMINISTRATOR)
    _revoked(user)

    assert selectors.has_open_recovery(user.pk)
    assert not selectors.has_open_recovery(other.pk)


def test_a_device_that_nobody_approved_does_not_complete_a_recovery_the_command_opened(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    _revoked(user)
    _change_role(user, Role.ADMINISTRATOR, RoleEventType.REVOKED)
    _change_role(user, Role.READER, RoleEventType.GRANTED)
    started = services.start_mfa_enrollment(actor=signed_in(user), password=PASSWORD, source=SOURCE)
    assert started.provisioning is not None

    result = _confirm(user, base64.b32decode(started.provisioning.secret))

    assert result.outcome == MfaOutcome.ACCEPTED
    assert not AuthenticationEvent.objects.filter(event_type=COMPLETED).exists()
    assert selectors.has_open_recovery(user.pk)


def test_a_later_recovery_of_the_same_account_is_recovered_again(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    for round_number in (1, 2):
        _revoked(user)
        secret, number = _enrolment_request(user)
        assert _approve_by_break_glass(user, number) == DONE
        assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED
        assert _events(user).count(COMPLETED) == round_number
        assert User.objects.get(pk=user.pk).session_epoch == round_number
        assert not selectors.has_open_recovery(user.pk)
    assert [event.break_glass_action for event in _break_glass_events(user)] == [
        REVOKE,
        APPROVE,
        REVOKE,
        APPROVE,
    ]


# --- Locks (the order every other operation takes them in) ------------------------------


def _locks(statements: list[str]) -> list[str]:
    steps = []
    for statement in statements:
        advisory = re.search(r"pg_advisory_xact_lock\((\d+), (\d+)\)", statement)
        if "LOCK TABLE accounts_roleevent" in statement:
            steps.append("role events")
        elif advisory:
            steps.append(f"advisory {advisory.group(1)}:{advisory.group(2)}")
        elif "FOR UPDATE" in statement:
            table = re.search(r'FROM "accounts_(\w+)"', statement)
            assert table is not None
            steps.append(f"{table.group(1)} row")
    return steps


def test_a_revocation_takes_its_locks_in_the_established_order(account: AccountFactory) -> None:
    administrators = [account(Role.ADMINISTRATOR) for _ in range(3)]
    _unable(administrators[0], "no device")
    _unable(administrators[2], "untrusted device")
    # Not Administrators on record and active: their locks are not taken.
    reviewer = account(Role.REVIEWER)
    disabled = account(Role.ADMINISTRATOR)
    _unable(disabled, "disabled")
    user = account(Role.ADMINISTRATOR)
    number = _asked(user)
    identifier = int(services._key("identifier", user.email)[:8], 16) >> 1

    with CaptureQueriesContext(connection) as queries:
        assert _revoke(user, number) == DONE

    held = sorted([*(administrator.pk for administrator in administrators), user.pk])
    assert _locks([query["sql"] for query in queries.captured_queries]) == [
        "role events",
        f"advisory 2:{identifier}",
        *(f"advisory 3:{user_id}" for user_id in held),
        "user row",
        "mfarecoveryrequest row",
    ]
    assert reviewer.pk not in held
    assert disabled.pk not in held


def test_an_approval_takes_its_locks_in_the_established_order(account: AccountFactory) -> None:
    # The account's identifier is below one Administrator's and above another's.
    below = account(Role.ADMINISTRATOR)
    user = account(Role.ADMINISTRATOR)
    above = account(Role.ADMINISTRATOR)
    _unable(below, "no device")
    _unable(above, "no device")
    _revoked(user)
    _secret, number = _enrolment_request(user)

    with CaptureQueriesContext(connection) as queries:
        assert _approve_by_break_glass(user, number) == DONE

    assert below.pk < user.pk < above.pk
    assert _locks([query["sql"] for query in queries.captured_queries]) == [
        "role events",
        f"advisory 3:{below.pk}",
        f"advisory 3:{user.pk}",
        f"advisory 3:{above.pk}",
        "user row",
        "totpdevice row",
    ]


def test_an_action_that_names_no_account_takes_no_lock_but_the_first(
    account: AccountFactory,
) -> None:
    account(Role.ADMINISTRATOR)

    with CaptureQueriesContext(connection) as queries:
        services.break_glass_revoke_device(email="test.nobody@caipo.test", request_number=1)

    assert _locks([query["sql"] for query in queries.captured_queries]) == ["role events"]


# --- Only the command, and nothing a request can reach (point 60) ----------------------

SERVICES = ("break_glass_revoke_device", "break_glass_approve_enrollment")


def _sources() -> dict[str, str]:
    package_root = Path(inspect.getfile(caipo)).parent
    return {
        str(path.relative_to(package_root)): path.read_text()
        for path in package_root.rglob("*.py")
        if "tests" not in path.parts and "migrations" not in path.parts
    }


def test_only_the_command_calls_the_two_break_glass_services() -> None:
    for name in SERVICES:
        callers = sorted(path for path, text in _sources().items() if name in text)

        assert callers == [
            "accounts/management/commands/recover_mfa_break_glass.py",
            # Where it is defined.
            "accounts/services.py",
        ]
    assert not [
        path
        for path in _sources()
        if path.startswith(("web/", "config/", "core/")) and "break_glass" in _sources()[path]
    ]


def test_only_the_two_services_record_a_break_glass_event() -> None:
    writers = sorted(
        path for path, text in _sources().items() if "MFA_RECOVERY_BREAK_GLASS" in text
    )

    # The model defines it and the selector reads it.
    assert writers == ["accounts/models.py", "accounts/selectors.py", "accounts/services.py"]
    assert ".create(" not in inspect.getsource(selectors.open_recovery_of)
    source = inspect.getsource(services)
    assert source.count("AuthenticationEventType.MFA_RECOVERY_BREAK_GLASS") == 2
    assert source.count("break_glass_action=action") == 2
    for name, action in zip(SERVICES, ("REVOKE_DEVICE", "APPROVE_ENROLLMENT"), strict=True):
        service = inspect.getsource(getattr(services, name))
        assert service.count("AuthenticationEventType.MFA_RECOVERY_BREAK_GLASS") == 1
        assert f"action = BreakGlassAction.{action}" in service


@pytest.mark.parametrize("name", SERVICES)
def test_a_break_glass_service_takes_no_actor_no_source_and_no_secret(name: str) -> None:
    service = getattr(services, name)

    assert set(inspect.signature(service).parameters) == {"email", "request_number"}
    body = inspect.getsource(service).split('"""')[2]
    for forbidden in (
        "AuthenticationContext",
        "set_password",
        "check_password",
        "totp.",
        "secret",
        "actor=",
        '_key("source"',
        "TotpDevice.objects.create",
        "TotpDeviceState.ACTIVE",
        "MFA_RECOVERY_AUTHORIZED",
        "MFA_ENROLLMENT_APPROVED",
    ):
        assert forbidden not in body, forbidden


def test_no_permission_and_no_role_reaches_break_glass() -> None:
    assert not [permission for permission in Permission if "break" in permission.value]
    assert len(Permission) == 10
    # The policy's code, without its comments, which do name the command.
    policy = "\n".join(line.split("#")[0] for line in inspect.getsource(authorization).splitlines())
    assert "break" not in policy.lower()


def test_the_services_that_an_administrator_calls_never_call_the_break_glass_services() -> None:
    for service in (
        services.authorize_mfa_recovery,
        services.reject_mfa_recovery,
        services.approve_mfa_enrollment,
        services.reject_mfa_enrollment,
        services._decide_enrollment,
        services.request_mfa_recovery,
        services.confirm_mfa_enrollment,
    ):
        body = inspect.getsource(service).split('"""')[-1]
        assert "break_glass" not in body, service.__name__


def test_an_administrator_cannot_do_through_the_application_what_the_command_does(
    account: AccountFactory,
) -> None:
    # The only Administrator, still holding a verified sign-in, and its own
    # request: the application's path refuses both decisions.
    user = account(Role.ADMINISTRATOR)
    context = verified(user)
    number = _asked(user)

    with pytest.raises(PermissionDenied):
        _authorize(number, context)

    assert _break_glass_events() == []
    assert TotpDevice.objects.filter(user=user, state=TotpDeviceState.ACTIVE).exists()


# --- What is kept, and what is not (points 62 and 88) -----------------------------------


def test_no_event_and_no_log_line_of_break_glass_holds_an_address_or_a_secret(
    account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    user = account(Role.ADMINISTRATOR)
    token = _reset_token(user)
    number = _asked(user)
    challenge = _challenge(user)
    stored_before = User.objects.get(pk=user.pk)
    caplog.clear()

    assert _revoke(user, number + 1) == UNAVAILABLE
    assert _revoke(user, number) == DONE
    secret, enrolment = _enrolment_request(user)
    assert _approve_by_break_glass(user, enrolment) == DONE

    lines = logged(
        record for record in caplog.records if "break_glass" in str(record.__dict__.get("event"))
    )
    kept = [
        str(event) for event in AuthenticationEvent.objects.filter(event_type=BREAK_GLASS).values()
    ]
    assert len(kept) == 2
    for text in (lines, " ".join(kept)):
        for forbidden in (
            user.email,
            PASSWORD,
            stored_before.password,
            token,
            challenge,
            base64.b32encode(secret).decode(),
            stored_before.get_session_auth_hash(),
            "otpauth",
        ):
            assert forbidden not in text
    assert "break_glass_unavailable" in lines
    assert f"'user_id': {user.pk}" in lines


def test_a_refusal_is_logged_by_action_and_reason_only(
    account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    user = account(Role.REVIEWER)
    number = _asked(user)
    caplog.clear()

    assert _revoke(user, number) == UNAVAILABLE

    (record,) = [
        record
        for record in caplog.records
        if record.__dict__.get("event") == "mfa_recovery.break_glass_unavailable"
    ]
    extra = {
        name: value
        for name, value in vars(record).items()
        if name not in vars(logging.makeLogRecord({})) and name != "message"
    }
    assert extra == {
        "event": "mfa_recovery.break_glass_unavailable",
        "action": REVOKE,
        "reason": "not_administrator",
    }
    assert record.levelno == logging.WARNING
