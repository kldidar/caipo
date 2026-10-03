"""Creating the first Administrator: the service, and the command an operator runs."""

import base64
import builtins
import getpass
import inspect
import io
import logging
import re
import sys
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command, load_command_class
from django.core.management.base import CommandError
from django.db import IntegrityError

import caipo
from caipo.accounts import models, selectors, services, totp
from caipo.accounts.management.commands import create_first_administrator as command_module
from caipo.accounts.models import (
    AuthenticationEvent,
    AuthenticationEventType,
    RoleEvent,
    RoleEventType,
    TotpDevice,
    TotpDeviceState,
    User,
)
from caipo.accounts.selectors import Permission, Role
from caipo.accounts.services import (
    FirstAdministratorExistsError,
    MfaOutcome,
    SecondFactorCodeError,
    SignInOutcome,
)
from caipo.accounts.tests.fixtures import (
    Clock,
    UserFactory,
    code_at,
    logged,
    signed_in,
    verified,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db]

# Visibly synthetic fixture values.
EMAIL = "test.administrator@caipo.test"
PASSWORD = "TEST-correct-horse-battery-staple"
OPERATOR = "TEST-operator"
COMMAND = "create_first_administrator"
CONFIRMATION = command_module.CONFIRMATION


SOURCE = "203.0.113.10"
WRONG_CODE = "000000"


def _create(email: str = EMAIL, password: str = PASSWORD, code: str | None = None) -> User:
    """Run both steps of the bootstrap, by default with the right code for the issued secret."""
    enrollment = services.prepare_first_administrator(email=email, password=password)
    return services.create_first_administrator(
        email=email,
        password=password,
        operator=OPERATOR,
        enrollment=enrollment,
        code=code_at(secret=enrollment.secret) if code is None else code,
    )


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


def test_the_password_is_hashed_and_alone_signs_nobody_in() -> None:
    user = _create()

    assert user.password.startswith("argon2$")
    assert PASSWORD not in user.password
    result = services.sign_in(email=EMAIL, password=PASSWORD, source=SOURCE)
    assert result.outcome == SignInOutcome.SECOND_FACTOR_REQUIRED
    assert result.user is None


def test_the_role_grants_only_enrolment_until_a_second_factor_is_verified() -> None:
    # Bootstrapping makes no exception to ADR-0007 rule 4: a context that
    # shows the password alone holds nothing administrative.
    assert selectors.permissions_of(signed_in(_create())) == {Permission.MFA_MANAGE_OWN}


def test_the_first_administrator_is_created_with_an_active_trusted_second_factor() -> None:
    user = _create()

    device = TotpDevice.objects.get()
    assert device.user == user
    assert device.state == TotpDeviceState.ACTIVE
    assert device.confirmed_at is not None
    # Trusted by the bootstrap itself: nobody exists who could have approved it.
    assert device.approved_at is not None
    assert device.approved_by is None
    assert selectors.mfa_state_of(user) == selectors.MfaState.ACTIVE
    event = AuthenticationEvent.objects.get()
    assert event.event_type == AuthenticationEventType.MFA_ENROLLMENT_SUCCEEDED
    assert (event.user, event.actor) == (user, None)
    assert "second factor" in RoleEvent.objects.get().reason


@pytest.mark.parametrize("code", [WRONG_CODE, "", "12345", "1234567", "abcdef"])
def test_without_a_right_code_nothing_at_all_is_created(code: str) -> None:
    with pytest.raises(SecondFactorCodeError):
        _create(code=code)

    assert not User.objects.exists()
    assert not RoleEvent.objects.exists()
    assert not TotpDevice.objects.exists()
    assert not AuthenticationEvent.objects.exists()
    # The bootstrap is still open: nothing happened.
    assert selectors.an_administrator_was_ever_created() is False


def test_a_code_for_another_secret_does_not_create_the_administrator() -> None:
    enrollment = services.prepare_first_administrator(email=EMAIL, password=PASSWORD)
    other = services.prepare_first_administrator(email=EMAIL, password=PASSWORD)
    assert other.secret != enrollment.secret

    with pytest.raises(SecondFactorCodeError):
        services.create_first_administrator(
            email=EMAIL,
            password=PASSWORD,
            operator=OPERATOR,
            enrollment=enrollment,
            code=code_at(secret=other.secret),
        )

    assert not User.objects.exists()


def test_preparing_writes_nothing_and_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        enrollment = services.prepare_first_administrator(email=EMAIL, password=PASSWORD)

    assert not User.objects.exists()
    assert not TotpDevice.objects.exists()
    assert not AuthenticationEvent.objects.exists()
    assert [record for record in caplog.records if record.name.startswith("caipo")] == []
    assert enrollment.provisioning.secret not in repr(enrollment)
    assert str(enrollment.secret) not in repr(enrollment)


def test_preparing_refuses_what_creating_would_refuse(user_with_roles: UserFactory) -> None:
    with pytest.raises(ValidationError):
        services.prepare_first_administrator(email=EMAIL, password="12345678901234")
    with pytest.raises(ValidationError):
        services.prepare_first_administrator(email="not-an-email", password=PASSWORD)

    user_with_roles(Role.ADMINISTRATOR)
    with pytest.raises(FirstAdministratorExistsError):
        services.prepare_first_administrator(email=EMAIL, password=PASSWORD)


def test_the_code_that_created_the_administrator_cannot_be_used_again() -> None:
    _create()
    challenge = services.sign_in(email=EMAIL, password=PASSWORD, source=SOURCE).challenge
    assert challenge is not None
    secret = _stored_secret()

    result = services.verify_second_factor(
        challenge=challenge, code=code_at(secret=secret), source=SOURCE
    )

    assert result.outcome == MfaOutcome.REFUSED


def test_the_secret_and_code_reach_no_log_event_or_role_record(
    caplog: pytest.LogCaptureFixture,
) -> None:
    enrollment = services.prepare_first_administrator(email=EMAIL, password=PASSWORD)
    code = code_at(secret=enrollment.secret)

    with caplog.at_level(logging.DEBUG):
        services.create_first_administrator(
            email=EMAIL, password=PASSWORD, operator=OPERATOR, enrollment=enrollment, code=code
        )

    stored = " ".join(
        [
            RoleEvent.objects.get().reason,
            *(str(value) for value in AuthenticationEvent.objects.values_list().get()),
            logged(caplog.records),
        ]
    )
    for forbidden in (enrollment.provisioning.secret, enrollment.provisioning.uri, PASSWORD):
        assert forbidden not in stored
    assert enrollment.secret not in bytes(TotpDevice.objects.get().secret_ciphertext)


def _stored_secret() -> bytes:
    device = TotpDevice.objects.get()
    return totp.decrypt_secret(
        bytes(device.secret_ciphertext), device.key_id, user_id=device.user_id
    )


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


def test_bootstrap_stays_closed_after_the_first_administrator_loses_the_role(
    user_with_roles: UserFactory,
) -> None:
    first = _create()
    second = user_with_roles(Role.ADMINISTRATOR)
    services.revoke_role(
        actor=verified(second), user=first, role=Role.ADMINISTRATOR, reason="TEST revocation"
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
        services.grant_role(
            actor=signed_in(first), user=other, role=Role.READER, reason="TEST attempt"
        )

    assert RoleEvent.objects.filter(event_type=RoleEventType.GRANTED).count() == 1


def test_the_first_administrator_needs_the_bootstrap_device_for_every_privilege(
    terminal: Terminal, user_with_roles: UserFactory, clock: Clock
) -> None:
    """ADR-0007 rule 4 and ADR-0014, end to end, with nothing standing in for TOTP."""
    terminal.will_type(lines=[EMAIL, CONFIRMATION], secrets=[PASSWORD, PASSWORD])

    # 1. The first Administrator is created, with the device verified at the terminal.
    _run(terminal)
    administrator = User.objects.get(email=EMAIL)
    assert selectors.roles_of(administrator) == {Role.ADMINISTRATOR}
    assert selectors.mfa_state_of(administrator) == selectors.MfaState.ACTIVE

    # 2. The password alone signs nobody in, and a context that claims no
    #    more than the password holds nothing administrative.
    result = services.sign_in(email=EMAIL, password=PASSWORD, source=SOURCE)
    assert result.outcome == SignInOutcome.SECOND_FACTOR_REQUIRED
    assert result.user is None and result.challenge is not None
    password_only = signed_in(administrator)
    assert selectors.permissions_of(password_only) == {Permission.MFA_MANAGE_OWN}
    other = user_with_roles(Role.READER)
    with pytest.raises(PermissionDenied):
        services.grant_role(actor=password_only, user=other, role=Role.RESEARCHER, reason="TEST")
    with pytest.raises(PermissionDenied):
        services.disable_user(actor=password_only, user=other)

    # 3. Whoever knows the password cannot give the account another device.
    started = services.start_mfa_enrollment(actor=password_only, password=PASSWORD, source=SOURCE)
    assert started.outcome == MfaOutcome.UNAVAILABLE

    # 4. With a code from the authenticator set up at the terminal, the
    #    account is an operational Administrator.
    clock(timedelta(seconds=60))
    verified_result = services.verify_second_factor(
        challenge=result.challenge, code=terminal.code(), source=SOURCE
    )
    assert verified_result.outcome == MfaOutcome.ACCEPTED
    assert verified_result.context is not None
    assert selectors.can(verified_result.context, Permission.ROLES_MANAGE) is True
    services.grant_role(
        actor=verified_result.context, user=other, role=Role.RESEARCHER, reason="TEST"
    )
    assert selectors.roles_of(other) == {Role.READER, Role.RESEARCHER}


# --- The bootstrap is the only way to an event without an actor ----------------


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


def test_only_the_bootstrap_operation_trusts_a_device_that_nobody_approved() -> None:
    """A device is marked approved in two places: the approval, which names the
    approving Administrator, and the bootstrap, which is the one that names nobody."""
    package_root = Path(inspect.getfile(caipo)).parent
    writers = sorted(
        str(path.relative_to(package_root))
        for path in package_root.rglob("*.py")
        if "tests" not in path.parts
        and "migrations" not in path.parts
        and re.search(r"approved_at\s*=[^=]", path.read_text())
    )

    # The model defines the field and sets it nowhere.
    assert writers == ["accounts/models.py", "accounts/services.py"]
    assert len(re.findall(r"approved_at\s*=[^=]", inspect.getsource(models))) == 1
    source = inspect.getsource(services)
    assert len(re.findall(r"approved_at\s*=[^=]", source)) == 2
    assert "approved_at=now" in inspect.getsource(services.create_first_administrator)
    assert "approved_by = actor.user" in inspect.getsource(services._decide_enrollment)


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


class _TerminalOutput(io.StringIO):
    """What the command writes, on something that says it is a terminal or says it is not."""

    def __init__(self, *, interactive: bool) -> None:
        super().__init__()
        self._interactive = interactive

    def isatty(self) -> bool:
        return self._interactive


class Terminal:
    """Stands in for the person at the keyboard, and records what was asked.

    By default the person reads the key off the screen, puts it into an
    authenticator, and types the code it shows. `codes` replaces that with
    what is typed at each request for a code, `RIGHT_CODE` meaning the same.
    """

    RIGHT_CODE = "TEST: the code the authenticator shows"

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        interactive: bool = True,
        output_is_a_terminal: bool = True,
    ) -> None:
        self.lines: Iterator[str] = iter(())
        self.secrets: Iterator[str] = iter(())
        self.codes: Iterator[str] = iter(())
        self.prompts: list[str] = []
        self.out = _TerminalOutput(interactive=output_is_a_terminal)
        monkeypatch.setattr(builtins, "input", self._input)
        monkeypatch.setattr(getpass, "getpass", self._getpass)
        monkeypatch.setattr(sys.stdin, "isatty", lambda: interactive, raising=False)

    def will_type(
        self, *, lines: list[str], secrets: list[str], codes: list[str] | None = None
    ) -> None:
        self.lines, self.secrets = iter(lines), iter(secrets)
        self.codes = iter([self.RIGHT_CODE] if codes is None else codes)

    def key(self) -> str:
        """Return the key as it was shown on the screen."""
        (shown,) = re.findall(r"^Key: (\S+)$", self.out.getvalue(), flags=re.MULTILINE)
        return str(shown)

    def code(self) -> str:
        """Return what an authenticator that was given the key shows now."""
        return code_at(secret=base64.b32decode(self.key()))

    def _input(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        if "code" in prompt:
            typed = next(self.codes)
            return self.code() if typed == self.RIGHT_CODE else typed
        return next(self.lines)

    def _getpass(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        return next(self.secrets)


@pytest.fixture
def terminal(monkeypatch: pytest.MonkeyPatch) -> Terminal:
    return Terminal(monkeypatch)


def _run(terminal: Terminal) -> str:
    err = io.StringIO()
    call_command(COMMAND, stdout=terminal.out, stderr=err)
    return terminal.out.getvalue() + err.getvalue()


def test_the_command_creates_the_first_administrator(terminal: Terminal) -> None:
    terminal.will_type(lines=[EMAIL, CONFIRMATION], secrets=[PASSWORD, PASSWORD])

    output = _run(terminal)

    user = User.objects.get()
    assert user.email == EMAIL
    assert user.is_active is True
    assert user.check_password(PASSWORD)
    assert selectors.roles_of(user) == {Role.ADMINISTRATOR}
    assert RoleEvent.objects.get().actor is None
    assert EMAIL in output
    assert "second factor" in output
    device = TotpDevice.objects.get()
    assert (device.user, device.state) == (user, TotpDeviceState.ACTIVE)
    assert device.approved_at is not None
    assert _stored_secret() == base64.b32decode(terminal.key())


def test_the_command_shows_the_key_once_before_anything_exists(
    terminal: Terminal, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, bool, bool]] = []

    def watch(prompt: str = "") -> str:
        seen.append((prompt, "Key: " in terminal.out.getvalue(), User.objects.exists()))
        return terminal._input(prompt)

    terminal.will_type(lines=[EMAIL, CONFIRMATION], secrets=[PASSWORD, PASSWORD])
    monkeypatch.setattr(builtins, "input", watch)

    output = _run(terminal)

    # When the code was asked for, the key was on the screen and no account existed.
    assert ("Current six-digit code: ", True, False) in seen
    assert output.count(terminal.key()) == 2  # the key, and the address that carries it
    assert "otpauth://totp/" in output


def test_a_mistyped_code_can_be_typed_again(terminal: Terminal) -> None:
    terminal.will_type(
        lines=[EMAIL, CONFIRMATION],
        secrets=[PASSWORD, PASSWORD],
        codes=[WRONG_CODE, Terminal.RIGHT_CODE],
    )

    output = _run(terminal)

    assert "not accepted" in output
    assert selectors.roles_of(User.objects.get()) == {Role.ADMINISTRATOR}
    assert TotpDevice.objects.get().state == TotpDeviceState.ACTIVE


def test_the_command_asks_for_a_code_three_times_at_most() -> None:
    assert command_module.CODE_ATTEMPTS == 3


def test_the_command_creates_nothing_when_no_code_is_accepted(
    terminal: Terminal, monkeypatch: pytest.MonkeyPatch
) -> None:
    terminal.will_type(
        lines=[EMAIL, CONFIRMATION],
        secrets=[PASSWORD, PASSWORD],
        codes=[WRONG_CODE] * command_module.CODE_ATTEMPTS,
    )

    with pytest.raises(CommandError, match="No code was accepted"):
        _run(terminal)

    assert not User.objects.exists()
    assert not RoleEvent.objects.exists()
    assert not TotpDevice.objects.exists()
    assert list(terminal.codes) == []

    # Nothing was left behind, so the bootstrap can be run again.
    again = Terminal(monkeypatch)
    again.will_type(lines=[EMAIL, CONFIRMATION], secrets=[PASSWORD, PASSWORD])
    _run(again)
    assert selectors.roles_of(User.objects.get()) == {Role.ADMINISTRATOR}


def test_the_command_does_not_write_the_key_to_anything_but_a_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal = Terminal(monkeypatch, output_is_a_terminal=False)
    terminal.will_type(lines=[EMAIL, CONFIRMATION], secrets=[PASSWORD, PASSWORD])

    with pytest.raises(CommandError, match="at a terminal"):
        _run(terminal)

    assert terminal.prompts == []
    assert "Key:" not in terminal.out.getvalue()
    assert not User.objects.exists()


def test_the_password_never_appears_in_output_prompts_or_logs(
    terminal: Terminal, caplog: pytest.LogCaptureFixture
) -> None:
    terminal.will_type(lines=[EMAIL, CONFIRMATION], secrets=[PASSWORD, PASSWORD])

    with caplog.at_level(logging.DEBUG):
        output = _run(terminal)

    recorded = " ".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
    assert PASSWORD not in output
    assert PASSWORD not in " ".join(terminal.prompts)
    assert PASSWORD not in recorded
    # The key is shown on the terminal and reaches no log.
    assert terminal.key() not in recorded


def test_the_password_is_asked_for_with_hidden_input_twice(terminal: Terminal) -> None:
    terminal.will_type(lines=[EMAIL, CONFIRMATION], secrets=[PASSWORD, PASSWORD])

    _run(terminal)

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
        _run(terminal)

    assert terminal.prompts == []
    assert User.objects.count() == 1


@pytest.mark.parametrize("typed", ["", "yes", "y", "CREATE FIRST ADMINISTRATOR", "create"])
def test_the_command_requires_the_confirmation_to_be_typed_out(
    terminal: Terminal, typed: str
) -> None:
    terminal.will_type(lines=[EMAIL, typed], secrets=[PASSWORD, PASSWORD])

    with pytest.raises(CommandError, match="Not confirmed"):
        _run(terminal)

    assert not User.objects.exists()
    assert not RoleEvent.objects.exists()


def test_the_command_refuses_passwords_that_differ(terminal: Terminal) -> None:
    terminal.will_type(lines=[EMAIL, CONFIRMATION], secrets=[PASSWORD, PASSWORD + "x"])

    with pytest.raises(CommandError, match="not the same") as error:
        _run(terminal)

    assert PASSWORD not in str(error.value)
    assert not User.objects.exists()


def test_the_command_refuses_a_weak_password_without_repeating_it(terminal: Terminal) -> None:
    weak = "12345678901234"
    terminal.will_type(lines=[EMAIL, CONFIRMATION], secrets=[weak, weak])

    with pytest.raises(CommandError, match="entirely numeric") as error:
        _run(terminal)

    assert weak not in str(error.value)
    assert not User.objects.exists()


def test_the_command_refuses_to_run_without_a_person_at_a_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal = Terminal(monkeypatch, interactive=False)
    terminal.will_type(lines=[EMAIL, CONFIRMATION], secrets=[PASSWORD, PASSWORD])

    with pytest.raises(CommandError, match="at a terminal"):
        _run(terminal)

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
        _run(terminal)

    assert not User.objects.exists()
    assert terminal.prompts == []


def test_environment_variables_are_ignored_when_a_person_is_present(
    terminal: Terminal, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ENVIRONMENT_NAMES:
        monkeypatch.setenv(name, "TEST-from-the-environment@caipo.test")
    terminal.will_type(lines=[EMAIL, CONFIRMATION], secrets=[PASSWORD, PASSWORD])

    _run(terminal)

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

    _run(terminal)

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
        call_command(COMMAND, *arguments, stdout=terminal.out, stderr=io.StringIO())

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
