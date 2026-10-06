"""Pages on which an Administrator decides on other accounts' recovery requests (ADR-0017).

These views handle the request and nothing else. Who may decide, on which
requests, and what is recorded are decided by `caipo.accounts`. A decision is
made by POST with a CSRF token, names the request by its number in the path,
and takes nothing else from the browser except, for an authorisation, the
explicit confirmation.

A decision that is not made gets one answer, whatever the reason. The service
does not give the reason to these views, so they cannot show it.
"""

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from caipo.accounts import selectors, services
from caipo.accounts.selectors import AuthenticationContext, Permission
from caipo.accounts.services import RecoveryDecisionOutcome
from caipo.web import sessions
from caipo.web.access import requires
from caipo.web.authentication import source
from caipo.web.forms import RecoveryAuthorizationForm

UNCONFIRMED_MESSAGE = _("Nothing was authorised. Tick the confirmation to authorise a request.")
# One message for every decision that was not made.
UNAVAILABLE_MESSAGE = _("That request is not available. Nothing was changed.")


def _actor(request: HttpRequest) -> AuthenticationContext:
    context = sessions.authentication_context(request)
    if context is None:
        raise PermissionDenied
    return context


def _page(
    request: HttpRequest,
    actor: AuthenticationContext,
    *,
    error: Promise | None = None,
    status: int = 200,
) -> HttpResponse:
    context = {
        "requests": selectors.recovery_requests_awaiting_decision(actor),
        "error": error,
        "authorization_form": RecoveryAuthorizationForm(),
    }
    return render(request, "web/recovery_requests.html", context, status=status)


def _decided(request: HttpRequest, outcome: RecoveryDecisionOutcome) -> HttpResponse:
    if outcome == RecoveryDecisionOutcome.UNAVAILABLE:
        # Not the list with a message above it: which requests the list holds
        # depends on what happened to this one, and the answer must not.
        return render(
            request,
            "web/recovery_request_unavailable.html",
            {"error": UNAVAILABLE_MESSAGE},
            status=409,
        )
    return HttpResponseRedirect(reverse("recovery-requests"))


@requires(Permission.MFA_RECOVERY_AUTHORIZE)
@never_cache
@require_GET
def overview(request: HttpRequest) -> HttpResponse:
    """List the recovery requests that await a decision."""
    return _page(request, _actor(request))


@requires(Permission.MFA_RECOVERY_AUTHORIZE)
@never_cache
@csrf_protect
@require_POST
def authorize(request: HttpRequest, number: int) -> HttpResponse:
    """Authorise one request, if the authorisation was explicitly confirmed."""
    actor = _actor(request)
    if not RecoveryAuthorizationForm(request.POST).is_valid():
        return _page(request, actor, error=UNCONFIRMED_MESSAGE, status=400)
    result = services.authorize_mfa_recovery(
        actor=actor, request_number=number, source=source(request)
    )
    return _decided(request, result.outcome)


@requires(Permission.MFA_RECOVERY_AUTHORIZE)
@never_cache
@csrf_protect
@require_POST
def reject(request: HttpRequest, number: int) -> HttpResponse:
    """Reject one request, which removes it."""
    actor = _actor(request)
    result = services.reject_mfa_recovery(
        actor=actor, request_number=number, source=source(request)
    )
    return _decided(request, result.outcome)
