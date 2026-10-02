"""Create the first Administrator account, interactively, at the server.

    python manage.py create_first_administrator

It works once. It asks for an email address, a password (typed twice, not
shown), and a typed confirmation. It takes no option that carries a
credential, reads none from the environment, and refuses to run unless a
person is at a terminal.
"""

import getpass
import os
import pwd
import sys
from typing import Any

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from caipo.accounts import selectors, services
from caipo.accounts.services import FirstAdministratorExistsError

CONFIRMATION = "create first administrator"


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
        if not sys.stdin.isatty():
            raise CommandError(
                "This command must be run by a person at a terminal. It does not read"
                " credentials from a pipe, a file, or the environment."
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
            user = services.create_first_administrator(
                email=email, password=password, operator=_operator()
            )
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

        self.stdout.write(
            self.style.SUCCESS(f"Created the first Administrator: {user.email}")
            + "\nThe Administrator role grants nothing until the account has enrolled a"
            " second factor, and enrolment is not implemented yet. The account can sign"
            " in; it cannot yet manage roles or accounts."
        )
