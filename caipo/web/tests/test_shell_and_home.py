"""The application shell (navigation, assets) and the home page."""

import re
from pathlib import Path
from typing import Any

import pytest
from django.contrib.staticfiles import finders
from django.test import Client

from caipo.accounts.models import User
from caipo.accounts.selectors import Role
from caipo.accounts.tests.fixtures import UserFactory
from caipo.registry.models import Country, Language
from caipo.web.tests.helpers import signed_in, verified

HOME = "/"
REGISTRY = "/registry/"

pytestmark = pytest.mark.django_db


def _text(response: Any) -> str:
    return str(response.content.decode())


def _navigation(page: str) -> str:
    match = re.search(r'<nav id="primary-nav".*?</nav>', page, re.S)
    return match.group(0) if match else ""


def _nav_links(page: str) -> set[str]:
    return set(re.findall(r'<a [^>]*href="([^"]+)"', _navigation(page)))


# --- Home page ---------------------------------------------------------------------------------


def test_an_anonymous_visitor_is_told_what_caipo_is_and_shown_no_record(client: Client) -> None:
    Country.objects.create(alpha2="XA", alpha3="XAA", name_en="TEST Country")

    response = client.get(HOME)

    page = _text(response)
    assert response.status_code == 200
    assert "no-store" in response["Cache-Control"] or "max-age=0" in response["Cache-Control"]
    assert "Evidence on AI policy and economic transformation in Central Asia" in page
    assert 'href="/login/"' in page
    assert "TEST Country" not in page
    assert "Overview" not in page
    assert _navigation(page) == ""


def test_the_home_page_only_reads(client: Client) -> None:
    assert client.post(HOME).status_code == 405
    assert client.head(HOME).status_code == 200


@pytest.mark.parametrize("role", [Role.READER, Role.RESEARCHER])
def test_a_signed_in_reader_of_the_registry_is_shown_its_counts(
    client: Client, user_with_roles: UserFactory, role: Role
) -> None:
    Country.objects.create(alpha2="XA", alpha3="XAA", name_en="TEST Country A")
    Country.objects.create(alpha2="XB", alpha3="XBB", name_en="TEST Country B")
    Language.objects.create(code="qaa", script_code="Qaaa", name_en="TEST Language")

    page = _text(signed_in(client, user_with_roles(role)).get(HOME))

    assert "<h1>Overview</h1>" in page
    counts = re.findall(r'<span class="stat__value">(\d+)</span>', page)
    assert counts == ["2", "1", "0", "0"]
    assert 'href="/registry/"' in page


def test_an_account_that_may_not_read_the_registry_is_shown_no_count(
    client: Client, user_with_roles: UserFactory
) -> None:
    # An Administrator on a password alone holds only what enrolling a second
    # factor needs.
    page = _text(signed_in(client, user_with_roles(Role.ADMINISTRATOR)).get(HOME))

    assert "<h1>Overview</h1>" in page
    assert "stat__value" not in page
    assert 'href="/registry/"' not in page
    assert 'href="/administration/accounts/"' not in page


def test_a_verified_administrator_is_offered_account_administration(
    client: Client, user_with_roles: UserFactory
) -> None:
    page = _text(verified(client, user_with_roles(Role.ADMINISTRATOR)).get(HOME))

    assert 'href="/administration/accounts/"' in page
    assert 'href="/registry/entry/"' in page


# --- Navigation ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (Role.READER, {"/", "/registry/", "/account/second-factor/", "/login/"}),
        (Role.RESEARCHER, {"/", "/registry/", "/account/second-factor/", "/login/"}),
    ],
)
def test_the_navigation_offers_exactly_the_pages_a_role_may_open(
    client: Client, user_with_roles: UserFactory, role: Role, expected: set[str]
) -> None:
    page = _text(signed_in(client, user_with_roles(role)).get(HOME))

    assert _nav_links(page) == expected


def test_a_verified_administrator_sees_the_administration_pages(
    client: Client, user_with_roles: UserFactory
) -> None:
    page = _text(verified(client, user_with_roles(Role.ADMINISTRATOR)).get(HOME))

    assert _nav_links(page) == {
        "/",
        "/registry/",
        "/administration/accounts/",
        "/administration/second-factor-requests/",
        "/administration/recovery-requests/",
        "/administration/recoveries/",
        "/account/second-factor/",
        "/login/",
    }


def test_every_page_the_navigation_offers_opens_for_that_account(
    user_with_roles: UserFactory,
) -> None:
    user: User = user_with_roles(Role.ADMINISTRATOR, Role.RESEARCHER)
    page = _text(verified(Client(), user).get(HOME))

    for link in _nav_links(page):
        # A fresh client per page: one that opened another page is unchanged.
        assert verified(Client(), user).get(link).status_code == 200, link


def test_the_current_section_is_marked(client: Client, user_with_roles: UserFactory) -> None:
    signed_in(client, user_with_roles(Role.RESEARCHER))

    on_registry = _navigation(_text(client.get(REGISTRY)))
    on_entry = _navigation(_text(client.get("/registry/entry/")))

    assert re.findall(r'href="([^"]+)" aria-current="page"', on_registry) == ["/registry/"]
    assert re.findall(r'href="([^"]+)" aria-current="page"', on_entry) == ["/registry/"]


def test_the_navigation_shows_no_email_address(
    client: Client, user_with_roles: UserFactory
) -> None:
    user = user_with_roles(Role.READER)

    page = _text(signed_in(client, user).get(HOME))

    assert user.email not in page


def test_a_page_about_signing_in_carries_no_navigation_even_when_signed_in(
    client: Client, user_with_roles: UserFactory
) -> None:
    signed_in(client, user_with_roles(Role.READER))

    for url in ("/password-reset/", "/activate/", "/password-reset/confirm/"):
        page = _text(client.get(url))
        assert _navigation(page) == "", url
        assert "navigation.js" not in page, url


def test_the_navigation_script_is_loaded_only_with_the_navigation(
    client: Client, user_with_roles: UserFactory
) -> None:
    assert "navigation.js" not in _text(client.get(HOME))
    assert "navigation.js" in _text(signed_in(client, user_with_roles(Role.READER)).get(HOME))


# --- Assets --------------------------------------------------------------------------------------


def _static(path: str) -> Path:
    found = finders.find(path)
    assert found is not None, path
    return Path(str(found))


def test_no_page_asset_is_fetched_from_another_site(client: Client) -> None:
    page = _text(client.get(HOME))
    stylesheet = _static("web/caipo.css").read_text()

    assert not re.search(r'(src|href)="(https?:)?//', page)
    for url in re.findall(r"url\(([^)]+)\)", stylesheet):
        assert "//" not in url, url
        assert _static("web/" + url.strip("\"'")).is_file(), url


def test_every_font_is_kept_with_its_licence() -> None:
    fonts = _static("web/caipo.css").parent / "fonts"

    families = {
        path.name.split("-latin")[0].split("-cyrillic")[0] for path in fonts.glob("*.woff2")
    }

    assert families == {"inter", "source-serif-4", "jetbrains-mono"}
    for family in families:
        assert "SIL Open Font License" in (fonts / f"{family}-LICENSE.txt").read_text()
    for path in fonts.glob("*.woff2"):
        assert path.read_bytes()[:4] == b"wOF2", path.name


def test_the_navigation_script_sends_nothing_anywhere() -> None:
    script = _static("web/navigation.js").read_text()

    for sender in ("fetch", "XMLHttpRequest", "sendBeacon", "http", "cookie", "localStorage"):
        assert sender not in script
