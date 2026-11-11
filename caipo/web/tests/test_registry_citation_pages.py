"""The sources of registry names and dates on the registry pages (ADR-0023)."""

import pytest
from django.test import Client

from caipo.accounts.models import AuditEvent, User
from caipo.accounts.selectors import Role
from caipo.accounts.tests.fixtures import UserFactory
from caipo.accounts.tests.fixtures import verified as acting_verified
from caipo.registry import services
from caipo.registry.models import Institution, InstitutionName
from caipo.registry.services import NewName
from caipo.registry.tests.helpers import TEST_SOURCE
from caipo.web.tests.helpers import signed_in

pytestmark = [pytest.mark.services, pytest.mark.django_db]

BROWSE = "/registry/"
ENTRY = "/registry/entry/"


class Records:
    """An institution with a sourced name, and a name entered before sources were recorded."""

    def __init__(self, administrator: User) -> None:
        actor = acting_verified(administrator)
        country = services.create_country(
            actor=actor, alpha2="XA", alpha3="XAA", name_en="TEST Country A"
        )
        language = services.create_language(
            actor=actor, code="qaa", script_code="Qaaa", name_en="TEST Language A"
        )
        self.institution = services.create_institution(
            actor=actor,
            kind="ministry",
            country=country,
            first_name=NewName(
                text="TEST Ministry", language=language, kind="official", source=TEST_SOURCE
            ),
        )
        owner = Institution.objects.get(public_id=self.institution)
        # As a name entered before migration 0003 is: written past the services.
        self.older = InstitutionName.objects.create(
            institution=owner,
            text="TEST MIN",
            language=owner.names.get().language,
            kind="abbreviation",
        ).public_id


@pytest.fixture
def records(user_with_roles: UserFactory) -> Records:
    return Records(user_with_roles(Role.ADMINISTRATOR))


@pytest.fixture
def researcher(user_with_roles: UserFactory) -> Client:
    return signed_in(Client(), user_with_roles(Role.RESEARCHER))


def _source_url(name: object) -> str:
    return f"/registry/entry/institution-names/{name}/source/"


def test_a_source_is_shown_as_a_link_that_leaves_the_application_safely(
    records: Records, user_with_roles: UserFactory
) -> None:
    page = signed_in(Client(), user_with_roles(Role.READER)).get(BROWSE).content.decode()

    assert (
        f'<a href="{TEST_SOURCE.url}" rel="noopener noreferrer nofollow" target="_blank">'
        f"{TEST_SOURCE.title}</a>"
    ) in page
    assert "read on 2026-01-02" in page
    assert "No source recorded" in page


def test_the_form_to_add_a_source_is_offered_for_a_name_without_one_only(
    records: Records, researcher: Client
) -> None:
    page = researcher.get(ENTRY).content.decode()

    assert f'action="{_source_url(records.older)}"' in page
    sourced = InstitutionName.objects.exclude(public_id=records.older).get().public_id
    assert f'action="{_source_url(sourced)}"' not in page


def test_a_source_added_on_the_page_is_recorded_and_audited(
    records: Records, researcher: Client
) -> None:
    response = researcher.post(
        _source_url(records.older),
        {
            "source_url": "https://source.example/older",
            "source_title": "TEST Older page",
            "source_accessed_on": "2026-01-03",
        },
    )

    assert response.status_code == 302
    citation = InstitutionName.objects.get(public_id=records.older).citation
    assert citation is not None and citation.title == "TEST Older page"
    assert AuditEvent.objects.latest("id").changes.get().field == "citation"


@pytest.mark.parametrize(
    "body",
    [
        {"source_url": "", "source_title": "TEST", "source_accessed_on": "2026-01-03"},
        {
            "source_url": "javascript:alert(1)",
            "source_title": "TEST",
            "source_accessed_on": "2026-01-03",
        },
        {"source_url": "https://source.example/", "source_title": "TEST", "source_accessed_on": ""},
    ],
)
def test_an_incomplete_or_unsafe_source_is_refused_and_nothing_is_recorded(
    records: Records, researcher: Client, body: dict[str, str]
) -> None:
    events = AuditEvent.objects.count()

    response = researcher.post(_source_url(records.older), body)

    assert response.status_code == 400
    assert InstitutionName.objects.get(public_id=records.older).citation is None
    assert AuditEvent.objects.count() == events


def test_a_name_with_a_source_is_not_given_another_on_the_page(
    records: Records, researcher: Client
) -> None:
    sourced = InstitutionName.objects.exclude(public_id=records.older).get()
    before = sourced.citation_id

    response = researcher.post(
        _source_url(sourced.public_id),
        {
            "source_url": "https://source.example/other",
            "source_title": "TEST Other",
            "source_accessed_on": "2026-01-03",
        },
    )

    assert response.status_code == 409
    assert "has a source already" in response.content.decode()
    assert InstitutionName.objects.get(pk=sourced.pk).citation_id == before


def test_a_reader_cannot_add_a_source(records: Records, user_with_roles: UserFactory) -> None:
    reader = signed_in(Client(), user_with_roles(Role.READER))

    response = reader.post(
        _source_url(records.older),
        {
            "source_url": "https://source.example/",
            "source_title": "T",
            "source_accessed_on": "2026-01-03",
        },
    )

    assert response.status_code == 403
    assert InstitutionName.objects.get(public_id=records.older).citation is None
