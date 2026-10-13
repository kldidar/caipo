"""Countries and languages used at the same time, on separate database connections
(ADR-0018 points 6, 7, and 41 to 43; ADR-0019, supplementary tests of Increment 2).

Two creations with the same identity: the database keeps the code unique,
one is stored with one audit event, and the other raises the service's
explicit error and leaves nothing. Two identical changes to one record: the
row lock admits one, and the other is refused as a change that changes
nothing. Nothing is retried.

These are integrity tests of Country and Language. They are not ADR-0018's
testing requirement 8, which is about cycles among institutions and belongs
to Increment 3 in full.

These tests commit their data, because other connections must see it, and
the database is emptied after each of them.
"""

import threading
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from django.db import connections, transaction

from caipo.accounts.selectors import AuthenticationContext, Role
from caipo.registry import services
from caipo.registry.models import Country, Language
from caipo.registry.services import DuplicateCodeError, NoChangeError
from caipo.registry.tests.helpers import ActingAs, changes, events

pytestmark = [pytest.mark.services, pytest.mark.django_db(transaction=True)]

WAIT_SECONDS = 20
# Enough repetitions that a service which only looked before it wrote, and
# did not rely on the database or on the lock, would be caught.
ROUNDS = 5


@pytest.fixture
def administrators(acting_as: ActingAs) -> tuple[AuthenticationContext, AuthenticationContext]:
    """Return two Administrators, so that an event shows which of two attempts made it."""
    return (
        acting_as(Role.ADMINISTRATOR, second_factor=True),
        acting_as(Role.ADMINISTRATOR, second_factor=True),
    )


def _together(first: Callable[[], object], second: Callable[[], object]) -> list[object]:
    """Run two operations at once, each on its own connection, and return what each did.

    What an operation raised is returned in place of its result, to be
    asserted on by the test, and is never hidden.
    """
    barrier = threading.Barrier(2)
    outcomes: list[object] = [None, None]

    def run(position: int, operation: Callable[[], object]) -> None:
        try:
            barrier.wait(timeout=WAIT_SECONDS)
            outcomes[position] = operation()
        except Exception as error:  # recorded and asserted on by the test, not hidden
            outcomes[position] = error
        finally:
            connections.close_all()

    threads = [
        threading.Thread(target=run, args=(position, operation))
        for position, operation in enumerate((first, second))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=WAIT_SECONDS)
        assert not thread.is_alive(), "an operation did not finish"
    return outcomes


def _one_of_each(outcomes: list[object], refusal: type[Exception]) -> int:
    """Check that one operation succeeded and the other was refused; return which succeeded."""
    refused = [isinstance(outcome, refusal) for outcome in outcomes]
    assert sorted(refused) == [False, True], outcomes
    winner = refused.index(False)
    assert not isinstance(outcomes[winner], Exception), outcomes
    return winner


# --- Simultaneous creation with the same identity -----------------------------


@pytest.mark.parametrize(
    ("first_codes", "second_codes"),
    [
        (("XA", "XAA"), ("XA", "XBB")),
        (("XA", "XAA"), ("XB", "XAA")),
        (("XA", "XAA"), ("XA", "XAA")),
    ],
    ids=["same-alpha2", "same-alpha3", "same-both"],
)
@pytest.mark.parametrize("round_number", range(ROUNDS))
def test_two_countries_created_at_once_with_a_code_in_common_leave_one(
    administrators: tuple[AuthenticationContext, AuthenticationContext],
    first_codes: tuple[str, str],
    second_codes: tuple[str, str],
    round_number: int,
) -> None:
    attempts = [(administrators[0], first_codes), (administrators[1], second_codes)]

    outcomes = _together(
        *(
            lambda actor=actor, codes=codes: services.create_country(
                actor=actor, alpha2=codes[0], alpha3=codes[1], name_en="TEST Country"
            )
            for actor, codes in attempts
        )
    )

    winner = _one_of_each(outcomes, DuplicateCodeError)
    actor, codes = attempts[winner]
    country = Country.objects.get()
    assert (country.alpha2, country.alpha3) == codes
    assert country.public_id == outcomes[winner]
    assert events() == [("created", "registry.country", country.public_id, actor.user.pk)]
    assert changes() == []


@pytest.mark.parametrize("round_number", range(ROUNDS))
def test_two_languages_created_at_once_with_the_same_pair_of_codes_leave_one(
    administrators: tuple[AuthenticationContext, AuthenticationContext], round_number: int
) -> None:
    outcomes = _together(
        *(
            lambda actor=actor: services.create_language(
                actor=actor, code="qaa", script_code="Qaaa", name_en="TEST Language"
            )
            for actor in administrators
        )
    )

    winner = _one_of_each(outcomes, DuplicateCodeError)
    language = Language.objects.get()
    assert language.public_id == outcomes[winner]
    assert events() == [
        ("created", "registry.language", language.public_id, administrators[winner].user.pk)
    ]
    assert changes() == []


def test_two_languages_created_at_once_that_share_one_code_are_both_stored(
    administrators: tuple[AuthenticationContext, AuthenticationContext],
) -> None:
    """The pair is unique, not either code: nothing here is a duplicate."""
    outcomes = _together(
        lambda: services.create_language(
            actor=administrators[0], code="qaa", script_code="Qaaa", name_en="TEST Language"
        ),
        lambda: services.create_language(
            actor=administrators[1], code="qaa", script_code="Qaab", name_en="TEST Language"
        ),
    )

    assert all(isinstance(outcome, uuid.UUID) for outcome in outcomes), outcomes
    assert Language.objects.count() == 2
    assert len(events()) == 2


def _held_then(
    held: Callable[[], object], follower: Callable[[], object], *, commit: bool
) -> tuple[list[object], list[object]]:
    """Run one creation in a transaction that stays open while another is attempted.

    Returns what the transaction that was held did and what the one that
    followed it did. The one held is committed or rolled back only after the
    other has been seen to wait: so the other could not have decided on a
    look at the table, and was decided by the database.
    """

    class RolledBack(Exception):
        pass

    holding = threading.Event()
    release = threading.Event()
    held_outcome: list[object] = []
    follower_outcome: list[object] = []

    def hold() -> None:
        try:
            with transaction.atomic():
                held_outcome.append(held())
                holding.set()
                assert release.wait(timeout=WAIT_SECONDS)
                if not commit:
                    raise RolledBack
        except RolledBack:
            held_outcome.append(None)
        except Exception as error:  # recorded and asserted on by the test, not hidden
            held_outcome.append(error)
        finally:
            connections.close_all()

    def follow() -> None:
        try:
            follower_outcome.append(follower())
        except Exception as error:  # recorded and asserted on by the test, not hidden
            follower_outcome.append(error)
        finally:
            connections.close_all()

    first = threading.Thread(target=hold)
    second = threading.Thread(target=follow)
    first.start()
    try:
        assert holding.wait(timeout=WAIT_SECONDS), held_outcome
        second.start()
        second.join(timeout=1)
        # It has decided nothing yet: the database makes it wait for the other.
        assert second.is_alive() and follower_outcome == []
    finally:
        release.set()
        first.join(timeout=WAIT_SECONDS)
        second.join(timeout=WAIT_SECONDS)
    return held_outcome, follower_outcome


CREATIONS_IN_CONFLICT = [
    pytest.param(
        lambda actor: services.create_country(
            actor=actor, alpha2="XA", alpha3="XAA", name_en="TEST Country"
        ),
        lambda actor: services.create_country(
            actor=actor, alpha2="XA", alpha3="XBB", name_en="TEST Country"
        ),
        Country,
        id="country-same-alpha2",
    ),
    pytest.param(
        lambda actor: services.create_country(
            actor=actor, alpha2="XA", alpha3="XAA", name_en="TEST Country"
        ),
        lambda actor: services.create_country(
            actor=actor, alpha2="XB", alpha3="XAA", name_en="TEST Country"
        ),
        Country,
        id="country-same-alpha3",
    ),
    pytest.param(
        lambda actor: services.create_language(
            actor=actor, code="qaa", script_code="Qaaa", name_en="TEST Language"
        ),
        lambda actor: services.create_language(
            actor=actor, code="qaa", script_code="Qaaa", name_en="TEST Language"
        ),
        Language,
        id="language-same-pair",
    ),
]


@pytest.mark.parametrize(("first", "second", "model"), CREATIONS_IN_CONFLICT)
def test_a_creation_that_meets_an_uncommitted_one_waits_and_is_refused_when_that_one_commits(
    administrators: tuple[AuthenticationContext, AuthenticationContext],
    first: Callable[[AuthenticationContext], uuid.UUID],
    second: Callable[[AuthenticationContext], uuid.UUID],
    model: Any,
) -> None:
    """The second cannot see the first's row, so only the database can refuse it."""
    held, follower = _held_then(
        lambda: first(administrators[0]), lambda: second(administrators[1]), commit=True
    )

    assert len(follower) == 1 and isinstance(follower[0], DuplicateCodeError), follower
    record = model.objects.get()
    assert held == [record.public_id]
    assert [(action, target, actor) for action, _, target, actor in events()] == [
        ("created", record.public_id, administrators[0].user.pk)
    ]


@pytest.mark.parametrize(("first", "second", "model"), CREATIONS_IN_CONFLICT)
def test_a_creation_that_meets_an_uncommitted_one_is_made_when_that_one_is_rolled_back(
    administrators: tuple[AuthenticationContext, AuthenticationContext],
    first: Callable[[AuthenticationContext], uuid.UUID],
    second: Callable[[AuthenticationContext], uuid.UUID],
    model: Any,
) -> None:
    """Neither attempt is repeated: the one that waited is simply let through."""
    held, follower = _held_then(
        lambda: first(administrators[0]), lambda: second(administrators[1]), commit=False
    )

    record = model.objects.get()
    assert follower == [record.public_id]
    assert held[0] != record.public_id
    assert [(action, target, actor) for action, _, target, actor in events()] == [
        ("created", record.public_id, administrators[1].user.pk)
    ]


# --- Simultaneous operations on one record ------------------------------------


def _record(model: Any, actor: AuthenticationContext) -> uuid.UUID:
    if model is Country:
        return services.create_country(
            actor=actor, alpha2="XA", alpha3="XAA", name_en="TEST Old name"
        )
    return services.create_language(
        actor=actor, code="qaa", script_code="Qaaa", name_en="TEST Old name"
    )


KINDS = [
    pytest.param(
        Country,
        "registry.country",
        services.rename_country,
        services.deactivate_country,
        services.reactivate_country,
        id="country",
    ),
    pytest.param(
        Language,
        "registry.language",
        services.rename_language,
        services.deactivate_language,
        services.reactivate_language,
        id="language",
    ),
]
KIND = ("model", "target_type", "rename", "deactivate", "reactivate")


@pytest.mark.parametrize(KIND, KINDS)
@pytest.mark.parametrize("round_number", range(ROUNDS))
def test_the_same_rename_made_twice_at_once_is_made_once(
    administrators: tuple[AuthenticationContext, AuthenticationContext],
    model: Any,
    target_type: str,
    rename: Callable[..., None],
    deactivate: Callable[..., None],
    reactivate: Callable[..., None],
    round_number: int,
) -> None:
    public_id = _record(model, administrators[0])

    outcomes = _together(
        *(
            lambda actor=actor: rename(actor=actor, public_id=public_id, name_en="TEST New name")
            for actor in administrators
        )
    )

    winner = _one_of_each(outcomes, NoChangeError)
    assert model.objects.get().name_en == "TEST New name"
    assert events()[1:] == [("updated", target_type, public_id, administrators[winner].user.pk)]
    assert [(field, old, new) for _, field, old, new in changes()] == [
        ("name_en", "TEST Old name", "TEST New name")
    ]


@pytest.mark.parametrize(KIND, KINDS)
@pytest.mark.parametrize("round_number", range(ROUNDS))
def test_two_deactivations_at_once_deactivate_once(
    administrators: tuple[AuthenticationContext, AuthenticationContext],
    model: Any,
    target_type: str,
    rename: Callable[..., None],
    deactivate: Callable[..., None],
    reactivate: Callable[..., None],
    round_number: int,
) -> None:
    public_id = _record(model, administrators[0])

    outcomes = _together(
        *(
            lambda actor=actor: deactivate(actor=actor, public_id=public_id)
            for actor in administrators
        )
    )

    winner = _one_of_each(outcomes, NoChangeError)
    assert not model.objects.get().is_active
    assert events()[1:] == [("deactivated", target_type, public_id, administrators[winner].user.pk)]
    assert changes() == []


@pytest.mark.parametrize(KIND, KINDS)
@pytest.mark.parametrize("round_number", range(ROUNDS))
def test_two_reactivations_at_once_reactivate_once(
    administrators: tuple[AuthenticationContext, AuthenticationContext],
    model: Any,
    target_type: str,
    rename: Callable[..., None],
    deactivate: Callable[..., None],
    reactivate: Callable[..., None],
    round_number: int,
) -> None:
    public_id = _record(model, administrators[0])
    deactivate(actor=administrators[0], public_id=public_id)

    outcomes = _together(
        *(
            lambda actor=actor: reactivate(actor=actor, public_id=public_id)
            for actor in administrators
        )
    )

    winner = _one_of_each(outcomes, NoChangeError)
    assert model.objects.get().is_active
    assert events()[2:] == [("reactivated", target_type, public_id, administrators[winner].user.pk)]
    assert changes() == []


@pytest.mark.parametrize(KIND, KINDS)
def test_a_change_waits_for_another_that_holds_the_record_and_then_decides_on_what_it_left(
    administrators: tuple[AuthenticationContext, AuthenticationContext],
    model: Any,
    target_type: str,
    rename: Callable[..., None],
    deactivate: Callable[..., None],
    reactivate: Callable[..., None],
) -> None:
    """The row lock in the open: one transaction holds the record while another asks for it."""
    public_id = _record(model, administrators[0])
    holding = threading.Event()
    release = threading.Event()
    outcomes: list[object] = []

    def hold() -> None:
        try:
            with transaction.atomic():
                deactivate(actor=administrators[0], public_id=public_id)
                holding.set()
                assert release.wait(timeout=WAIT_SECONDS)
        except Exception as error:  # recorded and asserted on by the test, not hidden
            outcomes.append(error)
        finally:
            connections.close_all()

    def follow() -> None:
        try:
            deactivate(actor=administrators[1], public_id=public_id)
            outcomes.append(None)
        except Exception as error:  # recorded and asserted on by the test, not hidden
            outcomes.append(error)
        finally:
            connections.close_all()

    holder = threading.Thread(target=hold)
    follower = threading.Thread(target=follow)
    holder.start()
    try:
        assert holding.wait(timeout=WAIT_SECONDS), outcomes
        follower.start()
        follower.join(timeout=1)
        # It has decided nothing yet: it waits for the record.
        assert follower.is_alive() and outcomes == []
    finally:
        release.set()
        holder.join(timeout=WAIT_SECONDS)
        follower.join(timeout=WAIT_SECONDS)

    assert len(outcomes) == 1 and isinstance(outcomes[0], NoChangeError), outcomes
    assert events()[1:] == [("deactivated", target_type, public_id, administrators[0].user.pk)]
