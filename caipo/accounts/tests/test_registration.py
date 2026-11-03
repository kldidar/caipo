"""Registering an account on the site, through the services (ADR-0021).

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
from django.contrib.auth.hashers import get_hasher
from django.core import mail as django_mail
from django.core.exceptions import ValidationError
from django.utils import timezone

from caipo.accounts import selectors, services
from caipo.accounts.models import (
    AccountActivation,
    AccountEvent,
    AccountEventType,
    AccountStatus,
    RoleEvent,
    RoleEventType,
    User,
)
from caipo.accounts.selectors import Permission, Role
from caipo.accounts.services import ActivationOutcome, SignInOutcome
from caipo.accounts.tests.fixtures import (
    Clock,
    UserFactory,
    approving_administrator,
    logged,
    signed_in,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db]

# Visibly synthetic fixture values.
EMAIL = "test.registrant@caipo.test"
OTHER_EMAIL = "test.other.registrant@caipo.test"
PASSWORD = "TEST-passphrase-chosen-at-activation"
OLD_PASSWORD = "TEST-passphrase-of-an-existing-account"
SOURCE = "203.0.113.20"
OTHER_SOURCE = "198.51.100.77"
ORIGIN = "https://caipo.test"

REGISTERED = AccountEventType.ACCOUNT_REGISTERED
REPEATED = AccountEventType.REGISTRATION_REPEATED
MESSAGE_SENT = AccountEventType.REGISTRATION_MESSAGE_SENT


def activation_url(token: str) -> str:
    return f"{ORIGIN}/activate/#{token}"


def _register(email: str = EMAIL, source: str = SOURCE) -> None:
    services.register_account(email=email, source=source, activation_url=activation_url)


def _token(index: int = -1) -> str:
    """Read the token off a verification message, by default the last one sent."""
    (token,) = re.findall(
        rf"{re.escape(ORIGIN)}/activate/#(\S+)", str(django_mail.outbox[index].body)
    )
    return str(token)


def _activate(token: str, source: str = SOURCE) -> ActivationOutcome:
    return services.activate_account(token=token, password=PASSWORD, source=source).outcome


def _events() -> list[tuple[str, int | None, int | None]]:
    return list(
        AccountEvent.objects.order_by("id").values_list("event_type", "user_id", "actor_id")
    )


def _account(email: str, status: AccountStatus) -> User:
    """Return a synthetic account written directly in the given state."""
    now = timezone.now()
    verified = None if status == AccountStatus.PENDING_VERIFICATION else now
    user = User(email=email, status=status, email_verified_at=verified, activated_at=verified)
    user.set_password(OLD_PASSWORD)
    user.save()
    return user


def _stored(user: User) -> User:
    return User.objects.get(pk=user.pk)


# --- A new address ---------------------------------------------------------------------


def test_a_new_address_gets_an_account_that_awaits_verification_with_the_reader_role() -> None:
    _register()

    user = User.objects.get(email=EMAIL)
    assert user.status == AccountStatus.PENDING_VERIFICATION
    assert user.email_verified_at is None
    assert user.activated_at is None
    assert not user.is_active
    assert selectors.roles_of(user) == {Role.READER}
    grant = RoleEvent.objects.get(user=user)
    assert (grant.role, grant.event_type, grant.actor) == (
        Role.READER,
        RoleEventType.GRANTED,
        None,
    )
    assert grant.reason == services.REGISTRATION_ROLE_REASON
    assert "ADR-0021" in grant.reason
    assert AccountActivation.objects.filter(user=user).count() == 1
    assert _events() == [(REGISTERED, user.pk, None), (MESSAGE_SENT, user.pk, None)]


def test_the_message_is_the_verification_message_with_one_link() -> None:
    _register()

    (message,) = django_mail.outbox
    assert message.to == [EMAIL]
    assert message.subject == services.verification_subject()
    assert message.body == services.verification_body(
        url=activation_url(_token()), lifetime_hours=48
    )
    assert len(re.findall(r"https?://", message.body)) == 1


def test_the_password_nobody_knows_signs_nobody_in_before_activation() -> None:
    _register()

    result = services.sign_in(email=EMAIL, password="", source=SOURCE)

    assert result.outcome == SignInOutcome.REFUSED
    assert User.objects.get(email=EMAIL).has_usable_password()


def test_from_registration_to_a_reader_who_can_read_and_do_nothing_else() -> None:
    _register()
    assert _activate(_token()) == ActivationOutcome.ACTIVATED

    result = services.sign_in(email=EMAIL, password=PASSWORD, source=SOURCE)

    assert result.outcome == SignInOutcome.SIGNED_IN
    assert result.user is not None
    assert result.user.status == AccountStatus.ACTIVE
    assert result.user.email_verified_at is not None
    assert selectors.permissions_of(signed_in(result.user)) == {
        Permission.WORKSPACE_READ,
        Permission.MFA_MANAGE_OWN,
        Permission.REGISTRY_READ,
        # Writing an article and sending it for review (ADR-0022).
        Permission.ARTICLES_SUBMIT,
    }
    assert not selectors.can(signed_in(result.user), Permission.RESEARCH_CONTRIBUTE)


def test_registering_takes_no_role_and_no_password() -> None:
    parameters = set(inspect.signature(services.register_account).parameters)

    assert parameters == {"email", "source", "activation_url"}


def test_the_address_is_stored_in_the_form_that_identifies_an_account() -> None:
    _register("  TEST.Registrant@CAIPO.test ")

    assert User.objects.get().email == EMAIL


@pytest.mark.parametrize(
    "typed", ["", "not-an-address", "TEST-passphrase-in-the-wrong-field", "a@" + "b" * 260]
)
def test_a_malformed_address_is_refused_and_nothing_is_stored(typed: str) -> None:
    with pytest.raises(ValidationError):
        _register(typed)

    assert not User.objects.exists()
    assert not RoleEvent.objects.exists()
    assert _events() == []
    assert django_mail.outbox == []


# --- An address that already has an account ---------------------------------------------


@pytest.mark.parametrize("status", [AccountStatus.ACTIVE, AccountStatus.DISABLED])
def test_an_active_or_disabled_account_is_sent_nothing_and_left_as_it_was(
    status: AccountStatus,
) -> None:
    user = _account(EMAIL, status)
    before = _stored(user)

    _register()

    after = _stored(user)
    assert (after.status, after.password, after.email_verified_at) == (
        before.status,
        before.password,
        before.email_verified_at,
    )
    assert User.objects.count() == 1
    assert not RoleEvent.objects.exists()
    assert not AccountActivation.objects.exists()
    assert django_mail.outbox == []
    assert _events() == [(REPEATED, user.pk, None)]


def test_registering_again_gives_an_existing_account_no_role(
    user_with_roles: UserFactory,
) -> None:
    researcher = user_with_roles(Role.RESEARCHER)
    events = RoleEvent.objects.count()

    _register(researcher.email)

    assert selectors.roles_of(researcher) == {Role.RESEARCHER}
    assert RoleEvent.objects.count() == events


def test_an_address_typed_in_another_case_is_the_same_account() -> None:
    user = _account(EMAIL, AccountStatus.ACTIVE)

    _register("Test.Registrant@CAIPO.TEST")

    assert User.objects.count() == 1
    assert _events() == [(REPEATED, user.pk, None)]


def test_an_account_that_awaits_verification_is_sent_the_message_again_with_a_new_token(
    clock: Clock,
) -> None:
    _register()
    first = _token()
    clock(timedelta(minutes=5))

    _register()

    user = User.objects.get()
    assert len(django_mail.outbox) == 2
    second = _token()
    assert second != first
    assert _activate(first) == ActivationOutcome.REFUSED
    assert _activate(second) == ActivationOutcome.ACTIVATED
    assert selectors.roles_of(_stored(user)) == {Role.READER}
    assert RoleEvent.objects.count() == 1
    assert [event[0] for event in _events()] == [
        REGISTERED,
        MESSAGE_SENT,
        REPEATED,
        MESSAGE_SENT,
        AccountEventType.VERIFICATION_FAILED,
        AccountEventType.VERIFICATION_SUCCEEDED,
    ]


def test_an_account_an_administrator_created_keeps_its_role_when_its_owner_registers() -> None:
    administrator = approving_administrator()
    created = services.create_user(
        actor=administrator,
        email=EMAIL,
        role=Role.RESEARCHER,
        source=SOURCE,
        activation_url=activation_url,
    )

    _register()

    assert len(django_mail.outbox) == 2
    assert _activate(_token()) == ActivationOutcome.ACTIVATED
    assert selectors.roles_of(_stored(created.user)) == {Role.RESEARCHER}


def test_messages_sent_again_are_limited_per_account(clock: Clock, settings: LazySettings) -> None:
    limit = settings.ACCOUNT_REGISTRATION_MESSAGE_LIMIT
    for number in range(limit):
        _register(source=f"203.0.113.{number}")
    assert len(django_mail.outbox) == limit
    last = _token()

    _register(source=OTHER_SOURCE)

    assert len(django_mail.outbox) == limit
    assert _events()[-1][0] == REPEATED
    assert _activate(last) == ActivationOutcome.ACTIVATED


def test_messages_an_administrator_had_sent_count_against_the_limit(
    settings: LazySettings,
) -> None:
    administrator = approving_administrator()
    created = services.create_user(
        actor=administrator,
        email=EMAIL,
        role=Role.READER,
        source=SOURCE,
        activation_url=activation_url,
    )
    for _ in range(settings.ACCOUNT_REGISTRATION_MESSAGE_LIMIT - 1):
        services.send_account_verification(
            actor=administrator,
            user_id=created.user.pk,
            source=SOURCE,
            activation_url=activation_url,
        )
    sent = len(django_mail.outbox)

    _register(source=OTHER_SOURCE)

    assert len(django_mail.outbox) == sent


def test_the_limit_on_messages_lifts_when_earlier_ones_age_out(
    clock: Clock, settings: LazySettings
) -> None:
    for number in range(settings.ACCOUNT_REGISTRATION_MESSAGE_LIMIT):
        _register(source=f"203.0.113.{number}")
    clock(settings.ACCOUNT_REGISTRATION_WINDOW)
    _register(source=OTHER_SOURCE)
    assert len(django_mail.outbox) == settings.ACCOUNT_REGISTRATION_MESSAGE_LIMIT

    clock(timedelta(seconds=1))
    _register(source=OTHER_SOURCE)

    assert len(django_mail.outbox) == settings.ACCOUNT_REGISTRATION_MESSAGE_LIMIT + 1


# --- Throttling by source -----------------------------------------------------------------


def test_the_limits_are_ten_registrations_an_hour_from_a_source_and_three_messages(
    settings: LazySettings,
) -> None:
    assert settings.ACCOUNT_REGISTRATION_SOURCE_LIMIT == 10
    assert settings.ACCOUNT_REGISTRATION_WINDOW == timedelta(hours=1)
    assert settings.ACCOUNT_REGISTRATION_MESSAGE_LIMIT == 3


def test_the_limit_on_registrations_from_one_source_is_exact(settings: LazySettings) -> None:
    limit = settings.ACCOUNT_REGISTRATION_SOURCE_LIMIT
    existing = _account(OTHER_EMAIL, AccountStatus.ACTIVE)
    _register(OTHER_EMAIL)
    for number in range(limit - 1):
        _register(f"test.registrant{number}@caipo.test")
    assert User.objects.count() == limit
    events = _events()

    _register()

    # Beyond the limit nothing is created, sent, or recorded, whatever the address.
    assert not User.objects.filter(email=EMAIL).exists()
    assert len(django_mail.outbox) == limit - 1
    assert _events() == events
    assert _events()[0] == (REPEATED, existing.pk, None)

    _register(source=OTHER_SOURCE)

    assert User.objects.filter(email=EMAIL).exists()


def test_the_limit_on_a_source_lifts_when_earlier_registrations_age_out(
    clock: Clock, settings: LazySettings
) -> None:
    for number in range(settings.ACCOUNT_REGISTRATION_SOURCE_LIMIT):
        _register(f"test.registrant{number}@caipo.test")
    clock(settings.ACCOUNT_REGISTRATION_WINDOW)
    _register()
    assert not User.objects.filter(email=EMAIL).exists()

    clock(timedelta(seconds=1))
    _register()

    assert User.objects.filter(email=EMAIL).exists()


def test_activations_and_messages_do_not_count_against_the_limit_on_a_source(
    settings: LazySettings,
) -> None:
    settings.ACCOUNT_REGISTRATION_SOURCE_LIMIT = 2
    _register()
    assert _activate(_token()) == ActivationOutcome.ACTIVATED
    assert _activate("TEST-not-a-token") == ActivationOutcome.REFUSED

    _register(OTHER_EMAIL)

    assert User.objects.filter(email=OTHER_EMAIL).exists()


# --- What a caller can tell ---------------------------------------------------------------


def test_every_registration_returns_nothing_and_costs_one_password_hash(
    monkeypatch: pytest.MonkeyPatch, user_with_roles: UserFactory
) -> None:
    hasher = type(get_hasher())
    original = hasher.encode
    hashed: list[str] = []

    def counting(self: Any, password: str, salt: str, *args: Any, **kwargs: Any) -> str:
        hashed.append(salt)
        return str(original(self, password, salt, *args, **kwargs))

    _account("test.active@caipo.test", AccountStatus.ACTIVE)
    _account("test.disabled@caipo.test", AccountStatus.DISABLED)
    _account("test.pending@caipo.test", AccountStatus.PENDING_VERIFICATION)
    monkeypatch.setattr(hasher, "encode", counting)

    for email in (EMAIL, "test.active@caipo.test", "test.disabled@caipo.test"):
        hashed.clear()
        assert (
            services.register_account(email=email, source=SOURCE, activation_url=activation_url)
            is None
        )
        assert len(hashed) == 1, email
    hashed.clear()
    assert (
        services.register_account(
            email="test.pending@caipo.test", source=SOURCE, activation_url=activation_url
        )
        is None
    )
    assert len(hashed) == 1


def test_every_registration_logs_the_same_line_without_the_address_or_a_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _account("test.active@caipo.test", AccountStatus.ACTIVE)

    with caplog.at_level(logging.INFO, logger="caipo.accounts.services"):
        _register()
        _register("test.active@caipo.test")

    taken = [record for record in caplog.records if record.getMessage() == "Registration taken"]
    assert len(taken) == 2
    text = logged(caplog.records)
    assert "caipo.test" not in text
    assert _token() not in text
    assert not hasattr(taken[0], "user_id")


def test_a_message_that_cannot_be_sent_leaves_an_account_that_can_be_sent_another(
    settings: LazySettings, caplog: pytest.LogCaptureFixture
) -> None:
    settings.EMAIL_BACKEND = "caipo.core.mail.RefusingEmailBackend"

    with caplog.at_level(logging.ERROR, logger="caipo.accounts.services"):
        _register()

    user = User.objects.get()
    assert user.status == AccountStatus.PENDING_VERIFICATION
    assert _events() == [(REGISTERED, user.pk, None)]
    assert "The verification message could not be sent" in caplog.text
    assert "caipo.test" not in logged(caplog.records)

    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    _register()

    assert len(django_mail.outbox) == 1
    assert _activate(_token()) == ActivationOutcome.ACTIVATED


def test_the_link_is_built_by_the_caller_and_the_token_is_stored_only_as_a_keyed_hash() -> None:
    _register()

    token = _token()
    activation = AccountActivation.objects.get()
    assert activation.token_key == services._key("activation", token)
    assert token not in str(list(AccountEvent.objects.values()))
    source = inspect.getsource(services.register_account)
    assert "PUBLIC_BASE_URL" not in source
    assert "reverse(" not in source
