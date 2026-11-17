"""How the daily quotas count (ADR-0025 point 7): questions recorded since UTC midnight."""

from datetime import UTC, datetime

from django.db.models import QuerySet
from django.utils import timezone

from caipo.assistant.models import AIInteraction


def start_of_day() -> datetime:
    """Midnight, UTC, of the current day: when the quotas start again."""
    return timezone.now().astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def asked_today() -> QuerySet[AIInteraction]:
    """Every interaction recorded since the start of the current UTC day."""
    return AIInteraction.objects.filter(created_at__gte=start_of_day())
