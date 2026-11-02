"""Analysis runs and search runs: the demonstrator form (ADR-0020, DATA_MODEL.md §3.7).

An AnalysisRun records a descriptive computation over stored observations:
its method and method version, its parameters, every input value it used
with the release that value came from, its result, and a SHA-256 fingerprint
of the inputs and of the result, so that running it again shows whether the
same inputs give the same result. It makes no correlation, causal, or
interpretive statement.

A SearchRun records a search for sources: what was searched, where, how,
by which criteria, what was examined, and what was found. It is how the
absence of a source is recorded: "no qualifying source found" is an outcome
of a search bounded by what was examined, and never a document.

Both are append-only.
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from caipo.core.append_only import AppendOnlyModel, AppendOnlyQuerySet
from caipo.core.data_class import DataClass

_FINGERPRINT = r"^[0-9a-f]{64}$"


class AnalysisMethod(models.TextChoices):
    DESCRIPTIVE_CHANGE = "descriptive_change", _("Descriptive change between two years")


class AnalysisRun(AppendOnlyModel):
    """A recorded descriptive analysis, with what it used and a fingerprint of each. Append-only."""

    public_id = models.UUIDField(_("public identifier"), default=uuid.uuid4, editable=False)
    data_class = models.CharField(_("data class"), max_length=16, choices=DataClass)
    title = models.CharField(_("title"), max_length=300)
    method = models.CharField(_("method"), max_length=32, choices=AnalysisMethod)
    method_version = models.PositiveSmallIntegerField(_("method version"))
    parameters = models.JSONField(_("parameters"))
    inputs = models.JSONField(_("inputs"))
    result = models.JSONField(_("result"))
    input_fingerprint = models.CharField(_("input fingerprint"), max_length=64)
    result_fingerprint = models.CharField(_("result fingerprint"), max_length=64)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("run by"),
    )
    created_at = models.DateTimeField(_("run at"), auto_now_add=True)

    objects = AppendOnlyQuerySet["AnalysisRun"].as_manager()

    class Meta:
        verbose_name = _("analysis run")
        verbose_name_plural = _("analysis runs")
        constraints = [
            models.UniqueConstraint(
                fields=["public_id"], name="research_analysis_public_id_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(data_class__in=DataClass.values),
                name="research_analysis_data_class_known",
            ),
            models.CheckConstraint(
                condition=models.Q(method__in=AnalysisMethod.values),
                name="research_analysis_method_known",
            ),
            models.CheckConstraint(
                condition=models.Q(input_fingerprint__regex=_FINGERPRINT)
                & models.Q(result_fingerprint__regex=_FINGERPRINT),
                name="research_analysis_fingerprints_form",
            ),
            models.CheckConstraint(condition=~models.Q(title=""), name="research_analysis_titled"),
        ]


class SearchLayer(models.TextChoices):
    """Which layer a search's inclusion criteria are for (RESEARCH_PROTOCOL.md §3.1.5)."""

    CORE = "core", _("Core AI policy corpus")
    CONTEXTUAL = "contextual", _("Contextual policy registry")
    INDICATORS = "indicators", _("Economic indicators")


class SearchOutcome(models.TextChoices):
    NO_QUALIFYING_SOURCE = "no_qualifying_source_found", _("No qualifying source found")
    QUALIFYING_SOURCES = "qualifying_sources_found", _("Qualifying sources found")
    INCONCLUSIVE = "inconclusive", _("Inconclusive")


class SearchRun(AppendOnlyModel):
    """A recorded search for sources, with its scope, method, and bounded outcome. Append-only."""

    public_id = models.UUIDField(_("public identifier"), default=uuid.uuid4, editable=False)
    data_class = models.CharField(_("data class"), max_length=16, choices=DataClass)
    title = models.CharField(_("title"), max_length=300)
    layer = models.CharField(_("layer searched for"), max_length=16, choices=SearchLayer)
    countries = models.CharField(_("countries"), max_length=200)
    searched_on = models.DateField(_("searched on"))
    queries = models.TextField(_("queries, in each language"))
    source_universe = models.TextField(_("sources in scope"))
    inclusion_criteria = models.TextField(_("inclusion criteria"))
    exclusion_criteria = models.TextField(_("exclusion criteria"), blank=True)
    sources_examined = models.TextField(_("sources examined"))
    method = models.TextField(_("method"))
    outcome = models.CharField(_("outcome"), max_length=32, choices=SearchOutcome)
    summary = models.TextField(_("summary"))
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("recorded by"),
    )
    created_at = models.DateTimeField(_("recorded at"), auto_now_add=True)

    objects = AppendOnlyQuerySet["SearchRun"].as_manager()

    class Meta:
        verbose_name = _("search run")
        verbose_name_plural = _("search runs")
        constraints = [
            models.UniqueConstraint(fields=["public_id"], name="research_search_public_id_unique"),
            models.CheckConstraint(
                condition=models.Q(data_class__in=DataClass.values),
                name="research_search_data_class_known",
            ),
            models.CheckConstraint(
                condition=models.Q(layer__in=SearchLayer.values), name="research_search_layer_known"
            ),
            models.CheckConstraint(
                condition=models.Q(outcome__in=SearchOutcome.values),
                name="research_search_outcome_known",
            ),
            models.CheckConstraint(
                condition=~models.Q(title="")
                & ~models.Q(queries="")
                & ~models.Q(source_universe="")
                & ~models.Q(inclusion_criteria="")
                & ~models.Q(sources_examined="")
                & ~models.Q(method="")
                & ~models.Q(summary=""),
                name="research_search_recorded_in_full",
            ),
        ]
