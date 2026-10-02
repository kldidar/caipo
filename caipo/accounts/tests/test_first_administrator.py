"""Creating the first Administrator: the service, and the command an operator runs."""

import builtins
import getpass
import inspect
import io
import logging
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command, load_command_class
from django.core.management.base import CommandError
from django.db import IntegrityError

import caipo
from caipo.accounts import mfa, selectors, services
from caipo.accounts.management.commands import create_first_administrator as command_module
from caipo.accounts.models import RoleEvent, RoleEventType, User
from caipo.accounts.selectors import Permission, Role
from caipo.accounts.services import FirstAdministratorExistsError, SignInOutcome
from caipo.accounts.tests.fixtures import UserFactory

pytestmark = [pytest.mark.services, pytest.mark.django_db]

# Visibly synthetic fixture values.
EMAIL = "test.administrator@caipo.test"
PASSWORD = "TEST-correct-horse-battery-staple"
OPERATOR = "TEST-operator"
COMMAND = "create_first_administrator"
CONFIRMATION = command_module.CONFIRMATION


def _create(email: str = EMAIL, password: str = PASSWORD) -> User:
    return services.create_first_administrator(email=email, password=password, operator=OPERATOR)


# --- The service ---------------------------------------------------------------


def test_the_first_administrator_is_created_active_with_the_role() -> None:
    user = _create()

    stored = User.objects.get()
    assert stored == user
    assert stored.email == EMAIL
    assert stored.is_active is True
    assert selectors.roles_of(stored) == {Role.ADMINISTRATOR}


def test_the_grant_is_a_role_event_without_an_actor_that_says_who_ran_it() -> None:
    user = _create()

    event = RoleEvent.objects.get()
    assert (event.user, event.role, event.event_type) == (user, "administrator", "granted")
    assert event.actor is None
    assert "create_first_administrator" in event.reason
    assert OPERATOR in event.reason
    assert PASSWORD not in event.reason


def test_the_password_is_hashed_and_signs_the_account_in() -> None:
    user = _create()

    assert user.password.startswith("argon2$")
    assert PASSWORD not in user.password
    result = services.sign_in(email=EMAIL, password=PASSWORD, source="203.0.113.10")
    assert result.outcome == SignInOutcome.SIGNED_IN


def test_the_role_grants_nothing_until_a_second_factor_exists() -> None:
    # Bootstrapping makes no exception to ADR-0007 rule 4.
    assert selectors.permissions_of(_create()) == frozenset()


def test_the_email_is_normalized() -> None:
    assert _create(email="  Test.Administrator@CAIPO.Test ").email == EMAIL


def test_a_second_bootstrap_is_refused() -> None:
    _create()

    with pytest.raises(FirstAdministratorExistsError):
        _create(email="test.second@caipo.test")

    assert User.objects.count() == 1
    assert RoleEvent.objects.count() == 1


def test_bootstrap_is_refused_when_an_administrator_was_granted_by_other_means(
    user_with_roles: UserFactory,
) -> None:
    user_with_roles(Role.ADMINISTRATOR)

    with pytest.raises(FirstAdministratorExistsError):
        _create()

    assert not User.objects.filter(email=EMAIL).exists()


@pytest.mark.usefixtures("mfa_enrolled")
def test_bootstrap_stays_closed_after_the_first_administrator_loses_the_role(
    user_with_roles: UserFactory,
) -> None:
    first = _create()
    second = user_with_roles(Role.ADMINISTRATOR)
    services.revoke_role(
        actor=second, user=first, role=Role.ADMINISTRATOR, reason="TEST revocation"
    )

    with pytest.raises(FirstAdministratorExistsError):
        _create(email="test.again@caipo.test")


@pytest.mark.parametrize(
    "password",
    ["short", "12345678901234", "password", "test.administrator"],
    ids=["too-short", "all-digits", "common", "like-the-email"],
)
def test_a_password_that_fails_validation_is_refused(password: str) -> None:
    with pytest.raises(ValidationError):
        _create(password=password)

    assert not User.objects.exists()
    assert not RoleEvent.objects.exists()


@pytest.mark.parametrize("email", ["", "not-an-email", "test@", "@caipo.test"])
def test_an_invalid_email_is_refused(email: str) -> None:
    with pytest.raises(ValidationError):
        _create(email=email)

    assert not User.objects.exists()


def test_an_email_that_already_has_an_account_is_refused(user_with_roles: UserFactory) -> None:
    existing = user_with_roles()

    with pytest.raises(ValidationError):
        _create(email=existing.email)

    assert selectors.roles_of(existing) == frozenset()
    assert not RoleEvent.objects.exists()


def test_a_failure_part_way_leaves_no_account_behind(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(**kwargs: object) -> None:
        raise RuntimeError("TEST failure while recording the grant")

    # Fault injection: the role event cannot be written.
    monkeypatch.setattr(RoleEvent.objects, "create", fail)

    with pytest.raises(RuntimeError):
        _create()

    assert not User.objects.exists()
    assert not RoleEvent.objects.exists()


def test_creation_is_logged_without_email_or_password(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="caipo.accounts.services"):
        user = _create()

    (record,) = caplog.records
    assert record.__dict__["event"] == "accounts.first_administrator_created"
    assert record.__dict__["user_id"] == user.pk
    logged = f"{record.getMessage()} {record.__dict__}"
    assert PASSWORD not in logged
    assert EMAIL not in logged


def test_normal_role_changes_still_need_an_acting_administrator(
    user_with_roles: UserFactory,
) -> None:
    # The bootstrap is the only path without an actor; grant_role has none.
    first = _create()
    other = user_with_roles()

    with pytest.raises(PermissionDenied):
        services.grant_role(actor=first, user=other, role=Role.READER, reason="TEST attempt")

    assert RoleEvent.objects.filter(event_type=RoleEventType.GRANTED).count() == 1


def test_the_first_administrator_can_sign_in_and_holds_no_administrative_privilege(
    terminal: Terminal, user_with_roles: UserFactory
) -> None:
    """ADR-0007 rule 4 and ADR-0013 point 27, end to end, with nothing standing in for TOTP."""
    # The application as it really runs: the enrolment lookup has not been replaced.
    assert mfa.is_enrolled.__module__ == "caipo.accounts.mfa"
    assert Path(inspect.getfile(mfa.is_enrolled)).name == "mfa.py"
    terminal.will_type(lines=[EMAIL, CONFIRMATION], secrets=[PASSWORD, PASSWORD])

    # 1. The first Administrator can be created.
    _run()
    administrator = User.objects.get(email=EMAIL)

    # 2. The account can authenticate.
    result = services.sign_in(email=EMAIL, password=PASSWORD, source="203.0.113.10")
    assert result.outcome == SignInOutcome.SIGNED_IN
    assert result.user == administrator

    # 3. The Administrator role is present.
    assert selectors.roles_of(administrator) == {Role.ADMINISTRATOR}

    # 4. Without an enrolled second factor, nothing the role confers is available.
    assert mfa.is_enrolled(administrator) is False
    assert selectors.permissions_of(administrator) == frozenset()
    for permission in Permission:
        assert selectors.can(administrator, permission) is False
        with pytest.raises(PermissionDenied):
            selectors.require_permission(administrator, permission)

    other = user_with_roles(Role.READER)
    with pytest.raises(PermissionDenied):
        services.grant_role(actor=administrator, user=other, role=Role.RESEARCHER, reason="TEST")
    with pytest.raises(PermissionDenied):
        services.revoke_role(actor=administrator, user=other, role=Role.READER, reason="TEST")
    with pytest.raises(PermissionDenied):
        services.deactivate_user(actor=administrator, user=other)

    assert selectors.roles_of(other) == {Role.READER}
    assert User.objects.get(pk=other.pk).is_active is True
    assert RoleEvent.objects.filter(actor=administrator).count() == 0


# --- The bootstrap is the only way to an event without an actor ----------------


@pytest.mark.usefixtures("mfa_enrolled")
@pytest.mark.parametrize("operation", [services.grant_role, services.revoke_role])
@pytest.mark.parametrize("role", list(Role))
def test_the_role_services_refuse_a_change_that_names_no_actor(
    user_with_roles: UserFactory, operation: Callable[..., RoleEvent], role: Role
) -> None:
    user_with_roles(Role.ADMINISTRATOR)
    target = user_with_roles(Role.READER)
    events_before = RoleEvent.objects.count()

    with pytest.raises(PermissionDenied):
        operation(actor=None, user=target, role=role, reason="TEST attempt without an actor")

    assert RoleEvent.objects.count() == events_before
    assert not RoleEvent.objects.filter(actor__isnull=True).exists()


def test_only_the_command_calls_the_bootstrap_operation() -> None:
    package_root = Path(inspect.getfile(caipo)).parent
    callers = sorted(
        str(path.relative_to(package_root))
        for path in package_root.rglob("*.py")
        if "tests" not in path.parts and "create_first_administrator" in path.read_text()
    )

    assert callers == [
        "accounts/management/commands/create_first_administrator.py",
        # Where it is defined.
        "accounts/services.py",
    ]


def test_only_the_bootstrap_operation_writes_an_event_without_an_actor() -> None:
    package_root = Path(inspect.getfile(caipo)).parent
    writers = sorted(
        str(path.relative_to(package_root))
        for path in package_root.rglob("*.py")
        if "tests" not in path.parts
        and "migrations" not in path.parts
        and "actor=None" in path.read_text()
    )

    assert writers == ["accounts/services.py"]
    assert inspect.getsource(services).count("actor=None") == 1
    assert "actor=None" in inspect.getsource(services.create_first_administrator)


def test_a_second_actor_less_event_is_refused_by_the_database_even_for_the_bootstrap_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create()
    # Suppose the application's own check were bypassed or wrong.
    monkeypatch.setattr(selectors, "an_administrator_was_ever_created", lambda: False)

    with pytest.raises(IntegrityError, match="accounts_roleevent_single_bootstrap"):
        _create(email="test.second@caipo.test")

    assert User.objects.count() == 1
    assert RoleEvent.objects.filter(actor__isnull=True).count() == 1


# --- The command ---------------------------------------------------------------


class Terminal:
    """Stands in for the person at the keyboard, and records what was asked."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, interactive: bool = True) -> None:
        self.lines: Iterator[str] = iter(())
        self.secrets: Iterator[str] = iter(())
        self.prompts: list[str] = []
        monkeypatch.setattr(builtins, "input", self._input)
        monkeypatch.setattr(getpass, "getpass", self._getpass)
        monkeypatch.setattr(sys.stdin, "isatty", lambda: interactive, raising=False)

    def will_type(self, *, lines: list[str], secrets: list[str]) -> None:
        self.lines, self.secrets = iter(lines), iter(secrets)

    def _input(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        return next(self.lines)

    def _getpass(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        return next(self.secrets)


@pytest.fixture
def terminal(monkeypatch: pytest.MonkeyPatch) -> Terminal:
    return Terminal(monkeypatch)


def _run() -> str:
    out, err = io.StringIO(), io.StringIO()
    call_command(COMMAND, stdout=out, stderr=err)
    return out.getvalue() + err.getvalue()


def test_the_command_creates_the_first_administrator(terminal: Terminal) -> None:
    terminal.will_type(lines=[EMAIL, CONFIRMATION], secrets=[PASSWORD, PASSWORD])

    output = _run()

    user = User.objects.get()
    assert user.email == EMAIL
    assert user.is_active is True
    assert user.check_password(PASSWORD)
    assert selectors.roles_of(user) == {Role.ADMINISTRATOR}
    assert RoleEvent.objects.get().actor is None
    assert EMAIL in output
    assert "second factor" in output


def test_the_password_never_appears_in_output_prompts_or_logs(
    terminal: Terminal, caplog: pytest.LogCaptureFixture
) -> None:
    terminal.will_type(lines=[EMAIL, CONFIRMATION], secrets=[PASSWORD, PASSWORD])

    with caplog.at_level(logging.DEBUG):
        output = _run()

    logged = " ".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
    assert PASSWORD not in output
    assert PASSWORD not in " ".join(terminal.prompts)
    assert PASSWORD not in logged


def test_the_password_is_asked_for_with_hidden_input_twice(terminal: Terminal) -> None:
    terminal.will_type(lines=[EMAIL, CONFIRMATION], secrets=[PASSWORD, PASSWORD])

    _run()

    # Both secrets were consumed through getpass, and nothing else was.
    assert list(terminal.secrets) == []
    assert list(terminal.lines) == []
    assert [prompt for prompt in terminal.prompts if "assword" in prompt] == [
        "Password (not shown): ",
        "Password again: ",
    ]


def test_the_command_refuses_a_second_bootstrap_before_asking_anything(
    terminal: Terminal,
) -> None:
    _create()

    with pytest.raises(CommandError, match="already been created"):
        _run()

    assert terminal.prompts == []
    assert User.objects.count() == 1


@pytest.mark.parametrize("typed", ["", "yes", "y", "CREATE FIRST ADMINISTRATOR", "create"])
def test_the_command_requires_the_confirmation_to_be_typed_out(
    terminal: Terminal, typed: str
) -> None:
    terminal.will_type(lines=[EMAIL, typed], secrets=[PASSWORD, PASSWORD])

    with pytest.raises(CommandError, match="Not confirmed"):
        _run()

    assert not User.objects.exists()
    assert not RoleEvent.objects.exists()


def test_the_command_refuses_passwords_that_differ(terminal: Terminal) -> None:
    terminal.will_type(lines=[EMAIL, CONFIRMATION], secrets=[PASSWORD, PASSWORD + "x"])

    with pytest.raises(CommandError, match="not the same") as error:
        _run()

    assert PASSWORD not in str(error.value)
    assert not User.objects.exists()


def test_the_command_refuses_a_weak_password_without_repeating_it(terminal: Terminal) -> None:
    weak = "12345678901234"
    terminal.will_type(lines=[EMAIL, CONFIRMATION], secrets=[weak, weak])

    with pytest.raises(CommandError, match="entirely numeric") as error:
        _run()

    assert weak not in str(error.value)
    assert not User.objects.exists()


def test_the_command_refuses_to_run_without_a_person_at_a_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal = Terminal(monkeypatch, interactive=False)
    terminal.will_type(lines=[EMAIL, CONFIRMATION], secrets=[PASSWORD, PASSWORD])

    with pytest.raises(CommandError, match="at a terminal"):
        _run()

    assert terminal.prompts == []
    assert not User.objects.exists()


ENVIRONMENT_NAMES = [
    "DJANGO_SUPERUSER_PASSWORD",
    "DJANGO_SUPERUSER_EMAIL",
    "CAIPO_ADMIN_PASSWORD",
    "CAIPO_ADMIN_EMAIL",
    "CAIPO_ADMINISTRATOR_PASSWORD",
    "CAIPO_ADMINISTRATOR_EMAIL",
    "ADMIN_PASSWORD",
    "ADMIN_EMAIL",
    "CAIPO_BOOTSTRAP_ADMINISTRATOR",
    "CAIPO_CREATE_FIRST_ADMINISTRATOR",
]


def test_no_environment_variable_supplies_credentials_or_skips_the_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ENVIRONMENT_NAMES:
        monkeypatch.setenv(name, "TEST-from-the-environment@caipo.test")
    terminal = Terminal(monkeypatch, interactive=False)

    with pytest.raises(CommandError, match="at a terminal"):
        _run()

    assert not User.objects.exists()
    assert terminal.prompts == []


def test_environment_variables_are_ignored_when_a_person_is_present(
    terminal: Terminal, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ENVIRONMENT_NAMES:
        monkeypatch.setenv(name, "TEST-from-the-environment@caipo.test")
    terminal.will_type(lines=[EMAIL, CONFIRMATION], secrets=[PASSWORD, PASSWORD])

    _run()

    user = User.objects.get()
    assert user.email == EMAIL
    assert user.check_password(PASSWORD)
    assert not user.check_password("TEST-from-the-environment@caipo.test")


def test_the_operator_is_taken_from_the_process_not_from_the_environment(
    terminal: Terminal, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("USER", "LOGNAME", "USERNAME", "LNAME"):
        monkeypatch.setenv(name, "TEST-spoofed-operator")
    terminal.will_type(lines=[EMAIL, CONFIRMATION], secrets=[PASSWORD, PASSWORD])

    _run()

    assert "TEST-spoofed-operator" not in RoleEvent.objects.get().reason


@pytest.mark.parametrize(
    "arguments",
    [
        ["--password", PASSWORD],
        ["--email", EMAIL],
        ["--noinput"],
        ["--no-input"],
        [EMAIL],
        [EMAIL, PASSWORD],
    ],
)
def test_the_command_accepts_no_credential_or_non_interactive_argument(
    terminal: Terminal, arguments: list[str]
) -> None:
    terminal.will_type(lines=[EMAIL, CONFIRMATION], secrets=[PASSWORD, PASSWORD])

    with pytest.raises((CommandError, TypeError)):
        call_command(COMMAND, *arguments, stdout=io.StringIO(), stderr=io.StringIO())

    assert not User.objects.exists()
    assert terminal.prompts == []


def test_the_command_defines_no_options_of_its_own() -> None:
    command = load_command_class("caipo.accounts", COMMAND)
    parser = command.create_parser("manage.py", COMMAND)
    options = {option for action in parser._actions for option in action.option_strings}

    standard = {
        "-h",
        "--help",
        "--version",
        "-v",
        "--verbosity",
        "--settings",
        "--pythonpath",
        "--traceback",
        "--no-color",
        "--force-color",
        "--skip-checks",
    }
    assert options == standard
