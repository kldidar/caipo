"""Recovery requests made alongside other operations, on separate database connections (ADR-0017).

These tests commit their data, because other connections must see it, and the
database is emptied after each of them.
"""

import re
import threading
from collections.abc import Callable
from functools import partial

import pytest
from django.conf import LazySettings
from django.core import mail as django_mail
from django.db import connections

from caipo.accounts import services
from caipo.accounts.models import (
    AccountStatus,
    AuthenticationEvent,
    MfaChallenge,
    MfaRecoveryRequest,
    TotpDevice,
    User,
)
from caipo.accounts.selectors import Role
from caipo.accounts.services import (
    MfaOutcome,
    MfaResult,
    PasswordResetOutcome,
    PasswordResetResult,
    RecoveryRequestOutcome,
    RecoveryRequestResult,
    SignInOutcome,
    SignInResult,
)
from caipo.accounts.tests.fixtures import (
    UserFactory,
    approving_administrator,
    code_at,
    enrolled_device,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db(transaction=True)]

# Visibly synthetic fixture values.
PASSWORD = "TEST-passphrase-for-fixtures-only"
NEW_PASSWORD = "TEST-passphrase-chosen-afterwards"
SOURCE = "203.0.113.10"
OTHER_SOURCE = "198.51.100.66"
WAIT_SECONDS = 30
# Long enough for an operation that is not held back by a lock to finish.
SETTLE_SECONDS = 1.5

REQUESTED = RecoveryRequestOutcome.REQUESTED
REFUSED = RecoveryRequestOutcome.REFUSED
THROTTLED = RecoveryRequestOutcome.THROTTLED


def _at_the_same_time(*operations: Callable[[], object]) -> list[object]:
    """Run the operations together, each on its own connection, and return their results."""
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


def _behind(held: _Held, operation: Callable[[], object]) -> tuple[object, object]:
    """Start an operation while another is held, and return both results in that order.

    Fails unless the second operation waited for the first: that it did is
    what shows the two cannot interleave.
    """
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
    thread.join(timeout=SETTLE_SECONDS)
    waited = thread.is_alive()
    first = held.finish()
    thread.join(timeout=WAIT_SECONDS)
    assert not thread.is_alive(), "the second operation did not finish"
    assert waited, "the second operation did not wait for the first"
    return first, result[0]


def _account(user_with_roles: UserFactory, role: Role = Role.ADMINISTRATOR) -> User:
    user = user_with_roles(role)
    user.set_password(PASSWORD)
    user.save()
    enrolled_device(user)
    return user


def _sign_in(user: User, source: str = SOURCE) -> SignInResult:
    return services.sign_in(email=user.email, password=PASSWORD, source=source)


def _challenge(user: User, source: str = SOURCE) -> str:
    result = _sign_in(user, source)
    assert result.outcome == SignInOutcome.SECOND_FACTOR_REQUIRED
    assert result.challenge is not None
    return result.challenge


def _ask(challenge: str, source: str = SOURCE) -> RecoveryRequestResult:
    return services.request_mfa_recovery(challenge=challenge, source=source)


def _verify(challenge: str) -> MfaResult:
    return services.verify_second_factor(challenge=challenge, code=code_at(), source=SOURCE)


def _count(event_type: str) -> int:
    return AuthenticationEvent.objects.filter(event_type=event_type).count()


def _recovery_outcomes(results: list[object]) -> list[str]:
    assert all(isinstance(result, RecoveryRequestResult) for result in results), results
    return sorted(
        result.outcome.value for result in results if isinstance(result, RecoveryRequestResult)
    )


# --- One challenge, several submissions ------------------------------------------------


def test_one_challenge_submitted_several_times_at_once_makes_one_request(
    user_with_roles: UserFactory,
) -> None:
    user = _account(user_with_roles)
    challenge = _challenge(user)

    results = _at_the_same_time(
        *(lambda source=f"203.0.113.{n}": _ask(challenge, source) for n in range(1, 7))
    )

    assert _recovery_outcomes(results) == ["refused"] * 5 + ["requested"]
    request = MfaRecoveryRequest.objects.get()
    numbers = [
        result.number
        for result in results
        if isinstance(result, RecoveryRequestResult) and result.number is not None
    ]
    assert numbers == [request.pk]
    assert _count("mfa_recovery_requested") == 1
    assert _count("mfa_recovery_failed") == 5
    assert not MfaChallenge.objects.exists()


def test_a_second_submission_waits_for_the_first_and_then_finds_the_challenge_used(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _account(user_with_roles)
    challenge = _challenge(user)

    held = _Held(monkeypatch, "_challenge_for_recovery", lambda: _ask(challenge))
    first, second = _behind(held, lambda: _ask(challenge, OTHER_SOURCE))

    assert isinstance(first, RecoveryRequestResult)
    assert first.outcome == REQUESTED
    assert second == RecoveryRequestResult(REFUSED)
    assert MfaRecoveryRequest.objects.get().pk == first.number
    # It found the challenge before it waited, and not after.
    failed = AuthenticationEvent.objects.get(event_type="mfa_recovery_failed")
    assert failed.user is None
    assert User.objects.get(pk=user.pk).session_epoch == 0


# --- A request and a code for the same challenge ---------------------------------------


def test_a_request_and_a_code_at_once_never_both_use_the_challenge(
    user_with_roles: UserFactory,
) -> None:
    for _ in range(4):
        user = _account(user_with_roles)
        challenge = _challenge(user)

        asked, verified = _at_the_same_time(partial(_ask, challenge), partial(_verify, challenge))

        assert isinstance(asked, RecoveryRequestResult), asked
        assert isinstance(verified, MfaResult), verified
        used = (asked.outcome == REQUESTED, verified.outcome == MfaOutcome.ACCEPTED)
        assert used in ((True, False), (False, True)), (asked, verified)
        assert MfaRecoveryRequest.objects.filter(user=user).exists() is used[0]
        assert not MfaChallenge.objects.filter(user=user).exists()


def test_a_code_that_arrives_during_a_request_is_refused(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _account(user_with_roles)
    challenge = _challenge(user)

    held = _Held(monkeypatch, "_challenge_for_recovery", lambda: _ask(challenge))
    asked, verified = _behind(held, lambda: _verify(challenge))

    assert isinstance(asked, RecoveryRequestResult)
    assert asked.outcome == REQUESTED
    assert verified == MfaResult(MfaOutcome.REFUSED)
    assert _count("login_success") == 0
    assert MfaRecoveryRequest.objects.count() == 1


def test_a_request_that_arrives_while_a_code_is_examined_is_refused(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _account(user_with_roles)
    challenge = _challenge(user)

    held = _Held(monkeypatch, "_pending_challenge", lambda: _verify(challenge))
    verified, asked = _behind(held, lambda: _ask(challenge))

    assert isinstance(verified, MfaResult)
    assert verified.outcome == MfaOutcome.ACCEPTED
    assert asked == RecoveryRequestResult(REFUSED)
    assert not MfaRecoveryRequest.objects.exists()
    assert _count("mfa_recovery_failed") == 1
    assert TotpDevice.objects.filter(user=user, state="active").exists()


# --- A request and a sign-in for the same account --------------------------------------


def test_a_sign_in_that_arrives_during_a_request_issues_a_challenge_that_survives_it(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _account(user_with_roles)
    challenge = _challenge(user)

    held = _Held(monkeypatch, "_challenge_for_recovery", lambda: _ask(challenge))
    asked, signed_in = _behind(held, lambda: _sign_in(user, OTHER_SOURCE))

    assert isinstance(asked, RecoveryRequestResult)
    assert asked.outcome == REQUESTED
    assert isinstance(signed_in, SignInResult)
    assert signed_in.outcome == SignInOutcome.SECOND_FACTOR_REQUIRED
    assert signed_in.challenge is not None
    # The request used up the earlier challenge and not the one issued after.
    assert MfaChallenge.objects.filter(user=user).count() == 1
    assert _verify(challenge).outcome == MfaOutcome.REFUSED
    assert _verify(signed_in.challenge).outcome == MfaOutcome.ACCEPTED
    assert MfaRecoveryRequest.objects.get().pk == asked.number


def test_a_request_with_a_challenge_that_a_sign_in_is_replacing_is_refused(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _account(user_with_roles)
    earlier = _challenge(user)

    # A new sign-in holds the lock on the account's email address and has not
    # yet replaced the challenge. The request finds the earlier one, waits,
    # and must look again afterwards.
    held = _Held(monkeypatch, "_throttled_by", lambda: _sign_in(user, OTHER_SOURCE))
    signed_in, asked = _behind(held, lambda: _ask(earlier))

    assert isinstance(signed_in, SignInResult)
    assert signed_in.challenge is not None
    assert asked == RecoveryRequestResult(REFUSED)
    assert not MfaRecoveryRequest.objects.exists()
    assert AuthenticationEvent.objects.get(event_type="mfa_recovery_failed").user is None
    # The challenge that replaced it is untouched and can ask.
    assert _ask(signed_in.challenge, OTHER_SOURCE).outcome == REQUESTED


# --- A request and a password reset ----------------------------------------------------


def _reset_token(user: User) -> str:
    services.request_password_reset(
        email=user.email,
        source=OTHER_SOURCE,
        reset_url=lambda token: f"https://caipo.test/password-reset/confirm/#{token}",
    )
    return [
        str(token)
        for message in django_mail.outbox
        for token in re.findall(r"#(\S+)", str(message.body))
    ][-1]


def _reset(token: str) -> PasswordResetResult:
    return services.reset_password(token=token, password=NEW_PASSWORD, source=OTHER_SOURCE)


def test_a_request_that_arrives_during_a_password_reset_is_refused(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _account(user_with_roles)
    token = _reset_token(user)
    challenge = _challenge(user)

    held = _Held(monkeypatch, "_pending_password_reset", lambda: _reset(token))
    reset, asked = _behind(held, lambda: _ask(challenge))

    assert reset == PasswordResetResult(PasswordResetOutcome.RESET)
    # The reset removed the challenge: it was issued on a password that no
    # longer exists.
    assert asked == RecoveryRequestResult(REFUSED)
    assert not MfaRecoveryRequest.objects.exists()
    assert User.objects.get(pk=user.pk).check_password(NEW_PASSWORD) is True


def test_a_password_reset_that_arrives_during_a_request_waits_and_both_are_done(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _account(user_with_roles)
    token = _reset_token(user)
    challenge = _challenge(user)

    held = _Held(monkeypatch, "_challenge_for_recovery", lambda: _ask(challenge))
    asked, reset = _behind(held, lambda: _reset(token))

    assert isinstance(asked, RecoveryRequestResult)
    assert asked.outcome == REQUESTED
    assert reset == PasswordResetResult(PasswordResetOutcome.RESET)
    # A reset knows nothing of a recovery and leaves the request where it is.
    assert MfaRecoveryRequest.objects.get().pk == asked.number
    assert User.objects.get(pk=user.pk).check_password(NEW_PASSWORD) is True
    assert TotpDevice.objects.filter(user=user, state="active").exists()


def test_a_request_and_a_password_reset_at_once_leave_a_consistent_state(
    user_with_roles: UserFactory,
) -> None:
    for _ in range(3):
        user = _account(user_with_roles)
        token = _reset_token(user)
        challenge = _challenge(user)

        asked, reset = _at_the_same_time(partial(_ask, challenge), partial(_reset, token))

        assert reset == PasswordResetResult(PasswordResetOutcome.RESET), reset
        assert isinstance(asked, RecoveryRequestResult), asked
        assert asked.outcome in (REQUESTED, REFUSED)
        assert MfaRecoveryRequest.objects.filter(user=user).exists() is (asked.outcome == REQUESTED)
        assert not MfaChallenge.objects.filter(user=user).exists()


# --- A request and a disabling ---------------------------------------------------------


def test_a_request_that_arrives_while_the_account_is_disabled_is_refused(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    administrator = approving_administrator()
    user = _account(user_with_roles, Role.REVIEWER)
    challenge = _challenge(user)

    # The disabling has changed the status and has not yet committed.
    held = _Held(
        monkeypatch,
        "_record_account",
        lambda: services.disable_user(actor=administrator, user=user),
    )
    disabled, asked = _behind(held, lambda: _ask(challenge))

    assert disabled is None
    assert asked == RecoveryRequestResult(REFUSED)
    assert not MfaRecoveryRequest.objects.exists()
    assert User.objects.get(pk=user.pk).status == AccountStatus.DISABLED
    # The challenge identified the account, which was by then not eligible.
    assert AuthenticationEvent.objects.get(event_type="mfa_recovery_failed").user == user


def test_a_disabling_that_arrives_during_a_request_waits_and_both_are_done(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    administrator = approving_administrator()
    user = _account(user_with_roles, Role.REVIEWER)
    challenge = _challenge(user)

    held = _Held(monkeypatch, "_challenge_for_recovery", lambda: _ask(challenge))
    asked, disabled = _behind(held, lambda: services.disable_user(actor=administrator, user=user))

    assert isinstance(asked, RecoveryRequestResult)
    assert asked.outcome == REQUESTED
    assert disabled is None
    assert User.objects.get(pk=user.pk).status == AccountStatus.DISABLED
    # The request stays on record and authorises nothing.
    assert MfaRecoveryRequest.objects.get().pk == asked.number
    assert TotpDevice.objects.filter(user=user, state="active").exists()


# --- The limits, under submissions sent together ---------------------------------------


def test_refused_submissions_sent_at_once_cannot_exceed_the_limit(
    settings: LazySettings,
) -> None:
    limit = settings.MFA_RECOVERY_THROTTLE_FAILURES

    results = _at_the_same_time(
        *(lambda n=n: _ask(f"TEST-not-a-challenge-{n}") for n in range(limit + 6))
    )

    assert _recovery_outcomes(results) == ["refused"] * limit + ["throttled"] * 6
    assert _count("mfa_recovery_failed") == limit


def test_requests_from_one_source_sent_at_once_cannot_exceed_its_limit(
    user_with_roles: UserFactory, settings: LazySettings
) -> None:
    settings.MFA_RECOVERY_REQUEST_SOURCE_LIMIT = 3
    challenges = [_challenge(_account(user_with_roles), f"203.0.113.{n}") for n in range(1, 7)]

    results = _at_the_same_time(*(lambda c=challenge: _ask(c) for challenge in challenges))

    assert _recovery_outcomes(results) == ["requested"] * 3 + ["throttled"] * 3
    assert _count("mfa_recovery_requested") == 3
    assert MfaRecoveryRequest.objects.count() == 3
    # A throttled submission used up nothing.
    assert MfaChallenge.objects.count() == 3
    assert _count("mfa_recovery_failed") == 0
