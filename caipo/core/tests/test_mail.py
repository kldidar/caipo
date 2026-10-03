"""The email boundary: one way out, and no message sent unless a service is configured."""

import inspect
import smtplib
from collections.abc import Sequence
from pathlib import Path

import pytest
from django.conf import LazySettings
from django.core import mail as django_mail
from django.core.mail import EmailMessage
from django.core.mail.backends.base import BaseEmailBackend

import caipo
from caipo.core import mail

TO = "test.recipient@caipo.test"
SUBJECT = "TEST subject"
BODY = "TEST body with a link https://caipo.test/activate/#TEST-token\n"


def _deliver() -> None:
    mail.deliver(to=TO, subject=SUBJECT, body=BODY)


def test_a_message_is_handed_to_the_configured_backend_as_plain_text(
    settings: LazySettings,
) -> None:
    _deliver()

    (message,) = django_mail.outbox
    assert message.to == [TO]
    assert (message.cc, message.bcc, message.attachments) == ([], [], [])
    assert message.subject == SUBJECT
    assert message.body == BODY
    assert message.content_subtype == "plain"
    assert message.from_email == settings.DEFAULT_FROM_EMAIL


def test_delivery_in_tests_is_deterministic_and_goes_nowhere(settings: LazySettings) -> None:
    assert settings.EMAIL_BACKEND == "django.core.mail.backends.locmem.EmailBackend"

    for _ in range(3):
        _deliver()

    assert [(m.to, m.subject, m.body) for m in django_mail.outbox] == [([TO], SUBJECT, BODY)] * 3


def test_the_refusing_backend_refuses_every_message(settings: LazySettings) -> None:
    # That it is the default of every environment that names no other is
    # checked with the settings, in tests/test_settings.py.
    settings.EMAIL_BACKEND = "caipo.core.mail.RefusingEmailBackend"

    with pytest.raises(mail.DeliveryError) as error:
        _deliver()

    assert isinstance(error.value.__cause__, mail.DeliveryNotConfiguredError)
    assert django_mail.outbox == []


def test_the_development_backend_writes_the_message_to_a_file_and_sends_nothing(
    settings: LazySettings, tmp_path: Path
) -> None:
    settings.EMAIL_BACKEND = "django.core.mail.backends.filebased.EmailBackend"
    settings.EMAIL_FILE_PATH = tmp_path

    _deliver()
    _deliver()

    files = sorted(tmp_path.iterdir())
    assert len(files) == 2
    for file in files:
        text = file.read_text()
        assert f"To: {TO}" in text
        assert f"Subject: {SUBJECT}" in text
        assert "https://caipo.test/activate/#TEST-token" in text
    assert django_mail.outbox == []


class _Failing(BaseEmailBackend):
    error: Exception = OSError("TEST connection refused")

    def send_messages(self, email_messages: Sequence[EmailMessage]) -> int:
        raise self.error


class _SendsNothing(BaseEmailBackend):
    def send_messages(self, email_messages: Sequence[EmailMessage]) -> int:
        return 0


@pytest.mark.parametrize(
    "error",
    [
        OSError("TEST connection refused"),
        TimeoutError("TEST timed out"),
        smtplib.SMTPRecipientsRefused({TO: (550, b"TEST no such user")}),
        smtplib.SMTPAuthenticationError(535, b"TEST bad credentials"),
    ],
    ids=["os", "timeout", "recipient", "authentication"],
)
def test_a_failure_of_the_service_is_one_error_that_carries_nothing_of_the_message(
    settings: LazySettings, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setattr(_Failing, "error", error)
    settings.EMAIL_BACKEND = f"{__name__}._Failing"

    with pytest.raises(mail.DeliveryError) as raised:
        _deliver()

    assert raised.value.__cause__ is error
    for part in (TO, SUBJECT, "TEST-token", "caipo.test"):
        assert part not in str(raised.value)


def test_a_backend_that_reports_sending_nothing_is_an_error(settings: LazySettings) -> None:
    settings.EMAIL_BACKEND = f"{__name__}._SendsNothing"

    with pytest.raises(mail.DeliveryError):
        _deliver()


def test_a_defect_in_a_backend_is_not_disguised_as_a_delivery_failure(
    settings: LazySettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_Failing, "error", TypeError("TEST defect"))
    settings.EMAIL_BACKEND = f"{__name__}._Failing"

    with pytest.raises(TypeError):
        _deliver()


def test_the_boundary_logs_nothing_and_knows_nothing_of_accounts() -> None:
    source = inspect.getsource(mail)

    assert "logging" not in source
    assert "caipo.accounts" not in source
    assert "User" not in source


def test_nothing_else_in_the_application_sends_mail_or_names_a_provider() -> None:
    package_root = Path(inspect.getfile(caipo)).parent
    senders = sorted(
        str(path.relative_to(package_root))
        for path in package_root.rglob("*.py")
        if "tests" not in path.parts
        and any(word in path.read_text() for word in ("django.core.mail", "smtplib", "send_mail"))
    )

    # The boundary, and the two settings modules that name a Django backend for it.
    assert senders == [
        "config/settings/development.py",
        "config/settings/testing.py",
        "core/mail.py",
    ]
    callers = sorted(
        str(path.relative_to(package_root))
        for path in package_root.rglob("*.py")
        if "tests" not in path.parts and "mail.deliver(" in path.read_text()
    )
    assert callers == ["accounts/services.py"]
