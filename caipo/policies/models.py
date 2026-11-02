"""Policies, their documents, formal events, and AI-related provisions (ADR-0020).

A Policy is a unit of analysis expressed in one or more documents. Its
assignment to the core AI policy corpus or the contextual policy registry
(RESEARCH_PROTOCOL.md §3.1.5) is a provisional working assignment with a
reason, never an eligibility decision (ADR-0020 point 8).

A policy has **no stored status**. Its formal status is derived from its
PolicyEvents (DATA_MODEL.md §4.4), which are formal lifecycle events only
and are append-only. Implementation is never a PolicyEvent.

Without ingestion there is no Passage, so an event or a provision cites a
document and a locator (ADR-0020 point 11). Provision text may be held only
for demonstration data, which is synthetic; a database check refuses it on
a reference record.
"""

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from caipo.core.append_only import AppendOnlyModel, AppendOnlyQuerySet
from caipo.core.data_class import DataClass

TITLE_MAX_LENGTH = 1000
LOCATOR_MAX_LENGTH = 200


class PolicyType(models.TextChoices):
    """The kind of initiative. Provisional: the codebook that fixes these is not written (B11)."""

    STRATEGY = "strategy", _("Strategy")
    CONCEPT = "concept", _("Concept")
    PROGRAMME = "programme", _("Programme")
    ACTION_PLAN = "action_plan", _("Action plan")
    LAW = "law", _("Law")
    REGULATION = "regulation", _("Regulation")
    OTHER = "other", _("Other")


class CorpusAssignment(models.TextChoices):
    CORE = "core", _("Core AI policy corpus")
    CONTEXTUAL = "contextual", _("Contextual policy registry")


class AIFocus(models.TextChoices):
    """How a core policy relates to AI (RESEARCH_PROTOCOL.md §3.1.2)."""

    AI_FOCUSED = "ai_focused", _("AI-focused instrument")
    AI_PROVISIONS = "ai_provisions", _("Broader instrument with AI-related provisions")


class ContextualCategory(models.TextChoices):
    """The category of contextual material. Provisional: the list is OPEN (O-7)."""

    DIGITAL_ECONOMY = "digital_economy", _("Digital economy")
    DATA_GOVERNANCE = "data_governance", _("Data governance")
    TELECOMMUNICATIONS = "telecommunications", _("Telecommunications")
    EDUCATION = "education", _("Education")
    OTHER = "other", _("Other")


class Policy(models.Model):
    """A policy initiative, with its provisional place in the core corpus or the contextual
    registry."""

    public_id = models.UUIDField(_("public identifier"), default=uuid.uuid4, editable=False)
    data_class = models.CharField(_("data class"), max_length=16, choices=DataClass)
    country = models.ForeignKey(
        "registry.Country", on_delete=models.PROTECT, related_name="+", verbose_name=_("country")
    )
    lead_institution = models.ForeignKey(
        "registry.Institution",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("lead institution"),
    )
    policy_type = models.CharField(_("kind of policy"), max_length=16, choices=PolicyType)
    title = models.CharField(_("title as written"), max_length=TITLE_MAX_LENGTH)
    title_language = models.ForeignKey(
        "registry.Language",
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("language of the title"),
    )
    title_en = models.CharField(_("English title"), max_length=TITLE_MAX_LENGTH, blank=True)
    corpus_assignment = models.CharField(
        _("corpus assignment"), max_length=16, choices=CorpusAssignment
    )
    ai_focus = models.CharField(_("AI focus"), max_length=16, choices=AIFocus, blank=True)
    contextual_category = models.CharField(
        _("contextual category"), max_length=32, choices=ContextualCategory, blank=True
    )
    assignment_reason = models.TextField(_("reason for the assignment"))
    summary = models.TextField(_("summary"), blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("policy")
        verbose_name_plural = _("policies")
        constraints = [
            models.UniqueConstraint(fields=["public_id"], name="policies_policy_public_id_unique"),
            models.CheckConstraint(
                condition=models.Q(data_class__in=DataClass.values),
                name="policies_policy_data_class_known",
            ),
            models.CheckConstraint(
                condition=models.Q(policy_type__in=PolicyType.values),
                name="policies_policy_type_known",
            ),
            models.CheckConstraint(condition=~models.Q(title=""), name="policies_policy_titled"),
            # A core policy says how it relates to AI and has no contextual
            # category; a contextual one has a category and no AI focus.
            models.CheckConstraint(
                condition=(
                    models.Q(
                        corpus_assignment=CorpusAssignment.CORE,
                        ai_focus__in=AIFocus.values,
                        contextual_category="",
                    )
                    | models.Q(
                        corpus_assignment=CorpusAssignment.CONTEXTUAL,
                        ai_focus="",
                        contextual_category__in=ContextualCategory.values,
                    )
                ),
                name="policies_policy_assignment_consistent",
            ),
            models.CheckConstraint(
                condition=~models.Q(assignment_reason=""),
                name="policies_policy_assignment_reasoned",
            ),
        ]

    def __str__(self) -> str:
        return self.title_en or self.title


class DocumentRole(models.TextChoices):
    """What a document is to a policy (DATA_MODEL.md §3.6)."""

    ENACTING_TEXT = "enacting_text", _("Enacting text")
    AMENDMENT = "amendment", _("Amendment")
    IMPLEMENTING_ACT = "implementing_act", _("Implementing act")
    OFFICIAL_REPORT = "official_report", _("Official report")
    EXTERNAL_ASSESSMENT = "external_assessment", _("External assessment")
    COMMENTARY = "commentary", _("Commentary")


# The roles of a document that can establish a formal lifecycle event.
FORMAL_ROLES: frozenset[str] = frozenset(
    {DocumentRole.ENACTING_TEXT, DocumentRole.AMENDMENT, DocumentRole.IMPLEMENTING_ACT}
)


class PolicyDocumentLink(models.Model):
    """A document that expresses, amends, implements, or reports on a policy."""

    public_id = models.UUIDField(_("public identifier"), default=uuid.uuid4, editable=False)
    policy = models.ForeignKey(
        Policy, on_delete=models.PROTECT, related_name="document_links", verbose_name=_("policy")
    )
    document = models.ForeignKey(
        "sources.Document", on_delete=models.PROTECT, related_name="+", verbose_name=_("document")
    )
    role = models.CharField(_("role"), max_length=32, choices=DocumentRole)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("policy document")
        verbose_name_plural = _("policy documents")
        constraints = [
            models.UniqueConstraint(fields=["public_id"], name="policies_link_public_id_unique"),
            models.UniqueConstraint(
                fields=["policy", "document", "role"], name="policies_link_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=DocumentRole.values), name="policies_link_role_known"
            ),
        ]


class PolicyEventType(models.TextChoices):
    """Formal lifecycle events only (CLAUDE.md, architecture rule 9). There are no others."""

    ADOPTED = "adopted", _("Adopted")
    AMENDED = "amended", _("Amended")
    ENTERED_INTO_FORCE = "entered_into_force", _("Entered into force")
    EXPIRED = "expired", _("Expired")
    REPEALED = "repealed", _("Repealed")


class PolicyEvent(AppendOnlyModel):
    """A formal lifecycle event, established by a formal document of the policy. Append-only."""

    public_id = models.UUIDField(_("public identifier"), default=uuid.uuid4, editable=False)
    policy = models.ForeignKey(
        Policy, on_delete=models.PROTECT, related_name="events", verbose_name=_("policy")
    )
    event_type = models.CharField(_("event"), max_length=32, choices=PolicyEventType)
    effective_date = models.DateField(_("effective date"))
    document = models.ForeignKey(
        "sources.Document", on_delete=models.PROTECT, related_name="+", verbose_name=_("document")
    )
    locator = models.CharField(_("locator"), max_length=LOCATOR_MAX_LENGTH, blank=True)
    created_at = models.DateTimeField(_("recorded at"), auto_now_add=True)

    objects = AppendOnlyQuerySet["PolicyEvent"].as_manager()

    class Meta:
        verbose_name = _("policy event")
        verbose_name_plural = _("policy events")
        constraints = [
            models.UniqueConstraint(fields=["public_id"], name="policies_event_public_id_unique"),
            models.CheckConstraint(
                condition=models.Q(event_type__in=PolicyEventType.values),
                name="policies_event_type_known",
            ),
        ]


class ProvisionType(models.TextChoices):
    """What an AI-related provision provides for. Provisional: the codebook is not written (B11)."""

    OBJECTIVE = "objective", _("Objective")
    INSTRUMENT = "instrument", _("Instrument")
    INSTITUTIONAL = "institutional", _("Institutional arrangement")
    OTHER = "other", _("Other")


class PolicyProvision(models.Model):
    """An AI-related provision of a core policy, located in one of its documents."""

    public_id = models.UUIDField(_("public identifier"), default=uuid.uuid4, editable=False)
    policy = models.ForeignKey(
        Policy, on_delete=models.PROTECT, related_name="provisions", verbose_name=_("policy")
    )
    data_class = models.CharField(_("data class"), max_length=16, choices=DataClass)
    provision_type = models.CharField(_("kind of provision"), max_length=16, choices=ProvisionType)
    document = models.ForeignKey(
        "sources.Document", on_delete=models.PROTECT, related_name="+", verbose_name=_("document")
    )
    locator = models.CharField(_("locator"), max_length=LOCATOR_MAX_LENGTH)
    label = models.CharField(_("what it provides for"), max_length=300)
    quoted_text = models.TextField(_("quoted text"), blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("AI-related provision")
        verbose_name_plural = _("AI-related provisions")
        constraints = [
            models.UniqueConstraint(
                fields=["public_id"], name="policies_provision_public_id_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(data_class__in=DataClass.values),
                name="policies_provision_data_class_known",
            ),
            models.CheckConstraint(
                condition=models.Q(provision_type__in=ProvisionType.values),
                name="policies_provision_type_known",
            ),
            models.CheckConstraint(
                condition=~models.Q(locator="") & ~models.Q(label=""),
                name="policies_provision_located_and_labelled",
            ),
            # The text of a real document is not held while its rights are
            # undecided (ADR-0020 point 7); only synthetic text may be quoted.
            models.CheckConstraint(
                condition=models.Q(data_class=DataClass.DEMONSTRATION) | models.Q(quoted_text=""),
                name="policies_provision_no_reference_text",
            ),
        ]
