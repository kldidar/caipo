"""Recover an Administrator's lost second factor, interactively, at the server.

    python manage.py recover_mfa_break_glass

For one case only (ADR-0017 points 59 to 70): an Administrator who lost the
second factor, when the other Administrators that the application's own
recovery needs do not exist. It asks for three things and nothing else: the
email address of the account, a request number, and a phrase typed out as
confirmation. The phrase says which of its two actions is meant:

- revoking the lost device named by the account's recovery request, in place
  of an Administrator's authorisation;
- approving the enrolment request that follows that recovery, in place of an
  Administrator's approval.

It sets no password, creates no device, makes no device active, and signs
nobody in: the account still enrols in the application and gives its first
code there. It asks for no password, code, secret, or token, and shows none.

It takes no option, has no non-interactive mode, reads nothing from the
environment, and refuses to run unless a person is at a terminal. Who ran it
is not recorded by the application: that belongs to the operational audit
trail of the server (ADR-0017 point 68).
"""

import sys
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from caipo.accounts import services
from caipo.accounts.services import BreakGlassOutcome
from caipo.core.correlation import correlation_scope

# The two phrases are fixed here. Which one is typed is the whole of how the
# action is chosen: nothing is inferred from the state of the account.
REVOKE_CONFIRMATION = "revoke lost second factor"
APPROVE_CONFIRMATION = "approve enrolment after recovery"

# A request number is an identifier the database issued: digits, and no more
# of them than such an identifier has.
NUMBER_DIGITS = 18

REFUSED = (
    "Refused. Nothing was changed. The account, the number, and the action do not"
    " name something this command may do now."
)


class Command(BaseCommand):
    help = "Recover an Administrator's lost second factor by break-glass. Interactive."

    # There are deliberately no arguments. In particular there is no option
    # for the account, the number, or the action, and no --noinput: the
    # command is run by a person who types each of the three.

    def handle(self, *args: Any, **options: Any) -> None:
        if not sys.stdin.isatty() or not self.stdout.isatty():
            raise CommandError(
                "This command must be run by a person at a terminal. It does not read"
                " its input from a pipe, a file, or the environment."
            )
        # One identifier ties the event to the log lines of this run.
        with correlation_scope():
            self._run()

    def _run(self) -> None:
        email = input("Email address of the Administrator account: ").strip()
        number = input("Request number: ").strip()
        self.stdout.write(
            "\nThis command sets no password and creates no second factor."
            "\nTo revoke the lost second factor that the recovery request with this"
            f" number names, type: {REVOKE_CONFIRMATION}"
            "\nTo approve the enrolment request with this number, made after a"
            f" recovery, type: {APPROVE_CONFIRMATION}"
        )
        # Compared as it was typed. What was typed is never written back or
        # logged, at this prompt or at the two before it: people type
        # passwords where something else was asked for.
        confirmation = input("> ")
        if confirmation not in (REVOKE_CONFIRMATION, APPROVE_CONFIRMATION):
            raise CommandError("Not confirmed. Nothing was done.")
        if not (number.isascii() and number.isdigit() and len(number) <= NUMBER_DIGITS):
            raise CommandError("That is not a request number. Nothing was done.")

        if confirmation == REVOKE_CONFIRMATION:
            result = services.break_glass_revoke_device(email=email, request_number=int(number))
            done = (
                "The lost second factor was revoked and the sessions of the account were"
                " ended. Nobody was signed in. The account signs in with its password and"
                " asks for a new enrolment."
            )
        else:
            result = services.break_glass_approve_enrollment(
                email=email, request_number=int(number)
            )
            done = (
                "The enrolment request was approved. Nothing is active yet: the account"
                " signs in with its password and gives the first code of the new second"
                " factor in the application."
            )
        if result.outcome != BreakGlassOutcome.DONE:
            raise CommandError(REFUSED)
        # Written only now: the service has returned, so its transaction has
        # committed.
        self.stdout.write(self.style.SUCCESS(done))
