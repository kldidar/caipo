"""The Institution and InstitutionName services: what they accept, refuse, store, and
record (ADR-0018 points 8 to 10, 13, 18 to 23, 35, and 41 to 43; testing requirements 7,
9, and 10; ADR-0019 Increment 3).

Who may call them is in test_institution_permissions.py, what the database
refuses by itself in test_institution_models.py, and what happens when two
are called at once in test_institution_concurrency.py.
"""

import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest
from django.db.models import F

from caipo.accounts.models import AuditEvent, AuditEventChange
from caipo.accounts.selectors import AuthenticationContext, Role
from caipo.core.correlation import correlation_scope
from caipo.registry import selectors, services
from caipo.registry.models import Institution, InstitutionName
from caipo.registry.services import (
    CycleError,
    DeactivatedReferenceError,
    InvalidEntryError,
    LastNameError,
    NewName,
    NoChangeError,
    RecordNotFoundError,
    SuccessionError,
)
from caipo.registry.tests.helpers import (
    COUNTRIES,
    UNKNOWN,
    ActingAs,
    events,
    institution,
    names_of,
    reference_records,
    stored_with_institutions,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db]

D1, D2, D3, D4 = date(2001, 2, 3), date(2002, 3, 4), date(2003, 4, 5), date(2004, 5, 6)
NOT_A_DATE: list[Any] = ["2001-02-03", datetime(2001, 2, 3, tzinfo=UTC), 20010203, (2001, 2, 3)]
NOT_AN_IDENTIFIER: list[Any] = [str(UNKNOWN), 1, b"x"]
BAD_TEXTS: list[Any] = [
    "", " ", "\t\n ", "T" * 501, "TEST \x00 name", None, 1, b"TEST",
]  # fmt: skip


class Records:
    """Three countries and three languages, all active, entered by an Administrator."""

    def __init__(self, actor: AuthenticationContext) -> None:
        self.countries, self.languages = reference_records(actor)
        self.country = self.countries[0]
        self.language = self.languages[0]


@pytest.fixture
def records(administrator: AuthenticationContext) -> Records:
    return Records(administrator)


@pytest.fixture
def researcher(acting_as: ActingAs) -> AuthenticationContext:
    """A Researcher on a password alone, who maintains institutions (ADR-0018 point 12)."""
    return acting_as(Role.RESEARCHER)


def _create(actor: AuthenticationContext, records: Records, **values: Any) -> uuid.UUID:
    return institution(actor, records.language, **values)


def _state(public_id: uuid.UUID) -> dict[str, Any]:
    """Return what is stored of an institution, its references by their public identifiers."""
    return dict(
        Institution.objects.filter(public_id=public_id)
        .values(
            "kind",
            "valid_from",
            "valid_to",
            country_public_id=F("country__public_id"),
            parent_public_id=F("parent__public_id"),
            successor_public_id=F("successor__public_id"),
        )
        .get()
    )


def _change(actor: AuthenticationContext, public_id: uuid.UUID, **values: Any) -> None:
    """Change an institution to what it is, with the values given changed."""
    current = _state(public_id)
    services.change_institution(
        actor=actor,
        public_id=public_id,
        **{
            "kind": current["kind"],
            "country": current["country_public_id"],
            "parent": current["parent_public_id"],
            "successor": current["successor_public_id"],
            "valid_from": current["valid_from"],
            "valid_to": current["valid_to"],
            **values,
        },
    )


def _entry(actor: AuthenticationContext, public_id: uuid.UUID) -> selectors.InstitutionEntry:
    (entry,) = [each for each in selectors.institutions(actor) if each.public_id == public_id]
    return entry


# --- Creating an institution with its first name ------------------------------


def test_an_institution_is_created_together_with_its_first_name(
    researcher: AuthenticationContext, records: Records
) -> None:
    parent = _create(researcher, records, text="TEST Parent")
    successor = _create(researcher, records, text="TEST Successor", valid_to=D4)

    public_id = services.create_institution(
        actor=researcher,
        kind="regulator",
        country=records.country,
        parent=parent,
        successor=successor,
        valid_from=D1,
        valid_to=D3,
        first_name=NewName(
            text="TEST Regulator",
            language=records.languages[1],
            kind="abbreviation",
            valid_from=D1,
            valid_to=D2,
        ),
    )

    assert isinstance(public_id, uuid.UUID) and public_id.version == 4
    assert _state(public_id) == {
        "kind": "regulator",
        "valid_from": D1,
        "valid_to": D3,
        "country_public_id": records.country,
        "parent_public_id": parent,
        "successor_public_id": successor,
    }
    name = InstitutionName.objects.get(institution__public_id=public_id)
    assert (
        name.text,
        name.language.public_id,
        name.kind,
        name.valid_from,
        name.valid_to,
        name.entered_in_error,
    ) == ("TEST Regulator", records.languages[1], "abbreviation", D1, D2, False)
    assert events()[-2:] == [
        ("created", "registry.institution", public_id, researcher.user.pk),
        ("created", "registry.institution_name", name.public_id, researcher.user.pk),
    ]


def test_an_institution_needs_no_country_parent_successor_or_date(
    researcher: AuthenticationContext, records: Records
) -> None:
    """An international body has no country, and an unknown date is empty (points 8 and 21)."""
    public_id = services.create_institution(
        actor=researcher,
        kind="international_organisation",
        first_name=NewName(text="TEST Body", language=records.language, kind="official"),
    )

    assert _state(public_id) == {
        "kind": "international_organisation",
        "valid_from": None,
        "valid_to": None,
        "country_public_id": None,
        "parent_public_id": None,
        "successor_public_id": None,
    }


@pytest.mark.parametrize("kind", ["other", "", "Ministry", "ministry ", "official", None, 1])
def test_an_institution_of_a_kind_not_on_the_list_is_refused(
    researcher: AuthenticationContext, records: Records, kind: Any
) -> None:
    before = stored_with_institutions()

    with pytest.raises(InvalidEntryError):
        _create(researcher, records, kind=kind)

    assert stored_with_institutions() == before


@pytest.mark.parametrize("kind", ["other", "", "Official", "ministry", None])
def test_a_first_name_of_a_kind_not_on_the_list_is_refused(
    researcher: AuthenticationContext, records: Records, kind: Any
) -> None:
    before = stored_with_institutions()

    with pytest.raises(InvalidEntryError):
        services.create_institution(
            actor=researcher,
            kind="ministry",
            first_name=NewName(text="TEST Name", language=records.language, kind=kind),
        )

    assert stored_with_institutions() == before


@pytest.mark.parametrize("value", NOT_A_DATE)
@pytest.mark.parametrize("where", ["valid_from", "valid_to", "name_valid_from", "name_valid_to"])
def test_a_date_that_is_not_a_calendar_date_is_refused(
    researcher: AuthenticationContext, records: Records, where: str, value: Any
) -> None:
    """A date and time is not a date: no time of day stands for a day (point 21)."""
    before = stored_with_institutions()
    name: dict[str, Any] = {}
    attributes: dict[str, Any] = {}
    if where.startswith("name_"):
        name[where.removeprefix("name_")] = value
    else:
        attributes[where] = value

    with pytest.raises(InvalidEntryError):
        services.create_institution(
            actor=researcher,
            kind="ministry",
            first_name=NewName(
                text="TEST Name", language=records.language, kind="official", **name
            ),
            **attributes,
        )

    assert stored_with_institutions() == before


@pytest.mark.parametrize(("valid_from", "valid_to"), [(D1, D1), (D2, D1)])
@pytest.mark.parametrize("whose", ["institution", "name"])
def test_dates_that_are_not_in_order_are_refused(
    researcher: AuthenticationContext,
    records: Records,
    whose: str,
    valid_from: date,
    valid_to: date,
) -> None:
    """Half-open periods: valid-from is before valid-to where both are known (point 21)."""
    before = stored_with_institutions()
    dates: dict[str, Any] = {"valid_from": valid_from, "valid_to": valid_to}

    with pytest.raises(InvalidEntryError):
        services.create_institution(
            actor=researcher,
            kind="ministry",
            first_name=NewName(
                text="TEST Name",
                language=records.language,
                kind="official",
                **(dates if whose == "name" else {}),
            ),
            **(dates if whose == "institution" else {}),
        )

    assert stored_with_institutions() == before


@pytest.mark.parametrize("text", BAD_TEXTS)
def test_an_institution_with_no_usable_first_name_is_not_created(
    researcher: AuthenticationContext, records: Records, text: Any
) -> None:
    """Every institution has a name (point 20): without one it is not created at all."""
    before = stored_with_institutions()

    with pytest.raises(InvalidEntryError):
        _create(researcher, records, text=text)

    assert stored_with_institutions() == before


def test_a_first_name_that_is_not_a_new_name_is_refused(
    researcher: AuthenticationContext, records: Records
) -> None:
    with pytest.raises(InvalidEntryError):
        services.create_institution(
            actor=researcher,
            kind="ministry",
            first_name={"text": "TEST Name"},  # type: ignore[arg-type]  # the wrong type is the case under test
        )

    assert not Institution.objects.exists()


@pytest.mark.parametrize(
    ("entered", "stored"),
    [
        ("  TEST Name\n", "TEST Name"),
        ("TEST  Two   Spaces", "TEST  Two   Spaces"),
        ("test lower CASE", "test lower CASE"),
        # e followed by COMBINING ACUTE ACCENT, stored composed as one letter.
        ("TEST Métier", "TEST Métier"),
        # The composed letter is stored as it came.
        ("TEST Métier", "TEST Métier"),
        ("TEST Вазирлиги", "TEST Вазирлиги"),
        ("TEST ﬁ ligature", "TEST ﬁ ligature"),
    ],
)
def test_a_name_is_stored_in_normalization_form_c_and_otherwise_as_entered(
    researcher: AuthenticationContext, records: Records, entered: str, stored: str
) -> None:
    """NFC only: no case folding, no compatibility folding, no transliteration (point 9)."""
    public_id = _create(researcher, records, text=entered)

    assert InstitutionName.objects.get(institution__public_id=public_id).text == stored


def test_the_length_of_a_name_is_that_of_its_stored_form(
    researcher: AuthenticationContext, records: Records
) -> None:
    longest = _create(researcher, records, text="T" * 500)
    # 1,000 code points as entered, 500 once composed.
    composed = _create(researcher, records, text="é" * 500)

    assert InstitutionName.objects.get(institution__public_id=longest).text == "T" * 500
    assert InstitutionName.objects.get(institution__public_id=composed).text == "é" * 500
    with pytest.raises(InvalidEntryError):
        _create(researcher, records, text="T" * 501)


@pytest.mark.parametrize("reference", ["country", "parent", "successor"])
@pytest.mark.parametrize("identifier", [UNKNOWN, *NOT_AN_IDENTIFIER])
def test_a_reference_to_no_record_is_refused(
    researcher: AuthenticationContext, records: Records, reference: str, identifier: Any
) -> None:
    before = stored_with_institutions()

    with pytest.raises(RecordNotFoundError):
        _create(researcher, records, valid_to=D1, **{reference: identifier})

    assert stored_with_institutions() == before


@pytest.mark.parametrize("identifier", [UNKNOWN, *NOT_AN_IDENTIFIER])
def test_a_name_in_no_language_is_refused(
    researcher: AuthenticationContext, records: Records, identifier: Any
) -> None:
    before = stored_with_institutions()

    with pytest.raises(RecordNotFoundError):
        institution(researcher, identifier)

    assert stored_with_institutions() == before


def test_a_record_of_another_kind_is_not_taken_for_the_one_referred_to(
    researcher: AuthenticationContext, records: Records
) -> None:
    """A country's identifier names no institution, and an institution's no country."""
    other = _create(researcher, records)

    with pytest.raises(RecordNotFoundError):
        _create(researcher, records, parent=records.country)
    with pytest.raises(RecordNotFoundError):
        _create(researcher, records, country=other)
    with pytest.raises(RecordNotFoundError):
        institution(researcher, records.country)
    with pytest.raises(RecordNotFoundError):
        _create(researcher, records, parent=Institution.objects.get().pk)

    assert Institution.objects.count() == 1


# --- A deactivated country or language cannot be newly referred to (point 18) -


def test_an_institution_cannot_be_created_in_a_deactivated_country(
    administrator: AuthenticationContext, researcher: AuthenticationContext, records: Records
) -> None:
    services.deactivate_country(actor=administrator, public_id=records.country)
    before = stored_with_institutions()

    with pytest.raises(DeactivatedReferenceError):
        _create(researcher, records, country=records.country)

    assert stored_with_institutions() == before
    services.reactivate_country(actor=administrator, public_id=records.country)
    _create(researcher, records, country=records.country)


@pytest.mark.parametrize("how", ["first name", "added name"])
def test_a_name_cannot_be_given_a_deactivated_language(
    administrator: AuthenticationContext,
    researcher: AuthenticationContext,
    records: Records,
    how: str,
) -> None:
    owner = _create(researcher, records)
    services.deactivate_language(actor=administrator, public_id=records.languages[1])
    before = stored_with_institutions()

    with pytest.raises(DeactivatedReferenceError):
        if how == "first name":
            institution(researcher, records.languages[1])
        else:
            services.add_institution_name(
                actor=researcher,
                institution=owner,
                name=NewName(text="TEST Name", language=records.languages[1], kind="official"),
            )

    assert stored_with_institutions() == before


def test_an_institution_keeps_a_country_that_was_deactivated_after_it_was_given(
    administrator: AuthenticationContext, researcher: AuthenticationContext, records: Records
) -> None:
    """Deactivation is not deletion: what refers to it stays, and can still be changed."""
    public_id = _create(researcher, records, country=records.country)
    services.deactivate_country(actor=administrator, public_id=records.country)

    _change(researcher, public_id, kind="regulator")

    assert _state(public_id)["country_public_id"] == records.country
    assert _entry(researcher, public_id).country == records.country
    with pytest.raises(DeactivatedReferenceError):
        _change(researcher, _create(researcher, records), country=records.country)
    _change(researcher, public_id, country=records.countries[1])
    with pytest.raises(DeactivatedReferenceError):
        _change(researcher, public_id, country=records.country)


def test_a_name_in_a_language_deactivated_after_it_was_given_stays(
    administrator: AuthenticationContext, researcher: AuthenticationContext, records: Records
) -> None:
    public_id = _create(researcher, records)
    (name,) = names_of(public_id)
    services.deactivate_language(actor=administrator, public_id=records.language)

    services.change_institution_name_dates(
        actor=researcher, public_id=name, valid_from=D1, valid_to=None
    )

    (entry,) = _entry(researcher, public_id).names
    assert (entry.language, entry.valid_from) == (records.language, D1)


# --- Succession (point 22) -----------------------------------------------------


def test_an_institution_that_names_a_successor_has_ended(
    researcher: AuthenticationContext, records: Records
) -> None:
    successor = _create(researcher, records)
    before = stored_with_institutions()

    with pytest.raises(SuccessionError):
        _create(researcher, records, successor=successor)
    with pytest.raises(SuccessionError):
        _create(researcher, records, successor=successor, valid_from=D1)

    assert stored_with_institutions() == before


@pytest.mark.parametrize(
    ("ends", "successor_ends", "allowed"),
    [
        (D2, None, True),
        (D2, D3, True),
        (D2, D2, True),
        (D2, D1, False),
    ],
    ids=["successor-end-unknown", "successor-ends-later", "same-day", "successor-ends-earlier"],
)
def test_a_successor_did_not_end_before_its_predecessor(
    researcher: AuthenticationContext,
    records: Records,
    ends: date,
    successor_ends: date | None,
    allowed: bool,
) -> None:
    successor = _create(researcher, records, text="TEST Successor", valid_to=successor_ends)

    if allowed:
        public_id = _create(researcher, records, valid_to=ends, successor=successor)
        assert _state(public_id)["successor_public_id"] == successor
    else:
        with pytest.raises(SuccessionError):
            _create(researcher, records, valid_to=ends, successor=successor)
        assert Institution.objects.count() == 1


def test_several_institutions_may_name_one_successor(
    researcher: AuthenticationContext, records: Records
) -> None:
    """A merger. A split into several bodies cannot be recorded with one link."""
    successor = _create(researcher, records, text="TEST Merged")

    first = _create(researcher, records, valid_to=D1, successor=successor)
    second = _create(researcher, records, valid_to=D2, successor=successor)

    assert {_state(first)["successor_public_id"], _state(second)["successor_public_id"]} == {
        successor
    }


def test_a_successor_is_checked_when_either_side_changes(
    researcher: AuthenticationContext, records: Records
) -> None:
    successor = _create(researcher, records, text="TEST Successor", valid_to=D3)
    predecessor = _create(researcher, records, valid_to=D2, successor=successor)
    early = _create(researcher, records, text="TEST Early", valid_to=D1)
    before = stored_with_institutions()

    # The predecessor moves its end after the successor's.
    with pytest.raises(SuccessionError):
        _change(researcher, predecessor, valid_to=D4)
    # The successor moves its end before the predecessor's.
    with pytest.raises(SuccessionError):
        _change(researcher, successor, valid_to=D1)
    # The predecessor stops having ended while it names a successor.
    with pytest.raises(SuccessionError):
        _change(researcher, predecessor, valid_to=None)
    # A successor named afresh has ended before this one.
    with pytest.raises(SuccessionError):
        _change(researcher, predecessor, successor=early)

    assert stored_with_institutions() == before
    _change(researcher, successor, valid_to=D2)
    _change(researcher, successor, valid_to=None)
    _change(researcher, predecessor, valid_to=D4)


def test_a_successor_is_named_and_cleared_through_a_change(
    researcher: AuthenticationContext, records: Records
) -> None:
    successor = _create(researcher, records, text="TEST Successor")
    public_id = _create(researcher, records)

    with pytest.raises(SuccessionError):
        _change(researcher, public_id, successor=successor)
    _change(researcher, public_id, successor=successor, valid_to=D1)
    _change(researcher, public_id, successor=None)

    assert _state(public_id)["successor_public_id"] is None
    assert _state(public_id)["valid_to"] == D1


# --- Cycles (point 22) ---------------------------------------------------------


@pytest.mark.parametrize("link", ["parent", "successor"])
def test_an_institution_is_not_its_own_parent_or_successor(
    researcher: AuthenticationContext, records: Records, link: str
) -> None:
    public_id = _create(researcher, records, valid_to=D1)
    before = stored_with_institutions()

    with pytest.raises(CycleError):
        _change(researcher, public_id, **{link: public_id})

    assert stored_with_institutions() == before


@pytest.mark.parametrize("length", [2, 3, 5])
def test_a_chain_of_parents_never_comes_back(
    researcher: AuthenticationContext, records: Records, length: int
) -> None:
    chain = [_create(researcher, records, text=f"TEST Level {level}") for level in range(length)]
    for child, parent in zip(chain[1:], chain, strict=False):
        _change(researcher, child, parent=parent)
    before = stored_with_institutions()

    with pytest.raises(CycleError):
        _change(researcher, chain[0], parent=chain[-1])

    assert stored_with_institutions() == before


@pytest.mark.parametrize("length", [2, 3, 5])
def test_a_chain_of_successors_never_comes_back(
    researcher: AuthenticationContext, records: Records, length: int
) -> None:
    """Every one has ended on the same day, so that no rule of dates stops the cycle first."""
    chain = [
        _create(researcher, records, text=f"TEST Step {step}", valid_to=D1)
        for step in range(length)
    ]
    for predecessor, successor in zip(chain, chain[1:], strict=False):
        _change(researcher, predecessor, successor=successor)
    before = stored_with_institutions()

    with pytest.raises(CycleError):
        _change(researcher, chain[-1], successor=chain[0])

    assert stored_with_institutions() == before


def test_a_tree_of_parents_and_a_link_across_it_are_not_cycles(
    researcher: AuthenticationContext, records: Records
) -> None:
    top = _create(researcher, records, text="TEST Top")
    left = _create(researcher, records, text="TEST Left", parent=top)
    right = _create(researcher, records, text="TEST Right", parent=top)
    below = _create(researcher, records, text="TEST Below", parent=left)

    _change(researcher, below, parent=right)
    _change(researcher, left, parent=right)
    # Parents and successors are separate chains.
    _change(researcher, top, valid_to=D1, successor=below)

    assert _state(left)["parent_public_id"] == right
    assert _state(top)["successor_public_id"] == below


# --- Changing an institution ---------------------------------------------------


def test_a_change_overwrites_each_attribute_and_records_its_old_and_new_value(
    researcher: AuthenticationContext, records: Records
) -> None:
    parent = _create(researcher, records, text="TEST Parent")
    successor = _create(researcher, records, text="TEST Successor")
    public_id = _create(researcher, records)
    recorded = len(events())

    services.change_institution(
        actor=researcher,
        public_id=public_id,
        kind="regulator",
        country=records.country,
        parent=parent,
        successor=successor,
        valid_from=D1,
        valid_to=D2,
    )

    assert _state(public_id) == {
        "kind": "regulator",
        "valid_from": D1,
        "valid_to": D2,
        "country_public_id": records.country,
        "parent_public_id": parent,
        "successor_public_id": successor,
    }
    ((action, target_type, target, actor),) = events()[recorded:]
    assert (action, target_type, target, actor) == (
        "updated",
        "registry.institution",
        public_id,
        researcher.user.pk,
    )
    event = AuditEvent.objects.latest("id")
    assert sorted(event.changes.values_list("field", "old_value", "new_value")) == [
        ("country", "", str(records.country)),
        ("kind", "ministry", "regulator"),
        ("parent", "", str(parent)),
        ("successor", "", str(successor)),
        ("valid_from", "", "2001-02-03"),
        ("valid_to", "", "2002-03-04"),
    ]


def test_a_cleared_attribute_is_recorded_as_nothing(
    researcher: AuthenticationContext, records: Records
) -> None:
    parent = _create(researcher, records, text="TEST Parent")
    successor = _create(researcher, records, text="TEST Successor")
    public_id = _create(
        researcher,
        records,
        country=records.country,
        parent=parent,
        successor=successor,
        valid_from=D1,
        valid_to=D2,
    )

    _change(
        researcher,
        public_id,
        country=None,
        parent=None,
        successor=None,
        valid_from=None,
        valid_to=None,
    )

    event = AuditEvent.objects.latest("id")
    assert sorted(event.changes.values_list("field", "old_value", "new_value")) == [
        ("country", str(records.country), ""),
        ("parent", str(parent), ""),
        ("successor", str(successor), ""),
        ("valid_from", "2001-02-03", ""),
        ("valid_to", "2002-03-04", ""),
    ]


@pytest.mark.parametrize(
    ("field", "value", "rendered"),
    [
        ("kind", "university", ("ministry", "university")),
        ("valid_from", D1, ("", "2001-02-03")),
        ("valid_to", D4, ("", "2004-05-06")),
    ],
)
def test_only_what_changed_is_recorded(
    researcher: AuthenticationContext,
    records: Records,
    field: str,
    value: Any,
    rendered: tuple[str, str],
) -> None:
    public_id = _create(researcher, records, country=records.country)

    _change(researcher, public_id, **{field: value})

    assert list(
        AuditEvent.objects.latest("id").changes.values_list("field", "old_value", "new_value")
    ) == [(field, *rendered)]


def test_a_change_that_changes_nothing_is_refused_and_records_nothing(
    researcher: AuthenticationContext, records: Records
) -> None:
    parent = _create(researcher, records, text="TEST Parent")
    public_id = _create(researcher, records, country=records.country, parent=parent, valid_to=D1)
    before = stored_with_institutions()

    with pytest.raises(NoChangeError):
        _change(researcher, public_id)

    assert stored_with_institutions() == before


@pytest.mark.parametrize("public_id", [UNKNOWN, "not-a-uuid", 1, None])
def test_a_change_to_an_institution_that_does_not_exist_is_refused(
    researcher: AuthenticationContext, records: Records, public_id: Any
) -> None:
    _create(researcher, records)
    before = stored_with_institutions()

    with pytest.raises(RecordNotFoundError):
        services.change_institution(
            actor=researcher,
            public_id=public_id,
            kind="regulator",
            country=None,
            parent=None,
            successor=None,
            valid_from=None,
            valid_to=None,
        )

    assert stored_with_institutions() == before


def test_an_institution_is_not_changed_through_the_identifier_of_its_name(
    researcher: AuthenticationContext, records: Records
) -> None:
    public_id = _create(researcher, records)
    (name,) = names_of(public_id)

    with pytest.raises(RecordNotFoundError):
        services.change_institution(
            actor=researcher,
            public_id=name,
            kind="company",
            country=None,
            parent=None,
            successor=None,
            valid_from=None,
            valid_to=None,
        )

    assert _state(public_id)["kind"] == "ministry"


def test_a_change_leaves_the_names_and_every_other_institution_as_they_were(
    researcher: AuthenticationContext, records: Records
) -> None:
    other = _create(researcher, records, text="TEST Other")
    public_id = _create(researcher, records)
    others_before = list(Institution.objects.filter(public_id=other).values())
    names_before = list(InstitutionName.objects.order_by("id").values())

    _change(researcher, public_id, kind="company", parent=other)

    assert list(Institution.objects.filter(public_id=other).values()) == others_before
    assert list(InstitutionName.objects.order_by("id").values()) == names_before


# --- Names ----------------------------------------------------------------------


def test_a_name_is_added_to_an_institution_and_recorded(
    researcher: AuthenticationContext, records: Records
) -> None:
    """A renamed body gets a new name; the old one stays (ADR-0018 point 19)."""
    public_id = _create(researcher, records, text="TEST Old name")
    (old,) = names_of(public_id)
    services.change_institution_name_dates(
        actor=researcher, public_id=old, valid_from=None, valid_to=D2
    )
    recorded = len(events())

    added = services.add_institution_name(
        actor=researcher,
        institution=public_id,
        name=NewName(
            text=" TEST New name ",
            language=records.languages[2],
            kind="transliteration",
            valid_from=D2,
        ),
    )

    assert names_of(public_id) == [old, added]
    assert [
        (name.text, name.language, name.kind, name.valid_from, name.valid_to)
        for name in _entry(researcher, public_id).names
    ] == [
        ("TEST Old name", records.language, "official", None, D2),
        ("TEST New name", records.languages[2], "transliteration", D2, None),
    ]
    assert events()[recorded:] == [
        ("created", "registry.institution_name", added, researcher.user.pk)
    ]
    assert not AuditEvent.objects.latest("id").changes.exists()


def test_the_same_name_may_be_added_again(
    researcher: AuthenticationContext, records: Records
) -> None:
    public_id = _create(researcher, records, text="TEST Name")

    services.add_institution_name(
        actor=researcher,
        institution=public_id,
        name=NewName(text="TEST Name", language=records.language, kind="official"),
    )

    assert [name.text for name in _entry(researcher, public_id).names] == ["TEST Name"] * 2


@pytest.mark.parametrize("text", BAD_TEXTS)
def test_a_name_with_no_usable_text_is_not_added(
    researcher: AuthenticationContext, records: Records, text: Any
) -> None:
    public_id = _create(researcher, records)
    before = stored_with_institutions()

    with pytest.raises(InvalidEntryError):
        services.add_institution_name(
            actor=researcher,
            institution=public_id,
            name=NewName(text=text, language=records.language, kind="official"),
        )

    assert stored_with_institutions() == before


@pytest.mark.parametrize("institution_id", [UNKNOWN, "not-a-uuid", 1, None])
def test_a_name_is_not_added_to_an_institution_that_does_not_exist(
    researcher: AuthenticationContext, records: Records, institution_id: Any
) -> None:
    public_id = _create(researcher, records)
    (name,) = names_of(public_id)
    before = stored_with_institutions()

    for missing in (institution_id, name, records.country):
        with pytest.raises(RecordNotFoundError):
            services.add_institution_name(
                actor=researcher,
                institution=missing,
                name=NewName(text="TEST Name", language=records.language, kind="official"),
            )

    assert stored_with_institutions() == before


def test_the_dates_of_a_name_change_and_are_recorded_and_nothing_else_of_it_does(
    researcher: AuthenticationContext, records: Records
) -> None:
    public_id = _create(researcher, records)
    (name,) = names_of(public_id)
    before = InstitutionName.objects.values().get()

    services.change_institution_name_dates(
        actor=researcher, public_id=name, valid_from=D1, valid_to=D3
    )
    services.change_institution_name_dates(
        actor=researcher, public_id=name, valid_from=D1, valid_to=None
    )

    after = InstitutionName.objects.values().get()
    assert after == {**before, "valid_from": D1, "valid_to": None}
    assert events()[-2:] == [
        ("updated", "registry.institution_name", name, researcher.user.pk),
        ("updated", "registry.institution_name", name, researcher.user.pk),
    ]
    first, second = AuditEvent.objects.order_by("-id")[:2][::-1]
    assert sorted(first.changes.values_list("field", "old_value", "new_value")) == [
        ("valid_from", "", "2001-02-03"),
        ("valid_to", "", "2003-04-05"),
    ]
    assert list(second.changes.values_list("field", "old_value", "new_value")) == [
        ("valid_to", "2003-04-05", "")
    ]


def test_dates_of_a_name_that_change_nothing_or_are_not_valid_are_refused(
    researcher: AuthenticationContext, records: Records
) -> None:
    public_id = _create(researcher, records)
    (name,) = names_of(public_id)
    before = stored_with_institutions()

    with pytest.raises(NoChangeError):
        services.change_institution_name_dates(
            actor=researcher, public_id=name, valid_from=None, valid_to=None
        )
    invalid: list[tuple[Any, Any]] = [(D1, D1), (D2, D1), ("2001-02-03", None), (None, 20010203)]
    for valid_from, valid_to in invalid:
        with pytest.raises(InvalidEntryError):
            services.change_institution_name_dates(
                actor=researcher, public_id=name, valid_from=valid_from, valid_to=valid_to
            )
    missing: Any
    for missing in (UNKNOWN, public_id, "not-a-uuid", None):
        with pytest.raises(RecordNotFoundError):
            services.change_institution_name_dates(
                actor=researcher, public_id=missing, valid_from=D1, valid_to=None
            )

    assert stored_with_institutions() == before


# --- A name entered in error (points 19 and 20) ------------------------------


def _two_names(
    researcher: AuthenticationContext, records: Records
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    public_id = _create(researcher, records, text="TEST Wrong name")
    right = services.add_institution_name(
        actor=researcher,
        institution=public_id,
        name=NewName(text="TEST Right name", language=records.language, kind="official"),
    )
    (wrong, _) = names_of(public_id)
    return public_id, wrong, right


def test_a_name_marked_as_entered_in_error_stays_and_is_no_longer_a_name_of_its_institution(
    researcher: AuthenticationContext, records: Records
) -> None:
    public_id, wrong, right = _two_names(researcher, records)
    recorded = len(events())
    before = InstitutionName.objects.filter(public_id=wrong).values().get()

    services.mark_institution_name_entered_in_error(actor=researcher, public_id=wrong)

    assert InstitutionName.objects.filter(public_id=wrong).values().get() == {
        **before,
        "entered_in_error": True,
    }
    entry = _entry(researcher, public_id)
    assert [name.public_id for name in entry.names] == [right]
    assert [name.public_id for name in entry.names_entered_in_error] == [wrong]
    assert entry.label == "TEST Right name"
    assert events()[recorded:] == [
        ("marked_entered_in_error", "registry.institution_name", wrong, researcher.user.pk)
    ]
    assert not AuditEvent.objects.latest("id").changes.exists()


def test_a_name_is_marked_once(researcher: AuthenticationContext, records: Records) -> None:
    _, wrong, _ = _two_names(researcher, records)
    services.mark_institution_name_entered_in_error(actor=researcher, public_id=wrong)
    before = stored_with_institutions()

    with pytest.raises(NoChangeError):
        services.mark_institution_name_entered_in_error(actor=researcher, public_id=wrong)

    assert stored_with_institutions() == before


def test_the_only_unmarked_name_of_an_institution_is_not_marked(
    researcher: AuthenticationContext, records: Records
) -> None:
    """The right name is added first (ADR-0018 point 20)."""
    alone = _create(researcher, records)
    (only,) = names_of(alone)
    public_id, wrong, right = _two_names(researcher, records)
    services.mark_institution_name_entered_in_error(actor=researcher, public_id=wrong)
    before = stored_with_institutions()

    with pytest.raises(LastNameError):
        services.mark_institution_name_entered_in_error(actor=researcher, public_id=only)
    # A marked name does not count as the other one.
    with pytest.raises(LastNameError):
        services.mark_institution_name_entered_in_error(actor=researcher, public_id=right)

    assert stored_with_institutions() == before
    assert [name.public_id for name in _entry(researcher, public_id).names] == [right]


def test_a_mark_set_by_mistake_is_answered_by_adding_the_name_again(
    researcher: AuthenticationContext, records: Records
) -> None:
    public_id, wrong, right = _two_names(researcher, records)
    services.mark_institution_name_entered_in_error(actor=researcher, public_id=wrong)

    again = services.add_institution_name(
        actor=researcher,
        institution=public_id,
        name=NewName(text="TEST Wrong name", language=records.language, kind="official"),
    )
    services.mark_institution_name_entered_in_error(actor=researcher, public_id=right)

    entry = _entry(researcher, public_id)
    assert [name.public_id for name in entry.names] == [again]
    assert [name.public_id for name in entry.names_entered_in_error] == [wrong, right]


@pytest.mark.parametrize("public_id", [UNKNOWN, "not-a-uuid", 1, None])
def test_marking_a_name_that_does_not_exist_is_refused(
    researcher: AuthenticationContext, records: Records, public_id: Any
) -> None:
    owner, _, _ = _two_names(researcher, records)
    before = stored_with_institutions()

    for missing in (public_id, owner):
        with pytest.raises(RecordNotFoundError):
            services.mark_institution_name_entered_in_error(actor=researcher, public_id=missing)

    assert stored_with_institutions() == before


# --- Reading -------------------------------------------------------------------


def test_the_read_lists_every_institution_with_its_names_and_references(
    researcher: AuthenticationContext, records: Records
) -> None:
    parent = _create(researcher, records, text="TEST Parent", country=records.country)
    successor = _create(researcher, records, text="TEST Successor", kind="company")
    child = _create(
        researcher,
        records,
        text="TEST Child",
        parent=parent,
        valid_from=D1,
        valid_to=D2,
        successor=successor,
    )

    entries = selectors.institutions(researcher)

    assert [entry.public_id for entry in entries] == [parent, successor, child]
    first, second, third = entries
    assert (first.kind, first.kind_label, first.country, first.country_alpha2) == (
        "ministry",
        "Ministry",
        records.country,
        COUNTRIES[0][0],
    )
    assert (second.kind_label, second.country, second.country_alpha2) == ("Company", None, None)
    assert third.parent == selectors.InstitutionReference(parent, "TEST Parent")
    assert third.successor == selectors.InstitutionReference(successor, "TEST Successor")
    assert (third.valid_from, third.valid_to) == (D1, D2)
    (name,) = third.names
    assert (name.text, name.language_code, name.script_code, name.kind_label) == (
        "TEST Child",
        "qaa",
        "Qaaa",
        "Official",
    )
    assert third.names_entered_in_error == ()


def test_the_read_returns_values_and_no_model(
    researcher: AuthenticationContext, records: Records
) -> None:
    _create(researcher, records)

    (entry,) = selectors.institutions(researcher)

    for value in (entry, *entry.names):
        assert not [
            name
            for name, attribute in vars(value).items()
            if hasattr(attribute, "_meta") or name in {"id", "pk"}
        ]


# --- The same rules for every country (ADR-0018 testing requirement 10) -------


@pytest.mark.parametrize("number", range(len(COUNTRIES)))
def test_each_synthetic_country_lives_under_the_same_institution_rules(
    administrator: AuthenticationContext,
    researcher: AuthenticationContext,
    records: Records,
    number: int,
) -> None:
    chosen = records.countries[number]
    parent = _create(researcher, records, text="TEST Parent", country=chosen)
    public_id = _create(researcher, records, country=chosen, parent=parent)

    with pytest.raises(CycleError):
        _change(researcher, parent, parent=public_id)
    with pytest.raises(NoChangeError):
        _change(researcher, public_id)
    _change(researcher, public_id, kind="legislature", valid_to=D1, successor=parent)
    services.deactivate_country(actor=administrator, public_id=chosen)
    with pytest.raises(DeactivatedReferenceError):
        _create(researcher, records, country=chosen)
    _change(researcher, public_id, kind="regulator")

    assert _state(public_id) == {
        "kind": "regulator",
        "valid_from": None,
        "valid_to": D1,
        "country_public_id": chosen,
        "parent_public_id": parent,
        "successor_public_id": parent,
    }
    assert [action for action, _, target, _ in events() if target == public_id] == [
        "created",
        "updated",
        "updated",
    ]


# --- What the audit record holds (ADR-0018 testing requirement 9) -------------


def test_every_event_names_the_account_that_acted_the_record_and_the_request(
    researcher: AuthenticationContext, acting_as: ActingAs, records: Records
) -> None:
    other = acting_as(Role.ADMINISTRATOR, second_factor=True)
    recorded = AuditEvent.objects.count()

    with correlation_scope() as first:
        public_id = _create(researcher, records)
    (initial,) = names_of(public_id)
    with correlation_scope() as second:
        _change(other, public_id, kind="regulator")
    with correlation_scope() as third:
        added = services.add_institution_name(
            actor=researcher,
            institution=public_id,
            name=NewName(text="TEST Second", language=records.language, kind="official"),
        )
    with correlation_scope() as fourth:
        services.change_institution_name_dates(
            actor=other, public_id=added, valid_from=D1, valid_to=None
        )
    with correlation_scope() as fifth:
        services.mark_institution_name_entered_in_error(actor=researcher, public_id=initial)

    rows = list(
        AuditEvent.objects.order_by("id")[recorded:].values(
            "action", "target_type", "target_public_id", "actor_id", "correlation_id"
        )
    )
    assert rows == [
        {
            "action": action,
            "target_type": target_type,
            "target_public_id": target,
            "actor_id": actor.user.pk,
            "correlation_id": correlation_id,
        }
        for action, target_type, target, actor, correlation_id in [
            ("created", "registry.institution", public_id, researcher, first),
            ("created", "registry.institution_name", initial, researcher, first),
            ("updated", "registry.institution", public_id, other, second),
            ("created", "registry.institution_name", added, researcher, third),
            ("updated", "registry.institution_name", added, other, fourth),
            ("marked_entered_in_error", "registry.institution_name", initial, researcher, fifth),
        ]
    ]
    assert len({first, second, third, fourth, fifth}) == 5


def test_only_an_update_has_change_records(
    researcher: AuthenticationContext, records: Records
) -> None:
    public_id, wrong, right = _two_names(researcher, records)
    _change(researcher, public_id, kind="company")
    services.change_institution_name_dates(
        actor=researcher, public_id=right, valid_from=D1, valid_to=None
    )
    services.mark_institution_name_entered_in_error(actor=researcher, public_id=wrong)

    institution_events = AuditEvent.objects.filter(
        target_type__in=["registry.institution", "registry.institution_name"]
    ).order_by("id")
    assert [
        (event.action, list(event.changes.values_list("field", flat=True)))
        for event in institution_events
    ] == [
        ("created", []),
        ("created", []),
        ("created", []),
        ("updated", ["kind"]),
        ("updated", ["valid_from"]),
        ("marked_entered_in_error", []),
    ]


def test_no_event_holds_a_name_an_email_address_or_anything_but_the_change(
    researcher: AuthenticationContext, records: Records
) -> None:
    """ADR-0018 point 36: no free text, and no personal data beyond the actor."""
    with correlation_scope():
        public_id = _create(researcher, records, text="TEST Secretive Name")
        _change(researcher, public_id, kind="company", valid_from=D1)
        services.add_institution_name(
            actor=researcher,
            institution=public_id,
            name=NewName(text="TEST Another Name", language=records.language, kind="official"),
        )

    written = " ".join(
        str(value)
        for row in [*AuditEvent.objects.values(), *AuditEventChange.objects.values()]
        for value in row.values()
    )
    assert "Secretive" not in written and "Another" not in written
    assert researcher.user.email not in written
    assert set(AuditEventChange.objects.values_list("field", flat=True)) <= {
        "kind",
        "valid_from",
        "name_en",
    }


# --- Logging --------------------------------------------------------------------


def test_each_change_is_logged_with_the_identifier_and_no_value(
    researcher: AuthenticationContext, records: Records, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="caipo.registry.services"):
        public_id = _create(researcher, records, text="TEST Logged Name")
        (first,) = names_of(public_id)
        _change(researcher, public_id, valid_from=D1)
        added = services.add_institution_name(
            actor=researcher,
            institution=public_id,
            name=NewName(text="TEST Other Logged", language=records.language, kind="official"),
        )
        services.change_institution_name_dates(
            actor=researcher, public_id=added, valid_from=D2, valid_to=None
        )
        services.mark_institution_name_entered_in_error(actor=researcher, public_id=first)

    logged = [record for record in caplog.records if record.name == "caipo.registry.services"]
    assert [
        (record.__dict__["event"], record.__dict__["public_id"], record.__dict__["actor_id"])
        for record in logged
        if "institution" in record.__dict__["event"]
    ] == [
        ("registry.institution_created", str(public_id), researcher.user.pk),
        ("registry.institution_name_created", str(first), researcher.user.pk),
        ("registry.institution_updated", str(public_id), researcher.user.pk),
        ("registry.institution_name_created", str(added), researcher.user.pk),
        ("registry.institution_name_updated", str(added), researcher.user.pk),
        ("registry.institution_name_marked_entered_in_error", str(first), researcher.user.pk),
    ]
    text = " ".join(f"{record.getMessage()} {record.__dict__}" for record in logged)
    assert "Logged" not in text and "2001-02-03" not in text
    assert researcher.user.email not in text


def test_a_refused_change_is_not_logged_as_made(
    researcher: AuthenticationContext, records: Records, caplog: pytest.LogCaptureFixture
) -> None:
    public_id = _create(researcher, records, valid_to=D1)
    (only,) = names_of(public_id)
    other = _create(researcher, records, text="TEST Other")
    caplog.clear()

    with caplog.at_level(logging.INFO, logger="caipo.registry.services"):
        with pytest.raises(NoChangeError):
            _change(researcher, public_id)
        with pytest.raises(CycleError):
            _change(researcher, public_id, parent=public_id)
        with pytest.raises(LastNameError):
            services.mark_institution_name_entered_in_error(actor=researcher, public_id=only)
        with pytest.raises(InvalidEntryError):
            _create(researcher, records, text=" ")
        with pytest.raises(SuccessionError):
            _change(researcher, public_id, valid_to=None, successor=other)
        with pytest.raises(RecordNotFoundError):
            _change(researcher, public_id, parent=UNKNOWN)

    assert [record for record in caplog.records if record.name == "caipo.registry.services"] == []
