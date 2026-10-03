"""Create the first Administrator account, interactively, at the server.

    python manage.py create_first_administrator

It works once. It asks for an email address, a password (typed twice, not
shown), and a typed confirmation. It then shows the key of the account's second
factor, once, and asks for a code from the authenticator application that was
given it. The account is created only when that code is right, so the first
Administrator never exists without a verified second factor (ADR-0014).

It takes no option that carries a credential, reads none from the environment,
and refuses to run unless a person is at a terminal: the key is written to
that terminal and nowhere else.
"""

import getpass
import os
import pwd
import sys
from typing import Any

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from caipo.accounts import selectors, services
from caipo.accounts.services import FirstAdministratorExistsError, SecondFactorCodeError

CONFIRMATION = "create first administrator"
# How many codes may be typed before the command gives up, having created
# nothing. A mistyped code is expected; guessing is not possible here, because
# no account exists for a guess to open.
CODE_ATTEMPTS = 3


def _operator() -> str:
    """Return the operating-system account running the command.

    Taken from the process's user identifier, not from USER or LOGNAME, which
    the caller could set to anything.
    """
    uid = os.getuid()
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return f"uid {uid}"


class Command(BaseCommand):
    help = "Create the first Administrator account. Interactive; works once."

    # There are deliberately no arguments. In particular there is no --email,
    # --password, or --noinput: a credential on a command line is visible to
    # other processes and is kept in shell history.

    def handle(self, *args: Any, **options: Any) -> None:
        if selectors.an_administrator_was_ever_created():
            raise CommandError("An Administrator has already been created. Nothing was done.")
        if not sys.stdin.isatty() or not self.stdout.isatty():
            raise CommandError(
                "This command must be run by a person at a terminal. It does not read"
                " credentials from a pipe, a file, or the environment, and it does not"
                " write the second-factor key anywhere but to a terminal."
            )

        email = input("Email address of the first Administrator: ").strip()
        password = getpass.getpass("Password (not shown): ")
        if getpass.getpass("Password again: ") != password:
            raise CommandError("The two passwords are not the same. Nothing was done.")

        self.stdout.write(
            "\nThis creates an active account with the Administrator role."
            f"\nTo proceed, type: {CONFIRMATION}"
        )
        if input("> ").strip() != CONFIRMATION:
            raise CommandError("Not confirmed. Nothing was done.")

        try:
            enrollment = services.prepare_first_administrator(email=email, password=password)
            self.stdout.write(
                "\nAdd this key to an authenticator application now. It is shown only here"
                " and cannot be shown again."
                f"\nKey: {enrollment.provisioning.secret}"
                f"\nOr use this address in the application: {enrollment.provisioning.uri}"
                "\nNothing has been created yet. The account is created when a code from"
                " the application is accepted."
            )
            user = None
            for _attempt in range(CODE_ATTEMPTS):
                code = input("Current six-digit code: ").strip()
                try:
                    user = services.create_first_administrator(
                        email=email,
                        password=password,
                        operator=_operator(),
                        enrollment=enrollment,
                        code=code,
                    )
                except SecondFactorCodeError:
                    self.stdout.write("That code was not accepted.")
                    continue
                break
        except FirstAdministratorExistsError as error:
            raise CommandError(
                "An Administrator has already been created. Nothing was done."
            ) from error
        except ValidationError as error:
            # Validator messages describe the rule that failed; none of them
            # repeats the password.
            raise CommandError(
                "Refused. Nothing was done.\n"
                + "\n".join(f"- {message}" for message in error.messages)
            ) from error
        if user is None:
            raise CommandError(
                "No code was accepted. Nothing was done: no account exists, and the key"
                " shown above is void. Run the command again."
            )

        self.stdout.write(
            self.style.SUCCESS(f"Created the first Administrator: {user.email}")
            + "\nIts second factor is the authenticator that was just verified. Sign in"
            " with the password and a code from it."
        )
