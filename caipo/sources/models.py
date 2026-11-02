"""Sources and the documents registered from them: the demonstrator form (ADR-0020).

Metadata only. A Source is a publishing channel; a Document is one work from
it, described by its title, form, identifier, date, and official address.
No bytes, no text, no artifact, no extraction: those wait for the
research-grade build of Phase 2 (DATA_MODEL.md §3.3). What a document says is
never held for a reference document, whose rights are not decided (B7).

Every record carries its data class (`caipo.core.data_class`), held by a
database check. Nothing is deleted: the foreign keys that point here protect
what they point at.
"""

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from caipo.core.data_class import DataClass

TITLE_MAX_LENGTH = 1000
NAME_MAX_LENGTH = 300
URL_MAX_LENGTH = 2000


class SourceTier(models.TextChoices):
    """A source's relationship to what it reports (RESEARCH_PROTOCOL.md §4.1).

    A neutral category, not a rating of quality: the letters are no ranking.
    """

    A = "A", _("A: Official primary legal or policy text")
    B = "B", _("B: Official secondary material")
    C = "C", _("C: Intergovernmental or multilateral organisation")
    D = "D", _("D: Peer-reviewed research")
    E = "E", _("E: Independent research institute")
    F = "F", _("F: News media")
    G = "G", _("G: Other")


class PermittedUse(models.TextChoices):
    """What the recorded terms of a source allow the project to do with what it publishes."""

    STORE = "store", _("May be stored and redistributed with attribution")
    PROCESS = "process", _("May be processed, not redistributed")
    REFERENCE_ONLY = "reference_only", _("Reference only: metadata and address, no content")


class DocumentType(models.TextChoices):
    """The form of a document (DATA_MODEL.md §3.3)."""

    LAW = "law", _("Law")
    DECREE = "decree", _("Decree")
    RESOLUTION = "resolution", _("Resolution")
    STRATEGY = "strategy", _("Strategy")
    PROGRAMME = "programme", _("Programme")
    REGULATION = "regulation", _("Regulation")
    REPORT = "report", _("Report")
    STATISTICAL_PUBLICATION = "statistical_publication", _("Statistical publication")
    ARTICLE = "article", _("Article")
    PRESS_RELEASE = "press_release", _("Press release")
    OTHER = "other", _("Other")


_WEB_ADDRESS = r"^https?://[^\s]+$"


class Source(models.Model):
    """A publishing channel, with what is known of its terms and coverage (ADR-0020)."""

    public_id = models.UUIDField(_("public identifier"), default=uuid.uuid4, editable=False)
    data_class = models.CharField(_("data class"), max_length=16, choices=DataClass)
    name = models.CharField(_("name"), max_length=NAME_MAX_LENGTH)
    publisher = models.CharField(_("publisher"), max_length=NAME_MAX_LENGTH)
    url = models.CharField(_("address"), max_length=URL_MAX_LENGTH)
    source_tier = models.CharField(_("source tier"), max_length=1, choices=SourceTier)
    # Empty for a publisher that covers several countries.
    country = models.ForeignKey(
        "registry.Country",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("country"),
    )
    licence = models.CharField(_("licence or terms"), max_length=500, blank=True)
    licence_verified = models.BooleanField(_("licence verified"), default=False)
    permitted_use = models.CharField(_("permitted use"), max_length=16, choices=PermittedUse)
    accessed_on = models.DateField(_("accessed on"))
    coverage = models.TextField(_("coverage"), blank=True)
    limitations = models.TextField(_("limitations"), blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("source")
        verbose_name_plural = _("sources")
        constraints = [
            models.UniqueConstraint(fields=["public_id"], name="sources_source_public_id_unique"),
            models.CheckConstraint(
                condition=models.Q(data_class__in=DataClass.values),
                name="sources_source_data_class_known",
            ),
            models.CheckConstraint(
                condition=models.Q(source_tier__in=SourceTier.values),
                name="sources_source_tier_known",
            ),
            models.CheckConstraint(
                condition=models.Q(permitted_use__in=PermittedUse.values),
                name="sources_source_permitted_use_known",
            ),
            models.CheckConstraint(
                condition=models.Q(url__regex=_WEB_ADDRESS), name="sources_source_url_form"
            ),
            models.CheckConstraint(
                condition=~models.Q(name="") & ~models.Q(publisher=""),
                name="sources_source_named",
            ),
            # A licence is not called verified unless it is written down.
            models.CheckConstraint(
                condition=models.Q(licence_verified=False) | ~models.Q(licence=""),
                name="sources_source_verified_licence_stated",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Document(models.Model):
    """One work registered from a source, by its metadata only (ADR-0020 point 7)."""

    public_id = models.UUIDField(_("public identifier"), default=uuid.uuid4, editable=False)
    source = models.ForeignKey(
        Source, on_delete=models.PROTECT, related_name="documents", verbose_name=_("source")
    )
    data_class = models.CharField(_("data class"), max_length=16, choices=DataClass)
    country = models.ForeignKey(
        "registry.Country", on_delete=models.PROTECT, related_name="+", verbose_name=_("country")
    )
    issuing_institution = models.ForeignKey(
        "registry.Institution",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("issuing institution"),
    )
    document_type = models.CharField(_("form"), max_length=32, choices=DocumentType)
    title = models.CharField(_("title as written"), max_length=TITLE_MAX_LENGTH)
    title_language = models.ForeignKey(
        "registry.Language",
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("language of the title"),
    )
    title_en = models.CharField(_("English title"), max_length=TITLE_MAX_LENGTH, blank=True)
    title_en_official = models.BooleanField(_("English title is official"), default=False)
    official_identifier = models.CharField(_("official identifier"), max_length=200, blank=True)
    date_of_issue = models.DateField(_("date of issue"), null=True, blank=True)
    official_url = models.CharField(_("official address"), max_length=URL_MAX_LENGTH, blank=True)
    accessed_on = models.DateField(_("accessed on"), null=True, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("document")
        verbose_name_plural = _("documents")
        constraints = [
            models.UniqueConstraint(fields=["public_id"], name="sources_document_public_id_unique"),
            models.CheckConstraint(
                condition=models.Q(data_class__in=DataClass.values),
                name="sources_document_data_class_known",
            ),
            models.CheckConstraint(
                condition=models.Q(document_type__in=DocumentType.values),
                name="sources_document_type_known",
            ),
            models.CheckConstraint(condition=~models.Q(title=""), name="sources_document_titled"),
            models.CheckConstraint(
                condition=models.Q(official_url="") | models.Q(official_url__regex=_WEB_ADDRESS),
                name="sources_document_official_url_form",
            ),
            # An English title is called official only if there is one.
            models.CheckConstraint(
                condition=models.Q(title_en_official=False) | ~models.Q(title_en=""),
                name="sources_document_official_english_title_given",
            ),
        ]

    def __str__(self) -> str:
        return self.title
