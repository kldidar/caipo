"""Write interface of the demonstrator's indicators (ADR-0020).

Each operation requires `RESEARCH_CONTRIBUTE` first, then validates, writes,
and records its audit event, in one transaction. A release is imported whole
or not at all. Values are stored exactly as given: missing values stay
missing and nothing is interpolated, rounded, or converted.
"""

import logging
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction

from caipo.accounts import selectors as accounts_selectors
from caipo.accounts import services as accounts_services
from caipo.accounts.selectors import AuditAction, AuditTargetType, AuthenticationContext, Permission
from caipo.core.data_class import country_fits
from caipo.core.entry import DataClassError, InvalidEntryError, RecordNotFoundError, clean_text
from caipo.indicators.models import (
    DatasetRelease,
    Indicator,
    Layer,
    Observation,
    ObservationStatus,
)
from caipo.registry import selectors as registry_selectors
from caipo.sources import selectors as sources_selectors

logger = logging.getLogger(__name__)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
# The largest magnitude the value column holds: 18 digits before the point.
_LIMIT = Decimal("1e18")
_DECIMALS = 18


class DuplicateReleaseError(InvalidEntryError):
    """A release with the same file hash has already been imported from this source."""


@dataclass(frozen=True)
class ObservationRow:
    """One value as a provider gives it. `value` is None exactly when the value is missing."""

    indicator_code: str
    country_alpha2: str
    year: int
    value: Decimal | None
    status: str
    footnote: str = ""


def _source(public_id: uuid.UUID) -> sources_selectors.SourceReference:
    source = sources_selectors.source_reference(public_id)
    if source is None:
        raise RecordNotFoundError("The source does not exist.")
    return source


def _record(
    actor: AuthenticationContext, target_type: AuditTargetType, public_id: uuid.UUID
) -> None:
    accounts_services.record_audit_event(
        actor=actor,
        action=AuditAction.CREATED,
        target_type=target_type,
        target_public_id=public_id,
        changes=(),
    )


def create_indicator(
    *,
    actor: AuthenticationContext,
    source: uuid.UUID,
    code: str,
    name: str,
    unit: str,
    layer: str,
    layer_reason: str,
    definition: str = "",
    original_provider: str = "",
) -> uuid.UUID:
    """Create an indicator of a provider in one layer, and return its public identifier.

    Preconditions: the actor holds `RESEARCH_CONTRIBUTE`; the source exists,
    and the indicator takes its data class; the layer is A, B, or C; the code,
    name, unit, and reason for the layer are not empty; the provider has no
    other indicator with this code.

    Side effects: one Indicator and one `created` audit event in one
    transaction, and a log line after it commits.

    Raises PermissionDenied before anything else is examined;
    RecordNotFoundError or InvalidEntryError. Nothing is stored in either case.
    """
    accounts_selectors.require_permission(actor, Permission.RESEARCH_CONTRIBUTE)
    if layer not in Layer.values:
        raise InvalidEntryError("The layer is A, B, or C.")
    provider = _source(source)
    clean_code = clean_text(code, field="code", max_length=64)
    try:
        with transaction.atomic():
            indicator = Indicator.objects.create(
                data_class=provider.data_class,
                source_id=provider.pk,
                code=clean_code,
                name=clean_text(name, field="name", max_length=300),
                definition=clean_text(
                    definition, field="definition", max_length=5000, required=False
                ),
                unit=clean_text(unit, field="unit", max_length=100),
                layer=layer,
                layer_reason=clean_text(
                    layer_reason, field="reason for the layer", max_length=5000
                ),
                original_provider=clean_text(
                    original_provider, field="original provider", max_length=500, required=False
                ),
            )
            _record(actor, AuditTargetType.INDICATOR, indicator.public_id)
    except IntegrityError as error:
        if "indicators_indicator_code_unique" in str(error):
            raise InvalidEntryError(
                "The provider already has an indicator with this code."
            ) from error
        raise
    logger.info(
        "Demonstrator record created",
        extra={
            "event": "indicators.indicator_created",
            "public_id": str(indicator.public_id),
            "actor_id": actor.user.pk,
        },
    )
    return indicator.public_id


def _value(row: ObservationRow) -> Decimal | None:
    if row.status not in ObservationStatus.values:
        raise InvalidEntryError(f"The status {row.status!r} is not one of those listed.")
    if (row.status == ObservationStatus.MISSING) != (row.value is None):
        raise InvalidEntryError(
            "A missing value holds nothing, and a value that is held is not missing."
        )
    if row.value is not None:
        exponent = row.value.as_tuple().exponent
        if (
            not row.value.is_finite()
            or abs(row.value) >= _LIMIT
            or not isinstance(exponent, int)
            or exponent < -_DECIMALS
        ):
            raise InvalidEntryError(
                "A value is a finite number of at most 18 digits before the point and 18 "
                "after it, so that it is stored exactly as given."
            )
    if not 1900 <= row.year <= 2100:
        raise InvalidEntryError("A year is between 1900 and 2100.")
    return row.value


def import_release(
    *,
    actor: AuthenticationContext,
    source: uuid.UUID,
    label: str,
    retrieved_on: date,
    file_name: str,
    sha256: str,
    rows: Sequence[ObservationRow],
) -> uuid.UUID:
    """Import one release of a provider's data, whole, and return its public identifier.

    Preconditions: the actor holds `RESEARCH_CONTRIBUTE`; the source exists,
    and the release takes its data class; the hash is 64 lower-case hex
    digits and no release of this source has it; every row names an
    indicator of this source by its code and a country that exists and fits
    the data class; each row's status is listed, a missing value holds
    nothing and a value that is held is not missing, the value is finite,
    and the year is between 1900 and 2100; no indicator, country, and year
    occurs twice.

    Side effects: one DatasetRelease and its Observations, which are
    append-only, and one `created` audit event for the release, in one
    transaction; a log line after it commits.

    Raises PermissionDenied before anything else is examined;
    RecordNotFoundError, DataClassError, InvalidEntryError, or
    DuplicateReleaseError (a kind of InvalidEntryError). Nothing is stored
    in any of those cases: a release with one bad row is refused entirely.
    """
    accounts_selectors.require_permission(actor, Permission.RESEARCH_CONTRIBUTE)
    provider = _source(source)
    if not _SHA256.match(sha256):
        raise InvalidEntryError("The hash is 64 lower-case hexadecimal digits.")
    indicators = dict(Indicator.objects.filter(source_id=provider.pk).values_list("code", "pk"))
    countries = {country.alpha2: country for country in registry_selectors.country_choices()}
    seen: set[tuple[str, str, int]] = set()
    prepared: list[Observation] = []
    for row in rows:
        key = (row.indicator_code, row.country_alpha2, row.year)
        if key in seen:
            raise InvalidEntryError(f"{key} occurs twice in the release.")
        seen.add(key)
        if row.indicator_code not in indicators:
            raise RecordNotFoundError(f"The source has no indicator {row.indicator_code!r}.")
        country = countries.get(row.country_alpha2)
        if country is None:
            raise RecordNotFoundError(f"No active country has the code {row.country_alpha2!r}.")
        if not country_fits(provider.data_class, country.alpha2):
            raise DataClassError(
                "Demonstration values belong only to synthetic countries, "
                "and reference values never do."
            )
        prepared.append(
            Observation(
                indicator_id=indicators[row.indicator_code],
                country_id=country.pk,
                year=row.year,
                value=_value(row),
                status=row.status,
                footnote=clean_text(row.footnote, field="footnote", max_length=500, required=False),
            )
        )
    try:
        with transaction.atomic():
            release = DatasetRelease.objects.create(
                data_class=provider.data_class,
                source_id=provider.pk,
                label=clean_text(label, field="release label", max_length=100),
                retrieved_on=retrieved_on,
                file_name=clean_text(file_name, field="file", max_length=300),
                sha256=sha256,
            )
            for observation in prepared:
                observation.release = release
            Observation.objects.bulk_create(prepared)
            _record(actor, AuditTargetType.DATASET_RELEASE, release.public_id)
    except IntegrityError as error:
        if "indicators_release_file_once" in str(error):
            raise DuplicateReleaseError("This file has already been imported.") from error
        raise
    logger.info(
        "Demonstrator record created",
        extra={
            "event": "indicators.release_imported",
            "public_id": str(release.public_id),
            "observations": len(prepared),
            "actor_id": actor.user.pk,
        },
    )
    return release.public_id
