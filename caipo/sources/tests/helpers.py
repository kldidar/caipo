"""What the source and policy tests share: a small synthetic world and the actors in it.

Countries: XA is in the ISO 3166-1 user-assigned range, so it takes only
demonstration records. OA is assigned to no country by ISO 3166-1 and is not
user-assigned, so the rule treats it as real and it takes only reference
records; its name says it is a test record. Languages and institutions use
the private-use codes of ISO 639-3 and ISO 15924.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from caipo.accounts.models import AuditEvent
from caipo.accounts.selectors import AuthenticationContext
from caipo.registry.models import Country, Language
from caipo.sources import services

UNKNOWN = uuid.UUID("00000000-0000-4000-8000-00000000ffff")
ACCESSED = date(2026, 1, 2)


@dataclass(frozen=True)
class World:
    demo_country: uuid.UUID
    reference_country: uuid.UUID
    language: uuid.UUID


def make_world() -> World:
    demo = Country.objects.create(alpha2="XA", alpha3="XAA", name_en="TEST Synthetic Country")
    reference = Country.objects.create(alpha2="OA", alpha3="OAA", name_en="TEST Reference Country")
    language = Language.objects.create(code="qaa", script_code="Qaaa", name_en="TEST Language")
    return World(demo.public_id, reference.public_id, language.public_id)


def source_values(
    world: World, data_class: str = "demonstration", /, **changes: Any
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "data_class": data_class,
        "name": "TEST Source",
        "publisher": "TEST Publisher",
        "url": "https://source.example/",
        "source_tier": "A",
        "permitted_use": "store",
        "accessed_on": ACCESSED,
        "country": world.demo_country if data_class == "demonstration" else world.reference_country,
    }
    values.update(changes)
    return values


def make_source(
    actor: AuthenticationContext, world: World, data_class: str = "demonstration"
) -> uuid.UUID:
    return services.create_source(actor=actor, **source_values(world, data_class))


def make_document(
    actor: AuthenticationContext,
    world: World,
    source: uuid.UUID,
    data_class: str = "demonstration",
    /,
    **changes: Any,
) -> uuid.UUID:
    values: dict[str, Any] = {
        "source": source,
        "country": world.demo_country if data_class == "demonstration" else world.reference_country,
        "document_type": "decree",
        "title": "TEST Decree on Artificial Intelligence",
        "title_language": world.language,
        "date_of_issue": date(2025, 1, 1),
    }
    values.update(changes)
    return services.create_document(actor=actor, **values)


def audit_events(target_type: str) -> list[tuple[str, uuid.UUID]]:
    return list(
        AuditEvent.objects.filter(target_type=target_type)
        .order_by("id")
        .values_list("action", "target_public_id")
    )
