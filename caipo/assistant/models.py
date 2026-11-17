"""The record of every question put to the demonstrator's assistants (DATA_MODEL.md §3.9).

Append-only, as CLAUDE.md rule 7 requires of AI interaction records: an
interaction is created once with fields that never change, and each stage of
the pipeline adds a record of its own. Its outcome is derived from those
records, never stored. Database triggers refuse every UPDATE and DELETE.
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from caipo.core.append_only import AppendOnlyModel, AppendOnlyQuerySet

MODEL_IDENTIFIER_MAX_LENGTH = 200


class AssistantKind(models.TextChoices):
    RESEARCH = "research", _("Research assistant")
    HELP = "help", _("Help assistant")


class QuestionLanguage(models.TextChoices):
    ENGLISH = "english", _("English")
    RUSSIAN = "russian", _("Russian")


class Stage(models.TextChoices):
    """The fixed sequence of AI_ARCHITECTURE.md §2."""

    INPUT_GUARD = "input_guard", _("Input guard")
    QUERY_ANALYSIS = "query_analysis", _("Query analysis")
    RETRIEVAL = "retrieval", _("Retrieval")
    EVIDENCE_VERIFICATION = "evidence_verification", _("Evidence verification")
    SYNTHESIS = "synthesis", _("Synthesis")
    CITATION_VERIFICATION = "citation_verification", _("Citation verification")
    RESPONSE = "response", _("Response assembly")


class StageResult(models.TextChoices):
    PASSED = "passed", _("Passed")
    ABSTAINED = "abstained", _("Abstained")
    REFUSED = "refused", _("Refused")
    FAILED = "failed", _("Failed")
    TIMED_OUT = "timed_out", _("Timed out")


class AIInteraction(AppendOnlyModel):
    """One question, with what was used to answer it; created once, never changed."""

    public_id = models.UUIDField(_("public identifier"), default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("asked by"),
    )
    assistant = models.CharField(_("assistant"), max_length=16, choices=AssistantKind)
    question = models.TextField(_("question"))
    language = models.CharField(
        _("language of the question"), max_length=8, choices=QuestionLanguage
    )
    pipeline_version = models.CharField(_("pipeline version"), max_length=64)
    prompt_versions = models.JSONField(_("prompt versions"), default=dict)
    model_identifier = models.CharField(_("model"), max_length=MODEL_IDENTIFIER_MAX_LENGTH)
    generation_settings = models.JSONField(_("generation settings"), default=dict)
    chunking_version = models.CharField(_("chunking configuration version"), max_length=64)
    created_at = models.DateTimeField(_("asked at"), auto_now_add=True)

    objects = AppendOnlyQuerySet["AIInteraction"].as_manager()

    class Meta:
        verbose_name = _("AI interaction")
        verbose_name_plural = _("AI interactions")
        indexes = [models.Index(fields=["created_at"], name="assistant_interaction_asked")]
        constraints = [
            models.UniqueConstraint(
                fields=["public_id"], name="assistant_interaction_public_id_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(assistant__in=AssistantKind.values),
                name="assistant_interaction_assistant_known",
            ),
            models.CheckConstraint(
                condition=models.Q(language__in=QuestionLanguage.values),
                name="assistant_interaction_language_known",
            ),
            models.CheckConstraint(
                condition=~models.Q(question=""), name="assistant_interaction_question_present"
            ),
        ]

    def __str__(self) -> str:
        return str(self.public_id)


class InteractionStageRecord(AppendOnlyModel):
    """One stage of the pipeline as it ran for one interaction (AI_ARCHITECTURE.md §2)."""

    interaction = models.ForeignKey(
        AIInteraction,
        on_delete=models.PROTECT,
        related_name="stages",
        verbose_name=_("interaction"),
    )
    stage = models.CharField(_("stage"), max_length=32, choices=Stage)
    result = models.CharField(_("result"), max_length=16, choices=StageResult)
    reason = models.CharField(_("reason"), max_length=64, blank=True)
    detail = models.JSONField(_("detail"), default=dict)
    input_tokens = models.PositiveIntegerField(_("input tokens"), default=0)
    output_tokens = models.PositiveIntegerField(_("output tokens"), default=0)
    duration_ms = models.PositiveIntegerField(_("duration in milliseconds"), default=0)
    created_at = models.DateTimeField(_("recorded at"), auto_now_add=True)

    objects = AppendOnlyQuerySet["InteractionStageRecord"].as_manager()

    class Meta:
        verbose_name = _("interaction stage record")
        verbose_name_plural = _("interaction stage records")
        constraints = [
            models.UniqueConstraint(
                fields=["interaction", "stage"], name="assistant_stage_once_per_interaction"
            ),
            models.CheckConstraint(
                condition=models.Q(stage__in=Stage.values), name="assistant_stage_known"
            ),
            models.CheckConstraint(
                condition=models.Q(result__in=StageResult.values),
                name="assistant_stage_result_known",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.interaction_id}:{self.stage}:{self.result}"
