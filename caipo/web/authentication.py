"""Sign-in and sign-out pages.

These views handle the request and the session and nothing else. Whether the
credentials are right, whether the attempt is throttled, and what is recorded
are decided by `caipo.accounts.services`.
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

from caipo.accounts import services
from caipo.accounts.services import SignInOutcome
from caipo.web.access import public
from caipo.web.forms import SignInForm

NEXT_FIELD = "next"

# One message for a wrong password, an unknown email address, and a
# deactivated account.
REFUSED_MESSAGE = _("The email address or password is not correct.")
THROTTLED_MESSAGE = _("Too many sign-in attempts. Wait a while and try again.")


def _source(request: HttpRequest) -> str:
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
    status = 200
    error = None

    if request.method == "POST":
        form = SignInForm(request.POST)
        if form.is_valid():
            result = services.sign_in(
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password"],
                source=_source(request),
            )
            if result.outcome == SignInOutcome.SIGNED_IN and result.user is not None:
                # Replaces the session key, so that a key known before
                # signing in is worth nothing afterwards.
                login(request, result.user)
                return HttpResponseRedirect(_safe_destination(request, destination))
            if result.outcome == SignInOutcome.THROTTLED:
                status, error = 429, THROTTLED_MESSAGE
            else:
                error = REFUSED_MESSAGE
    else:
        form = SignInForm()

    context = {
        "form": form,
        "error": error,
        "next_field": NEXT_FIELD,
        # Only ever a path on this site, so it is safe to put back in the page.
        "next": destination if _safe_destination(request, destination) == destination else "",
    }
    return render(request, "web/sign_in.html", context, status=status)


@public
@never_cache
@csrf_protect
@require_POST
def sign_out(request: HttpRequest) -> HttpResponse:
    """End the session. POST only, so that a link or an image cannot sign anyone out.

    Public, because signing out when not signed in must be harmless, not an
    error. It always goes to the sign-in page and takes no destination.
    """
    if request.user.is_authenticated:
        services.record_sign_out(user=request.user, source=_source(request))
    # Deletes the session's data and its cookie, signed in or not.
    logout(request)
    return HttpResponseRedirect(reverse("login"))
