"""Read interface of the assistants: quotas left, the provider, and an interaction's outcome.

An interaction's outcome is derived from its stage records, never stored
(DATA_MODEL.md §4.5).
"""

import uuid
from dataclasses import dataclass

from caipo.accounts import selectors as accounts_selectors
from caipo.accounts.selectors import AuthenticationContext, Permission
from caipo.assistant import config
from caipo.assistant.models import (
    AssistantKind,
    AssistantLabel,
    EvidenceKind,
    InteractionStageRecord,
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
    "Outcome",
    "ProviderNotice",
    "QuotasLeft",
    "interaction_outcome",
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
