"""The formal events read for a shared time axis (FR-42)."""

from datetime import date

import pytest
from django.core.exceptions import PermissionDenied

from caipo.accounts.selectors import AuthenticationContext
from caipo.policies import selectors, services
from caipo.sources.tests.helpers import World, make_document, make_source

pytestmark = pytest.mark.django_db


def _policy_with_events(
    actor: AuthenticationContext,
    world: World,
    events: list[tuple[str, date]],
    *,
    data_class: str = "demonstration",
    corpus: str = "core",
    title: str = "TEST Strategy for Artificial Intelligence",
    title_en: str = "",
) -> None:
    home = world.demo_country if data_class == "demonstration" else world.reference_country
    policy = services.create_policy(
        actor=actor,
        data_class=data_class,
        country=home,
        policy_type="strategy",
        title=title,
        title_en=title_en,
        title_language=world.language,
        corpus_assignment=corpus,
        ai_focus="ai_focused" if corpus == "core" else "",
        contextual_category="" if corpus == "core" else "education",
        assignment_reason="TEST reason",
    )
    document = make_document(
        actor, world, make_source(actor, world, data_class), data_class, country=home
    )
    services.link_document(actor=actor, policy=policy, document=document, role="enacting_text")
    for event_type, effective in events:
        services.record_event(
            actor=actor,
            policy=policy,
            event_type=event_type,
            effective_date=effective,
            document=document,
        )


def test_the_events_of_core_policies_are_read_oldest_first(
    researcher: AuthenticationContext, reader: AuthenticationContext, world: World
) -> None:
    _policy_with_events(
        researcher,
        world,
        [("entered_into_force", date(2021, 6, 1)), ("adopted", date(2021, 3, 1))],
        title="TEST Title as written",
        title_en="TEST English title",
    )
    _policy_with_events(researcher, world, [("adopted", date(2020, 5, 5))])

    events = selectors.formal_events(reader, data_class="demonstration", countries=["XA"])

    assert [(event.effective_date, event.event_type, event.label) for event in events] == [
        (date(2020, 5, 5), "adopted", "Adopted"),
        (date(2021, 3, 1), "adopted", "Adopted"),
        (date(2021, 6, 1), "entered_into_force", "Entered into force"),
    ]
    assert events[1].policy_title == "TEST English title"
    assert events[0].policy_title == "TEST Strategy for Artificial Intelligence"
    assert (events[1].country_alpha2, events[1].country_name) == ("XA", "TEST Synthetic Country")


def test_only_the_countries_asked_for_are_read(
    researcher: AuthenticationContext, reader: AuthenticationContext, world: World
) -> None:
    _policy_with_events(researcher, world, [("adopted", date(2021, 3, 1))])
    _policy_with_events(researcher, world, [("adopted", date(2022, 4, 4))], data_class="reference")

    assert selectors.formal_events(reader, data_class="demonstration", countries=["OA"]) == []
    assert selectors.formal_events(reader, data_class="reference", countries=["XA"]) == []
    assert selectors.formal_events(reader, data_class="demonstration", countries=[]) == []
    assert [
        event.country_alpha2
        for event in selectors.formal_events(reader, data_class="reference", countries=["XA", "OA"])
    ] == ["OA"]


def test_contextual_policies_are_left_out(
    researcher: AuthenticationContext, reader: AuthenticationContext, world: World
) -> None:
    _policy_with_events(researcher, world, [("adopted", date(2021, 3, 1))], corpus="contextual")

    assert selectors.formal_events(reader, data_class="demonstration", countries=["XA"]) == []


def test_synthetic_and_reference_events_are_never_read_together(
    researcher: AuthenticationContext, reader: AuthenticationContext, world: World
) -> None:
    _policy_with_events(researcher, world, [("adopted", date(2021, 3, 1))])
    _policy_with_events(researcher, world, [("adopted", date(2022, 4, 4))], data_class="reference")

    demonstration = selectors.formal_events(
        reader, data_class="demonstration", countries=["XA", "OA"]
    )
    reference = selectors.formal_events(reader, data_class="reference", countries=["XA", "OA"])

    assert [event.country_alpha2 for event in demonstration] == ["XA"]
    assert [event.country_alpha2 for event in reference] == ["OA"]


def test_reading_events_needs_workspace_access(world: World) -> None:
    with pytest.raises(PermissionDenied):
        selectors.formal_events(None, data_class="demonstration", countries=["XA"])
