"""Read interface of the assistants: quotas left, the provider, and an interaction's outcome.

An interaction's outcome is derived from its stage records, never stored
(DATA_MODEL.md §4.5).
"""

import uuid
from dataclasses import dataclass
from typing import Any

from caipo.accounts import selectors as accounts_selectors
from caipo.accounts.selectors import AuthenticationContext, Permission
from caipo.assistant import config
from caipo.assistant.models import (
    AIInteraction,
    AnswerStatement,
    AssistantKind,
    AssistantLabel,
    EvidenceKind,
    InteractionStageRecord,
    RetrievalHit,
    Stage,
    StageResult,
    UncertaintyFlag,
)
from caipo.assistant.quotas import asked_today

__all__ = [
    "AssistantKind",
    "AssistantLabel",
    "EvidenceKind",
    "UncertaintyFlag",
    "HitEntry",
    "InteractionRecord",
    "Outcome",
    "ProviderNotice",
    "QuotasLeft",
    "StageEntry",
    "StatementEntry",
    "interaction_outcome",
    "interaction_record",
    "provider_notice",
    "quotas_left",
]

# The order of the stages, by which the first that did not pass is found.
_ORDER = list(Stage.values)
# A stage's result, as the interaction's outcome.
_OUTCOME = {
    StageResult.ABSTAINED: "abstained",
    StageResult.REFUSED: "refused",
    StageResult.FAILED: "failed",
    StageResult.TIMED_OUT: "timed_out",
}


class Outcome:
    ANSWERED = "answered"
    ABSTAINED = "abstained"
    REFUSED = "refused"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class ProviderNotice:
    label: str
    model: str


def provider_notice() -> ProviderNotice:
    """The provider and model that questions are sent to, as each assistant names them.

    ADR-0025 point 8: the asker is told, next to the input, where a question goes.
    """
    provider = config.load().provider
    return ProviderNotice(label=provider.label, model=provider.model)


@dataclass(frozen=True)
class QuotasLeft:
    account: int
    instance: int


def quotas_left(actor: AuthenticationContext) -> QuotasLeft:
    """The questions this account, and the whole instance, may still ask today (UTC).

    Raises PermissionDenied if the actor may not ask.
    """
    accounts_selectors.require_permission(actor, Permission.ASSISTANT_ASK)
    configuration = config.load()
    today = asked_today()
    return QuotasLeft(
        account=max(0, configuration.per_account_daily - today.filter(user=actor.user).count()),
        instance=max(0, configuration.instance_daily - today.count()),
    )


def interaction_outcome(interaction: uuid.UUID) -> str | None:
    """The outcome of an interaction, derived from its stages; None while it has none yet.

    The first stage, in the pipeline's order, that did not pass gives the
    outcome. If every recorded stage passed and the response was assembled,
    the interaction was answered. Unknown interactions give None.
    """
    stages = dict(
        InteractionStageRecord.objects.filter(interaction__public_id=interaction).values_list(
            "stage", "result"
        )
    )
    for stage in sorted(stages, key=_ORDER.index):
        if stages[stage] != StageResult.PASSED:
            return _OUTCOME[StageResult(stages[stage])]
    if stages.get(Stage.RESPONSE) == StageResult.PASSED:
        return Outcome.ANSWERED
    return None


@dataclass(frozen=True)
class StageEntry:
    stage: str
    result: str
    reason: str
    detail: dict[str, Any]
    input_tokens: int
    output_tokens: int
    duration_ms: int


@dataclass(frozen=True)
class HitEntry:
    """One item of evidence placed before the model, under its handle."""

    handle: str
    kind: str
    segment: uuid.UUID | None
    observation_id: int | None
    help_page: str
    help_section: str


@dataclass(frozen=True)
class StatementEntry:
    """One statement the model wrote, the verdict on it, and, if shown, the handles it cites."""

    position: int
    text: str
    label: str
    verification: str
    removal_reason: str
    cited: tuple[str, ...]


@dataclass(frozen=True)
class InteractionRecord:
    question: str
    language: str
    assistant: str
    model_identifier: str
    prompt_versions: dict[str, str]
    stages: tuple[StageEntry, ...]
    hits: tuple[HitEntry, ...]
    statements: tuple[StatementEntry, ...]


def interaction_record(interaction: uuid.UUID) -> InteractionRecord | None:
    """Everything recorded of one interaction, in the pipeline's order; None if there is none.

    For the evaluation of the assistants (AI_ARCHITECTURE.md §9), which reads
    what each stage did. Only shown statements have citations, so a removed
    statement cites nothing here. It checks no permission: it is for the
    evaluation command, which runs only on a database of its own.
    """
    found = AIInteraction.objects.filter(public_id=interaction).first()
    if found is None:
        return None
    stages = sorted(
        InteractionStageRecord.objects.filter(interaction=found),
        key=lambda record: _ORDER.index(record.stage),
    )
    statements = AnswerStatement.objects.filter(interaction=found).order_by("position")
    return InteractionRecord(
        question=found.question,
        language=found.language,
        assistant=found.assistant,
        model_identifier=found.model_identifier,
        prompt_versions=dict(found.prompt_versions),
        stages=tuple(
            StageEntry(
                stage=record.stage,
                result=record.result,
                reason=record.reason,
                detail=dict(record.detail),
                input_tokens=record.input_tokens,
                output_tokens=record.output_tokens,
                duration_ms=record.duration_ms,
            )
            for record in stages
        ),
        hits=tuple(
            HitEntry(
                handle=hit.handle,
                kind=hit.kind,
                segment=hit.segment,
                observation_id=hit.observation_id,
                help_page=hit.help_page,
                help_section=hit.help_section,
            )
            for hit in RetrievalHit.objects.filter(interaction=found).order_by("pk")
        ),
        statements=tuple(
            StatementEntry(
                position=statement.position,
                text=statement.text,
                label=statement.label,
                verification=statement.verification,
                removal_reason=statement.removal_reason,
                cited=tuple(statement.citations.order_by("pk").values_list("handle", flat=True)),
            )
            for statement in statements
        ),
    )
