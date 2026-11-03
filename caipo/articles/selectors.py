"""Read interface of contributed articles (ADR-0022).

A published article is shown to every account that may read the workspace.
An article that is not published is shown only to its author, and to
reviewers on their own pages; to anybody else it does not exist. The reason
for a decline or a withdrawal is shown only to them too. The author is named
by the name they chose, never by their account's email address.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from caipo.accounts import selectors as accounts_selectors
from caipo.accounts.selectors import AuthenticationContext, Permission
from caipo.articles.models import (
    LICENCE_DEEDS,
    Article,
    ArticleDecisionType,
    ArticleLicence,
    ArticleStatus,
    status_of,
)

__all__ = [
    "ArticleDecisionType",
    "ArticleEntry",
    "ArticleStatus",
    "DecisionEntry",
    "article",
    "article_for_review",
    "articles_awaiting_review",
    "articles_decided",
    "articles_of",
    "published_articles",
]


@dataclass(frozen=True)
class DecisionEntry:
    decision: str
    reason: str
    decided_at: datetime

    @property
    def label(self) -> str:
        return str(ArticleDecisionType(self.decision).label)


@dataclass(frozen=True)
class ArticleEntry:
    public_id: uuid.UUID
    author_name: str
    title: str
    summary: str
    body: str
    licence: str
    submitted_at: datetime
    status: ArticleStatus
    # Only for the author and reviewers; empty for anybody else.
    decisions: tuple[DecisionEntry, ...]
    is_own: bool
    # The decisions this reader may make now: none unless a reviewer, and
    # never on their own article.
    allowed: tuple[str, ...]

    @property
    def status_label(self) -> str:
        return str(self.status.label)

    @property
    def licence_label(self) -> str:
        return str(ArticleLicence(self.licence).label)

    @property
    def licence_deed(self) -> str:
        return LICENCE_DEEDS[ArticleLicence(self.licence)]

    @property
    def latest_reason(self) -> str:
        """The reason given for the latest decision, if this reader is shown it."""
        return self.decisions[-1].reason if self.decisions else ""

    @property
    def published_at(self) -> datetime | None:
        for entry in reversed(self.decisions):
            if entry.decision == ArticleDecisionType.PUBLISHED:
                return entry.decided_at
        return None


def _entry(actor: AuthenticationContext, article: Article, *, review: bool) -> ArticleEntry:
    """Describe an article for this actor.

    `review` is true on the reviewers' pages: every decision is shown with
    its reason, and the decisions the actor may make now are offered. On the
    other pages the author sees every decision with its reason, and anybody
    else only when it was published.
    """
    decisions = sorted(article.decisions.all(), key=lambda decision: decision.pk)
    status = status_of([decision.decision for decision in decisions])
    is_own = article.author_id == actor.user.pk
    if review or is_own:
        shown = tuple(
            DecisionEntry(decision.decision, decision.reason, decision.decided_at)
            for decision in decisions
        )
    else:
        shown = tuple(
            DecisionEntry(decision.decision, "", decision.decided_at)
            for decision in decisions
            if decision.decision == ArticleDecisionType.PUBLISHED
        )
    allowed: tuple[str, ...] = ()
    if review and not is_own:
        if status == ArticleStatus.AWAITING_REVIEW:
            allowed = (ArticleDecisionType.PUBLISHED, ArticleDecisionType.DECLINED)
        elif status == ArticleStatus.PUBLISHED:
            allowed = (ArticleDecisionType.WITHDRAWN,)
    return ArticleEntry(
        public_id=article.public_id,
        author_name=article.author_name,
        title=article.title,
        summary=article.summary,
        body=article.body,
        licence=article.licence,
        submitted_at=article.submitted_at,
        status=status,
        decisions=shown,
        is_own=is_own,
        allowed=allowed,
    )


def published_articles(actor: AuthenticationContext) -> list[ArticleEntry]:
    """Every published article, most recently published first. Requires `WORKSPACE_READ`."""
    accounts_selectors.require_permission(actor, Permission.WORKSPACE_READ)
    articles = (
        Article.objects.prefetch_related("decisions")
        .filter(decisions__decision=ArticleDecisionType.PUBLISHED)
        .distinct()
    )
    entries = [_entry(actor, article, review=False) for article in articles]
    published = [entry for entry in entries if entry.status == ArticleStatus.PUBLISHED]
    return sorted(
        published, key=lambda entry: entry.published_at or entry.submitted_at, reverse=True
    )


def article(actor: AuthenticationContext, public_id: uuid.UUID) -> ArticleEntry | None:
    """One article as a reader of the workspace sees it. Requires `WORKSPACE_READ`.

    A published article is shown to every reader, and any article to its
    author. For anybody else an article that is not published does not
    exist: None.
    """
    accounts_selectors.require_permission(actor, Permission.WORKSPACE_READ)
    found = Article.objects.prefetch_related("decisions").filter(public_id=public_id).first()
    if found is None:
        return None
    entry = _entry(actor, found, review=False)
    return entry if entry.is_own or entry.status == ArticleStatus.PUBLISHED else None


def articles_of(actor: AuthenticationContext) -> list[ArticleEntry]:
    """The actor's own articles, in any status, newest first. Requires `ARTICLES_SUBMIT`."""
    accounts_selectors.require_permission(actor, Permission.ARTICLES_SUBMIT)
    articles = (
        Article.objects.prefetch_related("decisions")
        .filter(author=actor.user)
        .order_by("-submitted_at", "-id")
    )
    return [_entry(actor, article, review=False) for article in articles]


def articles_awaiting_review(actor: AuthenticationContext) -> list[ArticleEntry]:
    """Articles with no decision yet, oldest first. Requires `ARTICLES_REVIEW`."""
    accounts_selectors.require_permission(actor, Permission.ARTICLES_REVIEW)
    articles = (
        Article.objects.prefetch_related("decisions")
        .filter(decisions__isnull=True)
        .order_by("submitted_at", "id")
    )
    return [_entry(actor, article, review=True) for article in articles]


def articles_decided(actor: AuthenticationContext) -> list[ArticleEntry]:
    """Articles with a decision, most recently sent first. Requires `ARTICLES_REVIEW`."""
    accounts_selectors.require_permission(actor, Permission.ARTICLES_REVIEW)
    articles = (
        Article.objects.prefetch_related("decisions")
        .filter(decisions__isnull=False)
        .distinct()
        .order_by("-submitted_at", "-id")
    )
    return [_entry(actor, article, review=True) for article in articles]


def article_for_review(actor: AuthenticationContext, public_id: uuid.UUID) -> ArticleEntry | None:
    """Any article, with every decision and its reason. Requires `ARTICLES_REVIEW`."""
    accounts_selectors.require_permission(actor, Permission.ARTICLES_REVIEW)
    found = Article.objects.prefetch_related("decisions").filter(public_id=public_id).first()
    return None if found is None else _entry(actor, found, review=True)
