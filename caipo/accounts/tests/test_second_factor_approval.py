"""Approval of a second factor for accounts whose privileges rest on it (ADR-0014).

The property under test: for a Reviewer or Administrator account, knowing the
password is never enough to establish a second factor that the authorization
decision trusts. No HTTP is involved, and nothing stands in for TOTP.
"""

import base64
import inspect
import logging
from collections.abc import Callable
from datetime import timedelta

import pytest
from django.conf import LazySettings
from django.core.exceptions import PermissionDenied

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
ATTACKER_SOURCE = "198.51.100.66"

ACCEPTED = MfaOutcome.ACCEPTED
REFUSED = MfaOutcome.REFUSED
UNAVAILABLE = MfaOutcome.UNAVAILABLE

STEP = timedelta(seconds=30)
OWN_MFA = Permission.MFA_MANAGE_OWN
PRIVILEGED = {
    Permission.RESEARCH_REVIEW,
    Permission.ROLES_MANAGE,
    Permission.ACCOUNTS_DEACTIVATE,
    Permission.MFA_ENROLLMENT_APPROVE,
}
PRIVILEGED_ROLES = [Role.REVIEWER, Role.ADMINISTRATOR]


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


def _request(user: User, source: str = SOURCE) -> tuple[bytes, int]:
    """Start an enrolment for an account that needs approval; return its secret and number."""
    result = services.start_mfa_enrollment(actor=signed_in(user), password=PASSWORD, source=source)
    assert result.outcome == ACCEPTED
    assert result.provisioning is not None
    number = selectors.enrollment_request_number_of(user)
    assert number is not None
    return base64.b32decode(result.provisioning.secret), number


def _approve(number: int, actor: AuthenticationContext | None = None) -> services.MfaResult:
    return services.approve_mfa_enrollment(
        actor=actor or approving_administrator(), request_number=number, source=SOURCE
    )


def _reject(number: int, actor: AuthenticationContext | None = None) -> services.MfaResult:
    return services.reject_mfa_enrollment(
        actor=actor or approving_administrator(), request_number=number, source=SOURCE
    )


def _confirm(user: User, code: str) -> services.MfaResult:
    return services.confirm_mfa_enrollment(actor=signed_in(user), code=code, source=SOURCE)


def _device(user: User) -> TotpDevice:
    return TotpDevice.objects.get(user=user)


def _claims_verified(user: User) -> AuthenticationContext:
    """Return a context that claims a verified code against whatever device the account has."""
    return AuthenticationContext(user, Assurance.MFA_VERIFIED, _device(user).pk)


def _privileges(context: AuthenticationContext | None) -> set[Permission]:
    return set(selectors.permissions_of(context)) & PRIVILEGED


# --- The compromised password ---------------------------------------------------


@pytest.mark.parametrize("role", PRIVILEGED_ROLES)
def test_a_compromised_password_cannot_establish_a_second_factor(
    account: AccountFactory, role: Role, clock: Clock
) -> None:
    """The scenario the approval exists for, from the attacker's side, step by step."""
    victim = account(role)

    # The attacker knows the password and nothing else. It signs them in.
    result = services.sign_in(email=victim.email, password=PASSWORD, source=ATTACKER_SOURCE)
    assert result.outcome == SignInOutcome.SIGNED_IN
    attacker = signed_in(victim)
    assert _privileges(attacker) == set()

    # They ask for a second factor of their own, and are given a secret.
    secret, number = _request(victim, ATTACKER_SOURCE)
    assert selectors.mfa_state_of(victim) == MfaState.PENDING_APPROVAL

    # A right code for that secret activates nothing, now or later.
    for _ in range(3):
        assert _confirm(victim, code_at(secret=secret)).outcome == UNAVAILABLE
        clock(STEP)
    device = _device(victim)
    assert device.state == TotpDeviceState.PENDING_APPROVAL
    assert (device.confirmed_at, device.approved_at, device.approved_by) == (None, None, None)

    # They cannot approve it themselves, with any context they can build.
    for context in (attacker, _claims_verified(victim)):
        with pytest.raises(PermissionDenied):
            _approve(number, context)
        with pytest.raises(PermissionDenied):
            selectors.enrollment_requests_awaiting_approval(context)
    assert _device(victim).state == TotpDeviceState.PENDING_APPROVAL

    # The password still signs in on its own, and still confers nothing.
    again = services.sign_in(email=victim.email, password=PASSWORD, source=ATTACKER_SOURCE)
    assert again.outcome == SignInOutcome.SIGNED_IN
    assert not MfaChallenge.objects.exists()
    for context in (attacker, _claims_verified(victim)):
        assert _privileges(context) == set()
        assert selectors.permissions_of(context) <= {
            OWN_MFA,
            Permission.WORKSPACE_READ,
            Permission.RESEARCH_CONTRIBUTE,
        }
    assert "mfa_enrollment_succeeded" not in _events()
    assert "mfa_enrollment_approved" not in _events()


def test_a_compromised_administrator_password_changes_no_role_and_no_account(
    account: AccountFactory,
) -> None:
    victim = account(Role.ADMINISTRATOR)
    other = account(Role.READER)
    secret, _ = _request(victim, ATTACKER_SOURCE)
    _confirm(victim, code_at(secret=secret))
    roles_before = RoleEvent.objects.count()

    for context in (signed_in(victim), _claims_verified(victim)):
        with pytest.raises(PermissionDenied):
            services.grant_role(actor=context, user=other, role=Role.ADMINISTRATOR, reason="TEST")
        with pytest.raises(PermissionDenied):
            services.revoke_role(actor=context, user=other, role=Role.READER, reason="TEST")
        with pytest.raises(PermissionDenied):
            services.deactivate_user(actor=context, user=other)

    assert RoleEvent.objects.count() == roles_before
    assert User.objects.get(pk=other.pk).is_active is True


# --- Requesting -----------------------------------------------------------------


@pytest.mark.parametrize("role", PRIVILEGED_ROLES)
def test_a_privileged_account_requesting_enrolment_awaits_approval(
    account: AccountFactory, role: Role
) -> None:
    user = account(role)

    _, number = _request(user)

    device = _device(user)
    assert device.pk == number
    assert device.state == TotpDeviceState.PENDING_APPROVAL
    assert (device.approved_at, device.approved_by) == (None, None)
    assert selectors.mfa_state_of(user) == MfaState.PENDING_APPROVAL
    assert _events() == ["mfa_enrollment_started"]


@pytest.mark.parametrize("roles", [(Role.READER, Role.REVIEWER), (Role.RESEARCHER, Role.REVIEWER)])
def test_a_lesser_role_held_as_well_does_not_spare_the_approval(
    account: AccountFactory, roles: tuple[Role, ...]
) -> None:
    user = account(*roles)

    _request(user)

    assert selectors.mfa_state_of(user) == MfaState.PENDING_APPROVAL


@pytest.mark.parametrize("role", [Role.READER, Role.RESEARCHER])
def test_an_account_without_a_privileged_role_enrols_without_approval(
    account: AccountFactory, role: Role
) -> None:
    user = account(role)

    result = services.start_mfa_enrollment(actor=signed_in(user), password=PASSWORD, source=SOURCE)

    assert result.outcome == ACCEPTED
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION
    assert selectors.enrollment_request_number_of(user) is None
    assert _device(user).approved_at is None


def test_a_request_takes_the_role_from_the_record_not_from_the_caller(
    account: AccountFactory,
) -> None:
    # A role revoked: the account no longer needs approval. A stale object
    # that still looks privileged, or does not, changes nothing either way.
    user = account(Role.READER, Role.REVIEWER)
    services.revoke_role(
        actor=approving_administrator(), user=user, role=Role.REVIEWER, reason="TEST revocation"
    )

    services.start_mfa_enrollment(actor=signed_in(user), password=PASSWORD, source=SOURCE)

    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION
    assert set(inspect.signature(services.start_mfa_enrollment).parameters) == {
        "actor",
        "password",
        "source",
    }


def test_a_request_awaiting_approval_is_not_asked_for_at_sign_in_and_accepts_no_code(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    secret, _ = _request(user)

    result = _confirm(user, code_at(secret=secret))

    assert result.outcome == UNAVAILABLE
    assert result.context is None
    # Not examined, so not counted as a refused code either.
    assert _events() == ["mfa_enrollment_started"]
    assert _device(user).last_used_step is None
    sign_in = services.sign_in(email=user.email, password=PASSWORD, source=SOURCE)
    assert sign_in.outcome == SignInOutcome.SIGNED_IN


def test_requesting_again_gives_a_new_number_and_voids_the_old_one(
    account: AccountFactory,
) -> None:
    user = account(Role.REVIEWER)
    _, first = _request(user)

    second_secret, second = _request(user)

    assert second != first
    assert _approve(first).outcome == UNAVAILABLE
    assert selectors.mfa_state_of(user) == MfaState.PENDING_APPROVAL
    assert _approve(second).outcome == ACCEPTED
    assert _confirm(user, code_at(secret=second_secret)).outcome == ACCEPTED


def test_requesting_again_after_the_approval_needs_a_new_approval(
    account: AccountFactory,
) -> None:
    """Whoever knows the password cannot take over an approval given to someone else."""
    user = account(Role.ADMINISTRATOR)
    _, number = _request(user)
    assert _approve(number).outcome == ACCEPTED

    attacker_secret, attacker_number = _request(user, ATTACKER_SOURCE)

    device = _device(user)
    assert attacker_number != number
    assert device.state == TotpDeviceState.PENDING_APPROVAL
    assert (device.approved_at, device.approved_by) == (None, None)
    assert _confirm(user, code_at(secret=attacker_secret)).outcome == UNAVAILABLE
    assert _privileges(_claims_verified(user)) == set()


# --- Approving ------------------------------------------------------------------


@pytest.mark.parametrize("role", PRIVILEGED_ROLES)
def test_an_approval_lets_the_first_code_be_accepted_and_grants_nothing_itself(
    account: AccountFactory, role: Role
) -> None:
    user = account(role)
    secret, number = _request(user)
    approver = approving_administrator()

    result = _approve(number, approver)

    assert result.outcome == ACCEPTED
    assert result.context is None and result.provisioning is None
    device = _device(user)
    assert device.pk == number
    assert device.state == TotpDeviceState.PENDING_VERIFICATION
    assert device.approved_by == approver.user
    assert device.approved_at is not None
    assert device.confirmed_at is None
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION
    # Approved and not yet verified: still nothing privileged, for any context.
    for context in (signed_in(user), _claims_verified(user)):
        assert _privileges(context) == set()

    confirmed = _confirm(user, code_at(secret=secret))

    assert confirmed.outcome == ACCEPTED
    assert confirmed.context is not None
    assert _privileges(confirmed.context) != set()
    assert _privileges(signed_in(user)) == set()
    assert _events(user) == [
        "mfa_enrollment_started",
        "mfa_enrollment_approved",
        "mfa_enrollment_succeeded",
    ]


def test_an_approved_account_signs_in_with_its_code_and_holds_its_privileges(
    account: AccountFactory, clock: Clock
) -> None:
    user = account(Role.ADMINISTRATOR)
    secret, number = _request(user)
    _approve(number)
    _confirm(user, code_at(secret=secret))
    clock(STEP)

    challenge = services.sign_in(email=user.email, password=PASSWORD, source=SOURCE).challenge
    assert challenge is not None
    result = services.verify_second_factor(
        challenge=challenge, code=code_at(secret=secret), source=SOURCE
    )

    assert result.outcome == ACCEPTED
    assert selectors.can(result.context, Permission.ROLES_MANAGE) is True


def test_the_approval_is_recorded_naming_the_account_and_the_administrator(
    account: AccountFactory,
) -> None:
    user = account(Role.REVIEWER)
    _, number = _request(user)
    approver = approving_administrator()

    _approve(number, approver)

    event = AuthenticationEvent.objects.get(event_type="mfa_enrollment_approved")
    assert (event.user, event.actor) == (user, approver.user)
    started = AuthenticationEvent.objects.get(event_type="mfa_enrollment_started")
    assert started.actor is None
    # Counted with the account's other events, under the same key.
    assert event.identifier_key == started.identifier_key


@pytest.mark.parametrize(
    "kind",
    [
        "nobody",
        "bare-account",
        "administrator-on-a-password",
        "administrator-claiming-a-device-it-has-not",
        "administrator-with-an-unapproved-device",
        "administrator-with-a-pending-device",
        "deactivated-administrator",
        "verified-reviewer",
        "verified-researcher",
        "verified-reader",
        "no-role",
    ],
)
def test_only_an_administrator_verified_against_a_trusted_device_approves_or_rejects(
    account: AccountFactory, user_with_roles: UserFactory, kind: str
) -> None:
    target = account(Role.REVIEWER)
    _, number = _request(target)
    administrator = account(Role.ADMINISTRATOR)
    actor: object
    if kind == "nobody":
        actor = None
    elif kind == "bare-account":
        enrolled_device(administrator)
        actor = administrator
    elif kind == "administrator-on-a-password":
        enrolled_device(administrator)
        actor = signed_in(administrator)
    elif kind == "administrator-claiming-a-device-it-has-not":
        actor = AuthenticationContext(administrator, Assurance.MFA_VERIFIED, number)
    elif kind == "administrator-with-an-unapproved-device":
        device = enrolled_device(administrator, trusted=False)
        actor = AuthenticationContext(administrator, Assurance.MFA_VERIFIED, device.pk)
    elif kind == "administrator-with-a-pending-device":
        _, own = _request(administrator)
        actor = AuthenticationContext(administrator, Assurance.MFA_VERIFIED, own)
    elif kind == "deactivated-administrator":
        actor = verified(administrator)
        User.objects.filter(pk=administrator.pk).update(is_active=False)
    elif kind == "no-role":
        actor = verified(user_with_roles())
    else:
        role = {
            "verified-reviewer": Role.REVIEWER,
            "verified-researcher": Role.RESEARCHER,
            "verified-reader": Role.READER,
        }[kind]
        actor = verified(user_with_roles(role))
    before = TotpDevice.objects.values().get(pk=number)

    for operation in (services.approve_mfa_enrollment, services.reject_mfa_enrollment):
        with pytest.raises(PermissionDenied):
            operation(actor=actor, request_number=number, source=SOURCE)  # type: ignore[arg-type]  # the wrong kinds of actor are the point of the test

    assert TotpDevice.objects.values().get(pk=number) == before
    assert _events(target) == ["mfa_enrollment_started"]


def test_an_administrator_cannot_approve_their_own_request(account: AccountFactory) -> None:
    """With every context the account can have while its own request is pending."""
    administrator = account(Role.ADMINISTRATOR)
    _, number = _request(administrator)

    for context in (signed_in(administrator), _claims_verified(administrator)):
        for operation in (_approve, _reject):
            with pytest.raises(PermissionDenied):
                operation(number, context)

    device = _device(administrator)
    assert device.state == TotpDeviceState.PENDING_APPROVAL
    assert device.approved_at is None
    assert _events() == ["mfa_enrollment_started"]


@pytest.mark.parametrize("operation", ["approve", "reject"])
def test_the_rule_against_deciding_on_ones_own_request_holds_by_itself(
    account: AccountFactory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    operation: str,
) -> None:
    administrator = account(Role.ADMINISTRATOR)
    _, number = _request(administrator)
    # Suppose the permission check were bypassed or wrong.
    monkeypatch.setattr(selectors, "require_permission", lambda context, permission: None)
    decide = _approve if operation == "approve" else _reject
    caplog.clear()

    with (
        caplog.at_level(logging.WARNING, logger="caipo.accounts.services"),
        pytest.raises(PermissionDenied),
    ):
        decide(number, signed_in(administrator))

    assert _device(administrator).state == TotpDeviceState.PENDING_APPROVAL
    assert _device(administrator).approved_at is None
    assert [record.__dict__["event"] for record in caplog.records] == [
        "mfa.own_enrollment_decision_refused"
    ]
    assert _events() == ["mfa_enrollment_started"]


def test_an_approver_who_has_lost_the_device_approves_nothing(account: AccountFactory) -> None:
    target = account(Role.REVIEWER)
    _, number = _request(target)
    approver = approving_administrator()
    TotpDevice.objects.filter(user=approver.user).delete()

    with pytest.raises(PermissionDenied):
        _approve(number, approver)

    assert _device(target).state == TotpDeviceState.PENDING_APPROVAL


@pytest.mark.parametrize("operation", [_approve, _reject])
def test_a_request_that_does_not_await_a_decision_cannot_be_decided(
    account: AccountFactory, operation: Callable[[int], services.MfaResult]
) -> None:
    reader = account(Role.READER)
    services.start_mfa_enrollment(actor=signed_in(reader), password=PASSWORD, source=SOURCE)
    active = enrolled_device(account(Role.REVIEWER), trusted=False)
    approved_user = account(Role.REVIEWER)
    _, approved = _request(approved_user)
    assert _approve(approved).outcome == ACCEPTED
    before = list(TotpDevice.objects.order_by("id").values())
    events = _events()

    for number in (_device(reader).pk, active.pk, approved, 0, -1, 2**40):
        assert operation(number).outcome == UNAVAILABLE

    assert list(TotpDevice.objects.order_by("id").values()) == before
    assert _events() == events


def test_the_operations_take_a_request_number_and_no_account(account: AccountFactory) -> None:
    for operation in (services.approve_mfa_enrollment, services.reject_mfa_enrollment):
        assert set(inspect.signature(operation).parameters) == {
            "actor",
            "request_number",
            "source",
        }


# --- Rejecting ------------------------------------------------------------------


def test_a_rejection_discards_the_secret_and_is_recorded(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    secret, number = _request(user)
    approver = approving_administrator()

    result = _reject(number, approver)

    assert result.outcome == ACCEPTED
    assert not TotpDevice.objects.filter(user=user).exists()
    assert selectors.mfa_state_of(user) == MfaState.NOT_ENROLLED
    assert _confirm(user, code_at(secret=secret)).outcome == UNAVAILABLE
    assert _approve(number).outcome == UNAVAILABLE
    event = AuthenticationEvent.objects.get(event_type="mfa_enrollment_rejected")
    assert (event.user, event.actor) == (user, approver.user)
    # The account may ask again, and the new request is a new one.
    _, again = _request(user)
    assert again != number


# --- Lapsing ---------------------------------------------------------------------


def test_a_request_not_decided_in_time_is_void(
    account: AccountFactory, clock: Clock, settings: LazySettings
) -> None:
    user = account(Role.REVIEWER)
    _, number = _request(user)
    clock(settings.MFA_APPROVAL_LIFETIME - timedelta(seconds=1))
    assert selectors.mfa_state_of(user) == MfaState.PENDING_APPROVAL
    assert [item.number for item in _awaiting()] == [number]

    clock(timedelta(seconds=1))

    assert selectors.mfa_state_of(user) == MfaState.NOT_ENROLLED
    assert selectors.enrollment_request_number_of(user) is None
    assert _awaiting() == []
    assert _approve(number).outcome == UNAVAILABLE
    assert _reject(number).outcome == UNAVAILABLE
    assert _device(user).approved_at is None


def test_an_approved_enrolment_waits_for_its_first_code_from_the_approval(
    account: AccountFactory, clock: Clock, settings: LazySettings
) -> None:
    user = account(Role.REVIEWER)
    secret, number = _request(user)
    # Approved late, and long after a self-service enrolment would have lapsed.
    clock(settings.MFA_APPROVAL_LIFETIME - timedelta(seconds=1))
    assert _approve(number).outcome == ACCEPTED

    clock(settings.MFA_APPROVAL_LIFETIME - timedelta(seconds=1))
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION
    clock(timedelta(seconds=1))

    assert selectors.mfa_state_of(user) == MfaState.NOT_ENROLLED
    assert _confirm(user, code_at(secret=secret)).outcome == UNAVAILABLE
    assert _device(user).state == TotpDeviceState.PENDING_VERIFICATION


def test_an_approved_enrolment_is_confirmed_just_in_time(
    account: AccountFactory, clock: Clock, settings: LazySettings
) -> None:
    user = account(Role.REVIEWER)
    secret, number = _request(user)
    _approve(number)
    clock(settings.MFA_APPROVAL_LIFETIME - timedelta(seconds=1))

    assert _confirm(user, code_at(secret=secret)).outcome == ACCEPTED


# --- The list an Administrator decides from --------------------------------------


def _awaiting() -> list[selectors.EnrollmentRequest]:
    return selectors.enrollment_requests_awaiting_approval(approving_administrator())


def test_the_list_holds_what_awaits_a_decision_oldest_first(
    account: AccountFactory, clock: Clock
) -> None:
    first, second = account(Role.REVIEWER), account(Role.ADMINISTRATOR)
    reader = account(Role.READER)
    services.start_mfa_enrollment(actor=signed_in(reader), password=PASSWORD, source=SOURCE)
    enrolled_device(account(Role.REVIEWER))
    _, first_number = _request(first)
    clock(STEP)
    _, second_number = _request(second)

    listed = _awaiting()

    assert [(item.number, item.email) for item in listed] == [
        (first_number, first.email),
        (second_number, second.email),
    ]
    assert listed[0].requested_at < listed[1].requested_at
    # A request carries nothing of the secret.
    assert set(vars(listed[0])) == {"number", "email", "requested_at"}

    _approve(first_number)
    assert [item.number for item in _awaiting()] == [second_number]


def test_the_list_never_holds_the_request_of_whoever_is_looking(
    account: AccountFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    administrator = account(Role.ADMINISTRATOR)
    _request(administrator)
    _, other = _request(account(Role.REVIEWER))
    # An Administrator who can look has an active device and so no request.
    # Suppose the permission check were bypassed or wrong: the rule still holds.
    monkeypatch.setattr(selectors, "require_permission", lambda context, permission: None)

    listed = selectors.enrollment_requests_awaiting_approval(signed_in(administrator))

    assert [item.number for item in listed] == [other]


@pytest.mark.parametrize("role", list(Role))
def test_the_list_is_refused_to_a_password_and_to_every_other_role(
    account: AccountFactory, role: Role
) -> None:
    user = account(role)
    contexts: list[AuthenticationContext] = [signed_in(user)]
    if role != Role.ADMINISTRATOR:
        contexts.append(verified(user))

    for context in contexts:
        with pytest.raises(PermissionDenied):
            selectors.enrollment_requests_awaiting_approval(context)


# --- A device that nobody approved ----------------------------------------------


@pytest.mark.parametrize("role", PRIVILEGED_ROLES)
def test_a_device_enrolled_before_the_role_was_granted_is_not_trusted(
    account: AccountFactory, role: Role, clock: Clock
) -> None:
    """Enrolling on a password first and being promoted afterwards is no way round."""
    user = account(Role.READER)
    started = services.start_mfa_enrollment(actor=signed_in(user), password=PASSWORD, source=SOURCE)
    assert started.provisioning is not None
    secret = base64.b32decode(started.provisioning.secret)
    enrolled = _confirm(user, code_at(secret=secret))
    assert enrolled.outcome == ACCEPTED

    services.grant_role(actor=approving_administrator(), user=user, role=role, reason="TEST grant")

    # Neither the context from the enrolment nor a fresh sign-in with the code.
    assert _privileges(enrolled.context) == set()
    clock(STEP)
    challenge = services.sign_in(email=user.email, password=PASSWORD, source=SOURCE).challenge
    assert challenge is not None
    result = services.verify_second_factor(
        challenge=challenge, code=code_at(secret=secret), source=SOURCE
    )
    assert result.outcome == ACCEPTED
    assert _privileges(result.context) == set()
    assert selectors.permissions_of(result.context) == {OWN_MFA, Permission.WORKSPACE_READ}


def test_an_enrolment_started_before_the_role_was_granted_is_not_trusted(
    account: AccountFactory,
) -> None:
    user = account(Role.READER)
    started = services.start_mfa_enrollment(actor=signed_in(user), password=PASSWORD, source=SOURCE)
    assert started.provisioning is not None
    services.grant_role(
        actor=approving_administrator(), user=user, role=Role.ADMINISTRATOR, reason="TEST grant"
    )

    confirmed = _confirm(user, code_at(secret=base64.b32decode(started.provisioning.secret)))

    assert confirmed.outcome == ACCEPTED
    assert _device(user).approved_at is None
    assert confirmed.context is not None
    assert _privileges(confirmed.context) == set()
    with pytest.raises(PermissionDenied):
        services.grant_role(
            actor=confirmed.context, user=account(), role=Role.READER, reason="TEST attempt"
        )


def test_an_unapproved_device_becomes_trusted_only_by_replacing_it_with_an_approved_one(
    account: AccountFactory, clock: Clock
) -> None:
    user = account(Role.READER, Role.REVIEWER)
    device = enrolled_device(user, trusted=False)
    untrusted = AuthenticationContext(user, Assurance.MFA_VERIFIED, device.pk)
    assert _privileges(untrusted) == set()

    replaced = services.replace_mfa_device(
        actor=untrusted, password=PASSWORD, code=code_at(), source=SOURCE
    )

    assert replaced.outcome == ACCEPTED
    assert replaced.provisioning is not None
    assert selectors.mfa_state_of(user) == MfaState.PENDING_APPROVAL
    number = selectors.enrollment_request_number_of(user)
    assert number is not None
    _approve(number)
    secret = base64.b32decode(replaced.provisioning.secret)
    confirmed = _confirm(user, code_at(secret=secret))
    assert Permission.RESEARCH_REVIEW in selectors.permissions_of(confirmed.context)


# --- Replacing an active device -------------------------------------------------


def _replace(
    actor: AuthenticationContext, password: str = PASSWORD, code: str | None = None
) -> services.MfaResult:
    return services.replace_mfa_device(
        actor=actor, password=password, code=code if code is not None else code_at(), source=SOURCE
    )


@pytest.mark.parametrize("role", list(Role))
def test_a_password_alone_does_not_replace_an_active_device(
    account: AccountFactory, role: Role
) -> None:
    user = account(role)
    actor = verified(user)
    before = TotpDevice.objects.values().get(user=user)

    for context in (signed_in(user), actor):
        started = services.start_mfa_enrollment(actor=context, password=PASSWORD, source=SOURCE)
        assert started.outcome == UNAVAILABLE
        assert started.provisioning is None
        for code in ("", "000000", "12345", "abcdef"):
            result = _replace(context, code=code)
            assert result.outcome in {REFUSED, MfaOutcome.THROTTLED}
            assert result.provisioning is None

    after = TotpDevice.objects.values().get(user=user)
    assert (after["id"], bytes(after["secret_ciphertext"]), after["state"]) == (
        before["id"],
        bytes(before["secret_ciphertext"]),
        before["state"],
    )
    assert "mfa_device_replaced" not in _events()
    assert "mfa_enrollment_started" not in _events()


def test_a_code_alone_does_not_replace_an_active_device(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    actor = verified(user)

    result = _replace(actor, password=WRONG)

    assert result.outcome == REFUSED
    assert selectors.mfa_state_of(user) == MfaState.ACTIVE
    assert _events() == ["password_confirmation_failed"]
    assert selectors.can(actor, Permission.ROLES_MANAGE) is True


@pytest.mark.parametrize("role", PRIVILEGED_ROLES)
def test_replacing_with_both_proofs_gives_up_the_device_and_awaits_approval(
    account: AccountFactory, role: Role, clock: Clock
) -> None:
    user = account(role)
    actor = verified(user)
    old = _device(user)
    assert _privileges(actor) != set()

    result = _replace(actor)

    assert result.outcome == ACCEPTED
    assert result.provisioning is not None
    assert result.context is None
    new = _device(user)
    assert new.pk != old.pk
    assert new.state == TotpDeviceState.PENDING_APPROVAL
    # The trust in the old device does not pass to the new one.
    assert (new.approved_at, new.approved_by) == (None, None)
    assert base64.b32decode(result.provisioning.secret) != b"TEST-totp-secret-000"
    assert _events(user) == ["mfa_device_replaced", "mfa_enrollment_started"]
    # Every context of the account, old or new, is without privileges.
    for context in (actor, signed_in(user), _claims_verified(user)):
        assert _privileges(context) == set()
    # A code for the new secret is not accepted before the approval.
    secret = base64.b32decode(result.provisioning.secret)
    clock(STEP)
    assert _confirm(user, code_at(secret=secret)).outcome == UNAVAILABLE
    # The old authenticator is of no use any more.
    assert services.sign_in(email=user.email, password=PASSWORD, source=SOURCE).outcome == (
        SignInOutcome.SIGNED_IN
    )


@pytest.mark.parametrize("role", [Role.READER, Role.RESEARCHER])
def test_replacing_needs_both_proofs_for_every_account_and_approval_only_for_privileged_ones(
    account: AccountFactory, role: Role
) -> None:
    user = account(role)
    actor = verified(user)

    result = _replace(actor)

    assert result.outcome == ACCEPTED
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION
    assert _device(user).approved_at is None


def test_a_code_already_used_does_not_replace(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    actor = verified(user)
    challenge = services.sign_in(email=user.email, password=PASSWORD, source=SOURCE).challenge
    assert challenge is not None
    code = code_at()
    assert (
        services.verify_second_factor(challenge=challenge, code=code, source=SOURCE).outcome
        == ACCEPTED
    )

    assert _replace(actor, code=code).outcome == REFUSED
    assert selectors.mfa_state_of(user) == MfaState.ACTIVE


def test_replacing_is_throttled_with_every_other_use_of_a_code(
    account: AccountFactory, settings: LazySettings
) -> None:
    user = account(Role.ADMINISTRATOR)
    actor = verified(user)
    for _ in range(settings.MFA_THROTTLE_FAILURES):
        assert _replace(actor, code="000000").outcome == REFUSED

    assert _replace(actor).outcome == MfaOutcome.THROTTLED
    assert selectors.mfa_state_of(user) == MfaState.ACTIVE


@pytest.mark.parametrize("state", ["none", "awaiting-approval", "awaiting-code"])
def test_replacing_without_an_active_device_is_not_possible(
    account: AccountFactory, state: str
) -> None:
    user = account(Role.REVIEWER)
    if state != "none":
        _, number = _request(user)
        if state == "awaiting-code":
            _approve(number)
    before = list(TotpDevice.objects.filter(user=user).values())

    assert _replace(signed_in(user)).outcome == UNAVAILABLE
    assert list(TotpDevice.objects.filter(user=user).values()) == before


def test_replacing_removes_a_pending_challenge(account: AccountFactory, clock: Clock) -> None:
    user = account(Role.ADMINISTRATOR)
    actor = verified(user)
    challenge = services.sign_in(email=user.email, password=PASSWORD, source=SOURCE).challenge
    assert challenge is not None

    assert _replace(actor).outcome == ACCEPTED

    assert not MfaChallenge.objects.exists()
    clock(STEP)
    result = services.verify_second_factor(challenge=challenge, code=code_at(), source=SOURCE)
    assert result.outcome == REFUSED


def test_nobody_replaces_the_device_of_another_account(account: AccountFactory) -> None:
    victim = account(Role.REVIEWER)
    enrolled_device(victim)
    administrator = account(Role.ADMINISTRATOR)

    assert set(inspect.signature(services.replace_mfa_device).parameters) == {
        "actor",
        "password",
        "code",
        "source",
    }
    assert _replace(verified(administrator)).outcome == ACCEPTED
    assert selectors.mfa_state_of(victim) == MfaState.ACTIVE


def test_disabling_and_enrolling_again_needs_approval_again(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    actor = verified(user)
    disabled = services.disable_mfa(actor=actor, password=PASSWORD, code=code_at(), source=SOURCE)
    assert disabled.outcome == ACCEPTED

    secret, _ = _request(user)

    assert selectors.mfa_state_of(user) == MfaState.PENDING_APPROVAL
    assert _confirm(user, code_at(secret=secret)).outcome == UNAVAILABLE
    assert _privileges(_claims_verified(user)) == set()


# --- What is recorded -------------------------------------------------------------


def test_no_secret_or_code_reaches_the_events_or_the_logs_of_the_approval_flow(
    account: AccountFactory, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    user = account(Role.ADMINISTRATOR)
    rejected = account(Role.REVIEWER)
    used: list[str] = [PASSWORD, user.email, rejected.email]

    with caplog.at_level(logging.DEBUG):
        for requester in (user, rejected):
            result = services.start_mfa_enrollment(
                actor=signed_in(requester), password=PASSWORD, source=SOURCE
            )
            assert result.provisioning is not None
            used += [result.provisioning.secret, result.provisioning.uri]
            if requester == user:
                secret = base64.b32decode(result.provisioning.secret)
        used.append(secret.hex())
        number = selectors.enrollment_request_number_of(user)
        other = selectors.enrollment_request_number_of(rejected)
        assert number is not None and other is not None
        used.append(code_at(secret=secret))
        _confirm(user, used[-1])
        assert _approve(number).outcome == ACCEPTED
        assert _reject(other).outcome == ACCEPTED
        clock(STEP)
        used.append(code_at(secret=secret))
        confirmed = _confirm(user, used[-1])
        assert confirmed.context is not None
        clock(STEP)
        used.append(code_at(secret=secret))
        replaced = _replace(confirmed.context, code=used[-1])
        assert replaced.provisioning is not None
        used += [replaced.provisioning.secret, replaced.provisioning.uri]
        written = logged(caplog.records) + repr(replaced) + repr(result)

    stored = repr(
        [
            list(AuthenticationEvent.objects.values()),
            list(RoleEvent.objects.values()),
            list(TotpDevice.objects.values("id", "state", "key_id", "approved_at")),
        ]
    )
    assert {
        "mfa_enrollment_started",
        "mfa_enrollment_approved",
        "mfa_enrollment_rejected",
        "mfa_enrollment_succeeded",
        "mfa_device_replaced",
    } <= set(_events())
    for value in used:
        assert value not in stored, value
        assert value not in written, value
    assert "otpauth" not in stored + written


def test_every_event_of_the_flow_names_its_account_and_only_decisions_name_an_actor(
    account: AccountFactory,
) -> None:
    user = account(Role.REVIEWER)
    _, number = _request(user)
    approver = approving_administrator()
    _approve(number, approver)

    events = AuthenticationEvent.objects.order_by("id")

    assert [(event.event_type, event.user, event.actor) for event in events] == [
        ("mfa_enrollment_started", user, None),
        ("mfa_enrollment_approved", user, approver.user),
    ]


@pytest.mark.parametrize(
    ("operation", "event"),
    [("approve", "mfa.enrollment_approved"), ("reject", "mfa.enrollment_rejected")],
)
def test_a_decision_is_logged_by_account_identifiers(
    account: AccountFactory, caplog: pytest.LogCaptureFixture, operation: str, event: str
) -> None:
    user = account(Role.REVIEWER)
    _, number = _request(user)
    approver = approving_administrator()

    with caplog.at_level(logging.INFO, logger="caipo.accounts.services"):
        (_approve if operation == "approve" else _reject)(number, approver)

    (record,) = [record for record in caplog.records if record.__dict__.get("event") == event]
    assert record.__dict__["user_id"] == user.pk
    assert record.__dict__["actor_id"] == approver.user.pk
    assert user.email not in logged(caplog.records)


# --- The first Administrator can approve -----------------------------------------


def test_the_first_administrator_approves_with_the_device_from_the_bootstrap(
    account: AccountFactory, clock: Clock
) -> None:
    email, password = "test.administrator@caipo.test", "TEST-correct-horse-battery-staple"
    enrollment = services.prepare_first_administrator(email=email, password=password)
    services.create_first_administrator(
        email=email,
        password=password,
        operator="TEST-operator",
        enrollment=enrollment,
        code=code_at(secret=enrollment.secret),
    )
    reviewer = account(Role.REVIEWER)
    secret, number = _request(reviewer)
    clock(STEP)
    challenge = services.sign_in(email=email, password=password, source=SOURCE).challenge
    assert challenge is not None
    first = services.verify_second_factor(
        challenge=challenge, code=code_at(secret=enrollment.secret), source=SOURCE
    ).context
    assert first is not None

    assert _approve(number, first).outcome == ACCEPTED

    confirmed = _confirm(reviewer, code_at(secret=secret))
    assert Permission.RESEARCH_REVIEW in selectors.permissions_of(confirmed.context)
    assert _device(reviewer).approved_by == first.user
