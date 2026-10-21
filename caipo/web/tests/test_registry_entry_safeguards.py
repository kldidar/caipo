"""Safeguards of the entry page: fixes of findings of the diagnostic of 2026-10-20.

- M2: a name is marked as entered in error only with a ticked confirmation,
  because the mark is never cleared.
- L3: a refused change to an institution, a new name, or a name's dates is
  shown again as it was typed, with its field errors.
- L5: a name holding an invisible direction control is refused with a
  message that says so.
- L6: a date is accepted only as YYYY-MM-DD in ASCII digits, every part
  padded with zeros.
"""

import uuid
from datetime import date
from typing import Any

import pytest
from django import forms
from django.test import Client

from caipo.accounts.models import AuditEvent, AuditEventChange, User
from caipo.accounts.selectors import Role
from caipo.accounts.tests.fixtures import UserFactory
from caipo.accounts.tests.fixtures import verified as acting_verified
from caipo.registry import services
from caipo.registry.models import Country, Institution, InstitutionName, Language
from caipo.registry.services import NewName
from caipo.web.forms import FullDateField, MarkEnteredInErrorForm
from caipo.web.tests.helpers import signed_in, verified

pytestmark = [pytest.mark.services, pytest.mark.django_db]

ENTRY = "/registry/entry/"
SAVED = f"{ENTRY}?saved=1"
CREATE_COUNTRY = "/registry/entry/countries/create/"
CREATE_INSTITUTION = "/registry/entry/institutions/create/"


class Records:
    """A country, a language, and an institution with two names, entered by an Administrator."""

    def __init__(self, administrator: User) -> None:
        actor = acting_verified(administrator)
        self.country = services.create_country(
            actor=actor, alpha2="XA", alpha3="XAA", name_en="TEST Country A"
        )
        self.language = services.create_language(
            actor=actor, code="qaa", script_code="Qaaa", name_en="TEST Language A"
        )
        self.institution = services.create_institution(
            actor=actor,
            kind="ministry",
            country=self.country,
            first_name=NewName(text="TEST Ministry", language=self.language, kind="official"),
        )
        self.other_name = services.add_institution_name(
            actor=actor,
            institution=self.institution,
            name=NewName(text="TEST MIN", language=self.language, kind="abbreviation"),
        )


@pytest.fixture
def administrator(user_with_roles: UserFactory) -> User:
    return user_with_roles(Role.ADMINISTRATOR)


@pytest.fixture
def records(administrator: User) -> Records:
    return Records(administrator)


@pytest.fixture
def researcher(user_with_roles: UserFactory) -> Client:
    return signed_in(Client(), user_with_roles(Role.RESEARCHER))


def _mark_url(name: uuid.UUID) -> str:
    return f"/registry/entry/institution-names/{name}/mark-entered-in-error/"


def _change_url(institution: uuid.UUID) -> str:
    return f"/registry/entry/institutions/{institution}/change/"


def _add_name_url(institution: uuid.UUID) -> str:
    return f"/registry/entry/institutions/{institution}/names/add/"


def _dates_url(name: uuid.UUID) -> str:
    return f"/registry/entry/institution-names/{name}/dates/"


def _stored() -> dict[str, list[Any]]:
    return {
        "countries": list(Country.objects.order_by("id").values()),
        "languages": list(Language.objects.order_by("id").values()),
        "institutions": list(Institution.objects.order_by("id").values()),
        "names": list(InstitutionName.objects.order_by("id").values()),
        "events": list(AuditEvent.objects.order_by("id").values()),
        "changes": list(AuditEventChange.objects.order_by("id").values()),
    }


def _text(response: Any) -> str:
    return str(response.content.decode())


# --- M2: the mark needs a ticked confirmation ---------------------------------------


@pytest.mark.parametrize(
    "body",
    [{}, {"confirmed": ""}, {"confirmed": "0"}, {"confirmed": "1"}, {"confirmed": "true"}],
)
def test_a_name_is_not_marked_without_the_ticked_confirmation(
    researcher: Client, records: Records, body: dict[str, str]
) -> None:
    before = _stored()

    response = researcher.post(_mark_url(records.other_name), body)

    assert response.status_code == 400
    assert "only when the confirmation is ticked, because the mark cannot be undone" in _text(
        response
    )
    assert _stored() == before


def test_a_name_is_marked_with_the_ticked_confirmation(
    researcher: Client, records: Records
) -> None:
    response = researcher.post(_mark_url(records.other_name), {"confirmed": "on"})

    assert response.status_code == 302
    assert response["Location"] == SAVED
    assert InstitutionName.objects.get(public_id=records.other_name).entered_in_error
    assert AuditEvent.objects.filter(
        action="marked_entered_in_error", target_public_id=records.other_name
    ).exists()


def test_each_mark_form_shows_its_own_confirmation_box(
    researcher: Client, records: Records
) -> None:
    page = _text(researcher.get(ENTRY))

    for name in InstitutionName.objects.filter(institution__public_id=records.institution):
        assert f'id="mark-{name.public_id}-confirmed"' in page
    assert "I understand that the mark cannot be undone." in page


def test_the_confirmation_form_takes_only_what_a_ticked_box_sends() -> None:
    assert MarkEnteredInErrorForm({"confirmed": "on"}).is_valid()
    for value in ["", "0", "1", "true", "yes", "off"]:
        assert not MarkEnteredInErrorForm({"confirmed": value}).is_valid()


# --- L3: a refused change is shown again as typed ----------------------------------


def test_a_refused_change_of_an_institution_is_shown_again_as_typed(
    researcher: Client, records: Records
) -> None:
    body = {
        "kind": "regulator",
        "country": "",
        "parent": str(records.institution),
        "successor": "",
        "valid_from": "2001-02-03",
        "valid_to": "",
    }
    before = _stored()

    response = researcher.post(_change_url(records.institution), body)

    assert response.status_code == 409
    assert "cannot be its own parent" in _text(response)
    page = _text(response)
    assert f'value="2001-02-03" id="institution-{records.institution}-valid_from"' in page
    assert '<option value="regulator" selected>' in page
    assert _stored() == before


def test_a_change_of_an_institution_with_a_bad_date_shows_the_date_and_its_error(
    researcher: Client, records: Records
) -> None:
    body = {
        "kind": "regulator",
        "country": "",
        "parent": "",
        "successor": "",
        "valid_from": "2001-2-3",
        "valid_to": "",
    }

    response = researcher.post(_change_url(records.institution), body)

    assert response.status_code == 400
    page = _text(response)
    assert 'value="2001-2-3"' in page
    assert '<span role="alert">Enter a valid date.</span>' in page
    assert '<option value="regulator" selected>' in page


def test_a_refused_new_name_is_shown_again_as_typed(researcher: Client, records: Records) -> None:
    body = {
        "text": "TEST Typed name",
        "language": str(records.language),
        "kind": "transliteration",
        "valid_from": "2002-01-01",
        "valid_to": "2001-01-01",
    }
    before = _stored()

    response = researcher.post(_add_name_url(records.institution), body)

    assert response.status_code == 400
    page = _text(response)
    assert 'value="TEST Typed name"' in page
    assert 'value="2002-01-01"' in page
    assert 'value="2001-01-01"' in page
    assert '<option value="transliteration" selected>' in page
    assert _stored() == before


def test_refused_dates_of_a_name_are_shown_again_as_typed(
    researcher: Client, records: Records
) -> None:
    before = _stored()

    response = researcher.post(
        _dates_url(records.other_name), {"valid_from": "2003-04-05", "valid_to": "2003-04-05"}
    )

    assert response.status_code == 400
    page = _text(response)
    assert f'value="2003-04-05" id="dates-{records.other_name}-valid_from"' in page
    assert f'value="2003-04-05" id="dates-{records.other_name}-valid_to"' in page
    assert _stored() == before


def test_what_was_typed_is_shown_only_in_the_form_it_was_sent_from(
    researcher: Client, records: Records
) -> None:
    """The other forms on the page show what is stored, not what was sent to another one."""
    page = _text(
        researcher.post(
            _dates_url(records.other_name), {"valid_from": "2003-04-05", "valid_to": "2003-04-05"}
        )
    )

    first = InstitutionName.objects.filter(institution__public_id=records.institution).exclude(
        public_id=records.other_name
    )
    (name,) = first
    assert f'value="2003-04-05" id="dates-{name.public_id}-valid_from"' not in page
    assert page.count('value="2003-04-05"') == 2


# --- L5: a direction control is refused with a message that says so -----------------


def test_a_new_name_with_a_direction_control_is_refused_and_the_page_says_why(
    researcher: Client, records: Records
) -> None:
    before = _stored()

    response = researcher.post(
        _add_name_url(records.institution),
        {
            "text": "TEST \u202eName",
            "language": str(records.language),
            "kind": "official",
            "valid_from": "",
            "valid_to": "",
        },
    )

    assert response.status_code == 400
    assert "invisible character that changes the direction of text" in _text(response)
    assert _stored() == before


def test_a_new_institution_with_a_direction_control_in_its_name_is_refused(
    researcher: Client, records: Records
) -> None:
    before = _stored()

    response = researcher.post(
        CREATE_INSTITUTION,
        {
            "institution-kind": "university",
            "institution-country": "",
            "institution-parent": "",
            "institution-successor": "",
            "institution-valid_from": "",
            "institution-valid_to": "",
            "first-name-text": "TEST \u2066University\u2069",
            "first-name-language": str(records.language),
            "first-name-kind": "official",
            "first-name-valid_from": "",
            "first-name-valid_to": "",
        },
    )

    assert response.status_code == 400
    assert "invisible character that changes the direction of text" in _text(response)
    assert _stored() == before


def test_a_country_with_a_direction_control_in_its_name_is_refused(
    administrator: User, records: Records
) -> None:
    client = verified(Client(), administrator)
    before = _stored()

    response = client.post(
        CREATE_COUNTRY,
        {"country-alpha2": "XB", "country-alpha3": "XBB", "country-name_en": "TEST \u202dB"},
    )

    assert response.status_code == 400
    assert "invisible character that changes the direction of text" in _text(response)
    assert _stored() == before


def test_a_country_rename_with_a_direction_control_is_refused(
    administrator: User, records: Records
) -> None:
    client = verified(Client(), administrator)
    before = _stored()

    response = client.post(
        f"/registry/entry/countries/{records.country}/rename/", {"name_en": "TEST \u202bA"}
    )

    assert response.status_code == 400
    assert "invisible character that changes the direction of text" in _text(response)
    assert _stored() == before


# --- L6: one strict form of date -----------------------------------------------------

NOT_STRICT_DATES = [
    "2020-1-1",
    "2020-01-1",
    "2020-1-01",
    "20-01-01",
    "\uff12\uff10\uff12\uff10-01-01",  # full-width digits
    "\u0662\u0660\u0662\u0660-01-01",  # Arabic-Indic digits
    "2020-\u0660\u0661-01",
    " 2020-01-01",
    "2020-01-01 ",
    "2020/01/01",
    "20200101",
    "2020-01-01T00:00",
    "2020-02-30",
    "0000-01-01",
    "+2020-01-01",
]


@pytest.mark.parametrize("value", NOT_STRICT_DATES)
def test_the_date_field_refuses_every_form_but_one(value: str) -> None:
    with pytest.raises(forms.ValidationError):
        FullDateField(required=False).clean(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("2020-01-01", date(2020, 1, 1)), ("0001-12-31", date(1, 12, 31)), ("", None)],
)
def test_the_date_field_accepts_a_full_padded_date_or_nothing(
    value: str, expected: date | None
) -> None:
    assert FullDateField(required=False).clean(value) == expected


@pytest.mark.parametrize("value", NOT_STRICT_DATES)
def test_a_date_not_in_the_one_form_is_refused_on_every_form_of_the_page(
    researcher: Client, records: Records, value: str
) -> None:
    before = _stored()
    bodies = [
        (
            _change_url(records.institution),
            {"kind": "ministry", "country": "", "parent": "", "successor": "", "valid_from": value},
        ),
        (
            _add_name_url(records.institution),
            {
                "text": "TEST Dated name",
                "language": str(records.language),
                "kind": "official",
                "valid_from": value,
            },
        ),
        (_dates_url(records.other_name), {"valid_from": value, "valid_to": ""}),
    ]

    for url, body in bodies:
        assert researcher.post(url, body).status_code == 400, url

    assert _stored() == before


def test_a_full_padded_date_is_stored_as_entered(researcher: Client, records: Records) -> None:
    response = researcher.post(
        _dates_url(records.other_name), {"valid_from": "2001-02-03", "valid_to": ""}
    )

    assert response.status_code == 302
    assert InstitutionName.objects.get(public_id=records.other_name).valid_from == date(2001, 2, 3)
