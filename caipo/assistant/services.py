"""Write interface of the assistants: starting an interaction and recording its stages.

The input guard of AI_ARCHITECTURE.md §3: the account may ask, the question
is acceptable, and the quotas are not spent. Only then is an AIInteraction
created, with the fields that never change. Each later stage adds one
InteractionStageRecord. Nothing is updated or deleted (CLAUDE.md rule 7).
"""

import logging
import unicodedata
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.db import connection, transaction
from django.utils.translation import gettext as _

from caipo.accounts import selectors as accounts_selectors
from caipo.accounts.selectors import AuthenticationContext, Permission
from caipo.assistant import config
from caipo.assistant.models import (
    AIInteraction,
    AssistantKind,
    InteractionStageRecord,
    QuestionLanguage,
    Stage,
    StageResult,
)
from caipo.assistant.quotas import asked_today
from caipo.core.entry import InvalidEntryError, has_direction_control
from caipo.retrieval import selectors as retrieval_selectors

if TYPE_CHECKING:
    from caipo.assistant import pipeline

logger = logging.getLogger(__name__)

# Serialises the counting of the quotas, so that two questions asked at once
# cannot both take the last place of a day. Any fixed number would do.
_QUOTA_LOCK = 25_0007


class QuotaExceededError(Exception):
    """A daily quota is spent: the account's or the instance's. Nothing was recorded."""

    def __init__(self, scope: str) -> None:
        super().__init__(scope)
        self.scope = scope


@dataclass(frozen=True)
class InteractionStart:
    public_id: uuid.UUID
    question: str
    language: str


def detect_language(question: str) -> str:
    """Russian if the question has more Cyrillic letters than Latin ones, else English.

    Deterministic, so the language of an interaction never depends on a model.
    """
    cyrillic = sum(1 for ch in question if "CYRILLIC" in unicodedata.name(ch, ""))
    latin = sum(1 for ch in question if "LATIN" in unicodedata.name(ch, ""))
    return QuestionLanguage.RUSSIAN if cyrillic > latin else QuestionLanguage.ENGLISH


def _clean_question(question: str, max_length: int) -> str:
    text = unicodedata.normalize("NFC", question).strip()
    if not text:
        raise InvalidEntryError(_("Ask a question."))
    if len(text) > max_length:
        raise InvalidEntryError(
            _("A question is at most %(limit)d characters.") % {"limit": max_length}
        )
    if has_direction_control(text):
        raise InvalidEntryError(_("The question holds a direction control character."))
    return text


def begin_interaction(
    *,
    actor: AuthenticationContext,
    assistant: str,
    question: str,
    prompt_versions: Mapping[str, str],
) -> InteractionStart:
    """Pass the input guard and record a new interaction; return what the pipeline needs.

    Preconditions: the actor holds `ASSISTANT_ASK`; the assistant is one of
    `AssistantKind`; the question, in NFC and without surrounding whitespace,
    is not empty, is at most the configured length, and holds no direction
    control; fewer than the configured number of questions were recorded
    today (UTC) by this account and by the whole instance.

    Side effects: one AIInteraction, with the pipeline version, the prompt
    versions given, the model identifier and generation settings, and the
    chunking version, and one `input_guard` stage record that passed, in one
    transaction; a log line follows, without the question.

    Raises PermissionDenied before anything else is examined;
    InvalidEntryError for an unknown assistant or an unacceptable question;
    QuotaExceededError naming the quota that is spent. Nothing is recorded in
    any of those cases, and no model is called.
    """
    accounts_selectors.require_permission(actor, Permission.ASSISTANT_ASK)
    if assistant not in AssistantKind.values:
        raise InvalidEntryError(_("There is no such assistant."))
    configuration = config.load()
    text = _clean_question(question, configuration.max_question_length)
    provider = configuration.provider
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_QUOTA_LOCK])
        today = asked_today()
        if today.filter(user=actor.user).count() >= configuration.per_account_daily:
            raise QuotaExceededError("account")
        if today.count() >= configuration.instance_daily:
            raise QuotaExceededError("instance")
        interaction = AIInteraction.objects.create(
            user=actor.user,
            assistant=assistant,
            question=text,
            language=detect_language(text),
            pipeline_version=configuration.pipeline_version,
            prompt_versions=dict(prompt_versions),
            model_identifier=f"{provider.name}:{provider.model}",
            generation_settings={
                "temperature": provider.temperature,
                "max_output_tokens": provider.max_output_tokens,
            },
            chunking_version=retrieval_selectors.chunking_version(),
        )
        InteractionStageRecord.objects.create(
            interaction=interaction, stage=Stage.INPUT_GUARD, result=StageResult.PASSED
        )
    logger.info(
        "Assistant question accepted",
        extra={
            "event": "assistant.interaction_started",
            "public_id": str(interaction.public_id),
            "assistant": assistant,
            "actor_id": actor.user.pk,
        },
    )
    return InteractionStart(interaction.public_id, text, interaction.language)


def record_stage(
    *,
    interaction: uuid.UUID,
    stage: str,
    result: str,
    reason: str = "",
    detail: Mapping[str, Any] | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    duration_ms: int = 0,
) -> None:
    """Record how one stage of the pipeline ran for an interaction.

    Preconditions: the interaction exists, the stage and result are listed
    values, and the stage has not been recorded for it. Called by the
    pipeline of this app after `begin_interaction`, which checked the
    account's permission; it takes no actor.

    Side effects: one InteractionStageRecord.

    Raises InvalidEntryError for an unknown interaction, stage, or result, or
    a stage already recorded. Nothing is recorded in those cases.
    """
    if stage not in Stage.values or result not in StageResult.values:
        raise InvalidEntryError(_("Unknown stage or result."))
    with transaction.atomic():
        found = AIInteraction.objects.filter(public_id=interaction).values_list("pk", flat=True)
        interaction_pk = found.first()
        if interaction_pk is None:
            raise InvalidEntryError(_("There is no such interaction."))
        if InteractionStageRecord.objects.filter(
            interaction_id=interaction_pk, stage=stage
        ).exists():
            raise InvalidEntryError(_("That stage is recorded already."))
        InteractionStageRecord.objects.create(
            interaction_id=interaction_pk,
            stage=stage,
            result=result,
            reason=reason,
            detail=dict(detail or {}),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=duration_ms,
        )


def interaction_key(interaction: uuid.UUID) -> int:
    """The internal key of an interaction, for the records of its answer in this app.

    Raises InvalidEntryError if there is no such interaction.
    """
    key = AIInteraction.objects.filter(public_id=interaction).values_list("pk", flat=True).first()
    if key is None:
        raise InvalidEntryError(_("There is no such interaction."))
    return key


def answer_question(
    *, actor: AuthenticationContext, assistant: str, question: str
) -> pipeline.Answer:
    """Answer a question through the pipeline: verified statements, or a stated reason.

    The write interface of the pipeline for the pages; see
    `pipeline.answer_question` for its preconditions, side effects, and the
    errors it raises (those of `begin_interaction`).
    """
    # The pipeline is built on this module's services, so it is imported here.
    from caipo.assistant import pipeline

    return pipeline.answer_question(actor=actor, assistant=assistant, question=question)
