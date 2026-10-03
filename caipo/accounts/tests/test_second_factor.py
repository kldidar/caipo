"""The second factor through the services: enrolment, sign-in, throttling, and disabling.

No HTTP is involved, and nothing stands in for TOTP: secrets are issued by the
enrolment service, and codes are computed from them as an authenticator
application would.
"""

import base64
import inspect
import logging
import re
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest
from django.conf import LazySettings
from django.conf import settings as django_settings
from django.core.exceptions import PermissionDenied
from django.utils import timezone

import caipo
from caipo.accounts import selectors, services
from caipo.accounts.models import (
    AuthenticationEvent,
    MfaChallenge,
    RoleEvent,
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
from caipo.accounts.services import MfaOutcome, SignInOutcome
from caipo.accounts.tests.fixtures import (
    TEST_TOTP_SECRET,
    Clock,
    UserFactory,
    approving_administrator,
    code_at,
    enrolled_device,
    logged,
    signed_in,
    verified,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db]

type AccountFactory = Callable[..., User]

# Visibly synthetic fixture values.
PASSWORD = "TEST-passphrase-for-fixtures-only"
WRONG = "TEST-wrong-passphrase"
SOURCE = "203.0.113.10"
WRONG_CODE = "000000"

ACCEPTED = MfaOutcome.ACCEPTED
REFUSED = MfaOutcome.REFUSED
THROTTLED = MfaOutcome.THROTTLED
UNAVAILABLE = MfaOutcome.UNAVAILABLE

STEP = timedelta(seconds=30)
ADMINISTRATIVE = {
    Permission.ROLES_MANAGE,
    Permission.ACCOUNTS_CREATE,
    Permission.ACCOUNTS_DEACTIVATE,
    Permission.ACCOUNTS_ENABLE,
    Permission.MFA_ENROLLMENT_APPROVE,
}
OWN_MFA = Permission.MFA_MANAGE_OWN

PACKAGE_ROOT = Path(inspect.getfile(caipo)).parent


@pytest.fixture
def account(user_with_roles: UserFactory) -> AccountFactory:
    """Return a factory for synthetic users with the given roles and a known password."""

    def make(*roles: Role) -> User:
        user = user_with_roles(*roles)
        user.set_password(PASSWORD)
        user.save()
        return user

    return make


def _events(user: User | None = None) -> list[str]:
    events = AuthenticationEvent.objects.order_by("id")
    if user is not None:
        events = events.filter(user=user)
    return list(events.values_list("event_type", flat=True))


def _wrong_code(secret: bytes = TEST_TOTP_SECRET) -> str:
    """Return a code that is certainly not right for the secret at the moment."""
    now = timezone.now()
    right = {code_at(now + offset * STEP, secret=secret) for offset in range(-10, 11)}
    return next(code for code in ("000000", "111111", "222222", "333333") if code not in right)


def _start(user: User, password: str = PASSWORD, *, approved: bool = True) -> services.MfaResult:
    """Start an enrolment and, where one is needed, have an Administrator approve it.

    What these tests are about begins where the first code is awaited. The
    approval itself, and everything an unapproved enrolment must not do, is
    tested in test_second_factor_approval.py.
    """
    result = services.start_mfa_enrollment(actor=signed_in(user), password=password, source=SOURCE)
    number = selectors.enrollment_request_number_of(user)
    if approved and result.outcome == ACCEPTED and number is not None:
        approval = services.approve_mfa_enrollment(
            actor=approving_administrator(), request_number=number, source=SOURCE
        )
        assert approval.outcome == ACCEPTED
    return result


def _secret_of(result: services.MfaResult) -> bytes:
    assert result.provisioning is not None
    return base64.b32decode(result.provisioning.secret)


def _confirm(user: User, code: str) -> services.MfaResult:
    return services.confirm_mfa_enrollment(actor=signed_in(user), code=code, source=SOURCE)


def _enrol(user: User) -> tuple[AuthenticationContext, bytes]:
    """Enrol the account through the services and return its context and secret."""
    secret = _secret_of(_start(user))
    result = _confirm(user, code_at(secret=secret))
    assert result.outcome == ACCEPTED
    assert result.context is not None
    return result.context, secret


def _challenge(user: User) -> str:
    result = services.sign_in(email=user.email, password=PASSWORD, source=SOURCE)
    assert result.outcome == SignInOutcome.SECOND_FACTOR_REQUIRED
    assert result.challenge is not None
    return result.challenge


def _verify(challenge: str, code: str) -> services.MfaResult:
    return services.verify_second_factor(challenge=challenge, code=code, source=SOURCE)


# --- Starting an enrolment ----------------------------------------------------


def test_an_account_starts_not_enrolled(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)

    assert selectors.mfa_state_of(user) == MfaState.NOT_ENROLLED
    assert not TotpDevice.objects.exists()


def test_starting_issues_a_secret_and_leaves_the_enrolment_pending(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)

    result = _start(user)

    assert result.outcome == ACCEPTED
    assert result.context is None
    assert result.provisioning is not None
    assert len(_secret_of(result)) == 20
    device = TotpDevice.objects.get(user=user)
    assert (device.user, device.state) == (user, TotpDeviceState.PENDING_VERIFICATION)
    assert (device.confirmed_at, device.last_used_step) == (None, None)
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION
    assert _events() == ["mfa_enrollment_started", "mfa_enrollment_approved"]


def test_the_provisioning_uri_names_the_issuer_and_the_account_only(
    account: AccountFactory,
) -> None:
    user = account(Role.READER)

    provisioning = _start(user).provisioning

    assert provisioning is not None
    assert provisioning.uri == (
        f"otpauth://totp/CAIPO:{user.email.replace('@', '%40')}"
        f"?digits=6&secret={provisioning.secret}&algorithm=SHA1&issuer=CAIPO&period=30"
    )
    assert PASSWORD not in provisioning.uri


def test_the_secret_is_generated_by_the_server_and_never_taken_from_the_caller(
    account: AccountFactory,
) -> None:
    user = account(Role.READER)

    secrets = {_secret_of(_start(user)) for _ in range(3)}

    assert len(secrets) == 3
    for operation in (services.start_mfa_enrollment, services.confirm_mfa_enrollment):
        assert set(inspect.signature(operation).parameters) <= {
            "actor",
            "password",
            "code",
            "source",
        }
    with pytest.raises(TypeError):
        # The ignore below: a caller supplying the secret is the case under test.
        services.start_mfa_enrollment(  # type: ignore[call-arg]
            actor=signed_in(user), password=PASSWORD, source=SOURCE, secret=TEST_TOTP_SECRET
        )


def test_starting_requires_the_password_again(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)

    result = _start(user, WRONG)

    assert result.outcome == REFUSED
    assert result.provisioning is None
    assert not TotpDevice.objects.exists()
    assert selectors.mfa_state_of(user) == MfaState.NOT_ENROLLED
    assert _events() == ["password_confirmation_failed"]


@pytest.mark.parametrize("password", ["", " ", PASSWORD + " ", PASSWORD.lower()])
def test_a_near_miss_of_the_password_is_refused(account: AccountFactory, password: str) -> None:
    assert _start(account(Role.READER), password).outcome == REFUSED
    assert not TotpDevice.objects.exists()


def test_the_password_of_another_account_does_not_start_an_enrolment(
    account: AccountFactory, user_with_roles: UserFactory
) -> None:
    user = account(Role.READER)
    other = user_with_roles(Role.READER)
    other.set_password("TEST-another-passphrase-entirely")
    other.save()

    result = services.start_mfa_enrollment(
        actor=signed_in(user), password="TEST-another-passphrase-entirely", source=SOURCE
    )

    assert result.outcome == REFUSED


def test_starting_again_replaces_the_pending_secret(account: AccountFactory) -> None:
    user = account(Role.READER)
    first = _secret_of(_start(user))

    second = _secret_of(_start(user))

    assert first != second
    assert TotpDevice.objects.count() == 1
    assert _confirm(user, code_at(secret=first)).outcome == REFUSED
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION
    assert _confirm(user, code_at(secret=second)).outcome == ACCEPTED


def test_starting_is_refused_while_a_second_factor_is_active(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    actor, _ = _enrol(user)
    stored = TotpDevice.objects.values().get(user=user)

    for acting in (actor, signed_in(user)):
        result = services.start_mfa_enrollment(actor=acting, password=PASSWORD, source=SOURCE)
        assert result.outcome == UNAVAILABLE
        assert result.provisioning is None

    assert TotpDevice.objects.values().get(user=user) == stored
    assert selectors.mfa_state_of(user) == MfaState.ACTIVE


@pytest.mark.parametrize("operation", ["start", "confirm", "disable"])
def test_an_account_without_a_role_cannot_manage_a_second_factor(
    account: AccountFactory, operation: str
) -> None:
    actor = signed_in(account())

    with pytest.raises(PermissionDenied):
        _operations(actor)[operation]()

    assert not TotpDevice.objects.exists()
    assert _events() == []


@pytest.mark.parametrize("operation", ["start", "confirm", "disable"])
def test_a_deactivated_account_cannot_manage_a_second_factor(
    account: AccountFactory, operation: str
) -> None:
    user = account(Role.ADMINISTRATOR)
    User.objects.filter(pk=user.pk).update(status="disabled")

    with pytest.raises(PermissionDenied):
        _operations(signed_in(user))[operation]()

    assert not TotpDevice.objects.exists()


@pytest.mark.parametrize("operation", ["start", "confirm", "disable"])
@pytest.mark.parametrize("who", ["nobody", "bare-account"])
def test_no_operation_runs_without_an_authentication_context(
    account: AccountFactory, operation: str, who: str
) -> None:
    actor = None if who == "nobody" else account(Role.ADMINISTRATOR)

    with pytest.raises(PermissionDenied):
        # The ignore below: an actor that is not a context is the case under test.
        _operations(actor)[operation]()  # type: ignore[arg-type]

    assert not TotpDevice.objects.exists()
    assert _events() == []


def _operations(actor: AuthenticationContext) -> dict[str, Callable[[], object]]:
    return {
        "start": lambda: services.start_mfa_enrollment(
            actor=actor, password=PASSWORD, source=SOURCE
        ),
        "confirm": lambda: services.confirm_mfa_enrollment(
            actor=actor, code=WRONG_CODE, source=SOURCE
        ),
        "disable": lambda: services.disable_mfa(
            actor=actor, password=PASSWORD, code=WRONG_CODE, source=SOURCE
        ),
    }


# --- A pending enrolment grants nothing -----------------------------------------


@pytest.mark.parametrize("role", [Role.REVIEWER, Role.ADMINISTRATOR])
def test_a_pending_enrolment_grants_no_privilege(account: AccountFactory, role: Role) -> None:
    user = account(role)
    _start(user)
    device = TotpDevice.objects.get(user=user)

    assert selectors.permissions_of(signed_in(user)) == {OWN_MFA}
    # Not even to a context that claims a code was verified against it.
    claimed = AuthenticationContext(user, Assurance.MFA_VERIFIED, device.pk)
    assert selectors.permissions_of(claimed) == {OWN_MFA}


def test_a_pending_enrolment_is_not_asked_for_at_sign_in(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    _start(user)

    result = services.sign_in(email=user.email, password=PASSWORD, source=SOURCE)

    assert result.outcome == SignInOutcome.SIGNED_IN
    assert result.challenge is None
    assert not MfaChallenge.objects.exists()


def test_an_administrator_with_a_pending_enrolment_cannot_change_roles(
    account: AccountFactory, user_with_roles: UserFactory
) -> None:
    administrator = account(Role.ADMINISTRATOR)
    target = user_with_roles()
    _start(administrator)
    device = TotpDevice.objects.get(user=administrator)

    for actor in (
        signed_in(administrator),
        AuthenticationContext(administrator, Assurance.MFA_VERIFIED, device.pk),
    ):
        with pytest.raises(PermissionDenied):
            services.grant_role(actor=actor, user=target, role=Role.READER, reason="TEST attempt")

    assert selectors.roles_of(target) == frozenset()


# --- Confirming an enrolment ----------------------------------------------------


def test_a_wrong_code_does_not_activate(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    secret = _secret_of(_start(user))

    result = _confirm(user, _wrong_code(secret))

    assert result.outcome == REFUSED
    assert result.context is None
    assert TotpDevice.objects.get(user=user).state == TotpDeviceState.PENDING_VERIFICATION
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION
    assert selectors.permissions_of(signed_in(user)) == {OWN_MFA}
    assert _events() == [
        "mfa_enrollment_started",
        "mfa_enrollment_approved",
        "mfa_verification_failed",
    ]


def test_a_code_from_another_secret_does_not_activate(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    _start(user)

    assert _confirm(user, code_at(secret=TEST_TOTP_SECRET)).outcome == REFUSED
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION


def test_the_right_code_activates_and_raises_the_assurance(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    secret = _secret_of(_start(user))

    result = _confirm(user, code_at(secret=secret))

    device = TotpDevice.objects.get(user=user)
    assert result.outcome == ACCEPTED
    assert result.context == AuthenticationContext(user, Assurance.MFA_VERIFIED, device.pk)
    assert device.state == TotpDeviceState.ACTIVE
    assert device.confirmed_at is not None
    assert device.last_used_step is not None
    assert selectors.mfa_state_of(user) == MfaState.ACTIVE
    assert selectors.permissions_of(result.context) == ADMINISTRATIVE | {OWN_MFA}
    assert _events() == [
        "mfa_enrollment_started",
        "mfa_enrollment_approved",
        "mfa_enrollment_succeeded",
    ]


def test_an_enrolment_not_confirmed_in_time_is_void(
    account: AccountFactory, clock: Clock, settings: LazySettings
) -> None:
    # An enrolment that needs no approval. One that does waits longer, for a
    # person: test_second_factor_approval.py.
    user = account(Role.READER)
    secret = _secret_of(_start(user))
    clock(settings.MFA_ENROLLMENT_LIFETIME - timedelta(seconds=1))
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION

    clock(timedelta(seconds=1))

    assert selectors.mfa_state_of(user) == MfaState.NOT_ENROLLED
    result = _confirm(user, code_at(secret=secret))
    assert result.outcome == UNAVAILABLE
    assert result.context is None
    assert TotpDevice.objects.get(user=user).state == TotpDeviceState.PENDING_VERIFICATION
    assert selectors.permissions_of(signed_in(user)) == {OWN_MFA, Permission.WORKSPACE_READ}
    assert _events() == ["mfa_enrollment_started"]


def test_an_enrolment_confirmed_just_in_time_is_accepted(
    account: AccountFactory, clock: Clock, settings: LazySettings
) -> None:
    user = account(Role.READER)
    secret = _secret_of(_start(user))
    clock(settings.MFA_ENROLLMENT_LIFETIME - timedelta(seconds=1))

    assert _confirm(user, code_at(secret=secret)).outcome == ACCEPTED


def test_confirming_with_nothing_pending_is_not_possible(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)

    result = _confirm(user, code_at())

    assert result.outcome == UNAVAILABLE
    assert selectors.mfa_state_of(user) == MfaState.NOT_ENROLLED
    assert _events() == []


def test_an_enrolment_is_confirmed_once(account: AccountFactory, clock: Clock) -> None:
    user = account(Role.ADMINISTRATOR)
    _, secret = _enrol(user)
    confirmed = TotpDevice.objects.values().get(user=user)
    clock(STEP)

    again = _confirm(user, code_at(secret=secret))

    assert again.outcome == UNAVAILABLE
    assert again.context is None
    assert TotpDevice.objects.values().get(user=user) == confirmed


def test_another_account_cannot_confirm_an_enrolment(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    other = account(Role.READER)
    secret = _secret_of(_start(user))

    result = _confirm(other, code_at(secret=secret))

    assert result.outcome == UNAVAILABLE
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION
    assert selectors.mfa_state_of(other) == MfaState.NOT_ENROLLED


# --- Signing in -----------------------------------------------------------------


@pytest.mark.parametrize("role", [Role.READER, Role.RESEARCHER])
def test_an_account_without_a_second_factor_signs_in_with_its_password(
    account: AccountFactory, role: Role
) -> None:
    user = account(role)

    result = services.sign_in(email=user.email, password=PASSWORD, source=SOURCE)

    assert (result.outcome, result.user, result.challenge) == (
        SignInOutcome.SIGNED_IN,
        user,
        None,
    )
    assert _events() == ["login_success"]
    assert not MfaChallenge.objects.exists()


@pytest.mark.parametrize("role", list(Role))
def test_with_a_second_factor_the_password_alone_signs_nobody_in(
    account: AccountFactory, role: Role
) -> None:
    user = account(role)
    enrolled_device(user)

    result = services.sign_in(email=user.email, password=PASSWORD, source=SOURCE)

    assert result.outcome == SignInOutcome.SECOND_FACTOR_REQUIRED
    assert result.user is None
    assert result.challenge
    assert _events() == ["mfa_challenge_issued"]
    assert MfaChallenge.objects.get().user == user


def test_a_wrong_password_never_reaches_the_second_factor(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)

    result = services.sign_in(email=user.email, password=WRONG, source=SOURCE)

    assert (result.outcome, result.challenge) == (SignInOutcome.REFUSED, None)
    assert not MfaChallenge.objects.exists()
    assert _events() == ["login_failure"]


def test_the_right_code_completes_the_sign_in_at_the_higher_assurance(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    device = enrolled_device(user)
    challenge = _challenge(user)

    result = _verify(challenge, code_at())

    assert result.outcome == ACCEPTED
    assert result.context == AuthenticationContext(user, Assurance.MFA_VERIFIED, device.pk)
    assert selectors.permissions_of(result.context) == ADMINISTRATIVE | {OWN_MFA}
    assert not MfaChallenge.objects.exists()
    assert _events() == ["mfa_challenge_issued", "mfa_verification_succeeded", "login_success"]


def test_a_wrong_code_signs_nobody_in_and_is_recorded(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    challenge = _challenge(user)

    result = _verify(challenge, _wrong_code())

    assert (result.outcome, result.context) == (REFUSED, None)
    assert _events() == ["mfa_challenge_issued", "mfa_verification_failed"]
    # The challenge is still there: a mistyped code is not the end of the sign-in.
    assert _verify(challenge, code_at()).outcome == ACCEPTED


def test_a_used_challenge_cannot_be_used_again(account: AccountFactory, clock: Clock) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    challenge = _challenge(user)
    assert _verify(challenge, code_at()).outcome == ACCEPTED
    events = _events()
    clock(STEP)

    replayed = _verify(challenge, code_at())

    assert (replayed.outcome, replayed.context) == (REFUSED, None)
    assert _events() == events, "a dead challenge names nobody, so nothing is recorded"


def test_a_code_is_accepted_once(account: AccountFactory, clock: Clock) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    code = code_at()
    assert _verify(_challenge(user), code).outcome == ACCEPTED

    assert _verify(_challenge(user), code).outcome == REFUSED

    clock(STEP)
    assert _verify(_challenge(user), code_at()).outcome == ACCEPTED


def test_an_older_code_is_refused_after_a_newer_one_was_used(
    account: AccountFactory, clock: Clock
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    earlier = code_at()
    clock(STEP)
    assert _verify(_challenge(user), code_at()).outcome == ACCEPTED

    # Still inside the drift window, and never used, but older than the last one.
    assert _verify(_challenge(user), earlier).outcome == REFUSED


def test_the_code_used_to_enrol_cannot_be_used_to_sign_in(
    account: AccountFactory, clock: Clock
) -> None:
    user = account(Role.ADMINISTRATOR)
    secret = _secret_of(_start(user))
    code = code_at(secret=secret)
    assert _confirm(user, code).outcome == ACCEPTED

    assert _verify(_challenge(user), code).outcome == REFUSED


@pytest.mark.parametrize(("steps", "accepted"), [(-2, False), (-1, True), (1, True), (2, False)])
def test_a_code_is_accepted_one_step_either_side_of_now(
    account: AccountFactory, clock: Clock, steps: int, accepted: bool
) -> None:
    user = account(Role.READER)
    enrolled_device(user)

    result = _verify(_challenge(user), code_at(timezone.now() + steps * STEP))

    assert (result.outcome == ACCEPTED) is accepted


@pytest.mark.parametrize(
    "challenge", ["", "TEST-unknown-challenge", "0" * 43], ids=["empty", "unknown", "right-shape"]
)
def test_an_unknown_challenge_is_refused_and_records_nothing(
    account: AccountFactory, challenge: str
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)

    result = _verify(challenge, code_at())

    assert (result.outcome, result.context) == (REFUSED, None)
    assert _events() == []


def test_the_stored_challenge_is_not_the_token(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    challenge = _challenge(user)

    stored = MfaChallenge.objects.get()

    assert stored.token_key != challenge
    assert challenge not in repr(MfaChallenge.objects.values().get())
    # What is stored does not work as a token.
    assert _verify(stored.token_key, code_at()).outcome == REFUSED


def test_a_challenge_lapses(account: AccountFactory, clock: Clock, settings: LazySettings) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    challenge = _challenge(user)

    clock(settings.MFA_CHALLENGE_LIFETIME)

    result = _verify(challenge, code_at())
    assert (result.outcome, result.context) == (REFUSED, None)
    assert _events() == ["mfa_challenge_issued"]


def test_a_challenge_is_good_until_just_before_it_lapses(
    account: AccountFactory, clock: Clock, settings: LazySettings
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    challenge = _challenge(user)

    clock(settings.MFA_CHALLENGE_LIFETIME - timedelta(seconds=1))

    assert _verify(challenge, code_at()).outcome == ACCEPTED


def test_a_new_sign_in_replaces_the_pending_challenge(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    first = _challenge(user)
    second = _challenge(user)

    assert first != second
    assert MfaChallenge.objects.count() == 1
    assert _verify(first, code_at()).outcome == REFUSED
    assert _verify(second, code_at()).outcome == ACCEPTED


def test_a_cancelled_challenge_cannot_complete_a_sign_in(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    challenge = _challenge(user)

    services.cancel_second_factor_challenge(challenge=challenge)
    services.cancel_second_factor_challenge(challenge=challenge)
    services.cancel_second_factor_challenge(challenge="TEST-unknown-challenge")

    assert not MfaChallenge.objects.exists()
    assert _verify(challenge, code_at()).outcome == REFUSED


def test_a_challenge_completes_a_sign_in_only_for_its_own_account(
    account: AccountFactory, clock: Clock
) -> None:
    victim = account(Role.ADMINISTRATOR)
    attacker = account(Role.READER)
    enrolled_device(victim)
    _, attacker_secret = _enrol(attacker)
    clock(STEP)
    victims_challenge = _challenge(victim)
    attackers_challenge = _challenge(attacker)

    # The attacker's own, valid code against the victim's challenge.
    crossed = _verify(victims_challenge, code_at(secret=attacker_secret))
    assert (crossed.outcome, crossed.context) == (REFUSED, None)

    # The attacker's own challenge only ever yields the attacker.
    own = _verify(attackers_challenge, code_at(secret=attacker_secret))
    assert own.outcome == ACCEPTED
    assert own.context is not None
    assert own.context.user == attacker
    assert selectors.permissions_of(own.context).isdisjoint(ADMINISTRATIVE)
    assert "login_success" not in _events(victim)


def test_verification_takes_no_account_from_the_caller() -> None:
    assert set(inspect.signature(services.verify_second_factor).parameters) == {
        "challenge",
        "code",
        "source",
    }


def test_an_account_deactivated_after_the_password_step_is_not_signed_in(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    challenge = _challenge(user)
    User.objects.filter(pk=user.pk).update(status="disabled")

    result = _verify(challenge, code_at())

    assert (result.outcome, result.context) == (REFUSED, None)
    assert "login_success" not in _events()


def test_a_second_factor_removed_after_the_password_step_signs_nobody_in(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    challenge = _challenge(user)
    TotpDevice.objects.all().delete()

    result = _verify(challenge, code_at())

    assert (result.outcome, result.context) == (REFUSED, None)


def test_a_secret_that_cannot_be_decrypted_refuses_the_code_and_says_so_in_the_log(
    account: AccountFactory, settings: LazySettings, caplog: pytest.LogCaptureFixture
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    challenge = _challenge(user)
    settings.TOTP_ENCRYPTION_KEY = bytes(range(32))

    with caplog.at_level(logging.ERROR, logger="caipo.accounts.services"):
        result = _verify(challenge, code_at())

    assert (result.outcome, result.context) == (REFUSED, None)
    (record,) = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert record.__dict__["event"] == "mfa.secret_unavailable"
    assert record.__dict__["user_id"] == user.pk
    assert record.exc_info is None


def test_a_secret_moved_from_another_account_is_not_accepted(account: AccountFactory) -> None:
    victim = account(Role.ADMINISTRATOR)
    attacker = account(Role.READER)
    enrolled_device(victim)
    _, attacker_secret = _enrol(attacker)
    # Someone with write access to the table copies their own secret over the victim's.
    TotpDevice.objects.filter(user=victim).update(
        secret_ciphertext=TotpDevice.objects.get(user=attacker).secret_ciphertext
    )

    result = _verify(_challenge(victim), code_at(secret=attacker_secret))

    assert (result.outcome, result.context) == (REFUSED, None)


# --- Throttling of codes --------------------------------------------------------


def test_the_limit_on_refused_codes_is_exact(
    account: AccountFactory, settings: LazySettings
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    limit = settings.MFA_THROTTLE_FAILURES
    challenge = _challenge(user)

    for _ in range(limit):
        assert _verify(challenge, _wrong_code()).outcome == REFUSED
    events = _events()

    # The right code is not examined any more.
    result = _verify(challenge, code_at())
    assert (result.outcome, result.context) == (THROTTLED, None)
    assert _events() == events, "a throttled attempt records nothing"
    assert events.count("mfa_verification_failed") == limit


def test_one_refusal_short_of_the_limit_the_right_code_still_works(
    account: AccountFactory, settings: LazySettings
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    challenge = _challenge(user)

    for _ in range(settings.MFA_THROTTLE_FAILURES - 1):
        assert _verify(challenge, _wrong_code()).outcome == REFUSED

    assert _verify(challenge, code_at()).outcome == ACCEPTED


def test_refused_codes_never_exceed_the_limit_however_many_are_sent(
    account: AccountFactory, settings: LazySettings
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    challenge = _challenge(user)

    outcomes = [_verify(challenge, _wrong_code()).outcome for _ in range(40)]

    limit = settings.MFA_THROTTLE_FAILURES
    assert outcomes == [REFUSED] * limit + [THROTTLED] * (40 - limit)
    assert _events().count("mfa_verification_failed") == limit


def test_the_throttle_lifts_by_itself_and_only_after_the_window(
    account: AccountFactory, clock: Clock, settings: LazySettings
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    for _ in range(settings.MFA_THROTTLE_FAILURES):
        _verify(_challenge(user), _wrong_code())

    clock(settings.MFA_THROTTLE_WINDOW - timedelta(seconds=1))
    assert _verify(_challenge(user), code_at()).outcome == THROTTLED

    clock(timedelta(seconds=2))
    assert _verify(_challenge(user), code_at()).outcome == ACCEPTED


def test_an_accepted_code_does_not_buy_fresh_guesses(
    account: AccountFactory, clock: Clock, settings: LazySettings
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    for _ in range(settings.MFA_THROTTLE_FAILURES - 1):
        _verify(_challenge(user), _wrong_code())
    assert _verify(_challenge(user), code_at()).outcome == ACCEPTED
    clock(STEP)

    assert _verify(_challenge(user), _wrong_code()).outcome == REFUSED
    assert _verify(_challenge(user), code_at()).outcome == THROTTLED


def test_a_new_challenge_does_not_reset_the_count(
    account: AccountFactory, settings: LazySettings
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)

    outcomes = [
        _verify(_challenge(user), _wrong_code()).outcome
        for _ in range(settings.MFA_THROTTLE_FAILURES + 1)
    ]

    assert outcomes[-1] == THROTTLED


def test_changing_the_source_does_not_reset_the_count(
    account: AccountFactory, settings: LazySettings
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    challenge = _challenge(user)

    outcomes = [
        services.verify_second_factor(
            challenge=challenge, code=_wrong_code(), source=f"203.0.113.{number}"
        ).outcome
        for number in range(settings.MFA_THROTTLE_FAILURES + 1)
    ]

    assert outcomes[-1] == THROTTLED


def test_the_throttle_is_per_account(account: AccountFactory, settings: LazySettings) -> None:
    user = account(Role.ADMINISTRATOR)
    other = account(Role.READER)
    enrolled_device(user)
    enrolled_device(other)
    challenge = _challenge(user)
    for _ in range(settings.MFA_THROTTLE_FAILURES):
        _verify(challenge, _wrong_code())

    assert _verify(_challenge(other), code_at()).outcome == ACCEPTED


def test_the_throttle_covers_enrolment_sign_in_and_disabling_together(
    account: AccountFactory, clock: Clock, settings: LazySettings
) -> None:
    user = account(Role.ADMINISTRATOR)
    secret = _secret_of(_start(user))
    limit = settings.MFA_THROTTLE_FAILURES

    for _ in range(limit - 2):
        assert _confirm(user, _wrong_code(secret)).outcome == REFUSED
    confirmed = _confirm(user, code_at(secret=secret))
    assert confirmed.outcome == ACCEPTED
    assert confirmed.context is not None
    clock(STEP)
    assert _verify(_challenge(user), _wrong_code(secret)).outcome == REFUSED
    assert (
        services.disable_mfa(
            actor=confirmed.context, password=PASSWORD, code=_wrong_code(secret), source=SOURCE
        ).outcome
        == REFUSED
    )

    # The limit is reached: no flow examines a code any more.
    assert _verify(_challenge(user), code_at(secret=secret)).outcome == THROTTLED
    assert (
        services.disable_mfa(
            actor=confirmed.context,
            password=PASSWORD,
            code=code_at(secret=secret),
            source=SOURCE,
        ).outcome
        == THROTTLED
    )
    assert selectors.mfa_state_of(user) == MfaState.ACTIVE


def test_confirming_an_enrolment_is_throttled_too(
    account: AccountFactory, settings: LazySettings
) -> None:
    user = account(Role.ADMINISTRATOR)
    secret = _secret_of(_start(user))
    for _ in range(settings.MFA_THROTTLE_FAILURES):
        assert _confirm(user, _wrong_code(secret)).outcome == REFUSED

    result = _confirm(user, code_at(secret=secret))

    assert (result.outcome, result.context) == (THROTTLED, None)
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION


# --- Throttling of the password asked for again ---------------------------------


def test_password_confirmation_is_throttled_like_sign_in(
    account: AccountFactory, settings: LazySettings
) -> None:
    user = account(Role.ADMINISTRATOR)
    limit = settings.LOGIN_THROTTLE_ACCOUNT_FAILURES

    for _ in range(limit):
        assert _start(user, WRONG).outcome == REFUSED

    assert _start(user, PASSWORD).outcome == THROTTLED
    assert not TotpDevice.objects.exists()
    assert _events() == ["password_confirmation_failed"] * limit


def test_wrong_passwords_at_sign_in_and_when_asked_again_count_together(
    account: AccountFactory, settings: LazySettings
) -> None:
    user = account(Role.ADMINISTRATOR)
    limit = settings.LOGIN_THROTTLE_ACCOUNT_FAILURES

    for _ in range(limit - 1):
        services.sign_in(email=user.email, password=WRONG, source=SOURCE)
    assert _start(user, WRONG).outcome == REFUSED

    assert _start(user, PASSWORD).outcome == THROTTLED
    assert (
        services.sign_in(email=user.email, password=PASSWORD, source=SOURCE).outcome
        == SignInOutcome.THROTTLED
    )


# --- Authorization at each assurance --------------------------------------------


@pytest.mark.parametrize(
    ("role", "privileged"),
    [
        (
            Role.REVIEWER,
            {Permission.WORKSPACE_READ, Permission.RESEARCH_CONTRIBUTE, Permission.RESEARCH_REVIEW},
        ),
        (Role.ADMINISTRATOR, ADMINISTRATIVE),
    ],
)
def test_privileged_permissions_need_a_verified_second_factor(
    account: AccountFactory, role: Role, privileged: set[Permission]
) -> None:
    user = account(role)
    with_mfa, _ = _enrol(user)
    # The same account, enrolled, in a context that verified no code.
    without_mfa = signed_in(user)

    assert selectors.permissions_of(without_mfa) == {OWN_MFA}
    assert selectors.permissions_of(with_mfa) == privileged | {OWN_MFA}
    for permission in privileged:
        assert selectors.can(with_mfa, permission)
        assert not selectors.can(without_mfa, permission)
        with pytest.raises(PermissionDenied):
            selectors.require_permission(without_mfa, permission)


@pytest.mark.parametrize("role", [Role.READER, Role.RESEARCHER])
def test_reader_and_researcher_are_unchanged_by_the_second_factor(
    account: AccountFactory, role: Role
) -> None:
    user = account(role)
    before = selectors.permissions_of(signed_in(user))

    with_mfa, _ = _enrol(user)

    assert before
    assert selectors.permissions_of(signed_in(user)) == before
    assert selectors.permissions_of(with_mfa) == before
    assert before.isdisjoint(ADMINISTRATIVE | {Permission.RESEARCH_REVIEW})


def test_a_service_called_directly_refuses_an_administrator_without_a_verified_code(
    account: AccountFactory, user_with_roles: UserFactory
) -> None:
    administrator = account(Role.ADMINISTRATOR)
    target = user_with_roles(Role.READER)
    with_mfa, _ = _enrol(administrator)
    without_mfa = signed_in(administrator)

    with pytest.raises(PermissionDenied):
        services.grant_role(
            actor=without_mfa, user=target, role=Role.RESEARCHER, reason="TEST attempt"
        )
    with pytest.raises(PermissionDenied):
        services.revoke_role(
            actor=without_mfa, user=target, role=Role.READER, reason="TEST attempt"
        )
    with pytest.raises(PermissionDenied):
        services.disable_user(actor=without_mfa, user=target)
    assert selectors.roles_of(target) == {Role.READER}
    assert User.objects.get(pk=target.pk).is_active is True

    services.grant_role(actor=with_mfa, user=target, role=Role.RESEARCHER, reason="TEST grant")
    assert selectors.roles_of(target) == {Role.READER, Role.RESEARCHER}


def test_a_claim_of_a_verified_code_counts_only_against_the_accounts_own_active_device(
    account: AccountFactory, user_with_roles: UserFactory
) -> None:
    administrator = account(Role.ADMINISTRATOR)
    other = account(Role.READER)
    target = user_with_roles()
    others_device = enrolled_device(other)

    claims = [
        # A device that does not exist.
        AuthenticationContext(administrator, Assurance.MFA_VERIFIED, 987654321),
        AuthenticationContext(administrator, Assurance.MFA_VERIFIED, 0),
        AuthenticationContext(administrator, Assurance.MFA_VERIFIED, -1),
        # A real, active device that belongs to somebody else.
        AuthenticationContext(administrator, Assurance.MFA_VERIFIED, others_device.pk),
    ]

    for claim in claims:
        assert selectors.permissions_of(claim) == {OWN_MFA}
        with pytest.raises(PermissionDenied):
            services.grant_role(actor=claim, user=target, role=Role.READER, reason="TEST attempt")
    assert not RoleEvent.objects.filter(user=target).exists()


def test_an_enrolled_device_alone_is_not_a_verified_code(account: AccountFactory) -> None:
    # The database says the account is enrolled; the context says no code was
    # verified. The database row alone grants nothing.
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)

    assert selectors.mfa_state_of(user) == MfaState.ACTIVE
    assert selectors.permissions_of(signed_in(user)) == {OWN_MFA}


def test_a_context_names_a_device_if_and_only_if_it_is_verified(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)

    with pytest.raises(ValueError, match="MFA_VERIFIED"):
        AuthenticationContext(user, Assurance.MFA_VERIFIED)
    with pytest.raises(ValueError, match="MFA_VERIFIED"):
        AuthenticationContext(user, Assurance.PASSWORD_AUTHENTICATED, 1)


@pytest.mark.parametrize(
    "marker", [None, True, False, "1", "mfa_verified", 1.0, [1], {"device": 1}, b"1"]
)
def test_only_an_integer_is_taken_as_a_claim_of_a_verified_device(
    account: AccountFactory, marker: object
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)

    actor = selectors.authentication_context(user, verified_device_id=marker)

    assert actor == AuthenticationContext(user, Assurance.PASSWORD_AUTHENTICATED)
    assert selectors.permissions_of(actor) == {OWN_MFA}


def test_a_verified_context_built_from_the_right_device_is_believed(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    device = enrolled_device(user)

    actor = selectors.authentication_context(user, verified_device_id=device.pk)

    assert actor == verified(user)
    assert selectors.permissions_of(actor) == ADMINISTRATIVE | {OWN_MFA}


# --- Disabling ------------------------------------------------------------------


def _disable(
    actor: AuthenticationContext, password: str = PASSWORD, code: str | None = None
) -> services.MfaResult:
    return services.disable_mfa(
        actor=actor, password=password, code=code if code is not None else code_at(), source=SOURCE
    )


def test_disabling_needs_the_password_and_a_current_code(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    actor = verified(user)

    assert _disable(actor, WRONG).outcome == REFUSED
    assert _disable(actor, PASSWORD, _wrong_code()).outcome == REFUSED
    assert _disable(actor, WRONG, _wrong_code()).outcome == REFUSED
    assert selectors.mfa_state_of(user) == MfaState.ACTIVE
    assert selectors.can(actor, Permission.ROLES_MANAGE)

    assert _disable(actor).outcome == ACCEPTED

    assert selectors.mfa_state_of(user) == MfaState.NOT_ENROLLED
    assert not TotpDevice.objects.exists()
    assert _events() == [
        "password_confirmation_failed",
        "mfa_verification_failed",
        "password_confirmation_failed",
        "mfa_disabled",
    ]


def test_disabling_takes_the_privileges_of_every_context_with_it(
    account: AccountFactory, user_with_roles: UserFactory
) -> None:
    user = account(Role.ADMINISTRATOR)
    actor = verified(user)

    assert _disable(actor).outcome == ACCEPTED

    assert selectors.permissions_of(actor) == {OWN_MFA}
    with pytest.raises(PermissionDenied):
        services.grant_role(
            actor=actor, user=user_with_roles(), role=Role.READER, reason="TEST attempt"
        )
    # And the next sign-in is by password alone again.
    result = services.sign_in(email=user.email, password=PASSWORD, source=SOURCE)
    assert result.outcome == SignInOutcome.SIGNED_IN


def test_a_context_verified_against_a_removed_device_does_not_revive_with_a_new_one(
    account: AccountFactory, clock: Clock
) -> None:
    user = account(Role.ADMINISTRATOR)
    old, secret = _enrol(user)
    clock(STEP)
    assert _disable(old, code=code_at(secret=secret)).outcome == ACCEPTED

    new, _ = _enrol(user)

    assert new.mfa_device_id != old.mfa_device_id
    assert selectors.permissions_of(new) == ADMINISTRATIVE | {OWN_MFA}
    assert selectors.permissions_of(old) == {OWN_MFA}


def test_disabling_removes_a_pending_challenge(account: AccountFactory, clock: Clock) -> None:
    user = account(Role.ADMINISTRATOR)
    actor = verified(user)
    challenge = _challenge(user)

    assert _disable(actor).outcome == ACCEPTED

    assert not MfaChallenge.objects.exists()
    clock(STEP)
    assert _verify(challenge, code_at()).outcome == REFUSED


def test_a_code_already_used_does_not_disable(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    code = code_at()
    signed = _verify(_challenge(user), code)
    assert signed.context is not None

    assert _disable(signed.context, code=code).outcome == REFUSED
    assert selectors.mfa_state_of(user) == MfaState.ACTIVE


def test_disabling_without_an_active_second_factor_is_not_possible(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)

    assert _disable(signed_in(user)).outcome == UNAVAILABLE
    _start(user)
    assert _disable(signed_in(user)).outcome == UNAVAILABLE
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION


def test_nobody_can_disable_the_second_factor_of_another_account(
    account: AccountFactory,
) -> None:
    victim = account(Role.READER)
    administrator = account(Role.ADMINISTRATOR)
    enrolled_device(victim)
    actor = verified(administrator)

    # The operation has no parameter that could name another account.
    assert set(inspect.signature(services.disable_mfa).parameters) == {
        "actor",
        "password",
        "code",
        "source",
    }
    assert _disable(actor).outcome == ACCEPTED

    assert selectors.mfa_state_of(victim) == MfaState.ACTIVE
    assert selectors.mfa_state_of(administrator) == MfaState.NOT_ENROLLED


# --- What is stored, recorded, and logged ---------------------------------------


def test_no_secret_code_or_credential_reaches_the_logs_the_events_or_the_tables(
    account: AccountFactory, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    user = account(Role.ADMINISTRATOR)
    used: list[str] = [PASSWORD, WRONG, user.email]

    with caplog.at_level(logging.DEBUG):
        _start(user, WRONG)
        started = _start(user)
        assert started.provisioning is not None
        secret = _secret_of(started)
        used += [started.provisioning.secret, started.provisioning.uri, secret.hex()]
        used.append(_wrong_code(secret))
        _confirm(user, used[-1])
        used.append(code_at(secret=secret))
        confirmed = _confirm(user, used[-1])
        assert confirmed.context is not None
        clock(STEP)
        challenge = _challenge(user)
        used.append(challenge)
        _verify(challenge, _wrong_code(secret))
        used.append(code_at(secret=secret))
        assert _verify(challenge, used[-1]).outcome == ACCEPTED
        clock(STEP)
        used.append(_challenge(user))
        used.append(code_at(secret=secret))
        assert _disable(confirmed.context, code=used[-1]).outcome == ACCEPTED
        written = logged(caplog.records) + repr(started)

    stored = repr(
        [
            list(AuthenticationEvent.objects.values()),
            list(RoleEvent.objects.values()),
            list(User.objects.values("id", "email", "status", "last_login")),
        ]
    )
    assert _events()[-1] == "mfa_disabled"
    for value in used:
        assert value not in written, value
    for value in [value for value in used if value != user.email]:
        assert value not in stored, value


def test_the_device_row_holds_the_secret_only_under_encryption(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    started = _start(user)
    assert started.provisioning is not None
    secret = _secret_of(started)

    row = TotpDevice.objects.values().get(user=user)
    ciphertext = bytes(row["secret_ciphertext"])

    assert secret not in ciphertext
    assert started.provisioning.secret.encode() not in ciphertext
    assert secret.hex().encode() not in ciphertext
    for value in (started.provisioning.secret, secret.hex(), "otpauth"):
        assert value not in repr(
            {name: v for name, v in row.items() if name != "secret_ciphertext"}
        )
    assert set(row) == {
        "id",
        "user_id",
        "state",
        "secret_ciphertext",
        "key_id",
        "last_used_step",
        "created_at",
        "confirmed_at",
        "approved_at",
        "approved_by_id",
    }


def test_results_do_not_show_secrets_when_printed(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    started = _start(user)
    assert started.provisioning is not None

    assert started.provisioning.secret not in repr(started)
    assert started.provisioning.secret not in repr(started.provisioning)
    assert "otpauth" not in repr(started)
    assert str(TotpDevice.objects.get(user=user)) == "pending_verification"
    assert (
        repr(TotpDevice.objects.get(user=user))
        == f"<TotpDevice: {TotpDeviceState.PENDING_VERIFICATION}>"
    )


def test_every_event_names_the_account_and_none_holds_more_than_the_columns(
    account: AccountFactory, clock: Clock
) -> None:
    user = account(Role.ADMINISTRATOR)
    _, secret = _enrol(user)
    clock(STEP)
    _verify(_challenge(user), code_at(secret=secret))

    events = AuthenticationEvent.objects.all()

    assert {event.user for event in events} == {user}
    assert {field.column for field in AuthenticationEvent._meta.concrete_fields} == {
        "id",
        "event_type",
        "user_id",
        "actor_id",
        "identifier_key",
        "source_key",
        "correlation_id",
        "created_at",
    }


@pytest.mark.parametrize(
    ("operation", "event"),
    [
        ("start", "mfa.enrollment_started"),
        ("confirm", "mfa.enrollment_succeeded"),
        ("verify", "authentication.signed_in"),
        ("disable", "mfa.disabled"),
    ],
)
def test_each_change_is_logged_by_account_identifier(
    account: AccountFactory,
    clock: Clock,
    caplog: pytest.LogCaptureFixture,
    operation: str,
    event: str,
) -> None:
    user = account(Role.ADMINISTRATOR)

    with caplog.at_level(logging.INFO, logger="caipo.accounts.services"):
        actor, secret = _enrol(user)
        clock(STEP)
        _verify(_challenge(user), code_at(secret=secret))
        clock(STEP)
        _disable(actor, code=code_at(secret=secret))

    (record,) = [record for record in caplog.records if record.__dict__.get("event") == event]
    assert record.__dict__["user_id"] == user.pk
    assert user.email not in str(record.__dict__)


# --- There is no switch -----------------------------------------------------------

# Names someone might hope would switch the requirement off.
SWITCHES = [
    "BYPASS_MFA",
    "MFA_BYPASS",
    "DISABLE_MFA",
    "MFA_DISABLED",
    "MFA_ENABLED",
    "MFA_ENROLLED",
    "MFA_VERIFIED",
    "MFA_REQUIRED",
    "REQUIRE_MFA",
    "SKIP_MFA",
    "TOTP_BYPASS",
    "TOTP_DISABLED",
    "TOTP_REQUIRED",
    "ASSURANCE",
    "TESTING",
    "DEBUG",
]


def _production_modules() -> list[Path]:
    return [path for path in PACKAGE_ROOT.rglob("*.py") if "tests" not in path.parts]


@pytest.mark.parametrize("value", ["true", "1", "True", "yes", "on", "mfa_verified"])
def test_no_environment_variable_stands_in_for_a_second_factor(
    account: AccountFactory, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    administrator = account(Role.ADMINISTRATOR)
    enrolled_device(administrator)
    for name in SWITCHES:
        for variable in (name, f"CAIPO_{name}", f"DJANGO_{name}"):
            monkeypatch.setenv(variable, value)

    assert selectors.permissions_of(signed_in(administrator)) == {OWN_MFA}
    result = services.sign_in(email=administrator.email, password=PASSWORD, source=SOURCE)
    assert result.outcome == SignInOutcome.SECOND_FACTOR_REQUIRED
    assert _verify(_challenge(administrator), _wrong_code()).outcome == REFUSED


def test_no_setting_stands_in_for_a_second_factor(
    account: AccountFactory, settings: LazySettings
) -> None:
    administrator = account(Role.ADMINISTRATOR)
    enrolled_device(administrator)
    for name in SWITCHES:
        setattr(settings, name, "REQUIRE" not in name and "REQUIRED" not in name)

    assert selectors.permissions_of(signed_in(administrator)) == {OWN_MFA}
    result = services.sign_in(email=administrator.email, password=PASSWORD, source=SOURCE)
    assert result.outcome == SignInOutcome.SECOND_FACTOR_REQUIRED
    assert _verify(_challenge(administrator), _wrong_code()).outcome == REFUSED


def test_the_only_second_factor_settings_are_these() -> None:
    names = {
        name
        for name in dir(django_settings)
        if name.isupper() and any(word in name for word in ("MFA", "TOTP", "OTP", "ASSURANCE"))
    }

    assert "SECRET_KEY" in dir(django_settings), "the settings were not listed at all"

    # An issuer name, a drift window, a key, three lifetimes, and a throttle.
    # None of them says whether a second factor, or its approval, is required.
    assert names == {
        "TOTP_ISSUER",
        "TOTP_DRIFT_STEPS",
        "TOTP_ENCRYPTION_KEY",
        "MFA_ENROLLMENT_LIFETIME",
        "MFA_APPROVAL_LIFETIME",
        "MFA_CHALLENGE_LIFETIME",
        "MFA_THROTTLE_WINDOW",
        "MFA_THROTTLE_FAILURES",
    }


def test_no_value_on_the_account_stands_in_for_a_second_factor(account: AccountFactory) -> None:
    administrator = account(Role.ADMINISTRATOR, Role.REVIEWER)
    for attribute in (
        "mfa_enrolled",
        "mfa_verified",
        "is_verified",
        "otp_device",
        "totp_enrolled",
        "assurance",
        "mfa_device_id",
    ):
        setattr(administrator, attribute, True)
    administrator.save()

    stored = User.objects.get(pk=administrator.pk)
    for user in (administrator, stored):
        assert selectors.mfa_state_of(user) == MfaState.NOT_ENROLLED
        assert selectors.permissions_of(signed_in(user)) == {OWN_MFA}


def test_the_account_table_has_no_column_that_could_record_enrolment() -> None:
    columns = {field.column for field in User._meta.concrete_fields}

    assert columns == {
        "id",
        "password",
        "last_login",
        "email",
        # The lifecycle of the account. None of the three says anything
        # about a second factor.
        "status",
        "email_verified_at",
        "activated_at",
        "created_at",
        "updated_at",
    }


def test_the_policy_and_the_decision_read_no_environment_and_no_setting_but_the_lifetimes() -> None:
    for module in ("authorization.py", "authentication.py"):
        source = (PACKAGE_ROOT / "accounts" / module).read_text()
        assert "environ" not in source, module
        assert "settings" not in source, module
    selectors_source = (PACKAGE_ROOT / "accounts" / "selectors.py").read_text()
    assert "environ" not in selectors_source
    assert set(re.findall(r"settings\.(\w+)", selectors_source)) == {
        "ACCOUNT_ACTIVATION_LIFETIME",
        "MFA_ENROLLMENT_LIFETIME",
        "MFA_APPROVAL_LIFETIME",
    }


def test_no_production_module_reaches_into_the_tests() -> None:
    offenders = [
        str(path.relative_to(PACKAGE_ROOT))
        for path in _production_modules()
        if any(
            marker in path.read_text()
            for marker in ("monkeypatch", ".tests", "import pytest", "enrolled_device", "TEST_TOTP")
        )
    ]

    assert _production_modules(), "no production modules were found to check"
    assert offenders == []


def test_a_verified_context_is_created_only_by_the_two_operations_that_check_a_code() -> None:
    # MFA_VERIFIED is written in exactly these places outside the tests: where
    # it is defined and compared, where a claim from the session is wrapped for
    # checking, and where a code has just been accepted.
    mentions = {
        str(path.relative_to(PACKAGE_ROOT)): path.read_text().count("Assurance.MFA_VERIFIED")
        for path in _production_modules()
        if "Assurance.MFA_VERIFIED" in path.read_text()
    }

    assert mentions == {
        "accounts/authentication.py": 1,
        "accounts/authorization.py": 1,
        "accounts/selectors.py": 3,
        "accounts/services.py": 2,
    }
    services_source = (PACKAGE_ROOT / "accounts" / "services.py").read_text()
    for operation in ("verify_second_factor", "confirm_mfa_enrollment"):
        body = services_source.split(f"def {operation}(")[1].split("\ndef ")[0]
        assert body.count("Assurance.MFA_VERIFIED") == 1
        assert "_accept_code(" in body


# --- States the services never produce, written directly ------------------------


def test_a_pending_device_never_completes_a_sign_in(account: AccountFactory) -> None:
    # A challenge is issued only for an active device and is removed with it,
    # so the services cannot reach this state. It is written here by hand.
    user = account(Role.ADMINISTRATOR)
    secret = _secret_of(_start(user))
    MfaChallenge.objects.create(
        user=user,
        token_key=services._key("challenge", "TEST-challenge"),
        created_at=timezone.now(),
    )

    result = _verify("TEST-challenge", code_at(secret=secret))

    assert (result.outcome, result.context) == (REFUSED, None)
    assert TotpDevice.objects.get(user=user).state == TotpDeviceState.PENDING_VERIFICATION
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION
    assert "login_success" not in _events()
