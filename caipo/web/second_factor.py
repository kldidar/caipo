"""Pages on which an account manages its own second factor (ADR-0014).

These views handle the request and the session and nothing else. Whether the
password and the code are right, what state the second factor is in, and what
is recorded are decided by `caipo.accounts.services`. Every change is made by
POST with a CSRF token, and none of them takes the secret, the state, or the
account from the request. Approving an enrolment is another account's business
and is in `caipo.web.second_factor_requests`.
"""

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.middleware.csrf import rotate_token
from django.shortcuts import render
from django.urls import reverse
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_POST

from caipo.accounts import selectors, services
from caipo.accounts.selectors import AuthenticationContext, Permission
from caipo.accounts.services import MfaOutcome, MfaResult, Provisioning
from caipo.web import sessions
from caipo.web.access import requires
from caipo.web.authentication import source
from caipo.web.forms import (
    DisableSecondFactorForm,
    PasswordConfirmationForm,
    SecondFactorCodeForm,
)

# One message whichever of the two proofs was wrong.
REFUSED_MESSAGE = _("That was not accepted. Check what you entered and try again.")
THROTTLED_MESSAGE = _("Too many attempts were refused. Wait a while and try again.")
UNAVAILABLE_MESSAGE = _("That is not possible in the current state. Start again from this page.")
INVALID_MESSAGE = _("Fill in every field. A code has six digits.")


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
    provisioning: Provisioning | None = None,
) -> HttpResponse:
    context = {
        "state": selectors.mfa_state_of(actor.user).value,
        # What the person tells an Administrator, so that this request and no
        # other is the one approved.
        "request_number": selectors.enrollment_request_number_of(actor.user),
        "error": error,
        # Present only in the response to the request that started the
        # enrolment. It is not kept anywhere to be shown again.
        "provisioning": provisioning,
        "password_form": PasswordConfirmationForm(),
        "code_form": SecondFactorCodeForm(),
        "disable_form": DisableSecondFactorForm(),
        "replace_form": DisableSecondFactorForm(prefix="replace"),
    }
    return render(request, "web/second_factor.html", context, status=status)


def _refusal(request: HttpRequest, actor: AuthenticationContext, result: MfaResult) -> HttpResponse:
    if result.outcome == MfaOutcome.THROTTLED:
        return _page(request, actor, error=THROTTLED_MESSAGE, status=429)
    if result.outcome == MfaOutcome.UNAVAILABLE:
        return _page(request, actor, error=UNAVAILABLE_MESSAGE, status=409)
    return _page(request, actor, error=REFUSED_MESSAGE)


@requires(Permission.MFA_MANAGE_OWN)
@never_cache
@require_GET
def overview(request: HttpRequest) -> HttpResponse:
    """Show where the account stands with its second factor, and what it can do next."""
    return _page(request, _actor(request))


@requires(Permission.MFA_MANAGE_OWN)
@sensitive_post_parameters("password")
@never_cache
@csrf_protect
@require_POST
def enrol(request: HttpRequest) -> HttpResponse:
    """Start an enrolment, and show the new secret in the response, once."""
    actor = _actor(request)
    form = PasswordConfirmationForm(request.POST)
    if not form.is_valid():
        return _page(request, actor, error=INVALID_MESSAGE)
    result = services.start_mfa_enrollment(
        actor=actor, password=form.cleaned_data["password"], source=source(request)
    )
    if result.outcome != MfaOutcome.ACCEPTED or result.provisioning is None:
        return _refusal(request, actor, result)
    return _page(request, actor, provisioning=result.provisioning)


@requires(Permission.MFA_MANAGE_OWN)
@sensitive_post_parameters("code")
@never_cache
@csrf_protect
@require_POST
def confirm(request: HttpRequest) -> HttpResponse:
    """Activate the pending enrolment with a code from the authenticator application."""
    actor = _actor(request)
    form = SecondFactorCodeForm(request.POST)
    if not form.is_valid():
        return _page(request, actor, error=INVALID_MESSAGE)
    result = services.confirm_mfa_enrollment(
        actor=actor, code=form.cleaned_data["code"], source=source(request)
    )
    if result.outcome != MfaOutcome.ACCEPTED or result.context is None:
        return _refusal(request, actor, result)
    # The session gains assurance, so it gets a new key and a new CSRF token,
    # as at sign-in.
    request.session.cycle_key()
    rotate_token(request)
    sessions.record_verified_second_factor(request, result.context)
    return HttpResponseRedirect(reverse("second-factor"))


@requires(Permission.MFA_MANAGE_OWN)
@sensitive_post_parameters("password", "code")
@never_cache
@csrf_protect
@require_POST
def disable(request: HttpRequest) -> HttpResponse:
    """Remove the account's own second factor, given its password and a current code."""
    actor = _actor(request)
    form = DisableSecondFactorForm(request.POST)
    if not form.is_valid():
        return _page(request, actor, error=INVALID_MESSAGE)
    result = services.disable_mfa(
        actor=actor,
        password=form.cleaned_data["password"],
        code=form.cleaned_data["code"],
        source=source(request),
    )
    if result.outcome != MfaOutcome.ACCEPTED:
        return _refusal(request, actor, result)
    sessions.forget_verified_second_factor(request)
    request.session.cycle_key()
    return HttpResponseRedirect(reverse("second-factor"))


@requires(Permission.MFA_MANAGE_OWN)
@sensitive_post_parameters("replace-password", "replace-code")
@never_cache
@csrf_protect
@require_POST
def replace(request: HttpRequest) -> HttpResponse:
    """Give up the account's second factor for a new one, and show the new secret, once.

    Needs the password and a current code from the device being given up. The
    session loses its note of that device, and with it whatever the device
    proved, before the new secret is shown.
    """
    actor = _actor(request)
    form = DisableSecondFactorForm(request.POST, prefix="replace")
    if not form.is_valid():
        return _page(request, actor, error=INVALID_MESSAGE)
    result = services.replace_mfa_device(
        actor=actor,
        password=form.cleaned_data["password"],
        code=form.cleaned_data["code"],
        source=source(request),
    )
    if result.outcome != MfaOutcome.ACCEPTED or result.provisioning is None:
        return _refusal(request, actor, result)
    sessions.forget_verified_second_factor(request)
    request.session.cycle_key()
    return _page(request, _actor(request), provisioning=result.provisioning)
