"""Second-factor operations made at the same time, on separate database connections.

These tests commit their data, because other connections must see it, and the
database is emptied after each of them.
"""

import base64
import threading
from collections.abc import Callable

import pytest
from django.conf import LazySettings
from django.db import connections

from caipo.accounts import selectors, services
from caipo.accounts.models import AuthenticationEvent, MfaChallenge, TotpDevice, User
from caipo.accounts.selectors import MfaState, Role
from caipo.accounts.services import MfaOutcome, MfaResult, SignInOutcome
from caipo.accounts.tests.fixtures import (
    UserFactory,
    approving_administrator,
    code_at,
    enrolled_device,
    signed_in,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db(transaction=True)]

# Visibly synthetic fixture values.
PASSWORD = "TEST-passphrase-for-fixtures-only"
SOURCE = "203.0.113.10"
WAIT_SECONDS = 30


def _at_the_same_time(*operations: Callable[[], MfaResult]) -> list[MfaResult]:
    """Run the operations together, each on its own connection, and return their results."""
    barrier = threading.Barrier(len(operations))
    results: list[MfaResult | BaseException | None] = [None] * len(operations)

    def run(index: int, operation: Callable[[], MfaResult]) -> None:
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
    finished = [result for result in results if isinstance(result, MfaResult)]
    assert len(finished) == len(operations), results
    return finished


def _outcomes(results: list[MfaResult]) -> list[str]:
    return sorted(result.outcome.value for result in results)


def _events() -> list[str]:
    return list(AuthenticationEvent.objects.order_by("id").values_list("event_type", flat=True))


def _account(user_with_roles: UserFactory, role: Role = Role.ADMINISTRATOR) -> User:
    user = user_with_roles(role)
    user.set_password(PASSWORD)
    user.save()
    return user


def _challenge(user: User) -> str:
    result = services.sign_in(email=user.email, password=PASSWORD, source=SOURCE)
    assert result.outcome == SignInOutcome.SECOND_FACTOR_REQUIRED
    assert result.challenge is not None
    return result.challenge


def test_an_enrolment_confirmed_twice_at_once_is_activated_once(
    user_with_roles: UserFactory,
) -> None:
    # A role that needs no approval: this is about the code, not the approval.
    user = _account(user_with_roles, Role.READER)
    started = services.start_mfa_enrollment(actor=signed_in(user), password=PASSWORD, source=SOURCE)
    assert started.provisioning is not None
    code = code_at(secret=base64.b32decode(started.provisioning.secret))

    def confirm() -> MfaResult:
        return services.confirm_mfa_enrollment(actor=signed_in(user), code=code, source=SOURCE)

    results = _at_the_same_time(confirm, confirm, confirm, confirm)

    assert _outcomes(results) == ["accepted", "unavailable", "unavailable", "unavailable"]
    assert TotpDevice.objects.count() == 1
    assert selectors.mfa_state_of(user) == MfaState.ACTIVE
    assert _events().count("mfa_enrollment_succeeded") == 1
    (accepted,) = [result for result in results if result.context is not None]
    assert accepted.context is not None
    assert accepted.context.mfa_device_id == TotpDevice.objects.get().pk


def test_enrolments_started_at_once_leave_one_pending_device(
    user_with_roles: UserFactory,
) -> None:
    # A role that needs no approval: this is about the code, not the approval.
    user = _account(user_with_roles, Role.READER)

    def start() -> MfaResult:
        return services.start_mfa_enrollment(
            actor=signed_in(user), password=PASSWORD, source=SOURCE
        )

    results = _at_the_same_time(start, start, start)

    assert _outcomes(results) == ["accepted"] * 3
    assert TotpDevice.objects.count() == 1
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION
    # Only the secret issued last is the pending one.
    secrets = [
        base64.b32decode(result.provisioning.secret)
        for result in results
        if result.provisioning is not None
    ]
    confirmations = [
        services.confirm_mfa_enrollment(
            actor=signed_in(user), code=code_at(secret=secret), source=SOURCE
        ).outcome
        for secret in secrets
    ]
    assert confirmations.count(MfaOutcome.ACCEPTED) == 1


def test_a_start_and_a_confirmation_at_once_never_activate_an_unproven_secret(
    user_with_roles: UserFactory,
) -> None:
    # A role that needs no approval: this is about the code, not the approval.
    user = _account(user_with_roles, Role.READER)
    started = services.start_mfa_enrollment(actor=signed_in(user), password=PASSWORD, source=SOURCE)
    assert started.provisioning is not None
    code = code_at(secret=base64.b32decode(started.provisioning.secret))

    confirmed, restarted = _at_the_same_time(
        lambda: services.confirm_mfa_enrollment(actor=signed_in(user), code=code, source=SOURCE),
        lambda: services.start_mfa_enrollment(
            actor=signed_in(user), password=PASSWORD, source=SOURCE
        ),
    )

    device = TotpDevice.objects.get()
    if confirmed.outcome == MfaOutcome.ACCEPTED:
        # The confirmation won: the restart found an active device and did nothing.
        assert restarted.outcome == MfaOutcome.UNAVAILABLE
        assert device.state == "active"
    else:
        # The restart won: the old code proves nothing about the new secret.
        assert (confirmed.outcome, restarted.outcome) == (MfaOutcome.REFUSED, MfaOutcome.ACCEPTED)
        assert device.state == "pending_verification"
        assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION


def test_one_challenge_used_twice_at_once_signs_in_once(user_with_roles: UserFactory) -> None:
    user = _account(user_with_roles)
    enrolled_device(user)
    challenge = _challenge(user)
    code = code_at()

    def verify() -> MfaResult:
        return services.verify_second_factor(challenge=challenge, code=code, source=SOURCE)

    results = _at_the_same_time(verify, verify, verify, verify)

    assert _outcomes(results) == ["accepted", "refused", "refused", "refused"]
    assert _events().count("login_success") == 1
    assert _events().count("mfa_verification_succeeded") == 1
    assert not MfaChallenge.objects.exists()


def test_wrong_codes_sent_at_once_cannot_exceed_the_limit(
    user_with_roles: UserFactory, settings: LazySettings
) -> None:
    user = _account(user_with_roles)
    enrolled_device(user)
    challenge = _challenge(user)
    current = {code_at()}
    wrong = next(code for code in ("000000", "111111", "222222") if code not in current)

    def guess() -> MfaResult:
        return services.verify_second_factor(challenge=challenge, code=wrong, source=SOURCE)

    results = _at_the_same_time(*([guess] * 12))

    limit = settings.MFA_THROTTLE_FAILURES
    assert _outcomes(results) == ["refused"] * limit + ["throttled"] * (12 - limit)
    assert _events().count("mfa_verification_failed") == limit


def test_disabling_twice_at_once_removes_the_device_once(user_with_roles: UserFactory) -> None:
    user = _account(user_with_roles)
    device = enrolled_device(user)
    actor = selectors.authentication_context(user, verified_device_id=device.pk)
    assert actor is not None
    code = code_at()

    def disable() -> MfaResult:
        return services.disable_mfa(actor=actor, password=PASSWORD, code=code, source=SOURCE)

    results = _at_the_same_time(disable, disable)

    assert _outcomes(results) == ["accepted", "unavailable"]
    assert not TotpDevice.objects.exists()
    assert _events().count("mfa_disabled") == 1


# --- The approval of an enrolment ------------------------------------------------


def _request(user: User) -> tuple[str, int]:
    """Start an enrolment that needs approval; return a current code for it and its number."""
    started = services.start_mfa_enrollment(actor=signed_in(user), password=PASSWORD, source=SOURCE)
    assert started.provisioning is not None
    number = selectors.enrollment_request_number_of(user)
    assert number is not None
    return code_at(secret=base64.b32decode(started.provisioning.secret)), number


def test_a_request_approved_several_times_at_once_is_approved_once(
    user_with_roles: UserFactory,
) -> None:
    user = _account(user_with_roles, Role.REVIEWER)
    _, number = _request(user)
    approver = approving_administrator()

    def approve() -> MfaResult:
        return services.approve_mfa_enrollment(actor=approver, request_number=number, source=SOURCE)

    results = _at_the_same_time(approve, approve, approve, approve)

    assert _outcomes(results) == ["accepted", "unavailable", "unavailable", "unavailable"]
    assert _events().count("mfa_enrollment_approved") == 1
    device = TotpDevice.objects.get(user=user)
    assert (device.state, device.approved_by) == ("pending_verification", approver.user)


def test_an_approval_and_a_rejection_at_once_leave_one_decision(
    user_with_roles: UserFactory,
) -> None:
    user = _account(user_with_roles, Role.ADMINISTRATOR)
    _, number = _request(user)
    approver = approving_administrator()

    approved, rejected = _at_the_same_time(
        lambda: services.approve_mfa_enrollment(
            actor=approver, request_number=number, source=SOURCE
        ),
        lambda: services.reject_mfa_enrollment(
            actor=approver, request_number=number, source=SOURCE
        ),
    )

    decisions = [event for event in _events() if event != "mfa_enrollment_started"]
    if approved.outcome == MfaOutcome.ACCEPTED:
        assert rejected.outcome == MfaOutcome.UNAVAILABLE
        assert decisions == ["mfa_enrollment_approved"]
        assert TotpDevice.objects.get(user=user).state == "pending_verification"
    else:
        assert (approved.outcome, rejected.outcome) == (
            MfaOutcome.UNAVAILABLE,
            MfaOutcome.ACCEPTED,
        )
        assert decisions == ["mfa_enrollment_rejected"]
        assert not TotpDevice.objects.filter(user=user).exists()


def test_an_approval_and_a_new_request_at_once_never_leave_an_approved_secret_nobody_asked_about(
    user_with_roles: UserFactory,
) -> None:
    """Whoever knows the password and asks again, as the approval lands, gains nothing."""
    user = _account(user_with_roles, Role.ADMINISTRATOR)
    _, number = _request(user)
    approver = approving_administrator()

    approved, restarted = _at_the_same_time(
        lambda: services.approve_mfa_enrollment(
            actor=approver, request_number=number, source=SOURCE
        ),
        lambda: services.start_mfa_enrollment(
            actor=signed_in(user), password=PASSWORD, source=SOURCE
        ),
    )

    # Whichever came first, the new request stands, and it is not approved.
    assert restarted.outcome == MfaOutcome.ACCEPTED
    assert approved.outcome in {MfaOutcome.ACCEPTED, MfaOutcome.UNAVAILABLE}
    device = TotpDevice.objects.get(user=user)
    assert device.pk != number
    assert device.state == "pending_approval"
    assert (device.approved_at, device.approved_by) == (None, None)
    assert selectors.mfa_state_of(user) == MfaState.PENDING_APPROVAL
    assert restarted.provisioning is not None
    code = code_at(secret=base64.b32decode(restarted.provisioning.secret))
    confirmation = services.confirm_mfa_enrollment(actor=signed_in(user), code=code, source=SOURCE)
    assert confirmation.outcome == MfaOutcome.UNAVAILABLE


def test_a_code_sent_as_the_approval_lands_activates_only_an_approved_device(
    user_with_roles: UserFactory,
) -> None:
    user = _account(user_with_roles, Role.REVIEWER)
    code, number = _request(user)
    approver = approving_administrator()

    approved, confirmed = _at_the_same_time(
        lambda: services.approve_mfa_enrollment(
            actor=approver, request_number=number, source=SOURCE
        ),
        lambda: services.confirm_mfa_enrollment(actor=signed_in(user), code=code, source=SOURCE),
    )

    assert approved.outcome == MfaOutcome.ACCEPTED
    device = TotpDevice.objects.get(user=user)
    assert device.approved_by == approver.user
    if confirmed.outcome == MfaOutcome.ACCEPTED:
        assert device.state == "active"
    else:
        # The code arrived first, was not examined, and changed nothing.
        assert confirmed.outcome == MfaOutcome.UNAVAILABLE
        assert device.state == "pending_verification"
        assert "mfa_verification_failed" not in _events()


def test_a_replacement_made_twice_at_once_is_made_once(user_with_roles: UserFactory) -> None:
    user = _account(user_with_roles, Role.ADMINISTRATOR)
    device = enrolled_device(user)
    actor = selectors.authentication_context(user, verified_device_id=device.pk)
    assert actor is not None
    code = code_at()

    def replace() -> MfaResult:
        return services.replace_mfa_device(actor=actor, password=PASSWORD, code=code, source=SOURCE)

    results = _at_the_same_time(replace, replace)

    assert _outcomes(results) == ["accepted", "unavailable"]
    assert _events().count("mfa_device_replaced") == 1
    assert _events().count("mfa_enrollment_started") == 1
    new = TotpDevice.objects.get(user=user)
    assert (new.state, new.approved_at) == ("pending_approval", None)
    assert new.pk != device.pk
