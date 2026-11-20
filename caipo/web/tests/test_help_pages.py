"""The help pages, the help panel, and the help assistant's answers (ADR-0025 point 3)."""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
from django.test import Client

from caipo.accounts.selectors import Role
from caipo.accounts.tests.fixtures import UserFactory
from caipo.assistant import config, pipeline
from caipo.assistant.providers import FakeProvider
from caipo.retrieval import selectors as retrieval_selectors
from caipo.retrieval import services as retrieval_services
from caipo.web.tests.helpers import signed_in, verified

pytestmark = pytest.mark.django_db

ASK = "/help/ask/"
HTMX = Path(__file__).resolve().parents[1] / "static" / "web" / "htmx"
HX = {"HX-Request": "true"}


def _text(response: Any) -> str:
    return str(response.content.decode())


def _provider(monkeypatch: pytest.MonkeyPatch, *statements: dict[str, object]) -> FakeProvider:
    def respond(system: str, user: str) -> str:
        if system.startswith("You check numbered statements"):
            count = len(json.loads(user)["statements"])
            return json.dumps(
                {"verdicts": [{"index": i, "verdict": "supported"} for i in range(count)]}
            )
        return json.dumps({"statements": list(statements), "gaps": []})

    provider = FakeProvider(respond)
    monkeypatch.setattr(pipeline, "get_provider", lambda: provider)
    return provider


@pytest.fixture
def indexed() -> None:
    retrieval_services.rebuild_index()


def test_the_help_pages_are_public_and_list_every_page_and_section(client: Client) -> None:
    page = _text(client.get("/help/"))

    for help_page in retrieval_selectors.help_corpus():
        assert f'href="/help/{help_page.page}/"' in page
        for section in help_page.sections:
            assert f'href="/help/{help_page.page}/#{section.anchor}"' in page


def test_a_help_page_shows_each_section_under_its_anchor(client: Client) -> None:
    help_page = retrieval_selectors.help_corpus()[0]

    page = _text(client.get(f"/help/{help_page.page}/"))

    for section in help_page.sections:
        assert f'id="{section.anchor}"' in page
        assert section.heading in page


@pytest.mark.parametrize("name", ["TEST", "zzqx"])
def test_an_unknown_help_page_is_not_found(client: Client, name: str) -> None:
    assert client.get(f"/help/{name}/").status_code == 404


def test_no_help_page_takes_the_name_of_the_question_route() -> None:
    assert "ask" not in {page.page for page in retrieval_selectors.help_corpus()}


def test_the_panel_is_offered_to_an_account_that_may_ask_and_holds_no_form(
    client: Client, user_with_roles: UserFactory
) -> None:
    page = _text(signed_in(client, user_with_roles(Role.READER)).get("/"))

    assert 'class="help-panel"' in page
    assert f'hx-get="{ASK}" hx-trigger="toggle once"' in page
    assert f'<a href="{ASK}">' in page
    assert "web/htmx/htmx.min.js" in page
    assert "<form" not in page and "csrfmiddlewaretoken" not in page
    configuration = json.loads(re.findall(r"<meta name=\"htmx-config\" content='([^']+)'", page)[0])
    assert configuration == {
        "allowEval": False,
        "allowScriptTags": False,
        "includeIndicatorStyles": False,
        "selfRequestsOnly": True,
        "historyCacheSize": 0,
    }


def test_the_panel_is_not_offered_to_whoever_may_not_ask(
    client: Client, user_with_roles: UserFactory
) -> None:
    anonymous = _text(client.get("/"))
    administrator = _text(verified(Client(), user_with_roles(Role.ADMINISTRATOR)).get("/"))

    for page in (anonymous, administrator):
        assert "help-panel" not in page
        assert "htmx" not in page


def test_an_anonymous_visitor_may_not_ask(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(monkeypatch)

    assert client.post(ASK, {"question": "How do I export?"}, headers=HX).status_code == 403
    assert provider.calls == []


def test_opening_the_panel_loads_the_form_that_names_the_provider(
    client: Client, user_with_roles: UserFactory
) -> None:
    reader = signed_in(client, user_with_roles(Role.READER))
    provider = config.load().provider

    in_panel = _text(reader.get(ASK, headers=HX))
    as_page = _text(reader.get(ASK))

    assert "<html" not in in_panel and "<html" in as_page
    for form in (in_panel, as_page):
        assert f'hx-post="{ASK}"' in form and "csrfmiddlewaretoken" in form
        assert f"Sent to {provider.label} ({provider.model})" in form


def test_a_page_without_navigation_has_no_panel(
    client: Client, user_with_roles: UserFactory
) -> None:
    page = _text(signed_in(client, user_with_roles(Role.READER)).get("/password-reset/"))

    assert "help-panel" not in page and "htmx" not in page


@pytest.mark.usefixtures("indexed")
def test_the_panel_gets_the_answer_alone_with_links_to_the_help_sections(
    client: Client, user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    _provider(
        monkeypatch,
        {
            "text": "Choose Export CSV or Export JSON.",
            "label": "documented_statement",
            "citations": ["H1"],
        },
    )

    response = signed_in(client, user_with_roles(Role.READER)).post(
        ASK, {"question": "How do I export an analysis?"}, headers=HX
    )
    fragment = _text(response)

    assert response.status_code == 200
    assert "<html" not in fragment
    assert "Choose Export CSV or Export JSON." in fragment
    assert re.search(r'href="/help/[a-z-]+/#[a-z0-9-]+"', fragment)


@pytest.mark.usefixtures("indexed")
def test_without_script_the_answer_is_a_page(
    client: Client, user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    _provider(
        monkeypatch,
        {
            "text": "Choose Export CSV or Export JSON.",
            "label": "documented_statement",
            "citations": ["H1"],
        },
    )

    page = _text(
        signed_in(client, user_with_roles(Role.READER)).post(
            ASK, {"question": "How do I export an analysis?"}
        )
    )

    assert "<html" in page and "Choose Export CSV or Export JSON." in page
    assert f'action="{ASK}"' in page, "the form stays, to ask again"


@pytest.mark.usefixtures("indexed")
def test_a_question_outside_the_help_gets_the_fixed_reply(
    client: Client, user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(monkeypatch)

    fragment = _text(
        signed_in(client, user_with_roles(Role.READER)).post(
            ASK, {"question": "zzqx wvvp"}, headers=HX
        )
    )

    assert "The help pages do not answer this question. They cover:" in fragment
    for help_page in retrieval_selectors.help_corpus():
        assert f'href="/help/{help_page.page}/"' in fragment
    assert provider.calls == []


@pytest.mark.usefixtures("indexed")
def test_a_models_words_are_shown_escaped(
    client: Client, user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    statement = pipeline.StatementShown(
        text="<b>TEST</b>", label="documented_statement", flags=(), sources=()
    )
    real = pipeline.answer_question

    def answered(**options: Any) -> pipeline.Answer:
        answer = real(**options)
        return pipeline.Answer(
            answer.interaction, answer.assistant, "answered", "english", (statement,)
        )

    monkeypatch.setattr(pipeline, "answer_question", answered)
    _provider(monkeypatch)

    fragment = _text(
        signed_in(client, user_with_roles(Role.READER)).post(ASK, {"question": "zzqx"}, headers=HX)
    )

    assert "&lt;b&gt;TEST&lt;/b&gt;" in fragment and "<b>TEST</b>" not in fragment


def test_a_refused_question_is_explained_in_the_panel(
    client: Client, user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(monkeypatch)
    reader = signed_in(client, user_with_roles(Role.READER))

    in_panel = reader.post(ASK, {"question": "   "}, headers=HX)
    as_page = reader.post(ASK, {"question": "   "})

    assert in_panel.status_code == 200 and 'role="alert"' in _text(in_panel)
    assert as_page.status_code == 400
    assert provider.calls == []


def test_htmx_is_kept_at_its_pinned_version_with_its_licence() -> None:
    readme = (HTMX / "README.md").read_text(encoding="utf-8")
    digest = hashlib.sha256((HTMX / "htmx.min.js").read_bytes()).hexdigest()

    assert digest in readme
    assert "`htmx.org` 2.0.11" in readme
    assert "Zero-Clause BSD" in (HTMX / "LICENSE.txt").read_text(encoding="utf-8")
