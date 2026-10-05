"""What the database holds for the recovery of a lost second factor, and refuses (ADR-0017).

The schema only. No service, page, or command of recovery exists yet.
"""

from datetime import timedelta
from typing import Any

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from caipo.accounts.models import (
    DECISION_EVENT_TYPES,
    AuthenticationEvent,
    AuthenticationEventType,
    BreakGlassAction,
    MfaRecoveryRequest,
    RecoveryRequestChangeError,
    User,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db]

KEY = "0" * 64
BREAK_GLASS = "mfa_recovery_break_glass"
ACTIONS = ["revoke_device", "approve_enrollment"]

USER_KNOWN = "accounts_authenticationevent_user_known_unless_failure"
ACTOR_IFF_DECISION = "accounts_authenticationevent_actor_iff_decision"
ACTOR_IS_NOT_USER = "accounts_authenticationevent_actor_is_not_user"
ACTION_IFF_BREAK_GLASS = "accounts_authenticationevent_action_iff_break_glass"
NO_SOURCE = "accounts_authenticationevent_break_glass_has_no_source"

INSERT_EVENT = (
    "INSERT INTO accounts_authenticationevent"
    " (event_type, user_id, identifier_key, source_key, correlation_id, created_at{column})"
    " VALUES (%s, %s, %s, %s, '', now(){value})"
)


@pytest.fixture
def user() -> User:
    return User.objects.create_user("test.account@caipo.test")


@pytest.fixture
def actor() -> User:
    return User.objects.create_user("test.actor@caipo.test")


def _event(event_type: str, **values: Any) -> AuthenticationEvent:
    # A break-glass event has no source, and every other event here has one,
    # unless the test says otherwise.
    values.setdefault("source_key", "" if event_type == BREAK_GLASS else KEY)
    return AuthenticationEvent.objects.create(event_type=event_type, identifier_key=KEY, **values)


def _refused(constraint: str, event_type: str, **values: Any) -> None:
    with pytest.raises(IntegrityError, match=constraint), transaction.atomic():
        _event(event_type, **values)
    assert not AuthenticationEvent.objects.exists()


# --- The six event types (point 82) ----------------------------------------------------


def test_the_recovery_event_types_are_exactly_these_six() -> None:
    recovery = [value for value in AuthenticationEventType.values if "recovery" in value]

    assert recovery == [
        "mfa_recovery_requested",
        "mfa_recovery_failed",
        "mfa_recovery_rejected",
        "mfa_recovery_authorized",
        "mfa_recovery_completed",
        "mfa_recovery_break_glass",
    ]


@pytest.mark.parametrize("event_type", ["mfa_recovery_requested", "mfa_recovery_completed"])
def test_a_request_and_a_completion_name_the_account_and_no_actor(
    user: User, actor: User, event_type: str
) -> None:
    stored = _event(event_type, user=user)

    assert (stored.user, stored.actor, stored.break_glass_action) == (user, None, "")
    stored_id = stored.pk
    with pytest.raises(IntegrityError, match=USER_KNOWN), transaction.atomic():
        _event(event_type, user=None)
    with pytest.raises(IntegrityError, match=ACTOR_IFF_DECISION), transaction.atomic():
        _event(event_type, user=user, actor=actor)
    assert list(AuthenticationEvent.objects.values_list("pk", flat=True)) == [stored_id]


def test_a_refused_submission_names_the_account_only_if_one_is_known(user: User) -> None:
    named = _event("mfa_recovery_failed", user=user)
    unnamed = _event("mfa_recovery_failed", user=None)

    assert (named.user, named.actor) == (user, None)
    assert (unnamed.user, unnamed.actor) == (None, None)


def test_the_database_rejects_an_actor_on_a_refused_submission(user: User, actor: User) -> None:
    # Nobody decided anything: the application refused it (point 85).
    _refused(ACTOR_IFF_DECISION, "mfa_recovery_failed", user=user, actor=actor)
    _refused(ACTOR_IFF_DECISION, "mfa_recovery_failed", user=None, actor=actor)


@pytest.mark.parametrize("event_type", ["mfa_recovery_rejected", "mfa_recovery_authorized"])
def test_a_decision_on_a_recovery_names_the_account_and_the_administrator(
    user: User, actor: User, event_type: str
) -> None:
    stored = _event(event_type, user=user, actor=actor)

    assert (stored.user, stored.actor, stored.break_glass_action) == (user, actor, "")


@pytest.mark.parametrize("event_type", ["mfa_recovery_rejected", "mfa_recovery_authorized"])
def test_the_database_rejects_a_decision_on_a_recovery_that_names_nobody_as_deciding(
    user: User, event_type: str
) -> None:
    _refused(ACTOR_IFF_DECISION, event_type, user=user)


@pytest.mark.parametrize("event_type", ["mfa_recovery_rejected", "mfa_recovery_authorized"])
def test_the_database_rejects_a_decision_on_the_recovery_of_ones_own_account(
    user: User, event_type: str
) -> None:
    # Point 7: the service is to refuse it, and the database refuses its record.
    _refused(ACTOR_IS_NOT_USER, event_type, user=user, actor=user)


@pytest.mark.parametrize("event_type", ["mfa_recovery_rejected", "mfa_recovery_authorized"])
def test_the_database_rejects_a_decision_on_a_recovery_of_no_account(
    actor: User, event_type: str
) -> None:
    _refused(USER_KNOWN, event_type, user=None, actor=actor)


# --- The break-glass action (points 86 and 87) -----------------------------------------


def test_the_break_glass_actions_are_exactly_these_two() -> None:
    assert BreakGlassAction.values == ACTIONS
    limit = AuthenticationEvent._meta.get_field("break_glass_action").max_length
    assert limit is not None
    assert max(len(value) for value in ACTIONS) <= limit


@pytest.mark.parametrize("action", ACTIONS)
def test_a_break_glass_event_states_its_action_and_names_no_actor(user: User, action: str) -> None:
    stored = _event(BREAK_GLASS, user=user, break_glass_action=action)

    assert (stored.user, stored.actor) == (user, None)
    assert AuthenticationEvent.objects.get().break_glass_action == action


def test_the_database_rejects_a_break_glass_event_without_an_action(user: User) -> None:
    _refused(ACTION_IFF_BREAK_GLASS, BREAK_GLASS, user=user)
    _refused(ACTION_IFF_BREAK_GLASS, BREAK_GLASS, user=user, break_glass_action="")


@pytest.mark.parametrize(
    "action",
    [
        "REVOKE_DEVICE",
        "revoke_device ",
        " approve_enrollment",
        "revoke",
        "approve_enrolment",
        "revoke,approve",
        "set_password",
        "TEST free text",
    ],
)
def test_the_database_rejects_any_other_action(user: User, action: str) -> None:
    _refused(ACTION_IFF_BREAK_GLASS, BREAK_GLASS, user=user, break_glass_action=action)


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize(
    "event_type", [value for value in AuthenticationEventType.values if value != BREAK_GLASS]
)
def test_the_database_rejects_an_action_on_any_other_event(
    user: User, event_type: str, action: str
) -> None:
    # Named as each event requires, so that only the action is at fault.
    decided_by = (
        User.objects.create_user("test.actor@caipo.test")
        if event_type in DECISION_EVENT_TYPES
        else None
    )

    _refused(
        ACTION_IFF_BREAK_GLASS, event_type, user=user, actor=decided_by, break_glass_action=action
    )


@pytest.mark.parametrize("action", ACTIONS)
def test_the_database_rejects_an_actor_on_a_break_glass_event(
    user: User, actor: User, action: str
) -> None:
    # Whoever ran the command is not an account, and none stands in (point 67).
    _refused(ACTOR_IFF_DECISION, BREAK_GLASS, user=user, actor=actor, break_glass_action=action)


@pytest.mark.parametrize("action", ACTIONS)
def test_the_database_rejects_a_break_glass_event_for_no_account(action: str) -> None:
    _refused(USER_KNOWN, BREAK_GLASS, user=None, break_glass_action=action)


def test_the_action_cannot_be_null_in_the_database(user: User) -> None:
    # A null would make the check unknown, which a check constraint lets pass.
    statement = INSERT_EVENT.format(column=", break_glass_action", value=", NULL")

    for event_type, source in ((BREAK_GLASS, ""), ("login_success", KEY)):
        with pytest.raises(IntegrityError, match="break_glass_action"), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(statement, [event_type, user.pk, KEY, source])
    assert not AuthenticationEvent.objects.exists()


def test_the_database_supplies_no_action_for_a_row_that_states_none(user: User) -> None:
    statement = INSERT_EVENT.format(column="", value="")

    with pytest.raises(IntegrityError, match="break_glass_action"), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(statement, [BREAK_GLASS, user.pk, KEY, ""])
    assert not AuthenticationEvent.objects.exists()


def test_the_rules_hold_for_rows_written_without_the_application(user: User) -> None:
    statement = INSERT_EVENT.format(column=", break_glass_action", value=", %s")

    def insert(event_type: str, action: str, source: str) -> None:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(statement, [event_type, user.pk, KEY, source, action])

    for event_type, action, source in [
        (BREAK_GLASS, "", ""),
        (BREAK_GLASS, "set_password", ""),
        ("login_success", "revoke_device", KEY),
        ("mfa_recovery_completed", "approve_enrollment", KEY),
    ]:
        with pytest.raises(IntegrityError, match=ACTION_IFF_BREAK_GLASS):
            insert(event_type, action, source)
    for action in ACTIONS:
        with pytest.raises(IntegrityError, match=NO_SOURCE):
            insert(BREAK_GLASS, action, KEY)
    insert(BREAK_GLASS, "revoke_device", "")
    insert(BREAK_GLASS, "approve_enrollment", "")
    insert("login_success", "", KEY)

    assert sorted(AuthenticationEvent.objects.values_list("event_type", "break_glass_action")) == [
        ("login_success", ""),
        (BREAK_GLASS, "approve_enrollment"),
        (BREAK_GLASS, "revoke_device"),
    ]


# --- No network address on a break-glass event (point 86) ------------------------------


@pytest.mark.parametrize("action", ACTIONS)
def test_a_break_glass_event_is_stored_with_no_source(user: User, action: str) -> None:
    _event(BREAK_GLASS, user=user, break_glass_action=action, source_key="")

    assert AuthenticationEvent.objects.get().source_key == ""


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("source", [KEY, "0", " ", "TEST terminal", "recover_mfa_break_glass"])
def test_the_database_rejects_a_break_glass_event_with_a_source(
    user: User, action: str, source: str
) -> None:
    _refused(NO_SOURCE, BREAK_GLASS, user=user, break_glass_action=action, source_key=source)


def test_the_source_of_a_break_glass_event_cannot_be_null_in_the_database(user: User) -> None:
    # A null would make the check unknown, which a check constraint lets pass.
    statement = INSERT_EVENT.format(column=", break_glass_action", value=", %s")

    with pytest.raises(IntegrityError, match="source_key"), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(statement, [BREAK_GLASS, user.pk, KEY, None, "revoke_device"])
    assert not AuthenticationEvent.objects.exists()


@pytest.mark.parametrize("source", [KEY, ""])
@pytest.mark.parametrize(
    "event_type", [value for value in AuthenticationEventType.values if value != BREAK_GLASS]
)
def test_every_other_event_is_stored_with_or_without_a_source_as_before(
    user: User, event_type: str, source: str
) -> None:
    # The constraint speaks of the break-glass event and of no other.
    decided_by = (
        User.objects.create_user("test.actor@caipo.test")
        if event_type in DECISION_EVENT_TYPES
        else None
    )

    _event(event_type, user=user, actor=decided_by, source_key=source)

    assert AuthenticationEvent.objects.get().source_key == source


# --- The recovery request (point 25) ---------------------------------------------------


def _request(user: User) -> MfaRecoveryRequest:
    return MfaRecoveryRequest.objects.create(user=user, created_at=timezone.now())


def test_the_request_table_holds_exactly_these_columns() -> None:
    # A number, an account, and a time: no token, no secret, and nowhere to
    # write how a person was identified.
    columns = {field.column for field in MfaRecoveryRequest._meta.concrete_fields}

    assert columns == {"id", "user_id", "created_at"}


def test_a_request_is_stored_with_a_number(user: User) -> None:
    request = _request(user)

    stored = MfaRecoveryRequest.objects.get()
    assert (stored.pk, stored.user) == (request.pk, user)
    assert isinstance(stored.pk, int)
    assert stored.created_at.utcoffset() is not None


def test_an_account_has_at_most_one_request(user: User) -> None:
    first = _request(user)

    with pytest.raises(IntegrityError, match="user_id"), transaction.atomic():
        _request(user)

    assert list(MfaRecoveryRequest.objects.values_list("pk", flat=True)) == [first.pk]


def test_an_account_has_at_most_one_request_written_without_the_application(user: User) -> None:
    statement = "INSERT INTO accounts_mfarecoveryrequest (user_id, created_at) VALUES (%s, now())"
    with connection.cursor() as cursor:
        cursor.execute(statement, [user.pk])

    with pytest.raises(IntegrityError, match="user_id"), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(statement, [user.pk])

    assert MfaRecoveryRequest.objects.count() == 1


def test_different_accounts_each_have_their_own_request(user: User, actor: User) -> None:
    numbers = {_request(user).pk, _request(actor).pk}

    assert len(numbers) == 2
    assert MfaRecoveryRequest.objects.count() == 2


def test_a_request_that_replaces_another_has_another_number(user: User) -> None:
    numbers = []
    for _ in range(3):
        with transaction.atomic():
            MfaRecoveryRequest.objects.filter(user=user).delete()
            numbers.append(_request(user).pk)

    assert numbers == sorted(set(numbers))
    assert list(MfaRecoveryRequest.objects.values_list("pk", flat=True)) == [numbers[-1]]


def test_a_number_is_not_issued_again_after_its_request_is_removed(user: User, actor: User) -> None:
    removed = _request(user)
    removed_number = removed.pk
    removed.delete()

    later = [_request(actor).pk, _request(user).pk]

    assert removed_number not in later
    assert min(later) > removed_number


def test_the_database_rejects_a_request_of_no_account() -> None:
    with pytest.raises(IntegrityError, match="user_id"), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO accounts_mfarecoveryrequest (user_id, created_at) VALUES (NULL, now())"
            )

    assert not MfaRecoveryRequest.objects.exists()


def test_an_account_with_a_request_cannot_be_deleted(user: User) -> None:
    _request(user)

    with pytest.raises(ProtectedError):
        user.delete()

    assert User.objects.filter(pk=user.pk).exists()


# --- A request is replaced, never changed where it stands ------------------------------


def _stored() -> tuple[int, int, Any]:
    return MfaRecoveryRequest.objects.values_list("pk", "user_id", "created_at").get()


def test_the_time_a_request_was_made_cannot_be_changed_by_saving_it(user: User) -> None:
    request = _request(user)
    before = _stored()

    request.created_at = timezone.now() + timedelta(minutes=30)
    with pytest.raises(RecoveryRequestChangeError):
        request.save()
    with pytest.raises(RecoveryRequestChangeError):
        request.save(update_fields=["created_at"])

    assert _stored() == before


def test_the_account_of_a_request_cannot_be_changed_by_saving_it(user: User, actor: User) -> None:
    request = _request(user)
    before = _stored()

    request.user = actor
    with pytest.raises(RecoveryRequestChangeError):
        request.save()
    with pytest.raises(RecoveryRequestChangeError):
        request.save(update_fields=["user"])

    assert _stored() == before


def test_a_request_read_back_from_the_database_cannot_be_saved_again(user: User) -> None:
    _request(user)
    before = _stored()

    with pytest.raises(RecoveryRequestChangeError):
        MfaRecoveryRequest.objects.get().save()
    with pytest.raises(RecoveryRequestChangeError):
        MfaRecoveryRequest.objects.get().save(force_update=True)

    assert _stored() == before


@pytest.mark.parametrize("field", ["created_at", "user"])
def test_requests_cannot_be_changed_through_the_manager(
    user: User, actor: User, field: str
) -> None:
    request = _request(user)
    before = _stored()
    value: Any = timezone.now() + timedelta(minutes=30) if field == "created_at" else actor

    with pytest.raises(RecoveryRequestChangeError):
        MfaRecoveryRequest.objects.filter(pk=request.pk).update(**{field: value})
    with pytest.raises(RecoveryRequestChangeError):
        MfaRecoveryRequest.objects.all().update(**{field: value})
    setattr(request, field, value)
    with pytest.raises(RecoveryRequestChangeError):
        MfaRecoveryRequest.objects.bulk_update([request], [field])

    assert _stored() == before


def test_the_way_the_other_pending_records_are_replaced_is_refused_for_a_request(
    user: User,
) -> None:
    # MfaChallenge, AccountActivation, and PasswordReset are replaced with
    # update_or_create, which keeps the row and so would keep the number.
    _request(user)
    before = _stored()

    with pytest.raises(RecoveryRequestChangeError):
        MfaRecoveryRequest.objects.update_or_create(
            user=user, defaults={"created_at": timezone.now() + timedelta(minutes=30)}
        )

    assert _stored() == before


def test_update_or_create_can_only_create(user: User) -> None:
    request, created = MfaRecoveryRequest.objects.update_or_create(
        user=user, defaults={"created_at": timezone.now()}
    )

    assert created is True
    assert _stored()[:2] == (request.pk, user.pk)


def test_requests_cannot_be_written_in_bulk_which_could_overwrite_one(user: User) -> None:
    request = _request(user)
    before = _stored()
    replacement = MfaRecoveryRequest(user=user, created_at=timezone.now() + timedelta(minutes=30))

    with pytest.raises(RecoveryRequestChangeError):
        MfaRecoveryRequest.objects.bulk_create(
            [replacement],
            update_conflicts=True,
            unique_fields=["user"],
            update_fields=["created_at"],
        )
    with pytest.raises(RecoveryRequestChangeError):
        MfaRecoveryRequest.objects.bulk_create([replacement])

    assert _stored() == before
    assert request.pk == before[0]


def test_a_request_can_still_be_removed_and_made_again(user: User) -> None:
    first = _request(user)
    first_number, first_time = first.pk, first.created_at

    first.delete()
    assert not MfaRecoveryRequest.objects.exists()
    second = MfaRecoveryRequest.objects.create(
        user=user, created_at=first_time + timedelta(minutes=5)
    )
    MfaRecoveryRequest.objects.filter(user=user).delete()
    third = _request(user)

    assert first_number < second.pk < third.pk
    assert _stored()[:2] == (third.pk, user.pk)
