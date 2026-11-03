"""Contributed articles (ADR-0022): the published ones, writing one, one's own, and review.

These views handle the request and nothing else. What may be sent,
published, declined, or withdrawn, and by whom, is decided by
`caipo.articles`, which checks the permission again. An article's text is
shown escaped, with its line breaks, and never as HTML.
"""

import uuid

from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_safe

from caipo.accounts import selectors as accounts_selectors
from caipo.accounts.selectors import Permission
from caipo.articles import selectors, services
from caipo.articles.models import ArticleLicence
from caipo.articles.selectors import ArticleDecisionType
from caipo.web.access import requires
from caipo.web.workspace import FORM_ERROR, REFUSED, actor_of
from caipo.web.workspace_forms import ArticleDecisionForm, ArticleForm


@requires(Permission.WORKSPACE_READ)
@never_cache
@require_safe
def articles(request: HttpRequest) -> HttpResponse:
    """List the published articles, with the ways to write and to review one."""
    actor = actor_of(request)
    can_review = accounts_selectors.can(actor, Permission.ARTICLES_REVIEW)
    return render(
        request,
        "web/articles.html",
        {
            "entries": selectors.published_articles(actor),
            "can_write": accounts_selectors.can(actor, Permission.ARTICLES_SUBMIT),
            "can_review": can_review,
            "waiting": len(selectors.articles_awaiting_review(actor)) if can_review else 0,
        },
    )


@requires(Permission.ARTICLES_SUBMIT)
@never_cache
@csrf_protect
@require_http_methods(["GET", "HEAD", "POST"])
def article_new(request: HttpRequest) -> HttpResponse:
    """Show the form for an article, and send it for review on POST."""
    actor = actor_of(request)
    form = ArticleForm(request.POST if request.method == "POST" else None)
    error = None
    if request.method == "POST":
        if form.is_valid():
            data = form.cleaned_data
            try:
                public_id = services.submit_article(
                    actor=actor,
                    author_name=data["author_name"],
                    title=data["title"],
                    summary=data["summary"],
                    body=data["body"],
                    licence=ArticleLicence.CC_BY_4_0 if data["licence"] else "",
                )
            except REFUSED as refusal:
                error = str(refusal)
            else:
                return HttpResponseRedirect(f"{reverse('article', args=[public_id])}?sent=1")
        else:
            error = str(FORM_ERROR)
    return render(
        request,
        "web/article_new.html",
        {"form": form, "error": error},
        status=400 if error else 200,
    )


@requires(Permission.ARTICLES_SUBMIT)
@never_cache
@require_safe
def articles_mine(request: HttpRequest) -> HttpResponse:
    """List the account's own articles, in every status, with each decision's reason."""
    return render(
        request, "web/articles_mine.html", {"entries": selectors.articles_of(actor_of(request))}
    )


@requires(Permission.WORKSPACE_READ)
@never_cache
@require_safe
def article(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Show a published article, or one of the account's own in any status."""
    entry = selectors.article(actor_of(request), public_id)
    if entry is None:
        raise Http404
    return render(
        request, "web/article.html", {"article": entry, "sent": bool(request.GET.get("sent"))}
    )


@requires(Permission.ARTICLES_REVIEW)
@never_cache
@require_safe
def articles_review(request: HttpRequest) -> HttpResponse:
    """List the articles that await review, oldest first, and those already decided."""
    actor = actor_of(request)
    return render(
        request,
        "web/articles_review.html",
        {
            "waiting": selectors.articles_awaiting_review(actor),
            "decided": selectors.articles_decided(actor),
        },
    )


@requires(Permission.ARTICLES_REVIEW)
@never_cache
@csrf_protect
@require_http_methods(["GET", "HEAD", "POST"])
def article_review(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Show any article to a reviewer, and record a decision about it on POST."""
    actor = actor_of(request)
    entry = selectors.article_for_review(actor, public_id)
    if entry is None:
        raise Http404
    error = None
    if request.method == "POST":
        form = ArticleDecisionForm(request.POST)
        if form.is_valid():
            decision = form.cleaned_data["decision"]
            reason = form.cleaned_data["reason"]
            try:
                if decision == ArticleDecisionType.PUBLISHED:
                    services.publish_article(actor=actor, article_id=public_id)
                elif decision == ArticleDecisionType.DECLINED:
                    services.decline_article(actor=actor, article_id=public_id, reason=reason)
                else:
                    services.withdraw_article(actor=actor, article_id=public_id, reason=reason)
            except REFUSED as refusal:
                error = str(refusal)
            else:
                return HttpResponseRedirect(
                    f"{reverse('article-review', args=[public_id])}?decided=1"
                )
        else:
            error = str(FORM_ERROR)
    return render(
        request,
        "web/article_review.html",
        {
            "article": entry,
            "error": error,
            "decided": bool(request.GET.get("decided")),
        },
        status=400 if error else 200,
    )
