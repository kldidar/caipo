"""Checking credentials, recording the attempt, and throttling: no HTTP involved."""

import logging
import threading
from collections.abc import Callable
from datetime import timedelta

import pytest
from django.conf import LazySettings
from django.db import connections

from caipo.accounts import services
from caipo.accounts.models import AuthenticationEvent, User
from caipo.accounts.services import SignInOutcome, SignInResult
from caipo.core.correlation import correlation_scope

pytestmark = [pytest.mark.services, pytest.mark.django_db]

# Visibly synthetic fixture values.
EMAIL = "test.reader@caipo.test"
PASSWORD = "TEST-passphrase-for-fixtures-only"
WRONG = "TEST-wrong-passphrase"
UNKNOWN = "test.nobody@caipo.test"
SOURCE = "203.0.113.10"
OTHER_SOURCE = "203.0.113.20"

SIGNED_IN = SignInOutcome.SIGNED_IN
REFUSED = SignInOutcome.REFUSED
THROTTLED = SignInOutcome.THROTTLED


@pytest.fixture
def user() -> User:
    return User.objects.create_user(EMAIL, PASSWORD)


def _attempt(email: str = EMAIL, password: str = WRONG, source: str = SOURCE) -> SignInOutcome:
    return services.sign_in(email=email, password=password, source=source).outcome


def _events() -> list[tuple[str, int | None]]:
    return list(AuthenticationEvent.objects.order_by("id").values_list("event_type", "user_id"))


# --- Outcomes -----------------------------------------------------------------


def test_the_right_password_signs_in(user: User) -> None:
    result = services.sign_in(email=EMAIL, password=PASSWORD, source=SOURCE)

    assert result == SignInResult(SIGNED_IN, user)
    assert _events() == [("login_success", user.pk)]


@pytest.mark.parametrize("typed", ["Test.Reader@CAIPO.Test", "  test.reader@caipo.test  "])
def test_the_email_is_matched_in_its_normalized_form(user: User, typed: str) -> None:
    assert services.sign_in(email=typed, password=PASSWORD, source=SOURCE).user == user


def test_a_wrong_password_is_refused_and_recorded_against_the_account(user: User) -> None:
    result = services.sign_in(email=EMAIL, password=WRONG, source=SOURCE)

    assert result == SignInResult(REFUSED, None)
    assert _events() == [("login_failure", user.pk)]


def test_an_unknown_email_is_refused_and_recorded_against_nobody(user: User) -> None:
    result = services.sign_in(email=UNKNOWN, password=PASSWORD, source=SOURCE)

    assert result == SignInResult(REFUSED, None)
    assert _events() == [("login_failure", None)]


def test_a_deactivated_account_is_refused_even_with_the_right_password(user: User) -> None:
    User.objects.filter(pk=user.pk).update(is_active=False)

    result = services.sign_in(email=EMAIL, password=PASSWORD, source=SOURCE)

    assert result == SignInResult(REFUSED, None)
    assert _events() == [("login_failure", user.pk)]


def test_an_account_without_a_usable_password_is_refused() -> None:
    User.objects.create_user(EMAIL)

    assert _attempt(password="") == REFUSED
    assert _attempt(password="!") == REFUSED


def test_every_kind_of_refusal_gives_the_caller_the_same_answer(user: User) -> None:
    inactive = User.objects.create_user("test.inactive@caipo.test", PASSWORD)
    User.objects.filter(pk=inactive.pk).update(is_active=False)

    answers = {
        services.sign_in(email=EMAIL, password=WRONG, source=SOURCE),
        services.sign_in(email=UNKNOWN, password=PASSWORD, source=SOURCE),
        services.sign_in(email=inactive.email, password=PASSWORD, source=SOURCE),
    }

    assert answers == {SignInResult(REFUSED, None)}


def test_a_sign_out_is_recorded(user: User) -> None:
    services.record_sign_out(user=user, source=SOURCE)

    assert _events() == [("logout", user.pk)]


# --- What is recorded, and what never is --------------------------------------


def test_an_event_holds_keyed_hashes_and_nothing_that_was_submitted(user: User) -> None:
    services.sign_in(email=EMAIL, password=WRONG, source=SOURCE)
    services.sign_in(email=UNKNOWN, password=WRONG, source=SOURCE)
    services.sign_in(email=EMAIL, password=PASSWORD, source=SOURCE)
    services.record_sign_out(user=user, source=SOURCE)

    rows = list(AuthenticationEvent.objects.values())
    stored = repr(rows)
    assert len(rows) == 4
    for submitted in (PASSWORD, WRONG, EMAIL, UNKNOWN, SOURCE, user.password):
        assert submitted not in stored
    for row in rows:
        assert len(row["identifier_key"]) == 64
        assert len(row["source_key"]) == 64
        int(row["identifier_key"], 16)
        int(row["source_key"], 16)


def test_a_password_typed_into_the_email_field_is_not_stored(user: User) -> None:
    services.sign_in(email=PASSWORD, password=PASSWORD, source=SOURCE)

    assert PASSWORD not in repr(list(AuthenticationEvent.objects.values()))
    assert PASSWORD.lower() not in repr(list(AuthenticationEvent.objects.values()))


def test_the_same_address_and_source_always_give_the_same_keys(user: User) -> None:
    services.sign_in(email=EMAIL, password=WRONG, source=SOURCE)
    services.sign_in(email=" TEST.reader@caipo.test", password=PASSWORD, source=SOURCE)
    services.sign_in(email=UNKNOWN, password=WRONG, source=OTHER_SOURCE)

    first, second, third = AuthenticationEvent.objects.order_by("id")
    assert (first.identifier_key, first.source_key) == (second.identifier_key, second.source_key)
    assert third.identifier_key != first.identifier_key
    assert third.source_key != first.source_key
    assert first.identifier_key != first.source_key


def test_an_event_carries_the_correlation_id_of_the_work_it_belongs_to(user: User) -> None:
    with correlation_scope() as correlation_id:
        services.sign_in(email=EMAIL, password=WRONG, source=SOURCE)
        services.sign_in(email=EMAIL, password=PASSWORD, source=SOURCE)
        services.record_sign_out(user=user, source=SOURCE)

    recorded = set(AuthenticationEvent.objects.values_list("correlation_id", flat=True))
    assert recorded == {correlation_id}


def test_an_event_outside_any_unit_of_work_has_no_correlation_id(user: User) -> None:
    services.sign_in(email=EMAIL, password=PASSWORD, source=SOURCE)

    assert AuthenticationEvent.objects.get().correlation_id == ""


def test_nothing_submitted_is_logged(user: User, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        services.sign_in(email=EMAIL, password=WRONG, source=SOURCE)
        services.sign_in(email=UNKNOWN, password=WRONG, source=SOURCE)
        services.sign_in(email=EMAIL, password=PASSWORD, source=SOURCE)
        services.record_sign_out(user=user, source=SOURCE)

    events = [record.__dict__.get("event") for record in caplog.records if "caipo" in record.name]
    assert events == [
        "authentication.refused",
        "authentication.refused",
        "authentication.signed_in",
        "authentication.signed_out",
    ]
    logged = " ".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
    for submitted in (PASSWORD, WRONG, EMAIL, UNKNOWN, SOURCE, user.password):
        assert submitted not in logged


def test_a_refusal_is_logged_the_same_for_a_known_and_an_unknown_address(
    user: User, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger="caipo.accounts.services"):
        services.sign_in(email=EMAIL, password=WRONG, source=SOURCE)
        services.sign_in(email=UNKNOWN, password=WRONG, source=SOURCE)

    known, unknown = caplog.records
    extras = ("event", "user_id", "scope")
    assert known.getMessage() == unknown.getMessage()
    assert [known.__dict__.get(name) for name in extras] == [
        unknown.__dict__.get(name) for name in extras
    ]


# --- Throttling ---------------------------------------------------------------


def test_one_mistake_does_not_lock_anyone_out(user: User) -> None:
    assert _attempt() == REFUSED
    assert _attempt(password=PASSWORD) == SIGNED_IN


def test_repeated_failures_for_one_address_are_throttled(
    user: User, settings: LazySettings
) -> None:
    limit = settings.LOGIN_THROTTLE_ACCOUNT_FAILURES

    assert [_attempt() for _ in range(limit)] == [REFUSED] * limit
    # Now even the right password is not looked at.
    assert _attempt(password=PASSWORD) == THROTTLED
    assert _attempt() == THROTTLED


def test_throttling_is_the_same_whether_or_not_the_account_exists(
    user: User, settings: LazySettings
) -> None:
    attempts = settings.LOGIN_THROTTLE_ACCOUNT_FAILURES + 3

    existing = [_attempt(email=EMAIL, source=SOURCE) for _ in range(attempts)]
    missing = [_attempt(email=UNKNOWN, source=OTHER_SOURCE) for _ in range(attempts)]

    assert existing == missing
    assert THROTTLED in existing


def test_an_address_is_throttled_across_sources(user: User, settings: LazySettings) -> None:
    limit = settings.LOGIN_THROTTLE_ACCOUNT_FAILURES

    for number in range(limit):
        assert _attempt(source=f"198.51.100.{number}") == REFUSED

    assert _attempt(password=PASSWORD, source="198.51.100.200") == THROTTLED


def test_throttling_one_address_does_not_throttle_another(
    user: User, settings: LazySettings
) -> None:
    other = User.objects.create_user("test.other@caipo.test", PASSWORD)
    for _ in range(settings.LOGIN_THROTTLE_ACCOUNT_FAILURES):
        _attempt()
    assert _attempt(password=PASSWORD) == THROTTLED

    result = services.sign_in(email=other.email, password=PASSWORD, source=SOURCE)

    assert result == SignInResult(SIGNED_IN, other)


def test_repeated_failures_from_one_source_are_throttled(
    user: User, settings: LazySettings
) -> None:
    limit = settings.LOGIN_THROTTLE_SOURCE_FAILURES

    # A different address each time, so that no single address is throttled.
    outcomes = [_attempt(email=f"test.guess{number}@caipo.test") for number in range(limit)]

    assert outcomes == [REFUSED] * limit
    assert _attempt(email="test.another@caipo.test") == THROTTLED
    assert _attempt(email=EMAIL, password=PASSWORD) == THROTTLED


def test_throttling_one_source_does_not_throttle_another(
    user: User, settings: LazySettings
) -> None:
    for number in range(settings.LOGIN_THROTTLE_SOURCE_FAILURES):
        _attempt(email=f"test.guess{number}@caipo.test")
    assert _attempt(email=EMAIL, password=PASSWORD) == THROTTLED

    assert _attempt(email=EMAIL, password=PASSWORD, source=OTHER_SOURCE) == SIGNED_IN


def test_a_successful_sign_in_clears_the_count_for_that_address(
    user: User, settings: LazySettings, clock: Callable[[timedelta], None]
) -> None:
    limit = settings.LOGIN_THROTTLE_ACCOUNT_FAILURES
    for _ in range(limit - 1):
        clock(timedelta(seconds=1))
        assert _attempt() == REFUSED

    clock(timedelta(seconds=1))
    assert _attempt(password=PASSWORD) == SIGNED_IN

    # A full allowance again, not one remaining attempt.
    for _ in range(limit - 1):
        clock(timedelta(seconds=1))
        assert _attempt() == REFUSED
    clock(timedelta(seconds=1))
    assert _attempt(password=PASSWORD) == SIGNED_IN


def test_a_successful_sign_in_does_not_clear_the_count_for_the_source(
    user: User, settings: LazySettings, clock: Callable[[timedelta], None]
) -> None:
    limit = settings.LOGIN_THROTTLE_SOURCE_FAILURES
    for number in range(limit - 1):
        _attempt(email=f"test.guess{number}@caipo.test")

    clock(timedelta(seconds=1))
    assert _attempt(email=EMAIL, password=PASSWORD) == SIGNED_IN
    clock(timedelta(seconds=1))
    assert _attempt(email="test.last@caipo.test") == REFUSED

    # One valid account has not bought this source a new allowance, for
    # other addresses or for its own.
    assert _attempt(email="test.more@caipo.test") == THROTTLED
    assert _attempt(email=EMAIL, password=PASSWORD) == THROTTLED


def test_throttling_ends_by_itself_when_the_failures_are_old_enough(
    user: User, settings: LazySettings, clock: Callable[[timedelta], None]
) -> None:
    for _ in range(settings.LOGIN_THROTTLE_ACCOUNT_FAILURES):
        _attempt()
    assert _attempt(password=PASSWORD) == THROTTLED

    clock(settings.LOGIN_THROTTLE_WINDOW - timedelta(seconds=1))
    assert _attempt(password=PASSWORD) == THROTTLED

    clock(timedelta(seconds=2))
    assert _attempt(password=PASSWORD) == SIGNED_IN


def test_throttled_attempts_are_not_stored(user: User, settings: LazySettings) -> None:
    limit = settings.LOGIN_THROTTLE_ACCOUNT_FAILURES
    for _ in range(limit):
        _attempt()

    for _ in range(50):
        assert _attempt() == THROTTLED

    assert AuthenticationEvent.objects.count() == limit


def test_one_source_cannot_store_more_than_its_allowance_in_a_window(
    user: User, settings: LazySettings
) -> None:
    limit = settings.LOGIN_THROTTLE_SOURCE_FAILURES

    for number in range(limit * 3):
        _attempt(email=f"test.guess{number}@caipo.test")

    assert AuthenticationEvent.objects.count() == limit


def test_a_throttled_attempt_is_logged_without_saying_who(
    user: User, settings: LazySettings, caplog: pytest.LogCaptureFixture
) -> None:
    for _ in range(settings.LOGIN_THROTTLE_ACCOUNT_FAILURES):
        _attempt()
    caplog.clear()

    with caplog.at_level(logging.WARNING, logger="caipo.accounts.services"):
        _attempt(password=PASSWORD)

    (record,) = caplog.records
    assert record.__dict__["event"] == "authentication.throttled"
    assert record.__dict__["scope"] == "account"
    assert "user_id" not in record.__dict__
    assert EMAIL not in f"{record.getMessage()} {record.__dict__}"


def test_the_limits_come_from_repository_settings_not_the_environment(
    user: User, settings: LazySettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("LOGIN_THROTTLE_ACCOUNT_FAILURES", "LOGIN_THROTTLE_SOURCE_FAILURES"):
        for variable in (name, f"CAIPO_{name}", f"DJANGO_{name}"):
            monkeypatch.setenv(variable, "1000000")
    monkeypatch.setenv("LOGIN_THROTTLE_DISABLED", "true")

    for _ in range(settings.LOGIN_THROTTLE_ACCOUNT_FAILURES):
        _attempt()

    assert _attempt(password=PASSWORD) == THROTTLED


@pytest.mark.django_db(transaction=True)
def test_attempts_sent_together_cannot_exceed_the_allowance(settings: LazySettings) -> None:
    User.objects.create_user(EMAIL, PASSWORD)
    limit = settings.LOGIN_THROTTLE_ACCOUNT_FAILURES
    attempts = limit + 7
    barrier = threading.Barrier(attempts)
    outcomes: list[object] = []

    def attempt(number: int) -> None:
        try:
            barrier.wait(timeout=20)
            # Different sources, so that only the lock on the address serializes them.
            outcomes.append(_attempt(source=f"198.51.100.{number}"))
        except Exception as error:  # recorded and asserted on below, not hidden
            outcomes.append(error)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=attempt, args=(number,)) for number in range(attempts)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert sorted(str(outcome) for outcome in outcomes) == sorted(
        [str(REFUSED)] * limit + [str(THROTTLED)] * 7
    )
    assert AuthenticationEvent.objects.count() == limit
