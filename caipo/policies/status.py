"""The formal status of a policy, derived from its events (DATA_MODEL.md §4.4). Never stored."""

from collections.abc import Iterable
from datetime import date

from django.db import models
from django.utils.translation import gettext_lazy as _

from caipo.policies.models import PolicyEventType


class FormalStatus(models.TextChoices):
    UNKNOWN = "unknown", _("No formal event recorded")
    ADOPTED_NOT_IN_FORCE = "adopted_not_in_force", _("Adopted, not in force")
    IN_FORCE = "in_force", _("In force")
    EXPIRED = "expired", _("Expired")
    REPEALED = "repealed", _("Repealed")


def derive_status(events: Iterable[tuple[str, date]], *, on: date | None = None) -> FormalStatus:
    """Return the formal status that events of (type, effective date) establish.

    Only events effective on or before `on` count, when it is given. A repeal
    or an expiry ends the policy; an entry into force makes it in force unless
    a later repeal or expiry follows; an adoption alone leaves it adopted and
    not in force; an amendment changes nothing. With no event, nothing is
    known, and that is said rather than guessed.
    """
    types = {event_type for event_type, event_date in events if on is None or event_date <= on}
    if PolicyEventType.REPEALED in types:
        return FormalStatus.REPEALED
    if PolicyEventType.EXPIRED in types:
        return FormalStatus.EXPIRED
    if PolicyEventType.ENTERED_INTO_FORCE in types:
        return FormalStatus.IN_FORCE
    if PolicyEventType.ADOPTED in types:
        return FormalStatus.ADOPTED_NOT_IN_FORCE
    return FormalStatus.UNKNOWN
