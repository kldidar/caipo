"""The development-only command that creates the demonstration environment (ADR-0020 point 16)."""

import dataclasses
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from pytest import MonkeyPatch

from caipo.accounts.models import AuditEvent, User
from caipo.core.data_class import is_synthetic_country
from caipo.demo.catalogue import load
from caipo.indicators.models import DatasetRelease, Indicator, Observation
from caipo.policies.models import Policy, PolicyProvision
from caipo.research.models import AnalysisRun, SearchRun
from caipo.sources.models import Document, Segment, Source

pytestmark = pytest.mark.django_db


def test_it_refuses_to_run_without_debug() -> None:
    with override_settings(DEBUG=False), pytest.raises(CommandError):
        call_command("seed_demo", stdout=StringIO())
    assert not Source.objects.exists()
    assert not User.objects.exists()


@override_settings(DEBUG=True)
def test_it_creates_the_catalogue_through_the_services() -> None:
    out = StringIO()
    call_command("seed_demo", "--password", "TEST-password-for-demo", stdout=out)

    catalogue = load()
    assert Source.objects.count() == len(catalogue.sources)
    assert Document.objects.count() == len(catalogue.documents)
    assert Policy.objects.count() == len(catalogue.policies)
    assert AuditEvent.objects.filter(target_type="policies.policy").count() == len(
        catalogue.policies
    )
    assert Indicator.objects.count() == len(catalogue.indicators)
    assert DatasetRelease.objects.count() == 2
    assert Observation.objects.filter(release__data_class="demonstration").count() == len(
        catalogue.demo_observations
    )
    assert Observation.objects.filter(release__data_class="reference").count() == 240
    assert AnalysisRun.objects.count() == len(catalogue.analyses)
    assert (
        SearchRun.objects.filter(
            outcome="no_qualifying_source_found", data_class="reference"
        ).count()
        == 1
    )
    texts = Segment.objects.values_list("document__title", flat=True).distinct()
    titles = {spec.key: spec.title for spec in catalogue.documents}
    assert set(texts) == {titles[key] for key in catalogue.texts}
    assert Segment.objects.count() == sum(len(parts) for parts in catalogue.texts.values())
    assert AuditEvent.objects.filter(
        target_type="sources.document", action="updated", changes__field="text"
    ).count() == len(catalogue.texts)
    assert "demo.researcher@caipo.test" in out.getvalue()
    assert "TEST-password-for-demo" not in out.getvalue()
    researcher = User.objects.get(email="demo.researcher@caipo.test")
    assert researcher.check_password("TEST-password-for-demo")


@override_settings(DEBUG=True)
def test_the_two_data_classes_never_meet() -> None:
    call_command("seed_demo", "--password", "TEST-password-for-demo", stdout=StringIO())

    for indicator_class, alpha2 in Observation.objects.values_list(
        "indicator__data_class", "country__alpha2"
    ):
        assert is_synthetic_country(alpha2) == (indicator_class == "demonstration")
    for model in (Source, Document, Policy):
        for data_class, alpha2 in model.objects.exclude(country=None).values_list(
            "data_class", "country__alpha2"
        ):
            assert is_synthetic_country(alpha2) == (data_class == "demonstration")
    assert (
        not PolicyProvision.objects.filter(data_class="reference").exclude(quoted_text="").exists()
    )
    assert not Segment.objects.exclude(document__data_class="demonstration").exists()
    for title in Policy.objects.filter(data_class="demonstration").values_list("title", flat=True):
        assert title.startswith("DEMO")


@override_settings(DEBUG=True)
def test_running_it_again_changes_nothing() -> None:
    call_command("seed_demo", "--password", "TEST-password-for-demo", stdout=StringIO())
    before = (Source.objects.count(), Policy.objects.count(), AuditEvent.objects.count())

    out = StringIO()
    call_command("seed_demo", stdout=out)

    assert (Source.objects.count(), Policy.objects.count(), AuditEvent.objects.count()) == before
    assert "already present" in out.getvalue()


@override_settings(DEBUG=True)
def test_an_environment_seeded_before_the_texts_is_given_them_and_nothing_else(
    monkeypatch: MonkeyPatch,
) -> None:
    from caipo.demo.management.commands import seed_demo

    without_texts = dataclasses.replace(load(), texts={})
    monkeypatch.setattr(seed_demo, "load", lambda: without_texts)
    call_command("seed_demo", "--password", "TEST-password-for-demo", stdout=StringIO())
    before = (Source.objects.count(), Document.objects.count(), Policy.objects.count())
    events = AuditEvent.objects.count()
    assert not Segment.objects.exists()

    monkeypatch.setattr(seed_demo, "load", load)
    out = StringIO()
    call_command("seed_demo", stdout=out)

    texts = len(load().texts)
    assert f"Texts attached: {texts}." in out.getvalue()
    assert (Source.objects.count(), Document.objects.count(), Policy.objects.count()) == before
    assert AuditEvent.objects.count() == events + texts
    assert User.objects.get(email="demo.researcher@caipo.test").check_password(
        "TEST-password-for-demo"
    )


@override_settings(DEBUG=True)
def test_texts_are_not_attached_without_the_demonstration_researcher(
    monkeypatch: MonkeyPatch,
) -> None:
    from caipo.demo.management.commands import seed_demo

    monkeypatch.setattr(seed_demo, "load", lambda: dataclasses.replace(load(), texts={}))
    call_command("seed_demo", "--password", "TEST-password-for-demo", stdout=StringIO())
    monkeypatch.setattr(seed_demo, "load", load)
    monkeypatch.setattr(seed_demo, "RESEARCHER_EMAIL", "nobody@caipo.test")

    with pytest.raises(CommandError, match="Researcher account is missing"):
        call_command("seed_demo", stdout=StringIO())

    assert not Segment.objects.exists()


@override_settings(DEBUG=True)
def test_a_random_password_is_shown_once_when_none_is_given() -> None:
    out = StringIO()
    call_command("seed_demo", stdout=out)

    assert "Password for both (shown once)" in out.getvalue()


def test_only_demonstration_documents_are_given_a_text() -> None:
    catalogue = load()
    demonstration = {
        spec.key
        for spec in catalogue.documents
        if is_synthetic_country(spec.country) and spec.title.startswith("DEMO")
    }

    assert catalogue.texts
    assert set(catalogue.texts) <= demonstration
    for parts in catalogue.texts.values():
        locators = [locator for locator, _ in parts]
        assert len(locators) == len(set(locators))
        assert all(text.strip() for _, text in parts)


def test_every_quoted_provision_is_in_its_document_text_under_its_locator() -> None:
    """A provision's quotation and its locator agree with the document it quotes."""
    catalogue = load()
    quoted = [
        provision
        for policy in catalogue.policies
        if policy.data_class == "demonstration"
        for provision in policy.provisions
        if provision.quoted_text
    ]

    assert quoted
    for provision in quoted:
        parts = dict(catalogue.texts[provision.document])
        assert provision.quoted_text in parts[provision.locator], provision.locator


def test_every_located_event_names_a_part_of_its_document_text() -> None:
    catalogue = load()
    located = [
        (document, locator)
        for policy in catalogue.policies
        if policy.data_class == "demonstration"
        for _, _, document, locator in policy.events
        if locator
    ]

    assert located
    for document, locator in located:
        assert locator in dict(catalogue.texts[document]), (document, locator)
