"""The page on which an Administrator reads the audit record (ADR-0018)."""

import uuid

import pytest
from django.db import transaction
from django.test import Client

from caipo.accounts.models import AuditEvent
from caipo.accounts.selectors import AuditAction, AuditField, AuditTargetType, Permission, Role
from caipo.accounts.services import AuditChange, record_audit_event
from caipo.accounts.tests.fixtures import UserFactory, enrolled_device
from caipo.accounts.tests.fixtures import signed_in as signed_in_context
from caipo.web import audit
from caipo.web.access import declared_access
from caipo.web.tests.helpers import signed_in, verified

pytestmark = pytest.mark.django_db

AUDIT = "/administration/audit/"
TARGET = uuid.UUID("00000000-0000-4000-8000-000000000001")
OTHER = uuid.UUID("00000000-0000-4000-8000-000000000002")


@pytest.fixture
def changes(user_with_roles: UserFactory) -> None:
    writer = signed_in_context(user_with_roles(Role.RESEARCHER))
    with transaction.atomic():
        record_audit_event(
            actor=writer,
            action=AuditAction.UPDATED,
            target_type=AuditTargetType.INSTITUTION,
            target_public_id=TARGET,
            changes=[AuditChange(AuditField.NAME_EN, "TEST <b>old</b>", "TEST new & better")],
        )
    with transaction.atomic():
        record_audit_event(
            actor=writer,
            action=AuditAction.CREATED,
            target_type=AuditTargetType.POLICY,
            target_public_id=OTHER,
            changes=[],
        )


@pytest.fixture
def administrator(user_with_roles: UserFactory) -> Client:
    return verified(Client(), user_with_roles(Role.ADMINISTRATOR))


def _visitor(kind: str, user_with_roles: UserFactory) -> Client:
    if kind == "anonymous":
        return Client()
    if kind == "administrator-on-a-password":
        user = user_with_roles(Role.ADMINISTRATOR)
        enrolled_device(user)
        return signed_in(Client(), user)
    return verified(Client(), user_with_roles(Role(kind)))


@pytest.mark.parametrize(
    "kind", ["anonymous", "administrator-on-a-password", "reviewer", "researcher", "reader"]
)
def test_only_a_verified_administrator_reaches_the_record(
    changes: None, user_with_roles: UserFactory, kind: str
) -> None:
    response = _visitor(kind, user_with_roles).get(AUDIT)

    assert response.status_code == 403
    assert str(TARGET) not in response.content.decode()


def test_the_page_declares_the_permission_its_selector_requires() -> None:
    assert declared_access(audit.record) == Permission.AUDIT_READ


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_the_page_only_reads(changes: None, administrator: Client, method: str) -> None:
    events = AuditEvent.objects.count()

    assert getattr(administrator, method)(AUDIT).status_code == 405
    assert AuditEvent.objects.count() == events


def test_the_page_shows_each_change_with_its_fields_as_text(
    changes: None, administrator: Client
) -> None:
    page = administrator.get(AUDIT).content.decode()

    assert page.index(str(OTHER)) < page.index(str(TARGET))
    assert "Institution" in page and "Policy" in page
    assert "English name" in page
    assert "TEST &lt;b&gt;old&lt;/b&gt;" in page
    assert "TEST new &amp; better" in page
    assert "<b>old</b>" not in page
    assert "No field recorded" in page


def test_the_page_is_narrowed_to_one_kind(changes: None, administrator: Client) -> None:
    page = administrator.get(f"{AUDIT}?kind=policies.policy").content.decode()

    assert str(OTHER) in page
    assert str(TARGET) not in page
    assert '<option value="policies.policy" selected>' in page


def test_an_unknown_kind_or_page_shows_the_whole_record(
    changes: None, administrator: Client
) -> None:
    page = administrator.get(f"{AUDIT}?kind=<script>&page=abc").content.decode()

    assert str(OTHER) in page and str(TARGET) in page
    assert "<script>" not in page.split("<main", 1)[1]


def test_the_navigation_offers_the_record_to_a_verified_administrator_only(
    administrator: Client, user_with_roles: UserFactory
) -> None:
    assert f'href="{AUDIT}"' in administrator.get("/login/").content.decode()
    reader = verified(Client(), user_with_roles(Role.READER))
    assert f'href="{AUDIT}"' not in reader.get("/login/").content.decode()
