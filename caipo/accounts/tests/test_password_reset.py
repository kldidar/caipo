"""Resetting a forgotten password through the services (ADR-0016): asking for the
message, and setting the password with the token it carries.

No HTTP is involved. Messages go to the in-memory backend, and the token is read
from the message as the person receiving it would read it.
"""

import inspect
import logging
import re
from datetime import timedelta

import pytest
from django.conf import LazySettings
from django.core import mail as django_mail
from django.db import IntegrityError, connection, models, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from caipo.accounts import selectors, services
from caipo.accounts.models import (
    AccountActivation,
    AccountEvent,
    AccountStatus,
    AuthenticationEvent,
    MfaChallenge,
    PasswordReset,
    RoleEvent,
    TotpDevice,
    User,
)
from caipo.accounts.selectors import MfaState, Permission, Role
from caipo.accounts.services import (
    ActivationOutcome,
    MfaOutcome,
    PasswordResetOutcome,
    PasswordResetResult,
    SignInOutcome,
)
from caipo.accounts.tests.fixtures import (
    Clock,
    UserFactory,
    approving_administrator,
    code_at,
    enrolled_device,
    logged,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db]

# Visibly synthetic fixture values.
EMAIL = "test.forgetful@caipo.test"
OTHER_EMAIL = "test.other.forgetful@caipo.test"
UNKNOWN = "test.nobody@caipo.test"
OLD_PASSWORD = "TEST-passphrase-that-was-forgotten"
PASSWORD = "TEST-passphrase-chosen-afterwards"
OTHER_PASSWORD = "TEST-another-passphrase-entirely"
SOURCE = "203.0.113.10"
OTHER_SOURCE = "198.51.100.66"
ORIGIN = "https://caipo.test"

RESET = PasswordResetOutcome.RESET
REFUSED = PasswordResetOutcome.REFUSED
THROTTLED = PasswordResetOutcome.THROTTLED
PASSWORD_REFUSED = PasswordResetOutcome.PASSWORD_REFUSED

REQUESTED = "password_reset_requested"
SUCCEEDED = "password_reset_succeeded"
FAILED = "password_reset_failed"


def reset_url(token: str) -> str:
    return f"{ORIGIN}/password-reset/confirm/#{token}"


def _account(email: str = EMAIL, *, status: AccountStatus = AccountStatus.ACTIVE) -> User:
    """Return a synthetic account in the given state, with the password that was forgotten.

    Written directly: an active account that was activated by its owner, one
    that awaits verification, or one that was activated and then disabled.
    """
    now = timezone.now()
    verified = None if status == AccountStatus.PENDING_VERIFICATION else now
    user = User(email=email, status=status, email_verified_at=verified, activated_at=verified)
    user.set_password(OLD_PASSWORD)
    user.save()
    return user


def _request(email: str = EMAIL, source: str = SOURCE) -> None:
    services.request_password_reset(email=email, source=source, reset_url=reset_url)


def _token(index: int = -1) -> str:
    """Read the token off a reset message, by default the last one sent."""
    (token,) = re.findall(
        rf"{re.escape(ORIGIN)}/password-reset/confirm/#(\S+)", str(django_mail.outbox[index].body)
    )
    return str(token)


def _requested(email: str = EMAIL) -> str:
    """Ask for a reset and return the token that was sent."""
    sent = len(django_mail.outbox)
    _request(email)
    assert len(django_mail.outbox) == sent + 1
    return _token()


def _reset(token: str, password: str = PASSWORD, source: str = SOURCE) -> PasswordResetResult:
    return services.reset_password(token=token, password=password, source=source)


def _events() -> list[tuple[str, int | None]]:
    return list(AuthenticationEvent.objects.order_by("id").values_list("event_type", "user_id"))


def _stored(user: User) -> User:
    return User.objects.get(pk=user.pk)


def _sign_in(email: str, password: str, source: str = SOURCE) -> SignInOutcome:
    return services.sign_in(email=email, password=password, source=source).outcome


def _key(purpose: str, value: str) -> str:
    return services._key(purpose, value)


# --- Asking for a reset ---------------------------------------------------------------


def test_an_active_account_is_sent_one_message_and_given_one_token(clock: Clock) -> None:
    user = _account()

    _request()

    (message,) = django_mail.outbox
    assert message.to == [EMAIL]
    reset = PasswordReset.objects.get()
    assert reset.user == user
    assert reset.token_key == _key("password_reset", _token())
    assert reset.created_at == timezone.now()
    assert reset.expires_at == timezone.now() + timedelta(hours=1)
    assert _events() == [(REQUESTED, user.pk)]
    # Asking changes nothing about the account.
    assert _stored(user).check_password(OLD_PASSWORD) is True


def test_an_address_with_no_account_gets_no_token_and_no_message() -> None:
    _account()

    _request(UNKNOWN)

    assert django_mail.outbox == []
    assert not PasswordReset.objects.exists()
    assert _events() == [(REQUESTED, None)]


@pytest.mark.parametrize("status", [AccountStatus.PENDING_VERIFICATION, AccountStatus.DISABLED])
def test_an_account_that_is_not_active_is_treated_as_no_account(status: AccountStatus) -> None:
    user = _account(status=status)

    _request()

    assert django_mail.outbox == []
    assert not PasswordReset.objects.exists()
    # The record names the account the address belongs to; nothing else does.
    assert _events() == [(REQUESTED, user.pk)]
    assert _stored(user).status == status


def test_the_first_administrator_is_eligible_although_its_address_was_never_verified(
    user_with_roles: UserFactory,
) -> None:
    # The bootstrap creates the account through the manager, active and unverified.
    administrator = user_with_roles(Role.ADMINISTRATOR)
    assert administrator.email_verified_at is None

    token = _requested(administrator.email)

    assert _reset(token).outcome == RESET
    stored = _stored(administrator)
    assert stored.check_password(PASSWORD) is True
    # A reset verifies no address.
    assert stored.email_verified_at is None


@pytest.mark.parametrize(
    "typed",
    ["Test.Forgetful@CAIPO.Test", "  test.forgetful@caipo.test  ", "test.ﬀorgetful@caipo.test"],
)
def test_the_email_is_matched_in_its_normalized_form(typed: str) -> None:
    user = _account("test.fforgetful@caipo.test" if "ﬀ" in typed else EMAIL)

    _request(typed)

    assert PasswordReset.objects.get().user == user
    (message,) = django_mail.outbox
    assert message.to == [user.email]
    # Counted under the same key however it was typed.
    (event,) = AuthenticationEvent.objects.all()
    assert event.identifier_key == _key("identifier", user.email)


def test_the_service_tells_its_caller_nothing() -> None:
    _account()
    _account(OTHER_EMAIL, status=AccountStatus.DISABLED)

    for email in (EMAIL, OTHER_EMAIL, UNKNOWN):
        _request(email)

    assert inspect.signature(services.request_password_reset).return_annotation is None
    assert set(inspect.signature(services.request_password_reset).parameters) == {
        "email",
        "source",
        "reset_url",
    }


def test_asking_again_replaces_the_token(clock: Clock) -> None:
    user = _account()
    first = _requested()
    clock(timedelta(minutes=10))

    second = _requested()

    assert first != second
    reset = PasswordReset.objects.get()
    assert reset.token_key == _key("password_reset", second)
    # The lifetime starts again with the new token.
    assert reset.expires_at == timezone.now() + timedelta(hours=1)
    assert _reset(first).outcome == REFUSED
    assert _stored(user).check_password(OLD_PASSWORD) is True
    assert _reset(second).outcome == RESET


def test_a_message_that_cannot_be_sent_changes_nothing_a_caller_can_see(
    settings: LazySettings, caplog: pytest.LogCaptureFixture
) -> None:
    user = _account()
    settings.EMAIL_BACKEND = "caipo.core.mail.RefusingEmailBackend"

    with caplog.at_level(logging.DEBUG, logger="caipo.accounts.services"):
        _request()

    assert django_mail.outbox == []
    assert _events() == [(REQUESTED, user.pk)]
    record = next(r for r in caplog.records if r.levelno == logging.ERROR)
    assert record.__dict__["event"] == "password_reset.message_not_sent"
    assert record.__dict__["user_id"] == user.pk
    assert record.__dict__["cause"] == "DeliveryNotConfiguredError"
    assert record.exc_info is None
    written = logged(caplog.records)
    for forbidden in (EMAIL, ORIGIN, "password-reset/confirm", "#"):
        assert forbidden not in written, forbidden
    assert _stored(user).check_password(OLD_PASSWORD) is True

    # Once messages can be sent, asking again works.
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    assert _reset(_requested()).outcome == RESET


def test_the_link_is_made_by_the_caller_and_the_service_knows_no_address() -> None:
    _account()
    seen: list[str] = []

    def elsewhere(token: str) -> str:
        seen.append(token)
        return f"https://elsewhere.test/r/#{token}"

    services.request_password_reset(email=EMAIL, source=SOURCE, reset_url=elsewhere)
    services.request_password_reset(email=UNKNOWN, source=SOURCE, reset_url=elsewhere)

    (message,) = django_mail.outbox
    # Asked for a link once: only the eligible account has a token.
    assert len(seen) == 1
    assert f"https://elsewhere.test/r/#{seen[0]}" in str(message.body)
    source = inspect.getsource(services)
    assert "PUBLIC_BASE_URL" not in source
    assert "reverse(" not in source


# --- Throttling of requests -------------------------------------------------------------


def test_the_limit_on_requests_for_one_email_address_is_exact(settings: LazySettings) -> None:
    user = _account()
    limit = settings.PASSWORD_RESET_REQUEST_EMAIL_LIMIT

    for number in range(limit):
        _request(source=f"203.0.113.{number}")
    assert len(django_mail.outbox) == limit
    fifth = _token()

    _request(source=OTHER_SOURCE)

    # The request beyond the limit issued no token, sent nothing, and stored nothing.
    assert len(django_mail.outbox) == limit
    assert PasswordReset.objects.get().token_key == _key("password_reset", fifth)
    assert _events() == [(REQUESTED, user.pk)] * limit


def test_the_limits_are_five_an_hour_for_an_address_and_twenty_in_fifteen_minutes_for_a_source(
    settings: LazySettings,
) -> None:
    assert settings.PASSWORD_RESET_REQUEST_EMAIL_LIMIT == 5
    assert settings.PASSWORD_RESET_REQUEST_EMAIL_WINDOW == timedelta(hours=1)
    assert settings.PASSWORD_RESET_REQUEST_SOURCE_LIMIT == 20
    assert settings.PASSWORD_RESET_REQUEST_SOURCE_WINDOW == timedelta(minutes=15)


def test_the_limit_on_requests_from_one_source_is_exact(settings: LazySettings) -> None:
    _account()
    limit = settings.PASSWORD_RESET_REQUEST_SOURCE_LIMIT

    for number in range(limit - 1):
        _request(f"test.nobody{number}@caipo.test")
    _request()
    assert len(django_mail.outbox) == 1
    assert AuthenticationEvent.objects.count() == limit

    _account(OTHER_EMAIL)
    _request(OTHER_EMAIL)

    assert len(django_mail.outbox) == 1
    assert not PasswordReset.objects.filter(user__email=OTHER_EMAIL).exists()
    assert AuthenticationEvent.objects.count() == limit


def test_requests_count_whether_or_not_the_address_has_an_account(settings: LazySettings) -> None:
    limit = settings.PASSWORD_RESET_REQUEST_EMAIL_LIMIT
    for number in range(limit + 3):
        _request(UNKNOWN, source=f"203.0.113.{number}")

    assert _events() == [(REQUESTED, None)] * limit

    # An account created for the address meanwhile is throttled all the same.
    _account(UNKNOWN)
    _request(UNKNOWN)
    assert django_mail.outbox == []


def test_the_two_limits_are_independent(settings: LazySettings) -> None:
    _account()
    _account(OTHER_EMAIL)
    for number in range(settings.PASSWORD_RESET_REQUEST_EMAIL_LIMIT):
        _request(source=f"203.0.113.{number}")
    sent = len(django_mail.outbox)

    # The address is throttled from every source; another address is not.
    _request(source=OTHER_SOURCE)
    assert len(django_mail.outbox) == sent
    _request(OTHER_EMAIL, source="203.0.113.0")
    assert len(django_mail.outbox) == sent + 1

    # A source at its limit is throttled for every address; another source is not.
    for number in range(settings.PASSWORD_RESET_REQUEST_SOURCE_LIMIT):
        _request(f"test.nobody{number}@caipo.test", source="192.0.2.1")
    sent = len(django_mail.outbox)
    _request(OTHER_EMAIL, source="192.0.2.1")
    assert len(django_mail.outbox) == sent
    _request(OTHER_EMAIL, source="192.0.2.2")
    assert len(django_mail.outbox) == sent + 1


def test_the_limit_for_an_address_lifts_by_itself_and_only_after_the_window(
    clock: Clock, settings: LazySettings
) -> None:
    _account()
    for number in range(settings.PASSWORD_RESET_REQUEST_EMAIL_LIMIT):
        _request(source=f"203.0.113.{number}")
    sent = len(django_mail.outbox)

    clock(settings.PASSWORD_RESET_REQUEST_EMAIL_WINDOW)
    _request(source=OTHER_SOURCE)
    assert len(django_mail.outbox) == sent

    clock(timedelta(seconds=1))
    _request(source=OTHER_SOURCE)
    assert len(django_mail.outbox) == sent + 1


def test_the_limit_for_a_source_lifts_by_itself_and_only_after_the_window(
    clock: Clock, settings: LazySettings
) -> None:
    _account()
    for number in range(settings.PASSWORD_RESET_REQUEST_SOURCE_LIMIT):
        _request(f"test.nobody{number}@caipo.test")

    clock(settings.PASSWORD_RESET_REQUEST_SOURCE_WINDOW)
    _request()
    assert django_mail.outbox == []

    clock(timedelta(seconds=1))
    _request()
    assert len(django_mail.outbox) == 1


def test_nothing_clears_the_count_of_requests_early(settings: LazySettings) -> None:
    _account()
    limit = settings.PASSWORD_RESET_REQUEST_EMAIL_LIMIT
    for number in range(limit - 1):
        _request(source=f"203.0.113.{number}")
    assert _reset(_token()).outcome == RESET
    assert _sign_in(EMAIL, PASSWORD) == SignInOutcome.SIGNED_IN

    _request(source=OTHER_SOURCE)
    assert len(django_mail.outbox) == limit
    _request(source=OTHER_SOURCE)
    assert len(django_mail.outbox) == limit


def test_a_throttled_request_is_logged_and_says_which_limit(
    caplog: pytest.LogCaptureFixture, settings: LazySettings
) -> None:
    settings.PASSWORD_RESET_REQUEST_EMAIL_LIMIT = 1
    settings.PASSWORD_RESET_REQUEST_SOURCE_LIMIT = 2
    _request(UNKNOWN)

    with caplog.at_level(logging.DEBUG, logger="caipo.accounts.services"):
        _request(UNKNOWN)
        _request("test.nobody2@caipo.test")
        _request("test.nobody3@caipo.test")

    throttled = [
        record.__dict__["scope"]
        for record in caplog.records
        if record.__dict__.get("event") == "password_reset.request_throttled"
    ]
    assert throttled == ["email", "source"]
    assert AuthenticationEvent.objects.count() == 2
    assert "caipo.test" not in logged(caplog.records)


def test_reset_requests_and_sign_in_failures_are_counted_apart(settings: LazySettings) -> None:
    _account()
    for _ in range(settings.LOGIN_THROTTLE_ACCOUNT_FAILURES):
        assert _sign_in(EMAIL, OTHER_PASSWORD) == SignInOutcome.REFUSED
    assert _sign_in(EMAIL, OLD_PASSWORD) == SignInOutcome.THROTTLED

    # Throttled sign-in does not stop a reset from being asked for...
    token = _requested()
    for _ in range(settings.PASSWORD_RESET_REQUEST_EMAIL_LIMIT):
        _request(source=OTHER_SOURCE)

    # ...and requests, throttled or not, are not sign-in failures.
    assert AuthenticationEvent.objects.filter(event_type="login_failure").count() == 5
    assert token != _token()


# --- The token ----------------------------------------------------------------------------


def test_a_token_is_256_random_bits_and_only_its_keyed_hash_is_stored() -> None:
    _account()
    _account(OTHER_EMAIL)

    first, second = _requested(), _requested(OTHER_EMAIL)

    assert first != second
    # 32 bytes as unpadded URL-safe base64.
    assert len(first) == 43
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", first)
    stored = repr(list(PasswordReset.objects.values()))
    assert first not in stored and second not in stored
    keys = set(PasswordReset.objects.values_list("token_key", flat=True))
    assert keys == {_key("password_reset", first), _key("password_reset", second)}
    assert all(re.fullmatch(r"[0-9a-f]{64}", key) for key in keys)


def test_the_stored_key_cannot_be_used_as_the_token() -> None:
    user = _account()
    _requested()

    assert _reset(PasswordReset.objects.get().token_key).outcome == REFUSED
    assert _stored(user).check_password(OLD_PASSWORD) is True


def test_the_token_resets_the_password_and_nothing_else(clock: Clock) -> None:
    user = _account()
    before = User.objects.filter(pk=user.pk).values().get()
    token = _requested()
    clock(timedelta(minutes=30))

    result = _reset(token)

    assert result == PasswordResetResult(RESET)
    stored = _stored(user)
    assert stored.check_password(PASSWORD) is True
    assert stored.check_password(OLD_PASSWORD) is False
    after = User.objects.filter(pk=user.pk).values().get()
    changed = {name for name, value in before.items() if value != dict(after)[name]}
    assert changed == {"password", "updated_at"}
    assert not PasswordReset.objects.exists()
    assert _events() == [(REQUESTED, user.pk), (SUCCEEDED, user.pk)]
    assert _sign_in(EMAIL, OLD_PASSWORD) == SignInOutcome.REFUSED
    assert _sign_in(EMAIL, PASSWORD) == SignInOutcome.SIGNED_IN


def test_a_reset_signs_nobody_in_and_takes_no_account_from_the_caller() -> None:
    _account()
    token = _requested()

    result = _reset(token)

    assert set(vars(result)) == {"outcome", "password_errors"}
    assert set(inspect.signature(services.reset_password).parameters) == {
        "token",
        "password",
        "source",
    }
    assert not AuthenticationEvent.objects.filter(event_type="login_success").exists()
    # No path from the reset to a session: the service does not know Django's sign-in.
    source = inspect.getsource(services)
    assert "login(" not in source
    assert "update_session_auth_hash" not in source


def test_a_token_works_once() -> None:
    user = _account()
    token = _requested()
    assert _reset(token).outcome == RESET

    again = _reset(token, OTHER_PASSWORD)

    assert again == PasswordResetResult(REFUSED)
    assert _stored(user).check_password(PASSWORD) is True
    # Used, the token belongs to no account any more.
    assert _events()[-1] == (FAILED, None)


@pytest.mark.parametrize(
    "token", ["", "x", "A" * 43, "A" * 4000, "../../etc/passwd", "' OR 1=1 --", "\x00"]
)
def test_a_wrong_or_malformed_token_changes_nothing_and_names_nobody(token: str) -> None:
    user = _account()
    good = _requested()

    result = _reset(token)

    assert result == PasswordResetResult(REFUSED)
    assert _stored(user).check_password(OLD_PASSWORD) is True
    (event,) = AuthenticationEvent.objects.filter(event_type=FAILED)
    assert (event.user, event.actor, event.identifier_key) == (None, None, "")
    assert event.source_key == _key("source", SOURCE)
    # The good token is untouched.
    assert _reset(good).outcome == RESET


def test_a_token_lapses_after_exactly_one_hour(clock: Clock, settings: LazySettings) -> None:
    assert settings.PASSWORD_RESET_LIFETIME == timedelta(hours=1)
    user = _account()
    token = _requested()

    clock(timedelta(hours=1))

    assert _reset(token) == PasswordResetResult(REFUSED)
    assert _stored(user).check_password(OLD_PASSWORD) is True
    # It was this account's current token, so the record names the account.
    (event,) = AuthenticationEvent.objects.filter(event_type=FAILED)
    assert (event.user, event.identifier_key) == (user, _key("identifier", EMAIL))


def test_a_token_is_good_until_just_before_it_lapses(clock: Clock) -> None:
    _account()
    token = _requested()

    clock(timedelta(hours=1) - timedelta(microseconds=1))

    assert _reset(token).outcome == RESET


def test_the_expiry_stored_with_the_token_decides_and_not_a_later_setting(
    clock: Clock, settings: LazySettings
) -> None:
    _account()
    token = _requested()
    settings.PASSWORD_RESET_LIFETIME = timedelta(hours=48)

    clock(timedelta(hours=1))

    assert _reset(token).outcome == REFUSED


def test_a_token_resets_only_the_account_it_was_sent_to() -> None:
    user, other = _account(), _account(OTHER_EMAIL)
    token = _requested()
    _requested(OTHER_EMAIL)

    assert _reset(token).outcome == RESET

    assert _stored(user).check_password(PASSWORD) is True
    assert _stored(other).check_password(OLD_PASSWORD) is True
    assert PasswordReset.objects.get().user == other


@pytest.mark.parametrize("status", [AccountStatus.PENDING_VERIFICATION, AccountStatus.DISABLED])
def test_a_token_is_refused_for_an_account_that_is_not_active_whatever_row_exists(
    status: AccountStatus,
) -> None:
    user = _account()
    token = _requested()
    # Written directly: no service leaves a token with such an account.
    never = {"email_verified_at": None, "activated_at": None}
    User.objects.filter(pk=user.pk).update(
        status=status, **(never if status == AccountStatus.PENDING_VERIFICATION else {})
    )

    assert _reset(token) == PasswordResetResult(REFUSED)

    assert _stored(user).check_password(OLD_PASSWORD) is True
    assert _events()[-1] == (FAILED, user.pk)
    assert PasswordReset.objects.filter(user=user).exists()


def test_every_refusal_is_the_same_answer(clock: Clock) -> None:
    _account()
    used = _requested()
    assert _reset(used).outcome == RESET
    replaced = _requested()
    current = _requested()
    disabled = _account(OTHER_EMAIL)
    of_disabled = _requested(OTHER_EMAIL)
    User.objects.filter(pk=disabled.pk).update(status=AccountStatus.DISABLED)

    refusals = [_reset(token) for token in ("A" * 43, "x", used, replaced, of_disabled)]
    clock(timedelta(hours=1))
    refusals.append(_reset(current))

    assert refusals == [PasswordResetResult(REFUSED)] * 6
    assert all(refusal.password_errors == () for refusal in refusals)


def test_an_activation_token_does_not_reset_and_a_reset_token_does_not_activate() -> None:
    created = services.create_user(
        actor=approving_administrator(),
        email=OTHER_EMAIL,
        role=Role.READER,
        source=SOURCE,
        activation_url=lambda token: f"{ORIGIN}/activate/#{token}",
    )
    (activation_token,) = re.findall(r"/activate/#(\S+)", str(django_mail.outbox[-1].body))
    user = _account()
    reset_token = _requested()

    assert _reset(activation_token).outcome == REFUSED
    activated = services.activate_account(token=reset_token, password=PASSWORD, source=SOURCE)

    assert activated.outcome == ActivationOutcome.REFUSED
    assert _stored(created.user).status == AccountStatus.PENDING_VERIFICATION
    assert _stored(user).check_password(OLD_PASSWORD) is True
    # Each still works where it belongs.
    assert AccountActivation.objects.filter(user=created.user).exists()
    assert _reset(reset_token).outcome == RESET
    # Keyed apart: the same token would not have the same key in both tables.
    assert _key("password_reset", reset_token) != _key("activation", reset_token)


# --- The new password ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "password",
    ["Tx9!q", "12345678901234", "qwertyuiop", "test.forgetful"],
    ids=["too-short", "all-digits", "common", "like-the-email"],
)
def test_a_password_that_fails_validation_changes_nothing_and_spends_nothing(
    password: str,
) -> None:
    user = _account()
    token = _requested()
    before = PasswordReset.objects.values().get()

    result = _reset(token, password)

    assert result.outcome == PASSWORD_REFUSED
    assert result.password_errors
    assert all(password not in message for message in result.password_errors)
    assert _stored(user).check_password(OLD_PASSWORD) is True
    assert PasswordReset.objects.values().get() == before
    # Neither a success nor a refused token: nothing is recorded.
    assert _events() == [(REQUESTED, user.pk)]
    assert _reset(token).outcome == RESET


def test_the_password_is_validated_only_for_a_good_token() -> None:
    _account()
    _requested()

    result = _reset("A" * 43, "Tx9!q")

    # A refused token says nothing about the password sent with it.
    assert result == PasswordResetResult(REFUSED)


def test_a_rejected_password_is_not_counted_as_a_refused_token(settings: LazySettings) -> None:
    _account()
    token = _requested()

    for _ in range(settings.PASSWORD_RESET_THROTTLE_FAILURES + 2):
        assert _reset(token, "Tx9!q").outcome == PASSWORD_REFUSED

    assert _reset(token).outcome == RESET


# --- What a reset leaves alone ---------------------------------------------------------------


@pytest.mark.parametrize("trusted", [True, False])
def test_the_second_factor_is_exactly_as_it_was(trusted: bool) -> None:
    user = _account()
    enrolled_device(user, trusted=trusted)
    before = list(TotpDevice.objects.values())
    state = selectors.mfa_state_of(user)

    assert _reset(_requested()).outcome == RESET

    assert list(TotpDevice.objects.values()) == before
    assert selectors.mfa_state_of(user) == state == MfaState.ACTIVE
    # The new password alone signs nobody in: the code is still asked for.
    result = services.sign_in(email=EMAIL, password=PASSWORD, source=SOURCE)
    assert result.outcome == SignInOutcome.SECOND_FACTOR_REQUIRED
    assert result.challenge is not None
    verified = services.verify_second_factor(
        challenge=result.challenge, code=code_at(), source=SOURCE
    )
    assert verified.outcome == MfaOutcome.ACCEPTED


def test_an_enrolment_that_awaits_approval_still_awaits_it(user_with_roles: UserFactory) -> None:
    administrator = user_with_roles(Role.ADMINISTRATOR)
    administrator.set_password(OLD_PASSWORD)
    administrator.save()
    started = services.start_mfa_enrollment(
        actor=selectors.AuthenticationContext(
            administrator, selectors.Assurance.PASSWORD_AUTHENTICATED
        ),
        password=OLD_PASSWORD,
        source=SOURCE,
    )
    assert started.outcome == MfaOutcome.ACCEPTED
    before = list(TotpDevice.objects.values())

    assert _reset(_requested(administrator.email)).outcome == RESET

    assert list(TotpDevice.objects.values()) == before
    assert selectors.mfa_state_of(administrator) == MfaState.PENDING_APPROVAL


def test_roles_are_unchanged_and_a_privileged_role_still_needs_its_second_factor(
    user_with_roles: UserFactory,
) -> None:
    administrator = user_with_roles(Role.ADMINISTRATOR, Role.READER)
    roles = list(RoleEvent.objects.values())

    assert _reset(_requested(administrator.email)).outcome == RESET

    assert list(RoleEvent.objects.values()) == roles
    assert selectors.roles_of(administrator) == {Role.ADMINISTRATOR, Role.READER}
    result = services.sign_in(email=administrator.email, password=PASSWORD, source=SOURCE)
    assert result.outcome == SignInOutcome.SIGNED_IN and result.user is not None
    context = selectors.authentication_context(result.user, verified_device_id=None)
    # Whoever controls the mailbox gains a password and no more.
    assert not selectors.can(context, Permission.ROLES_MANAGE)
    assert not selectors.can(context, Permission.ACCOUNTS_CREATE)
    assert selectors.can(context, Permission.MFA_MANAGE_OWN)


def test_a_reset_does_not_lift_the_throttle_on_sign_in(settings: LazySettings) -> None:
    _account()
    for _ in range(settings.LOGIN_THROTTLE_ACCOUNT_FAILURES):
        assert _sign_in(EMAIL, OTHER_PASSWORD) == SignInOutcome.REFUSED
    failures = AuthenticationEvent.objects.filter(event_type="login_failure").count()

    assert _reset(_requested()).outcome == RESET

    assert AuthenticationEvent.objects.filter(event_type="login_failure").count() == failures
    assert _sign_in(EMAIL, PASSWORD) == SignInOutcome.THROTTLED
    assert _sign_in(EMAIL, PASSWORD, OTHER_SOURCE) == SignInOutcome.THROTTLED


def test_a_reset_does_not_lift_the_throttle_on_sign_in_for_a_source(
    settings: LazySettings,
) -> None:
    _account()
    for number in range(settings.LOGIN_THROTTLE_SOURCE_FAILURES):
        assert _sign_in(f"test.nobody{number}@caipo.test", OTHER_PASSWORD) == SignInOutcome.REFUSED

    assert _reset(_requested()).outcome == RESET

    assert _sign_in(EMAIL, PASSWORD) == SignInOutcome.THROTTLED
    assert _sign_in(EMAIL, PASSWORD, OTHER_SOURCE) == SignInOutcome.SIGNED_IN


def test_a_reset_does_not_lift_the_throttle_on_second_factor_codes(settings: LazySettings) -> None:
    user = _account()
    enrolled_device(user)
    challenge = services.sign_in(email=EMAIL, password=OLD_PASSWORD, source=SOURCE).challenge
    assert challenge is not None
    for _ in range(settings.MFA_THROTTLE_FAILURES):
        refused = services.verify_second_factor(challenge=challenge, code="000000", source=SOURCE)
        assert refused.outcome == MfaOutcome.REFUSED

    assert _reset(_requested()).outcome == RESET

    fresh = services.sign_in(email=EMAIL, password=PASSWORD, source=SOURCE).challenge
    assert fresh is not None
    throttled = services.verify_second_factor(challenge=fresh, code=code_at(), source=SOURCE)
    assert throttled.outcome == MfaOutcome.THROTTLED


# --- A sign-in that awaits its second-factor code ------------------------------------------


def test_a_pending_challenge_does_not_survive_a_reset() -> None:
    user = _account()
    enrolled_device(user)
    challenge = services.sign_in(email=EMAIL, password=OLD_PASSWORD, source=SOURCE).challenge
    assert challenge is not None
    assert MfaChallenge.objects.filter(user=user).count() == 1

    assert _reset(_requested()).outcome == RESET

    assert not MfaChallenge.objects.exists()
    # The right code from the right device no longer completes that sign-in.
    result = services.verify_second_factor(challenge=challenge, code=code_at(), source=SOURCE)
    assert result.outcome == MfaOutcome.REFUSED
    assert result.context is None
    assert not AuthenticationEvent.objects.filter(event_type="login_success").exists()


def test_a_reset_removes_only_the_challenge_of_its_own_account() -> None:
    user, other = _account(), _account(OTHER_EMAIL)
    enrolled_device(user)
    enrolled_device(other)
    services.sign_in(email=EMAIL, password=OLD_PASSWORD, source=SOURCE)
    kept = services.sign_in(email=OTHER_EMAIL, password=OLD_PASSWORD, source=SOURCE).challenge
    assert kept is not None

    assert _reset(_requested()).outcome == RESET

    assert MfaChallenge.objects.get().user == other
    result = services.verify_second_factor(challenge=kept, code=code_at(), source=SOURCE)
    assert result.outcome == MfaOutcome.ACCEPTED


@pytest.mark.parametrize("refusal", ["token", "password"])
def test_a_reset_that_is_refused_leaves_a_pending_challenge_in_place(refusal: str) -> None:
    user = _account()
    enrolled_device(user)
    challenge = services.sign_in(email=EMAIL, password=OLD_PASSWORD, source=SOURCE).challenge
    assert challenge is not None
    token = _requested()

    if refusal == "token":
        assert _reset("A" * 43).outcome == REFUSED
    else:
        assert _reset(token, "Tx9!q").outcome == PASSWORD_REFUSED

    result = services.verify_second_factor(challenge=challenge, code=code_at(), source=SOURCE)
    assert result.outcome == MfaOutcome.ACCEPTED


def test_a_reset_that_cannot_be_recorded_is_not_made(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _account()
    enrolled_device(user)
    services.sign_in(email=EMAIL, password=OLD_PASSWORD, source=SOURCE)
    token = _requested()

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("TEST the event could not be written")

    with monkeypatch.context() as patch, pytest.raises(RuntimeError, match="TEST"):
        patch.setattr(services, "_record", fail)
        _reset(token)

    # One transaction: the password, the token, and the challenge are as they were.
    assert _stored(user).check_password(OLD_PASSWORD) is True
    assert PasswordReset.objects.filter(user=user).exists()
    assert MfaChallenge.objects.filter(user=user).exists()
    assert _reset(token).outcome == RESET


# --- Throttling of refused tokens -----------------------------------------------------------


def test_the_limit_on_refused_tokens_from_a_source_is_exact(settings: LazySettings) -> None:
    user = _account()
    token = _requested()
    limit = settings.PASSWORD_RESET_THROTTLE_FAILURES

    for _ in range(limit):
        assert _reset("A" * 43).outcome == REFUSED
    assert AuthenticationEvent.objects.filter(event_type=FAILED).count() == limit

    with CaptureQueriesContext(connection) as queries:
        wrong, right = _reset("B" * 43), _reset(token)

    assert wrong == right == PasswordResetResult(THROTTLED)
    # Refused unexamined: the token table is not read, and nothing is stored.
    statements = " ".join(query["sql"] for query in queries.captured_queries)
    assert "accounts_passwordreset" not in statements
    assert "INSERT" not in statements
    assert AuthenticationEvent.objects.filter(event_type=FAILED).count() == limit
    assert _stored(user).check_password(OLD_PASSWORD) is True
    # The valid token was not spent, and works from a source that is not throttled.
    assert PasswordReset.objects.filter(user=user).exists()
    assert _reset(token, source=OTHER_SOURCE).outcome == RESET


def test_the_limit_is_ten_refusals_in_fifteen_minutes(settings: LazySettings) -> None:
    assert settings.PASSWORD_RESET_THROTTLE_FAILURES == 10
    assert settings.PASSWORD_RESET_THROTTLE_WINDOW == timedelta(minutes=15)


def test_the_throttle_on_refused_tokens_lifts_by_itself_and_only_after_the_window(
    clock: Clock, settings: LazySettings
) -> None:
    _account()
    for _ in range(settings.PASSWORD_RESET_THROTTLE_FAILURES):
        _reset("A" * 43)
    token = _requested()

    clock(settings.PASSWORD_RESET_THROTTLE_WINDOW)
    assert _reset(token).outcome == THROTTLED

    clock(timedelta(seconds=1))
    assert _reset(token).outcome == RESET


def test_an_accepted_token_does_not_buy_fresh_guesses(settings: LazySettings) -> None:
    _account()
    for _ in range(settings.PASSWORD_RESET_THROTTLE_FAILURES - 1):
        _reset("A" * 43)

    assert _reset(_requested()).outcome == RESET

    assert _reset("A" * 43).outcome == REFUSED
    assert _reset("A" * 43).outcome == THROTTLED


def test_the_limit_on_refused_tokens_is_separate_from_every_other_limit(
    settings: LazySettings,
) -> None:
    _account()
    for _ in range(settings.PASSWORD_RESET_THROTTLE_FAILURES):
        _reset("A" * 43)
    assert _reset("A" * 43).outcome == THROTTLED

    # Asking for a reset, signing in, and activating are not held back by it...
    token = _requested()
    assert _sign_in(EMAIL, OLD_PASSWORD) == SignInOutcome.SIGNED_IN
    activation = services.activate_account(token="A" * 43, password=PASSWORD, source=SOURCE)
    assert activation.outcome == ActivationOutcome.REFUSED

    # ...and none of them is counted by it: refused activations and reset
    # requests from another source leave that source free to reset.
    for number in range(settings.PASSWORD_RESET_REQUEST_SOURCE_LIMIT + 1):
        _request(f"test.nobody{number}@caipo.test", source=OTHER_SOURCE)
    for _ in range(settings.ACCOUNT_ACTIVATION_THROTTLE_FAILURES):
        services.activate_account(token="A" * 43, password=PASSWORD, source=OTHER_SOURCE)
    assert _reset(token, source=OTHER_SOURCE).outcome == RESET


def test_a_throttled_submission_is_logged_without_anything_submitted(
    caplog: pytest.LogCaptureFixture, settings: LazySettings
) -> None:
    settings.PASSWORD_RESET_THROTTLE_FAILURES = 1
    _account()
    token = _requested()
    _reset("A" * 43)
    caplog.clear()

    with caplog.at_level(logging.DEBUG, logger="caipo.accounts.services"):
        assert _reset(token).outcome == THROTTLED

    (record,) = caplog.records
    assert record.__dict__["event"] == "password_reset.throttled"
    assert token not in logged(caplog.records)
    assert "user_id" not in record.__dict__


# --- Disabling and enabling ------------------------------------------------------------------


def test_disabling_removes_the_token_and_enabling_does_not_bring_it_back() -> None:
    administrator = approving_administrator()
    user = _account()
    token = _requested()

    services.disable_user(actor=administrator, user=user)

    assert not PasswordReset.objects.exists()
    assert _reset(token).outcome == REFUSED

    services.enable_user(actor=administrator, user=user)

    assert _stored(user).status == AccountStatus.ACTIVE
    assert not PasswordReset.objects.exists()
    assert _reset(token, source=OTHER_SOURCE).outcome == REFUSED
    assert _stored(user).check_password(OLD_PASSWORD) is True


def test_a_fresh_reset_can_be_asked_for_once_the_account_is_enabled_again() -> None:
    administrator = approving_administrator()
    user = _account()
    old = _requested()
    services.disable_user(actor=administrator, user=user)
    _request()
    assert len(django_mail.outbox) == 1
    services.enable_user(actor=administrator, user=user)

    fresh = _requested()

    assert fresh != old
    assert _reset(fresh).outcome == RESET
    assert _stored(user).check_password(PASSWORD) is True


def test_disabling_removes_only_the_token_of_the_account_disabled() -> None:
    user, other = _account(), _account(OTHER_EMAIL)
    _requested()
    kept = _requested(OTHER_EMAIL)

    services.disable_user(actor=approving_administrator(), user=user)

    assert PasswordReset.objects.get().user == other
    assert _reset(kept).outcome == RESET


def test_a_disabling_that_cannot_be_recorded_keeps_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = approving_administrator()
    user = _account()
    token = _requested()

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("TEST the event could not be written")

    with monkeypatch.context() as patch, pytest.raises(RuntimeError, match="TEST"):
        patch.setattr(services, "_record_account", fail)
        services.disable_user(actor=administrator, user=user)

    assert _stored(user).status == AccountStatus.ACTIVE
    assert _reset(token).outcome == RESET


# --- What is recorded -------------------------------------------------------------------------


def test_the_events_hold_keyed_hashes_and_name_no_actor(clock: Clock) -> None:
    user = _account()
    _request(UNKNOWN, OTHER_SOURCE)
    token = _requested()
    _reset("A" * 43)
    _reset(token)

    events = list(AuthenticationEvent.objects.order_by("id"))

    assert [(event.event_type, event.user) for event in events] == [
        (REQUESTED, None),
        (REQUESTED, user),
        (FAILED, None),
        (SUCCEEDED, user),
    ]
    assert all(event.actor is None for event in events)
    assert [event.identifier_key for event in events] == [
        _key("identifier", UNKNOWN),
        _key("identifier", EMAIL),
        "",
        _key("identifier", EMAIL),
    ]
    assert [event.source_key for event in events] == [
        _key("source", OTHER_SOURCE),
        *[_key("source", SOURCE)] * 3,
    ]
    assert all(event.created_at.utcoffset() == timedelta(0) for event in events)
    # Reset events do not touch the record of an account's lifecycle.
    assert not AccountEvent.objects.exists()


def test_no_event_and_no_log_holds_a_token_its_hash_a_password_an_address_or_a_link(
    caplog: pytest.LogCaptureFixture,
) -> None:
    user = _account()
    with caplog.at_level(logging.DEBUG):
        _request(UNKNOWN)
        first = _requested()
        second = _requested()
        _reset(first, OTHER_PASSWORD)
        _reset(second, "Tx9!q")
        _reset(second)
        third = _requested()
        services.disable_user(actor=approving_administrator(), user=user)
        _reset(third)

    tokens = (first, second, third)
    hashes = tuple(_key("password_reset", token) for token in tokens)
    events = repr(list(AuthenticationEvent.objects.values()))
    for forbidden in (
        *tokens,
        *hashes,
        PASSWORD,
        OTHER_PASSWORD,
        OLD_PASSWORD,
        "Tx9!q",
        EMAIL,
        UNKNOWN,
        SOURCE,
        ORIGIN,
        "password-reset/confirm",
        _stored(user).password,
    ):
        assert forbidden not in events, forbidden
    written = logged(caplog.records)
    for forbidden in (*tokens, *hashes, PASSWORD, OTHER_PASSWORD, "Tx9!q", EMAIL, UNKNOWN, ORIGIN):
        assert forbidden not in written, forbidden
    # The table has no column a secret could be put into.
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


def test_what_is_logged_does_not_tell_a_request_with_an_account_from_one_without(
    caplog: pytest.LogCaptureFixture, settings: LazySettings
) -> None:
    _account()
    _account(OTHER_EMAIL, status=AccountStatus.DISABLED)
    # With no message handed on, every request writes the same lines.
    settings.EMAIL_BACKEND = "caipo.core.mail.RefusingEmailBackend"

    lines = []
    for email in (UNKNOWN, OTHER_EMAIL):
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="caipo.accounts.services"):
            _request(email)
        lines.append(logged(caplog.records))

    assert lines[0] == lines[1]
    assert "user_id" not in lines[0]


# --- The message -----------------------------------------------------------------------------


def test_the_message_says_what_it_is_for_and_carries_one_link() -> None:
    _account()
    token = _requested()

    (message,) = django_mail.outbox
    body = str(message.body)

    assert message.to == [EMAIL]
    assert message.cc == [] and message.bcc == []
    assert message.subject == "Reset your CAIPO password"
    assert message.content_subtype == "plain"
    assert message.attachments == []
    assert "password reset was requested" in body
    assert "choose a new password" in body
    assert "1 hour after" in body
    assert "works once" in body
    assert "ignore it" in body
    assert re.findall(r"https?://\S+", body) == [reset_url(token)]


def test_the_message_states_the_lifetime_that_is_configured() -> None:
    assert "stops working 1 hour after" in services.password_reset_body(
        url="TEST-link", lifetime_hours=1
    )
    assert "stops working 3 hours after" in services.password_reset_body(
        url="TEST-link", lifetime_hours=3
    )


@pytest.mark.parametrize("role", list(Role))
def test_the_message_holds_nothing_about_the_account_but_the_link(
    user_with_roles: UserFactory, role: Role
) -> None:
    user = user_with_roles(role)
    enrolled_device(user)
    _requested(user.email)

    (message,) = django_mail.outbox
    text = (str(message.subject) + str(message.body)).lower()

    forbidden = [
        user.email,
        _stored(user).password,
        "argon2",
        "test-totp-secret-000",
        "otpauth",
        "sessionid",
        *(value.lower() for value in Role.values),
        *(permission.value for permission in Permission),
        "permission",
        "privilege",
        "two-step",
    ]
    for value in forbidden:
        assert value.lower() not in text, value
    assert "password:" not in text


def test_the_message_is_the_same_for_every_recipient_apart_from_the_link(
    user_with_roles: UserFactory,
) -> None:
    _account()
    administrator = user_with_roles(Role.ADMINISTRATOR)
    first = _requested()
    second = _requested(administrator.email)

    one, two = (str(message.body) for message in django_mail.outbox)

    assert one.replace(first, "TOKEN") == two.replace(second, "TOKEN")
    assert django_mail.outbox[0].subject == django_mail.outbox[1].subject


# --- The stored state --------------------------------------------------------------------------


def test_the_table_holds_exactly_these_columns() -> None:
    assert {field.column for field in PasswordReset._meta.concrete_fields} == {
        "id",
        "user_id",
        "token_key",
        "created_at",
        "expires_at",
    }


def test_the_database_allows_one_reset_for_an_account() -> None:
    user = _account()
    now = timezone.now()
    lapses = now + timedelta(hours=1)
    PasswordReset.objects.create(user=user, token_key="a" * 64, created_at=now, expires_at=lapses)

    with pytest.raises(IntegrityError, match="user_id"), transaction.atomic():
        PasswordReset.objects.create(
            user=user, token_key="b" * 64, created_at=now, expires_at=lapses
        )


def test_the_database_allows_a_token_key_once() -> None:
    now = timezone.now()
    lapses = now + timedelta(hours=1)
    PasswordReset.objects.create(
        user=_account(), token_key="a" * 64, created_at=now, expires_at=lapses
    )

    with pytest.raises(IntegrityError, match="token_key"), transaction.atomic():
        PasswordReset.objects.create(
            user=_account(OTHER_EMAIL), token_key="a" * 64, created_at=now, expires_at=lapses
        )


@pytest.mark.parametrize("lifetime", [timedelta(0), timedelta(hours=-1)])
def test_the_database_rejects_a_reset_that_lapses_no_later_than_it_was_issued(
    lifetime: timedelta,
) -> None:
    now = timezone.now()

    with (
        pytest.raises(IntegrityError, match="accounts_passwordreset_expires_after_created"),
        transaction.atomic(),
    ):
        PasswordReset.objects.create(
            user=_account(), token_key="a" * 64, created_at=now, expires_at=now + lifetime
        )


def test_an_account_with_a_reset_cannot_be_deleted() -> None:
    user = _account()
    _requested()

    with pytest.raises(models.ProtectedError):
        user.delete()
