"""The demonstrator's assistants (ADR-0025): the research assistant's page, and the help panel.

The view takes the question and shows what the pipeline returns: verified
statements only, each with its evidence as the server holds it, or why there
is no answer. A model's words are shown escaped, never as HTML, and no link
comes from a model: every link leads to a record of this site.
"""

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from caipo.accounts.selectors import Permission
from caipo.assistant import selectors, services
from caipo.assistant.selectors import AssistantKind, AssistantLabel, EvidenceKind, UncertaintyFlag
from caipo.assistant.services import QuotaExceededError
from caipo.indicators.selectors import ObservationStatus
from caipo.retrieval import selectors as retrieval_selectors
from caipo.web.access import requires
from caipo.web.workspace import FORM_ERROR, REFUSED, actor_of
from caipo.web.workspace_forms import QuestionForm

if TYPE_CHECKING:
    from caipo.assistant.pipeline import Answer, SourceShown

# Why an answer has no statement, by the reason the pipeline recorded.
_STOPPED: dict[str, str | Promise] = {
    "no_evidence": _(
        "Nothing held answers this question. The research assistant answers only from the"
        " reference observations and the demonstration texts, never from a model's general"
        " knowledge."
    ),
    "nothing_verified": _(
        "No statement could be checked against the evidence, so none is shown. The question may"
        " ask for something the evidence does not hold."
    ),
    "not_configured": _("The assistant is not configured on this instance."),
    "rate_limited": _("The model provider is busy. Try again in a minute."),
}
_TIMED_OUT = _("The answer took too long and was stopped. Nothing is shown. Try again later.")
_FAILED = _("The assistant could not answer just now, and nothing is shown. Try again later.")
_QUOTA = {
    "account": _("You have asked as many questions as one account may today. Try again tomorrow."),
    "instance": _("This site has answered as many questions as it may today. Try again tomorrow."),
}


@dataclass(frozen=True)
class EvidenceShown:
    kind: str | Promise
    title: str
    detail: str
    quote: str
    status: str | Promise
    url: str
    synthetic: bool


@dataclass(frozen=True)
class StatementShown:
    text: str
    label: str | Promise
    flags: tuple[str | Promise, ...]
    evidence: tuple[EvidenceShown, ...]


@dataclass(frozen=True)
class AnswerShown:
    answered: bool
    message: str | Promise
    statements: tuple[StatementShown, ...]
    searched: str


def _url(kind: str, record: uuid.UUID | None) -> str:
    if record is None:
        return ""
    if kind == EvidenceKind.OBSERVATION:
        return reverse("indicator", args=[record])
    return reverse("source", args=[record])


def _evidence(source: SourceShown) -> EvidenceShown:
    return EvidenceShown(
        kind=EvidenceKind(source.kind).label,
        title=source.title,
        detail=source.detail,
        # A recorded gap has no value; the page says so in its own words.
        quote="" if source.status == ObservationStatus.MISSING else source.quote,
        status=ObservationStatus(source.status).label if source.status else "",
        url=_url(source.kind, source.record),
        synthetic=source.kind == EvidenceKind.SEGMENT,
    )


def _shown(answer: Answer) -> AnswerShown:
    statements = tuple(
        StatementShown(
            text=statement.text,
            label=AssistantLabel(statement.label).label,
            flags=tuple(UncertaintyFlag(flag).label for flag in statement.flags),
            evidence=tuple(_evidence(source) for source in statement.sources),
        )
        for statement in answer.statements
    )
    answered = answer.outcome == "answered"
    if answered:
        message: str | Promise = ""
    elif answer.outcome == "timed_out":
        message = _TIMED_OUT
    else:
        message = _STOPPED.get(answer.reason, _FAILED)
    return AnswerShown(
        answered=answered,
        message=message,
        statements=statements,
        searched=str(answer.searched.get("query", "")) if answer.outcome == "abstained" else "",
    )


@requires(Permission.ASSISTANT_ASK)
@never_cache
@csrf_protect
@require_http_methods(["GET", "HEAD", "POST"])
def research_assistant(request: HttpRequest) -> HttpResponse:
    """Show the question form, and on POST the verified answer or why there is none."""
    actor = actor_of(request)
    form = QuestionForm(request.POST if request.method == "POST" else None)
    answer = None
    error: str | Promise | None = None
    status = 200
    if request.method == "POST":
        if form.is_valid():
            try:
                answer = _shown(
                    services.answer_question(
                        actor=actor,
                        assistant=AssistantKind.RESEARCH,
                        question=form.cleaned_data["question"],
                    )
                )
            except QuotaExceededError as exceeded:
                error, status = _QUOTA[exceeded.scope], 429
            except REFUSED as refusal:
                error, status = str(refusal), 400
        else:
            error, status = FORM_ERROR, 400
    return render(
        request,
        "web/assistant.html",
        {
            "form": form,
            "answer": answer,
            "error": error,
            "quotas": selectors.quotas_left(actor),
            "provider": selectors.provider_notice(),
        },
        status=status,
    )


@dataclass(frozen=True)
class HelpLink:
    title: str
    url: str


@dataclass(frozen=True)
class HelpStatement:
    text: str
    sections: tuple[HelpLink, ...]


def _help_url(page: str, section: str) -> str:
    return f"{reverse('help-page', args=[page])}#{section}"


@requires(Permission.ASSISTANT_ASK)
@never_cache
@csrf_protect
@require_http_methods(["GET", "HEAD", "POST"])
def help_ask(request: HttpRequest) -> HttpResponse:
    """Show the help assistant's form; on POST, answer from the help pages or say what they cover.

    The help panel loads the form with HTMX when it is opened, so that no page
    carries a form or a token it does not use, and gets each answer alone.
    Without script, the panel's link opens the form as a page, and the answer
    is shown on it.
    """
    actor = actor_of(request)
    in_panel = request.headers.get("HX-Request") == "true"
    provider = selectors.provider_notice()
    if request.method != "POST":
        template = "web/includes/help_form.html" if in_panel else "web/help_answer.html"
        return render(request, template, {"provider": provider, "asked": False})
    form = QuestionForm(request.POST)
    statements: tuple[HelpStatement, ...] = ()
    message: str | Promise = ""
    outside = False
    status = 200
    if form.is_valid():
        try:
            answer = services.answer_question(
                actor=actor, assistant=AssistantKind.HELP, question=form.cleaned_data["question"]
            )
        except QuotaExceededError as exceeded:
            message, status = _QUOTA[exceeded.scope], 429
        except REFUSED as refusal:
            message, status = str(refusal), 400
        else:
            statements = tuple(
                HelpStatement(
                    text=statement.text,
                    sections=tuple(
                        HelpLink(source.title, _help_url(source.help_page, source.help_section))
                        for source in statement.sources
                    ),
                )
                for statement in answer.statements
            )
            # ADR-0025 point 3: a question the help does not answer gets a
            # fixed reply that says what the help covers.
            outside = answer.outcome == "abstained"
            if answer.outcome == "timed_out":
                message = _TIMED_OUT
            elif answer.outcome == "failed":
                message = _STOPPED.get(answer.reason, _FAILED)
    else:
        message, status = FORM_ERROR, 400
    context = {
        "provider": provider,
        "asked": True,
        "statements": statements,
        "message": message,
        "outside": outside,
        "pages": [
            HelpLink(page.title, reverse("help-page", args=[page.page]))
            for page in retrieval_selectors.help_corpus()
        ],
    }
    if in_panel:
        # HTMX places only a successful response, so a refusal is sent as one;
        # its words say what happened.
        return render(request, "web/includes/help_answer.html", context)
    return render(request, "web/help_answer.html", context, status=status)
