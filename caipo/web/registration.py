"""The page on which somebody registers an account for themselves (ADR-0021).

The view handles the request and nothing else. Whether a registration creates
an account, sends a message, or is throttled, and what is recorded, are
decided by `caipo.accounts.services.register_account`. A registered account
holds the Reader role and nothing more. Its owner verifies the address and
chooses a password on the activation page, as for an account an
Administrator creates.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from caipo.accounts import services
from caipo.web.access import public
from caipo.web.activation import activation_url
from caipo.web.authentication import source
from caipo.web.forms import RegistrationForm

INVALID_EMAIL_MESSAGE = _("Enter a valid email address.")


@public
@sensitive_post_parameters("email")
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def register(request: HttpRequest) -> HttpResponse:
    """Show the registration form, and take the registration on POST.

    Public: whoever registers is not signed in. Every registration with a
    well-formed email address gets the same answer, whether or not the
    address has an account and whether or not the registration was
    throttled. Nothing that was submitted is put back into the page.
    """
    error = None
    registered = False

    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            try:
                services.register_account(
                    email=form.cleaned_data["email"],
                    source=source(request),
                    activation_url=activation_url,
                )
            except ValidationError:
                error = INVALID_EMAIL_MESSAGE
            else:
                registered = True
        else:
            error = INVALID_EMAIL_MESSAGE

    context = {
        "form": RegistrationForm(),
        "error": error,
        "registered": registered,
        # Development writes messages to files instead of sending them
        # (ADR-0015 point 30), so the page says where to look.
        "outbox": settings.DEBUG,
    }
    return render(request, "web/register.html", context)
