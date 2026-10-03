"""The lifecycle of an account through the services (ADR-0015): creation by an
Administrator, verification and activation by its owner, disabling and enabling.

No HTTP is involved. Messages go to the in-memory backend, and the token is read
from the message as the person receiving it would read it.
"""

import inspect
import logging
import re
from datetime import timedelta
from typing import Any

import pytest
from django.conf import LazySettings
from django.core import mail as django_mail
from django.core.exceptions import PermissionDenied, ValidationError

from caipo.accounts import selectors, services
from caipo.accounts.models import (
    AccountActivation,
    AccountEvent,
    AccountStatus,
    AuthenticationEvent,
    RoleEvent,
    TotpDevice,
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
    AccountChangeError,
    ActivationOutcome,
    ActivationResult,
    LastAdministratorError,
    SignInOutcome,
)
from caipo.accounts.tests.fixtures import (
    Clock,
    UserFactory,
    approving_administrator,
    enrolled_device,
    logged,
    signed_in,
    verified,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db]

# Visibly synthetic fixture values.
EMAIL = "test.invited@caipo.test"
OTHER_EMAIL = "test.other.invited@caipo.test"
PASSWORD = "TEST-passphrase-chosen-by-the-owner"
OTHER_PASSWORD = "TEST-another-passphrase-entirely"
SOURCE = "203.0.113.10"
OTHER_SOURCE = "198.51.100.66"
ORIGIN = "https://caipo.test"

ACTIVATED = ActivationOutcome.ACTIVATED
REFUSED = ActivationOutcome.REFUSED
THROTTLED = ActivationOutcome.THROTTLED
PASSWORD_REFUSED = ActivationOutcome.PASSWORD_REFUSED

PENDING = AccountStatus.PENDING_VERIFICATION
ACTIVE = AccountStatus.ACTIVE
DISABLED = AccountStatus.DISABLED


def activation_url(token: str) -> str:
    return f"{ORIGIN}/activate/#{token}"


def _create(
    email: str = EMAIL,
    role: Any = Role.READER,
    actor: Any = None,
) -> services.CreatedAccount:
    return services.create_user(
        actor=actor if actor is not None else approving_administrator(),
        email=email,
        role=role,
        source=SOURCE,
        activation_url=activation_url,
    )


def _token(index: int = -1) -> str:
    """Read the token off a verification message, by default the last one sent."""
    (token,) = re.findall(
        rf"{re.escape(ORIGIN)}/activate/#(\S+)", str(django_mail.outbox[index].body)
    )
    return str(token)


def _invited(email: str = EMAIL, role: Role = Role.READER) -> tuple[User, str]:
    """Create an account and return it with the token that was sent to it."""
    created = _create(email, role)
    assert created.verification_sent is True
    return created.user, _token()


def _activate(token: str, password: str = PASSWORD, source: str = SOURCE) -> ActivationResult:
    return services.activate_account(token=token, password=password, source=source)


def _active(email: str = EMAIL, role: Role = Role.READER) -> User:
    user, token = _invited(email, role)
    assert _activate(token).outcome == ACTIVATED
    return User.objects.get(pk=user.pk)


def _events(user: User | None = None) -> list[str]:
    events = AccountEvent.objects.order_by("id")
    if user is not None:
        events = events.filter(user=user)
    return list(events.values_list("event_type", flat=True))


def _stored(user: User) -> User:
    return User.objects.get(pk=user.pk)


def _sign_in(email: str, password: str) -> SignInOutcome:
    return services.sign_in(email=email, password=password, source=SOURCE).outcome


def _everything_stored() -> str:
    return repr(
        [
            list(AccountEvent.objects.values()),
            list(AccountActivation.objects.values()),
            list(AuthenticationEvent.objects.values()),
            list(RoleEvent.objects.values()),
            list(User.objects.values()),
        ]
    )


# --- Creating an account ------------------------------------------------------------


@pytest.mark.parametrize("role", list(Role))
def test_a_verified_administrator_creates_an_account_that_awaits_verification(role: Role) -> None:
    actor = approving_administrator()

    created = _create(role=role, actor=actor)

    user = _stored(created.user)
    assert user.email == EMAIL
    assert user.status == PENDING
    assert user.is_active is False
    assert (user.email_verified_at, user.activated_at) == (None, None)
    assert selectors.roles_of(user) == {role}
    grant = RoleEvent.objects.get(user=user)
    assert (grant.role, grant.event_type, grant.actor) == (role, "granted", actor.user)
    assert AccountActivation.objects.get().user == user
    assert created.verification_sent is True
    assert [message.to for message in django_mail.outbox] == [[EMAIL]]
    assert _events(user) == ["account_created", "verification_sent"]


def test_the_email_address_is_normalised_and_validated() -> None:
    assert _create("  Test.Invited@CAIPO.Test ").user.email == EMAIL

    for email in ("", "not-an-email", "test@", "@caipo.test"):
        with pytest.raises(ValidationError):
            _create(email)

    assert User.objects.filter(status=PENDING).count() == 1
    assert len(django_mail.outbox) == 1


@pytest.mark.parametrize("email", [EMAIL, EMAIL.upper(), f" {EMAIL} "])
def test_an_email_address_that_has_an_account_is_refused(email: str) -> None:
    first = _create().user
    events = _events()

    with pytest.raises(ValidationError):
        _create(email, Role.ADMINISTRATOR)

    assert User.objects.filter(email=EMAIL).get() == first
    assert selectors.roles_of(first) == {Role.READER}
    assert _events() == events
    assert len(django_mail.outbox) == 1


def _actor_of_kind(kind: str, user_with_roles: UserFactory) -> object:
    if kind == "nobody":
        return None
    if kind == "bare-account":
        administrator = user_with_roles(Role.ADMINISTRATOR)
        enrolled_device(administrator)
        return administrator
    if kind == "administrator-on-a-password":
        administrator = user_with_roles(Role.ADMINISTRATOR)
        enrolled_device(administrator)
        return signed_in(administrator)
    if kind == "administrator-with-an-unapproved-device":
        administrator = user_with_roles(Role.ADMINISTRATOR)
        device = enrolled_device(administrator, trusted=False)
        return AuthenticationContext(administrator, Assurance.MFA_VERIFIED, device.pk)
    if kind == "administrator-claiming-a-device-it-has-not":
        return AuthenticationContext(
            user_with_roles(Role.ADMINISTRATOR), Assurance.MFA_VERIFIED, 2**31
        )
    if kind == "disabled-administrator":
        return verified(user_with_roles(Role.ADMINISTRATOR, is_active=False))
    if kind == "no-role":
        return verified(user_with_roles())
    role = {
        "verified-reviewer": Role.REVIEWER,
        "verified-researcher": Role.RESEARCHER,
        "verified-reader": Role.READER,
    }[kind]
    return verified(user_with_roles(role))


UNAUTHORISED = [
    "nobody",
    "bare-account",
    "administrator-on-a-password",
    "administrator-with-an-unapproved-device",
    "administrator-claiming-a-device-it-has-not",
    "disabled-administrator",
    "verified-reviewer",
    "verified-researcher",
    "verified-reader",
    "no-role",
]


@pytest.mark.parametrize("kind", UNAUTHORISED)
def test_only_an_administrator_verified_against_a_trusted_device_creates_an_account(
    user_with_roles: UserFactory, kind: str
) -> None:
    actor = _actor_of_kind(kind, user_with_roles)
    users = User.objects.count()

    with pytest.raises(PermissionDenied):
        services.create_user(
            actor=actor,  # type: ignore[arg-type]  # the wrong kinds of actor are the point of the test
            email=EMAIL,
            role=Role.READER,
            source=SOURCE,
            activation_url=activation_url,
        )

    assert User.objects.count() == users
    assert not User.objects.filter(email=EMAIL).exists()
    assert not AccountActivation.objects.exists()
    assert _events() == []
    assert django_mail.outbox == []


def test_an_unauthorised_caller_learns_nothing_about_accounts_or_inputs(
    user_with_roles: UserFactory,
) -> None:
    existing = _create().user
    reader = verified(user_with_roles(Role.READER))

    # Whatever is wrong with the input, the answer is the same refusal.
    for email, role in ((existing.email, Role.READER), ("not-an-email", "superuser"), ("", "")):
        with pytest.raises(PermissionDenied):
            _create(email, role, reader)


@pytest.mark.parametrize(
    "role",
    ["superuser", "", "ADMINISTRATOR", "Administrator", "staff", "reader,administrator", None],
)
def test_a_role_outside_the_four_roles_is_refused(role: object) -> None:
    with pytest.raises(ValueError, match="is not a valid Role"):
        _create(role=role)

    assert not User.objects.filter(email=EMAIL).exists()
    assert _events() == []
    assert django_mail.outbox == []


def test_creation_takes_an_email_address_and_one_role_and_no_password() -> None:
    assert set(inspect.signature(services.create_user).parameters) == {
        "actor",
        "email",
        "role",
        "source",
        "activation_url",
    }


def test_exactly_the_role_asked_for_is_granted_and_by_the_role_service_rules() -> None:
    actor = approving_administrator()
    roles_before = RoleEvent.objects.count()

    user = _create(role=Role.RESEARCHER, actor=actor).user

    assert RoleEvent.objects.count() == roles_before + 1
    event = RoleEvent.objects.latest("id")
    assert (event.user, event.role, event.actor) == (user, "researcher", actor.user)
    assert event.reason
    # No inheritance: a Researcher is not also recorded as a Reader.
    assert selectors.roles_of(user) == {Role.RESEARCHER}


def test_an_account_that_awaits_verification_holds_no_permission_whatever_its_role() -> None:
    for number, role in enumerate(Role):
        user = _create(f"test.invited{number}@caipo.test", role).user
        device = enrolled_device(user)

        for context in (
            signed_in(user),
            AuthenticationContext(user, Assurance.MFA_VERIFIED, device.pk),
        ):
            assert selectors.permissions_of(context) == frozenset()


def test_the_status_is_read_from_the_database_and_not_from_the_object_passed_in() -> None:
    user = _create(role=Role.RESEARCHER).user
    stale = _stored(user)
    # In memory only: an object that claims what the database does not say.
    stale.status = ACTIVE
    assert stale.is_active is True

    assert selectors.permissions_of(signed_in(stale)) == frozenset()
    assert selectors.can(signed_in(stale), Permission.WORKSPACE_READ) is False


@pytest.mark.parametrize("role", [Role.REVIEWER, Role.ADMINISTRATOR])
def test_a_privileged_role_given_at_creation_confers_nothing_before_the_second_factor(
    role: Role,
) -> None:
    user = _active(role=role)

    # Activated, signed in with the password it chose: only its own second factor.
    assert _sign_in(EMAIL, PASSWORD) == SignInOutcome.SIGNED_IN
    assert selectors.permissions_of(signed_in(user)) == {Permission.MFA_MANAGE_OWN}
    # And that second factor cannot be established on the password (ADR-0014).
    started = services.start_mfa_enrollment(actor=signed_in(user), password=PASSWORD, source=SOURCE)
    assert started.outcome == services.MfaOutcome.ACCEPTED
    assert selectors.mfa_state_of(user) == MfaState.PENDING_APPROVAL
    assert not TotpDevice.objects.filter(user=user, approved_at__isnull=False).exists()
    with pytest.raises(PermissionDenied):
        _create(OTHER_EMAIL, Role.READER, signed_in(user))


def test_an_administrator_that_awaits_verification_is_not_an_administrator_that_remains(
    user_with_roles: UserFactory,
) -> None:
    only = user_with_roles(Role.ADMINISTRATOR)
    _create(role=Role.ADMINISTRATOR, actor=verified(only))

    with pytest.raises(LastAdministratorError):
        services.disable_user(actor=verified(only), user=only)
    assert _stored(only).status == ACTIVE


def test_nobody_knows_the_password_of_a_new_account(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        created = _create()
        other = _create(OTHER_EMAIL)

    user = _stored(created.user)
    # A real hash, so that guessing it costs what any guess costs, of a value
    # that was discarded.
    assert user.password.startswith("argon2$")
    assert user.has_usable_password() is True
    assert user.password != _stored(other.user).password
    for guess in ("", EMAIL, "password", PASSWORD):
        assert user.check_password(guess) is False
    assert not hasattr(created, "password")
    assert "argon2" not in repr(created) + logged(caplog.records)
    assert "argon2" not in " ".join(str(message.body) for message in django_mail.outbox)


def test_a_failure_part_way_leaves_no_account_behind(monkeypatch: pytest.MonkeyPatch) -> None:
    actor = approving_administrator()
    users, roles = User.objects.count(), RoleEvent.objects.count()

    def fail(**kwargs: object) -> None:
        raise RuntimeError("TEST failure while recording the creation")

    # Fault injection: the account event cannot be written.
    monkeypatch.setattr(AccountEvent.objects, "create", fail)

    with pytest.raises(RuntimeError):
        _create(actor=actor)

    assert User.objects.count() == users
    assert RoleEvent.objects.count() == roles
    assert not AccountActivation.objects.exists()
    assert django_mail.outbox == []


def test_a_message_that_cannot_be_sent_leaves_an_account_that_awaits_one(
    settings: LazySettings, caplog: pytest.LogCaptureFixture
) -> None:
    actor = approving_administrator()
    settings.EMAIL_BACKEND = "caipo.core.mail.RefusingEmailBackend"

    with caplog.at_level(logging.DEBUG, logger="caipo.accounts.services"):
        created = _create(actor=actor)

    assert created.verification_sent is False
    assert _stored(created.user).status == PENDING
    assert _events() == ["account_created"]
    record = next(r for r in caplog.records if r.levelno == logging.ERROR)
    assert record.__dict__["event"] == "accounts.verification_not_sent"
    assert record.__dict__["user_id"] == created.user.pk
    assert record.exc_info is None
    assert EMAIL not in logged(caplog.records)
    assert "activate" not in logged(caplog.records)

    # Once messages can be sent, sending it again completes the invitation.
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    assert _send_again(created.user, actor) is True
    assert _activate(_token()).outcome == ACTIVATED


def test_creation_is_logged_by_identifier_and_never_with_the_address_or_the_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    actor = approving_administrator()

    with caplog.at_level(logging.DEBUG):
        user, token = _invited()

    written = logged(caplog.records)
    record = next(r for r in caplog.records if r.__dict__.get("event") == "accounts.created")
    assert record.__dict__["user_id"] == user.pk
    assert record.__dict__["actor_id"] == actor.user.pk
    for forbidden in (EMAIL, token, activation_url(token), ORIGIN):
        assert forbidden not in written


# --- The token -------------------------------------------------------------------------


def test_a_token_is_256_random_bits_and_only_its_keyed_hash_is_stored() -> None:
    tokens = set()
    for number in range(20):
        _create(f"test.invited{number}@caipo.test")
        tokens.add(_token())

    assert len(tokens) == 20
    for token in tokens:
        # 32 random bytes in URL-safe Base64, without padding.
        assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token)
    keys = set(AccountActivation.objects.values_list("token_key", flat=True))
    assert len(keys) == 20
    for key in keys:
        assert re.fullmatch(r"[0-9a-f]{64}", key)
    stored = _everything_stored()
    for token in tokens:
        assert token not in stored
        assert token not in keys


def test_the_stored_key_cannot_be_used_as_the_token() -> None:
    user, _ = _invited()
    key = AccountActivation.objects.get(user=user).token_key

    assert _activate(key).outcome == REFUSED
    assert _stored(user).status == PENDING


def test_the_token_is_in_no_result_and_no_log(caplog: pytest.LogCaptureFixture) -> None:
    actor = approving_administrator()
    with caplog.at_level(logging.DEBUG):
        created = _create(actor=actor)
        first = _token()
        _activate(first[:-1] + "x")
        _send_again(created.user, actor)
        second = _token()
        result = _activate(second)

    assert result.outcome == ACTIVATED
    written = logged(caplog.records) + repr(created) + repr(result)
    for token in (first, second):
        assert token not in written
        assert token not in _everything_stored()
    assert PASSWORD not in written


# --- Activating ------------------------------------------------------------------------


def test_the_token_verifies_the_address_and_activates_the_account(clock: Clock) -> None:
    user, token = _invited()
    assert _sign_in(EMAIL, PASSWORD) == SignInOutcome.REFUSED
    clock(timedelta(minutes=5))

    result = _activate(token)

    assert result == ActivationResult(ACTIVATED)
    stored = _stored(user)
    assert stored.status == ACTIVE
    assert stored.is_active is True
    assert stored.email_verified_at is not None
    assert stored.email_verified_at == stored.activated_at
    assert stored.email_verified_at > stored.created_at
    assert stored.check_password(PASSWORD) is True
    assert not AccountActivation.objects.exists()
    assert _events(user) == ["account_created", "verification_sent", "verification_succeeded"]
    succeeded = AccountEvent.objects.get(event_type="verification_succeeded")
    assert (succeeded.user, succeeded.actor) == (user, None)
    assert _sign_in(EMAIL, PASSWORD) == SignInOutcome.SIGNED_IN
    assert selectors.permissions_of(signed_in(stored)) == {
        Permission.WORKSPACE_READ,
        Permission.MFA_MANAGE_OWN,
    }


def test_activation_signs_nobody_in_and_takes_no_account_from_the_caller() -> None:
    _, token = _invited()

    result = _activate(token)

    assert set(vars(result)) == {"outcome", "password_errors"}
    assert set(inspect.signature(services.activate_account).parameters) == {
        "token",
        "password",
        "source",
    }
    assert not AuthenticationEvent.objects.exists()


def _wrong_tokens(token: str) -> list[str]:
    return [
        "",
        " ",
        "x",
        token[:-1],
        token + "x",
        token.swapcase(),
        token[::-1],
        "A" * 43,
        f" {token}",
    ]


def test_a_wrong_token_changes_nothing_and_names_nobody() -> None:
    user, token = _invited()
    before = User.objects.values().get(pk=user.pk)

    for wrong in _wrong_tokens(token)[:5]:
        assert _activate(wrong) == ActivationResult(REFUSED)

    assert User.objects.values().get(pk=user.pk) == before
    failures = AccountEvent.objects.filter(event_type="verification_failed")
    assert failures.count() == 5
    assert {failure.user for failure in failures} == {None}
    assert AccountActivation.objects.filter(user=user).exists()
    # The right token still works afterwards.
    assert _activate(token).outcome == ACTIVATED


def test_a_token_works_once(clock: Clock) -> None:
    user, token = _invited()
    assert _activate(token).outcome == ACTIVATED
    activated = User.objects.values().get(pk=user.pk)
    clock(timedelta(minutes=1))

    replay = _activate(token, OTHER_PASSWORD)

    assert replay == ActivationResult(REFUSED)
    assert User.objects.values().get(pk=user.pk) == activated
    assert _stored(user).check_password(PASSWORD) is True
    assert _stored(user).check_password(OTHER_PASSWORD) is False
    assert _events(user)[-1] == "verification_succeeded"
    assert AccountEvent.objects.filter(event_type="verification_failed", user=None).count() == 1


def test_a_token_lapses(clock: Clock, settings: LazySettings) -> None:
    user, token = _invited()
    clock(settings.ACCOUNT_ACTIVATION_LIFETIME)

    result = _activate(token)

    assert result == ActivationResult(REFUSED)
    assert _stored(user).status == PENDING
    assert _stored(user).check_password(PASSWORD) is False
    # Its own token, lapsed: the refusal names the account.
    failure = AccountEvent.objects.get(event_type="verification_failed")
    assert failure.user == user


def test_a_token_is_good_until_just_before_it_lapses(clock: Clock, settings: LazySettings) -> None:
    _, token = _invited()
    clock(settings.ACCOUNT_ACTIVATION_LIFETIME - timedelta(seconds=1))

    assert _activate(token).outcome == ACTIVATED


def test_the_lifetime_is_48_hours(settings: LazySettings) -> None:
    assert settings.ACCOUNT_ACTIVATION_LIFETIME == timedelta(hours=48)


def test_a_token_activates_only_the_account_it_was_sent_to() -> None:
    first, first_token = _invited()
    second, second_token = _invited(OTHER_EMAIL, Role.ADMINISTRATOR)

    assert _activate(first_token).outcome == ACTIVATED

    assert _stored(first).status == ACTIVE
    assert _stored(second).status == PENDING
    assert _stored(second).check_password(PASSWORD) is False
    assert AccountActivation.objects.get().user == second
    assert _sign_in(OTHER_EMAIL, PASSWORD) == SignInOutcome.REFUSED
    # The first account's token is spent and never opens the second.
    assert _activate(first_token, OTHER_PASSWORD).outcome == REFUSED
    assert _stored(second).status == PENDING
    assert _activate(second_token, OTHER_PASSWORD).outcome == ACTIVATED
    assert _stored(first).check_password(PASSWORD) is True


def test_the_token_of_a_disabled_account_activates_nothing() -> None:
    user, token = _invited()
    services.disable_user(actor=approving_administrator(), user=user)

    assert _activate(token) == ActivationResult(REFUSED)

    assert _stored(user).status == DISABLED
    assert _stored(user).check_password(PASSWORD) is False
    assert _sign_in(EMAIL, PASSWORD) == SignInOutcome.REFUSED


@pytest.mark.parametrize("status", [DISABLED, ACTIVE])
def test_a_token_is_refused_for_an_account_that_does_not_await_verification(
    status: AccountStatus, clock: Clock
) -> None:
    """Even if a token row were left beside an account in another state."""
    user, token = _invited()
    before = _stored(user).password
    User.objects.filter(pk=user.pk).update(
        status=status, activated_at=_stored(user).created_at if status == ACTIVE else None
    )

    assert _activate(token) == ActivationResult(REFUSED)

    stored = _stored(user)
    assert stored.status == status
    assert stored.password == before
    assert stored.email_verified_at is None
    assert AccountEvent.objects.get(event_type="verification_failed").user == user


def test_every_refusal_is_the_same_answer(clock: Clock, settings: LazySettings) -> None:
    _, used = _invited("test.used@caipo.test")
    _activate(used)
    disabled, of_disabled = _invited("test.disabled@caipo.test")
    services.disable_user(actor=approving_administrator(), user=disabled)
    _, replaced = _invited("test.replaced@caipo.test")
    _send_again(User.objects.get(email="test.replaced@caipo.test"))
    _, lapsed = _invited("test.lapsed@caipo.test")
    clock(settings.ACCOUNT_ACTIVATION_LIFETIME)

    answers = {
        name: _activate(token, source=f"203.0.113.{number}")
        for number, (name, token) in enumerate(
            {
                "unknown": "A" * 43,
                "used": used,
                "disabled": of_disabled,
                "replaced": replaced,
                "lapsed": lapsed,
            }.items()
        )
    }

    assert set(answers.values()) == {ActivationResult(REFUSED)}


# --- The password chosen at activation ---------------------------------------------------


@pytest.mark.parametrize(
    "password",
    ["Tx9!q", "12345678901234", "qwertyuiop", "test.invited"],
    ids=["too-short", "all-digits", "common", "like-the-email"],
)
def test_a_password_that_fails_validation_activates_nothing_and_spends_nothing(
    password: str,
) -> None:
    user, token = _invited()
    before = User.objects.values().get(pk=user.pk)

    result = _activate(token, password)

    assert result.outcome == PASSWORD_REFUSED
    assert result.password_errors
    assert password not in " ".join(result.password_errors)
    assert User.objects.values().get(pk=user.pk) == before
    assert _events(user) == ["account_created", "verification_sent"]
    # The token was not spent: a better password completes the activation.
    assert _activate(token).outcome == ACTIVATED


def test_the_password_is_validated_only_for_a_good_token() -> None:
    _invited()

    result = _activate("A" * 43, "short")

    # A bad token learns nothing about passwords, and nothing about itself.
    assert result == ActivationResult(REFUSED)


def test_only_activation_gives_the_account_a_password_anybody_knows() -> None:
    user, token = _invited()
    for guess in (PASSWORD, "", EMAIL):
        assert _sign_in(EMAIL, guess) == SignInOutcome.REFUSED

    _activate(token)

    assert _sign_in(EMAIL, PASSWORD) == SignInOutcome.SIGNED_IN
    assert _stored(user).password.startswith("argon2$")
    assert PASSWORD not in _stored(user).password


# --- Throttling of activation attempts ---------------------------------------------------


def test_the_limit_on_refused_attempts_from_a_source_is_exact(settings: LazySettings) -> None:
    settings.ACCOUNT_ACTIVATION_THROTTLE_FAILURES = 3
    user, token = _invited()

    outcomes = [_activate("A" * 43).outcome for _ in range(5)]

    assert outcomes == [REFUSED, REFUSED, REFUSED, THROTTLED, THROTTLED]
    assert AccountEvent.objects.filter(event_type="verification_failed").count() == 3
    # Throttled, the right token is not examined either.
    assert _activate(token) == ActivationResult(THROTTLED)
    assert _stored(user).status == PENDING
    # Another source is not affected, and the token was not spent.
    assert _activate(token, source=OTHER_SOURCE).outcome == ACTIVATED


def test_the_limit_is_ten_refusals_in_fifteen_minutes(settings: LazySettings) -> None:
    assert settings.ACCOUNT_ACTIVATION_THROTTLE_FAILURES == 10
    assert settings.ACCOUNT_ACTIVATION_THROTTLE_WINDOW == timedelta(minutes=15)


def test_the_throttle_lifts_by_itself_and_only_after_the_window(
    clock: Clock, settings: LazySettings
) -> None:
    settings.ACCOUNT_ACTIVATION_THROTTLE_FAILURES = 2
    _, token = _invited()
    for _ in range(2):
        _activate("A" * 43)
    clock(settings.ACCOUNT_ACTIVATION_THROTTLE_WINDOW - timedelta(seconds=1))
    assert _activate(token).outcome == THROTTLED

    clock(timedelta(seconds=2))

    assert _activate(token).outcome == ACTIVATED


def test_an_accepted_token_does_not_buy_fresh_guesses(settings: LazySettings) -> None:
    settings.ACCOUNT_ACTIVATION_THROTTLE_FAILURES = 2
    _, token = _invited()
    _activate("A" * 43)
    assert _activate(token).outcome == ACTIVATED
    _activate("B" * 43)

    assert _activate("C" * 43).outcome == THROTTLED


def test_a_rejected_password_is_not_counted_as_a_refused_token(settings: LazySettings) -> None:
    settings.ACCOUNT_ACTIVATION_THROTTLE_FAILURES = 2
    _, token = _invited()

    for _ in range(4):
        assert _activate(token, "short").outcome == PASSWORD_REFUSED

    assert _activate(token).outcome == ACTIVATED


# --- Sending the message again -----------------------------------------------------------


def _send_again(user: User, actor: Any = None) -> bool:
    return services.send_account_verification(
        actor=actor if actor is not None else approving_administrator(),
        user_id=user.pk,
        source=SOURCE,
        activation_url=activation_url,
    )


def test_sending_again_replaces_the_token() -> None:
    actor = approving_administrator()
    user, first = _invited()

    assert _send_again(user, actor) is True

    second = _token()
    assert second != first
    assert AccountActivation.objects.filter(user=user).count() == 1
    assert _activate(first).outcome == REFUSED
    assert _stored(user).status == PENDING
    assert _activate(second).outcome == ACTIVATED
    sent = AccountEvent.objects.filter(event_type="verification_sent")
    assert [(event.user, event.actor) for event in sent] == [(user, actor.user)] * 2


def test_sending_again_starts_the_lifetime_again(clock: Clock, settings: LazySettings) -> None:
    user, first = _invited()
    clock(settings.ACCOUNT_ACTIVATION_LIFETIME)
    assert (
        selectors.accounts_awaiting_verification(approving_administrator())[
            0
        ].verification_expires_at
        is None
    )

    _send_again(user)

    clock(settings.ACCOUNT_ACTIVATION_LIFETIME - timedelta(seconds=1))
    assert _activate(first).outcome == REFUSED
    assert _activate(_token()).outcome == ACTIVATED


@pytest.mark.parametrize("kind", UNAUTHORISED)
def test_only_a_verified_administrator_sends_the_message_again(
    user_with_roles: UserFactory, kind: str
) -> None:
    user, token = _invited()
    actor = _actor_of_kind(kind, user_with_roles)
    key = AccountActivation.objects.get().token_key

    # For an account that awaits verification and for one that does not exist alike.
    for user_id in (user.pk, 2**31):
        with pytest.raises(PermissionDenied):
            services.send_account_verification(
                actor=actor,  # type: ignore[arg-type]  # the wrong kinds of actor are the point of the test
                user_id=user_id,
                source=SOURCE,
                activation_url=activation_url,
            )

    assert AccountActivation.objects.get().token_key == key
    assert len(django_mail.outbox) == 1
    assert _activate(token).outcome == ACTIVATED


@pytest.mark.parametrize("state", ["active", "disabled", "unknown"])
def test_only_an_account_that_awaits_verification_is_sent_the_message(state: str) -> None:
    user = _active()
    if state == "disabled":
        services.disable_user(actor=approving_administrator(), user=user)
    sent, events = len(django_mail.outbox), _events()

    with pytest.raises(AccountChangeError):
        services.send_account_verification(
            actor=approving_administrator(),
            user_id=user.pk if state != "unknown" else 2**31,
            source=SOURCE,
            activation_url=activation_url,
        )

    assert len(django_mail.outbox) == sent
    assert _events() == events
    assert not AccountActivation.objects.exists()


# --- The list an Administrator works from ---------------------------------------------------


def test_the_list_holds_the_accounts_that_await_verification(
    clock: Clock, settings: LazySettings
) -> None:
    first, _ = _invited()
    clock(timedelta(hours=1))
    second, second_token = _invited(OTHER_EMAIL)
    _active("test.active@caipo.test")

    listed = selectors.accounts_awaiting_verification(approving_administrator())

    assert [(item.user_id, item.email) for item in listed] == [
        (first.pk, EMAIL),
        (second.pk, OTHER_EMAIL),
    ]
    assert all(item.verification_expires_at is not None for item in listed)
    assert set(vars(listed[0])) == {"user_id", "email", "created_at", "verification_expires_at"}
    assert second_token not in repr(listed)

    clock(settings.ACCOUNT_ACTIVATION_LIFETIME - timedelta(minutes=30))
    listed = selectors.accounts_awaiting_verification(approving_administrator())
    assert [item.verification_expires_at is None for item in listed] == [True, False]


@pytest.mark.parametrize(
    "kind", [kind for kind in UNAUTHORISED if kind not in {"nobody", "bare-account"}]
)
def test_the_list_is_refused_to_everybody_else(user_with_roles: UserFactory, kind: str) -> None:
    _invited()

    with pytest.raises(PermissionDenied):
        selectors.accounts_awaiting_verification(_actor_of_kind(kind, user_with_roles))  # type: ignore[arg-type]  # the wrong kinds of actor are the point of the test


# --- Status and signing in ------------------------------------------------------------------


def test_signing_in_follows_the_status_at_once() -> None:
    administrator = approving_administrator()
    user, token = _invited()

    # Awaiting verification: no password signs in.
    assert _sign_in(EMAIL, PASSWORD) == SignInOutcome.REFUSED
    _activate(token)
    # Active.
    assert _sign_in(EMAIL, PASSWORD) == SignInOutcome.SIGNED_IN
    context = signed_in(_stored(user))
    assert selectors.can(context, Permission.WORKSPACE_READ) is True
    # Disabled: the right password is refused and the context holds nothing.
    services.disable_user(actor=administrator, user=user)
    assert _sign_in(EMAIL, PASSWORD) == SignInOutcome.REFUSED
    assert selectors.permissions_of(context) == frozenset()
    # Enabled: as it was.
    services.enable_user(actor=administrator, user=user)
    assert _sign_in(EMAIL, PASSWORD) == SignInOutcome.SIGNED_IN
    assert selectors.can(context, Permission.WORKSPACE_READ) is True


def test_an_account_that_cannot_be_signed_in_to_is_refused_like_one_that_does_not_exist() -> None:
    pending, _ = _invited()
    disabled = _active(OTHER_EMAIL)
    services.disable_user(actor=approving_administrator(), user=disabled)

    results = [
        services.sign_in(email=email, password=PASSWORD, source=f"203.0.113.{number}")
        for number, email in enumerate([EMAIL, OTHER_EMAIL, "test.nobody@caipo.test"])
    ]

    assert len({(result.outcome, result.user, result.challenge) for result in results}) == 1
    assert results[0].outcome == SignInOutcome.REFUSED
    assert _stored(pending).last_login is None


# --- Disabling and enabling ------------------------------------------------------------------


def test_disabling_is_recorded_naming_the_administrator(clock: Clock) -> None:
    actor = approving_administrator()
    user = _active()
    clock(timedelta(minutes=1))

    services.disable_user(actor=actor, user=user)

    assert user.status == DISABLED
    stored = _stored(user)
    assert stored.status == DISABLED
    assert stored.is_active is False
    # What it had been is kept.
    assert stored.email_verified_at is not None and stored.activated_at is not None
    assert selectors.roles_of(stored) == {Role.READER}
    event = AccountEvent.objects.get(event_type="account_disabled")
    assert (event.user, event.actor) == (user, actor.user)
    assert event.created_at > stored.activated_at


def test_disabling_an_account_that_awaits_verification_removes_its_token() -> None:
    user, token = _invited()

    services.disable_user(actor=approving_administrator(), user=user)

    assert not AccountActivation.objects.exists()
    assert _stored(user).status == DISABLED
    assert _activate(token).outcome == REFUSED


def test_an_account_that_is_already_disabled_cannot_be_disabled_again() -> None:
    user = _active()
    services.disable_user(actor=approving_administrator(), user=user)
    events = _events()

    with pytest.raises(AccountChangeError):
        services.disable_user(actor=approving_administrator(), user=user)

    assert _events() == events


@pytest.mark.parametrize("kind", UNAUTHORISED)
@pytest.mark.parametrize("operation", ["disable", "enable"])
def test_only_a_verified_administrator_disables_or_enables(
    user_with_roles: UserFactory, kind: str, operation: str
) -> None:
    target = _active()
    if operation == "enable":
        services.disable_user(actor=approving_administrator(), user=target)
    actor = _actor_of_kind(kind, user_with_roles)
    before, events = User.objects.values().get(pk=target.pk), _events()

    change = services.disable_user if operation == "disable" else services.enable_user
    with pytest.raises(PermissionDenied):
        change(actor=actor, user=target)  # type: ignore[arg-type]  # the wrong kinds of actor are the point of the test

    assert User.objects.values().get(pk=target.pk) == before
    assert _events() == events


def test_the_only_administrator_cannot_be_disabled_by_anyone(user_with_roles: UserFactory) -> None:
    only = user_with_roles(Role.ADMINISTRATOR)
    events = _events()

    with pytest.raises(LastAdministratorError):
        services.disable_user(actor=verified(only), user=only)

    assert _stored(only).status == ACTIVE
    assert _events() == events
    assert selectors.can(verified(only), Permission.ACCOUNTS_CREATE) is True


def test_an_administrator_disables_their_own_account_only_while_another_remains(
    user_with_roles: UserFactory,
) -> None:
    first, second = user_with_roles(Role.ADMINISTRATOR), user_with_roles(Role.ADMINISTRATOR)
    as_first = verified(first)

    services.disable_user(actor=as_first, user=first)

    assert _stored(first).status == DISABLED
    event = AccountEvent.objects.get(event_type="account_disabled")
    assert (event.user, event.actor) == (first, first)
    # Having disabled itself, it can do nothing more, including undo it.
    assert selectors.permissions_of(as_first) == frozenset()
    with pytest.raises(PermissionDenied):
        services.enable_user(actor=as_first, user=first)
    # And the one that remains is now the last.
    with pytest.raises(LastAdministratorError):
        services.disable_user(actor=verified(second), user=second)


def test_enabling_returns_an_activated_account_to_active_as_it_was(clock: Clock) -> None:
    actor = approving_administrator()
    user = _active(role=Role.RESEARCHER)
    before = _stored(user)
    services.disable_user(actor=actor, user=user)
    clock(timedelta(hours=1))

    status = services.enable_user(actor=actor, user=user)

    stored = _stored(user)
    assert status == ACTIVE == stored.status == user.status
    assert (stored.password, stored.email_verified_at, stored.activated_at) == (
        before.password,
        before.email_verified_at,
        before.activated_at,
    )
    assert selectors.roles_of(stored) == {Role.RESEARCHER}
    event = AccountEvent.objects.get(event_type="account_enabled")
    assert (event.user, event.actor) == (user, actor.user)
    assert _events(user)[-2:] == ["account_disabled", "account_enabled"]


def test_enabling_never_activates_an_account_that_was_never_verified() -> None:
    actor = approving_administrator()
    user, token = _invited()
    services.disable_user(actor=actor, user=user)

    status = services.enable_user(actor=actor, user=user)

    stored = _stored(user)
    assert status == PENDING == stored.status
    assert (stored.email_verified_at, stored.activated_at) == (None, None)
    assert stored.is_active is False
    assert _sign_in(EMAIL, PASSWORD) == SignInOutcome.REFUSED
    # The earlier token stays dead; a new message is needed.
    assert not AccountActivation.objects.exists()
    assert _activate(token).outcome == REFUSED
    _send_again(user, actor)
    assert _activate(_token()).outcome == ACTIVATED
    assert _stored(user).email_verified_at is not None


@pytest.mark.parametrize("state", ["active", "pending"])
def test_only_a_disabled_account_can_be_enabled(state: str) -> None:
    user = _active() if state == "active" else _invited()[0]
    before, events = User.objects.values().get(pk=user.pk), _events()

    with pytest.raises(AccountChangeError):
        services.enable_user(actor=approving_administrator(), user=user)

    assert User.objects.values().get(pk=user.pk) == before
    assert _events() == events


def test_the_rule_against_enabling_ones_own_account_holds_by_itself(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    administrator = user_with_roles(Role.ADMINISTRATOR, is_active=False)
    user_with_roles(Role.ADMINISTRATOR)
    # Suppose the permission check were bypassed or wrong.
    monkeypatch.setattr(selectors, "require_permission", lambda context, permission: None)

    with pytest.raises(PermissionDenied):
        services.enable_user(actor=verified(administrator), user=administrator)

    assert _stored(administrator).status == DISABLED
    assert _events() == []


def test_disabling_and_enabling_take_an_actor_and_an_account_and_nothing_else() -> None:
    for operation in (services.disable_user, services.enable_user):
        assert set(inspect.signature(operation).parameters) == {"actor", "user"}


@pytest.mark.parametrize("operation", ["disable", "enable"])
def test_a_change_of_status_that_cannot_be_recorded_is_not_made(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    actor = approving_administrator()
    user = _active()
    if operation == "enable":
        services.disable_user(actor=actor, user=user)
    before = _stored(user).status

    def fail(**kwargs: object) -> None:
        raise RuntimeError("TEST failure while recording the change")

    monkeypatch.setattr(AccountEvent.objects, "create", fail)
    change = services.disable_user if operation == "disable" else services.enable_user

    with pytest.raises(RuntimeError):
        change(actor=actor, user=user)

    assert _stored(user).status == before


def test_role_changes_stay_protected_for_accounts_made_this_way() -> None:
    actor = approving_administrator()
    user = _active(role=Role.ADMINISTRATOR)

    # The new Administrator, on its password, changes nobody's roles, its own included.
    with pytest.raises(PermissionDenied):
        services.grant_role(
            actor=signed_in(user), user=user, role=Role.REVIEWER, reason="TEST attempt"
        )
    with pytest.raises(PermissionDenied):
        services.revoke_role(
            actor=signed_in(user), user=actor.user, role=Role.ADMINISTRATOR, reason="TEST attempt"
        )

    assert selectors.roles_of(user) == {Role.ADMINISTRATOR}
    assert selectors.roles_of(actor.user) == {Role.ADMINISTRATOR}


# --- What is recorded ---------------------------------------------------------------------


def test_the_events_of_a_whole_life_name_the_account_the_actor_and_the_time(
    clock: Clock,
) -> None:
    actor = approving_administrator()
    user, token = _invited()
    clock(timedelta(minutes=1))
    _activate("A" * 43)
    clock(timedelta(minutes=1))
    _activate(token)
    clock(timedelta(minutes=1))
    services.disable_user(actor=actor, user=user)
    clock(timedelta(minutes=1))
    services.enable_user(actor=actor, user=user)

    events = list(AccountEvent.objects.order_by("id"))

    assert [(event.event_type, event.user, event.actor) for event in events] == [
        ("account_created", user, actor.user),
        ("verification_sent", user, actor.user),
        ("verification_failed", None, None),
        ("verification_succeeded", user, None),
        ("account_disabled", user, actor.user),
        ("account_enabled", user, actor.user),
    ]
    times = [event.created_at for event in events]
    assert times == sorted(times)
    assert all(time.utcoffset() == timedelta(0) for time in times)


def test_no_event_holds_a_token_a_password_an_address_or_a_source(
    caplog: pytest.LogCaptureFixture,
) -> None:
    actor = approving_administrator()
    with caplog.at_level(logging.DEBUG):
        user, first = _invited()
        _activate(first[:-1] + "x", OTHER_PASSWORD)
        _send_again(user, actor)
        second = _token()
        _activate(second, "short")
        _activate(second)
        services.disable_user(actor=actor, user=user)
        services.enable_user(actor=actor, user=user)

    events = repr(list(AccountEvent.objects.values())) + repr(
        list(AccountActivation.objects.values())
    )
    for forbidden in (
        first,
        second,
        PASSWORD,
        OTHER_PASSWORD,
        EMAIL,
        SOURCE,
        ORIGIN,
        _stored(user).password,
    ):
        assert forbidden not in events, forbidden
    written = logged(caplog.records)
    for forbidden in (first, second, PASSWORD, OTHER_PASSWORD, EMAIL, ORIGIN):
        assert forbidden not in written, forbidden
    assert {field.column for field in AccountEvent._meta.concrete_fields} == {
        "id",
        "event_type",
        "user_id",
        "actor_id",
        "source_key",
        "correlation_id",
        "created_at",
    }


# --- The message -----------------------------------------------------------------------------


def test_the_message_says_what_it_is_for_and_carries_one_link() -> None:
    _, token = _invited()

    (message,) = django_mail.outbox
    body = str(message.body)

    assert message.to == [EMAIL]
    assert message.cc == [] and message.bcc == []
    assert message.subject == "Activate your CAIPO account"
    assert message.content_subtype == "plain"
    assert message.attachments == []
    assert "account has been created" in body
    assert "choose your password" in body
    assert "48 hours" in body
    assert "works once" in body
    assert "ignore it" in body
    assert re.findall(r"https?://\S+", body) == [activation_url(token)]


@pytest.mark.parametrize("role", list(Role))
def test_the_message_holds_nothing_about_the_account_but_the_link(role: Role) -> None:
    actor = approving_administrator()
    user, token = _invited(role=role)
    device_secret = "TEST-totp-secret-000"

    (message,) = django_mail.outbox
    text = (str(message.subject) + str(message.body)).lower()

    forbidden = [
        EMAIL,
        actor.user.email,
        _stored(user).password,
        "argon2",
        device_secret.lower(),
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


def test_the_message_is_the_same_for_every_recipient_apart_from_the_link() -> None:
    _, first = _invited(EMAIL, Role.READER)
    _, second = _invited(OTHER_EMAIL, Role.ADMINISTRATOR)

    one, two = (str(message.body) for message in django_mail.outbox)

    assert one.replace(first, "TOKEN") == two.replace(second, "TOKEN")
    assert django_mail.outbox[0].subject == django_mail.outbox[1].subject


def test_the_link_is_made_by_the_caller_and_the_service_knows_no_address() -> None:
    seen: list[str] = []

    def elsewhere(token: str) -> str:
        seen.append(token)
        return f"https://elsewhere.test/a/#{token}"

    services.create_user(
        actor=approving_administrator(),
        email=EMAIL,
        role=Role.READER,
        source=SOURCE,
        activation_url=elsewhere,
    )

    (message,) = django_mail.outbox
    assert len(seen) == 1
    assert f"https://elsewhere.test/a/#{seen[0]}" in str(message.body)
    source = inspect.getsource(services)
    assert "PUBLIC_BASE_URL" not in source
    assert "reverse(" not in source
