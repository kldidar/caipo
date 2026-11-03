"""Write interface of contributed articles (ADR-0022).

Sending an article requires `ARTICLES_SUBMIT`; publishing, declining, and
withdrawing one require `ARTICLES_REVIEW`. Each operation checks its
permission first, then validates, writes, and records its audit event, in
one transaction. Articles and decisions are append-only: an article, once
sent, is never changed, and a decision is never taken back except by the
one later decision allowed, a withdrawal after publication.
"""

import logging
import uuid

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from caipo.accounts import selectors as accounts_selectors
from caipo.accounts import services as accounts_services
from caipo.accounts.selectors import AuditAction, AuditTargetType, AuthenticationContext, Permission
from caipo.articles.models import (
    Article,
    ArticleDecision,
    ArticleDecisionType,
    ArticleLicence,
    ArticleStatus,
    status_of,
)
from caipo.core.entry import InvalidEntryError, RecordNotFoundError, clean_text

logger = logging.getLogger(__name__)

# The advisory lock class under which one author's submissions are counted.
_SUBMISSION_LOCK = 22

AUTHOR_NAME_LIMIT = 120
TITLE_LIMIT = 200
SUMMARY_LIMIT = 600
BODY_LIMIT = 20000
REASON_LIMIT = 2000

# Which decision may follow which status. Nothing follows a decline or a
# withdrawal: the author sends a new article instead.
_ALLOWED = {
    ArticleStatus.AWAITING_REVIEW: {ArticleDecisionType.PUBLISHED, ArticleDecisionType.DECLINED},
    ArticleStatus.PUBLISHED: {ArticleDecisionType.WITHDRAWN},
    ArticleStatus.DECLINED: set(),
    ArticleStatus.WITHDRAWN: set(),
}


def _record(
    actor: AuthenticationContext, target_type: AuditTargetType, public_id: uuid.UUID
) -> None:
    accounts_services.record_audit_event(
        actor=actor,
        action=AuditAction.CREATED,
        target_type=target_type,
        target_public_id=public_id,
        changes=(),
    )


def submit_article(
    *,
    actor: AuthenticationContext,
    author_name: str,
    title: str,
    summary: str,
    body: str,
    licence: str,
) -> uuid.UUID:
    """Send an article for review, and return its public identifier.

    Preconditions: the actor holds `ARTICLES_SUBMIT`; the licence is one the
    author accepts by sending (CC BY 4.0); the author's name, title,
    summary, and text are not empty and within their limits; the actor sent
    fewer than ARTICLE_SUBMISSION_LIMIT articles within
    ARTICLE_SUBMISSION_WINDOW.

    Side effects: one Article and one `created` audit event in one
    transaction; a log line after it commits. The article awaits review and
    is shown to nobody but its author and reviewers until it is published.

    Raises PermissionDenied before anything else is examined, and
    InvalidEntryError for anything else refused. Nothing is stored in either
    case.
    """
    accounts_selectors.require_permission(actor, Permission.ARTICLES_SUBMIT)
    if licence not in ArticleLicence.values:
        raise InvalidEntryError(
            _("An article is sent only under the licence it is published with, CC BY 4.0.")
        )
    fields = {
        "author_name": clean_text(
            author_name, field=_("author's name"), max_length=AUTHOR_NAME_LIMIT
        ),
        "title": clean_text(title, field=_("title"), max_length=TITLE_LIMIT),
        "summary": clean_text(summary, field=_("summary"), max_length=SUMMARY_LIMIT),
        "body": clean_text(body, field=_("text"), max_length=BODY_LIMIT),
    }
    with transaction.atomic():
        # One submission at a time for an author, so that the count is exact.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)", [_SUBMISSION_LOCK, actor.user.pk]
            )
        since = timezone.now() - settings.ARTICLE_SUBMISSION_WINDOW
        recent = Article.objects.filter(author=actor.user, submitted_at__gte=since).count()
        if recent >= settings.ARTICLE_SUBMISSION_LIMIT:
            raise InvalidEntryError(
                _("You have sent %(limit)d articles within a day. Wait before sending another.")
                % {"limit": settings.ARTICLE_SUBMISSION_LIMIT}
            )
        article = Article.objects.create(author=actor.user, licence=licence, **fields)
        _record(actor, AuditTargetType.ARTICLE, article.public_id)
    logger.info(
        "Article sent for review",
        extra={
            "event": "articles.submitted",
            "public_id": str(article.public_id),
            "actor_id": actor.user.pk,
        },
    )
    return article.public_id


def publish_article(*, actor: AuthenticationContext, article_id: uuid.UUID) -> None:
    """Publish an article that awaits review. See `_decide`."""
    _decide(actor, article_id, ArticleDecisionType.PUBLISHED, "")


def decline_article(*, actor: AuthenticationContext, article_id: uuid.UUID, reason: str) -> None:
    """Decline an article that awaits review, with the reason its author is shown. See `_decide`."""
    _decide(actor, article_id, ArticleDecisionType.DECLINED, reason)


def withdraw_article(*, actor: AuthenticationContext, article_id: uuid.UUID, reason: str) -> None:
    """Stop showing a published article, with the reason its author is shown. See `_decide`."""
    _decide(actor, article_id, ArticleDecisionType.WITHDRAWN, reason)


def _decide(
    actor: AuthenticationContext,
    article_id: uuid.UUID,
    decision: ArticleDecisionType,
    reason: str,
) -> None:
    """Record a reviewer's decision about another account's article.

    Preconditions: the actor holds `ARTICLES_REVIEW`; the article exists and
    is not the actor's own; the decision may follow the article's status (a
    verdict on an article that awaits review, a withdrawal of a published
    one); a decline or a withdrawal gives a reason.

    Side effects: one ArticleDecision and one `created` audit event in one
    transaction, holding the article's row lock, so that two reviewers
    deciding at once cannot both give a verdict; a log line after it
    commits.

    Raises PermissionDenied before anything else is examined;
    RecordNotFoundError if there is no such article; InvalidEntryError for
    anything else refused. Nothing is stored in either case.
    """
    accounts_selectors.require_permission(actor, Permission.ARTICLES_REVIEW)
    required = decision != ArticleDecisionType.PUBLISHED
    clean_reason = clean_text(reason, field=_("reason"), max_length=REASON_LIMIT, required=required)
    with transaction.atomic():
        article = Article.objects.select_for_update().filter(public_id=article_id).first()
        if article is None:
            raise RecordNotFoundError(_("There is no such article."))
        if article.author_id == actor.user.pk:
            raise InvalidEntryError(_("Nobody decides about their own article."))
        status = status_of(
            list(article.decisions.order_by("id").values_list("decision", flat=True))
        )
        if decision not in _ALLOWED[status]:
            raise InvalidEntryError(
                _("This article is %(status)s, so it cannot be %(decision)s now.")
                % {"status": status.label.lower(), "decision": decision.label.lower()}
            )
        made = ArticleDecision.objects.create(
            article=article, decision=decision, reason=clean_reason, decided_by=actor.user
        )
        _record(actor, AuditTargetType.ARTICLE_DECISION, made.public_id)
    logger.info(
        "Article decision recorded",
        extra={
            "event": f"articles.{decision.value}",
            "public_id": str(article.public_id),
            "decision_id": made.pk,
            "actor_id": actor.user.pk,
        },
    )
