"""The institution content of the registry's two pages over HTTP (ADR-0018 points 21 and
59 to 61, testing requirement 11; ADR-0019 points 11 to 15, Increment 3).

The browse page lists institutions with their names to every account that
reads the registry. The entry page holds the institution forms for every
account that reaches it, and each of its five changes is accepted for
`registry.institutions.manage` and refused without it. The country and
language forms are tested, and still refused without
`registry.reference.manage`, in test_registry_pages.py.
"""

import re
import uuid
from datetime import date
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from caipo.accounts.models import AuditEvent, AuditEventChange, User
from caipo.accounts.selectors import Permission, Role
from caipo.accounts.tests.fixtures import UserFactory
from caipo.accounts.tests.fixtures import verified as acting_verified
from caipo.registry import services
from caipo.registry.models import Country, Institution, InstitutionName, Language
from caipo.registry.services import NewName
from caipo.web import registry
from caipo.web.access import declared_access
from caipo.web.tests.helpers import signed_in, verified

pytestmark = [pytest.mark.services, pytest.mark.django_db]

PASSWORD = "TEST-passphrase-for-fixtures-only"
LOGIN = "/login/"
BROWSE = "/registry/"
ENTRY = "/registry/entry/"
SAVED = f"{ENTRY}?saved=1"
CREATE = "/registry/entry/institutions/create/"
UNKNOWN = uuid.UUID("00000000-0000-4000-8000-00000000ffff")

ACCOUNTS: dict[str, tuple[tuple[Role, ...], bool]] = {
    "reader": ((Role.READER,), False),
    "researcher": ((Role.RESEARCHER,), False),
    "reviewer-on-a-password": ((Role.REVIEWER,), False),
    "reviewer-verified": ((Role.REVIEWER,), True),
    "administrator-on-a-password": ((Role.ADMINISTRATOR,), False),
    "administrator-verified": ((Role.ADMINISTRATOR,), True),
    "no-role": ((), False),
}
# Written out here, not read from the policy: ADR-0018 points 11 to 14 and 59.
MAY_MAINTAIN = {"researcher", "reviewer-verified", "administrator-verified"}
REACH_BROWSE = {"reader", "researcher", "reviewer-verified", "administrator-verified"}


def _client(user_with_roles: UserFactory, account: str) -> Client:
    roles, second_factor = ACCOUNTS[account]
    user = user_with_roles(*roles)
    return verified(Client(), user) if second_factor else signed_in(Client(), user)


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
        self.name = InstitutionName.objects.filter(institution__public_id=self.institution).first()
        assert self.name is not None
        self.name_id = self.name.public_id


@pytest.fixture
def administrator(user_with_roles: UserFactory) -> User:
    return user_with_roles(Role.ADMINISTRATOR)


@pytest.fixture
def records(administrator: User) -> Records:
    return Records(administrator)


@pytest.fixture
def researcher_client(user_with_roles: UserFactory) -> Client:
    """A Researcher on a password alone, who maintains institutions."""
    return signed_in(Client(), user_with_roles(Role.RESEARCHER))


def _creation(records: Records, **values: str) -> dict[str, str]:
    return {
        "institution-kind": "university",
        "institution-country": str(records.country),
        "institution-parent": str(records.institution),
        "institution-successor": "",
        "institution-valid_from": "2001-02-03",
        "institution-valid_to": "",
        "first-name-text": "TEST University",
        "first-name-language": str(records.language),
        "first-name-kind": "official",
        "first-name-valid_from": "",
        "first-name-valid_to": "",
        **values,
    }


def _change_body(**values: str) -> dict[str, str]:
    return {
        "kind": "regulator",
        "country": "",
        "parent": "",
        "successor": "",
        "valid_from": "",
        "valid_to": "",
        **values,
    }


def _changes(
    institution: object, name: object, records: Records
) -> dict[str, tuple[str, dict[str, str]]]:
    """Return every institution POST, with a body that a permitted account could send."""
    return {
        "create an institution": (CREATE, _creation(records)),
        "change an institution": (
            f"/registry/entry/institutions/{institution}/change/",
            _change_body(),
        ),
        "add a name": (
            f"/registry/entry/institutions/{institution}/names/add/",
            {
                "text": "TEST Third name",
                "language": str(records.language),
                "kind": "transliteration",
                "valid_from": "",
                "valid_to": "",
            },
        ),
        "change the dates of a name": (
            f"/registry/entry/institution-names/{name}/dates/",
            {"valid_from": "2001-02-03", "valid_to": ""},
        ),
        "mark a name as entered in error": (
            f"/registry/entry/institution-names/{name}/mark-entered-in-error/",
            {},
        ),
    }


CHANGES = [
    "create an institution",
    "change an institution",
    "add a name",
    "change the dates of a name",
    "mark a name as entered in error",
]


def _post(records: Records, change: str) -> tuple[str, dict[str, str]]:
    return _changes(records.institution, records.name_id, records)[change]


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


# --- Declarations ---------------------------------------------------------------


def test_each_institution_view_declares_the_institutions_permission() -> None:
    for view in (
        registry.create_institution,
        registry.change_institution,
        registry.add_institution_name,
        registry.change_institution_name_dates,
        registry.mark_institution_name_entered_in_error,
    ):
        assert declared_access(view) == Permission.REGISTRY_INSTITUTIONS_MANAGE
    # ADR-0019 point 11: neither page's declaration changed in Increment 3.
    assert declared_access(registry.browse) == Permission.REGISTRY_READ
    assert declared_access(registry.entry) == Permission.REGISTRY_INSTITUTIONS_MANAGE


@pytest.mark.parametrize("change", CHANGES)
def test_every_institution_change_answers_only_a_post(
    researcher_client: Client, records: Records, change: str
) -> None:
    url, _ = _post(records, change)

    assert researcher_client.get(url).status_code == 405


# --- Changes: refused without the permission -------------------------------------


@pytest.mark.parametrize("change", CHANGES)
@pytest.mark.parametrize("account", sorted(set(ACCOUNTS) - MAY_MAINTAIN))
def test_every_change_is_refused_to_an_account_that_does_not_maintain_institutions(
    user_with_roles: UserFactory, records: Records, account: str, change: str
) -> None:
    url, body = _post(records, change)
    before = _stored()

    response = _client(user_with_roles, account).post(url, body)

    assert response.status_code == 403
    assert _stored() == before


@pytest.mark.parametrize("change", CHANGES)
def test_every_change_is_refused_to_an_anonymous_visitor(
    client: Client, records: Records, change: str
) -> None:
    url, body = _post(records, change)
    before = _stored()

    assert client.post(url, body).status_code == 403
    assert _stored() == before


@pytest.mark.parametrize("change", CHANGES)
def test_a_refusal_is_the_same_for_a_record_that_exists_and_one_that_does_not(
    user_with_roles: UserFactory, records: Records, change: str
) -> None:
    """Refused on the declaration, before any record is looked up (ADR-0018 point 52)."""
    client = signed_in(Client(), user_with_roles(Role.READER))
    existing, body = _post(records, change)
    missing, _ = _changes(UNKNOWN, UNKNOWN, records)[change]

    first, second = client.post(existing, body), client.post(missing, body)

    assert (first.status_code, second.status_code) == (403, 403)
    assert first.content == second.content


@pytest.mark.parametrize("change", CHANGES)
def test_the_service_refuses_for_itself_when_the_view_declares_too_little(
    user_with_roles: UserFactory,
    records: Records,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    """With every institution view opened to any reader, a Reader still changes nothing."""
    for view in (
        registry.create_institution,
        registry.change_institution,
        registry.add_institution_name,
        registry.change_institution_name_dates,
        registry.mark_institution_name_entered_in_error,
    ):
        monkeypatch.setattr(view, "caipo_access", Permission.REGISTRY_READ, raising=False)
    url, body = _post(records, change)
    before = _stored()

    response = signed_in(Client(), user_with_roles(Role.READER)).post(url, body)

    assert response.status_code == 403
    assert _stored() == before


@pytest.mark.parametrize("change", CHANGES)
def test_every_change_needs_a_csrf_token(
    user_with_roles: UserFactory, records: Records, change: str
) -> None:
    client = signed_in(Client(enforce_csrf_checks=True), user_with_roles(Role.RESEARCHER))
    url, body = _post(records, change)
    before = _stored()

    assert client.post(url, body).status_code == 403
    assert _stored() == before

    token = client.get(ENTRY).cookies["csrftoken"].value
    assert client.post(url, {**body, "csrfmiddlewaretoken": token}).status_code == 302
    assert _stored() != before


# --- Changes: made by every account that maintains institutions -------------------


@pytest.mark.parametrize("change", CHANGES)
@pytest.mark.parametrize("account", sorted(MAY_MAINTAIN))
def test_every_change_is_made_for_an_account_that_maintains_institutions(
    user_with_roles: UserFactory, records: Records, account: str, change: str
) -> None:
    roles, second_factor = ACCOUNTS[account]
    user = user_with_roles(*roles)
    client = verified(Client(), user) if second_factor else signed_in(Client(), user)
    url, body = _post(records, change)
    recorded = AuditEvent.objects.count()

    response = client.post(url, body)

    assert response.status_code == 302 and response["Location"] == SAVED
    assert set(AuditEvent.objects.order_by("id")[recorded:].values_list("actor_id", flat=True)) == {
        user.pk
    }


def test_an_institution_is_created_through_the_page_as_it_was_entered(
    researcher_client: Client, records: Records
) -> None:
    response = researcher_client.post(
        CREATE,
        _creation(
            records,
            **{
                "institution-valid_to": "2009-10-11",
                "first-name-text": "  TEST University  ",
                "first-name-valid_from": "2001-02-03",
            },
        ),
    )

    assert response.status_code == 302
    created = Institution.objects.latest("id")
    assert (
        created.kind,
        created.country.public_id if created.country else None,
        created.parent.public_id if created.parent else None,
        str(created.valid_from),
        str(created.valid_to),
    ) == ("university", records.country, records.institution, "2001-02-03", "2009-10-11")
    (name,) = InstitutionName.objects.filter(institution=created)
    assert (name.text, name.kind, str(name.valid_from), name.valid_to) == (
        "TEST University",
        "official",
        "2001-02-03",
        None,
    )


def test_a_name_is_marked_through_the_page_and_shown_apart(
    researcher_client: Client, records: Records
) -> None:
    url, body = _post(records, "mark a name as entered in error")

    assert researcher_client.post(url, body).status_code == 302

    page = _text(researcher_client.get(BROWSE))
    assert "Marked as entered in error, and not names of this institution" in page
    assert "<h3>TEST MIN</h3>" in page


# --- Changes that are refused, and what the page says -----------------------------


@pytest.mark.parametrize(
    "values",
    [
        {"institution-kind": "other"},
        {"institution-kind": ""},
        {"institution-valid_from": "2001-02"},
        {"institution-valid_from": "03/02/2001"},
        {"institution-valid_from": "2001-02-31"},
        {"institution-valid_from": "2002-01-01", "institution-valid_to": "2001-01-01"},
        {"institution-country": "not-a-uuid"},
        {"first-name-text": ""},
        {"first-name-text": "   "},
        {"first-name-text": "T" * 501},
        {"first-name-text": "TEST \x00 name"},
        {"first-name-language": ""},
        {"first-name-kind": "nickname"},
    ],
)
def test_an_institution_that_is_not_valid_is_not_saved_and_the_page_says_so(
    researcher_client: Client, records: Records, values: dict[str, str]
) -> None:
    before = _stored()

    response = researcher_client.post(CREATE, _creation(records, **values))

    assert response.status_code == 400
    assert "Nothing was saved. Choose a kind from the list" in _text(response)
    assert _stored() == before


def test_what_was_typed_is_shown_again_when_a_creation_is_refused(
    researcher_client: Client, records: Records
) -> None:
    page = _text(
        researcher_client.post(
            CREATE,
            _creation(
                records,
                **{"first-name-text": "TEST Typed name", "institution-valid_from": "2001-02"},
            ),
        )
    )

    assert 'value="TEST Typed name"' in page
    assert 'value="2001-02"' in page


@pytest.mark.parametrize(
    ("make", "change", "values", "status", "message"),
    [
        (
            "deactivated country",
            "create an institution",
            {},
            409,
            "A deactivated country or language cannot be newly referred to.",
        ),
        (
            "nothing",
            "change an institution",
            {"parent": "itself"},
            409,
            "cannot be its own parent or its own successor",
        ),
        (
            "nothing",
            "change an institution",
            {"successor": "other"},
            409,
            "An institution that names a successor has a valid-to date",
        ),
        (
            "nothing",
            "change an institution",
            {"kind": "ministry", "country": "country"},
            409,
            "Nothing was changed: the record is already as you asked.",
        ),
        (
            "one name",
            "mark a name as entered in error",
            {},
            409,
            "only name that is not marked as entered in error. Add the right name first.",
        ),
        (
            "nothing",
            "change the dates of a name",
            {"valid_from": "", "valid_to": ""},
            409,
            "Nothing was changed: the record is already as you asked.",
        ),
    ],
)
def test_a_change_the_service_refuses_is_not_saved_and_the_page_says_why(
    researcher_client: Client,
    administrator: User,
    records: Records,
    make: str,
    change: str,
    values: dict[str, str],
    status: int,
    message: str,
) -> None:
    actor = acting_verified(administrator)
    if make == "deactivated country":
        services.deactivate_country(actor=actor, public_id=records.country)
    if make == "one name":
        services.mark_institution_name_entered_in_error(actor=actor, public_id=records.other_name)
    other = services.create_institution(
        actor=actor,
        kind="company",
        first_name=NewName(text="TEST Company", language=records.language, kind="official"),
    )
    named = {
        "itself": str(records.institution),
        "other": str(other),
        "country": str(records.country),
    }
    url, body = _post(records, change)
    before = _stored()

    response = researcher_client.post(
        url, {**body, **{key: named.get(value, value) for key, value in values.items()}}
    )

    assert response.status_code == status
    assert message in _text(response)
    assert _stored() == before


def test_every_refusal_of_an_institution_service_is_answered_and_nothing_else_is(
    researcher_client: Client, records: Records, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An error that no refusal names is raised as it is, and is not taken for one."""
    assert set(registry.INSTITUTION_REFUSALS) == {
        services.InvalidEntryError,
        services.RecordNotFoundError,
        services.NoChangeError,
        services.DeactivatedReferenceError,
        services.CycleError,
        services.SuccessionError,
        services.LastNameError,
    }

    def fail(**_: object) -> None:
        raise services.DuplicateCodeError("TEST not a refusal of this operation")

    monkeypatch.setattr(services, "change_institution", fail)
    url, body = _post(records, "change an institution")

    with pytest.raises(services.DuplicateCodeError, match="TEST not a refusal"):
        researcher_client.post(url, body)


@pytest.mark.parametrize("change", CHANGES[1:])
def test_a_change_to_a_record_that_does_not_exist_is_refused_and_the_page_says_so(
    researcher_client: Client, records: Records, change: str
) -> None:
    url, body = _changes(UNKNOWN, UNKNOWN, records)[change]
    before = _stored()

    response = researcher_client.post(url, body)

    assert response.status_code == 404
    assert "Nothing was changed: there is no such record." in _text(response)
    assert _stored() == before


def test_a_name_and_an_institution_are_not_reached_through_each_others_identifier(
    researcher_client: Client, records: Records
) -> None:
    before = _stored()

    wrong_name = f"/registry/entry/institution-names/{records.institution}/dates/"
    wrong_institution = f"/registry/entry/institutions/{records.name_id}/change/"

    assert researcher_client.post(wrong_name, {"valid_from": "2001-02-03"}).status_code == 404
    assert researcher_client.post(wrong_institution, _change_body()).status_code == 404
    assert _stored() == before


def test_no_institution_path_holds_an_internal_key(
    researcher_client: Client, records: Records
) -> None:
    key = Institution.objects.get(public_id=records.institution).pk
    page = _text(researcher_client.get(ENTRY))

    assert researcher_client.post(f"/registry/entry/institutions/{key}/change/").status_code == 404
    assert f"/institutions/{key}/" not in page
    assert f'value="{key}"' not in page


# --- The entry page ----------------------------------------------------------------


def test_the_entry_page_says_that_a_date_not_known_to_the_day_is_left_empty(
    researcher_client: Client,
) -> None:
    """ADR-0018 point 21: nothing can enforce it, so the page says so."""
    page = _text(researcher_client.get(ENTRY))

    assert (
        "A date that is not known to the day is left empty: do not enter the first of January"
        " or the first of a month to stand for a year or a month."
    ) in page


def test_the_entry_page_shows_each_institution_with_what_is_stored(
    researcher_client: Client, administrator: User, records: Records
) -> None:
    actor = acting_verified(administrator)
    parent = services.create_institution(
        actor=actor,
        kind="legislature",
        first_name=NewName(text="TEST Parent", language=records.language, kind="official"),
    )
    services.change_institution(
        actor=actor,
        public_id=records.institution,
        kind="regulator",
        country=records.country,
        parent=parent,
        successor=None,
        valid_from=None,
        valid_to=None,
    )

    page = _text(researcher_client.get(ENTRY))

    section = page[page.index("<h3>TEST Ministry</h3>") : page.index("<h3>TEST Parent</h3>")]
    assert '<option value="regulator" selected>' in section
    assert f'<option value="{records.country}" selected>' in section
    assert f'<option value="{parent}" selected>' in section
    # An institution is not offered as its own parent or successor.
    assert f'<option value="{records.institution}"' not in section
    assert "Mark as entered in error" in section


def test_the_only_unmarked_name_is_offered_no_mark(
    researcher_client: Client, administrator: User, records: Records
) -> None:
    services.mark_institution_name_entered_in_error(
        actor=acting_verified(administrator), public_id=records.other_name
    )

    page = _text(researcher_client.get(ENTRY))

    assert "Mark as entered in error" not in page.split("<h4>Names</h4>")[1].split("<h4>")[0]


def test_a_deactivated_country_and_language_are_offered_as_deactivated(
    researcher_client: Client, administrator: User, records: Records
) -> None:
    actor = acting_verified(administrator)
    services.deactivate_country(actor=actor, public_id=records.country)
    services.deactivate_language(actor=actor, public_id=records.language)

    page = _text(researcher_client.get(ENTRY))

    assert "XA · TEST Country A · Deactivated" in page
    assert "qaa-Qaaa · TEST Language A · Deactivated" in page


# --- The browse page ---------------------------------------------------------------


@pytest.mark.parametrize("account", sorted(ACCOUNTS))
def test_each_account_that_reads_the_registry_sees_the_institutions(
    user_with_roles: UserFactory, records: Records, account: str
) -> None:
    response = _client(user_with_roles, account).get(BROWSE)

    if account in REACH_BROWSE:
        assert response.status_code == 200
        assert "<h3>TEST Ministry</h3>" in _text(response)
    else:
        assert response.status_code == 403


def test_the_browse_page_lists_an_institution_with_its_attributes_and_names(
    user_with_roles: UserFactory, administrator: User, records: Records
) -> None:
    actor = acting_verified(administrator)
    successor = services.create_institution(
        actor=actor,
        kind="company",
        first_name=NewName(text="TEST Successor", language=records.language, kind="official"),
    )
    services.change_institution(
        actor=actor,
        public_id=records.institution,
        kind="ministry",
        country=records.country,
        parent=None,
        successor=successor,
        valid_from=None,
        valid_to=date(2004, 5, 6),
    )
    services.change_institution_name_dates(
        actor=actor,
        public_id=records.name_id,
        valid_from=date(2001, 2, 3),
        valid_to=None,
    )

    page = _text(signed_in(Client(), user_with_roles(Role.READER)).get(BROWSE))
    section = page[page.index("<h3>TEST Ministry</h3>") : page.index("<h3>TEST Successor</h3>")]
    flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", section)).strip()

    assert flat == (
        "TEST Ministry Kind Ministry Country XA Parent institution None Valid from Not recorded"
        " Valid to 2004-05-06 Successor TEST Successor Names Name Language Kind of name"
        " Valid from Valid to TEST Ministry qaa-Qaaa Official 2001-02-03 Not recorded TEST MIN"
        " qaa-Qaaa Abbreviation Not recorded Not recorded"
    )


def test_a_name_is_escaped_on_both_pages(
    researcher_client: Client, administrator: User, records: Records
) -> None:
    services.create_institution(
        actor=acting_verified(administrator),
        kind="media_outlet",
        first_name=NewName(
            text='TEST <script>alert("x")</script> & more',
            language=records.language,
            kind="official",
        ),
    )

    for url in (BROWSE, ENTRY):
        page = _text(researcher_client.get(url))

        assert "<script>alert" not in page
        assert "TEST &lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; more" in page


def test_the_browse_page_offers_nothing_to_change_and_shows_no_account(
    researcher_client: Client, administrator: User, records: Records
) -> None:
    page = _text(researcher_client.get(BROWSE))

    assert "<form" not in page and "<input" not in page and "<button" not in page
    assert administrator.email not in page and "@caipo.test" not in page


def test_reading_the_pages_changes_and_records_nothing(
    researcher_client: Client, records: Records
) -> None:
    before = _stored()

    researcher_client.get(BROWSE)
    researcher_client.get(ENTRY)

    assert _stored() == before


# --- Through a real sign-in --------------------------------------------------------


def test_a_researcher_who_signs_in_with_a_password_maintains_institutions(
    user_with_roles: UserFactory, records: Records
) -> None:
    user = user_with_roles(Role.RESEARCHER)
    user.set_password(PASSWORD)
    user.save()
    client = Client()
    assert client.post(LOGIN, {"email": user.email, "password": PASSWORD}).status_code == 302

    assert client.post(CREATE, _creation(records)).status_code == 302

    assert reverse("registry-institution-create") == CREATE
    assert list(AuditEvent.objects.filter(actor=user).values_list("action", "target_type")) == [
        ("created", "registry.institution"),
        ("created", "registry.institution_name"),
    ]
