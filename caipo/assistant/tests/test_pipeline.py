"""The pipeline of an answer, end to end, with the deterministic fake provider (ADR-0025)."""

import dataclasses
import json
import uuid
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied

from caipo.accounts.selectors import AuthenticationContext, Role
from caipo.accounts.tests.fixtures import ActingAs
from caipo.assistant import config, selectors, services
from caipo.assistant.models import AIInteraction, AnswerCitation, AnswerStatement, RetrievalHit
from caipo.assistant.pipeline import Answer, answer_question
from caipo.assistant.providers import FakeProvider, ProviderUnavailableError
from caipo.indicators import selectors as indicators_selectors
from caipo.indicators import services as indicators_services
from caipo.indicators.services import ObservationRow
from caipo.retrieval import selectors as retrieval_selectors
from caipo.retrieval import services as retrieval_services
from caipo.retrieval.selectors import ChunkKind, SearchHit
from caipo.sources import selectors as sources_selectors
from caipo.sources import services as sources_services
from caipo.sources.services import TextPart
from caipo.sources.tests.helpers import World, make_document, make_source

pytestmark = [pytest.mark.services, pytest.mark.django_db]

INDICATOR = "TEST Individuals using the Internet"
GRANTS = "TEST A competitive grant programme supports start-ups."
Respond = Callable[[str, str], str]


@pytest.fixture
def evidence(researcher: AuthenticationContext, world: World) -> None:
    reference = make_source(researcher, world, "reference")
    indicators_services.create_indicator(
        actor=researcher,
        source=reference,
        code="TEST-NET",
        name=INDICATOR,
        unit="% of population",
        layer="B",
        layer_reason="TEST reason",
        definition="TEST share of the population using the Internet.",
    )
    indicators_services.import_release(
        actor=researcher,
        source=reference,
        label="TEST release 1",
        retrieved_on=date(2026, 1, 2),
        file_name="TEST.csv",
        sha256="a" * 64,
        rows=[
            ObservationRow("TEST-NET", "OA", 2019, Decimal("70.399998648"), "reported"),
            ObservationRow("TEST-NET", "OA", 2020, None, "missing"),
            ObservationRow("TEST-NET", "OA", 2021, Decimal("76.59"), "estimated"),
        ],
    )
    document = make_document(researcher, world, make_source(researcher, world))
    sources_services.attach_demonstration_text(
        actor=researcher, document=document, parts=[TextPart("Art. 7", GRANTS)]
    )
    retrieval_services.rebuild_index()


@pytest.fixture
def reader(acting_as: ActingAs) -> AuthenticationContext:
    return acting_as(Role.READER)


def _synthesis(*statements: dict[str, object], gaps: tuple[str, ...] = ()) -> str:
    return json.dumps({"statements": list(statements), "gaps": list(gaps)})


def _fake(synthesis: str | list[str], verdict: str = "supported") -> FakeProvider:
    answers = iter([synthesis] if isinstance(synthesis, str) else synthesis)

    def respond(system: str, user: str) -> str:
        if system.startswith("You prepare a search"):
            return json.dumps(
                {"search_query": "share of people using the Internet", "countries": [], "years": []}
            )
        if system.startswith("You check numbered statements"):
            count = len(json.loads(user)["statements"])
            return json.dumps(
                {"verdicts": [{"index": i, "verdict": verdict} for i in range(count)]}
            )
        return next(answers)

    return FakeProvider(respond)


def _ask(
    actor: AuthenticationContext, question: str, provider: FakeProvider, assistant: str = "research"
) -> Answer:
    return answer_question(actor=actor, assistant=assistant, question=question, provider=provider)


def _stages(interaction: uuid.UUID) -> list[tuple[str, str, str]]:
    return list(
        AIInteraction.objects.get(public_id=interaction)
        .stages.order_by("id")
        .values_list("stage", "result", "reason")
    )


@pytest.mark.usefixtures("evidence")
def test_a_verified_answer_shows_only_what_the_server_holds(reader: AuthenticationContext) -> None:
    provider = _fake(
        _synthesis(
            {
                "text": "The World Bank records 70.4 for TEST Reference Country in 2019.",
                "label": "recorded_observation",
                "citations": ["E1"],
            }
        )
    )

    answer = answer_question(
        actor=reader,
        assistant="research",
        question="How many people used the Internet in TEST Reference Country in 2019?",
        provider=provider,
    )

    assert answer.outcome == "answered"
    (shown,) = answer.statements
    assert shown.text.startswith("The World Bank records 70.4")
    (source,) = shown.sources
    assert source.title == f"{INDICATOR}, TEST Reference Country, 2019"
    assert source.quote == "70.399998648" and source.status == "reported"
    assert len(provider.calls) == 2, "English needs no analysis call: synthesis and support check"
    assert [stage for stage, _, _ in _stages(answer.interaction)] == [
        "input_guard",
        "query_analysis",
        "retrieval",
        "evidence_verification",
        "synthesis",
        "citation_verification",
        "response",
    ]
    assert selectors.interaction_outcome(answer.interaction) == "answered"
    citation = AnswerCitation.objects.get()
    assert citation.kind == "observation" and citation.observation is not None
    assert RetrievalHit.objects.filter(kind="observation", in_context=True).count() == 1


@pytest.mark.usefixtures("evidence")
def test_a_cited_passage_is_made_by_the_server_from_the_segment(
    reader: AuthenticationContext,
) -> None:
    provider = _fake(
        _synthesis(
            {
                "text": "The document states that a grant programme supports start-ups.",
                "label": "documented_statement",
                "citations": ["P1"],
                "quotes": [{"handle": "P1", "text": "competitive grant programme"}],
            }
        )
    )

    answer = _ask(reader, "Is there a competitive grant programme for start-ups?", provider)

    assert answer.outcome == "answered"
    (segment,) = sources_selectors.demonstration_segments()
    assert segment.text == GRANTS
    # The service returns the Passage it already holds for a span, so the
    # citation names the Passage of the whole Segment.
    whole = sources_services.passage_for_span(
        segment=segment.public_id, start_offset=0, end_offset=len(GRANTS)
    )
    assert AnswerCitation.objects.get().passage == whole


@pytest.mark.usefixtures("evidence")
def test_statements_that_fail_a_check_are_removed_and_recorded(
    reader: AuthenticationContext,
) -> None:
    provider = _fake(
        _synthesis(
            {
                "text": "The World Bank records 70.4 in 2019.",
                "label": "recorded_observation",
                "citations": ["E1"],
            },
            {
                "text": "The registry of laws says so.",
                "label": "documented_statement",
                "citations": ["P9"],
            },
            {
                "text": "The World Bank records 99 in 2019.",
                "label": "recorded_observation",
                "citations": ["E1"],
            },
            {
                "text": "Internet use rose because of the policy.",
                "label": "recorded_observation",
                "citations": ["E1"],
            },
        )
    )

    answer = _ask(reader, "Internet users in TEST Reference Country in 2019", provider)

    assert [s.text for s in answer.statements] == ["The World Bank records 70.4 in 2019."]
    assert list(
        AnswerStatement.objects.order_by("position").values_list("verification", "removal_reason")
    ) == [
        ("verified", ""),
        ("removed", "unknown_handle"),
        ("removed", "number"),
        ("removed", "causal_wording"),
    ]


@pytest.mark.usefixtures("evidence")
def test_a_statement_the_support_check_does_not_support_is_removed(
    reader: AuthenticationContext,
) -> None:
    provider = _fake(
        _synthesis(
            {
                "text": "The World Bank records 70.4 in 2019.",
                "label": "recorded_observation",
                "citations": ["E1"],
            }
        ),
        verdict="not_supported",
    )

    answer = _ask(reader, "Internet users in TEST Reference Country in 2019", provider)

    assert (answer.outcome, answer.reason, answer.statements) == (
        "abstained",
        "nothing_verified",
        (),
    )
    assert AnswerStatement.objects.get().removal_reason == "not_supported"


@pytest.mark.usefixtures("evidence")
def test_without_evidence_the_assistant_abstains_and_calls_no_model(
    reader: AuthenticationContext,
) -> None:
    provider = _fake(_synthesis())

    answer = _ask(reader, "zzqx wvvp", provider)

    assert (answer.outcome, answer.reason) == ("abstained", "no_evidence")
    assert provider.calls == []


@pytest.mark.usefixtures("evidence")
def test_a_russian_question_is_translated_for_search_only(reader: AuthenticationContext) -> None:
    provider = _fake(
        _synthesis(
            {
                "text": "Всемирный банк фиксирует 70.4 в 2019 году.",
                "label": "recorded_observation",
                "citations": ["E1"],
            }
        )
    )

    answer = _ask(reader, "Сколько людей пользовались интернетом?", provider)

    assert answer.language == "russian"
    assert ("query_analysis", "passed", "translated") in _stages(answer.interaction)
    assert answer.searched["query"] == "share of people using the Internet"
    assert "Write every statement and gap in Russian." in provider.calls[1][0]
    assert "cross_language" in answer.statements[0].flags


@pytest.mark.usefixtures("evidence")
def test_malformed_output_is_asked_for_once_more_then_fails(reader: AuthenticationContext) -> None:
    once = _fake(["not json", _synthesis()])
    twice = _fake(["not json", "still not json"])

    first = _ask(reader, "Internet users in TEST Reference Country", once)
    second = _ask(reader, "Internet users in TEST Reference Country", twice)

    assert first.reason == "nothing_verified"
    assert (second.outcome, second.reason) == ("failed", "malformed_output")
    assert sum(1 for system, _ in twice.calls if system.startswith("You answer")) == 2


@pytest.mark.usefixtures("evidence")
def test_no_answer_makes_more_than_three_model_calls(reader: AuthenticationContext) -> None:
    # ADR-0025 point 7: the translation of a Russian question uses one of the
    # three calls, so its malformed synthesis is not asked for again, because
    # the support check would then be a fourth.
    provider = _fake(["not json", _synthesis()])

    answer = _ask(reader, "Сколько людей пользовались интернетом?", provider)

    assert (answer.outcome, answer.reason) == ("failed", "malformed_output")
    assert len(provider.calls) == 2


@pytest.mark.usefixtures("evidence")
def test_a_provider_failure_ends_the_answer_as_failed(reader: AuthenticationContext) -> None:
    def fail(system: str, user: str) -> str:
        raise ProviderUnavailableError("TEST")

    answer = _ask(reader, "Internet users in TEST Reference Country", FakeProvider(fail))

    assert (answer.outcome, answer.reason) == ("failed", "unavailable")
    assert selectors.interaction_outcome(answer.interaction) == "failed"


@pytest.mark.usefixtures("evidence")
def test_a_provider_failure_is_logged_with_what_failed_for_the_operator(
    reader: AuthenticationContext, caplog: pytest.LogCaptureFixture
) -> None:
    def fail(system: str, user: str) -> str:
        raise ProviderUnavailableError("HTTP 401")

    with caplog.at_level("WARNING", logger="caipo.assistant.pipeline"):
        answer = _ask(reader, "Internet users in TEST Reference Country", FakeProvider(fail))

    (record,) = [
        r for r in caplog.records if getattr(r, "event", "") == "assistant.provider_failed"
    ]
    assert record.__dict__["reason"] == "unavailable"
    assert record.__dict__["detail"] == "HTTP 401"
    assert record.__dict__["public_id"] == str(answer.interaction)


@pytest.mark.usefixtures("evidence")
def test_past_the_deadline_no_model_is_called(
    reader: AuthenticationContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    configuration = dataclasses.replace(config.load(), deadline_seconds=-1.0)
    monkeypatch.setattr(config, "load", lambda path=None: configuration)
    provider = _fake(_synthesis())

    answer = _ask(reader, "Internet users in TEST Reference Country", provider)

    assert (answer.outcome, answer.reason) == ("timed_out", "deadline")
    assert provider.calls == []


@pytest.mark.usefixtures("evidence")
@pytest.mark.parametrize(
    "change",
    [
        {"text": "TEST tampered text"},
        {"start_offset": 1},
        {"end_offset": len(GRANTS) + 1},
    ],
    ids=["text", "start", "end"],
)
def test_retrieved_text_that_differs_from_its_segment_is_dropped(
    reader: AuthenticationContext, monkeypatch: pytest.MonkeyPatch, change: dict[str, Any]
) -> None:
    search = retrieval_selectors.search

    def tampered(question: str, *, kind: ChunkKind, limit: int) -> tuple[SearchHit, ...]:
        return tuple(
            dataclasses.replace(hit, **change) for hit in search(question, kind=kind, limit=limit)
        )

    monkeypatch.setattr(retrieval_selectors, "search", tampered)
    provider = _fake(_synthesis())

    answer = _ask(reader, "competitive grant programme start-ups", provider)

    assert RetrievalHit.objects.filter(kind="segment").exists()
    assert (answer.outcome, answer.reason) == ("abstained", "no_evidence")
    assert provider.calls == []


@pytest.mark.usefixtures("evidence")
def test_the_help_assistant_answers_from_help_and_names_the_section(
    reader: AuthenticationContext,
) -> None:
    def respond(system: str, user: str) -> str:
        if system.startswith("You check numbered statements"):
            return json.dumps({"verdicts": [{"index": 0, "verdict": "supported"}]})
        return _synthesis(
            {
                "text": "Choose Export CSV or Export JSON.",
                "label": "documented_statement",
                "citations": ["H1"],
            }
        )

    answer = _ask(reader, "How do I export an analysis?", FakeProvider(respond), "help")

    assert answer.outcome == "answered"
    (source,) = answer.statements[0].sources
    assert source.help_page and source.help_section
    assert AnswerCitation.objects.get().help_page == source.help_page


def test_an_account_that_may_not_ask_is_refused_before_anything(acting_as: ActingAs) -> None:
    provider = _fake(_synthesis())

    with pytest.raises(PermissionDenied):
        _ask(acting_as(Role.ADMINISTRATOR, second_factor=True), "TEST", provider)

    assert not AIInteraction.objects.exists() and provider.calls == []


@pytest.mark.usefixtures("evidence")
def test_the_record_of_an_interaction_holds_its_stages_evidence_and_statements(
    reader: AuthenticationContext,
) -> None:
    provider = _fake(
        _synthesis(
            {
                "text": "The World Bank records 70.4 for TEST Reference Country in 2019.",
                "label": "recorded_observation",
                "citations": ["E1"],
            },
            {"text": "TEST unsupported.", "label": "documented_statement", "citations": ["P9"]},
        )
    )

    answer = _ask(reader, "Internet users in TEST Reference Country in 2019", provider)
    record = selectors.interaction_record(answer.interaction)

    assert record is not None
    assert record.question == "Internet users in TEST Reference Country in 2019"
    assert [stage.stage for stage in record.stages] == [
        "input_guard",
        "query_analysis",
        "retrieval",
        "evidence_verification",
        "synthesis",
        "citation_verification",
        "response",
    ]
    assert "E1" in {hit.handle for hit in record.hits}
    shown, removed = record.statements
    assert (shown.verification, shown.cited) == ("verified", ("E1",))
    assert (removed.removal_reason, removed.cited) == ("unknown_handle", ())


def test_there_is_no_record_of_an_unknown_interaction() -> None:
    assert selectors.interaction_record(uuid.uuid4()) is None


@pytest.mark.usefixtures("evidence")
def test_an_observation_is_known_by_its_indicator_country_and_year(
    reader: AuthenticationContext,
) -> None:
    found = indicators_selectors.observation_evidence(
        "TEST Internet", countries=[], years=(2019, 2020), indicators=1, recent_years=8, limit=5
    )

    keys = indicators_selectors.observation_keys([item.observation_id for item in found] + [0])
    assert sorted(keys.values()) == [("TEST-NET", "OA", 2019), ("TEST-NET", "OA", 2020)]


@pytest.mark.usefixtures("evidence")
def test_the_service_passes_the_provider_it_is_given(reader: AuthenticationContext) -> None:
    provider = _fake(_synthesis())

    services.answer_question(
        actor=reader, assistant="research", question="TEST Internet", provider=provider
    )

    assert len(provider.calls) == 1
