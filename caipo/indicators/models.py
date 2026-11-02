"""Indicators, dataset releases, and observations: the demonstrator form (ADR-0020).

An Indicator is one measured concept from one provider (a Source), assigned
to exactly one layer of economic transformation (RESEARCH_PROTOCOL.md §3.2)
with a recorded reason. The assignment is provisional: the selection of
indicators is blocker B12, still open.

A DatasetRelease is one import of a provider's file, identified by the
SHA-256 of what was obtained. An Observation is one value of an indicator for
one country and one year, in one release. Missing values stay missing: an
observation whose status is `missing` holds no value, and no value is ever
filled in. Releases and observations are append-only; a revised value
arrives in a later release.
"""

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from caipo.core.append_only import AppendOnlyModel, AppendOnlyQuerySet
from caipo.core.data_class import DataClass


class Layer(models.TextChoices):
    """The three layers, which are never combined into one index (protocol §3.2)."""

    STRUCTURAL = "A", _("A. Structural economic change")
    DIGITAL = "B", _("B. Digital transformation")
    AI_SPECIFIC = "C", _("C. AI-specific outcomes")


class ObservationStatus(models.TextChoices):
    REPORTED = "reported", _("Reported")
    ESTIMATED = "estimated", _("Estimated")
    PROVISIONAL = "provisional", _("Provisional")
    PROJECTED = "projected", _("Projected")
    MISSING = "missing", _("Missing")


class Indicator(models.Model):
    """A measured concept from one provider, in one layer, with the reason for the layer."""

    public_id = models.UUIDField(_("public identifier"), default=uuid.uuid4, editable=False)
    data_class = models.CharField(_("data class"), max_length=16, choices=DataClass)
    source = models.ForeignKey(
        "sources.Source", on_delete=models.PROTECT, related_name="+", verbose_name=_("provider")
    )
    code = models.CharField(_("provider's code"), max_length=64)
    name = models.CharField(_("name"), max_length=300)
    definition = models.TextField(_("definition"), blank=True)
    unit = models.CharField(_("unit"), max_length=100)
    layer = models.CharField(_("layer"), max_length=1, choices=Layer)
    layer_reason = models.TextField(_("reason for the layer"))
    original_provider = models.CharField(_("original provider"), max_length=500, blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("indicator")
        verbose_name_plural = _("indicators")
        constraints = [
            models.UniqueConstraint(
                fields=["public_id"], name="indicators_indicator_public_id_unique"
            ),
            models.UniqueConstraint(
                fields=["source", "code"], name="indicators_indicator_code_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(data_class__in=DataClass.values),
                name="indicators_indicator_data_class_known",
            ),
            models.CheckConstraint(
                condition=models.Q(layer__in=Layer.values),
                name="indicators_indicator_layer_known",
            ),
            models.CheckConstraint(
                condition=~models.Q(code="")
                & ~models.Q(name="")
                & ~models.Q(unit="")
                & ~models.Q(layer_reason=""),
                name="indicators_indicator_described",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class DatasetRelease(AppendOnlyModel):
    """One import of a provider's data, identified by the hash of what was obtained. Append-only."""

    public_id = models.UUIDField(_("public identifier"), default=uuid.uuid4, editable=False)
    data_class = models.CharField(_("data class"), max_length=16, choices=DataClass)
    source = models.ForeignKey(
        "sources.Source", on_delete=models.PROTECT, related_name="+", verbose_name=_("provider")
    )
    label = models.CharField(_("provider's release label"), max_length=100)
    retrieved_on = models.DateField(_("retrieved on"))
    file_name = models.CharField(_("file"), max_length=300)
    sha256 = models.CharField(_("SHA-256"), max_length=64)
    created_at = models.DateTimeField(_("imported at"), auto_now_add=True)

    objects = AppendOnlyQuerySet["DatasetRelease"].as_manager()

    class Meta:
        verbose_name = _("dataset release")
        verbose_name_plural = _("dataset releases")
        constraints = [
            models.UniqueConstraint(
                fields=["public_id"], name="indicators_release_public_id_unique"
            ),
            models.UniqueConstraint(
                fields=["source", "sha256"], name="indicators_release_file_once"
            ),
            models.CheckConstraint(
                condition=models.Q(data_class__in=DataClass.values),
                name="indicators_release_data_class_known",
            ),
            models.CheckConstraint(
                condition=models.Q(sha256__regex=r"^[0-9a-f]{64}$"),
                name="indicators_release_sha256_form",
            ),
        ]


class Observation(AppendOnlyModel):
    """One value of an indicator for a country and a year, in one release. Append-only."""

    indicator = models.ForeignKey(
        Indicator,
        on_delete=models.PROTECT,
        related_name="observations",
        verbose_name=_("indicator"),
    )
    country = models.ForeignKey(
        "registry.Country", on_delete=models.PROTECT, related_name="+", verbose_name=_("country")
    )
    release = models.ForeignKey(
        DatasetRelease,
        on_delete=models.PROTECT,
        related_name="observations",
        verbose_name=_("release"),
    )
    year = models.PositiveSmallIntegerField(_("year"))
    # Wide enough to hold any value as published: 20 digits before the point
    # and 18 after. The service refuses a value that would need rounding.
    value = models.DecimalField(_("value"), max_digits=38, decimal_places=18, null=True, blank=True)
    status = models.CharField(_("status"), max_length=16, choices=ObservationStatus)
    footnote = models.CharField(_("provider's footnote"), max_length=500, blank=True)

    objects = AppendOnlyQuerySet["Observation"].as_manager()

    class Meta:
        verbose_name = _("observation")
        verbose_name_plural = _("observations")
        constraints = [
            models.UniqueConstraint(
                fields=["indicator", "country", "year", "release"],
                name="indicators_observation_once_per_release",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=ObservationStatus.values),
                name="indicators_observation_status_known",
            ),
            models.CheckConstraint(
                condition=models.Q(year__gte=1900, year__lte=2100),
                name="indicators_observation_year_range",
            ),
            # A missing value holds nothing, and a value that is held is not missing.
            models.CheckConstraint(
                condition=(
                    models.Q(status=ObservationStatus.MISSING, value__isnull=True)
                    | (~models.Q(status=ObservationStatus.MISSING) & models.Q(value__isnull=False))
                ),
                name="indicators_observation_missing_holds_nothing",
            ),
        ]
