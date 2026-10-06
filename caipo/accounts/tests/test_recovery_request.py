"""Asking for a lost second factor to be recovered (ADR-0017, points 21 to 27 and 71 to 76).

The request only. Authorising and rejecting one are tested in
test_recovery_authorization.py.
"""

import inspect
import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.conf import LazySettings
from django.contrib.sessions.models import Session
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from caipo.accounts import services
from caipo.accounts.models import (
    AccountStatus,
    AuthenticationEvent,
    MfaChallenge,
    MfaRecoveryRequest,
    PasswordReset,
    RoleEvent,
    RoleEventType,
    TotpDevice,
    User,
)
from caipo.accounts.selectors import Role
from caipo.accounts.services import (
    MfaOutcome,
    PasswordResetOutcome,
    RecoveryRequestOutcome,
    RecoveryRequestResult,
    SignInOutcome,
)
from caipo.accounts.tests.fixtures import (
    Clock,
    UserFactory,
    code_at,
    enrolled_device,
    logged,
    supporting_account,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db]

type AccountFactory = Callable[..., User]

# Visibly synthetic fixture values.
PASSWORD = "TEST-passphrase-for-fixtures-only"
NEW_PASSWORD = "TEST-passphrase-chosen-afterwards"
SOURCE = "203.0.113.10"
OTHER_SOURCE = "198.51.100.66"

REQUESTED = RecoveryRequestOutcome.REQUESTED
REFUSED = RecoveryRequestOutcome.REFUSED
THROTTLED = RecoveryRequestOutcome.THROTTLED

RECOVERY_EVENTS = ["mfa_recovery_requested", "mfa_recovery_failed"]
STEP = timedelta(seconds=30)


@pytest.fixture
def account(user_with_roles: UserFactory) -> AccountFactory:
    """Return a factory for synthetic users with a known password and an active second factor."""

    def make(*roles: Role, trusted: bool = True) -> User:
        user = user_with_roles(*roles)
        user.set_password(PASSWORD)
        user.save()
        enrolled_device(user, trusted=trusted)
        return user

    return make


def _challenge(user: User, source: str = SOURCE, password: str = PASSWORD) -> str:
    result = services.sign_in(email=user.email, password=password, source=source)
    assert result.outcome == SignInOutcome.SECOND_FACTOR_REQUIRED
    assert result.challenge is not None
    return result.challenge


def _ask(challenge: str, source: str = SOURCE) -> RecoveryRequestResult:
    return services.request_mfa_recovery(challenge=challenge, source=source)


def _asked(user: User, source: str = SOURCE) -> RecoveryRequestResult:
    return _ask(_challenge(user, source), source)


def _recorded() -> list[tuple[str, int | None]]:
    return list(
        AuthenticationEvent.objects.filter(event_type__in=RECOVERY_EVENTS)
        .order_by("id")
        .values_list("event_type", "user_id")
    )


def _count(event_type: str) -> int:
    return AuthenticationEvent.objects.filter(event_type=event_type).count()


def _state() -> dict[str, Any]:
    """Return everything a submission that changes nothing must leave as it is."""
    return {
        "events": list(AuthenticationEvent.objects.order_by("id").values()),
        "requests": list(MfaRecoveryRequest.objects.order_by("id").values()),
        "challenges": list(MfaChallenge.objects.order_by("id").values()),
        "devices": list(TotpDevice.objects.order_by("id").values()),
        "users": list(User.objects.order_by("id").values()),
        "roles": list(RoleEvent.objects.order_by("id").values()),
        "sessions": Session.objects.count(),
    }


def _revoke(user: User, role: Role) -> None:
    RoleEvent.objects.create(
        user=user,
        role=role,
        event_type=RoleEventType.REVOKED,
        actor=supporting_account("test.seed@caipo.test"),
        reason="TEST fixture",
    )


# --- A request that is accepted --------------------------------------------------------


def test_a_request_is_created_with_a_number_for_the_account_of_the_challenge(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    other = account(Role.ADMINISTRATOR)
    challenge = _challenge(user)
    before = timezone.now()

    result = _ask(challenge)

    request = MfaRecoveryRequest.objects.get()
    assert result == RecoveryRequestResult(REQUESTED, number=request.pk)
    assert request.user == user
    assert before <= request.created_at <= timezone.now()
    assert not MfaRecoveryRequest.objects.filter(user=other).exists()


def test_the_request_is_recorded_naming_the_account_and_no_actor(account: AccountFactory) -> None:
    user = account(Role.REVIEWER)

    _asked(user)

    event = AuthenticationEvent.objects.get(event_type="mfa_recovery_requested")
    assert (event.user, event.actor, event.break_glass_action) == (user, None, "")
    assert event.identifier_key == services._key("identifier", user.email)
    assert event.source_key == services._key("source", SOURCE)
    assert _recorded() == [("mfa_recovery_requested", user.pk)]


def test_the_service_takes_a_challenge_and_a_source_and_returns_no_context() -> None:
    parameters = set(inspect.signature(services.request_mfa_recovery).parameters)
    fields = set(RecoveryRequestResult.__dataclass_fields__)

    # No account, email address, or role can be passed in, and nothing that
    # could sign anybody in comes out.
    assert parameters == {"challenge", "source"}
    assert fields == {"outcome", "number"}


def test_asking_uses_up_the_challenge(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    challenge = _challenge(user)

    assert _ask(challenge).outcome == REQUESTED

    assert not MfaChallenge.objects.filter(user=user).exists()
    verified = services.verify_second_factor(challenge=challenge, code=code_at(), source=SOURCE)
    assert verified.outcome == MfaOutcome.REFUSED
    assert verified.context is None
    assert _count("login_success") == 0


def test_asking_changes_nothing_about_the_account(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR, Role.READER)
    challenge = _challenge(user)
    before = _state()

    assert _ask(challenge).outcome == REQUESTED

    after = _state()
    # The device, the password, the status, the session epoch, and the roles
    # are as they were, and nobody was signed in.
    for unchanged in ("devices", "users", "roles", "sessions"):
        assert after[unchanged] == before[unchanged], unchanged
    assert after["users"][0]["session_epoch"] == 0
    assert [event["event_type"] for event in after["events"][len(before["events"]) :]] == [
        "mfa_recovery_requested"
    ]
    assert _count("login_success") == 0


def test_the_device_still_signs_the_account_in_after_a_request(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    number = _asked(user).number

    again = services.verify_second_factor(challenge=_challenge(user), code=code_at(), source=SOURCE)

    assert again.outcome == MfaOutcome.ACCEPTED
    # Signing in with the device does not withdraw the request.
    assert MfaRecoveryRequest.objects.get().pk == number


def test_asking_does_not_clear_the_count_of_refused_codes(
    account: AccountFactory, settings: LazySettings
) -> None:
    user = account(Role.ADMINISTRATOR)
    wrong = next(
        code
        for code in ("000000", "111111", "222222")
        if code not in {code_at(timezone.now() + offset * STEP) for offset in range(-3, 4)}
    )
    for _ in range(settings.MFA_THROTTLE_FAILURES):
        services.verify_second_factor(challenge=_challenge(user), code=wrong, source=SOURCE)

    assert _asked(user).outcome == REQUESTED

    after = services.verify_second_factor(challenge=_challenge(user), code=code_at(), source=SOURCE)
    assert after.outcome == MfaOutcome.THROTTLED


def test_a_request_can_be_made_straight_after_a_password_reset(account: AccountFactory) -> None:
    # Point 52: the cooling-off holds back the authorisation, not the request.
    user = account(Role.ADMINISTRATOR)
    tokens: list[str] = []

    def reset_url(token: str) -> str:
        tokens.append(token)
        return "https://caipo.test/TEST"

    services.request_password_reset(email=user.email, source=SOURCE, reset_url=reset_url)
    reset = services.reset_password(token=tokens[0], password=NEW_PASSWORD, source=SOURCE)
    assert reset.outcome == PasswordResetOutcome.RESET

    result = _ask(_challenge(user, password=NEW_PASSWORD))

    assert result.outcome == REQUESTED
    assert not PasswordReset.objects.exists()


# --- Who may ask (points 15 to 18) -----------------------------------------------------


@pytest.mark.parametrize(
    "roles",
    [
        (Role.REVIEWER,),
        (Role.ADMINISTRATOR,),
        (Role.REVIEWER, Role.ADMINISTRATOR),
        (Role.READER, Role.REVIEWER),
        (Role.RESEARCHER, Role.ADMINISTRATOR),
    ],
)
def test_an_account_whose_roles_require_a_second_factor_may_ask(
    account: AccountFactory, roles: tuple[Role, ...]
) -> None:
    user = account(*roles)

    assert _asked(user).outcome == REQUESTED
    assert MfaRecoveryRequest.objects.get().user == user


def test_the_second_factor_need_not_be_trusted(account: AccountFactory) -> None:
    # Point 16: active, trusted or not.
    user = account(Role.REVIEWER, trusted=False)

    assert _asked(user).outcome == REQUESTED


@pytest.mark.parametrize(
    "roles", [(), (Role.READER,), (Role.RESEARCHER,), (Role.READER, Role.RESEARCHER)]
)
def test_an_account_whose_roles_require_no_second_factor_is_refused(
    account: AccountFactory, roles: tuple[Role, ...]
) -> None:
    user = account(*roles)
    challenge = _challenge(user)

    assert _ask(challenge) == RecoveryRequestResult(REFUSED)

    assert not MfaRecoveryRequest.objects.exists()
    assert _recorded() == [("mfa_recovery_failed", user.pk)]
    # Refused, not used up: the device still completes the sign-in.
    assert MfaChallenge.objects.filter(user=user).exists()
    verified = services.verify_second_factor(challenge=challenge, code=code_at(), source=SOURCE)
    assert verified.outcome == MfaOutcome.ACCEPTED


def test_an_account_that_lost_the_role_since_signing_in_is_refused(account: AccountFactory) -> None:
    user = account(Role.REVIEWER, Role.READER)
    challenge = _challenge(user)
    _revoke(user, Role.REVIEWER)

    assert _ask(challenge).outcome == REFUSED
    assert _recorded() == [("mfa_recovery_failed", user.pk)]


@pytest.mark.parametrize(
    "changes",
    [
        {"status": AccountStatus.DISABLED},
        {
            "status": AccountStatus.PENDING_VERIFICATION,
            "activated_at": None,
            "email_verified_at": None,
        },
    ],
)
def test_an_account_that_is_not_active_is_refused(
    account: AccountFactory, changes: dict[str, Any]
) -> None:
    user = account(Role.ADMINISTRATOR)
    challenge = _challenge(user)
    User.objects.filter(pk=user.pk).update(**changes)

    assert _ask(challenge) == RecoveryRequestResult(REFUSED)

    assert not MfaRecoveryRequest.objects.exists()
    assert _recorded() == [("mfa_recovery_failed", user.pk)]
    assert MfaChallenge.objects.filter(user=user).exists()


@pytest.mark.parametrize("state", ["none", "pending_approval", "pending_verification"])
def test_an_account_without_an_active_second_factor_is_refused(
    account: AccountFactory, state: str
) -> None:
    user = account(Role.ADMINISTRATOR)
    challenge = _challenge(user)
    if state == "none":
        TotpDevice.objects.filter(user=user).delete()
    else:
        TotpDevice.objects.filter(user=user).update(
            state=state, confirmed_at=None, last_used_step=None, approved_at=None, approved_by=None
        )

    assert _ask(challenge) == RecoveryRequestResult(REFUSED)

    assert not MfaRecoveryRequest.objects.exists()
    assert _recorded() == [("mfa_recovery_failed", user.pk)]


# --- A challenge that cannot be used (point 72) ----------------------------------------


@pytest.mark.parametrize("challenge", ["", " ", "TEST-not-a-challenge", "0" * 43, "x" * 5000])
def test_an_unknown_challenge_is_refused_and_names_nobody(
    account: AccountFactory, challenge: str
) -> None:
    user = account(Role.ADMINISTRATOR)
    _challenge(user)

    assert _ask(challenge) == RecoveryRequestResult(REFUSED)

    event = AuthenticationEvent.objects.get(event_type="mfa_recovery_failed")
    assert (event.user, event.actor, event.identifier_key) == (None, None, "")
    assert event.source_key == services._key("source", SOURCE)
    assert not MfaRecoveryRequest.objects.exists()
    assert MfaChallenge.objects.filter(user=user).exists()


def test_a_lapsed_challenge_is_refused_and_names_its_account(
    account: AccountFactory, clock: Clock, settings: LazySettings
) -> None:
    user = account(Role.ADMINISTRATOR)
    challenge = _challenge(user)
    clock(settings.MFA_CHALLENGE_LIFETIME + timedelta(seconds=1))

    assert _ask(challenge) == RecoveryRequestResult(REFUSED)

    event = AuthenticationEvent.objects.get(event_type="mfa_recovery_failed")
    assert (event.user, event.actor) == (user, None)
    assert event.identifier_key == services._key("identifier", user.email)
    assert not MfaRecoveryRequest.objects.exists()


def test_a_challenge_lapses_exactly_when_it_does_for_a_code(
    account: AccountFactory, clock: Clock, settings: LazySettings
) -> None:
    user = account(Role.ADMINISTRATOR)
    challenge = _challenge(user)
    issued = MfaChallenge.objects.get().created_at
    clock(issued + settings.MFA_CHALLENGE_LIFETIME - timezone.now() - timedelta(seconds=1))

    early = _ask(challenge)

    assert early.outcome == REQUESTED

    late_challenge = _challenge(user, OTHER_SOURCE)
    issued = MfaChallenge.objects.get().created_at
    clock(issued + settings.MFA_CHALLENGE_LIFETIME - timezone.now())
    assert _ask(late_challenge, OTHER_SOURCE).outcome == REFUSED
    assert MfaRecoveryRequest.objects.get().pk == early.number


def test_a_challenge_that_was_already_used_for_a_request_is_refused(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    challenge = _challenge(user)
    first = _ask(challenge)

    second = _ask(challenge)

    assert second == RecoveryRequestResult(REFUSED)
    assert MfaRecoveryRequest.objects.get().pk == first.number
    # The challenge no longer says whose it was.
    assert _recorded() == [("mfa_recovery_requested", user.pk), ("mfa_recovery_failed", None)]


def test_a_challenge_that_completed_a_sign_in_is_refused(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    challenge = _challenge(user)
    signed_in = services.verify_second_factor(challenge=challenge, code=code_at(), source=SOURCE)
    assert signed_in.outcome == MfaOutcome.ACCEPTED

    assert _ask(challenge) == RecoveryRequestResult(REFUSED)

    assert _recorded() == [("mfa_recovery_failed", None)]
    assert not MfaRecoveryRequest.objects.exists()


def test_a_challenge_replaced_by_a_later_sign_in_is_refused(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    earlier = _challenge(user)
    later = _challenge(user, OTHER_SOURCE)

    assert _ask(earlier).outcome == REFUSED
    assert _recorded() == [("mfa_recovery_failed", None)]

    assert _ask(later, OTHER_SOURCE).outcome == REQUESTED


def test_a_cancelled_challenge_is_refused(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    challenge = _challenge(user)
    services.cancel_second_factor_challenge(challenge=challenge)

    assert _ask(challenge).outcome == REFUSED
    assert _recorded() == [("mfa_recovery_failed", None)]


def test_a_challenge_cannot_ask_for_another_account(account: AccountFactory) -> None:
    asking = account(Role.ADMINISTRATOR)
    other = account(Role.ADMINISTRATOR)
    _challenge(other)

    assert _asked(asking).outcome == REQUESTED

    assert MfaRecoveryRequest.objects.get().user == asking
    assert MfaChallenge.objects.filter(user=other).exists()
    assert not AuthenticationEvent.objects.filter(
        event_type__in=RECOVERY_EVENTS, user=other
    ).exists()


def test_every_refusal_is_the_same_outcome(account: AccountFactory, clock: Clock) -> None:
    ineligible = _ask(_challenge(account(Role.READER)))
    used = account(Role.ADMINISTRATOR)
    spent = _challenge(used, OTHER_SOURCE)
    _ask(spent, OTHER_SOURCE)
    lapsed = _challenge(account(Role.ADMINISTRATOR))
    clock(timedelta(minutes=6))

    results = [ineligible, _ask(spent), _ask("TEST-not-a-challenge"), _ask(lapsed)]

    assert results == [RecoveryRequestResult(REFUSED)] * 4


# --- A new request replaces the earlier one (point 25) ---------------------------------


def test_a_new_request_replaces_the_earlier_one_and_has_another_number(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    first = _asked(user)
    made_first = MfaRecoveryRequest.objects.get().created_at

    second = _asked(user, OTHER_SOURCE)

    assert first.number is not None
    assert second.number is not None
    assert second.number > first.number
    request = MfaRecoveryRequest.objects.get()
    assert (request.pk, request.user) == (second.number, user)
    assert request.created_at > made_first
    assert not MfaRecoveryRequest.objects.filter(pk=first.number).exists()
    assert _count("mfa_recovery_requested") == 2


def test_a_lapsed_request_is_replaced_like_any_other(
    account: AccountFactory, clock: Clock, settings: LazySettings
) -> None:
    user = account(Role.ADMINISTRATOR)
    first = _asked(user)
    clock(settings.MFA_RECOVERY_REQUEST_LIFETIME + timedelta(minutes=1))

    second = _asked(user)

    assert second.outcome == REQUESTED
    assert second.number != first.number
    assert MfaRecoveryRequest.objects.get().pk == second.number


def test_a_request_of_one_account_does_not_touch_the_request_of_another(
    account: AccountFactory,
) -> None:
    first, second = account(Role.ADMINISTRATOR), account(Role.REVIEWER)
    kept = _asked(first)

    _asked(second, OTHER_SOURCE)
    _asked(second, OTHER_SOURCE)

    assert MfaRecoveryRequest.objects.get(user=first).pk == kept.number
    assert MfaRecoveryRequest.objects.count() == 2


def test_a_refused_submission_leaves_the_earlier_request_in_place(
    account: AccountFactory,
) -> None:
    user = account(Role.REVIEWER, Role.READER)
    kept = _asked(user)
    challenge = _challenge(user)
    _revoke(user, Role.REVIEWER)

    assert _ask(challenge).outcome == REFUSED

    assert MfaRecoveryRequest.objects.get().pk == kept.number


def test_a_request_that_fails_part_way_changes_nothing(
    account: AccountFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = account(Role.ADMINISTRATOR)
    kept = _asked(user)
    challenge = _challenge(user)
    before = _state()

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("TEST fault")

    # After the challenge and the earlier request were removed and the new
    # request was created.
    monkeypatch.setattr(services, "_record", fail)
    with pytest.raises(RuntimeError, match="TEST fault"):
        _ask(challenge)
    monkeypatch.undo()

    assert _state() == before
    assert MfaRecoveryRequest.objects.get().pk == kept.number
    assert _ask(challenge).outcome == REQUESTED


# --- The limits (points 71 to 76) ------------------------------------------------------


def _refused_from(source: str, times: int) -> None:
    for _ in range(times):
        assert _ask("TEST-not-a-challenge", source).outcome == REFUSED


def test_the_limits_are_these(settings: LazySettings) -> None:
    assert settings.MFA_RECOVERY_REQUEST_ACCOUNT_LIMIT == 5
    assert settings.MFA_RECOVERY_REQUEST_ACCOUNT_WINDOW == timedelta(hours=1)
    assert settings.MFA_RECOVERY_REQUEST_SOURCE_LIMIT == 20
    assert settings.MFA_RECOVERY_REQUEST_SOURCE_WINDOW == timedelta(minutes=15)
    assert settings.MFA_RECOVERY_THROTTLE_FAILURES == 10
    assert settings.MFA_RECOVERY_THROTTLE_WINDOW == timedelta(minutes=15)


def test_ten_refused_submissions_from_a_source_stop_the_next(
    account: AccountFactory, clock: Clock
) -> None:
    user = account(Role.ADMINISTRATOR)
    _refused_from(SOURCE, 9)
    challenge = _challenge(user)
    assert _ask("TEST-not-a-challenge").outcome == REFUSED
    before = _state()

    # A submission that would otherwise be accepted, and one that would not.
    assert _ask(challenge) == RecoveryRequestResult(THROTTLED)
    assert _ask("TEST-not-a-challenge") == RecoveryRequestResult(THROTTLED)

    assert _state() == before
    assert _count("mfa_recovery_failed") == 10
    # Another source is not held back, and neither is this one once the
    # refusals have aged out.
    other = account(Role.ADMINISTRATOR)
    assert _asked(other, OTHER_SOURCE).outcome == REQUESTED
    clock(timedelta(minutes=15, seconds=1))
    assert _asked(user).outcome == REQUESTED


def test_twenty_requests_from_a_source_stop_the_next(account: AccountFactory, clock: Clock) -> None:
    accounts = [account(Role.ADMINISTRATOR) for _ in range(5)]
    for user in accounts[:4]:
        for _ in range(5):
            assert _asked(user).outcome == REQUESTED
    challenge = _challenge(accounts[4])
    before = _state()

    assert _ask(challenge) == RecoveryRequestResult(THROTTLED)
    assert _ask("TEST-not-a-challenge") == RecoveryRequestResult(THROTTLED)

    assert _state() == before
    assert _count("mfa_recovery_requested") == 20
    assert _count("mfa_recovery_failed") == 0
    assert _ask(_challenge(accounts[4], OTHER_SOURCE), OTHER_SOURCE).outcome == REQUESTED
    clock(timedelta(minutes=15, seconds=1))
    assert _asked(accounts[4]).outcome == REQUESTED


def test_five_requests_for_an_account_stop_the_next_whatever_its_source(
    account: AccountFactory, clock: Clock
) -> None:
    user = account(Role.ADMINISTRATOR)
    sources = [f"203.0.113.{number}" for number in range(1, 7)]
    numbers = [_asked(user, source).number for source in sources[:5]]
    challenge = _challenge(user, sources[5])
    before = _state()

    result = _ask(challenge, sources[5])

    assert result == RecoveryRequestResult(THROTTLED)
    assert _state() == before
    # Nothing recorded, the request and its number kept, the challenge unused.
    assert _count("mfa_recovery_requested") == 5
    assert _count("mfa_recovery_failed") == 0
    assert MfaRecoveryRequest.objects.get().pk == numbers[-1]
    verified = services.verify_second_factor(challenge=challenge, code=code_at(), source=sources[5])
    assert verified.outcome == MfaOutcome.ACCEPTED

    # Another account from the same source is not held back, and this one is
    # not once its requests have aged out.
    assert _asked(account(Role.REVIEWER), sources[5]).outcome == REQUESTED
    clock(timedelta(hours=1, seconds=1))
    assert _asked(user, sources[5]).outcome == REQUESTED


def test_a_throttled_account_is_not_examined_further_and_records_nothing(
    account: AccountFactory,
) -> None:
    user = account(Role.REVIEWER, Role.READER)
    for number in range(1, 6):
        _asked(user, f"203.0.113.{number}")
    challenge = _challenge(user, OTHER_SOURCE)
    _revoke(user, Role.REVIEWER)

    # No longer eligible, and that is not what it is told.
    assert _ask(challenge, OTHER_SOURCE) == RecoveryRequestResult(THROTTLED)
    assert _count("mfa_recovery_failed") == 0


def test_a_throttled_submission_is_not_itself_counted(
    account: AccountFactory, clock: Clock
) -> None:
    _refused_from(SOURCE, 10)
    for _ in range(25):
        assert _ask("TEST-not-a-challenge").outcome == THROTTLED

    # The window is counted from the ten refusals, not from the attempts
    # that were turned away after them.
    clock(timedelta(minutes=15, seconds=1))
    assert _asked(account(Role.ADMINISTRATOR)).outcome == REQUESTED
    assert _count("mfa_recovery_failed") == 10


def test_a_source_is_stopped_before_any_challenge_or_account_is_looked_up(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    _refused_from(SOURCE, 10)
    existing = _challenge(user)

    for challenge in (existing, "TEST-not-a-challenge"):
        with CaptureQueriesContext(connection) as queries:
            assert _ask(challenge).outcome == THROTTLED

        statements = [query["sql"] for query in queries.captured_queries]
        touched = " ".join(statements)
        # The lock, the two counts, and the transaction around them.
        assert "pg_advisory_xact_lock" in touched
        for table in (
            "accounts_mfachallenge",
            "accounts_user",
            "accounts_totpdevice",
            "accounts_roleevent",
            "accounts_mfarecoveryrequest",
        ):
            assert table not in touched, table
        assert not any(
            statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
            for statement in statements
        )
    # The same statements, whether or not the challenge exists.
    assert MfaChallenge.objects.filter(user=user).exists()


def test_the_account_limit_is_met_only_after_the_challenge_was_examined(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    for number in range(1, 6):
        _asked(user, f"203.0.113.{number}")

    # Without a challenge that identifies the account, its limit says nothing.
    assert _ask("TEST-not-a-challenge", OTHER_SOURCE) == RecoveryRequestResult(REFUSED)
    assert _ask(_challenge(user, OTHER_SOURCE), OTHER_SOURCE).outcome == THROTTLED


# --- What is kept, and what is not (point 88) ------------------------------------------


def test_no_event_and_no_log_holds_a_challenge_an_address_or_a_password(
    account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    user = account(Role.ADMINISTRATOR)
    refused = account(Role.READER)
    challenges = [_challenge(user), _challenge(refused), "TEST-not-a-challenge"]
    caplog.clear()

    for challenge in challenges:
        _ask(challenge)
    _refused_from(SOURCE, 8)
    throttled = _challenge(user)
    challenges.append(throttled)
    assert _ask(throttled).outcome == THROTTLED

    forbidden = [
        *challenges,
        *(services._key("challenge", challenge) for challenge in challenges),
        user.email,
        refused.email,
        SOURCE,
        PASSWORD,
    ]
    events = repr(list(AuthenticationEvent.objects.filter(event_type__in=RECOVERY_EVENTS).values()))
    written = logged(caplog.records)
    for value in forbidden:
        assert value not in events, value
        assert value not in written, value
    assert {
        event
        for event in (record.__dict__.get("event") for record in caplog.records)
        if isinstance(event, str) and event.startswith("mfa_recovery.")
    } == {"mfa_recovery.requested", "mfa_recovery.refused", "mfa_recovery.throttled"}


def test_the_log_says_which_limit_was_met_and_the_result_does_not(
    account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    user = account(Role.ADMINISTRATOR)
    for number in range(1, 6):
        _asked(user, f"203.0.113.{number}")
    by_account = _ask(_challenge(user, OTHER_SOURCE), OTHER_SOURCE)
    _refused_from(SOURCE, 10)
    by_source = _ask("TEST-not-a-challenge")

    assert by_account == by_source == RecoveryRequestResult(THROTTLED)
    scopes = [
        record.__dict__["scope"]
        for record in caplog.records
        if record.__dict__.get("event") == "mfa_recovery.throttled"
    ]
    assert scopes == ["account", "source_failures"]
