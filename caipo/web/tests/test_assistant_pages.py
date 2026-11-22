"""The research assistant's page (ADR-0025), with the deterministic fake provider."""

import dataclasses
import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.test import Client

from caipo.accounts.selectors import Role
from caipo.accounts.tests.fixtures import UserFactory
from caipo.assistant import config, pipeline
from caipo.assistant.providers import FakeProvider
from caipo.indicators import services as indicators_services
from caipo.indicators.services import ObservationRow
from caipo.registry.tests.helpers import ActingAs
from caipo.retrieval import services as retrieval_services
from caipo.sources import services as sources_services
from caipo.sources.services import TextPart
from caipo.sources.tests.helpers import World, make_document, make_source, make_world
from caipo.web.tests.helpers import signed_in, verified

pytestmark = pytest.mark.django_db

PAGE = "/assistant/"
INDICATOR = "TEST Individuals using the Internet"
GRANTS = "TEST A competitive grant programme supports start-ups."
QUESTION = "How many people used the Internet in TEST Reference Country in 2019?"


def _text(response: Any) -> str:
    return str(response.content.decode())


@pytest.fixture
def evidence(acting_as: ActingAs) -> None:
    world: World = make_world()
    actor = acting_as(Role.RESEARCHER)
    reference = make_source(actor, world, "reference")
    indicators_services.create_indicator(
        actor=actor,
        source=reference,
        code="TEST-NET",
        name=INDICATOR,
        unit="% of population",
        layer="B",
        layer_reason="TEST reason",
        definition="TEST share of the population using the Internet.",
    )
    indicators_services.import_release(
        actor=actor,
        source=reference,
        label="TEST release 1",
        retrieved_on=date(2026, 1, 2),
        file_name="TEST.csv",
        sha256="a" * 64,
        rows=[
            ObservationRow("TEST-NET", "OA", 2019, Decimal("70.4"), "reported"),
            ObservationRow("TEST-NET", "OA", 2020, None, "missing"),
        ],
    )
    document = make_document(actor, world, make_source(actor, world))
    sources_services.attach_demonstration_text(
        actor=actor, document=document, parts=[TextPart("Art. 7", GRANTS)]
    )
    retrieval_services.rebuild_index()


def _provider(monkeypatch: pytest.MonkeyPatch, *statements: dict[str, object]) -> FakeProvider:
    def respond(system: str, user: str) -> str:
        if system.startswith("You check numbered statements"):
            count = len(json.loads(user)["statements"])
            return json.dumps(
                {"verdicts": [{"index": i, "verdict": "supported"} for i in range(count)]}
            )
        return json.dumps({"statements": list(statements), "gaps": []})

    provider = FakeProvider(respond)
    monkeypatch.setattr(pipeline, "get_provider", lambda: provider)
    return provider


def _reader(client: Client, user_with_roles: UserFactory) -> Client:
    return signed_in(client, user_with_roles(Role.READER))


@pytest.mark.parametrize(
    ("role", "status"),
    [(Role.READER, 200), (Role.RESEARCHER, 200), (Role.REVIEWER, 200), (Role.ADMINISTRATOR, 403)],
)
def test_the_page_opens_for_the_roles_that_may_ask(
    client: Client, user_with_roles: UserFactory, role: Role, status: int
) -> None:
    response = verified(client, user_with_roles(role)).get(PAGE)

    assert response.status_code == status


def test_an_anonymous_visitor_is_refused_before_anything_is_asked(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(monkeypatch)

    response = client.post(PAGE, {"question": QUESTION})

    assert response.status_code == 403
    assert provider.calls == []


def test_the_page_names_the_provider_and_the_questions_left(
    client: Client, user_with_roles: UserFactory
) -> None:
    page = _text(_reader(client, user_with_roles).get(PAGE))
    configuration = config.load()

    assert f"sent to {configuration.provider.label} ({configuration.provider.model})" in page
    assert "Do not include personal information." in page
    assert f"You may ask {configuration.per_account_daily} more questions today." in page
    assert "Evaluated on a small test set only." in page
    assert "no person has yet checked its answers" in page


@pytest.mark.usefixtures("evidence")
def test_a_recorded_observation_is_shown_with_the_value_the_server_holds(
    client: Client, user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    _provider(
        monkeypatch,
        {
            "text": "The World Bank records 70.4 for TEST Reference Country in 2019.",
            "label": "recorded_observation",
            "citations": ["E1"],
        },
    )

    response = _reader(client, user_with_roles).post(PAGE, {"question": QUESTION})
    page = _text(response)

    assert response.status_code == 200
    assert "The World Bank records 70.4 for TEST Reference Country in 2019." in page
    assert "Recorded observation" in page
    assert f"{INDICATOR}, TEST Reference Country, 2019" in page
    assert "Value as recorded: <strong>70.4</strong>" in page
    assert "does not say that any policy caused any outcome" in page
    assert "All of its evidence comes from one source" in page
    assert 'href="/indicators/' in page


@pytest.mark.usefixtures("evidence")
def test_a_demonstration_text_is_quoted_from_its_segment_and_marked_synthetic(
    client: Client, user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    _provider(
        monkeypatch,
        {
            "text": "The document states that a grant programme supports start-ups.",
            "label": "documented_statement",
            "citations": ["P1"],
        },
    )

    page = _text(
        _reader(client, user_with_roles).post(
            PAGE, {"question": "Is there a competitive grant programme for start-ups?"}
        )
    )

    assert "Documented statement" in page
    assert f'<blockquote class="provision__quote">{GRANTS}' in page
    assert "Synthetic text of a demonstration document." in page
    assert 'href="/sources/' in page


@pytest.mark.usefixtures("evidence")
def test_a_models_words_are_shown_escaped_and_never_as_a_link(
    client: Client, user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The markup check removes such a statement; were one ever to pass, the
    # page would still show it as text.
    statement = pipeline.StatementShown(
        text="<b>TEST</b> <a href='https://example.invalid/'>TEST</a>",
        label="recorded_observation",
        flags=(),
        sources=(),
    )
    real = pipeline.answer_question

    def answered(**options: Any) -> pipeline.Answer:
        return dataclasses.replace(real(**options), outcome="answered", statements=(statement,))

    monkeypatch.setattr(pipeline, "answer_question", answered)
    _provider(monkeypatch)

    page = _text(_reader(client, user_with_roles).post(PAGE, {"question": QUESTION}))

    assert "&lt;b&gt;TEST&lt;/b&gt;" in page
    assert "<b>TEST</b>" not in page and 'href="https://example.invalid' not in page


@pytest.mark.usefixtures("evidence")
def test_without_evidence_the_page_says_so_and_what_was_searched(
    client: Client, user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(monkeypatch)

    page = _text(_reader(client, user_with_roles).post(PAGE, {"question": "zzqx wvvp"}))

    assert "Nothing held answers this question." in page
    assert "Searched for: zzqx wvvp" in page
    assert provider.calls == []


@pytest.mark.usefixtures("evidence")
def test_a_recorded_gap_is_shown_as_a_gap(
    client: Client, user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    _provider(
        monkeypatch,
        {
            "text": "The World Bank records no value for TEST Reference Country in 2020.",
            "label": "recorded_observation",
            "citations": ["E2"],
        },
    )

    page = _text(
        _reader(client, user_with_roles).post(
            PAGE, {"question": "Internet users in TEST Reference Country in 2019 and 2020"}
        )
    )

    assert "No value is recorded for this year" in page
    assert "no value (missing)" not in page


def test_an_empty_question_is_refused_and_nothing_is_asked(
    client: Client, user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(monkeypatch)

    response = _reader(client, user_with_roles).post(PAGE, {"question": "   "})

    assert response.status_code == 400
    assert provider.calls == []


def test_a_spent_quota_is_explained(
    client: Client, user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    configuration = dataclasses.replace(config.load(), per_account_daily=1, instance_daily=5)
    monkeypatch.setattr(config, "load", lambda path=None: configuration)
    _provider(monkeypatch)
    reader = _reader(client, user_with_roles)
    reader.post(PAGE, {"question": "zzqx wvvp"})

    response = reader.post(PAGE, {"question": "zzqx wvvp"})

    assert response.status_code == 429
    assert "as many questions as one account may today" in _text(response)
