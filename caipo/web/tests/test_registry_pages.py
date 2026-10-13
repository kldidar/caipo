"""The two pages of the registry over HTTP (ADR-0018 points 59 to 61 and testing
requirement 11; ADR-0019 points 11 to 16).

A browse page that every role reads, and an entry page on which an
Administrator verified with a trusted second factor maintains countries and
languages. Two kinds of test here assert what is true only until
Increment 3 and are replaced then (ADR-0019 point 22): those of the message
that the entry page shows an account with nothing to do, and those that the
pages hold no institution content. Each says so.
"""

import re
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from caipo.accounts.models import AccountStatus, AuditEvent, AuditEventChange, User
from caipo.accounts.selectors import Permission, Role
from caipo.accounts.tests.fixtures import UserFactory, code_at, enrolled_device
from caipo.accounts.tests.fixtures import verified as acting_verified
from caipo.registry import services
from caipo.registry.models import Country, Language
from caipo.web import registry
from caipo.web.access import declared_access
from caipo.web.tests.helpers import signed_in, verified

pytestmark = [pytest.mark.services, pytest.mark.django_db]

# Visibly synthetic fixture values. The codes are from the ranges the
# standards reserve for private use.
PASSWORD = "TEST-passphrase-for-fixtures-only"

LOGIN = "/login/"
VERIFY = "/login/verify/"
BROWSE = "/registry/"
ENTRY = "/registry/entry/"
CREATE_COUNTRY = "/registry/entry/countries/create/"
CREATE_LANGUAGE = "/registry/entry/languages/create/"
UNKNOWN = uuid.UUID("00000000-0000-4000-8000-00000000ffff")

COUNTRY = {"country-alpha2": "XA", "country-alpha3": "XAA", "country-name_en": "TEST Country A"}
LANGUAGE = {
    "language-code": "qaa",
    "language-script_code": "Qaaa",
    "language-name_en": "TEST Language A",
}
NOTHING_TO_DO = (
    "Countries and languages are maintained by an Administrator."
    " This page offers your account nothing to do."
)

# How each kind of account is signed in: its roles, and whether a code from a
# trusted second factor was verified.
ACCOUNTS: dict[str, tuple[tuple[Role, ...], bool]] = {
    "reader": ((Role.READER,), False),
    "researcher": ((Role.RESEARCHER,), False),
    "reviewer-on-a-password": ((Role.REVIEWER,), False),
    "reviewer-verified": ((Role.REVIEWER,), True),
    "administrator-on-a-password": ((Role.ADMINISTRATOR,), False),
    "administrator-verified": ((Role.ADMINISTRATOR,), True),
    "no-role": ((), False),
}
# Written out here, not read from the policy: ADR-0018 points 11 and 59.
REACH_BROWSE = {"reader", "researcher", "reviewer-verified", "administrator-verified"}
REACH_ENTRY = {"researcher", "reviewer-verified", "administrator-verified"}
MAY_CHANGE = {"administrator-verified"}


def _client(user_with_roles: UserFactory, account: str) -> Client:
    roles, second_factor = ACCOUNTS[account]
    user = user_with_roles(*roles)
    return verified(Client(), user) if second_factor else signed_in(Client(), user)


@pytest.fixture
def administrator(user_with_roles: UserFactory) -> User:
    return user_with_roles(Role.ADMINISTRATOR)


@pytest.fixture
def client_of_administrator(administrator: User) -> Client:
    """Return a client signed in as an Administrator with a trusted second factor."""
    return verified(Client(), administrator)


@pytest.fixture
def country(administrator: User) -> uuid.UUID:
    return services.create_country(
        actor=acting_verified(administrator), alpha2="XA", alpha3="XAA", name_en="TEST Country A"
    )


@pytest.fixture
def language(administrator: User) -> uuid.UUID:
    return services.create_language(
        actor=acting_verified(administrator),
        code="qaa",
        script_code="Qaaa",
        name_en="TEST Language A",
    )


def _country_url(public_id: object, operation: str) -> str:
    return f"/registry/entry/countries/{public_id}/{operation}/"


def _language_url(public_id: object, operation: str) -> str:
    return f"/registry/entry/languages/{public_id}/{operation}/"


def _changes(country: uuid.UUID, language: uuid.UUID) -> dict[str, tuple[str, dict[str, str]]]:
    """Return every POST of the registry, with a body that a permitted account could send."""
    return {
        "create a country": (
            CREATE_COUNTRY,
            {"country-alpha2": "XB", "country-alpha3": "XBB", "country-name_en": "TEST Country B"},
        ),
        "rename a country": (_country_url(country, "rename"), {"name_en": "TEST Renamed"}),
        "deactivate a country": (_country_url(country, "deactivate"), {}),
        "reactivate a country": (_country_url(country, "reactivate"), {}),
        "create a language": (
            CREATE_LANGUAGE,
            {
                "language-code": "qab",
                "language-script_code": "Qaab",
                "language-name_en": "TEST Language B",
            },
        ),
        "rename a language": (_language_url(language, "rename"), {"name_en": "TEST Renamed"}),
        "deactivate a language": (_language_url(language, "deactivate"), {}),
        "reactivate a language": (_language_url(language, "reactivate"), {}),
    }


CHANGES = sorted(_changes(UNKNOWN, UNKNOWN))


def _stored() -> dict[str, list[Any]]:
    return {
        "countries": list(Country.objects.order_by("id").values()),
        "languages": list(Language.objects.order_by("id").values()),
        "events": list(AuditEvent.objects.order_by("id").values()),
        "changes": list(AuditEventChange.objects.order_by("id").values()),
    }


def _text(response: Any) -> str:
    return str(response.content.decode())


def _patterns(resolver: URLResolver) -> Iterator[URLPattern]:
    for entry in resolver.url_patterns:
        if isinstance(entry, URLResolver):
            yield from _patterns(entry)
        else:
            yield entry


def _registry_routes() -> dict[str, URLPattern]:
    return {
        str(entry.name): entry
        for entry in _patterns(get_resolver())
        if str(entry.name).startswith("registry")
    }


# --- Declarations, and that there are two pages and no others ------------------


def test_each_view_declares_the_access_the_decision_gives_it() -> None:
    """ADR-0019 point 11: neither page's declaration changes in Increment 3."""
    assert declared_access(registry.browse) == Permission.REGISTRY_READ
    assert declared_access(registry.entry) == Permission.REGISTRY_INSTITUTIONS_MANAGE
    for view in (
        registry.create_country,
        registry.rename_country,
        registry.deactivate_country,
        registry.reactivate_country,
        registry.create_language,
        registry.rename_language,
        registry.deactivate_language,
        registry.reactivate_language,
    ):
        assert declared_access(view) == Permission.REGISTRY_REFERENCE_MANAGE


def test_the_registry_has_these_routes_and_no_others() -> None:
    declared = {name: declared_access(entry.callback) for name, entry in _registry_routes().items()}

    assert declared == {
        "registry": Permission.REGISTRY_READ,
        "registry-entry": Permission.REGISTRY_INSTITUTIONS_MANAGE,
        "registry-country-create": Permission.REGISTRY_REFERENCE_MANAGE,
        "registry-country-rename": Permission.REGISTRY_REFERENCE_MANAGE,
        "registry-country-deactivate": Permission.REGISTRY_REFERENCE_MANAGE,
        "registry-country-reactivate": Permission.REGISTRY_REFERENCE_MANAGE,
        "registry-language-create": Permission.REGISTRY_REFERENCE_MANAGE,
        "registry-language-rename": Permission.REGISTRY_REFERENCE_MANAGE,
        "registry-language-deactivate": Permission.REGISTRY_REFERENCE_MANAGE,
        "registry-language-reactivate": Permission.REGISTRY_REFERENCE_MANAGE,
    }


def test_only_the_two_pages_answer_a_get_and_every_other_route_only_a_post(
    client_of_administrator: Client, country: uuid.UUID, language: uuid.UUID
) -> None:
    """Two pages, and no others: a change has no page of its own."""
    assert client_of_administrator.get(BROWSE).status_code == 200
    assert client_of_administrator.get(ENTRY).status_code == 200
    for url, _ in _changes(country, language).values():
        assert client_of_administrator.get(url).status_code == 405, url
    for url in (BROWSE, ENTRY):
        assert client_of_administrator.post(url).status_code == 405, url


def test_no_registry_path_holds_an_internal_key(
    client_of_administrator: Client, country: uuid.UUID
) -> None:
    key = Country.objects.get().pk

    assert client_of_administrator.post(_country_url(key, "deactivate")).status_code == 404
    assert f"/countries/{key}/" not in _text(client_of_administrator.get(ENTRY))
    assert Country.objects.get().is_active


# --- Who reaches which page -----------------------------------------------------


@pytest.mark.parametrize("account", sorted(ACCOUNTS))
def test_each_role_reaches_or_is_refused_the_browse_page(
    user_with_roles: UserFactory, account: str
) -> None:
    response = _client(user_with_roles, account).get(BROWSE)

    assert response.status_code == (200 if account in REACH_BROWSE else 403)


@pytest.mark.parametrize("account", sorted(ACCOUNTS))
def test_each_role_reaches_or_is_refused_the_entry_page(
    user_with_roles: UserFactory, account: str
) -> None:
    response = _client(user_with_roles, account).get(ENTRY)

    assert response.status_code == (200 if account in REACH_ENTRY else 403)


@pytest.mark.parametrize("url", [BROWSE, ENTRY])
def test_an_anonymous_visitor_is_refused_both_pages(client: Client, url: str) -> None:
    response = client.get(url)

    assert response.status_code == 403
    assert "TEST" not in _text(response)


@pytest.mark.parametrize("url", [BROWSE, ENTRY])
def test_a_disabled_account_is_refused_on_its_next_request(
    user_with_roles: UserFactory, url: str
) -> None:
    user = user_with_roles(Role.ADMINISTRATOR)
    client = verified(Client(), user)
    assert client.get(url).status_code == 200

    User.objects.filter(pk=user.pk).update(status=AccountStatus.DISABLED)

    assert client.get(url).status_code == 403


def test_an_administrator_with_a_second_factor_nobody_approved_is_refused(
    user_with_roles: UserFactory,
) -> None:
    user = user_with_roles(Role.ADMINISTRATOR)
    enrolled_device(user, trusted=False)
    client = verified(Client(), user)

    assert client.get(BROWSE).status_code == 403
    assert client.get(ENTRY).status_code == 403
    assert client.post(CREATE_COUNTRY, COUNTRY).status_code == 403
    assert not Country.objects.exists()


@pytest.mark.parametrize("url", [BROWSE, ENTRY])
def test_the_pages_are_not_cached(client_of_administrator: Client, url: str) -> None:
    response = client_of_administrator.get(url)

    assert "no-store" in response["Cache-Control"]


# --- The browse page ------------------------------------------------------------


def test_the_browse_page_lists_countries_and_languages_with_their_codes_names_and_state(
    user_with_roles: UserFactory, administrator: User, country: uuid.UUID, language: uuid.UUID
) -> None:
    actor = acting_verified(administrator)
    services.create_country(actor=actor, alpha2="XB", alpha3="XBB", name_en="TEST Country B")
    services.deactivate_country(actor=actor, public_id=country)

    page = _text(signed_in(Client(), user_with_roles(Role.READER)).get(BROWSE))

    rows = [
        re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", row)).strip()
        for row in re.findall(r"<tr>(.*?)</tr>", page, flags=re.DOTALL)
    ]
    assert rows == [
        "Alpha-2 code Alpha-3 code English name State",
        "XA XAA TEST Country A Deactivated",
        "XB XBB TEST Country B Active",
        "Language code Script code English name State",
        "qaa Qaaa TEST Language A Active",
    ]


def test_an_empty_registry_says_that_nothing_has_been_entered(
    user_with_roles: UserFactory,
) -> None:
    page = _text(signed_in(Client(), user_with_roles(Role.READER)).get(BROWSE))

    assert "No country has been entered." in page
    assert "No language has been entered." in page


def test_the_browse_page_offers_nothing_to_change(
    client_of_administrator: Client, country: uuid.UUID, language: uuid.UUID
) -> None:
    page = _text(client_of_administrator.get(BROWSE))

    assert "<form" not in page and "<input" not in page and "<button" not in page


def test_the_browse_page_links_to_the_entry_page_only_for_an_account_that_reaches_it(
    user_with_roles: UserFactory,
) -> None:
    link = f'href="{reverse("registry-entry")}"'

    assert link not in _text(signed_in(Client(), user_with_roles(Role.READER)).get(BROWSE))
    assert link in _text(signed_in(Client(), user_with_roles(Role.RESEARCHER)).get(BROWSE))


def test_reading_the_pages_changes_and_records_nothing(
    client_of_administrator: Client, country: uuid.UUID, language: uuid.UUID
) -> None:
    before = _stored()

    client_of_administrator.get(BROWSE)
    client_of_administrator.get(ENTRY)

    assert _stored() == before


def test_a_name_is_escaped_on_both_pages(
    client_of_administrator: Client, administrator: User
) -> None:
    services.create_country(
        actor=acting_verified(administrator),
        alpha2="XA",
        alpha3="XAA",
        name_en='TEST <script>alert("x")</script> & more',
    )

    for url in (BROWSE, ENTRY):
        page = _text(client_of_administrator.get(url))

        assert "<script>alert" not in page
        assert "TEST &lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; more" in page


def test_no_internal_key_and_no_account_is_shown(
    client_of_administrator: Client, administrator: User, country: uuid.UUID, language: uuid.UUID
) -> None:
    for url in (BROWSE, ENTRY):
        page = _text(client_of_administrator.get(url))

        assert administrator.email not in page
        assert "@caipo.test" not in page


# --- The entry page for an account with nothing to do ---------------------------
# These tests are replaced in Increment 3 (ADR-0019 points 15 and 22): the
# account then has the institution forms, and the message is no longer true.


@pytest.mark.parametrize("account", ["researcher", "reviewer-verified"])
def test_an_account_that_may_not_maintain_the_reference_lists_is_told_so_plainly(
    user_with_roles: UserFactory,
    administrator: User,
    country: uuid.UUID,
    language: uuid.UUID,
    account: str,
) -> None:
    page = _text(_client(user_with_roles, account).get(ENTRY))

    assert NOTHING_TO_DO in page
    assert "<form" not in page and "<input" not in page and "<button" not in page
    # It is told why, and is shown nothing it could mistake for something to do.
    assert "Add a country" not in page and "Add a language" not in page
    assert "TEST Country A" not in page and "TEST Language A" not in page


def test_an_administrator_is_not_shown_the_message(client_of_administrator: Client) -> None:
    page = _text(client_of_administrator.get(ENTRY))

    assert NOTHING_TO_DO not in page
    assert "Add a country" in page and "Add a language" in page


def test_the_message_promises_nothing(user_with_roles: UserFactory) -> None:
    page = _text(signed_in(Client(), user_with_roles(Role.RESEARCHER)).get(ENTRY)).lower()

    for promise in ("soon", "later", "will be", "coming", "not yet", "future", "planned"):
        assert promise not in page, promise


# --- No institution content ------------------------------------------------------
# These tests are replaced in Increment 3 (ADR-0019 points 5 and 22).


@pytest.mark.parametrize("account", ["researcher", "reviewer-verified", "administrator-verified"])
@pytest.mark.parametrize("url", [BROWSE, ENTRY])
def test_neither_page_says_anything_of_institutions(
    user_with_roles: UserFactory, account: str, url: str
) -> None:
    page = _text(_client(user_with_roles, account).get(url)).lower()

    assert "institution" not in page


def test_no_registry_route_is_about_institutions() -> None:
    routes = _registry_routes()

    assert not [name for name in routes if "institution" in name]
    assert not [name for name, entry in routes.items() if "institution" in str(entry.pattern)]


# --- Changes: refused without the permission -------------------------------------


@pytest.mark.parametrize("change", CHANGES)
@pytest.mark.parametrize("account", sorted(set(ACCOUNTS) - MAY_CHANGE))
def test_every_change_is_refused_to_an_account_without_the_reference_permission(
    user_with_roles: UserFactory,
    administrator: User,
    country: uuid.UUID,
    language: uuid.UUID,
    account: str,
    change: str,
) -> None:
    """The view refuses the POST itself, whether or not the page showed a form."""
    url, body = _changes(country, language)[change]
    before = _stored()

    response = _client(user_with_roles, account).post(url, body)

    assert response.status_code == 403
    assert _stored() == before


@pytest.mark.parametrize("change", CHANGES)
def test_every_change_is_refused_to_an_anonymous_visitor(
    client: Client, administrator: User, country: uuid.UUID, language: uuid.UUID, change: str
) -> None:
    url, body = _changes(country, language)[change]
    before = _stored()

    assert client.post(url, body).status_code == 403
    assert _stored() == before


@pytest.mark.parametrize("change", CHANGES)
def test_a_refusal_is_the_same_for_a_record_that_exists_and_one_that_does_not(
    user_with_roles: UserFactory,
    administrator: User,
    country: uuid.UUID,
    language: uuid.UUID,
    change: str,
) -> None:
    """Refused on the declaration, before any record is looked up (ADR-0018 point 52)."""
    client = signed_in(Client(), user_with_roles(Role.RESEARCHER))
    existing, body = _changes(country, language)[change]
    missing, _ = _changes(UNKNOWN, UNKNOWN)[change]

    first, second = client.post(existing, body), client.post(missing, body)

    assert (first.status_code, second.status_code) == (403, 403)
    assert first.content == second.content


@pytest.mark.parametrize("change", CHANGES)
def test_the_service_refuses_for_itself_when_the_view_declares_too_little(
    user_with_roles: UserFactory,
    administrator: User,
    country: uuid.UUID,
    language: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    """With every registry view opened to any reader, a Researcher still changes nothing."""
    for entry in _registry_routes().values():
        monkeypatch.setattr(entry.callback, "caipo_access", Permission.REGISTRY_READ, raising=False)
    url, body = _changes(country, language)[change]
    before = _stored()

    response = signed_in(Client(), user_with_roles(Role.RESEARCHER)).post(url, body)

    assert response.status_code == 403
    assert _stored() == before


@pytest.mark.parametrize("change", CHANGES)
def test_every_change_needs_a_csrf_token(
    administrator: User, country: uuid.UUID, language: uuid.UUID, change: str
) -> None:
    client = verified(Client(enforce_csrf_checks=True), administrator)
    url, body = _changes(country, language)[change]
    if change.startswith("reactivate"):
        actor = acting_verified(administrator)
        services.deactivate_country(actor=actor, public_id=country)
        services.deactivate_language(actor=actor, public_id=language)
    before = _stored()

    assert client.post(url, body).status_code == 403
    assert _stored() == before

    token = client.get(ENTRY).cookies["csrftoken"].value
    assert client.post(url, {**body, "csrfmiddlewaretoken": token}).status_code == 302
    assert _stored() != before


# --- Changes: made by an Administrator -------------------------------------------


def test_an_administrator_creates_a_country(
    client_of_administrator: Client, administrator: User
) -> None:
    response = client_of_administrator.post(CREATE_COUNTRY, COUNTRY)

    assert response.status_code == 302 and response["Location"] == f"{ENTRY}?saved=1"
    country = Country.objects.get()
    assert (country.alpha2, country.alpha3, country.name_en, country.is_active) == (
        "XA",
        "XAA",
        "TEST Country A",
        True,
    )
    assert list(AuditEvent.objects.values_list("action", "target_public_id", "actor_id")) == [
        ("created", country.public_id, administrator.pk)
    ]
    assert "The change was saved and recorded." in _text(
        client_of_administrator.get(response["Location"])
    )


def test_an_administrator_creates_a_language(
    client_of_administrator: Client, administrator: User
) -> None:
    response = client_of_administrator.post(CREATE_LANGUAGE, LANGUAGE)

    assert response.status_code == 302 and response["Location"] == f"{ENTRY}?saved=1"
    language = Language.objects.get()
    assert (language.code, language.script_code, language.name_en, language.is_active) == (
        "qaa",
        "Qaaa",
        "TEST Language A",
        True,
    )
    assert list(AuditEvent.objects.values_list("action", "target_public_id", "actor_id")) == [
        ("created", language.public_id, administrator.pk)
    ]


def test_an_administrator_renames_deactivates_and_reactivates_through_the_page(
    client_of_administrator: Client, country: uuid.UUID, language: uuid.UUID
) -> None:
    for url_of, model, public_id in (
        (_country_url, Country, country),
        (_language_url, Language, language),
    ):
        records: Any = model.objects
        renamed = client_of_administrator.post(
            url_of(public_id, "rename"), {"name_en": "  TEST Renamed "}
        )
        assert renamed.status_code == 302
        assert records.get().name_en == "TEST Renamed"

        assert client_of_administrator.post(url_of(public_id, "deactivate")).status_code == 302
        assert not records.get().is_active

        assert client_of_administrator.post(url_of(public_id, "reactivate")).status_code == 302
        assert records.get().is_active

    assert list(AuditEvent.objects.order_by("id").values_list("action", flat=True)) == [
        "created",
        "created",
        "updated",
        "deactivated",
        "reactivated",
        "updated",
        "deactivated",
        "reactivated",
    ]
    assert list(AuditEventChange.objects.values_list("field", "old_value", "new_value")) == [
        ("name_en", "TEST Country A", "TEST Renamed"),
        ("name_en", "TEST Language A", "TEST Renamed"),
    ]


def test_the_entry_page_offers_each_record_the_changes_that_would_change_something(
    client_of_administrator: Client, administrator: User, country: uuid.UUID, language: uuid.UUID
) -> None:
    services.deactivate_language(actor=acting_verified(administrator), public_id=language)

    page = _text(client_of_administrator.get(ENTRY))

    assert f'action="{_country_url(country, "rename")}"' in page
    assert f'action="{_country_url(country, "deactivate")}"' in page
    assert f'action="{_country_url(country, "reactivate")}"' not in page
    assert f'action="{_language_url(language, "rename")}"' in page
    assert f'action="{_language_url(language, "reactivate")}"' in page
    assert f'action="{_language_url(language, "deactivate")}"' not in page
    assert page.count("csrfmiddlewaretoken") == page.count("<form")


def test_the_entry_page_offers_no_way_to_change_a_code_or_to_delete(
    client_of_administrator: Client, country: uuid.UUID, language: uuid.UUID
) -> None:
    page = _text(client_of_administrator.get(ENTRY))
    record_forms = [
        form
        for form in re.findall(r"<form.*?</form>", page, flags=re.DOTALL)
        if "/create/" not in form
    ]

    assert len(record_forms) == 4
    for form in record_forms:
        assert set(re.findall(r'name="([^"]+)"', form)) <= {"csrfmiddlewaretoken", "name_en"}
    assert "delete" not in page.lower().replace("nothing here can be deleted", "")


def test_a_code_sent_with_a_rename_is_ignored(
    client_of_administrator: Client, country: uuid.UUID
) -> None:
    before = Country.objects.values().get()

    response = client_of_administrator.post(
        _country_url(country, "rename"),
        {"name_en": "TEST Renamed", "alpha2": "XB", "alpha3": "XBB", "public_id": str(UNKNOWN)},
    )

    assert response.status_code == 302
    assert Country.objects.values().get() == {**before, "name_en": "TEST Renamed"}


# --- Changes: refused for what was entered ---------------------------------------


@pytest.mark.parametrize(
    "entered",
    [
        {"country-alpha2": "xa"},
        {"country-alpha2": "XA "},
        {"country-alpha2": " XA"},
        {"country-alpha2": "XAA"},
        {"country-alpha2": "ХA"},
        {"country-alpha2": ""},
        {"country-alpha3": "xaa"},
        {"country-alpha3": "XAA "},
        {"country-alpha3": "XA"},
        {"country-alpha3": ""},
        {"country-name_en": ""},
        {"country-name_en": "   "},
        {"country-name_en": "T" * 201},
    ],
    ids=str,
)
def test_a_country_that_is_not_valid_is_not_saved_and_the_page_says_so(
    client_of_administrator: Client, entered: dict[str, str]
) -> None:
    """A code is taken exactly as typed: the page trims and converts nothing."""
    response = client_of_administrator.post(CREATE_COUNTRY, {**COUNTRY, **entered})

    assert response.status_code == 400
    assert "Nothing was saved. A country needs an alpha-2 code of two capital letters" in _text(
        response
    )
    assert not Country.objects.exists() and not AuditEvent.objects.exists()


@pytest.mark.parametrize(
    "entered",
    [
        {"language-code": "QAA"},
        {"language-code": "qa"},
        {"language-code": "qaa "},
        {"language-code": "qaa-Qaaa"},
        {"language-code": ""},
        {"language-script_code": "qaaa"},
        {"language-script_code": "QAAA"},
        {"language-script_code": "Qaa"},
        {"language-script_code": "Qaaa "},
        {"language-script_code": ""},
        {"language-name_en": ""},
        {"language-name_en": " \t "},
        {"language-name_en": "T" * 201},
    ],
    ids=str,
)
def test_a_language_that_is_not_valid_is_not_saved_and_the_page_says_so(
    client_of_administrator: Client, entered: dict[str, str]
) -> None:
    response = client_of_administrator.post(CREATE_LANGUAGE, {**LANGUAGE, **entered})

    assert response.status_code == 400
    assert "Nothing was saved. A language needs a language code of three lower-case" in _text(
        response
    )
    assert not Language.objects.exists() and not AuditEvent.objects.exists()


def test_what_was_typed_is_shown_again_when_it_is_refused(client_of_administrator: Client) -> None:
    response = client_of_administrator.post(
        CREATE_COUNTRY, {**COUNTRY, "country-alpha2": "xa", "country-name_en": "TEST Typed name"}
    )

    page = _text(response)
    assert 'value="xa"' in page and 'value="TEST Typed name"' in page


def test_a_country_whose_code_is_in_use_is_not_saved_and_the_page_says_so(
    client_of_administrator: Client, country: uuid.UUID
) -> None:
    before = _stored()

    response = client_of_administrator.post(
        CREATE_COUNTRY, {**COUNTRY, "country-alpha3": "XBB", "country-name_en": "TEST Other"}
    )

    assert response.status_code == 409
    assert "A country with one of these codes exists." in _text(response)
    assert _stored() == before


def test_a_language_whose_pair_of_codes_is_in_use_is_not_saved_and_the_page_says_so(
    client_of_administrator: Client, language: uuid.UUID
) -> None:
    before = _stored()

    response = client_of_administrator.post(CREATE_LANGUAGE, LANGUAGE)

    assert response.status_code == 409
    assert "A language with this language code and script code exists." in _text(response)
    assert _stored() == before


def test_the_same_language_in_another_script_is_saved(
    client_of_administrator: Client, language: uuid.UUID
) -> None:
    response = client_of_administrator.post(
        CREATE_LANGUAGE, {**LANGUAGE, "language-script_code": "Qaab"}
    )

    assert response.status_code == 302
    assert Language.objects.count() == 2


@pytest.mark.parametrize("name_en", ["", "  ", "T" * 201])
def test_a_rename_to_no_usable_name_is_refused_and_the_page_says_so(
    client_of_administrator: Client, country: uuid.UUID, language: uuid.UUID, name_en: str
) -> None:
    before = _stored()

    for url in (_country_url(country, "rename"), _language_url(language, "rename")):
        response = client_of_administrator.post(url, {"name_en": name_en})

        assert response.status_code == 400
        assert "Nothing was saved. Give an English name" in _text(response)

    assert _stored() == before


# What a failure of the database would say of itself. None of it belongs on a page.
DATABASE_DETAILS = ("psycopg", "PostgreSQL", "DataError", "Traceback", "0x00", "registry_")


@pytest.mark.parametrize(
    ("url", "entered", "message"),
    [
        (CREATE_COUNTRY, {**COUNTRY, "country-name_en": "TEST \x00 name"}, "A country needs"),
        (CREATE_COUNTRY, {**COUNTRY, "country-name_en": "\x00"}, "A country needs"),
        (CREATE_COUNTRY, {**COUNTRY, "country-alpha2": "X\x00"}, "A country needs"),
        (CREATE_COUNTRY, {**COUNTRY, "country-alpha3": "XA\x00"}, "A country needs"),
        (CREATE_LANGUAGE, {**LANGUAGE, "language-name_en": "TEST \x00 name"}, "A language needs"),
        (CREATE_LANGUAGE, {**LANGUAGE, "language-code": "qa\x00"}, "A language needs"),
        (CREATE_LANGUAGE, {**LANGUAGE, "language-script_code": "Qaa\x00"}, "A language needs"),
    ],
    ids=[
        "country-name",
        "country-name-nul-only",
        "country-alpha2",
        "country-alpha3",
        "language-name",
        "language-code",
        "language-script-code",
    ],
)
def test_a_creation_that_holds_a_nul_character_is_refused_as_any_invalid_entry_is(
    client_of_administrator: Client, url: str, entered: dict[str, str], message: str
) -> None:
    """PostgreSQL cannot store NUL in text. It is refused before the database is asked."""
    response = client_of_administrator.post(url, entered)

    page = _text(response)
    assert response.status_code == 400
    assert f"Nothing was saved. {message}" in page
    assert not any(detail in page for detail in DATABASE_DETAILS)
    assert _stored() == {"countries": [], "languages": [], "events": [], "changes": []}


@pytest.mark.parametrize("name_en", ["TEST \x00 name", "\x00", "\x00TEST Country A"])
def test_a_rename_that_holds_a_nul_character_is_refused_as_any_invalid_name_is(
    client_of_administrator: Client, country: uuid.UUID, language: uuid.UUID, name_en: str
) -> None:
    before = _stored()

    for url in (_country_url(country, "rename"), _language_url(language, "rename")):
        response = client_of_administrator.post(url, {"name_en": name_en})

        page = _text(response)
        assert response.status_code == 400
        assert "Nothing was saved. Give an English name" in page
        assert not any(detail in page for detail in DATABASE_DETAILS)

    assert _stored() == before


def test_a_change_that_changes_nothing_is_refused_and_the_page_says_so(
    client_of_administrator: Client, country: uuid.UUID, language: uuid.UUID
) -> None:
    before = _stored()

    for url, body in (
        (_country_url(country, "rename"), {"name_en": " TEST Country A "}),
        (_country_url(country, "reactivate"), {}),
        (_language_url(language, "rename"), {"name_en": "TEST Language A"}),
        (_language_url(language, "reactivate"), {}),
    ):
        response = client_of_administrator.post(url, body)

        assert response.status_code == 409, url
        assert "Nothing was changed: the record is already as you asked." in _text(response)

    assert _stored() == before


@pytest.mark.parametrize("operation", ["rename", "deactivate", "reactivate"])
def test_a_change_to_a_record_that_does_not_exist_is_refused_and_the_page_says_so(
    client_of_administrator: Client, country: uuid.UUID, language: uuid.UUID, operation: str
) -> None:
    before = _stored()
    body = {"name_en": "TEST Renamed"} if operation == "rename" else {}

    for url in (_country_url(UNKNOWN, operation), _language_url(UNKNOWN, operation)):
        response = client_of_administrator.post(url, body)

        assert response.status_code == 404
        assert "Nothing was changed: there is no such record." in _text(response)

    # A country is not reached through the identifier of a language, or the reverse.
    assert client_of_administrator.post(_country_url(language, operation), body).status_code == 404
    assert client_of_administrator.post(_language_url(country, operation), body).status_code == 404
    assert _stored() == before


def test_a_path_that_names_no_identifier_is_not_a_route(client_of_administrator: Client) -> None:
    for name in ("not-a-uuid", "1", "XA"):
        assert client_of_administrator.post(_country_url(name, "deactivate")).status_code == 404


# --- From the sign-in pages to a recorded change ----------------------------------


def test_an_administrator_who_signs_in_with_password_and_code_changes_the_registry(
    user_with_roles: UserFactory,
) -> None:
    """The whole way, with nothing put into the session by the test.

    The password and then a code from the account's trusted second factor
    are given to the sign-in pages, and the change that follows is recorded
    as that account's.
    """
    user = user_with_roles(Role.ADMINISTRATOR)
    user.set_password(PASSWORD)
    user.save()
    enrolled_device(user)
    client = Client()

    assert client.post(LOGIN, {"email": user.email, "password": PASSWORD}).status_code == 302
    # The password alone reaches nothing of the registry.
    assert client.get(ENTRY).status_code == 403
    assert client.post(CREATE_COUNTRY, COUNTRY).status_code == 403
    assert not Country.objects.exists()

    assert client.post(VERIFY, {"code": code_at()}).status_code == 302
    assert client.get(ENTRY).status_code == 200
    assert client.post(CREATE_COUNTRY, COUNTRY).status_code == 302

    assert list(AuditEvent.objects.values_list("action", "actor_id")) == [("created", user.pk)]


def test_a_researcher_who_signs_in_with_a_password_reads_and_cannot_change(
    user_with_roles: UserFactory,
) -> None:
    user = user_with_roles(Role.RESEARCHER)
    user.set_password(PASSWORD)
    user.save()
    client = Client()

    assert client.post(LOGIN, {"email": user.email, "password": PASSWORD}).status_code == 302

    assert client.get(BROWSE).status_code == 200
    assert NOTHING_TO_DO in _text(client.get(ENTRY))
    assert client.post(CREATE_COUNTRY, COUNTRY).status_code == 403
    assert not Country.objects.exists() and not AuditEvent.objects.exists()


# --- The signed-in page -----------------------------------------------------------


@pytest.mark.parametrize("account", sorted(ACCOUNTS))
def test_the_signed_in_page_links_to_the_registry_pages_an_account_reaches(
    user_with_roles: UserFactory, account: str
) -> None:
    page = _text(_client(user_with_roles, account).get(LOGIN))

    assert (f'href="{BROWSE}"' in page) is (account in REACH_BROWSE)
    assert (f'href="{ENTRY}"' in page) is (account in REACH_ENTRY)
