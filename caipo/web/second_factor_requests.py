"""Pages on which an Administrator decides on other accounts' enrolment requests (ADR-0014).

These views handle the request and nothing else. Who may decide, on which
requests, and what is recorded are decided by `caipo.accounts`. A decision is
made by POST with a CSRF token, names the request by its number in the path,
and takes nothing else from the browser except, for an approval, the explicit
confirmation.
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
from caipo.accounts.services import MfaOutcome
from caipo.web import sessions
from caipo.web.access import requires
from caipo.web.authentication import source
from caipo.web.forms import EnrollmentApprovalForm

UNCONFIRMED_MESSAGE = _("Nothing was approved. Tick the confirmation to approve a request.")
UNAVAILABLE_MESSAGE = _(
    "That request no longer awaits a decision. It was replaced, decided, or has lapsed."
)


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
        "requests": selectors.enrollment_requests_awaiting_approval(actor),
        "error": error,
        "approval_form": EnrollmentApprovalForm(),
    }
    return render(request, "web/second_factor_requests.html", context, status=status)


def _decided(
    request: HttpRequest, actor: AuthenticationContext, outcome: MfaOutcome
) -> HttpResponse:
    if outcome != MfaOutcome.ACCEPTED:
        return _page(request, actor, error=UNAVAILABLE_MESSAGE, status=409)
    return HttpResponseRedirect(reverse("second-factor-requests"))


@requires(Permission.MFA_ENROLLMENT_APPROVE)
@never_cache
@require_GET
def overview(request: HttpRequest) -> HttpResponse:
    """List the enrolment requests that await a decision."""
    return _page(request, _actor(request))


@requires(Permission.MFA_ENROLLMENT_APPROVE)
@never_cache
@csrf_protect
@require_POST
def approve(request: HttpRequest, number: int) -> HttpResponse:
    """Approve one request, if the approval was explicitly confirmed."""
    actor = _actor(request)
    if not EnrollmentApprovalForm(request.POST).is_valid():
        return _page(request, actor, error=UNCONFIRMED_MESSAGE, status=400)
    result = services.approve_mfa_enrollment(
        actor=actor, request_number=number, source=source(request)
    )
    return _decided(request, actor, result.outcome)


@requires(Permission.MFA_ENROLLMENT_APPROVE)
@never_cache
@csrf_protect
@require_POST
def reject(request: HttpRequest, number: int) -> HttpResponse:
    """Reject one request, discarding its secret."""
    actor = _actor(request)
    result = services.reject_mfa_enrollment(
        actor=actor, request_number=number, source=source(request)
    )
    return _decided(request, actor, result.outcome)
