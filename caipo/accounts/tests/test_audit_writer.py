"""The one service that writes the audit record (ADR-0018 points 38 to 44)."""

import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from django.contrib.auth.models import AnonymousUser
from django.db import DataError, IntegrityError, transaction

from caipo.accounts import selectors, services
from caipo.accounts.models import AccountStatus, AuditEvent, AuditEventChange, User
from caipo.accounts.selectors import (
    Assurance,
    AuditAction,
    AuditField,
    AuditTargetType,
    AuthenticationContext,
    Role,
)
from caipo.accounts.services import AuditChange, AuditRecordError, record_audit_event
from caipo.accounts.tests.fixtures import UserFactory, logged, signed_in
from caipo.core.correlation import correlation_scope

pytestmark = [pytest.mark.services, pytest.mark.django_db]

# Visibly synthetic: the identifiers of records that do not exist.
TARGET = uuid.UUID("00000000-0000-4000-8000-000000000001")
REFERRED_TO = uuid.UUID("00000000-0000-4000-8000-0000000000aa")
# Not a version 4 identifier. Which version a record is given is decided
# where the record is created, not here.
NOT_VERSION_4 = uuid.UUID("00000000-0000-1000-8000-000000000003")
RENAMED = AuditChange(AuditField.NAME_EN, "TEST old name", "TEST new name")


@pytest.fixture
def actor() -> AuthenticationContext:
    return signed_in(User.objects.create_user("test.actor@caipo.test"))


def _update(actor: AuthenticationContext, *changes: AuditChange) -> None:
    record_audit_event(
        actor=actor,
        action=AuditAction.UPDATED,
        target_type=AuditTargetType.INSTITUTION,
        target_public_id=TARGET,
        changes=changes,
    )


def _stored_changes() -> dict[str, tuple[str, str]]:
    return {
        change.field: (change.old_value, change.new_value)
        for change in AuditEventChange.objects.all()
    }


def _nothing_was_written() -> bool:
    return not AuditEvent.objects.exists() and not AuditEventChange.objects.exists()


# --- What is written ----------------------------------------------------------


def test_it_returns_nothing_and_writes_one_event(actor: AuthenticationContext) -> None:
    returned = record_audit_event(  # type: ignore[func-returns-value]  # that it returns nothing is what is asserted
        actor=actor,
        action=AuditAction.CREATED,
        target_type=AuditTargetType.COUNTRY,
        target_public_id=TARGET,
        changes=[],
    )

    assert returned is None
    event = AuditEvent.objects.get()
    assert (event.action, event.target_type, event.target_public_id, event.actor) == (
        "created",
        "registry.country",
        TARGET,
        actor.user,
    )
    assert not AuditEventChange.objects.exists()


def test_the_event_holds_the_correlation_id_of_the_unit_of_work(
    actor: AuthenticationContext,
) -> None:
    with correlation_scope() as correlation_id:
        _update(actor, RENAMED)

    assert AuditEvent.objects.get().correlation_id == correlation_id


def test_outside_a_unit_of_work_the_correlation_id_is_empty(actor: AuthenticationContext) -> None:
    _update(actor, RENAMED)

    assert AuditEvent.objects.get().correlation_id == ""


def test_an_update_records_each_changed_field_with_its_old_and_new_value(
    actor: AuthenticationContext,
) -> None:
    _update(
        actor,
        AuditChange(AuditField.KIND, "TEST kind a", "TEST kind b"),
        AuditChange(AuditField.PARENT, None, REFERRED_TO),
        AuditChange(AuditField.VALID_TO, date(2001, 2, 3), None),
    )

    event = AuditEvent.objects.get()
    assert event.action == "updated"
    assert {change.event for change in AuditEventChange.objects.all()} == {event}
    assert _stored_changes() == {
        "kind": ("TEST kind a", "TEST kind b"),
        "parent": ("", "00000000-0000-4000-8000-0000000000aa"),
        "valid_to": ("2001-02-03", ""),
    }


@pytest.mark.parametrize(
    ("value", "rendering"),
    [
        ("TEST Name with  Spaces and CAPITALS", "TEST Name with  Spaces and CAPITALS"),
        ("TEST décomposé узбек", "TEST décomposé узбек"),
        (date(1999, 12, 31), "1999-12-31"),
        (date(1, 1, 1), "0001-01-01"),
        (REFERRED_TO, "00000000-0000-4000-8000-0000000000aa"),
        (uuid.UUID("ABCDEF00-0000-4000-8000-0000000000AA"), "abcdef00-0000-4000-8000-0000000000aa"),
        (None, ""),
    ],
)
def test_a_value_has_one_rendering(
    actor: AuthenticationContext, value: services.AuditValue, rendering: str
) -> None:
    _update(actor, AuditChange(AuditField.NAME_EN, "TEST before", value))

    assert _stored_changes() == {"name_en": ("TEST before", rendering)}


def test_a_value_of_the_greatest_length_is_stored_whole(actor: AuthenticationContext) -> None:
    longest = "T" * 200

    _update(actor, AuditChange(AuditField.NAME_EN, None, longest))

    assert _stored_changes() == {"name_en": ("", longest)}


@pytest.mark.parametrize(
    ("action", "target_type"),
    [
        (action, target_type)
        for action in (AuditAction.CREATED, AuditAction.UPDATED)
        for target_type in AuditTargetType
    ]
    + [
        (AuditAction.DEACTIVATED, AuditTargetType.COUNTRY),
        (AuditAction.DEACTIVATED, AuditTargetType.LANGUAGE),
        (AuditAction.REACTIVATED, AuditTargetType.COUNTRY),
        (AuditAction.REACTIVATED, AuditTargetType.LANGUAGE),
        (AuditAction.MARKED_ENTERED_IN_ERROR, AuditTargetType.INSTITUTION_NAME),
    ],
)
def test_every_allowed_pair_is_written(
    actor: AuthenticationContext, action: AuditAction, target_type: AuditTargetType
) -> None:
    record_audit_event(
        actor=actor,
        action=action,
        target_type=target_type,
        target_public_id=TARGET,
        changes=[RENAMED] if action is AuditAction.UPDATED else [],
    )

    event = AuditEvent.objects.get()
    assert (event.action, event.target_type) == (action.value, target_type.value)


def test_which_version_the_identifier_is_does_not_concern_it(actor: AuthenticationContext) -> None:
    record_audit_event(
        actor=actor,
        action=AuditAction.CREATED,
        target_type=AuditTargetType.LANGUAGE,
        target_public_id=NOT_VERSION_4,
        changes=[],
    )

    assert AuditEvent.objects.get().target_public_id == NOT_VERSION_4


def test_the_vocabulary_is_given_out_by_the_read_interface() -> None:
    from caipo.accounts import models

    assert selectors.AuditAction is models.AuditAction
    assert selectors.AuditTargetType is models.AuditTargetType
    assert selectors.AuditField is models.AuditField
    assert {"AuditAction", "AuditField", "AuditTargetType"} <= set(selectors.__all__)


# --- It decides nothing -------------------------------------------------------


def test_it_checks_no_permission(user_with_roles: UserFactory) -> None:
    """Whoever calls it has decided. A Reader holds nothing that writes anything."""
    for user in (user_with_roles(Role.READER), User.objects.create_user("test.no.role@caipo.test")):
        _update(signed_in(user), RENAMED)

    assert AuditEvent.objects.count() == 2


def test_it_does_not_ask_what_state_the_account_is_in() -> None:
    user = User.objects.create_user("test.disabled@caipo.test")
    User.objects.filter(pk=user.pk).update(status=AccountStatus.DISABLED)

    _update(signed_in(user), RENAMED)

    assert AuditEvent.objects.get().actor == user


def test_it_logs_nothing_and_so_no_value(
    actor: AuthenticationContext, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger="caipo"):
        _update(actor, RENAMED)
        with pytest.raises(AuditRecordError):
            _update(actor, AuditChange(AuditField.NAME_EN, "TEST same", "TEST same"))

    ours = [record for record in caplog.records if record.name.startswith("caipo")]
    assert ours == []
    assert "TEST" not in logged(caplog.records)


# --- What it refuses, having written nothing ----------------------------------


@pytest.mark.parametrize(
    "not_an_actor",
    [
        None,
        "test.actor@caipo.test",
        1,
        AnonymousUser(),
        User(email="test.unsaved@caipo.test"),
    ],
    ids=["nothing", "an address", "a number", "an anonymous visitor", "a bare account"],
)
def test_it_refuses_anything_that_is_not_a_context(not_an_actor: object) -> None:
    with pytest.raises(AuditRecordError, match="saved account"):
        _update(cast(AuthenticationContext, not_an_actor), RENAMED)

    assert _nothing_was_written()


def test_it_refuses_a_bare_account_that_is_saved(actor: AuthenticationContext) -> None:
    with pytest.raises(AuditRecordError, match="saved account"):
        _update(cast(AuthenticationContext, actor.user), RENAMED)

    assert _nothing_was_written()


@pytest.mark.parametrize(
    "user",
    [User(email="test.unsaved@caipo.test"), AnonymousUser(), None],
    ids=["an unsaved account", "an anonymous visitor", "nobody"],
)
def test_it_refuses_a_context_around_anything_but_a_saved_account(user: object) -> None:
    context = AuthenticationContext(cast(User, user), Assurance.PASSWORD_AUTHENTICATED)

    with pytest.raises(AuditRecordError, match="saved account"):
        _update(context, RENAMED)

    assert _nothing_was_written()


@pytest.mark.parametrize("action", ["deleted", "CREATED", "", "read", None, 1])
def test_it_refuses_an_unknown_action(actor: AuthenticationContext, action: object) -> None:
    with pytest.raises(AuditRecordError, match="action"):
        record_audit_event(
            actor=actor,
            action=cast(AuditAction, action),
            target_type=AuditTargetType.COUNTRY,
            target_public_id=TARGET,
            changes=[],
        )

    assert _nothing_was_written()


@pytest.mark.parametrize(
    "target_type", ["country", "registry.source", "accounts.user", "", None, 1]
)
def test_it_refuses_an_unknown_target_type(
    actor: AuthenticationContext, target_type: object
) -> None:
    with pytest.raises(AuditRecordError, match="target type"):
        record_audit_event(
            actor=actor,
            action=AuditAction.CREATED,
            target_type=cast(AuditTargetType, target_type),
            target_public_id=TARGET,
            changes=[],
        )

    assert _nothing_was_written()


@pytest.mark.parametrize(
    ("action", "target_type"),
    [
        (AuditAction.DEACTIVATED, AuditTargetType.INSTITUTION),
        (AuditAction.DEACTIVATED, AuditTargetType.INSTITUTION_NAME),
        (AuditAction.REACTIVATED, AuditTargetType.INSTITUTION),
        (AuditAction.REACTIVATED, AuditTargetType.INSTITUTION_NAME),
        (AuditAction.MARKED_ENTERED_IN_ERROR, AuditTargetType.COUNTRY),
        (AuditAction.MARKED_ENTERED_IN_ERROR, AuditTargetType.LANGUAGE),
        (AuditAction.MARKED_ENTERED_IN_ERROR, AuditTargetType.INSTITUTION),
    ],
)
def test_it_refuses_an_action_that_does_not_apply_to_the_target_type(
    actor: AuthenticationContext, action: AuditAction, target_type: AuditTargetType
) -> None:
    with pytest.raises(AuditRecordError, match="does not apply"):
        record_audit_event(
            actor=actor,
            action=action,
            target_type=target_type,
            target_public_id=TARGET,
            changes=[],
        )

    assert _nothing_was_written()


@pytest.mark.parametrize(
    "identifier",
    [str(TARGET), TARGET.hex, TARGET.int, TARGET.bytes, "TEST-not-a-uuid", "", None],
    ids=["text", "hex", "integer", "bytes", "other text", "empty", "nothing"],
)
def test_it_refuses_a_target_that_is_not_a_uuid(
    actor: AuthenticationContext, identifier: object
) -> None:
    with pytest.raises(AuditRecordError, match="UUID"):
        record_audit_event(
            actor=actor,
            action=AuditAction.CREATED,
            target_type=AuditTargetType.COUNTRY,
            target_public_id=cast(uuid.UUID, identifier),
            changes=[],
        )

    assert _nothing_was_written()


def test_it_refuses_an_update_that_records_no_change(actor: AuthenticationContext) -> None:
    with pytest.raises(AuditRecordError, match="what changed"):
        _update(actor)

    assert _nothing_was_written()


@pytest.mark.parametrize(
    ("action", "target_type"),
    [
        (AuditAction.CREATED, AuditTargetType.COUNTRY),
        (AuditAction.DEACTIVATED, AuditTargetType.COUNTRY),
        (AuditAction.REACTIVATED, AuditTargetType.LANGUAGE),
        (AuditAction.MARKED_ENTERED_IN_ERROR, AuditTargetType.INSTITUTION_NAME),
    ],
)
def test_it_refuses_changes_on_anything_but_an_update(
    actor: AuthenticationContext, action: AuditAction, target_type: AuditTargetType
) -> None:
    with pytest.raises(AuditRecordError, match="what changed"):
        record_audit_event(
            actor=actor,
            action=action,
            target_type=target_type,
            target_public_id=TARGET,
            changes=[RENAMED],
        )

    assert _nothing_was_written()


@pytest.mark.parametrize("field", ["text", "code", "reason", "NAME_EN", "", None])
def test_it_refuses_an_unknown_field(actor: AuthenticationContext, field: object) -> None:
    with pytest.raises(AuditRecordError, match="field"):
        _update(actor, RENAMED, AuditChange(cast(AuditField, field), "TEST a", "TEST b"))

    assert _nothing_was_written()


@pytest.mark.parametrize(
    "not_a_change",
    [("name_en", "TEST a", "TEST b"), {"field": "name_en", "old": "TEST a", "new": "TEST b"}, None],
    ids=["a tuple", "a mapping", "nothing"],
)
def test_it_refuses_a_change_of_any_other_shape(
    actor: AuthenticationContext, not_a_change: object
) -> None:
    with pytest.raises(AuditRecordError, match="field"):
        _update(actor, cast(AuditChange, not_a_change))

    assert _nothing_was_written()


def test_it_refuses_a_field_given_twice(actor: AuthenticationContext) -> None:
    with pytest.raises(AuditRecordError, match="once"):
        _update(actor, RENAMED, AuditChange(AuditField.NAME_EN, "TEST new name", "TEST newer"))

    assert _nothing_was_written()


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("TEST same", "TEST same"),
        (None, None),
        (None, ""),
        (date(2001, 2, 3), date(2001, 2, 3)),
        (date(2001, 2, 3), "2001-02-03"),
        (REFERRED_TO, REFERRED_TO),
    ],
)
def test_it_refuses_a_change_whose_renderings_are_equal(
    actor: AuthenticationContext, old: services.AuditValue, new: services.AuditValue
) -> None:
    with pytest.raises(AuditRecordError, match="different"):
        _update(actor, AuditChange(AuditField.VALID_FROM, old, new))

    assert _nothing_was_written()


@pytest.mark.parametrize(
    "value",
    [
        1,
        1.5,
        True,
        b"TEST bytes",
        ["TEST"],
        {"TEST": "TEST"},
        datetime(2001, 2, 3, 4, 5, tzinfo=UTC),
    ],
    ids=["integer", "float", "boolean", "bytes", "list", "mapping", "date and time"],
)
@pytest.mark.parametrize("side", ["old", "new"])
def test_it_refuses_a_value_of_no_permitted_kind(
    actor: AuthenticationContext, value: object, side: str
) -> None:
    typed = cast(Any, value)
    change = (
        AuditChange(AuditField.NAME_EN, typed, "TEST b")
        if side == "old"
        else AuditChange(AuditField.NAME_EN, "TEST a", typed)
    )

    with pytest.raises(AuditRecordError, match="text, a date, a UUID, or nothing"):
        _update(actor, change)

    assert _nothing_was_written()


@pytest.mark.parametrize("side", ["old", "new"])
def test_it_refuses_a_value_that_is_too_long_and_shortens_nothing(
    actor: AuthenticationContext, side: str
) -> None:
    too_long = "T" * 201
    change = (
        AuditChange(AuditField.NAME_EN, too_long, "TEST b")
        if side == "old"
        else AuditChange(AuditField.NAME_EN, "TEST a", too_long)
    )

    with pytest.raises(AuditRecordError, match="too long"):
        _update(actor, change)

    assert _nothing_was_written()


def test_one_bad_change_among_good_ones_writes_none_of_them(actor: AuthenticationContext) -> None:
    with pytest.raises(AuditRecordError):
        _update(
            actor,
            AuditChange(AuditField.KIND, "TEST kind a", "TEST kind b"),
            AuditChange(AuditField.VALID_FROM, None, date(2001, 2, 3)),
            AuditChange(AuditField.NAME_EN, "TEST a", "T" * 201),
        )

    assert _nothing_was_written()


# --- The transaction ----------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_it_refuses_to_run_outside_a_transaction(actor: AuthenticationContext) -> None:
    with pytest.raises(AuditRecordError, match="inside the transaction"):
        _update(actor, RENAMED)
    with pytest.raises(AuditRecordError, match="inside the transaction"):
        record_audit_event(
            actor=actor,
            action=AuditAction.CREATED,
            target_type=AuditTargetType.COUNTRY,
            target_public_id=TARGET,
            changes=[],
        )

    assert _nothing_was_written()


@pytest.mark.django_db(transaction=True)
def test_outside_a_transaction_nothing_else_is_looked_at() -> None:
    """The refusal comes first, so an event can never be written by itself."""
    with pytest.raises(AuditRecordError, match="inside the transaction"):
        record_audit_event(
            actor=cast(AuthenticationContext, None),
            action=cast(AuditAction, "deleted"),
            target_type=cast(AuditTargetType, "accounts.user"),
            target_public_id=cast(uuid.UUID, None),
            changes=[],
        )


@pytest.mark.django_db(transaction=True)
def test_what_it_wrote_is_committed_with_the_transaction_it_was_called_in(
    actor: AuthenticationContext,
) -> None:
    with transaction.atomic():
        changed = User.objects.create_user("test.changed@caipo.test")
        _update(actor, RENAMED)

    assert User.objects.filter(pk=changed.pk).exists()
    assert AuditEvent.objects.count() == 1
    assert _stored_changes() == {"name_en": ("TEST old name", "TEST new name")}


@pytest.mark.django_db(transaction=True)
def test_it_opens_no_transaction_of_its_own(actor: AuthenticationContext) -> None:
    """What it wrote goes when the transaction it was called in is rolled back."""

    class ChangeFailed(Exception):
        pass

    with pytest.raises(ChangeFailed), transaction.atomic():
        _update(actor, RENAMED)
        raise ChangeFailed

    assert _nothing_was_written()


@pytest.mark.django_db(transaction=True)
def test_a_refusal_ends_the_change_it_was_called_for(actor: AuthenticationContext) -> None:
    with pytest.raises(AuditRecordError), transaction.atomic():
        User.objects.create_user("test.changed@caipo.test")
        _update(actor, AuditChange(AuditField.NAME_EN, "TEST a", "T" * 201))

    assert not User.objects.filter(email="test.changed@caipo.test").exists()
    assert _nothing_was_written()


@pytest.mark.django_db(transaction=True)
def test_an_actor_that_is_no_account_fails_the_whole_transaction() -> None:
    """The database decides this one: the writer does not look the account up."""
    nobody = AuthenticationContext(
        User(pk=2_000_000_000, email="test.nobody@caipo.test"), Assurance.PASSWORD_AUTHENTICATED
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user("test.changed@caipo.test")
        _update(nobody, RENAMED)

    assert not User.objects.filter(email="test.changed@caipo.test").exists()
    assert _nothing_was_written()


@pytest.mark.django_db(transaction=True)
def test_a_failed_write_cannot_be_caught_and_the_change_committed_without_it(
    actor: AuthenticationContext,
) -> None:
    """The event is inserted, and the change record then fails before it
    reaches the database: PostgreSQL text holds no NUL. A caller that
    swallowed the error would otherwise commit its change with half a record.
    """
    caught: list[Exception] = []

    with pytest.raises(transaction.TransactionManagementError), transaction.atomic():
        User.objects.create_user("test.changed@caipo.test")
        try:
            _update(actor, AuditChange(AuditField.NAME_EN, "TEST a", "TEST \x00 b"))
        except DataError as error:
            caught.append(error)
        # What a service would go on to do.
        User.objects.count()

    assert len(caught) == 1
    assert not User.objects.filter(email="test.changed@caipo.test").exists()
    assert _nothing_was_written()


@pytest.mark.django_db(transaction=True)
def test_a_failed_write_that_is_swallowed_to_the_end_still_commits_nothing(
    actor: AuthenticationContext,
) -> None:
    with transaction.atomic():
        User.objects.create_user("test.changed@caipo.test")
        try:
            _update(actor, AuditChange(AuditField.NAME_EN, "TEST a", "TEST \x00 b"))
        except DataError:
            pass

    assert not User.objects.filter(email="test.changed@caipo.test").exists()
    assert _nothing_was_written()
