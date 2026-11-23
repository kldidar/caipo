"""The page about CAIPO and the page of guarantees, for a reader from outside (Days 44 and 45)."""

import ast
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings
from django.test import Client

from caipo.accounts.selectors import Role
from caipo.accounts.tests.fixtures import UserFactory
from caipo.web import about
from caipo.web.guarantees import GROUPS
from caipo.web.tests.helpers import signed_in

pytestmark = pytest.mark.django_db

REPOSITORY = Path(__file__).resolve().parents[3]


def _text(response: Any) -> str:
    return str(response.content.decode())


def _defined(path: str) -> set[str]:
    tree = ast.parse((REPOSITORY / path).read_text(encoding="utf-8"))
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}


@pytest.mark.parametrize("url", ["/about/", "/guarantees/"])
def test_both_pages_are_public_and_open_to_an_account(
    client: Client, user_with_roles: UserFactory, url: str
) -> None:
    assert client.get(url).status_code == 200
    assert signed_in(Client(), user_with_roles(Role.READER)).get(url).status_code == 200


def test_the_about_page_says_what_is_real_what_is_synthetic_and_who_wrote_it(
    client: Client,
) -> None:
    page = _text(client.get("/about/"))

    assert "No text of a real legal document is held" in page
    assert "DEMO Northland and DEMO Southland" in page
    assert "written by an AI coding agent, Claude Code" in page
    assert "no person has yet checked their answers" in page
    assert 'href="/guarantees/"' in page
    report = f"{settings.SOURCE_REPOSITORY_URL}/blob/main/{about.EVALUATION_REPORT}"
    assert f'href="{report}"' in page
    assert (REPOSITORY / about.EVALUATION_REPORT).is_file()


def test_every_test_a_guarantee_names_exists() -> None:
    named = [
        test for group in GROUPS for guarantee in group.guarantees for test in guarantee.proofs
    ]

    assert named
    for test in named:
        path, name = test.split("::")
        assert name in _defined(path), test


def test_every_guarantee_names_at_least_one_test_and_none_twice() -> None:
    for group in GROUPS:
        for guarantee in group.guarantees:
            assert guarantee.proofs
            assert len(set(guarantee.proofs)) == len(guarantee.proofs)


def test_the_guarantees_page_links_each_test_to_its_source(client: Client) -> None:
    page = _text(client.get("/guarantees/"))

    for group in GROUPS:
        assert str(group.title) in page
        for guarantee in group.guarantees:
            for test in guarantee.proofs:
                path = test.split("::")[0]
                assert f'href="{settings.SOURCE_REPOSITORY_URL}/blob/main/{path}"' in page
    assert "What is not guaranteed" in page
    assert "Records of provenance are never changed or deleted" in page
    assert "The database refuses update and delete of an event sent as sql" in page


@pytest.mark.parametrize("url", ["/", "/help/", "/login/"])
def test_the_footer_links_the_about_guarantees_and_help_pages(client: Client, url: str) -> None:
    page = _text(client.get(url))

    for link in ('href="/about/"', 'href="/guarantees/"', 'href="/help/"'):
        assert link in page


def test_the_public_home_page_leads_to_the_about_page(client: Client) -> None:
    page = _text(client.get("/"))

    assert '<a class="button button--secondary" href="/about/">About CAIPO</a>' in page
