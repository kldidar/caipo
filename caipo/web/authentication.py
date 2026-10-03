"""Sign-in, second-factor verification, and sign-out pages.

These views handle the request and the session and nothing else. Whether the
credentials or the code are right, whether the attempt is throttled, and what
is recorded are decided by `caipo.accounts.services`.

An account with a second factor is signed in by two requests. After the
password the session holds only a pending challenge, and the visitor is still
anonymous to every other view. The session becomes a signed-in one only when
the code is accepted.
"""

from django.contrib.auth import login, logout
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from caipo.accounts import selectors, services
from caipo.accounts.selectors import Permission
from caipo.accounts.services import MfaOutcome, SignInOutcome
from caipo.web import sessions
from caipo.web.access import public
from caipo.web.forms import SecondFactorCodeForm, SignInForm

NEXT_FIELD = "next"

# One message for a wrong password, an unknown email address, and a
# deactivated account.
REFUSED_MESSAGE = _("The email address or password is not correct.")
THROTTLED_MESSAGE = _("Too many sign-in attempts. Wait a while and try again.")
# One message for a wrong code, a code already used, and a sign-in that took
# too long or was completed elsewhere.
CODE_REFUSED_MESSAGE = _("The code was not accepted. Try the next code, or sign in again.")
CODE_THROTTLED_MESSAGE = _("Too many codes were refused. Wait a while and try again.")


def source(request: HttpRequest) -> str:
    """Return the address the request came from, as this process saw it.

    Deliberately not read from X-Forwarded-For or any other header: a client
    can write those. Behind a reverse proxy this is the proxy's address until
    the deployment decision says which header to trust (ADR-0008).
    """
    return str(request.META.get("REMOTE_ADDR", ""))


def _safe_destination(request: HttpRequest, candidate: str) -> str:
    """Return the candidate if it is a path on this site, and the sign-in page otherwise."""
    if candidate and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return candidate
    return reverse("login")


@public
@sensitive_post_parameters("password")
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def sign_in(request: HttpRequest) -> HttpResponse:
    """Show the sign-in page, and sign in on POST.

    Public: an anonymous visitor must be able to reach it. For someone already
    signed in, the same page shows who they are and offers to sign out.
    """
    destination = request.POST.get(NEXT_FIELD) or request.GET.get(NEXT_FIELD) or ""
    # Only ever a path on this site, so it is safe to keep and to put back in
    # the page.
    local_destination = (
        destination if _safe_destination(request, destination) == destination else ""
    )
    status = 200
    error = None

    if request.method == "POST":
        form = SignInForm(request.POST)
        if form.is_valid():
            result = services.sign_in(
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password"],
                source=source(request),
            )
            if result.outcome == SignInOutcome.SIGNED_IN and result.user is not None:
                # A sign-in that was waiting for another account's code is
                # abandoned, and the session key is replaced, so that a key
                # known before signing in is worth nothing afterwards.
                sessions.end_pending_sign_in(request)
                login(request, result.user)
                return HttpResponseRedirect(_safe_destination(request, destination))
            if (
                result.outcome == SignInOutcome.SECOND_FACTOR_REQUIRED
                and result.challenge is not None
            ):
                # Nobody is signed in yet: the session only remembers which
                # challenge the code is for.
                sessions.begin_pending_sign_in(
                    request, challenge=result.challenge, destination=local_destination
                )
                return HttpResponseRedirect(reverse("login-verify"))
            if result.outcome == SignInOutcome.THROTTLED:
                status, error = 429, THROTTLED_MESSAGE
            else:
                error = REFUSED_MESSAGE
    else:
        form = SignInForm()

    actor = sessions.authentication_context(request)
    context = {
        "form": form,
        "error": error,
        "next_field": NEXT_FIELD,
        "next": local_destination,
        "can_manage_second_factor": selectors.can(actor, Permission.MFA_MANAGE_OWN),
        "can_approve_enrollments": selectors.can(actor, Permission.MFA_ENROLLMENT_APPROVE),
        "can_create_accounts": selectors.can(actor, Permission.ACCOUNTS_CREATE),
        "activated": "activated" in request.GET,
    }
    return render(request, "web/sign_in.html", context, status=status)


@public
@sensitive_post_parameters("code")
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def verify_second_factor(request: HttpRequest) -> HttpResponse:
    """Ask for the second-factor code of a pending sign-in, and check it on POST.

    Public: whoever reaches it is not signed in yet. Without a pending sign-in
    in the session there is nothing to verify, and the visitor is sent to the
    sign-in page, whoever they are. The account the code is checked for comes
    from the challenge held on the server; the request cannot name one.
    """
    pending = sessions.pending_sign_in(request)
    if pending is None:
        return HttpResponseRedirect(reverse("login"))
    status = 200
    error = None

    if request.method == "POST":
        form = SecondFactorCodeForm(request.POST)
        if form.is_valid():
            result = services.verify_second_factor(
                challenge=pending.challenge, code=form.cleaned_data["code"], source=source(request)
            )
            if result.outcome == MfaOutcome.ACCEPTED and result.context is not None:
                sessions.end_pending_sign_in(request)
                # Replaces the session key once more: the key that carried
                # the pending state does not carry the signed-in one.
                login(request, result.context.user)
                sessions.record_verified_second_factor(request, result.context)
                return HttpResponseRedirect(_safe_destination(request, pending.destination))
            if result.outcome == MfaOutcome.THROTTLED:
                status, error = 429, CODE_THROTTLED_MESSAGE
            else:
                error = CODE_REFUSED_MESSAGE
    else:
        form = SecondFactorCodeForm()

    return render(
        request, "web/verify_second_factor.html", {"form": form, "error": error}, status=status
    )


@public
@never_cache
@csrf_protect
@require_POST
def sign_out(request: HttpRequest) -> HttpResponse:
    """End the session. POST only, so that a link or an image cannot sign anyone out.

    Public, because signing out when not signed in must be harmless, not an
    error. It also abandons a sign-in that is waiting for its second factor.
    It always goes to the sign-in page and takes no destination.
    """
    if request.user.is_authenticated:
        services.record_sign_out(user=request.user, source=source(request))
    pending = sessions.pending_sign_in(request)
    if pending is not None:
        services.cancel_second_factor_challenge(challenge=pending.challenge)
    # Deletes the session's data and its cookie, signed in or not, and with
    # them the pending state and the note of a verified second factor.
    logout(request)
    return HttpResponseRedirect(reverse("login"))
