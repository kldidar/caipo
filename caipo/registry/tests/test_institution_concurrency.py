"""Institutions and names changed at the same time, on separate database connections
(ADR-0018 points 20, 22, and 23; testing requirement 8; the owner decision of
2026-10-20 that extends point 23).

Requirement 8 in full: two simultaneous changes that would together form a
cycle, of parents or of successors, and one of them is refused. The
succession lock admits one such change at a time, so the second decides on
what the first left. The same lock serializes the changes of valid-to dates
on which the rule of a successor's dates depends, and the lock on an
institution's row serializes the marking of its names, so that two such
changes made at once cannot together break a rule that each keeps alone.
Nothing is retried.

These tests commit their data, because other connections must see it, and
the database is emptied after each of them.
"""

import threading
import uuid
from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from django.db import connections, transaction

from caipo.accounts.selectors import AuthenticationContext, Role
from caipo.registry import services
from caipo.registry.models import Institution, InstitutionName
from caipo.registry.services import CycleError, LastNameError, NewName, SuccessionError
from caipo.registry.tests.helpers import ActingAs, events, institution, names_of
from caipo.registry.tests.test_concurrency import ROUNDS, WAIT_SECONDS, _one_of_each, _together

pytestmark = [pytest.mark.services, pytest.mark.django_db(transaction=True)]

D1, D2, D3 = date(2001, 2, 3), date(2002, 3, 4), date(2003, 4, 5)


@pytest.fixture
def researchers(acting_as: ActingAs) -> tuple[AuthenticationContext, AuthenticationContext]:
    """Return two Researchers, so that an event shows which of two attempts made it."""
    return acting_as(Role.RESEARCHER), acting_as(Role.RESEARCHER)


@pytest.fixture
def language(administrator: AuthenticationContext) -> uuid.UUID:
    return services.create_language(
        actor=administrator, code="qaa", script_code="Qaaa", name_en="TEST Language A"
    )


def _change(actor: AuthenticationContext, public_id: uuid.UUID, **values: Any) -> None:
    """Change an institution to what it is, with the values given changed."""
    current = Institution.objects.get(public_id=public_id)
    reference = {
        field: getattr(getattr(current, field), "public_id", None)
        for field in ("country", "parent", "successor")
    }
    services.change_institution(
        actor=actor,
        public_id=public_id,
        **{
            "kind": current.kind,
            **reference,
            "valid_from": current.valid_from,
            "valid_to": current.valid_to,
            **values,
        },
    )


def _updates(*public_ids: uuid.UUID) -> list[tuple[uuid.UUID, int]]:
    return [
        (target, actor)
        for action, _, target, actor in events()
        if action == "updated" and target in public_ids
    ]


# --- Requirement 8: two changes that would together form a cycle ---------------


@pytest.mark.parametrize("round_number", range(ROUNDS))
def test_two_changes_at_once_that_would_make_a_cycle_of_parents_leave_one(
    researchers: tuple[AuthenticationContext, AuthenticationContext],
    language: uuid.UUID,
    round_number: int,
) -> None:
    first = institution(researchers[0], language, "TEST First")
    second = institution(researchers[0], language, "TEST Second")

    outcomes = _together(
        lambda: _change(researchers[0], first, parent=second),
        lambda: _change(researchers[1], second, parent=first),
    )

    winner = _one_of_each(outcomes, CycleError)
    parents = dict(Institution.objects.values_list("public_id", "parent__public_id"))
    expected = {first: second, second: None} if winner == 0 else {first: None, second: first}
    assert parents == expected
    assert _updates(first, second) == [
        (first, researchers[0].user.pk) if winner == 0 else (second, researchers[1].user.pk)
    ]


@pytest.mark.parametrize("round_number", range(ROUNDS))
def test_two_changes_at_once_that_would_make_a_cycle_of_successors_leave_one(
    researchers: tuple[AuthenticationContext, AuthenticationContext],
    language: uuid.UUID,
    round_number: int,
) -> None:
    """Both ended on the same day, so that only the cycle stands in the way."""
    first = institution(researchers[0], language, "TEST First", valid_to=D1)
    second = institution(researchers[0], language, "TEST Second", valid_to=D1)

    outcomes = _together(
        lambda: _change(researchers[0], first, successor=second),
        lambda: _change(researchers[1], second, successor=first),
    )

    winner = _one_of_each(outcomes, CycleError)
    successors = dict(Institution.objects.values_list("public_id", "successor__public_id"))
    assert successors == (
        {first: second, second: None} if winner == 0 else {first: None, second: first}
    )
    assert len(_updates(first, second)) == 1


@pytest.mark.parametrize("round_number", range(ROUNDS))
def test_two_changes_at_once_that_would_close_a_longer_cycle_leave_one(
    researchers: tuple[AuthenticationContext, AuthenticationContext],
    language: uuid.UUID,
    round_number: int,
) -> None:
    """With C under B already, B under A and A under C would close A, C, B."""
    a = institution(researchers[0], language, "TEST A")
    b = institution(researchers[0], language, "TEST B")
    c = institution(researchers[0], language, "TEST C", parent=b)

    outcomes = _together(
        lambda: _change(researchers[0], b, parent=a),
        lambda: _change(researchers[1], a, parent=c),
    )

    _one_of_each(outcomes, CycleError)
    parents = dict(Institution.objects.values_list("public_id", "parent__public_id"))
    assert parents[c] == b
    assert (parents[b], parents[a]) in {(a, None), (None, c)}


def _held_then(
    held: Callable[[], object], follower: Callable[[], object], *, commit: bool
) -> tuple[list[object], list[object]]:
    """Run one change in a transaction that stays open while another is attempted.

    The one held is committed or rolled back only after the other has been
    seen to wait, so the other cannot have decided on what it read before.
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
        # It has decided nothing yet: the lock makes it wait for the other.
        assert second.is_alive() and follower_outcome == []
    finally:
        release.set()
        first.join(timeout=WAIT_SECONDS)
        second.join(timeout=WAIT_SECONDS)
    assert not first.is_alive() and not second.is_alive(), "an operation did not finish"
    return held_outcome, follower_outcome


def test_a_change_of_parent_waits_for_another_and_is_refused_on_the_cycle_it_left(
    researchers: tuple[AuthenticationContext, AuthenticationContext], language: uuid.UUID
) -> None:
    """Two different rows: only the succession lock, and no row lock, makes the second wait."""
    first = institution(researchers[0], language, "TEST First")
    second = institution(researchers[0], language, "TEST Second")

    held, follower = _held_then(
        lambda: _change(researchers[0], first, parent=second),
        lambda: _change(researchers[1], second, parent=first),
        commit=True,
    )

    assert held == [None]
    assert len(follower) == 1 and isinstance(follower[0], CycleError), follower
    assert _updates(first, second) == [(first, researchers[0].user.pk)]


def test_a_change_of_parent_that_waited_is_made_when_the_other_is_rolled_back(
    researchers: tuple[AuthenticationContext, AuthenticationContext], language: uuid.UUID
) -> None:
    first = institution(researchers[0], language, "TEST First")
    second = institution(researchers[0], language, "TEST Second")

    held, follower = _held_then(
        lambda: _change(researchers[0], first, parent=second),
        lambda: _change(researchers[1], second, parent=first),
        commit=False,
    )

    assert follower == [None]
    assert dict(Institution.objects.values_list("public_id", "parent__public_id")) == {
        first: None,
        second: first,
    }
    assert _updates(first, second) == [(second, researchers[1].user.pk)]


# --- The dates of a successor (owner decision of 2026-10-20) -------------------


@pytest.mark.parametrize("round_number", range(ROUNDS))
def test_two_changes_of_end_dates_at_once_cannot_make_a_successor_end_first(
    researchers: tuple[AuthenticationContext, AuthenticationContext],
    language: uuid.UUID,
    round_number: int,
) -> None:
    """Each is allowed alone; made together, the successor would end before its predecessor."""
    successor = institution(researchers[0], language, "TEST Successor", valid_to=D3)
    predecessor = institution(
        researchers[0], language, "TEST Predecessor", valid_to=D2, successor=successor
    )

    outcomes = _together(
        lambda: _change(researchers[0], predecessor, valid_to=D3),
        lambda: _change(researchers[1], successor, valid_to=D2),
    )

    _one_of_each(outcomes, SuccessionError)
    ends = dict(Institution.objects.values_list("public_id", "valid_to"))
    successor_ends, predecessor_ends = ends[successor], ends[predecessor]
    assert successor_ends is not None and predecessor_ends is not None
    assert successor_ends >= predecessor_ends
    assert len(_updates(successor, predecessor)) == 1


@pytest.mark.parametrize("round_number", range(ROUNDS))
def test_a_successor_named_while_its_end_moves_earlier_is_checked_against_the_new_end(
    researchers: tuple[AuthenticationContext, AuthenticationContext],
    language: uuid.UUID,
    round_number: int,
) -> None:
    """A creation that names a successor takes the same lock as a change of its end."""
    successor = institution(researchers[0], language, "TEST Successor", valid_to=D3)

    outcomes = _together(
        lambda: institution(
            researchers[0], language, "TEST Predecessor", valid_to=D2, successor=successor
        ),
        lambda: _change(researchers[1], successor, valid_to=D1),
    )

    _one_of_each(outcomes, SuccessionError)
    assert not Institution.objects.filter(
        successor__public_id=successor, successor__valid_to__lt=D2
    ).exists()


# --- The last unmarked name (owner decision of 2026-10-20) ---------------------


@pytest.mark.parametrize("round_number", range(ROUNDS))
def test_two_names_of_one_institution_marked_at_once_leave_one_unmarked(
    researchers: tuple[AuthenticationContext, AuthenticationContext],
    language: uuid.UUID,
    round_number: int,
) -> None:
    public_id = institution(researchers[0], language, "TEST First name")
    services.add_institution_name(
        actor=researchers[0],
        institution=public_id,
        name=NewName(text="TEST Second name", language=language, kind="official"),
    )
    first, second = names_of(public_id)

    outcomes = _together(
        lambda: services.mark_institution_name_entered_in_error(
            actor=researchers[0], public_id=first
        ),
        lambda: services.mark_institution_name_entered_in_error(
            actor=researchers[1], public_id=second
        ),
    )

    _one_of_each(outcomes, LastNameError)
    assert InstitutionName.objects.filter(entered_in_error=False).count() == 1
    assert [action for action, _, _, _ in events()].count("marked_entered_in_error") == 1


# --- The locks do not wait on each other in a circle ---------------------------


def test_a_change_of_succession_and_a_creation_that_refers_to_its_institution_both_complete(
    researchers: tuple[AuthenticationContext, AuthenticationContext], language: uuid.UUID
) -> None:
    """The creation holds its insert while the change locks the parent's row and waits.

    The creation's reference to that row is checked when it commits. Were the
    row locked FOR UPDATE, that check would wait for the change, which waits
    for the creation: the two would deadlock. The row is locked FOR NO KEY
    UPDATE, which the check does not wait for.
    """
    parent = institution(researchers[0], language, "TEST Parent")
    other = institution(researchers[0], language, "TEST Other")

    held, follower = _held_then(
        lambda: institution(researchers[0], language, "TEST Child", parent=parent),
        lambda: _change(researchers[1], parent, parent=other),
        commit=True,
    )

    assert len(held) == 1 and isinstance(held[0], uuid.UUID), held
    assert follower == [None]
    parents = dict(Institution.objects.values_list("public_id", "parent__public_id"))
    assert parents[held[0]] == parent and parents[parent] == other


def test_a_name_added_while_its_institution_changes_succession_both_complete(
    researchers: tuple[AuthenticationContext, AuthenticationContext], language: uuid.UUID
) -> None:
    successor = institution(researchers[0], language, "TEST Successor")
    public_id = institution(researchers[0], language, "TEST Institution")

    held, follower = _held_then(
        lambda: _change(researchers[0], public_id, valid_to=D1, successor=successor),
        lambda: _change(researchers[1], successor, parent=public_id),
        commit=True,
    )
    added = services.add_institution_name(
        actor=researchers[1],
        institution=public_id,
        name=NewName(text="TEST Added", language=language, kind="official"),
    )

    assert held == [None] and follower == [None]
    assert names_of(public_id)[-1] == added
