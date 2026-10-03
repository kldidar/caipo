"""The boundary through which the application sends email (ADR-0015).

Callers hand over a recipient, a subject, and a plain-text body, and learn
whether the message was handed on. Which service carries it is configuration:
Django's EMAIL_BACKEND setting names the implementation, so no caller knows a
provider and none is chosen here. Nothing in this module knows what a message
is for.

No provider is configured for production. Until the deployment decision
(ADR-0008) names one, the default backend below refuses every message, so
that nothing is sent by accident and a caller is told that nothing was sent.
"""

import smtplib
from collections.abc import Sequence

from django.core.mail import EmailMessage
from django.core.mail.backends.base import BaseEmailBackend


class DeliveryError(Exception):
    """A message could not be handed on for delivery. Carries no part of the message."""


class DeliveryNotConfiguredError(OSError):
    """No email service is configured in this environment."""


class RefusingEmailBackend(BaseEmailBackend):
    """Sends nothing and says so. The default until a delivery service is configured."""

    def send_messages(self, email_messages: Sequence[EmailMessage]) -> int:
        raise DeliveryNotConfiguredError("No email delivery service is configured.")


def deliver(*, to: str, subject: str, body: str) -> None:
    """Hand one plain-text message to the configured email backend.

    The sender is DEFAULT_FROM_EMAIL. Nothing is logged here: a caller decides
    what may be said about a message, and the body may hold a link that must
    not be logged.

    Raises DeliveryError if the backend refuses the message, cannot reach its
    service, or reports that it sent nothing. The cause is chained; the
    message is not part of the error.
    """
    message = EmailMessage(subject=subject, body=body, to=[to])
    try:
        sent = message.send()
    except (OSError, smtplib.SMTPException) as error:
        raise DeliveryError("The message could not be handed on for delivery.") from error
    if sent != 1:
        raise DeliveryError("The message was not accepted for delivery.")
