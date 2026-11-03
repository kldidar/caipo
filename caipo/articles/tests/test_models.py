"""What PostgreSQL holds for contributed articles, whatever the application does (ADR-0022)."""

from collections.abc import Callable
from typing import Any

import pytest
from django.db import IntegrityError, connection, transaction

from caipo.accounts.models import User
from caipo.articles.models import Article, ArticleDecision, status_of

pytestmark = pytest.mark.django_db

# Visibly synthetic.
REASON = "TEST reason"


@pytest.fixture
def author() -> User:
    return User.objects.create_user("test.author@caipo.test")


@pytest.fixture
def reviewer() -> User:
    return User.objects.create_user("test.reviewer@caipo.test")


@pytest.fixture
def article(author: User) -> Article:
    return Article.objects.create(
        author=author,
        author_name="TEST Author",
        title="TEST title",
        summary="TEST summary",
        body="TEST body",
        licence="CC-BY-4.0",
    )


def _refused(constraint: str, make: Callable[[], Any]) -> None:
    with pytest.raises(IntegrityError, match=constraint), transaction.atomic():
        make()


def _decide(article: Article, reviewer: User, decision: str, reason: str = REASON) -> Any:
    return ArticleDecision.objects.create(
        article=article, decision=decision, reason=reason, decided_by=reviewer
    )


@pytest.mark.parametrize("field", ["author_name", "title", "summary", "body"])
def test_the_database_refuses_an_article_with_an_empty_part(author: User, field: str) -> None:
    values = {
        "author_name": "TEST",
        "title": "TEST",
        "summary": "TEST",
        "body": "TEST",
        "licence": "CC-BY-4.0",
        field: "",
    }

    _refused(
        "articles_article_written_in_full", lambda: Article.objects.create(author=author, **values)
    )


def test_the_database_refuses_an_unknown_licence(author: User) -> None:
    _refused(
        "articles_article_licence_known",
        lambda: Article.objects.create(
            author=author,
            author_name="TEST",
            title="TEST",
            summary="TEST",
            body="TEST",
            licence="CC-BY-NC-4.0",
        ),
    )


def test_the_database_refuses_an_unknown_decision(article: Article, reviewer: User) -> None:
    _refused("articles_decision_known", lambda: _decide(article, reviewer, "approved"))


@pytest.mark.parametrize("decision", ["declined", "withdrawn"])
def test_a_decline_or_a_withdrawal_needs_a_reason(
    article: Article, reviewer: User, decision: str
) -> None:
    _refused(
        "articles_decision_reason_unless_published",
        lambda: _decide(article, reviewer, decision, reason=""),
    )


def test_an_article_has_one_verdict(article: Article, reviewer: User) -> None:
    _decide(article, reviewer, "published", reason="")

    _refused("articles_decision_one_verdict", lambda: _decide(article, reviewer, "declined"))
    _refused(
        "articles_decision_one_verdict", lambda: _decide(article, reviewer, "published", reason="")
    )


def test_an_article_has_one_withdrawal(article: Article, reviewer: User) -> None:
    _decide(article, reviewer, "published", reason="")
    _decide(article, reviewer, "withdrawn")

    _refused("articles_decision_one_withdrawal", lambda: _decide(article, reviewer, "withdrawn"))


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE articles_article SET body = 'TEST changed' WHERE id = %s",
        "DELETE FROM articles_article WHERE id = %s",
    ],
)
def test_an_article_is_never_changed_or_deleted(article: Article, statement: str) -> None:
    with (
        pytest.raises(IntegrityError, match="articles_article is append-only"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(statement, [article.pk])


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE articles_articledecision SET reason = 'TEST changed' WHERE id = %s",
        "DELETE FROM articles_articledecision WHERE id = %s",
    ],
)
def test_a_decision_is_never_changed_or_deleted(
    article: Article, reviewer: User, statement: str
) -> None:
    decision = _decide(article, reviewer, "declined")

    with (
        pytest.raises(IntegrityError, match="articles_articledecision is append-only"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(statement, [decision.pk])


def test_the_status_is_derived_from_the_latest_decision() -> None:
    assert status_of([]) == "awaiting_review"
    assert status_of(["published"]) == "published"
    assert status_of(["declined"]) == "declined"
    assert status_of(["published", "withdrawn"]) == "withdrawn"
