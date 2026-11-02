"""The development-only command that creates the demonstration environment (ADR-0020 point 16)."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from caipo.accounts.models import AuditEvent, User
from caipo.core.data_class import is_synthetic_country
from caipo.demo.catalogue import load
from caipo.indicators.models import DatasetRelease, Indicator, Observation
from caipo.policies.models import Policy, PolicyProvision
from caipo.research.models import AnalysisRun, SearchRun
from caipo.sources.models import Document, Source

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
def test_a_random_password_is_shown_once_when_none_is_given() -> None:
    out = StringIO()
    call_command("seed_demo", stdout=out)

    assert "Password for both (shown once)" in out.getvalue()
