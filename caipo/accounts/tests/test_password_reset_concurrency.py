"""Password reset operations made at the same time, on separate database connections
(ADR-0016).

These tests commit their data, because other connections must see it, and the
database is emptied after each of them.
"""

import re
import threading
from collections.abc import Callable

import pytest
from django.conf import LazySettings
from django.core import mail as django_mail
from django.db import connections

from caipo.accounts import services
from caipo.accounts.models import (
    AccountStatus,
    AuthenticationEvent,
    MfaChallenge,
    PasswordReset,
    User,
)
from caipo.accounts.services import (
    MfaOutcome,
    PasswordResetOutcome,
    PasswordResetResult,
    SignInOutcome,
    SignInResult,
)
from caipo.accounts.tests.fixtures import approving_administrator, code_at, enrolled_device

pytestmark = [pytest.mark.services, pytest.mark.django_db(transaction=True)]

# Visibly synthetic fixture values.
EMAIL = "test.forgetful@caipo.test"
OLD_PASSWORD = "TEST-passphrase-that-was-forgotten"
PASSWORD = "TEST-passphrase-chosen-afterwards"
OTHER_PASSWORD = "TEST-another-passphrase-entirely"
SOURCE = "203.0.113.10"
OTHER_SOURCE = "198.51.100.66"
WAIT_SECONDS = 30
# Long enough for an operation that is not held back by a lock to finish.
SETTLE_SECONDS = 1.5

RESET = PasswordResetOutcome.RESET
REFUSED = PasswordResetOutcome.REFUSED


def _at_the_same_time(*operations: Callable[[], object]) -> list[object]:
    """Run the operations together, each on its own connection.

    Returns what each returned, or the exception it raised, in the order given.
    """
    barrier = threading.Barrier(len(operations))
    results: list[object] = [None] * len(operations)

    def run(index: int, operation: Callable[[], object]) -> None:
        try:
            barrier.wait(timeout=WAIT_SECONDS)
            results[index] = operation()
        except Exception as error:  # recorded and asserted on by the test, not hidden
            results[index] = error
        finally:
            connections.close_all()

    threads = [
        threading.Thread(target=run, args=(index, operation))
        for index, operation in enumerate(operations)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=WAIT_SECONDS)
        assert not thread.is_alive(), "an operation did not finish"
    return results


class _Held:
    """Runs one operation on its own connection and holds it at a chosen point.

    The point is a function of the services module that the operation calls
    while it holds its locks. The function runs unchanged; the operation only
    waits after it until released. This is how a test puts a second operation
    in the middle of a first one, in a known order.
    """

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, point: str, operation: Callable[[], object]
    ) -> None:
        self.reached = threading.Event()
        self.release = threading.Event()
        self.result: object = None
        original = getattr(services, point)
        holder = threading.current_thread

        def held(*args: object, **kwargs: object) -> object:
            value = original(*args, **kwargs)
            if holder() is self.thread:
                self.reached.set()
                assert self.release.wait(timeout=WAIT_SECONDS), "never released"
            return value

        def run() -> None:
            try:
                self.result = operation()
            except Exception as error:  # recorded and asserted on by the test, not hidden
                self.result = error
            finally:
                connections.close_all()

        monkeypatch.setattr(services, point, held)
        self.thread = threading.Thread(target=run)
        self.thread.start()
        assert self.reached.wait(timeout=WAIT_SECONDS), "the operation never reached the point"

    def finish(self) -> object:
        self.release.set()
        self.thread.join(timeout=WAIT_SECONDS)
        assert not self.thread.is_alive(), "the held operation did not finish"
        return self.result


def _alongside(operation: Callable[[], object]) -> tuple[threading.Thread, list[object]]:
    """Start an operation on its own connection and return its thread and where its result goes."""
    result: list[object] = []

    def run() -> None:
        try:
            result.append(operation())
        except Exception as error:  # recorded and asserted on by the test, not hidden
            result.append(error)
        finally:
            connections.close_all()

    thread = threading.Thread(target=run)
    thread.start()
    return thread, result


def _url(token: str) -> str:
    return f"https://caipo.test/password-reset/confirm/#{token}"


def _account(email: str = EMAIL) -> User:
    return User.objects.create_user(email, OLD_PASSWORD)


def _request(email: str = EMAIL, source: str = SOURCE) -> None:
    services.request_password_reset(email=email, source=source, reset_url=_url)


def _tokens() -> list[str]:
    return [
        str(token)
        for message in django_mail.outbox
        for token in re.findall(r"#(\S+)", str(message.body))
    ]


def _requested(email: str = EMAIL) -> str:
    _request(email)
    return _tokens()[-1]


def _reset(token: str, password: str = PASSWORD, source: str = SOURCE) -> PasswordResetResult:
    return services.reset_password(token=token, password=password, source=source)


def _events(event_type: str) -> int:
    return AuthenticationEvent.objects.filter(event_type=event_type).count()


def _outcomes(results: list[object]) -> list[str]:
    assert all(isinstance(result, PasswordResetResult) for result in results), results
    return sorted(
        result.outcome.value for result in results if isinstance(result, PasswordResetResult)
    )


# --- One token, several submissions ---------------------------------------------------------


def test_one_token_used_several_times_at_once_resets_once() -> None:
    user = _account()
    token = _requested()

    results = _at_the_same_time(*[lambda: _reset(token)] * 4)

    assert _outcomes(results) == ["refused", "refused", "refused", "reset"]
    assert User.objects.get(pk=user.pk).check_password(PASSWORD) is True
    assert _events("password_reset_succeeded") == 1
    assert _events("password_reset_failed") == 3
    assert not PasswordReset.objects.exists()


def test_two_people_with_the_same_token_cannot_both_set_the_password() -> None:
    user = _account()
    token = _requested()

    first, second = _at_the_same_time(
        lambda: _reset(token, PASSWORD, SOURCE),
        lambda: _reset(token, OTHER_PASSWORD, OTHER_SOURCE),
    )

    assert _outcomes([first, second]) == ["refused", "reset"]
    assert isinstance(first, PasswordResetResult)
    winner, loser = (
        (PASSWORD, OTHER_PASSWORD) if first.outcome == RESET else (OTHER_PASSWORD, PASSWORD)
    )
    stored = User.objects.get(pk=user.pk)
    assert stored.check_password(winner) is True
    assert stored.check_password(loser) is False


# --- Requests made together -------------------------------------------------------------------


def test_requests_made_at_once_leave_one_token_and_only_the_last_message_works() -> None:
    user = _account()

    _at_the_same_time(
        *[lambda number=number: _request(source=f"203.0.113.{number}") for number in range(4)]
    )

    assert PasswordReset.objects.filter(user=user).count() == 1
    assert _events("password_reset_requested") == 4
    tokens = _tokens()
    assert len(tokens) == len(set(tokens)) == 4
    current = PasswordReset.objects.get().token_key
    working = [token for token in tokens if services._key("password_reset", token) == current]
    assert len(working) == 1
    for number, token in enumerate(tokens):
        expected = RESET if token == working[0] else REFUSED
        # Each from its own source, so that no refusal is a throttled one.
        assert _reset(token, source=f"198.51.100.{number}").outcome == expected


def test_requests_for_one_address_sent_at_once_cannot_exceed_its_limit(
    settings: LazySettings,
) -> None:
    _account()
    limit = settings.PASSWORD_RESET_REQUEST_EMAIL_LIMIT

    _at_the_same_time(
        *[
            lambda number=number: _request(source=f"203.0.113.{number}")
            for number in range(limit + 4)
        ]
    )

    assert _events("password_reset_requested") == limit
    assert len(django_mail.outbox) == limit


def test_requests_from_one_source_sent_at_once_cannot_exceed_its_limit(
    settings: LazySettings,
) -> None:
    # A lower limit keeps the number of connections small; the count is what is tested.
    settings.PASSWORD_RESET_REQUEST_SOURCE_LIMIT = 6
    _account()
    addresses = [EMAIL, *(f"test.nobody{number}@caipo.test" for number in range(9))]

    _at_the_same_time(*[lambda email=email: _request(email) for email in addresses])

    assert _events("password_reset_requested") == 6
    assert len(django_mail.outbox) <= 1


def test_wrong_tokens_sent_at_once_cannot_exceed_the_limit(settings: LazySettings) -> None:
    _account()
    limit = settings.PASSWORD_RESET_THROTTLE_FAILURES

    results = _at_the_same_time(*[lambda: _reset("A" * 43)] * (limit + 6))

    assert _outcomes(results) == ["refused"] * limit + ["throttled"] * 6
    assert _events("password_reset_failed") == limit


def test_a_token_replaced_while_its_reset_waits_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _account()
    old = _requested()

    # A new request has issued its token and has not yet committed. The reset
    # of the old token finds its row, waits, and must look again afterwards.
    request = _Held(monkeypatch, "_issue_password_reset", lambda: _request(source=OTHER_SOURCE))
    thread, result = _alongside(lambda: _reset(old))
    thread.join(timeout=SETTLE_SECONDS)
    waited = thread.is_alive()
    assert request.finish() is None
    thread.join(timeout=WAIT_SECONDS)

    assert waited, "the reset did not wait for the request"
    assert result == [PasswordResetResult(REFUSED)]
    assert User.objects.get(pk=user.pk).check_password(OLD_PASSWORD) is True
    # The token that replaced it is untouched and works.
    assert PasswordReset.objects.filter(user=user).count() == 1
    assert _reset(_tokens()[-1], source=OTHER_SOURCE).outcome == RESET


# --- A reset and a disabling ----------------------------------------------------------------


def test_a_request_and_a_disabling_at_once_leave_no_usable_token() -> None:
    user = _account()
    administrator = approving_administrator()

    requested, disabled = _at_the_same_time(
        _request, lambda: services.disable_user(actor=administrator, user=user)
    )

    assert requested is None and disabled is None
    assert User.objects.get(pk=user.pk).status == AccountStatus.DISABLED
    # Whichever came first: asked first, the token was removed by the
    # disabling; asked second, none was issued.
    assert not PasswordReset.objects.exists()
    for token in _tokens():
        assert _reset(token).outcome == REFUSED
    services.enable_user(actor=administrator, user=user)
    for token in _tokens():
        assert _reset(token).outcome == REFUSED
    assert User.objects.get(pk=user.pk).check_password(OLD_PASSWORD) is True


def test_a_reset_and_a_disabling_at_once_never_leave_a_usable_account_or_token() -> None:
    user = _account()
    token = _requested()
    administrator = approving_administrator()

    reset, disabled = _at_the_same_time(
        lambda: _reset(token), lambda: services.disable_user(actor=administrator, user=user)
    )

    assert disabled is None
    assert isinstance(reset, PasswordResetResult)
    stored = User.objects.get(pk=user.pk)
    assert stored.status == AccountStatus.DISABLED
    assert not PasswordReset.objects.exists()
    if reset.outcome == RESET:
        assert stored.check_password(PASSWORD) is True
    else:
        # The disabling came first: the token was gone when the reset looked.
        assert reset.outcome == REFUSED
        assert stored.check_password(OLD_PASSWORD) is True
    sign_in = services.sign_in(email=EMAIL, password=PASSWORD, source=SOURCE)
    assert sign_in.outcome == SignInOutcome.REFUSED
    assert _reset(token, source=OTHER_SOURCE).outcome == REFUSED


def test_a_reset_waits_for_a_disabling_in_progress_and_is_then_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _account()
    token = _requested()
    administrator = approving_administrator()

    # The disabling holds the account's row lock and has not yet committed.
    disabling = _Held(
        monkeypatch,
        "_record_account",
        lambda: services.disable_user(actor=administrator, user=user),
    )
    thread, result = _alongside(lambda: _reset(token))
    thread.join(timeout=SETTLE_SECONDS)
    waited = thread.is_alive()
    assert disabling.finish() is None
    thread.join(timeout=WAIT_SECONDS)

    assert waited, "the reset did not wait for the disabling"
    assert result == [PasswordResetResult(REFUSED)]
    assert User.objects.get(pk=user.pk).check_password(OLD_PASSWORD) is True


# --- A reset and a sign-in --------------------------------------------------------------------


def test_a_sign_in_that_passed_the_old_password_loses_its_challenge_to_a_reset_begun_meanwhile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _account()
    enrolled_device(user)
    token = _requested()

    # The sign-in has accepted the old password and has not yet stored its challenge.
    sign_in = _Held(
        monkeypatch,
        "authenticate",
        lambda: services.sign_in(email=EMAIL, password=OLD_PASSWORD, source=SOURCE),
    )
    thread, result = _alongside(lambda: _reset(token, source=OTHER_SOURCE))
    thread.join(timeout=SETTLE_SECONDS)
    waited = thread.is_alive()
    signed_in = sign_in.finish()
    thread.join(timeout=WAIT_SECONDS)

    # The reset waited for the sign-in, so it ran wholly after it and found
    # the challenge to remove. Had it run alongside, the challenge would have
    # been stored after the reset and would still complete a sign-in.
    assert waited, "the reset did not wait for the sign-in"
    assert result == [PasswordResetResult(RESET)]
    assert isinstance(signed_in, SignInResult)
    assert signed_in.outcome == SignInOutcome.SECOND_FACTOR_REQUIRED
    assert signed_in.challenge is not None
    assert not MfaChallenge.objects.exists()
    verified = services.verify_second_factor(
        challenge=signed_in.challenge, code=code_at(), source=SOURCE
    )
    assert verified.outcome == MfaOutcome.REFUSED
    assert _events("login_success") == 0


def test_a_sign_in_with_the_old_password_waits_for_a_reset_in_progress_and_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _account()
    enrolled_device(user)
    token = _requested()

    # The reset holds its locks, has accepted the token, and has not yet committed.
    reset = _Held(monkeypatch, "validate_password", lambda: _reset(token, source=OTHER_SOURCE))
    thread, result = _alongside(
        lambda: services.sign_in(email=EMAIL, password=OLD_PASSWORD, source=SOURCE)
    )
    thread.join(timeout=SETTLE_SECONDS)
    waited = thread.is_alive()
    assert reset.finish() == PasswordResetResult(RESET)
    thread.join(timeout=WAIT_SECONDS)

    assert waited, "the sign-in did not wait for the reset"
    (signed_in,) = result
    assert isinstance(signed_in, SignInResult)
    assert signed_in.outcome == SignInOutcome.REFUSED
    assert not MfaChallenge.objects.exists()
    assert User.objects.get(pk=user.pk).check_password(PASSWORD) is True


def test_a_reset_and_a_sign_in_at_once_never_leave_a_challenge_from_the_old_password() -> None:
    user = _account()
    enrolled_device(user)
    token = _requested()

    reset, signed_in = _at_the_same_time(
        lambda: _reset(token, source=OTHER_SOURCE),
        lambda: services.sign_in(email=EMAIL, password=OLD_PASSWORD, source=SOURCE),
    )

    assert reset == PasswordResetResult(RESET)
    assert isinstance(signed_in, SignInResult)
    assert signed_in.outcome in (SignInOutcome.SECOND_FACTOR_REQUIRED, SignInOutcome.REFUSED)
    assert not MfaChallenge.objects.filter(user=user).exists()
    if signed_in.challenge is not None:
        verified = services.verify_second_factor(
            challenge=signed_in.challenge, code=code_at(), source=SOURCE
        )
        assert verified.outcome == MfaOutcome.REFUSED


def test_a_code_and_a_reset_at_once_complete_at_most_the_sign_in_begun_before_the_reset() -> None:
    user = _account()
    enrolled_device(user)
    token = _requested()
    challenge = services.sign_in(email=EMAIL, password=OLD_PASSWORD, source=SOURCE).challenge
    assert challenge is not None
    code = code_at()

    reset, verified = _at_the_same_time(
        lambda: _reset(token, source=OTHER_SOURCE),
        lambda: services.verify_second_factor(challenge=challenge, code=code, source=SOURCE),
    )

    assert reset == PasswordResetResult(RESET)
    assert isinstance(verified, services.MfaResult)
    assert verified.outcome in (MfaOutcome.ACCEPTED, MfaOutcome.REFUSED)
    # Used or removed, the challenge is gone, and it cannot be used again.
    assert not MfaChallenge.objects.exists()
    again = services.verify_second_factor(challenge=challenge, code=code, source=SOURCE)
    assert again.outcome == MfaOutcome.REFUSED
