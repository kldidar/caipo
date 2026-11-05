"""Formal policy events beside an indicator's values, on the same years (FR-42).

The events are in a panel of their own above the chart. Nothing joins an
event to a value, the page says it is not a causal analysis, and every event
is also in a table with its exact date.
"""

import re
import uuid
from datetime import date
from decimal import Decimal

import pytest
from django.test import Client

from caipo.accounts.selectors import AuthenticationContext, Role
from caipo.accounts.tests.fixtures import UserFactory
from caipo.indicators import services as indicator_services
from caipo.indicators.services import ObservationRow
from caipo.policies import services as policy_services
from caipo.registry.tests.helpers import ActingAs
from caipo.sources.tests.helpers import World, make_document, make_source, make_world
from caipo.web.tests.helpers import signed_in

pytestmark = pytest.mark.django_db

CORE_TITLE = "TEST Strategy for Artificial Intelligence"
CONTEXTUAL_TITLE = "TEST Law on Schools"
REFERENCE_TITLE = "TEST Reference Strategy"


def _policy(
    actor: AuthenticationContext,
    world: World,
    title: str,
    events: list[tuple[str, date]],
    *,
    data_class: str = "demonstration",
    corpus: str = "core",
) -> None:
    policy = policy_services.create_policy(
        actor=actor,
        data_class=data_class,
        country=world.demo_country if data_class == "demonstration" else world.reference_country,
        policy_type="strategy",
        title=title,
        title_language=world.language,
        corpus_assignment=corpus,
        ai_focus="ai_focused" if corpus == "core" else "",
        contextual_category="" if corpus == "core" else "education",
        assignment_reason="TEST reason",
    )
    document = make_document(actor, world, make_source(actor, world, data_class), data_class)
    policy_services.link_document(
        actor=actor, policy=policy, document=document, role="enacting_text"
    )
    for event_type, effective in events:
        policy_services.record_event(
            actor=actor,
            policy=policy,
            event_type=event_type,
            effective_date=effective,
            document=document,
        )


def _indicator(actor: AuthenticationContext, world: World, data_class: str) -> uuid.UUID:
    source = make_source(actor, world, data_class)
    code = f"TEST-{data_class}"
    indicator = indicator_services.create_indicator(
        actor=actor,
        source=source,
        code=code,
        name=f"TEST indicator, {data_class}",
        unit="% of GDP",
        layer="A",
        layer_reason="TEST reason",
    )
    alpha2 = "XA" if data_class == "demonstration" else "OA"
    indicator_services.import_release(
        actor=actor,
        source=source,
        label="TEST",
        retrieved_on=date(2026, 1, 1),
        file_name="t",
        sha256=("a" if data_class == "demonstration" else "b") * 64,
        rows=[
            ObservationRow(code, alpha2, 2020, Decimal("1.5"), "reported"),
            ObservationRow(code, alpha2, 2021, None, "missing"),
            ObservationRow(code, alpha2, 2022, Decimal("2.25"), "estimated"),
        ],
    )
    return indicator


@pytest.fixture
def records(acting_as: ActingAs) -> dict[str, uuid.UUID]:
    world = make_world()
    actor = acting_as(Role.RESEARCHER)
    _policy(
        actor,
        world,
        CORE_TITLE,
        [
            ("adopted", date(2021, 3, 1)),
            ("entered_into_force", date(2021, 6, 1)),
            ("amended", date(2025, 2, 2)),
        ],
    )
    _policy(actor, world, CONTEXTUAL_TITLE, [("adopted", date(2020, 4, 4))], corpus="contextual")
    _policy(actor, world, REFERENCE_TITLE, [("adopted", date(2021, 5, 5))], data_class="reference")
    return {
        "demonstration": _indicator(actor, world, "demonstration"),
        "reference": _indicator(actor, world, "reference"),
    }


@pytest.fixture
def reader(user_with_roles: UserFactory) -> Client:
    return signed_in(Client(), user_with_roles(Role.READER))


def _page(reader: Client, indicator: uuid.UUID) -> str:
    response = reader.get(f"/indicators/{indicator}/")
    assert response.status_code == 200
    return str(response.content.decode())


def _panel(page: str) -> str:
    """The events panel: from its heading to the heading of the values."""
    return page.split('id="events-title"', 1)[1].split('id="chart-title"', 1)[0]


def _svgs(html: str) -> list[str]:
    return re.findall(r"<svg.*?</svg>", html, flags=re.DOTALL)


def test_the_events_are_shown_above_the_values_in_a_panel_of_their_own(
    reader: Client, records: dict[str, uuid.UUID]
) -> None:
    page = _page(reader, records["demonstration"])

    assert page.index('id="events-title"') < page.index('id="chart-title"')
    (events_svg,) = _svgs(_panel(page))
    (chart_svg,) = _svgs(page.split('id="chart-title"', 1)[1])
    assert "chart__events" in events_svg
    assert "<rect" not in chart_svg
    assert "chart__events" not in chart_svg


def test_nothing_joins_an_event_to_a_value(reader: Client, records: dict[str, uuid.UUID]) -> None:
    """FR-42 (a): no connecting line, fitted line, or computed effect."""
    (events_svg,) = _svgs(_panel(_page(reader, records["demonstration"])))

    for element in ("<path", "<polyline", "<polygon", "<circle"):
        assert element not in events_svg, element
    assert len(re.findall(r"<rect ", events_svg)) == 1


def test_the_panel_says_it_is_not_a_causal_analysis(
    reader: Client, records: dict[str, uuid.UUID]
) -> None:
    """FR-42 (b)."""
    panel = _panel(_page(reader, records["demonstration"]))

    assert "Not a causal analysis." in panel
    assert "They do not show that any policy caused any change" in panel
    assert "only that: two records with the same date" in panel


def test_the_values_keep_their_gaps_and_flags(
    reader: Client, records: dict[str, uuid.UUID]
) -> None:
    """FR-42 (c): the chart beside the events still shows what is missing or estimated."""
    page = _page(reader, records["demonstration"])

    assert "Hollow point: estimated or provisional" in page
    assert "2 of 3 years" in page
    assert "no value" in page


def test_events_of_one_year_are_one_mark_and_each_is_in_the_table(
    reader: Client, records: dict[str, uuid.UUID]
) -> None:
    panel = _panel(_page(reader, records["demonstration"]))

    assert "×2" in panel
    assert "Adopted, 2021-03-01, " + CORE_TITLE in panel
    assert "Entered into force, 2021-06-01, " + CORE_TITLE in panel
    for shown in ("2021-03-01", "2021-06-01", "2025-02-02", "Amended"):
        assert f">{shown}<" in panel, shown


def test_an_event_outside_the_years_charted_is_listed_and_said_to_be_not_drawn(
    reader: Client, records: dict[str, uuid.UUID]
) -> None:
    panel = _panel(_page(reader, records["demonstration"]))
    (events_svg,) = _svgs(panel)

    assert "1 event falls outside the years charted" in panel
    assert "2025" not in events_svg
    assert ">2025-02-02<" in panel


def test_contextual_policies_and_the_other_class_of_data_are_not_shown(
    reader: Client, records: dict[str, uuid.UUID]
) -> None:
    demonstration = _panel(_page(reader, records["demonstration"]))
    reference = _panel(_page(reader, records["reference"]))

    assert CORE_TITLE in demonstration
    assert CONTEXTUAL_TITLE not in demonstration
    assert REFERENCE_TITLE not in demonstration
    assert REFERENCE_TITLE in reference
    assert CORE_TITLE not in reference


def test_an_indicator_whose_countries_have_no_event_says_so_and_draws_nothing(
    reader: Client, acting_as: ActingAs
) -> None:
    world = make_world()
    actor = acting_as(Role.RESEARCHER)
    indicator = _indicator(actor, world, "demonstration")

    panel = _panel(_page(reader, indicator))

    assert "No formal event is recorded for a core-corpus policy of these countries" in panel
    assert _svgs(panel) == []
    assert "Not a causal analysis." in panel


def test_a_country_without_a_mark_is_not_said_to_have_no_event(
    reader: Client, records: dict[str, uuid.UUID]
) -> None:
    panel = _panel(_page(reader, records["demonstration"]))

    assert "has no event recorded here, which does not mean that none occurred" in panel


def test_the_text_of_the_panel_makes_no_claim_of_effect(
    reader: Client, records: dict[str, uuid.UUID]
) -> None:
    """A guard for this panel's own words. It is not the prohibited-wording list of FR-42 (d),
    which the owner writes (B11)."""
    text = re.sub(r"<[^>]+>", " ", _panel(_page(reader, records["demonstration"]))).lower()

    for phrase in (
        "impact",
        "effect",
        "led to",
        "due to",
        "result",
        "boost",
        "drove",
        "driven",
        "because",
        "thanks to",
        "attribut",
        "contributed to",
    ):
        assert phrase not in text, phrase


def test_the_events_are_read_with_workspace_access_only(
    client: Client, records: dict[str, uuid.UUID]
) -> None:
    response = client.get(f"/indicators/{records['demonstration']}/")

    assert response.status_code == 403
    assert CORE_TITLE not in response.content.decode()
