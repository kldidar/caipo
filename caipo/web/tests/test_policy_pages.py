"""The demonstrator's policy and source pages (ADR-0020)."""

import re
from datetime import date
from typing import Any

import pytest
from django.test import Client

from caipo.accounts.selectors import Role
from caipo.accounts.tests.fixtures import UserFactory
from caipo.policies import services as policy_services
from caipo.policies.models import Policy, PolicyEvent
from caipo.registry.tests.helpers import ActingAs
from caipo.sources.models import Source
from caipo.sources.tests.helpers import World, make_document, make_source, make_world
from caipo.web.tests.helpers import signed_in, verified

pytestmark = pytest.mark.django_db


def _text(response: Any) -> str:
    return str(response.content.decode())


@pytest.fixture
def world(db: None) -> World:
    return make_world()


@pytest.fixture
def researcher_client(user_with_roles: UserFactory) -> Client:
    return signed_in(Client(), user_with_roles(Role.RESEARCHER))


@pytest.fixture
def reader_client(user_with_roles: UserFactory) -> Client:
    return signed_in(Client(), user_with_roles(Role.READER))


@pytest.fixture
def records(acting_as: ActingAs, world: World) -> dict[str, Any]:
    actor = acting_as(Role.RESEARCHER)
    source = make_source(actor, world)
    document = make_document(actor, world, source)
    core = policy_services.create_policy(
        actor=actor,
        data_class="demonstration",
        country=world.demo_country,
        policy_type="strategy",
        title="TEST Core AI Strategy",
        title_language=world.language,
        corpus_assignment="core",
        ai_focus="ai_focused",
        assignment_reason="TEST core reason",
    )
    contextual = policy_services.create_policy(
        actor=actor,
        data_class="demonstration",
        country=world.demo_country,
        policy_type="concept",
        title="TEST Contextual Digital Concept",
        title_language=world.language,
        corpus_assignment="contextual",
        contextual_category="digital_economy",
        assignment_reason="TEST contextual reason",
    )
    policy_services.link_document(actor=actor, policy=core, document=document, role="enacting_text")
    policy_services.record_event(
        actor=actor,
        policy=core,
        event_type="adopted",
        effective_date=date(2025, 1, 2),
        document=document,
    )
    return {"source": source, "document": document, "core": core, "contextual": contextual}


# --- Access --------------------------------------------------------------------------------------


@pytest.mark.parametrize("url", ["/policies/", "/sources/", "/policies/new/", "/sources/new/"])
def test_an_anonymous_visitor_reaches_no_workspace_page(client: Client, url: str) -> None:
    assert client.get(url).status_code in (302, 403)


def test_a_reader_reads_but_is_offered_nothing_to_change(
    reader_client: Client, records: dict[str, Any]
) -> None:
    listing = _text(reader_client.get("/policies/"))
    page = _text(reader_client.get(f"/policies/{records['core']}/"))

    assert "TEST Core AI Strategy" in listing
    assert "Add a policy" not in listing
    assert '<form method="post"' not in page
    assert reader_client.get("/policies/new/").status_code == 403
    assert reader_client.post(f"/policies/{records['core']}/assignment/", {}).status_code == 403


def test_an_administrator_without_a_research_role_reads_no_policy(
    user_with_roles: UserFactory, records: dict[str, Any]
) -> None:
    client = verified(Client(), user_with_roles(Role.ADMINISTRATOR))

    assert client.get("/policies/").status_code == 403
    assert client.get(f"/sources/{records['source']}/").status_code == 403


def test_an_unknown_policy_or_source_is_not_found(researcher_client: Client) -> None:
    unknown = "00000000-0000-4000-8000-00000000ffff"

    assert researcher_client.get(f"/policies/{unknown}/").status_code == 404
    assert researcher_client.get(f"/sources/{unknown}/").status_code == 404


# --- The two corpora -----------------------------------------------------------------------------


def test_core_and_contextual_material_are_on_separate_tabs(
    reader_client: Client, records: dict[str, Any]
) -> None:
    core = _text(reader_client.get("/policies/"))
    contextual = _text(reader_client.get("/policies/?corpus=contextual"))

    assert "TEST Core AI Strategy" in core and "TEST Contextual Digital Concept" not in core
    assert (
        "TEST Contextual Digital Concept" in contextual
        and "TEST Core AI Strategy" not in contextual
    )


def test_demonstration_data_is_labelled_on_every_page_that_shows_it(
    reader_client: Client, records: dict[str, Any]
) -> None:
    for url in ("/policies/", f"/policies/{records['core']}/", f"/sources/{records['source']}/"):
        page = _text(reader_client.get(url))
        assert "Demonstration data is shown." in page, url
        assert "Demo data" in page, url


def test_filters_narrow_the_list_and_unknown_values_are_ignored(
    reader_client: Client, records: dict[str, Any]
) -> None:
    assert "TEST Core AI Strategy" in _text(reader_client.get("/policies/?country=XA"))
    assert "TEST Core AI Strategy" not in _text(reader_client.get("/policies/?class=reference"))
    assert "TEST Core AI Strategy" in _text(reader_client.get("/policies/?country=<script>&type=x"))


def test_an_empty_list_says_it_is_not_evidence_of_absence(
    reader_client: Client, world: World
) -> None:
    page = _text(reader_client.get("/policies/"))

    assert "No policy is in the core corpus yet." in page
    assert "not evidence that no such policy exists" in page


def test_the_policy_page_shows_the_derived_status_reason_and_provenance(
    reader_client: Client, records: dict[str, Any]
) -> None:
    page = _text(reader_client.get(f"/policies/{records['core']}/"))

    assert "Adopted, not in force" in page
    assert "TEST core reason" in page
    assert "Provisional" in page
    assert "TEST Source" in page
    assert "TEST Publisher" in page
    assert "tier A" in page


# --- Changes through the pages -------------------------------------------------------------------


def test_a_researcher_creates_a_policy_through_the_form(
    researcher_client: Client, world: World
) -> None:
    response = researcher_client.post(
        "/policies/new/",
        {
            "data_class": "demonstration",
            "country": str(world.demo_country),
            "policy_type": "strategy",
            "title": "TEST Form Strategy",
            "title_language": str(world.language),
            "corpus_assignment": "core",
            "ai_focus": "ai_focused",
            "assignment_reason": "TEST form reason",
        },
    )

    policy = Policy.objects.get(title="TEST Form Strategy")
    assert response.status_code == 302
    assert response["Location"] == f"/policies/{policy.public_id}/"


def test_a_refused_policy_is_shown_again_with_the_reason(
    researcher_client: Client, world: World
) -> None:
    response = researcher_client.post(
        "/policies/new/",
        {
            "data_class": "demonstration",
            "country": str(world.reference_country),
            "policy_type": "strategy",
            "title": "TEST Misplaced",
            "title_language": str(world.language),
            "corpus_assignment": "core",
            "ai_focus": "ai_focused",
            "assignment_reason": "TEST",
        },
    )

    assert response.status_code == 400
    assert "synthetic countries" in _text(response)
    assert not Policy.objects.exists()


def test_a_researcher_records_an_event_through_the_policy_page(
    researcher_client: Client, records: dict[str, Any]
) -> None:
    response = researcher_client.post(
        f"/policies/{records['core']}/events/add/",
        {
            "event_type": "entered_into_force",
            "effective_date": "2025-02-01",
            "document": str(records["document"]),
        },
    )

    assert response.status_code == 302
    page = _text(researcher_client.get(response["Location"]))
    assert "In force" in page
    assert "The change was saved and recorded." in page
    assert PolicyEvent.objects.count() == 2


def test_a_document_not_linked_to_the_policy_cannot_be_chosen_for_an_event(
    researcher_client: Client, records: dict[str, Any]
) -> None:
    response = researcher_client.post(
        f"/policies/{records['contextual']}/events/add/",
        {
            "event_type": "adopted",
            "effective_date": "2025-02-01",
            "document": str(records["document"]),
        },
    )

    assert response.status_code == 400
    assert PolicyEvent.objects.count() == 1


def test_a_researcher_registers_a_source_and_a_document(
    researcher_client: Client, world: World
) -> None:
    response = researcher_client.post(
        "/sources/new/",
        {
            "data_class": "reference",
            "name": "TEST Reference Portal",
            "publisher": "TEST Ministry",
            "url": "https://portal.example/",
            "source_tier": "A",
            "permitted_use": "reference_only",
            "accessed_on": "2026-01-02",
            "country": str(world.reference_country),
        },
    )
    source = Source.objects.get(name="TEST Reference Portal")
    assert response["Location"] == f"/sources/{source.public_id}/"

    created = researcher_client.post(
        f"/sources/{source.public_id}/documents/new/",
        {
            "country": str(world.reference_country),
            "document_type": "law",
            "title": "TEST Law on Data",
            "title_language": str(world.language),
        },
    )
    assert created.status_code == 302
    assert "TEST Law on Data" in _text(researcher_client.get(f"/sources/{source.public_id}/"))


def test_every_change_needs_a_csrf_token(
    user_with_roles: UserFactory, records: dict[str, Any]
) -> None:
    client = Client(enforce_csrf_checks=True)
    signed_in(client, user_with_roles(Role.RESEARCHER))

    assert client.post(f"/policies/{records['core']}/assignment/", {}).status_code == 403
    assert client.post("/sources/new/", {}).status_code == 403


def test_an_external_address_opens_safely(reader_client: Client, records: dict[str, Any]) -> None:
    page = _text(reader_client.get(f"/sources/{records['source']}/"))

    for tag in re.findall(r'<a [^>]*target="_blank"[^>]*>', page):
        assert 'rel="noopener noreferrer nofollow"' in tag
