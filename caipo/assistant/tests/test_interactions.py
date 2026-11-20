"""The input guard, the quotas, and the append-only record of interactions (ADR-0025)."""

import dataclasses
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.db.utils import IntegrityError
from django.utils import timezone

from caipo.accounts.selectors import AuthenticationContext, Role
from caipo.accounts.tests.fixtures import ActingAs
from caipo.assistant import config, selectors, services
from caipo.assistant.models import AIInteraction, InteractionStageRecord
from caipo.assistant.services import QuotaExceededError, begin_interaction, record_stage
from caipo.core.entry import InvalidEntryError
from caipo.retrieval import selectors as retrieval_selectors

pytestmark = [pytest.mark.services, pytest.mark.django_db]

PROMPTS = {"synthesis": "TEST-synthesis-1"}


@pytest.fixture
def reader(acting_as: ActingAs) -> AuthenticationContext:
    return acting_as(Role.READER)


@pytest.fixture
def small_quotas(monkeypatch: pytest.MonkeyPatch) -> None:
    configuration = dataclasses.replace(config.load(), per_account_daily=2, instance_daily=3)
    monkeypatch.setattr(config, "load", lambda path=None: configuration)


def _ask(actor: AuthenticationContext, question: str = "TEST What is recorded?") -> uuid.UUID:
    return begin_interaction(
        actor=actor, assistant="research", question=question, prompt_versions=PROMPTS
    ).public_id


def test_a_reader_starts_an_interaction_that_records_what_answers_it(
    reader: AuthenticationContext,
) -> None:
    start = begin_interaction(
        actor=reader,
        assistant="help",
        question="  TEST How do I export an analysis?\n",
        prompt_versions=PROMPTS,
    )

    interaction = AIInteraction.objects.get(public_id=start.public_id)
    provider = config.load().provider
    assert (start.question, start.language) == ("TEST How do I export an analysis?", "english")
    assert (interaction.user_id, interaction.assistant, interaction.question) == (
        reader.user.pk,
        "help",
        start.question,
    )
    assert interaction.pipeline_version == config.load().pipeline_version
    assert interaction.prompt_versions == PROMPTS
    assert interaction.model_identifier == f"{provider.name}:{provider.model}"
    assert interaction.generation_settings == {
        "temperature": provider.temperature,
        "max_output_tokens": provider.max_output_tokens,
    }
    assert interaction.chunking_version == retrieval_selectors.chunking_version()
    assert list(interaction.stages.values_list("stage", "result")) == [("input_guard", "passed")]


@pytest.mark.parametrize(
    ("question", "language"),
    [
        ("TEST Как экспортировать анализ?", "russian"),
        ("TEST How do I export an analysis?", "english"),
        ("Что такое CAIPO?", "russian"),
        ("What is the share of users in Узбекистан?", "english"),
        ("12345 ?", "english"),
    ],
)
def test_the_language_is_decided_by_the_letters_never_by_a_model(
    question: str, language: str
) -> None:
    assert services.detect_language(question) == language


@pytest.mark.parametrize("role", [Role.READER, Role.RESEARCHER, Role.REVIEWER])
def test_every_workspace_role_may_ask(acting_as: ActingAs, role: Role) -> None:
    _ask(acting_as(role, second_factor=role == Role.REVIEWER))

    assert AIInteraction.objects.count() == 1


def test_an_administrator_may_not_ask_and_is_refused_before_anything(acting_as: ActingAs) -> None:
    administrator = acting_as(Role.ADMINISTRATOR, second_factor=True)

    with pytest.raises(PermissionDenied):
        begin_interaction(actor=administrator, assistant="none", question="", prompt_versions={})

    assert not AIInteraction.objects.exists()


@pytest.mark.parametrize(
    ("assistant", "question"),
    [
        ("oracle", "TEST question"),
        ("research", "   \n "),
        ("research", "T" * 501),
        ("research", "TEST ‮question"),
    ],
    ids=["unknown-assistant", "blank", "too-long", "direction-control"],
)
def test_an_unacceptable_question_is_refused_and_nothing_is_recorded(
    reader: AuthenticationContext, assistant: str, question: str
) -> None:
    with pytest.raises(InvalidEntryError):
        begin_interaction(actor=reader, assistant=assistant, question=question, prompt_versions={})

    assert not AIInteraction.objects.exists()


@pytest.mark.usefixtures("small_quotas")
def test_an_account_asks_no_more_than_its_daily_quota(acting_as: ActingAs) -> None:
    first, second = acting_as(Role.READER), acting_as(Role.READER)
    _ask(first)
    _ask(first)

    with pytest.raises(QuotaExceededError) as raised:
        _ask(first)

    assert raised.value.scope == "account"
    assert AIInteraction.objects.count() == 2
    _ask(second)
    assert selectors.quotas_left(second) == selectors.QuotasLeft(account=1, instance=0)


@pytest.mark.usefixtures("small_quotas")
def test_the_instance_asks_no_more_than_its_daily_quota(acting_as: ActingAs) -> None:
    for _ in range(3):
        _ask(acting_as(Role.READER))

    with pytest.raises(QuotaExceededError) as raised:
        _ask(acting_as(Role.READER))

    assert raised.value.scope == "instance"
    assert AIInteraction.objects.count() == 3


@pytest.mark.usefixtures("small_quotas")
def test_the_quotas_start_again_at_midnight_utc(
    reader: AuthenticationContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ask(reader)
    _ask(reader)
    tomorrow = timezone.now() + timedelta(days=1)
    monkeypatch.setattr(timezone, "now", lambda: tomorrow)

    assert selectors.quotas_left(reader) == selectors.QuotasLeft(account=2, instance=3)


def test_the_quotas_left_are_read_only_by_an_account_that_may_ask(acting_as: ActingAs) -> None:
    with pytest.raises(PermissionDenied):
        selectors.quotas_left(acting_as(Role.ADMINISTRATOR, second_factor=True))


def test_each_stage_is_recorded_once(reader: AuthenticationContext) -> None:
    interaction = _ask(reader)

    record_stage(
        interaction=interaction,
        stage="synthesis",
        result="passed",
        detail={"raw": "TEST"},
        input_tokens=10,
        output_tokens=5,
        duration_ms=7,
    )
    with pytest.raises(InvalidEntryError, match="recorded already"):
        record_stage(interaction=interaction, stage="synthesis", result="failed")

    record = InteractionStageRecord.objects.get(stage="synthesis")
    assert (record.result, record.detail, record.input_tokens, record.duration_ms) == (
        "passed",
        {"raw": "TEST"},
        10,
        7,
    )


@pytest.mark.parametrize(
    ("stage", "result", "known"),
    [("oracle", "passed", True), ("synthesis", "maybe", True), ("synthesis", "passed", False)],
)
def test_an_unknown_stage_result_or_interaction_is_refused(
    reader: AuthenticationContext, stage: str, result: str, known: bool
) -> None:
    interaction = _ask(reader) if known else uuid.uuid4()

    with pytest.raises(InvalidEntryError):
        record_stage(interaction=interaction, stage=stage, result=result)

    assert InteractionStageRecord.objects.count() == (1 if known else 0)


@pytest.mark.parametrize(
    ("stages", "outcome"),
    [
        ([], None),
        ([("synthesis", "passed")], None),
        ([("evidence_verification", "abstained")], "abstained"),
        ([("query_analysis", "refused")], "refused"),
        ([("synthesis", "timed_out")], "timed_out"),
        ([("synthesis", "passed"), ("citation_verification", "failed")], "failed"),
        ([("synthesis", "passed"), ("response", "passed")], "answered"),
    ],
)
def test_the_outcome_is_derived_from_the_stages(
    reader: AuthenticationContext, stages: list[tuple[str, str]], outcome: str | None
) -> None:
    interaction = _ask(reader)
    for stage, result in stages:
        record_stage(interaction=interaction, stage=stage, result=result)

    assert selectors.interaction_outcome(interaction) == outcome
    assert selectors.interaction_outcome(uuid.uuid4()) is None


def _raw(sql: str) -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(sql)


@pytest.mark.parametrize("table", ["assistant_aiinteraction", "assistant_interactionstagerecord"])
def test_the_database_refuses_any_change_or_deletion(
    reader: AuthenticationContext, table: str
) -> None:
    _ask(reader)

    with pytest.raises(IntegrityError, match="append-only: UPDATE refused"):
        _raw(f"UPDATE {table} SET id = id")  # noqa: S608 - the table names are the test's own
    with pytest.raises(IntegrityError, match="append-only: DELETE refused"):
        _raw(f"DELETE FROM {table}")  # noqa: S608 - the table names are the test's own

    assert AIInteraction.objects.count() == 1


def test_the_configuration_of_the_repository_is_valid() -> None:
    configuration = config.load()

    assert configuration.provider.endpoint.startswith("https://")
    assert 0 < configuration.per_account_daily <= configuration.instance_daily


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (('name = "groq"', 'name = "oracle"'), "Unknown provider"),
        (('endpoint = "https://', 'endpoint = "http://'), "https"),
        (("per_account_daily = 20", "per_account_daily = 500"), "quota"),
        (("segments = 5", "segments = 0"), "positive"),
        (("deadline_seconds = 60", "deadline_seconds = 0"), "positive"),
        (("max_calls = 3", "max_calls = 4"), "two or three"),
        (("max_calls = 3", "max_calls = 1"), "two or three"),
    ],
)
def test_a_configuration_outside_what_the_code_does_is_refused(
    tmp_path: Path, change: tuple[str, str], message: str
) -> None:
    path = tmp_path / "assistant.toml"
    path.write_text(config.PATH.read_text(encoding="utf-8").replace(*change), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        config.load(path)


def test_an_interaction_is_found_by_its_public_identifier(reader: AuthenticationContext) -> None:
    public_id = _ask(reader)

    assert services.interaction_key(public_id) == AIInteraction.objects.get(public_id=public_id).pk
    with pytest.raises(InvalidEntryError):
        services.interaction_key(uuid.uuid4())
