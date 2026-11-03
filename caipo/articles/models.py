"""Contributed articles (ADR-0022).

An Article is a text that a signed-in account wrote and sent for review. It is
its author's view: not a source, not evidence, not a finding of CAIPO, and
never counted in any result. The text is the author's own, published under
the licence the author accepted when sending it. Once sent it is never
changed: a correction is a new article.

An ArticleDecision records what a reviewer decided about an article:
published, declined with a reason, or withdrawn after publication with a
reason. Whether an article awaits review, is published, was declined, or was
withdrawn is derived from its decisions and never stored.

Both are append-only.
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from caipo.core.append_only import AppendOnlyModel, AppendOnlyQuerySet


class ArticleLicence(models.TextChoices):
    """The licences an author can publish under. The project owner chose one (Q-15)."""

    CC_BY_4_0 = "CC-BY-4.0", _("Creative Commons Attribution 4.0 International (CC BY 4.0)")


# The licence's own statement of what it allows, for the link on each article.
LICENCE_DEEDS = {ArticleLicence.CC_BY_4_0: "https://creativecommons.org/licenses/by/4.0/"}


class ArticleDecisionType(models.TextChoices):
    PUBLISHED = "published", _("Published")
    DECLINED = "declined", _("Declined")
    WITHDRAWN = "withdrawn", _("Withdrawn")


class ArticleStatus(models.TextChoices):
    """What an article's decisions add up to. Derived, never stored."""

    AWAITING_REVIEW = "awaiting_review", _("Awaiting review")
    PUBLISHED = "published", _("Published")
    DECLINED = "declined", _("Declined")
    WITHDRAWN = "withdrawn", _("Withdrawn")


class Article(AppendOnlyModel):
    """A contributed article, as its author sent it. Append-only."""

    public_id = models.UUIDField(_("public identifier"), default=uuid.uuid4, editable=False)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("author"),
    )
    # The name the author chose to be credited with, as the licence requires.
    author_name = models.CharField(_("author's name"), max_length=120)
    title = models.CharField(_("title"), max_length=200)
    summary = models.CharField(_("summary"), max_length=600)
    body = models.TextField(_("text"))
    licence = models.CharField(_("licence"), max_length=16, choices=ArticleLicence)
    submitted_at = models.DateTimeField(_("sent at"), auto_now_add=True)

    objects = AppendOnlyQuerySet["Article"].as_manager()

    class Meta:
        verbose_name = _("article")
        verbose_name_plural = _("articles")
        constraints = [
            models.UniqueConstraint(fields=["public_id"], name="articles_article_public_id_unique"),
            models.CheckConstraint(
                condition=models.Q(licence__in=ArticleLicence.values),
                name="articles_article_licence_known",
            ),
            models.CheckConstraint(
                condition=~models.Q(author_name="")
                & ~models.Q(title="")
                & ~models.Q(summary="")
                & ~models.Q(body=""),
                name="articles_article_written_in_full",
            ),
        ]
        indexes = [
            # Each submission counts the author's recent ones.
            models.Index(fields=["author", "submitted_at"], name="articles_article_author"),
        ]

    def __str__(self) -> str:
        return self.title


class ArticleDecision(AppendOnlyModel):
    """A reviewer's decision about an article. Append-only.

    An article has at most one verdict, published or declined, and at most
    one withdrawal, which only follows publication. A decline or a
    withdrawal gives its reason; the order is kept by the service.
    """

    public_id = models.UUIDField(_("public identifier"), default=uuid.uuid4, editable=False)
    article = models.ForeignKey(
        Article, on_delete=models.PROTECT, related_name="decisions", verbose_name=_("article")
    )
    decision = models.CharField(_("decision"), max_length=16, choices=ArticleDecisionType)
    reason = models.TextField(_("reason"), blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("decided by"),
    )
    decided_at = models.DateTimeField(_("decided at"), auto_now_add=True)

    objects = AppendOnlyQuerySet["ArticleDecision"].as_manager()

    class Meta:
        verbose_name = _("article decision")
        verbose_name_plural = _("article decisions")
        constraints = [
            models.UniqueConstraint(
                fields=["public_id"], name="articles_decision_public_id_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(decision__in=ArticleDecisionType.values),
                name="articles_decision_known",
            ),
            models.CheckConstraint(
                condition=models.Q(decision=ArticleDecisionType.PUBLISHED) | ~models.Q(reason=""),
                name="articles_decision_reason_unless_published",
            ),
            models.UniqueConstraint(
                fields=["article"],
                condition=models.Q(
                    decision__in=[ArticleDecisionType.PUBLISHED, ArticleDecisionType.DECLINED]
                ),
                name="articles_decision_one_verdict",
            ),
            models.UniqueConstraint(
                fields=["article"],
                condition=models.Q(decision=ArticleDecisionType.WITHDRAWN),
                name="articles_decision_one_withdrawal",
            ),
        ]

    def __str__(self) -> str:
        return self.decision


def status_of(decisions: list[str]) -> ArticleStatus:
    """Return the status that an article's decisions, oldest first, add up to."""
    if not decisions:
        return ArticleStatus.AWAITING_REVIEW
    return ArticleStatus(decisions[-1])
