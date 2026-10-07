"""The break-glass command at the server's terminal (ADR-0017, points 60 to 62).

What the command asks for, what it refuses to be given, and what it writes.
What its two actions require and do is tested with the services it calls.
"""

import builtins
import getpass
import io
import logging
import re
import sys
from collections.abc import Callable, Iterator

import pytest
from django.core.management import call_command, load_command_class
from django.core.management.base import CommandError

from caipo.accounts import selectors, services
from caipo.accounts.management.commands import recover_mfa_break_glass
from caipo.accounts.models import AuthenticationEvent, TotpDevice, TotpDeviceState, User
from caipo.accounts.selectors import Role
from caipo.accounts.services import BreakGlassOutcome, BreakGlassResult, MfaOutcome
from caipo.accounts.tests.fixtures import UserFactory, enrolled_device, logged
from caipo.accounts.tests.test_recovery_authorization import (
    PASSWORD,
    _asked,
    _confirm,
    _enrolment_request,
    _reset_token,
    _state,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db]

COMMAND = "recover_mfa_break_glass"
REVOKE_PHRASE = "revoke lost second factor"
APPROVE_PHRASE = "approve enrolment after recovery"
BREAK_GLASS = "mfa_recovery_break_glass"


class _TerminalOutput(io.StringIO):
    """What the command writes, on something that says it is a terminal or says it is not."""

    def __init__(self, *, interactive: bool) -> None:
        super().__init__()
        self._interactive = interactive

    def isatty(self) -> bool:
        return self._interactive


class Terminal:
    """Stands in for the person at the keyboard, and records what was asked."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        interactive: bool = True,
        output_is_a_terminal: bool = True,
    ) -> None:
        self.lines: Iterator[str] = iter(())
        self.prompts: list[str] = []
        self.hidden_prompts: list[str] = []
        self.out = _TerminalOutput(interactive=output_is_a_terminal)
        monkeypatch.setattr(builtins, "input", self._input)
        monkeypatch.setattr(getpass, "getpass", self._getpass)
        monkeypatch.setattr(sys.stdin, "isatty", lambda: interactive, raising=False)

    def will_type(self, *lines: str) -> None:
        self.lines = iter(lines)

    def _input(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        return next(self.lines)

    def _getpass(self, prompt: str = "") -> str:
        self.hidden_prompts.append(prompt)
        return next(self.lines)


@pytest.fixture
def terminal(monkeypatch: pytest.MonkeyPatch) -> Terminal:
    return Terminal(monkeypatch)


def _run(terminal: Terminal) -> str:
    err = io.StringIO()
    call_command(COMMAND, stdout=terminal.out, stderr=err)
    return terminal.out.getvalue() + err.getvalue()


@pytest.fixture
def administrator(user_with_roles: UserFactory) -> User:
    """Return the only Administrator, with a known password and an active second factor."""
    user = user_with_roles(Role.ADMINISTRATOR)
    user.set_password(PASSWORD)
    user.save()
    enrolled_device(user)
    return user


def _break_glass_actions() -> list[str]:
    return list(
        AuthenticationEvent.objects.filter(event_type=BREAK_GLASS)
        .order_by("id")
        .values_list("break_glass_action", flat=True)
    )


# --- The two actions, each chosen by its phrase ----------------------------------------


def test_the_phrases_are_the_two_fixed_in_the_command() -> None:
    assert recover_mfa_break_glass.REVOKE_CONFIRMATION == REVOKE_PHRASE
    assert recover_mfa_break_glass.APPROVE_CONFIRMATION == APPROVE_PHRASE
    assert REVOKE_PHRASE != APPROVE_PHRASE


def test_the_command_revokes_the_lost_device_of_the_only_administrator(
    terminal: Terminal, administrator: User
) -> None:
    number = _asked(administrator)
    terminal.will_type(administrator.email, str(number), REVOKE_PHRASE)

    output = _run(terminal)

    assert not TotpDevice.objects.filter(user=administrator).exists()
    assert User.objects.get(pk=administrator.pk).session_epoch == 1
    assert _break_glass_actions() == ["revoke_device"]
    assert "revoked" in output
    assert "Nobody was signed in" in output


def test_the_command_approves_the_enrolment_that_follows(
    terminal: Terminal, administrator: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    terminal.will_type(administrator.email, str(_asked(administrator)), REVOKE_PHRASE)
    _run(terminal)
    secret, number = _enrolment_request(administrator)
    again = Terminal(monkeypatch)
    again.will_type(administrator.email, str(number), APPROVE_PHRASE)

    output = _run(again)

    device = TotpDevice.objects.get(user=administrator)
    assert device.state == TotpDeviceState.PENDING_VERIFICATION
    assert (device.approved_at is not None, device.approved_by) == (True, None)
    assert _break_glass_actions() == ["revoke_device", "approve_enrollment"]
    assert "Nothing is active yet" in output
    # The first code is still given in the application, and completes the recovery.
    assert _confirm(administrator, secret).outcome == MfaOutcome.ACCEPTED
    assert not selectors.has_open_recovery(administrator.pk)


def test_the_phrase_alone_chooses_the_action_whatever_the_state_of_the_account(
    terminal: Terminal, administrator: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[tuple[str, str, int]] = []

    def note(name: str) -> Callable[..., BreakGlassResult]:
        def service(*, email: str, request_number: int) -> BreakGlassResult:
            called.append((name, email, request_number))
            return BreakGlassResult(BreakGlassOutcome.DONE)

        return service

    monkeypatch.setattr(services, "break_glass_revoke_device", note("revoke"))
    monkeypatch.setattr(services, "break_glass_approve_enrollment", note("approve"))
    # The account has a request to revoke and nothing to approve. The command
    # does not look: it calls what the phrase names.
    number = _asked(administrator)
    for phrase in (APPROVE_PHRASE, REVOKE_PHRASE):
        typed = Terminal(monkeypatch)
        typed.will_type(administrator.email, str(number), phrase)
        _run(typed)

    assert called == [
        ("approve", administrator.email, number),
        ("revoke", administrator.email, number),
    ]


def test_the_phrase_for_one_action_does_not_perform_the_other(
    terminal: Terminal, administrator: User
) -> None:
    number = _asked(administrator)
    before = _state()
    # A number that names a recovery request, and the phrase for an approval.
    terminal.will_type(administrator.email, str(number), APPROVE_PHRASE)

    with pytest.raises(CommandError, match="Refused. Nothing was changed"):
        _run(terminal)

    assert _state() == before


def test_the_command_asks_for_exactly_three_things_and_hides_none(
    terminal: Terminal, administrator: User
) -> None:
    terminal.will_type(administrator.email, str(_asked(administrator)), REVOKE_PHRASE)

    _run(terminal)

    assert len(terminal.prompts) == 3
    assert "Email address" in terminal.prompts[0]
    assert "Request number" in terminal.prompts[1]
    # Nothing it asks for is a secret, so nothing is asked for hidden.
    assert terminal.hidden_prompts == []
    for prompt in terminal.prompts:
        assert not re.search(r"password|code|secret|token|key", prompt, flags=re.IGNORECASE)


def test_the_command_never_uses_hidden_input() -> None:
    source = sys.modules[recover_mfa_break_glass.__name__].__loader__.get_source(  # type: ignore[union-attr]  # a source module always has a loader that returns its text
        recover_mfa_break_glass.__name__
    )

    assert "getpass" not in source
    assert "os.environ" not in source
    assert "getenv" not in source
    assert "add_arguments" not in source
    assert "logger" not in source


# --- The confirmation ------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase",
    [
        "",
        "yes",
        "y",
        "revoke",
        "approve",
        "Revoke lost second factor",
        "REVOKE LOST SECOND FACTOR",
        " revoke lost second factor",
        "revoke lost second factor ",
        "revoke  lost second factor",
        "revoke lost second factor.",
        "approve enrollment after recovery",
        "revoke_device",
        "approve_enrollment",
        "revoke lost second factor approve enrolment after recovery",
    ],
)
def test_anything_but_one_of_the_two_exact_phrases_does_nothing(
    phrase: str, terminal: Terminal, administrator: User
) -> None:
    number = _asked(administrator)
    before = _state()
    terminal.will_type(administrator.email, str(number), phrase)

    with pytest.raises(CommandError, match="Not confirmed. Nothing was done"):
        _run(terminal)

    assert _state() == before


@pytest.mark.parametrize(
    "number",
    ["", "seven", "-1", "+1", "1.0", "1e3", "0x10", "1 2", "١٢", "²", "9" * 19, "1; --"],
)
def test_what_is_not_a_request_number_is_refused_before_anything_is_looked_up(
    number: str, terminal: Terminal, administrator: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _asked(administrator)
    before = _state()

    def unreachable(**kwargs: object) -> BreakGlassResult:
        raise AssertionError("a service was called")

    monkeypatch.setattr(services, "break_glass_revoke_device", unreachable)
    terminal.will_type(administrator.email, number, REVOKE_PHRASE)

    with pytest.raises(CommandError, match="not a request number") as error:
        _run(terminal)

    assert _state() == before
    if number.strip():
        assert number not in str(error.value)


# --- Refusals ---------------------------------------------------------------------------


def test_every_refusal_is_one_answer_that_repeats_nothing_that_was_typed(
    terminal: Terminal,
    administrator: User,
    user_with_roles: UserFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    number = _asked(administrator)
    reviewer = user_with_roles(Role.REVIEWER)
    before = _state()
    answers = set()
    for email, typed_number in (
        ("test.nobody@caipo.test", str(number)),
        (administrator.email, str(number + 1000)),
        (reviewer.email, str(number)),
        # A password typed where the address was asked for.
        (PASSWORD, str(number)),
    ):
        typed = Terminal(monkeypatch)
        typed.will_type(email, typed_number, REVOKE_PHRASE)
        with pytest.raises(CommandError) as error:
            _run(typed)
        answers.add(str(error.value))
        shown = str(error.value) + typed.out.getvalue() + "".join(typed.prompts)
        assert email not in shown
        assert typed_number not in shown

    assert len(answers) == 1
    assert "Nothing was changed" in answers.pop()
    assert _state() == before


def test_success_is_written_only_after_the_action_has_been_committed(
    terminal: Terminal, administrator: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    number = _asked(administrator)
    before = _state()

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("TEST fault before the event is written")

    monkeypatch.setattr(services, "_record", fail)
    terminal.will_type(administrator.email, str(number), REVOKE_PHRASE)

    with pytest.raises(RuntimeError, match="TEST fault"):
        _run(terminal)

    assert "revoked" not in terminal.out.getvalue()
    assert _state() == before


# --- A person at a terminal, and nothing else (point 61) --------------------------------


def test_the_command_refuses_to_run_without_a_terminal_on_its_input(
    administrator: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    number = _asked(administrator)
    before = _state()
    terminal = Terminal(monkeypatch, interactive=False)
    terminal.will_type(administrator.email, str(number), REVOKE_PHRASE)

    with pytest.raises(CommandError, match="at a terminal"):
        _run(terminal)

    assert terminal.prompts == []
    assert _state() == before


def test_the_command_refuses_to_run_without_a_terminal_on_its_output(
    administrator: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    number = _asked(administrator)
    before = _state()
    terminal = Terminal(monkeypatch, output_is_a_terminal=False)
    terminal.will_type(administrator.email, str(number), REVOKE_PHRASE)

    with pytest.raises(CommandError, match="at a terminal"):
        _run(terminal)

    assert terminal.prompts == []
    assert terminal.out.getvalue() == ""
    assert _state() == before


@pytest.mark.parametrize(
    "arguments",
    [
        ["--noinput"],
        ["--no-input"],
        ["--email", "test.user1@caipo.test"],
        ["--account", "test.user1@caipo.test"],
        ["--number", "1"],
        ["--action", "revoke_device"],
        ["--revoke"],
        ["--approve"],
        ["--confirm"],
        ["--yes"],
        ["-y"],
        ["--force-revoke"],
        ["--non-interactive"],
        ["--password", PASSWORD],
        ["test.user1@caipo.test"],
        ["test.user1@caipo.test", "1"],
        ["test.user1@caipo.test", "1", REVOKE_PHRASE],
        ["revoke_device"],
    ],
)
def test_the_command_accepts_no_argument_and_no_option(
    arguments: list[str], terminal: Terminal, administrator: User
) -> None:
    number = _asked(administrator)
    before = _state()
    terminal.will_type(administrator.email, str(number), REVOKE_PHRASE)

    with pytest.raises((CommandError, TypeError)):
        call_command(COMMAND, *arguments, stdout=terminal.out, stderr=io.StringIO())

    assert terminal.prompts == []
    assert _state() == before


def test_the_command_defines_no_options_of_its_own() -> None:
    command = load_command_class("caipo.accounts", COMMAND)
    parser = command.create_parser("manage.py", COMMAND)
    options = {option for action in parser._actions for option in action.option_strings}
    positional = [action.dest for action in parser._actions if not action.option_strings]

    assert options == {
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
    assert positional == []


ENVIRONMENT_NAMES = [
    "CAIPO_BREAK_GLASS",
    "CAIPO_BREAK_GLASS_ACCOUNT",
    "CAIPO_BREAK_GLASS_EMAIL",
    "CAIPO_BREAK_GLASS_NUMBER",
    "CAIPO_BREAK_GLASS_ACTION",
    "CAIPO_BREAK_GLASS_CONFIRMATION",
    "RECOVER_MFA_BREAK_GLASS",
    "BREAK_GLASS_ACTION",
    "DJANGO_SUPERUSER_EMAIL",
    "NOINPUT",
]


def test_no_environment_variable_supplies_an_input_or_skips_the_terminal(
    administrator: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    number = _asked(administrator)
    before = _state()
    for name in ENVIRONMENT_NAMES:
        monkeypatch.setenv(name, REVOKE_PHRASE)
    terminal = Terminal(monkeypatch, interactive=False)

    with pytest.raises(CommandError, match="at a terminal"):
        _run(terminal)

    assert terminal.prompts == []
    assert _state() == before
    assert number


def test_environment_variables_are_ignored_when_a_person_is_present(
    terminal: Terminal, administrator: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    number = _asked(administrator)
    before = _state()
    for name in ENVIRONMENT_NAMES:
        monkeypatch.setenv(name, REVOKE_PHRASE)
    # The person does not confirm, whatever the environment says.
    terminal.will_type(administrator.email, str(number), "no")

    with pytest.raises(CommandError, match="Not confirmed"):
        _run(terminal)

    assert len(terminal.prompts) == 3
    assert _state() == before


# --- What the command shows and records (points 62, 67, and 88) -------------------------


def test_the_command_shows_and_logs_no_secret_and_no_typed_phrase(
    terminal: Terminal,
    administrator: User,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    token = _reset_token(administrator)
    stored = User.objects.get(pk=administrator.pk)
    session_value = stored.get_session_auth_hash()
    device = TotpDevice.objects.get(user=administrator)
    terminal.will_type(administrator.email, str(_asked(administrator)), REVOKE_PHRASE)
    caplog.clear()

    shown = _run(terminal)
    secret, number = _enrolment_request(administrator)
    again = Terminal(monkeypatch)
    again.will_type(administrator.email, str(number), APPROVE_PHRASE)
    shown += _run(again) + "".join(terminal.prompts + again.prompts)

    lines = logged(caplog.records)
    for text in (shown, lines):
        for forbidden in (
            PASSWORD,
            stored.password,
            token,
            session_value,
            bytes(device.secret_ciphertext).hex(),
            device.key_id,
            "otpauth",
        ):
            assert forbidden not in text
    assert administrator.email not in shown
    assert administrator.email not in lines
    # The phrases are shown, so that they can be typed. They are never logged.
    assert REVOKE_PHRASE in shown
    assert REVOKE_PHRASE not in lines
    assert APPROVE_PHRASE not in lines
    assert secret.decode(errors="replace") not in shown


def test_the_event_names_no_actor_and_no_operator_and_carries_the_runs_correlation_id(
    terminal: Terminal, administrator: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("USER", "LOGNAME", "USERNAME", "LNAME", "SUDO_USER"):
        monkeypatch.setenv(name, "TEST-operator")
    terminal.will_type(administrator.email, str(_asked(administrator)), REVOKE_PHRASE)

    _run(terminal)

    event = AuthenticationEvent.objects.get(event_type=BREAK_GLASS)
    assert (event.user, event.actor, event.source_key) == (administrator, None, "")
    assert re.fullmatch(r"[0-9a-f]{32}", event.correlation_id)
    assert "TEST-operator" not in str(AuthenticationEvent.objects.filter(pk=event.pk).values())
    # No account was made to stand for whoever ran the command.
    assert not User.objects.filter(email__icontains="operator").exists()
    fields = {field.name for field in AuthenticationEvent._meta.get_fields()}
    assert fields == {
        "id",
        "event_type",
        "user",
        "actor",
        "identifier_key",
        "source_key",
        "correlation_id",
        "break_glass_action",
        "created_at",
    }


def test_each_run_has_a_correlation_id_of_its_own(
    terminal: Terminal, administrator: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    terminal.will_type(administrator.email, str(_asked(administrator)), REVOKE_PHRASE)
    _run(terminal)
    _secret, number = _enrolment_request(administrator)
    again = Terminal(monkeypatch)
    again.will_type(administrator.email, str(number), APPROVE_PHRASE)
    _run(again)

    first, second = AuthenticationEvent.objects.filter(event_type=BREAK_GLASS).order_by("id")

    assert first.correlation_id and second.correlation_id
    assert first.correlation_id != second.correlation_id
