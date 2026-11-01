"""The services of the demonstrator's policies (ADR-0020)."""

import uuid
from datetime import date
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection, transaction

from caipo.accounts.models import AuditEvent, AuditEventChange
from caipo.accounts.selectors import AuthenticationContext
from caipo.core.append_only import AppendOnlyError
from caipo.core.entry import DataClassError, InvalidEntryError, RecordNotFoundError
from caipo.policies import selectors, services
from caipo.policies.models import Policy, PolicyEvent, PolicyProvision
from caipo.policies.services import DuplicateLinkError
from caipo.policies.status import FormalStatus
from caipo.sources.tests.helpers import UNKNOWN, World, audit_events, make_document, make_source

pytestmark = pytest.mark.django_db


def _policy(
    actor: AuthenticationContext, world: World, data_class: str = "demonstration", /, **changes: Any
) -> uuid.UUID:
    values: dict[str, Any] = {
        "data_class": data_class,
        "country": world.demo_country if data_class == "demonstration" else world.reference_country,
        "policy_type": "strategy",
        "title": "TEST Strategy for Artificial Intelligence",
        "title_language": world.language,
        "corpus_assignment": "core",
        "ai_focus": "ai_focused",
        "assignment_reason": "TEST reason",
    }
    values.update(changes)
    return services.create_policy(actor=actor, **values)


def _linked(
    actor: AuthenticationContext,
    world: World,
    data_class: str = "demonstration",
    role: str = "enacting_text",
) -> tuple[uuid.UUID, uuid.UUID]:
    policy = _policy(actor, world, data_class)
    document = make_document(actor, world, make_source(actor, world, data_class), data_class)
    services.link_document(actor=actor, policy=policy, document=document, role=role)
    return policy, document


# --- Creating a policy ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("corpus", "focus", "category"),
    [("core", "ai_focused", ""), ("core", "ai_provisions", ""), ("contextual", "", "education")],
)
def test_a_researcher_creates_a_policy_with_its_assignment(
    researcher: AuthenticationContext, world: World, corpus: str, focus: str, category: str
) -> None:
    public_id = _policy(
        researcher, world, corpus_assignment=corpus, ai_focus=focus, contextual_category=category
    )

    policy = Policy.objects.get(public_id=public_id)
    assert (policy.corpus_assignment, policy.ai_focus, policy.contextual_category) == (
        corpus,
        focus,
        category,
    )
    assert audit_events("policies.policy") == [("created", public_id)]


@pytest.mark.parametrize(
    "changes",
    [
        {"corpus_assignment": "core", "ai_focus": ""},
        {"corpus_assignment": "core", "contextual_category": "education"},
        {
            "corpus_assignment": "contextual",
            "ai_focus": "ai_focused",
            "contextual_category": "education",
        },
        {"corpus_assignment": "contextual", "ai_focus": "", "contextual_category": ""},
        {"corpus_assignment": "both"},
        {"assignment_reason": "  "},
        {"title": ""},
        {"policy_type": "wish"},
    ],
)
def test_an_inconsistent_policy_is_refused(
    researcher: AuthenticationContext, world: World, changes: dict[str, object]
) -> None:
    with pytest.raises(InvalidEntryError):
        _policy(researcher, world, **changes)
    assert not Policy.objects.exists()


def test_a_demonstration_policy_cannot_belong_to_a_real_country(
    researcher: AuthenticationContext, world: World
) -> None:
    with pytest.raises(DataClassError):
        _policy(researcher, world, country=world.reference_country)


def test_a_reference_policy_cannot_belong_to_a_synthetic_country(
    researcher: AuthenticationContext, world: World
) -> None:
    with pytest.raises(DataClassError):
        _policy(researcher, world, "reference", country=world.demo_country)


@pytest.mark.parametrize("field", ["country", "title_language", "lead_institution"])
def test_a_policy_naming_an_unknown_record_is_refused(
    researcher: AuthenticationContext, world: World, field: str
) -> None:
    with pytest.raises(RecordNotFoundError):
        _policy(researcher, world, **{field: UNKNOWN})


def test_a_reader_may_not_create_a_policy(reader: AuthenticationContext, world: World) -> None:
    with pytest.raises(PermissionDenied):
        _policy(reader, world)


# --- Documents -----------------------------------------------------------------------------------


def test_a_document_is_linked_once_in_each_role(
    researcher: AuthenticationContext, world: World
) -> None:
    policy, document = _linked(researcher, world)

    with pytest.raises(DuplicateLinkError):
        services.link_document(
            actor=researcher, policy=policy, document=document, role="enacting_text"
        )
    services.link_document(
        actor=researcher, policy=policy, document=document, role="official_report"
    )

    assert len(audit_events("policies.policy_document_link")) == 2


def test_documents_of_the_other_data_class_are_never_linked(
    researcher: AuthenticationContext, world: World
) -> None:
    policy = _policy(researcher, world)
    reference_document = make_document(
        researcher, world, make_source(researcher, world, "reference"), "reference"
    )

    with pytest.raises(DataClassError):
        services.link_document(
            actor=researcher, policy=policy, document=reference_document, role="enacting_text"
        )


# --- Formal events -------------------------------------------------------------------------------


def test_events_derive_the_status_and_are_recorded(
    researcher: AuthenticationContext, world: World
) -> None:
    policy, document = _linked(researcher, world)

    services.record_event(
        actor=researcher,
        policy=policy,
        event_type="adopted",
        effective_date=date(2025, 1, 1),
        document=document,
    )
    adopted = selectors.policy_detail(researcher, policy)
    assert adopted is not None
    assert adopted.policy.status is FormalStatus.ADOPTED_NOT_IN_FORCE
    services.record_event(
        actor=researcher,
        policy=policy,
        event_type="entered_into_force",
        effective_date=date(2025, 2, 1),
        document=document,
        locator="Art. 9",
    )

    detail = selectors.policy_detail(researcher, policy)
    assert detail is not None
    assert detail.policy.status is FormalStatus.IN_FORCE
    assert [event.event_type for event in detail.events] == ["adopted", "entered_into_force"]
    assert len(audit_events("policies.policy_event")) == 2


def test_an_event_needs_a_formal_document_of_the_policy(
    researcher: AuthenticationContext, world: World
) -> None:
    policy, document = _linked(researcher, world, role="commentary")
    unlinked = make_document(researcher, world, make_source(researcher, world))

    for candidate in (document, unlinked):
        with pytest.raises(InvalidEntryError):
            services.record_event(
                actor=researcher,
                policy=policy,
                event_type="adopted",
                effective_date=date(2025, 1, 1),
                document=candidate,
            )
    assert not PolicyEvent.objects.exists()


def test_implementation_is_not_a_formal_event(
    researcher: AuthenticationContext, world: World
) -> None:
    policy, document = _linked(researcher, world)

    with pytest.raises(InvalidEntryError):
        services.record_event(
            actor=researcher,
            policy=policy,
            event_type="implemented",
            effective_date=date(2025, 1, 1),
            document=document,
        )


def test_adoption_is_recorded_once(researcher: AuthenticationContext, world: World) -> None:
    policy, document = _linked(researcher, world)
    services.record_event(
        actor=researcher,
        policy=policy,
        event_type="adopted",
        effective_date=date(2025, 1, 1),
        document=document,
    )

    with pytest.raises(InvalidEntryError):
        services.record_event(
            actor=researcher,
            policy=policy,
            event_type="adopted",
            effective_date=date(2025, 3, 1),
            document=document,
        )


def test_an_event_is_never_changed_or_deleted(
    researcher: AuthenticationContext, world: World
) -> None:
    policy, document = _linked(researcher, world)
    services.record_event(
        actor=researcher,
        policy=policy,
        event_type="adopted",
        effective_date=date(2025, 1, 1),
        document=document,
    )
    event = PolicyEvent.objects.get()

    with pytest.raises(AppendOnlyError):
        event.save()
    with pytest.raises(AppendOnlyError):
        PolicyEvent.objects.update(locator="x")
    for statement in (
        "UPDATE policies_policyevent SET locator = 'x'",
        "DELETE FROM policies_policyevent",
    ):
        with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(statement)


# --- Provisions ----------------------------------------------------------------------------------


def test_a_demonstration_provision_may_quote_its_synthetic_text(
    researcher: AuthenticationContext, world: World
) -> None:
    policy, document = _linked(researcher, world)

    public_id = services.add_provision(
        actor=researcher,
        policy=policy,
        provision_type="objective",
        document=document,
        locator="Art. 4",
        label="TEST target",
        quoted_text="TEST synthetic text.",
    )

    provision = PolicyProvision.objects.get(public_id=public_id)
    assert (provision.data_class, provision.quoted_text) == (
        "demonstration",
        "TEST synthetic text.",
    )


def test_a_reference_provision_is_described_and_never_quoted(
    researcher: AuthenticationContext, world: World
) -> None:
    policy, document = _linked(researcher, world, "reference")
    values: dict[str, Any] = {
        "actor": researcher,
        "policy": policy,
        "provision_type": "objective",
        "document": document,
        "locator": "Art. 4",
        "label": "TEST target",
    }

    with pytest.raises(DataClassError):
        services.add_provision(**values, quoted_text="Text of a real document.")
    services.add_provision(**values)

    assert PolicyProvision.objects.get().quoted_text == ""


def test_the_database_refuses_quoted_text_on_a_reference_provision(
    researcher: AuthenticationContext, world: World
) -> None:
    policy, document = _linked(researcher, world, "reference")
    services.add_provision(
        actor=researcher,
        policy=policy,
        provision_type="objective",
        document=document,
        locator="Art. 4",
        label="TEST target",
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        PolicyProvision.objects.filter(data_class="reference").update(quoted_text="smuggled")


def test_contextual_material_is_not_coded(researcher: AuthenticationContext, world: World) -> None:
    policy = _policy(
        researcher,
        world,
        corpus_assignment="contextual",
        ai_focus="",
        contextual_category="education",
    )
    document = make_document(researcher, world, make_source(researcher, world))
    services.link_document(actor=researcher, policy=policy, document=document, role="enacting_text")

    with pytest.raises(InvalidEntryError):
        services.add_provision(
            actor=researcher,
            policy=policy,
            provision_type="objective",
            document=document,
            locator="Art. 1",
            label="TEST",
        )


def test_a_provision_is_located_in_a_document_of_the_policy(
    researcher: AuthenticationContext, world: World
) -> None:
    policy = _policy(researcher, world)
    unlinked = make_document(researcher, world, make_source(researcher, world))

    with pytest.raises(InvalidEntryError):
        services.add_provision(
            actor=researcher,
            policy=policy,
            provision_type="objective",
            document=unlinked,
            locator="Art. 1",
            label="TEST",
        )


# --- Reassignment --------------------------------------------------------------------------------


def test_reassignment_records_each_part_that_changed(
    researcher: AuthenticationContext, world: World
) -> None:
    policy = _policy(researcher, world)

    services.reassign_policy(
        actor=researcher,
        policy=policy,
        corpus_assignment="contextual",
        contextual_category="digital_economy",
        assignment_reason="TEST new reason",
    )

    event = AuditEvent.objects.get(target_type="policies.policy", action="updated")
    changes = set(
        AuditEventChange.objects.filter(event=event).values_list("field", "old_value", "new_value")
    )
    assert changes == {
        ("corpus_assignment", "core", "contextual"),
        ("ai_focus", "ai_focused", ""),
        ("contextual_category", "", "digital_economy"),
    }
    assert Policy.objects.get(public_id=policy).assignment_reason == "TEST new reason"


def test_a_reassignment_that_changes_nothing_is_refused(
    researcher: AuthenticationContext, world: World
) -> None:
    policy = _policy(researcher, world)

    with pytest.raises(InvalidEntryError):
        services.reassign_policy(
            actor=researcher,
            policy=policy,
            corpus_assignment="core",
            ai_focus="ai_focused",
            assignment_reason="TEST",
        )


def test_a_coded_policy_stays_in_the_core_corpus(
    researcher: AuthenticationContext, world: World
) -> None:
    policy, document = _linked(researcher, world)
    services.add_provision(
        actor=researcher,
        policy=policy,
        provision_type="objective",
        document=document,
        locator="Art. 1",
        label="TEST",
    )

    with pytest.raises(InvalidEntryError):
        services.reassign_policy(
            actor=researcher,
            policy=policy,
            corpus_assignment="contextual",
            contextual_category="education",
            assignment_reason="TEST",
        )


def test_nothing_is_deleted(researcher: AuthenticationContext, world: World) -> None:
    _linked(researcher, world)

    for table in ("policies_policydocumentlink", "policies_policy"):
        with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed table names


# --- Reading -------------------------------------------------------------------------------------


def test_the_two_corpora_are_listed_apart(
    researcher: AuthenticationContext, reader: AuthenticationContext, world: World
) -> None:
    core = _policy(researcher, world)
    contextual = _policy(
        researcher,
        world,
        corpus_assignment="contextual",
        ai_focus="",
        contextual_category="education",
    )

    assert [entry.public_id for entry in selectors.policies(reader, corpus_assignment="core")] == [
        core
    ]
    assert [
        entry.public_id for entry in selectors.policies(reader, corpus_assignment="contextual")
    ] == [contextual]
    coverage = selectors.coverage(reader)
    assert [(row.alpha2, row.core, row.contextual) for row in coverage] == [("XA", 1, 1)]
