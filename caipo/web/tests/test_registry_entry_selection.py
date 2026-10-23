"""The entry page opens the change form of one institution at a time (finding L4).

Before this, every institution had a change form whose parent and successor
lists named every other institution, and the page grew with the square of
their number. Now only the institution `?change=<public id>` names has its
change form; every other one is shown as stored, with a link that opens its
form. The parameter chooses what the page shows and nothing else: the
declared access, the CSRF check, and the services decide as before, and a
refused submission comes back with the same institution open.
"""

import re
import uuid
from typing import Any

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from caipo.accounts.models import AuditEvent, User
from caipo.accounts.selectors import Role
from caipo.accounts.tests.fixtures import UserFactory
from caipo.accounts.tests.fixtures import verified as acting_verified
from caipo.registry import services
from caipo.registry.models import Country, Institution, InstitutionName, Language
from caipo.registry.services import NewName
from caipo.web.tests.helpers import signed_in, verified

pytestmark = [pytest.mark.services, pytest.mark.django_db]

ENTRY = "/registry/entry/"
SAVED = f"{ENTRY}?saved=1"
UNKNOWN = uuid.UUID("00000000-0000-4000-8000-00000000ffff")
CHANGE_ACTION = re.compile(r'action="/registry/entry/institutions/([0-9a-f-]+)/change/')
INVALID_SELECTION = "the link does not name one institution"
UNKNOWN_SELECTION = "there is no such institution"

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


class Records:
    """A country, a language, and two institutions; the ministry has two names and a parent."""

    def __init__(self, administrator: User) -> None:
        actor = acting_verified(administrator)
        self.actor = actor
        self.country = services.create_country(
            actor=actor, alpha2="XA", alpha3="XAA", name_en="TEST Country A"
        )
        self.language = services.create_language(
            actor=actor, code="qaa", script_code="Qaaa", name_en="TEST Language A"
        )
        self.agency = services.create_institution(
            actor=actor,
            kind="statistical_agency",
            first_name=NewName(text="TEST Agency", language=self.language, kind="official"),
        )
        self.ministry = services.create_institution(
            actor=actor,
            kind="ministry",
            country=self.country,
            parent=self.agency,
            first_name=NewName(text="TEST Ministry", language=self.language, kind="official"),
        )
        self.other_name = services.add_institution_name(
            actor=actor,
            institution=self.ministry,
            name=NewName(text="TEST MIN", language=self.language, kind="abbreviation"),
        )
        name = InstitutionName.objects.filter(institution__public_id=self.ministry).first()
        assert name is not None
        self.name = name.public_id


@pytest.fixture
def administrator(user_with_roles: UserFactory) -> User:
    return user_with_roles(Role.ADMINISTRATOR)


@pytest.fixture
def records(administrator: User) -> Records:
    return Records(administrator)


@pytest.fixture
def researcher(user_with_roles: UserFactory) -> Client:
    """A Researcher on a password alone, who maintains institutions."""
    return signed_in(Client(), user_with_roles(Role.RESEARCHER))


def _client(user_with_roles: UserFactory, account: str) -> Client:
    roles, second_factor = ACCOUNTS[account]
    user = user_with_roles(*roles)
    return verified(Client(), user) if second_factor else signed_in(Client(), user)


def _text(response: Any) -> str:
    return str(response.content.decode())


def _opened(page: str) -> list[str]:
    """The institutions whose change form the page holds."""
    return CHANGE_ACTION.findall(page)


def _section(page: str, institution: uuid.UUID) -> str:
    start = page.index(f'<section id="institution-{institution}">')
    return page[start : page.index("</section>", start)]


def _change_url(institution: uuid.UUID) -> str:
    return f"/registry/entry/institutions/{institution}/change/"


def _change(**values: str) -> dict[str, str]:
    return {
        "kind": "regulator",
        "country": "",
        "parent": "",
        "successor": "",
        "valid_from": "",
        "valid_to": "",
        **values,
    }


def _stored() -> dict[str, list[Any]]:
    return {
        "countries": list(Country.objects.order_by("id").values()),
        "languages": list(Language.objects.order_by("id").values()),
        "institutions": list(Institution.objects.order_by("id").values()),
        "names": list(InstitutionName.objects.order_by("id").values()),
        "audit events": list(AuditEvent.objects.order_by("id").values()),
    }


# --- Selection ----------------------------------------------------------------------


def test_without_a_selection_no_change_form_is_shown(researcher: Client, records: Records) -> None:
    response = researcher.get(ENTRY)

    assert response.status_code == 200
    page = _text(response)
    assert _opened(page) == []
    assert "Change the institution" not in page


def test_each_institution_is_shown_as_stored_with_a_link_to_its_form(
    researcher: Client, records: Records
) -> None:
    page = _text(researcher.get(ENTRY))

    for institution in (records.agency, records.ministry):
        assert f'href="{ENTRY}?change={institution}#institution-{institution}"' in _section(
            page, institution
        )
    ministry = " ".join(re.sub(r"<[^>]+>", " ", _section(page, records.ministry)).split())
    assert "Kind Ministry Country XA Parent institution TEST Agency" in ministry
    assert "Change TEST Ministry" in ministry


def test_a_selection_opens_that_institutions_form_only(
    researcher: Client, records: Records
) -> None:
    response = researcher.get(f"{ENTRY}?change={records.ministry}")

    assert response.status_code == 200
    page = _text(response)
    assert _opened(page) == [str(records.ministry)]
    ministry = _section(page, records.ministry)
    assert '<option value="ministry" selected>' in ministry
    assert f'<option value="{records.country}" selected>' in ministry
    assert f'<option value="{records.agency}" selected>' in ministry
    # It is not offered as its own parent or successor.
    assert f'<option value="{records.ministry}"' not in ministry
    assert f'<a href="{ENTRY}">Close the form</a>' in ministry
    # The other institution keeps its link.
    assert f"?change={records.agency}#" in _section(page, records.agency)


def test_with_a_selection_every_form_posts_with_it(
    user_with_roles: UserFactory, records: Records
) -> None:
    client = _client(user_with_roles, "administrator-verified")

    page = _text(client.get(f"{ENTRY}?change={records.agency}"))

    actions = re.findall(r'<form method="post" action="([^"]+)"', page)
    assert len(actions) == 15
    assert all(action.endswith(f"?change={records.agency}") for action in actions)


def test_without_a_selection_no_form_posts_with_one(researcher: Client, records: Records) -> None:
    page = _text(researcher.get(ENTRY))

    actions = re.findall(r'<form method="post" action="([^"]+)"', page)
    assert actions
    assert not any("?" in action for action in actions)


@pytest.mark.parametrize(
    "value",
    ["", "not-an-identifier", "1234", "<script>alert(1)</script>", "x" * 5000],
    ids=["empty", "text", "digits", "markup", "very-long"],
)
def test_a_selection_that_is_not_an_identifier_is_refused_with_400(
    researcher: Client, records: Records, value: str
) -> None:
    response = researcher.get(ENTRY, {"change": value})

    assert response.status_code == 400
    page = _text(response)
    assert INVALID_SELECTION in page
    assert _opened(page) == []
    if value:
        assert value not in page


def test_a_repeated_selection_is_refused_with_400(researcher: Client, records: Records) -> None:
    response = researcher.get(f"{ENTRY}?change={records.ministry}&change={records.agency}")

    assert response.status_code == 400
    assert INVALID_SELECTION in _text(response)
    assert _opened(_text(response)) == []


def test_a_selection_of_no_institution_is_refused_with_404(
    researcher: Client, records: Records
) -> None:
    for identifier in (UNKNOWN, records.name, records.country):
        response = researcher.get(f"{ENTRY}?change={identifier}")

        assert response.status_code == 404
        page = _text(response)
        assert UNKNOWN_SELECTION in page
        assert _opened(page) == []


def test_a_selection_changes_nothing_stored(researcher: Client, records: Records) -> None:
    before = _stored()

    researcher.get(f"{ENTRY}?change={records.ministry}")
    researcher.get(f"{ENTRY}?change={UNKNOWN}")
    researcher.get(f"{ENTRY}?change=not-an-identifier")

    assert _stored() == before


def test_a_label_in_the_link_is_escaped(researcher: Client, records: Records) -> None:
    services.create_institution(
        actor=records.actor,
        kind="company",
        first_name=NewName(
            text="TEST <b>Bold</b> & Co", language=records.language, kind="official"
        ),
    )

    page = _text(researcher.get(ENTRY))

    assert "Change TEST &lt;b&gt;Bold&lt;/b&gt; &amp; Co" in page
    assert "<b>Bold</b>" not in page


# --- Access -------------------------------------------------------------------------


@pytest.mark.parametrize("account", sorted(ACCOUNTS))
def test_a_selection_grants_nothing(
    user_with_roles: UserFactory, records: Records, account: str
) -> None:
    response = _client(user_with_roles, account).get(f"{ENTRY}?change={records.ministry}")

    if account in MAY_MAINTAIN:
        assert response.status_code == 200
        assert _opened(_text(response)) == [str(records.ministry)]
    else:
        assert response.status_code == 403
        assert _opened(_text(response)) == []


def test_an_anonymous_visitor_is_refused_with_a_selection(records: Records) -> None:
    response = Client().get(f"{ENTRY}?change={records.ministry}")

    assert response.status_code == 403
    assert _opened(_text(response)) == []


@pytest.mark.parametrize("account", sorted(set(ACCOUNTS) - MAY_MAINTAIN))
def test_a_change_with_a_selection_is_refused_without_the_permission(
    user_with_roles: UserFactory, records: Records, account: str
) -> None:
    before = _stored()

    response = _client(user_with_roles, account).post(
        f"{_change_url(records.ministry)}?change={records.ministry}", _change()
    )

    assert response.status_code == 403
    assert _stored() == before


def test_a_change_with_a_selection_is_refused_without_a_csrf_token(
    user_with_roles: UserFactory, records: Records
) -> None:
    client = signed_in(Client(enforce_csrf_checks=True), user_with_roles(Role.RESEARCHER))
    before = _stored()

    response = client.post(f"{_change_url(records.ministry)}?change={records.ministry}", _change())

    assert response.status_code == 403
    assert _stored() == before


def test_every_form_with_a_selection_carries_a_csrf_token(
    user_with_roles: UserFactory, records: Records
) -> None:
    client = _client(user_with_roles, "administrator-verified")

    page = _text(client.get(f"{ENTRY}?change={records.ministry}"))

    forms = page.split('<form method="post"')[1:]
    assert len(forms) == 15
    assert all('name="csrfmiddlewaretoken"' in form.split("</form>")[0] for form in forms)


# --- Saving and refusals ------------------------------------------------------------


def test_a_saved_change_redirects_without_the_selection(
    researcher: Client, records: Records
) -> None:
    events = AuditEvent.objects.count()

    response = researcher.post(
        f"{_change_url(records.ministry)}?change={records.ministry}",
        _change(country=str(records.country)),
    )

    assert response.status_code == 302
    assert response["Location"] == SAVED
    assert Institution.objects.get(public_id=records.ministry).kind == "regulator"
    assert AuditEvent.objects.count() == events + 1


def test_a_refused_change_opens_its_institutions_form_as_typed(
    researcher: Client, records: Records
) -> None:
    before = _stored()

    response = researcher.post(
        _change_url(records.agency), _change(kind="university", valid_from="2020-1-1")
    )

    assert response.status_code == 400
    page = _text(response)
    assert _opened(page) == [str(records.agency)]
    agency = _section(page, records.agency)
    assert '<option value="university" selected>' in agency
    assert 'value="2020-1-1"' in agency
    assert '<span role="alert">' in agency
    # The other forms post with the opened institution.
    assert f'names/add/?change={records.agency}"' in page
    assert _stored() == before


def test_a_change_refused_by_the_service_keeps_its_form_open(
    researcher: Client, records: Records
) -> None:
    before = _stored()

    response = researcher.post(
        f"{_change_url(records.agency)}?change={records.agency}",
        _change(kind="university", parent=str(records.ministry)),
    )

    assert response.status_code == 409
    page = _text(response)
    assert "cannot be its own parent" in page
    assert _opened(page) == [str(records.agency)]
    assert f'<option value="{records.ministry}" selected>' in _section(page, records.agency)
    assert _stored() == before


def test_a_change_of_no_institution_opens_no_form(researcher: Client, records: Records) -> None:
    response = researcher.post(f"{_change_url(UNKNOWN)}?change={UNKNOWN}", _change())

    assert response.status_code == 404
    page = _text(response)
    assert "there is no such record" in page
    assert _opened(page) == []


def test_a_refused_new_name_keeps_the_selection_and_what_was_typed(
    researcher: Client, records: Records
) -> None:
    before = _stored()

    response = researcher.post(
        f"/registry/entry/institutions/{records.agency}/names/add/?change={records.ministry}",
        {"text": "TEST typed name", "language": str(records.language), "kind": "nonsense"},
    )

    assert response.status_code == 400
    page = _text(response)
    assert _opened(page) == [str(records.ministry)]
    assert 'value="TEST typed name"' in _section(page, records.agency)
    assert _stored() == before


def test_refused_dates_keep_the_selection_and_what_was_typed(
    researcher: Client, records: Records
) -> None:
    before = _stored()

    response = researcher.post(
        f"/registry/entry/institution-names/{records.name}/dates/?change={records.agency}",
        {"valid_from": "2020-1-1", "valid_to": ""},
    )

    assert response.status_code == 400
    page = _text(response)
    assert _opened(page) == [str(records.agency)]
    assert 'value="2020-1-1"' in _section(page, records.ministry)
    assert _stored() == before


def test_an_unconfirmed_mark_keeps_the_selection(researcher: Client, records: Records) -> None:
    before = _stored()

    response = researcher.post(
        f"/registry/entry/institution-names/{records.name}/mark-entered-in-error/"
        f"?change={records.agency}",
        {},
    )

    assert response.status_code == 400
    page = _text(response)
    assert "only when the confirmation is ticked" in page
    assert _opened(page) == [str(records.agency)]
    assert _stored() == before


def test_a_refused_creation_keeps_the_selection_and_what_was_typed(
    researcher: Client, records: Records
) -> None:
    before = _stored()

    response = researcher.post(
        f"/registry/entry/institutions/create/?change={records.agency}",
        {
            "institution-kind": "nonsense",
            "first-name-text": "TEST typed institution",
            "first-name-language": str(records.language),
            "first-name-kind": "official",
        },
    )

    assert response.status_code == 400
    page = _text(response)
    assert _opened(page) == [str(records.agency)]
    assert 'value="TEST typed institution"' in page
    assert _stored() == before


def test_a_refused_country_keeps_the_selection(
    user_with_roles: UserFactory, records: Records
) -> None:
    client = _client(user_with_roles, "administrator-verified")
    before = _stored()

    response = client.post(
        f"/registry/entry/countries/create/?change={records.agency}",
        {"country-alpha2": "x", "country-alpha3": "XBB", "country-name_en": "TEST Country B"},
    )

    assert response.status_code == 400
    page = _text(response)
    assert _opened(page) == [str(records.agency)]
    assert _stored() == before


def test_a_refusal_with_a_bad_selection_reports_the_refusal(
    researcher: Client, records: Records
) -> None:
    response = researcher.post(
        f"{_change_url(records.agency)}?change=not-an-identifier",
        _change(valid_from="2020-1-1"),
    )

    assert response.status_code == 400
    page = _text(response)
    assert "Nothing was saved." in page
    assert INVALID_SELECTION not in page
    # The refused change opens its own form, whatever the parameter says.
    assert _opened(page) == [str(records.agency)]


def test_a_refused_new_name_with_a_selection_of_no_institution_opens_no_form(
    researcher: Client, records: Records
) -> None:
    response = researcher.post(
        f"/registry/entry/institutions/{records.agency}/names/add/?change={UNKNOWN}",
        {"text": "", "language": str(records.language), "kind": "official"},
    )

    assert response.status_code == 400
    page = _text(response)
    assert UNKNOWN_SELECTION not in page
    assert _opened(page) == []


# --- Growth -------------------------------------------------------------------------


def _measure(client: Client, url: str) -> tuple[int, int]:
    with CaptureQueriesContext(connection) as queries:
        page = _text(client.get(url))
    return page.count("<option"), len(queries)


def test_the_page_grows_linearly_with_the_number_of_institutions(
    researcher: Client, records: Records
) -> None:
    measured: dict[str, list[tuple[int, int]]] = {"closed": [], "opened": []}
    for step in range(3):
        for number in range(4):
            services.create_institution(
                actor=records.actor,
                kind="company",
                first_name=NewName(
                    text=f"TEST Company {step}-{number}", language=records.language, kind="official"
                ),
            )
        measured["closed"].append(_measure(researcher, ENTRY))
        measured["opened"].append(_measure(researcher, f"{ENTRY}?change={records.ministry}"))

    for page, ((first, q1), (second, q2), (third, q3)) in measured.items():
        # Equal steps in the number of institutions add equal numbers of
        # options: the growth is linear, not quadratic.
        assert third - second == second - first, page
        # The number of queries does not depend on the number of institutions.
        assert q1 == q2 == q3, page
