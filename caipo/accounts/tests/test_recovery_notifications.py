"""The messages about a recovery of a lost second factor (ADR-0017 points 79 to 81).

Who is told what, and that telling them decides nothing: a message that
cannot be sent leaves the recovery, the record, and the answer as they are.
The messages are kept in memory by the test settings; one test backend here
refuses chosen recipients, and the production default refuses them all.
"""

import inspect
import logging
import re
import smtplib
from collections.abc import Callable, Iterator, Sequence

import pytest
from django.conf import LazySettings
from django.core import mail as django_mail
from django.core.exceptions import PermissionDenied
from django.core.mail import EmailMessage
from django.core.mail.backends import locmem
from django.utils import timezone

from caipo.accounts import services
from caipo.accounts.models import (
    AccountStatus,
    AuthenticationEvent,
    MfaRecoveryRequest,
    RoleEventType,
    TotpDevice,
    TotpDeviceState,
    User,
)
from caipo.accounts.selectors import AuthenticationContext, Role
from caipo.accounts.services import (
    BreakGlassOutcome,
    MfaOutcome,
    RecoveryNotice,
    RecoveryRequestOutcome,
    SignInOutcome,
)
from caipo.accounts.tests.fixtures import (
    UserFactory,
    enrolled_device,
    logged,
    signed_in,
    verified,
)
from caipo.accounts.tests.test_recovery_authorization import (
    AUTHORIZED,
    PASSWORD,
    REJECTED,
    SOURCE,
    UNAVAILABLE,
    _approve,
    _asked,
    _authorize,
    _challenge,
    _change_role,
    _confirm,
    _enrolment_request,
    _reject,
    _reset_password,
    _state,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db]

type AccountFactory = Callable[..., User]

SUBJECT = "CAIPO security notice"
REQUEST_MADE = "A second-factor recovery request was made."
FINALIZED = "A second-factor recovery was finalized."
EMERGENCY = "An emergency second-factor recovery action was performed."

REFUSING_BACKEND = "caipo.core.mail.RefusingEmailBackend"
SELECTIVE_BACKEND = f"{__name__}.SelectiveBackend"

# The addresses the selective backend refuses. Emptied after each test.
_refused: set[str] = set()


class SelectiveBackend(locmem.EmailBackend):
    """Keeps messages in memory, as the test settings do, but refuses chosen recipients.

    It refuses as a mail service does: with an error that repeats the
    recipient's address.
    """

    def send_messages(self, email_messages: Sequence[EmailMessage]) -> int:
        for message in email_messages:
            for address in message.to:
                if address in _refused:
                    raise smtplib.SMTPRecipientsRefused({address: (550, b"TEST refusal")})
        return super().send_messages(email_messages)


@pytest.fixture(autouse=True)
def _nobody_refused() -> Iterator[None]:
    _refused.clear()
    yield
    _refused.clear()


@pytest.fixture
def account(user_with_roles: UserFactory) -> AccountFactory:
    """Return a factory for synthetic users with a known password, an active second factor,
    and, unless told otherwise, a verified email address."""

    def make(*roles: Role, address_verified: bool = True, device: bool = True) -> User:
        user = user_with_roles(*roles)
        user.set_password(PASSWORD)
        user.save()
        if device:
            enrolled_device(user)
        if address_verified:
            _verify_address(user)
        return user

    return make


def _verify_address(user: User) -> None:
    User.objects.filter(pk=user.pk).update(email_verified_at=timezone.now())
    user.refresh_from_db()


def _sent() -> list[tuple[str, str]]:
    """Return every message kept so far as its one recipient and its text, and forget them."""
    messages = [(message.to, message.subject, message.body) for message in django_mail.outbox]
    django_mail.outbox.clear()
    for to, subject, body in messages:
        assert len(to) == 1
        assert subject == SUBJECT
        assert body in (REQUEST_MADE, FINALIZED, EMERGENCY)
    return sorted((to[0], str(body)) for to, _subject, body in messages)


def _revoke_at_server(user: User, number: int) -> BreakGlassOutcome:
    return services.break_glass_revoke_device(email=user.email, request_number=number).outcome


def _approve_at_server(user: User, number: int) -> BreakGlassOutcome:
    return services.break_glass_approve_enrollment(email=user.email, request_number=number).outcome


def _notice_lines(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if str(record.__dict__.get("event", "")).startswith("mfa_recovery.notice")
    ]


def _fail(*args: object, **kwargs: object) -> None:
    raise RuntimeError("TEST fault while recording the event")


# --- The three messages (point 80) ------------------------------------------------------


def test_the_three_messages_are_exactly_these() -> None:
    assert services.recovery_notice_subject() == SUBJECT
    assert {notice: services.recovery_notice_body(notice) for notice in RecoveryNotice} == {
        RecoveryNotice.REQUESTED: REQUEST_MADE,
        RecoveryNotice.FINALIZED: FINALIZED,
        RecoveryNotice.EMERGENCY: EMERGENCY,
    }
    assert len(RecoveryNotice) == 3


@pytest.mark.parametrize("notice", list(RecoveryNotice))
def test_a_message_holds_nothing_that_differs_from_one_recovery_to_the_next(
    notice: RecoveryNotice,
) -> None:
    # The text takes no argument but which of the three it is.
    assert list(inspect.signature(services.recovery_notice_body).parameters) == ["notice"]
    assert list(inspect.signature(services.recovery_notice_subject).parameters) == []
    for text in (services.recovery_notice_body(notice), services.recovery_notice_subject()):
        assert not re.search(r"\d", text)
        assert "%" not in text
        assert "{" not in text
        lowered = text.lower()
        for forbidden in (
            "@",
            "http",
            "://",
            "www",
            "/",
            "#",
            "administrator",
            "reviewer",
            "researcher",
            "reader",
            "token",
            "password",
            "number",
            "break",
            "your",
        ):
            assert forbidden not in lowered, forbidden


def test_a_message_sent_holds_no_name_address_number_role_or_link(
    account: AccountFactory,
) -> None:
    user = account(Role.REVIEWER)
    actor, other = account(Role.ADMINISTRATOR), account(Role.ADMINISTRATOR)
    number = _asked(user)
    assert _authorize(number, verified(actor)) == AUTHORIZED
    messages = list(django_mail.outbox)

    assert len(messages) == 3
    for message in messages:
        assert message.cc == [] and message.bcc == [] and message.reply_to == []
        assert message.attachments == []
        assert message.extra_headers == {}
        text = f"{message.subject}\n{message.body}"
        for forbidden in (user.email, actor.email, other.email, str(number), "http", "@"):
            assert forbidden not in text, forbidden
    # Every recipient of one message gets the same text.
    assert {(message.subject, message.body) for message in messages[1:]} == {(SUBJECT, FINALIZED)}


# --- A request (owner only) -------------------------------------------------------------


def test_a_request_tells_the_owner_and_nobody_else(account: AccountFactory) -> None:
    user = account(Role.REVIEWER)
    account(Role.ADMINISTRATOR)
    account(Role.ADMINISTRATOR)

    _asked(user)

    assert _sent() == [(user.email, REQUEST_MADE)]


def test_a_request_for_an_administrator_tells_only_that_administrator(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    account(Role.ADMINISTRATOR)

    _asked(user)

    assert _sent() == [(user.email, REQUEST_MADE)]


def test_a_request_tells_nobody_if_the_owners_address_was_never_verified(
    account: AccountFactory,
) -> None:
    user = account(Role.REVIEWER, address_verified=False)
    account(Role.ADMINISTRATOR)

    number = _asked(user)

    assert _sent() == []
    assert MfaRecoveryRequest.objects.filter(pk=number, user=user).exists()


def test_each_new_request_tells_the_owner_once(account: AccountFactory) -> None:
    user = account(Role.REVIEWER)

    _asked(user)
    _asked(user)

    assert _sent() == [(user.email, REQUEST_MADE)] * 2


def test_a_refused_submission_tells_nobody(account: AccountFactory) -> None:
    # A Reader's second factor is not recovered: the submission is refused
    # and recorded as `mfa_recovery_failed`.
    user = account(Role.READER)

    result = services.request_mfa_recovery(challenge=_challenge(user), source=SOURCE)

    assert result.outcome == RecoveryRequestOutcome.REFUSED
    assert AuthenticationEvent.objects.filter(event_type="mfa_recovery_failed").count() == 1
    assert _sent() == []


def test_an_unknown_challenge_tells_nobody(account: AccountFactory) -> None:
    account(Role.REVIEWER)

    result = services.request_mfa_recovery(challenge="TEST-no-such-challenge", source=SOURCE)

    assert result.outcome == RecoveryRequestOutcome.REFUSED
    assert _sent() == []


def test_a_throttled_submission_tells_nobody(
    account: AccountFactory, settings: LazySettings
) -> None:
    settings.MFA_RECOVERY_REQUEST_ACCOUNT_LIMIT = 2
    user = account(Role.REVIEWER)
    _asked(user)
    _asked(user)
    _sent()

    result = services.request_mfa_recovery(challenge=_challenge(user), source=SOURCE)

    assert result.outcome == RecoveryRequestOutcome.THROTTLED
    assert _sent() == []


def test_a_rejection_tells_nobody(account: AccountFactory) -> None:
    user = account(Role.REVIEWER)
    actor = account(Role.ADMINISTRATOR)
    account(Role.ADMINISTRATOR)
    number = _asked(user)
    _sent()

    assert _reject(number, verified(actor)) == REJECTED

    assert _sent() == []


# --- A finalisation by an authorisation -------------------------------------------------


def test_an_authorisation_tells_the_owner_and_the_other_administrators(
    account: AccountFactory,
) -> None:
    user = account(Role.REVIEWER)
    actor, other = account(Role.ADMINISTRATOR), account(Role.ADMINISTRATOR)
    number = _asked(user)
    _sent()

    assert _authorize(number, verified(actor)) == AUTHORIZED

    assert _sent() == sorted([(user.email, FINALIZED), (other.email, FINALIZED)])


def test_the_administrator_who_authorised_is_not_told(account: AccountFactory) -> None:
    user = account(Role.REVIEWER)
    actor = account(Role.ADMINISTRATOR)
    account(Role.ADMINISTRATOR)
    number = _asked(user)
    _sent()

    assert _authorize(number, verified(actor)) == AUTHORIZED

    assert actor.email not in [to for to, _body in _sent()]


def test_a_recovered_administrator_is_told_once_as_the_owner(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    actor, other = account(Role.ADMINISTRATOR), account(Role.ADMINISTRATOR)
    number = _asked(user)
    _sent()

    assert _authorize(number, verified(actor)) == AUTHORIZED

    assert _sent() == sorted([(user.email, FINALIZED), (other.email, FINALIZED)])


def test_only_active_administrators_with_a_verified_address_are_told(
    account: AccountFactory,
) -> None:
    user = account(Role.REVIEWER)
    actor, able = account(Role.ADMINISTRATOR), account(Role.ADMINISTRATOR)
    # An Administrator on record who lost the device is told all the same.
    without_device = account(Role.ADMINISTRATOR, device=False)
    account(Role.ADMINISTRATOR, address_verified=False)
    disabled = account(Role.ADMINISTRATOR)
    User.objects.filter(pk=disabled.pk).update(status=AccountStatus.DISABLED)
    former = account(Role.ADMINISTRATOR)
    _change_role(former, Role.ADMINISTRATOR, RoleEventType.REVOKED)
    awaiting = account(Role.ADMINISTRATOR)
    User.objects.filter(pk=awaiting.pk).update(
        status=AccountStatus.PENDING_VERIFICATION, email_verified_at=None, activated_at=None
    )
    for role in (Role.READER, Role.RESEARCHER, Role.REVIEWER):
        account(role)
    number = _asked(user)
    _sent()

    assert _authorize(number, verified(actor)) == AUTHORIZED

    assert _sent() == sorted(
        [(user.email, FINALIZED), (able.email, FINALIZED), (without_device.email, FINALIZED)]
    )


def test_an_owner_whose_address_was_never_verified_is_not_told_of_the_finalisation(
    account: AccountFactory,
) -> None:
    user = account(Role.REVIEWER, address_verified=False)
    actor, other = account(Role.ADMINISTRATOR), account(Role.ADMINISTRATOR)
    number = _asked(user)

    assert _authorize(number, verified(actor)) == AUTHORIZED

    assert _sent() == [(other.email, FINALIZED)]


def test_an_authorisation_that_is_not_made_tells_nobody(account: AccountFactory) -> None:
    user = account(Role.REVIEWER)
    # Nobody exists to approve the device that follows (point 38).
    actor = account(Role.ADMINISTRATOR)
    account(Role.ADMINISTRATOR, device=False)
    number = _asked(user)
    _sent()

    assert _authorize(number, verified(actor)) == UNAVAILABLE
    assert _authorize(number + 1, verified(actor)) == UNAVAILABLE

    assert _sent() == []


def test_an_authorisation_that_is_refused_tells_nobody(account: AccountFactory) -> None:
    user = account(Role.REVIEWER)
    account(Role.ADMINISTRATOR)
    account(Role.ADMINISTRATOR)
    number = _asked(user)
    _sent()

    with pytest.raises(PermissionDenied):
        _authorize(number, verified(account(Role.REVIEWER)))

    assert _sent() == []


def test_an_authorisation_given_again_tells_nobody_again(account: AccountFactory) -> None:
    user = account(Role.REVIEWER)
    actor, other = account(Role.ADMINISTRATOR), account(Role.ADMINISTRATOR)
    number = _asked(user)
    assert _authorize(number, verified(actor)) == AUTHORIZED
    _sent()

    assert _authorize(number, verified(actor)) == UNAVAILABLE
    assert _authorize(number, verified(other)) == UNAVAILABLE

    assert _sent() == []


def test_nothing_after_the_finalisation_tells_anybody(account: AccountFactory) -> None:
    # The enrolment that follows, its approval, the first code that completes
    # the recovery, and an ordinary sign-in: no message for any of them.
    user = account(Role.REVIEWER)
    actor, other = account(Role.ADMINISTRATOR), account(Role.ADMINISTRATOR)
    assert _authorize(_asked(user), verified(actor)) == AUTHORIZED
    _sent()

    secret, number = _enrolment_request(user)
    assert _approve(number, verified(other)).outcome == MfaOutcome.ACCEPTED
    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED
    assert AuthenticationEvent.objects.filter(event_type="mfa_recovery_completed").count() == 1
    challenge = services.sign_in(email=user.email, password=PASSWORD, source=SOURCE)
    assert challenge.outcome == SignInOutcome.SECOND_FACTOR_REQUIRED

    assert _sent() == []


def test_a_password_reset_sends_only_its_own_message(account: AccountFactory) -> None:
    user = account(Role.REVIEWER)
    account(Role.ADMINISTRATOR)

    _reset_password(user)

    (message,) = django_mail.outbox
    assert message.to == [user.email]
    assert message.subject == services.password_reset_subject()


# --- The break-glass command ------------------------------------------------------------


def test_a_revocation_at_the_server_tells_the_owner_and_the_other_administrators_differently(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    able = account(Role.ADMINISTRATOR)
    without_device = account(Role.ADMINISTRATOR, device=False)
    account(Role.ADMINISTRATOR, address_verified=False, device=False)
    account(Role.REVIEWER)
    number = _asked(user)
    _sent()

    assert _revoke_at_server(user, number) == BreakGlassOutcome.DONE

    # One message for each Administrator, and it is the one about the
    # emergency action: not that one and the one about the finalisation.
    assert _sent() == sorted(
        [(user.email, FINALIZED), (able.email, EMERGENCY), (without_device.email, EMERGENCY)]
    )


def test_a_revocation_at_the_server_for_the_only_administrator_tells_only_the_owner(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    number = _asked(user)
    _sent()

    assert _revoke_at_server(user, number) == BreakGlassOutcome.DONE

    assert _sent() == [(user.email, FINALIZED)]


def test_a_revocation_at_the_server_tells_no_owner_whose_address_was_never_verified(
    account: AccountFactory,
) -> None:
    # The first Administrator's position: created at the server, never verified.
    user = account(Role.ADMINISTRATOR, address_verified=False)
    other = account(Role.ADMINISTRATOR, device=False)
    number = _asked(user)

    assert _revoke_at_server(user, number) == BreakGlassOutcome.DONE

    assert _sent() == [(other.email, EMERGENCY)]


def test_an_approval_at_the_server_tells_the_other_administrators_and_not_the_owner(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    other = account(Role.ADMINISTRATOR, device=False)
    account(Role.ADMINISTRATOR, address_verified=False, device=False)
    assert _revoke_at_server(user, _asked(user)) == BreakGlassOutcome.DONE
    secret, number = _enrolment_request(user)
    _sent()

    assert _approve_at_server(user, number) == BreakGlassOutcome.DONE

    assert _sent() == [(other.email, EMERGENCY)]
    # The first code completes the recovery, as before, and tells nobody.
    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED
    assert AuthenticationEvent.objects.filter(event_type="mfa_recovery_completed").count() == 1
    assert _sent() == []


def test_an_approval_at_the_server_after_an_authorisation_tells_whoever_authorised(
    account: AccountFactory,
) -> None:
    # Nobody acted in the command, so nobody is left out: the Administrator
    # who authorised is one of the others.
    user = account(Role.ADMINISTRATOR)
    actor, approver = account(Role.ADMINISTRATOR), account(Role.ADMINISTRATOR)
    assert _authorize(_asked(user), verified(actor)) == AUTHORIZED
    TotpDevice.objects.filter(user=approver).delete()
    _secret, number = _enrolment_request(user)
    _sent()

    assert _approve_at_server(user, number) == BreakGlassOutcome.DONE

    assert _sent() == sorted([(actor.email, EMERGENCY), (approver.email, EMERGENCY)])


def test_a_break_glass_action_that_is_not_performed_tells_nobody(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    account(Role.ADMINISTRATOR)
    account(Role.ADMINISTRATOR)
    number = _asked(user)
    _sent()

    # The application's own path is available, so the command refuses.
    assert _revoke_at_server(user, number) == BreakGlassOutcome.UNAVAILABLE
    assert _approve_at_server(user, number) == BreakGlassOutcome.UNAVAILABLE
    assert (
        services.break_glass_revoke_device(
            email="test.nobody@caipo.test", request_number=number
        ).outcome
        == BreakGlassOutcome.UNAVAILABLE
    )

    assert _sent() == []


def test_a_revocation_given_again_tells_nobody_again(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    account(Role.ADMINISTRATOR, device=False)
    number = _asked(user)
    assert _revoke_at_server(user, number) == BreakGlassOutcome.DONE
    _sent()

    assert _revoke_at_server(user, number) == BreakGlassOutcome.UNAVAILABLE

    assert _sent() == []


# --- Delivery decides nothing (points 14, 79, and 81) -----------------------------------


def test_a_request_is_made_all_the_same_when_no_message_can_be_sent(
    account: AccountFactory, settings: LazySettings, caplog: pytest.LogCaptureFixture
) -> None:
    user = account(Role.REVIEWER)
    challenge = _challenge(user)
    settings.EMAIL_BACKEND = REFUSING_BACKEND

    result = services.request_mfa_recovery(challenge=challenge, source=SOURCE)

    assert result.outcome == RecoveryRequestOutcome.REQUESTED
    assert result.number is not None
    assert MfaRecoveryRequest.objects.filter(pk=result.number, user=user).exists()
    assert AuthenticationEvent.objects.filter(event_type="mfa_recovery_requested").count() == 1
    (record,) = _notice_lines(caplog)
    assert record.__dict__["event"] == "mfa_recovery.notice_not_sent"


def test_an_authorisation_is_made_all_the_same_when_no_message_can_be_sent(
    account: AccountFactory, settings: LazySettings, caplog: pytest.LogCaptureFixture
) -> None:
    user = account(Role.REVIEWER)
    actor, other = account(Role.ADMINISTRATOR), account(Role.ADMINISTRATOR)
    number = _asked(user)
    _sent()
    caplog.clear()
    settings.EMAIL_BACKEND = REFUSING_BACKEND

    assert _authorize(number, verified(actor)) == AUTHORIZED

    assert not TotpDevice.objects.filter(user=user).exists()
    assert User.objects.get(pk=user.pk).session_epoch == 1
    assert AuthenticationEvent.objects.filter(event_type="mfa_recovery_authorized").count() == 1
    assert django_mail.outbox == []
    # Each recipient was tried, and each failure is one line.
    assert sorted(record.__dict__["user_id"] for record in _notice_lines(caplog)) == sorted(
        [user.pk, other.pk]
    )


@pytest.mark.parametrize("action", ["revoke", "approve"])
def test_a_break_glass_action_is_performed_all_the_same_when_no_message_can_be_sent(
    action: str, account: AccountFactory, settings: LazySettings
) -> None:
    user = account(Role.ADMINISTRATOR)
    account(Role.ADMINISTRATOR, device=False)
    number = _asked(user)
    if action == "approve":
        assert _revoke_at_server(user, number) == BreakGlassOutcome.DONE
        _secret, number = _enrolment_request(user)
    settings.EMAIL_BACKEND = REFUSING_BACKEND

    done = _revoke_at_server if action == "revoke" else _approve_at_server
    assert done(user, number) == BreakGlassOutcome.DONE

    assert AuthenticationEvent.objects.filter(event_type="mfa_recovery_break_glass").count() == (
        1 if action == "revoke" else 2
    )
    if action == "approve":
        assert TotpDevice.objects.get(user=user).state == TotpDeviceState.PENDING_VERIFICATION
    else:
        assert not TotpDevice.objects.filter(user=user).exists()


def test_the_state_left_is_the_same_whether_or_not_the_messages_were_sent(
    account: AccountFactory, settings: LazySettings
) -> None:
    def after_authorising(backend: str) -> dict[str, object]:
        user = account(Role.REVIEWER)
        actor = account(Role.ADMINISTRATOR)
        account(Role.ADMINISTRATOR)
        number = _asked(user)
        settings.EMAIL_BACKEND = backend
        assert _authorize(number, verified(actor)) == AUTHORIZED
        state = _state()
        return {
            "events": [event["event_type"] for event in state["events"] if event["user_id"]][-2:],
            "requests": state["requests"],
            "devices": TotpDevice.objects.filter(user=user).count(),
            "epoch": User.objects.get(pk=user.pk).session_epoch,
        }

    assert after_authorising(REFUSING_BACKEND) == after_authorising(
        "django.core.mail.backends.locmem.EmailBackend"
    )


@pytest.mark.parametrize("refused", ["owner", "first administrator", "last administrator"])
def test_one_recipient_who_cannot_be_reached_does_not_stop_the_others(
    refused: str,
    account: AccountFactory,
    settings: LazySettings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user = account(Role.REVIEWER)
    actor = account(Role.ADMINISTRATOR)
    first, last = account(Role.ADMINISTRATOR), account(Role.ADMINISTRATOR)
    unreachable = {"owner": user, "first administrator": first, "last administrator": last}[refused]
    number = _asked(user)
    _sent()
    caplog.clear()
    settings.EMAIL_BACKEND = SELECTIVE_BACKEND
    _refused.add(unreachable.email)

    assert _authorize(number, verified(actor)) == AUTHORIZED

    reached = sorted({user.email, first.email, last.email} - {unreachable.email})
    assert _sent() == [(email, FINALIZED) for email in reached]
    lines = _notice_lines(caplog)
    assert sorted(
        (record.__dict__["event"], record.__dict__["user_id"]) for record in lines
    ) == sorted(
        [("mfa_recovery.notice_not_sent", unreachable.pk)]
        + [
            ("mfa_recovery.notice_sent", recipient.pk)
            for recipient in (user, first, last)
            if recipient != unreachable
        ]
    )


def test_a_message_that_cannot_be_sent_is_logged_without_its_address_or_a_traceback(
    account: AccountFactory, settings: LazySettings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    user = account(Role.REVIEWER)
    actor, other = account(Role.ADMINISTRATOR), account(Role.ADMINISTRATOR)
    number = _asked(user)
    caplog.clear()
    settings.EMAIL_BACKEND = SELECTIVE_BACKEND
    _refused.update({user.email, other.email})

    assert _authorize(number, verified(actor)) == AUTHORIZED

    failures = [
        record
        for record in caplog.records
        if record.__dict__.get("event") == "mfa_recovery.notice_not_sent"
    ]
    assert len(failures) == 2
    for record in failures:
        assert record.levelno == logging.ERROR
        # The error of the mail service repeats the address, so it is not kept.
        assert record.exc_info is None
        assert record.exc_text is None
        assert record.stack_info is None
        extra = {
            name: value
            for name, value in vars(record).items()
            if name not in vars(logging.makeLogRecord({})) and name != "message"
        }
        assert set(extra) == {"event", "notice", "user_id", "cause"}
        assert extra["notice"] == "finalized"
        assert extra["cause"] == "SMTPRecipientsRefused"
    everything = logged(caplog.records)
    for email in (user.email, actor.email, other.email):
        assert email not in everything
    assert "TEST refusal" not in everything
    assert FINALIZED not in everything


def test_a_message_that_was_sent_is_logged_by_account_and_not_by_address(
    account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    user = account(Role.REVIEWER)
    caplog.clear()

    _asked(user)

    (record,) = _notice_lines(caplog)
    assert record.__dict__["event"] == "mfa_recovery.notice_sent"
    assert record.__dict__["notice"] == "requested"
    assert record.__dict__["user_id"] == user.pk
    assert user.email not in logged(caplog.records)


def test_no_message_and_no_event_is_recorded_for_a_message(account: AccountFactory) -> None:
    # No "notification sent" event exists: the six event types are fixed.
    user = account(Role.REVIEWER)
    actor = account(Role.ADMINISTRATOR)
    account(Role.ADMINISTRATOR)
    number = _asked(user)
    before = AuthenticationEvent.objects.count()

    assert _authorize(number, verified(actor)) == AUTHORIZED

    assert AuthenticationEvent.objects.count() == before + 1


# --- Nothing is sent for a change that was not made -------------------------------------


def test_a_request_whose_event_cannot_be_written_tells_nobody(
    account: AccountFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = account(Role.REVIEWER)
    challenge = _challenge(user)

    with monkeypatch.context() as patched:
        patched.setattr(services, "_record", _fail)
        with pytest.raises(RuntimeError, match="TEST fault"):
            services.request_mfa_recovery(challenge=challenge, source=SOURCE)

    assert _sent() == []
    assert not MfaRecoveryRequest.objects.filter(user=user).exists()


def test_an_authorisation_whose_event_cannot_be_written_tells_nobody(
    account: AccountFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = account(Role.REVIEWER)
    actor = account(Role.ADMINISTRATOR)
    account(Role.ADMINISTRATOR)
    number = _asked(user)
    _sent()

    with monkeypatch.context() as patched:
        patched.setattr(services, "_record", _fail)
        with pytest.raises(RuntimeError, match="TEST fault"):
            _authorize(number, verified(actor))

    assert _sent() == []
    assert TotpDevice.objects.filter(user=user, state=TotpDeviceState.ACTIVE).exists()


@pytest.mark.parametrize("action", ["revoke", "approve"])
def test_a_break_glass_action_whose_event_cannot_be_written_tells_nobody(
    action: str, account: AccountFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = account(Role.ADMINISTRATOR)
    account(Role.ADMINISTRATOR, device=False)
    number = _asked(user)
    if action == "approve":
        assert _revoke_at_server(user, number) == BreakGlassOutcome.DONE
        _secret, number = _enrolment_request(user)
    _sent()
    done = _revoke_at_server if action == "revoke" else _approve_at_server

    with monkeypatch.context() as patched:
        patched.setattr(services, "_record", _fail)
        with pytest.raises(RuntimeError, match="TEST fault"):
            done(user, number)

    assert _sent() == []


# --- Where the messages are sent from ---------------------------------------------------

SENDERS = {
    "request_mfa_recovery": 1,
    "authorize_mfa_recovery": 1,
    "break_glass_revoke_device": 2,
    "break_glass_approve_enrollment": 1,
}


def test_only_four_services_send_a_message_about_a_recovery() -> None:
    source = inspect.getsource(services)

    # The four below, and the definition.
    assert source.count("_notify_of_recovery(") == sum(SENDERS.values()) + 1
    for name, calls in SENDERS.items():
        assert inspect.getsource(getattr(services, name)).count("_notify_of_recovery(") == calls
    for name in (
        "reject_mfa_recovery",
        "confirm_mfa_enrollment",
        "approve_mfa_enrollment",
        "reject_mfa_enrollment",
        "_decide_enrollment",
        "start_mfa_enrollment",
        "reset_password",
        "sign_in",
        "verify_second_factor",
        "_recovery_refused",
        "_finalize_recovery",
    ):
        assert "_notify_of_recovery" not in inspect.getsource(getattr(services, name)), name


@pytest.mark.parametrize("name", sorted(SENDERS))
def test_a_message_is_sent_only_after_the_transaction_has_ended(name: str) -> None:
    # Each service is one function with one transaction block. A statement of
    # the function itself is indented by four spaces and one inside the block
    # by at least eight: every send is one of the former, after the block,
    # and the recipients are read inside it.
    body = inspect.getsource(getattr(services, name)).split('"""')[2]
    lines = body.splitlines()
    block = next(index for index, line in enumerate(lines) if "transaction.atomic()" in line)
    assert sum("transaction.atomic()" in line for line in lines) == 1
    sends = [index for index, line in enumerate(lines) if "_notify_of_recovery(" in line]
    assert sends
    for index in sends:
        assert lines[index].startswith("    _notify_of_recovery("), lines[index]
        assert index > block
    readers = [index for index, line in enumerate(lines) if "_to_notify(" in line]
    assert readers
    for index in readers:
        assert lines[index].startswith("        "), lines[index]
        assert block < index < sends[0]
    assert "mail.deliver" not in body


def test_the_function_that_sends_reads_nothing_from_the_database() -> None:
    body = inspect.getsource(services._notify_of_recovery).split('"""')[2]

    for forbidden in (".objects", "selectors.", "transaction", "_lock", "_record("):
        assert forbidden not in body, forbidden
    # Only the one error the email boundary raises is caught.
    assert body.count("except ") == 1
    assert "except mail.DeliveryError as error:" in body


def test_whoever_is_told_is_read_from_the_account_that_was_locked() -> None:
    # A context built by a caller is not where the address comes from.
    assert list(inspect.signature(services._owner_to_notify).parameters) == ["user"]
    assert list(inspect.signature(services._administrators_to_notify).parameters) == ["besides"]


def test_an_administrator_context_is_not_needed_to_be_told(account: AccountFactory) -> None:
    # Being told is not a permission: the other Administrator has never
    # signed in with a second factor in this test.
    user = account(Role.REVIEWER)
    actor: AuthenticationContext = verified(account(Role.ADMINISTRATOR))
    other = account(Role.ADMINISTRATOR)
    assert signed_in(other).mfa_device_id is None
    number = _asked(user)
    _sent()

    assert _authorize(number, actor) == AUTHORIZED

    assert (other.email, FINALIZED) in _sent()
