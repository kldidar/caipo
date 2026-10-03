"""The two pages on which the owner of an account replaces a forgotten password
(ADR-0016): one takes an email address and asks for a message, the other takes
the token from that message and a new password.

The views handle the request and nothing else. Which accounts can be reset,
whether a request or a token is throttled, whether a token is good, and what
is recorded are decided by `caipo.accounts.services`.

The token is never part of a URL that reaches this server. As for activation,
the link in the message carries it after a `#`, a small script moves it from
there into the form, and the form sends it in the body of a POST. Nothing is
read from a query string.
"""

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from caipo.accounts import services
from caipo.accounts.services import PasswordResetOutcome
from caipo.web.access import public
from caipo.web.authentication import source
from caipo.web.forms import PasswordResetForm, PasswordResetRequestForm

INVALID_EMAIL_MESSAGE = _("Enter a valid email address.")
INCOMPLETE_MESSAGE = _("Fill in the reset code and the new password, twice.")
# One message for a token that is unknown, malformed, used, replaced, or
# lapsed, and for an account that is not active.
REFUSED_MESSAGE = _(
    "That code was not accepted. It may have been used already or have lapsed."
    " Ask for a new message."
)
THROTTLED_MESSAGE = _("Too many attempts were refused. Wait a while and try again.")
RESET_QUERY = "reset"


def reset_url(token: str) -> str:
    """Return the address a password reset message carries for a token.

    Built from the configured address of the site, never from a request. The
    token follows a `#`, so opening the link does not send it anywhere.
    """
    return f"{settings.PUBLIC_BASE_URL}{reverse('password-reset-confirm')}#{token}"


@public
@sensitive_post_parameters("email")
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def request_reset(request: HttpRequest) -> HttpResponse:
    """Show the form that asks for a reset message, and take the request on POST.

    Public: whoever reaches it cannot sign in. Every request with a
    well-formed email address gets the same answer, whether or not the
    address has an account and whether or not the request was throttled.
    Nothing that was submitted is put back into the page: people type
    passwords into email fields.
    """
    error = None
    requested = False

    if request.method == "POST":
        form = PasswordResetRequestForm(request.POST)
        if form.is_valid():
            services.request_password_reset(
                email=form.cleaned_data["email"], source=source(request), reset_url=reset_url
            )
            requested = True
        else:
            error = INVALID_EMAIL_MESSAGE

    context = {"form": PasswordResetRequestForm(), "error": error, "requested": requested}
    return render(request, "web/password_reset_request.html", context)


@public
@sensitive_post_parameters("token", "password", "password_again")
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def confirm_reset(request: HttpRequest) -> HttpResponse:
    """Show the form that sets a new password, and set it on POST.

    Public: whoever reaches it cannot sign in. It answers the same way
    whoever asks and whatever account a token belongs to, and signs nobody
    in: after a reset the person goes to the sign-in page like anyone else.

    A token is never shown in the page. It is kept across a response in one
    case only: the service found it good and refused the password. Then it
    is carried in a hidden field, so that its holder can try another
    password without opening the link again. Whatever else was submitted in
    that field is not put back at all.
    """
    status = 200
    errors: tuple[str, ...] = ()
    form = PasswordResetForm()

    if request.method == "POST":
        submitted = PasswordResetForm(request.POST)
        if submitted.is_valid():
            result = services.reset_password(
                token=submitted.cleaned_data["token"],
                password=submitted.cleaned_data["password"],
                source=source(request),
            )
            if result.outcome == PasswordResetOutcome.RESET:
                return HttpResponseRedirect(f"{reverse('login')}?{RESET_QUERY}=1")
            if result.outcome == PasswordResetOutcome.PASSWORD_REFUSED:
                form = PasswordResetForm.carrying(submitted.cleaned_data["token"])
                errors = result.password_errors
            elif result.outcome == PasswordResetOutcome.THROTTLED:
                status, errors = 429, (str(THROTTLED_MESSAGE),)
            else:
                errors = (str(REFUSED_MESSAGE),)
        else:
            errors = tuple(str(error) for error in submitted.non_field_errors()) or (
                str(INCOMPLETE_MESSAGE),
            )

    context = {"form": form, "errors": errors}
    return render(request, "web/password_reset.html", context, status=status)
