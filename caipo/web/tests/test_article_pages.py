"""Contributed articles over HTTP (ADR-0022): writing, reviewing, and reading them."""

import re
from typing import Any

import pytest
from django.test import Client

from caipo.accounts.models import User
from caipo.accounts.selectors import Permission, Role
from caipo.accounts.tests.fixtures import UserFactory
from caipo.articles.models import Article, ArticleDecision
from caipo.web import articles
from caipo.web.access import declared_access
from caipo.web.tests.helpers import signed_in, verified

pytestmark = [pytest.mark.services, pytest.mark.django_db]

LIST = "/articles/"
NEW = "/articles/new/"
MINE = "/articles/mine/"
REVIEW = "/articles/review/"

# Visibly synthetic.
ARTICLE = {
    "author_name": "TEST Author",
    "title": "TEST article on a synthetic subject",
    "summary": "TEST summary.",
    "body": "TEST first paragraph.\n\nTEST second paragraph.",
    "licence": "on",
}
REASON = "TEST reason: outside the scope of CAIPO."


def _write(client: Client, **changes: str) -> Any:
    return client.post(NEW, {**ARTICLE, **changes})


def _written(client: Client, **changes: str) -> str:
    response = _write(client, **changes)
    assert response.status_code == 302, response.content.decode()[:500]
    location = str(response["Location"])
    assert location.endswith("?sent=1")
    return location.removesuffix("?sent=1")


def _review_url(article_url: str) -> str:
    return article_url.replace(LIST, REVIEW)


def _text(response: Any) -> str:
    return str(response.content.decode())


@pytest.fixture
def author(client: Client, user_with_roles: UserFactory) -> Client:
    return signed_in(client, user_with_roles(Role.READER))


@pytest.fixture
def reader(user_with_roles: UserFactory) -> Client:
    return signed_in(Client(), user_with_roles(Role.READER))


@pytest.fixture
def administrator(user_with_roles: UserFactory) -> Client:
    return verified(Client(), user_with_roles(Role.ADMINISTRATOR))


def test_from_writing_to_publication_to_every_reader(
    author: Client, reader: Client, administrator: Client
) -> None:
    url = _written(author)

    sent = _text(author.get(f"{url}?sent=1"))
    assert "Your article has been sent for review" in sent
    assert "Awaiting review" in sent
    assert reader.get(url).status_code == 404
    assert "TEST article" not in _text(reader.get(LIST))

    queue = _text(administrator.get(REVIEW))
    assert _review_url(url) in queue
    review = _text(administrator.get(_review_url(url)))
    assert 'value="published"' in review and 'value="declined"' in review
    decided = administrator.post(_review_url(url), {"decision": "published", "reason": ""})
    assert decided.status_code == 302

    listed = _text(reader.get(LIST))
    assert "TEST article on a synthetic subject" in listed
    page = _text(reader.get(url))
    assert "By TEST Author" in page
    assert "A contributed article." in page
    assert "https://creativecommons.org/licenses/by/4.0/" in page
    assert "<p>TEST first paragraph.</p>" in page
    assert "Published" in _text(author.get(MINE))


def test_a_declined_article_tells_its_author_why_and_nobody_else_sees_it(
    author: Client, reader: Client, administrator: Client
) -> None:
    url = _written(author)

    administrator.post(_review_url(url), {"decision": "declined", "reason": REASON})

    own = _text(author.get(url))
    assert "Declined" in own and REASON in own
    assert reader.get(url).status_code == 404
    mine = _text(author.get(MINE))
    assert "Declined" in mine and REASON in mine


def test_a_withdrawn_article_leaves_the_list(
    author: Client, reader: Client, administrator: Client
) -> None:
    url = _written(author)
    administrator.post(_review_url(url), {"decision": "published", "reason": ""})
    assert reader.get(url).status_code == 200

    review = _text(administrator.get(_review_url(url)))
    assert 'value="withdrawn"' in review and 'value="published"' not in review
    administrator.post(_review_url(url), {"decision": "withdrawn", "reason": REASON})

    assert reader.get(url).status_code == 404
    assert "TEST article" not in _text(reader.get(LIST))
    assert REASON in _text(author.get(url))


def test_a_decline_without_a_reason_is_refused_and_records_nothing(
    author: Client, administrator: Client
) -> None:
    url = _written(author)

    response = administrator.post(_review_url(url), {"decision": "declined", "reason": " "})

    assert response.status_code == 400
    assert "reason" in _text(response)
    assert not ArticleDecision.objects.exists()


def test_a_reviewer_cannot_decide_about_their_own_article(user_with_roles: UserFactory) -> None:
    client = verified(Client(), user_with_roles(Role.REVIEWER))
    url = _written(client)

    page = _text(client.get(_review_url(url)))
    response = client.post(_review_url(url), {"decision": "published", "reason": ""})

    assert "This is your own article." in page
    assert 'value="published"' not in page
    assert response.status_code == 400
    assert not ArticleDecision.objects.exists()


def test_an_article_is_sent_only_with_the_licence(author: Client) -> None:
    data = {key: value for key, value in ARTICLE.items() if key != "licence"}

    response = author.post(NEW, data)

    assert response.status_code == 400
    assert "CC BY 4.0" in _text(response)
    assert not Article.objects.exists()


def test_an_incomplete_article_is_refused(author: Client) -> None:
    response = _write(author, title="")

    assert response.status_code == 400
    assert not Article.objects.exists()


def test_the_text_is_shown_escaped_and_never_as_markup(
    author: Client, reader: Client, administrator: Client
) -> None:
    hostile = '<script>alert("TEST")</script>\n\n<a href="javascript:x">TEST</a>'
    url = _written(author, body=hostile, title="TEST <b>title</b>", author_name="<i>TEST</i>")
    administrator.post(_review_url(url), {"decision": "published", "reason": ""})

    for page in (_text(reader.get(url)), _text(administrator.get(_review_url(url)))):
        assert "<script>" not in page
        assert "&lt;script&gt;" in page
        assert '<a href="javascript:x">' not in page
        assert "<b>title</b>" not in page
        assert "<i>TEST</i>" not in page


def test_deciding_without_a_csrf_token_is_refused(
    author: Client, user_with_roles: UserFactory
) -> None:
    url = _written(author)
    client = verified(Client(enforce_csrf_checks=True), user_with_roles(Role.ADMINISTRATOR))

    response = client.post(_review_url(url), {"decision": "published", "reason": ""})

    assert response.status_code == 403
    assert not ArticleDecision.objects.exists()


def test_the_pages_declare_their_access() -> None:
    assert declared_access(articles.articles) == Permission.WORKSPACE_READ
    assert declared_access(articles.article) == Permission.WORKSPACE_READ
    assert declared_access(articles.article_new) == Permission.ARTICLES_SUBMIT
    assert declared_access(articles.articles_mine) == Permission.ARTICLES_SUBMIT
    assert declared_access(articles.articles_review) == Permission.ARTICLES_REVIEW
    assert declared_access(articles.article_review) == Permission.ARTICLES_REVIEW


@pytest.mark.parametrize("role", [Role.READER, Role.RESEARCHER])
def test_readers_and_researchers_cannot_open_the_review_pages(
    author: Client, user_with_roles: UserFactory, role: Role
) -> None:
    url = _written(author)
    client = signed_in(Client(), user_with_roles(role))

    assert client.get(REVIEW).status_code == 403
    assert client.get(_review_url(url)).status_code == 403
    assert client.post(_review_url(url), {"decision": "published"}).status_code == 403
    assert not ArticleDecision.objects.exists()


def test_an_administrator_on_a_password_alone_cannot_review(
    author: Client, user_with_roles: UserFactory
) -> None:
    url = _written(author)
    client = signed_in(Client(), user_with_roles(Role.ADMINISTRATOR))

    assert client.get(REVIEW).status_code == 403
    assert client.post(_review_url(url), {"decision": "published"}).status_code == 403


def test_an_administrator_reviews_and_does_not_write(administrator: Client) -> None:
    assert administrator.get(REVIEW).status_code == 200
    assert administrator.get(NEW).status_code == 403
    assert administrator.get(LIST).status_code == 403


def test_nobody_signed_out_reaches_any_article_page(author: Client) -> None:
    url = _written(author)
    anonymous = Client()

    for page in (LIST, NEW, MINE, REVIEW, url, _review_url(url)):
        response = anonymous.get(page)
        assert response.status_code in (302, 403), page
        assert "TEST article" not in _text(response)


def test_an_unknown_article_is_not_found(administrator: Client, reader: Client) -> None:
    unknown = "/articles/00000000-0000-4000-8000-000000000001/"

    assert reader.get(unknown).status_code == 404
    assert administrator.get(_review_url(unknown)).status_code == 404


def test_the_list_offers_writing_and_review_to_those_who_may(
    reader: Client, user_with_roles: UserFactory
) -> None:
    page = _text(reader.get(LIST))
    reviewer_page = _text(verified(Client(), user_with_roles(Role.REVIEWER)).get(LIST))

    assert f'href="{NEW}"' in page and f'href="{MINE}"' in page
    assert f'href="{REVIEW}"' not in page
    assert f'href="{REVIEW}"' in reviewer_page
    assert re.search(r"Review: 0 articles waiting", reviewer_page)


def test_the_author_is_named_by_the_chosen_name_and_never_by_email(
    author: Client, reader: Client, administrator: Client
) -> None:
    url = _written(author)
    administrator.post(_review_url(url), {"decision": "published", "reason": ""})
    email = User.objects.get(pk=Article.objects.get().author_id).email

    for page in (_text(reader.get(url)), _text(reader.get(LIST))):
        assert email not in page
