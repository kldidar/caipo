"""Asking for a lost second factor to be recovered, from a sign-in that awaits its code (ADR-0017).

This view handles the request and the session and nothing else. Whether the
submission is accepted, refused, or throttled, and what is recorded, are
decided by `caipo.accounts.services`.

A request is made from a sign-in that awaits its code. The account it is for
is the one the pending challenge was issued to, and the challenge is held on
the server: nothing the browser sends can name an account or a challenge.
"""

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from caipo.accounts import services
from caipo.accounts.services import RecoveryRequestOutcome
from caipo.web import sessions
from caipo.web.access import public
from caipo.web.authentication import source
from caipo.web.forms import SecondFactorCodeForm

# One message for a sign-in that took too long or was completed elsewhere,
# and for an account that this request is not for.
REFUSED_MESSAGE = _("The request was not accepted. Enter a code, or sign in again.")
# One message for every limit.
THROTTLED_MESSAGE = _("Too many recovery requests. Wait a while and try again.")


@public
@never_cache
@csrf_protect
@require_POST
def request_recovery(request: HttpRequest) -> HttpResponse:
    """Ask for the lost second factor of the pending sign-in's account to be recovered.

    Public: whoever reaches it is not signed in. Without a pending sign-in in
    the session there is nothing to ask about, and the visitor is sent to the
    sign-in page, as on the page that takes the code. POST only, with a CSRF
    token, and nothing else is read from the request.

    Nobody is signed in by it. A request that is accepted uses up the pending
    sign-in; one that is refused or throttled leaves the session as it was.
    """
    pending = sessions.pending_sign_in(request)
    if pending is None:
        return HttpResponseRedirect(reverse("login"))

    result = services.request_mfa_recovery(challenge=pending.challenge, source=source(request))
    if result.outcome == RecoveryRequestOutcome.REQUESTED and result.number is not None:
        # The challenge is gone, so the session has nothing left to wait for.
        sessions.end_pending_sign_in(request)
        context = {
            "number": result.number,
            "lifetime_minutes": int(settings.MFA_RECOVERY_REQUEST_LIFETIME.total_seconds() // 60),
        }
        return render(request, "web/recovery_requested.html", context)

    if result.outcome == RecoveryRequestOutcome.THROTTLED:
        status, error = 429, THROTTLED_MESSAGE
    else:
        status, error = 200, REFUSED_MESSAGE
    return render(
        request,
        "web/verify_second_factor.html",
        {"form": SecondFactorCodeForm(), "error": error},
        status=status,
    )
