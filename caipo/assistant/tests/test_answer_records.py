"""The record of an answer is append-only (CLAUDE.md rule 7; ADR-0025 point 9)."""

import pytest
from django.db import connection, transaction
from django.db.utils import IntegrityError
from psycopg import sql

from caipo.accounts.selectors import Role
from caipo.accounts.tests.fixtures import ActingAs
from caipo.assistant import config
from caipo.assistant.models import AIInteraction, AnswerCitation, AnswerStatement, RetrievalHit
from caipo.assistant.services import begin_interaction

pytestmark = [pytest.mark.services, pytest.mark.django_db]


@pytest.fixture
def interaction(acting_as: ActingAs) -> AIInteraction:
    start = begin_interaction(
        actor=acting_as(Role.READER), assistant="help", question="TEST", prompt_versions={}
    )
    return AIInteraction.objects.get(public_id=start.public_id)


def _records(interaction: AIInteraction) -> None:
    RetrievalHit.objects.create(
        interaction=interaction,
        kind="help",
        handle="H1",
        in_context=True,
        help_page="about",
        help_section="what-caipo-is",
    )
    statement = AnswerStatement.objects.create(
        interaction=interaction,
        position=0,
        text="TEST",
        label="documented_statement",
        verification="verified",
    )
    AnswerCitation.objects.create(
        statement=statement, handle="H1", kind="help", help_page="about", help_section="what"
    )


@pytest.mark.parametrize(
    "table", ["assistant_retrievalhit", "assistant_answerstatement", "assistant_answercitation"]
)
def test_the_database_refuses_any_change_or_deletion(
    interaction: AIInteraction, table: str
) -> None:
    _records(interaction)

    for statement, operation in (
        (sql.SQL("UPDATE {} SET id = id"), "UPDATE"),
        (sql.SQL("DELETE FROM {}"), "DELETE"),
    ):
        with pytest.raises(IntegrityError, match=f"append-only: {operation} refused"):
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(statement.format(sql.Identifier(table)))

    assert AnswerCitation.objects.count() == 1


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"verification": "removed", "removal_reason": ""}, "removed_has_reason"),
        ({"verification": "verified", "removal_reason": "quote"}, "removed_has_reason"),
        ({"verification": "verified", "label": "interpretation"}, "verified_has_label"),
    ],
)
def test_a_statement_is_either_verified_with_a_label_or_removed_with_a_reason(
    interaction: AIInteraction, values: dict[str, str], constraint: str
) -> None:
    fields = {"label": "documented_statement", "removal_reason": ""} | values

    with pytest.raises(IntegrityError, match=constraint), transaction.atomic():
        AnswerStatement.objects.create(interaction=interaction, position=0, text="TEST", **fields)


def test_a_hit_given_to_the_model_has_a_handle(interaction: AIInteraction) -> None:
    with pytest.raises(IntegrityError, match="in_context_has_handle"), transaction.atomic():
        RetrievalHit.objects.create(
            interaction=interaction, kind="help", in_context=True, help_page="about"
        )


def test_every_prompt_in_use_is_a_file_of_the_repository() -> None:
    configuration = config.load()

    for name in configuration.prompts:
        version, text = configuration.prompt(name)
        assert version and text.strip()
