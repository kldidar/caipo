"""The page on which the owner of a new account verifies its email address and
chooses its password (ADR-0015).

The view handles the request and nothing else. Whether a token is good, whether
the attempt is throttled, and what is recorded are decided by
`caipo.accounts.services.activate_account`.

The token is never part of a URL that reaches this server. The link in the
verification message carries it after a `#`, which a browser keeps to itself:
it is in no request line, no access log, and no Referer header. A small script
moves it from there into the form, and the form sends it in the body of a
POST. Without the script the person pastes it into the same field.
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
from caipo.accounts.services import ActivationOutcome
from caipo.web.access import public
from caipo.web.authentication import source
from caipo.web.forms import ActivationForm

# One message for a token that is unknown, used, replaced, or lapsed, and for
# an account that is disabled or already active.
REFUSED_MESSAGE = _(
    "That code was not accepted. It may have been used already or have lapsed."
    " Ask an Administrator to send the message again."
)
THROTTLED_MESSAGE = _("Too many attempts were refused. Wait a while and try again.")
ACTIVATED_QUERY = "activated"


def activation_url(token: str) -> str:
    """Return the address a verification message carries for a token.

    Built from the configured address of the site, never from a request. The
    token follows a `#`, so opening the link does not send it anywhere.
    """
    return f"{settings.PUBLIC_BASE_URL}{reverse('activate')}#{token}"


@public
@sensitive_post_parameters("token", "password", "password_again")
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def activate(request: HttpRequest) -> HttpResponse:
    """Show the activation form, and activate the account on POST.

    Public: whoever reaches it has no account they can sign in to yet. It
    answers the same way whoever asks and whatever account a token belongs
    to, and signs nobody in.
    """
    status = 200
    error = None
    password_errors: tuple[str, ...] = ()

    if request.method == "POST":
        form = ActivationForm(request.POST)
        if form.is_valid():
            result = services.activate_account(
                token=form.cleaned_data["token"],
                password=form.cleaned_data["password"],
                source=source(request),
            )
            if result.outcome == ActivationOutcome.ACTIVATED:
                return HttpResponseRedirect(f"{reverse('login')}?{ACTIVATED_QUERY}=1")
            if result.outcome == ActivationOutcome.PASSWORD_REFUSED:
                password_errors = result.password_errors
            else:
                # Nothing that was submitted is put back into the page.
                form = ActivationForm()
                if result.outcome == ActivationOutcome.THROTTLED:
                    status, error = 429, THROTTLED_MESSAGE
                else:
                    error = REFUSED_MESSAGE
    else:
        form = ActivationForm()

    context = {"form": form, "error": error, "password_errors": password_errors}
    return render(request, "web/activate.html", context, status=status)
