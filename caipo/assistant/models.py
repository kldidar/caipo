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


class EvidenceKind(models.TextChoices):
    """What a handle stands for: a recorded value, a demonstration text, or a section of help."""

    OBSERVATION = "observation", _("Recorded observation")
    SEGMENT = "segment", _("Demonstration text")
    HELP = "help", _("Help section")


class AssistantLabel(models.TextChoices):
    """The four labels an assistant statement may carry (AI_ARCHITECTURE.md §7.3)."""

    DOCUMENTED_STATEMENT = "documented_statement", _("Documented statement")
    STATED_POLICY_OBJECTIVE = "stated_policy_objective", _("Stated policy objective")
    REPORTED_IMPLEMENTATION = "reported_implementation", _("Reported implementation")
    RECORDED_OBSERVATION = "recorded_observation", _("Recorded observation")


class Verification(models.TextChoices):
    VERIFIED = "verified", _("Verified")
    REMOVED = "removed", _("Removed")


class RemovalReason(models.TextChoices):
    """Why a statement was removed: one per check of AI_ARCHITECTURE.md §6.2."""

    NO_CITATION = "no_citation", _("It cites nothing")
    UNKNOWN_HANDLE = "unknown_handle", _("It cites a handle not issued for this question")
    LABEL = "label", _("Its label is not permitted for what it cites")
    QUOTE = "quote", _("A quotation is not in the cited text")
    NUMBER = "number", _("A number is not in the cited evidence")
    MARKUP = "markup", _("It holds a link or markup")
    CAUSAL_WORDING = "causal_wording", _("It uses wording on the prohibited list")
    NOT_SUPPORTED = "not_supported", _("The support check did not find it supported")
    MALFORMED = "malformed", _("It is not in the required form")


class RetrievalHit(AppendOnlyModel):
    """One candidate retrieved for an interaction, whether or not it reached the model."""

    interaction = models.ForeignKey(
        AIInteraction, on_delete=models.PROTECT, related_name="hits", verbose_name=_("interaction")
    )
    kind = models.CharField(_("kind"), max_length=16, choices=EvidenceKind)
    handle = models.CharField(_("handle"), max_length=16, blank=True)
    in_context = models.BooleanField(_("placed in the model's context"))
    segment = models.UUIDField(_("segment"), null=True, blank=True)
    start_offset = models.PositiveIntegerField(_("start offset"), null=True, blank=True)
    end_offset = models.PositiveIntegerField(_("end offset"), null=True, blank=True)
    observation = models.ForeignKey(
        "indicators.Observation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("observation"),
    )
    help_page = models.CharField(_("help page"), max_length=64, blank=True)
    help_section = models.CharField(_("help section"), max_length=300, blank=True)
    lexical_rank = models.PositiveIntegerField(_("full-text rank"), null=True, blank=True)
    trigram_rank = models.PositiveIntegerField(_("trigram rank"), null=True, blank=True)
    score = models.FloatField(_("fused score"), null=True, blank=True)

    objects = AppendOnlyQuerySet["RetrievalHit"].as_manager()

    class Meta:
        verbose_name = _("retrieval hit")
        verbose_name_plural = _("retrieval hits")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(kind__in=EvidenceKind.values),
                name="assistant_hit_kind_known",
            ),
            models.CheckConstraint(
                condition=models.Q(in_context=False) | ~models.Q(handle=""),
                name="assistant_hit_in_context_has_handle",
            ),
            models.CheckConstraint(
                condition=models.Q(kind=EvidenceKind.OBSERVATION, observation__isnull=False)
                | models.Q(
                    kind=EvidenceKind.SEGMENT,
                    segment__isnull=False,
                    start_offset__isnull=False,
                    end_offset__isnull=False,
                )
                | (models.Q(kind=EvidenceKind.HELP) & ~models.Q(help_page="")),
                name="assistant_hit_kind_fits_its_reference",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.interaction_id}:{self.handle or self.kind}"


class AnswerStatement(AppendOnlyModel):
    """One statement the model wrote, with the verdict of the checks on it."""

    interaction = models.ForeignKey(
        AIInteraction,
        on_delete=models.PROTECT,
        related_name="statements",
        verbose_name=_("interaction"),
    )
    position = models.PositiveIntegerField(_("position"))
    text = models.TextField(_("text"))
    label = models.CharField(_("label"), max_length=32, blank=True)
    verification = models.CharField(_("verification"), max_length=16, choices=Verification)
    removal_reason = models.CharField(
        _("reason for removal"), max_length=32, choices=RemovalReason, blank=True
    )
    flags = models.JSONField(_("uncertainty flags"), default=list)

    objects = AppendOnlyQuerySet["AnswerStatement"].as_manager()

    class Meta:
        verbose_name = _("answer statement")
        verbose_name_plural = _("answer statements")
        constraints = [
            models.UniqueConstraint(
                fields=["interaction", "position"], name="assistant_statement_position_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(verification=Verification.VERIFIED, removal_reason="")
                | models.Q(
                    verification=Verification.REMOVED, removal_reason__in=RemovalReason.values
                ),
                name="assistant_statement_removed_has_reason",
            ),
            models.CheckConstraint(
                condition=models.Q(verification=Verification.REMOVED)
                | models.Q(label__in=AssistantLabel.values),
                name="assistant_statement_verified_has_label",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.interaction_id}:{self.position}"


class AnswerCitation(AppendOnlyModel):
    """A verified statement's citation of a Passage, an Observation, or a help section."""

    statement = models.ForeignKey(
        AnswerStatement,
        on_delete=models.PROTECT,
        related_name="citations",
        verbose_name=_("statement"),
    )
    handle = models.CharField(_("handle"), max_length=16)
    kind = models.CharField(_("kind"), max_length=16, choices=EvidenceKind)
    passage = models.UUIDField(_("passage"), null=True, blank=True)
    observation = models.ForeignKey(
        "indicators.Observation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("observation"),
    )
    help_page = models.CharField(_("help page"), max_length=64, blank=True)
    help_section = models.CharField(_("help section"), max_length=300, blank=True)

    objects = AppendOnlyQuerySet["AnswerCitation"].as_manager()

    class Meta:
        verbose_name = _("answer citation")
        verbose_name_plural = _("answer citations")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(kind=EvidenceKind.OBSERVATION, observation__isnull=False)
                | models.Q(kind=EvidenceKind.SEGMENT, passage__isnull=False)
                | (
                    models.Q(kind=EvidenceKind.HELP)
                    & ~models.Q(help_page="")
                    & ~models.Q(help_section="")
                ),
                name="assistant_citation_kind_fits_its_reference",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.statement_id}:{self.handle}"
